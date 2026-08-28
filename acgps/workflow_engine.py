from __future__ import annotations

from collections import Counter
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from acgps.contracts import ContractValidationError, validate_contract
from acgps.human_decisions import DecisionQueue, DecisionQueueError
from acgps.policy import PolicyEvaluationError, evaluate_policy, load_policy_bundle, validate_project_registration
from acgps.review_adapter import (
    ReviewEvidenceError,
    validate_fix_required_findings,
    validate_release_candidate_manifest,
    validate_review_findings,
)
from acgps.supervised_handoff import (
    build_supervised_coder_handoff_preview,
    build_supervised_coder_result_receipt_preview,
    build_supervised_planner_result_receipt_preview,
    build_supervised_reviewer_result_receipt_preview,
    build_supervised_verifier_result_receipt_preview,
)
from acgps.workflow_contracts import (
    canonical_json_bytes,
    validate_task_initialization_request,
    validate_transition_request,
)
from acgps.workflow_store import WorkflowStore, WorkflowStoreError, safe_state_path, write_state_atomic


class WorkflowEngineError(ValueError):
    pass


class WorkflowEngine:
    def __init__(
        self,
        policy_root: Path,
        state_root: Path,
        project_root: Path,
        profile_id: str,
        *,
        read_only: bool = False,
    ):
        self.policy_root = Path(policy_root)
        self.state_root = Path(state_root)
        self.project_root = Path(project_root)
        self.profile_id = profile_id
        self.read_only = read_only
        try:
            self.bundle = load_policy_bundle(self.policy_root)
            profile_record = self.bundle.project_profiles.get(profile_id)
            if not isinstance(profile_record, dict) or not isinstance(profile_record.get("profile"), dict):
                raise WorkflowEngineError(f"unknown project profile: {profile_id}")
            self.profile = profile_record["profile"]
            self.required_files = validate_project_registration(self.project_root, self.profile)
        except (PolicyEvaluationError, WorkflowEngineError) as exc:
            raise WorkflowEngineError(str(exc)) from exc
        project_resolved = self.project_root.resolve(strict=True)
        state_resolved = self.state_root.resolve(strict=False)
        if state_resolved == project_resolved or state_resolved.is_relative_to(project_resolved):
            raise WorkflowEngineError("state_root must remain outside the managed project root")
        self.store = WorkflowStore(self.state_root, read_only=read_only)
        self.decisions = DecisionQueue(
            self.state_root / "decisions",
            workflow_store=self.store,
            create_root=not read_only,
        )

    def intake(self, intake: dict[str, Any], *, actor: str = "PLANNER") -> dict[str, Any]:
        self._require_writable()
        try:
            validate_contract("task_intake", intake, mode="runtime")
        except ContractValidationError as exc:
            raise WorkflowEngineError(str(exc)) from exc
        if intake["project_id"] != self.profile["project_name"]:
            raise WorkflowEngineError("task intake project_id does not match the managed profile")
        token = self._task_token(intake["task_id"])
        created_at = intake["created_at_utc"]
        intake_binding = self._embedded_evidence_binding(
            binding_id=f"intake-{token}",
            evidence_kind="task_intake",
            record=intake,
            created_at_utc=created_at,
        )
        initialization = {
            "schema_version": 1,
            "initialization_id": f"init-{token}",
            "task_id": intake["task_id"],
            "project_id": intake["project_id"],
            "initial_state": "DRAFT",
            "actor": actor,
            "idempotency_key": f"intake-{token}",
            "task_intake_binding": intake_binding,
            "created_at_utc": created_at,
        }
        outcome = validate_task_initialization_request(initialization)
        if not outcome.valid:
            raise WorkflowEngineError(outcome.issues[0].message)
        event_id = f"evt-{token}-0001"
        event = {
            "schema_version": 1,
            "event_id": event_id,
            "generation": 1,
            "sequence": 1,
            "project_id": intake["project_id"],
            "task_id": intake["task_id"],
            "event_type": "TASK_CREATED",
            "actor": actor,
            "from_state": None,
            "to_state": None,
            "transition_id": None,
            "policy_evaluation_binding": None,
            "evidence_bindings": [],
            "decision_resolution_binding": None,
            "previous_event_hash": None,
            "event_hash": None,
            "created_at_utc": created_at,
            "details": {
                "audit_generation": {
                    "schema_version": 1,
                    "generation": 1,
                    "task_id": intake["task_id"],
                    "started_by_event_id": event_id,
                    "started_by_event_type": "TASK_CREATED",
                    "predecessor_generation": None,
                    "predecessor_valid_head_hash": None,
                    "quarantine_path": None,
                    "threat_model": "CORRUPTION_AND_NON_COORDINATED_TAMPER_ONLY",
                    "created_at_utc": created_at,
                }
            },
        }
        event["event_hash"] = self._canonical_sha(dict(event, event_hash=None))
        state = {
            "schema_version": 1,
            "task_id": intake["task_id"],
            "project_id": intake["project_id"],
            "current_state": "DRAFT",
            "previous_state": None,
            "last_transition_id": None,
            "audit_generation": 1,
            "audit_head_event_id": event_id,
            "audit_head_hash": event["event_hash"],
            "policy_evaluation_id": None,
            "pending_decision_id": None,
            "updated_at_utc": created_at,
        }
        try:
            self.store.commit_task_state_and_audit(event, state)
            write_state_atomic(
                safe_state_path(self.state_root, f"tasks/{intake['task_id']}/intake.json"),
                intake,
            )
        except WorkflowStoreError as exc:
            raise WorkflowEngineError(str(exc)) from exc
        return self.store.read_task_state(intake["task_id"])

    def status(self, task_id: str) -> dict[str, Any]:
        try:
            return self.store.read_task_state(task_id)
        except WorkflowStoreError as exc:
            raise WorkflowEngineError(str(exc)) from exc

    def audit(self, task_id: str) -> list[dict[str, Any]]:
        try:
            state = self.store.read_task_state(task_id)
            return self.store.read_audit_events(task_id, generation=state["audit_generation"])
        except WorkflowStoreError as exc:
            raise WorkflowEngineError(str(exc)) from exc

    def next_action_preview(self, task_id: str) -> dict[str, Any]:
        current = self.status(task_id)
        self._trusted_audit_lineage(current)
        legal_transitions = list(
            self.bundle.workflow["transitions"].get(current["current_state"], [])
        )
        pending_decision_requirement = None
        if current["current_state"] == "WAITING_HUMAN":
            pending_decision_requirement = self._pending_decision_requirement(
                current,
                legal_transitions,
            )
            legal_transitions = [
                pending_decision_requirement["required_resume_state"]
            ]
        return {
            "status": "NEXT_ACTION_PREVIEW",
            "task_id": current["task_id"],
            "project_id": current["project_id"],
            "current_state": current["current_state"],
            "audit_generation": current["audit_generation"],
            "audit_head_event_id": current["audit_head_event_id"],
            "audit_head_hash": current["audit_head_hash"],
            "pending_decision_id": current["pending_decision_id"],
            "pending_decision_requirement": pending_decision_requirement,
            "authorization_status": "NOT_EVALUATED",
            "selected_transition": None,
            "options": [
                {
                    "target_state": target,
                    "required_actor": self._required_transition_actor(
                        current["current_state"],
                        target,
                    ),
                    "evidence_contract": self._preview_evidence_contract(
                        current,
                        target,
                    ),
                }
                for target in legal_transitions
            ],
            "controls": {
                "model_execution": "NOT_STARTED",
                "process_launch": "NOT_STARTED",
                "state_write": "NOT_PERFORMED",
                "workflow_transition": "NOT_PERFORMED",
            },
        }

    def _pending_decision_requirement(
        self,
        current: dict[str, Any],
        legal_transitions: list[str],
    ) -> dict[str, Any]:
        try:
            pending_records = self.decisions.list_pending()
        except DecisionQueueError as exc:
            raise WorkflowEngineError(str(exc)) from exc
        matches = [
            record
            for record in pending_records
            if record["task_id"] == current["task_id"]
        ]
        if len(matches) != 1:
            raise WorkflowEngineError(
                "WAITING_HUMAN requires exactly one matching pending decision"
            )
        request = matches[0]
        if request["project_id"] != current["project_id"]:
            raise WorkflowEngineError(
                "pending decision project does not match WAITING_HUMAN state"
            )
        target = request["stage"]
        if target not in legal_transitions:
            raise WorkflowEngineError(
                f"pending decision target {target} is not legal from WAITING_HUMAN"
            )
        return {
            "decision_id": request["decision_id"],
            "status": request["status"],
            "required_resume_state": target,
            "allowed_option_ids": [option["id"] for option in request["options"]],
            "default_without_response": request["default_without_response"],
            "resolution_required": True,
        }

    def direct_transition_gate_preview(
        self,
        task_id: str,
        to_state: str,
        *,
        actor: str,
        evidence_paths: Iterable[Path],
        created_at_utc: str,
        risk_triggers: Iterable[str] = (),
        human_triggers: Iterable[str] = (),
        task_attributes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        current = self.status(task_id)
        if current["current_state"] == "WAITING_HUMAN":
            raise WorkflowEngineError(
                "direct transition gate preview cannot resume WAITING_HUMAN; "
                "use decision resolution-preview"
            )
        prepared = self._prepare_transition_validation(
            task_id,
            to_state,
            actor=actor,
            evidence_paths=evidence_paths,
            created_at_utc=created_at_utc,
            risk_triggers=risk_triggers,
            human_triggers=human_triggers,
            task_attributes=task_attributes,
        )
        if prepared["actual_target"] != to_state:
            raise WorkflowEngineError(
                "direct transition gate preview cannot create a WAITING_HUMAN decision"
            )
        current = prepared["current"]
        return {
            "status": "DIRECT_TRANSITION_GATE_PREVIEW",
            "task_id": current["task_id"],
            "project_id": current["project_id"],
            "current_state": current["current_state"],
            "target_state": to_state,
            "required_actor": self._required_transition_actor(
                current["current_state"],
                to_state,
            ),
            "evidence_status": "VALIDATED",
            "evidence_bindings": prepared["evidence_bindings"],
            "policy_evaluation_id": prepared["evaluation_id"],
            "policy_bundle_digest": prepared["policy_result"]["policy_bundle_digest"],
            "audit_generation": current["audit_generation"],
            "audit_head_event_id": current["audit_head_event_id"],
            "audit_head_hash": current["audit_head_hash"],
            "authorization_status": "NOT_GRANTED",
            "controls": {
                "model_execution": "NOT_STARTED",
                "process_launch": "NOT_STARTED",
                "state_write": "NOT_PERFORMED",
                "workflow_transition": "NOT_PERFORMED",
            },
        }

    def rc_ready_gate_preview(
        self,
        task_id: str,
        *,
        manifest_path: Path,
        actor: str,
        created_at_utc: str,
        risk_triggers: Iterable[str] = (),
        human_triggers: Iterable[str] = (),
        task_attributes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        prepared = self._prepare_transition_validation(
            task_id,
            "RC_READY",
            actor=actor,
            evidence_paths=[manifest_path],
            created_at_utc=created_at_utc,
            risk_triggers=risk_triggers,
            human_triggers=human_triggers,
            task_attributes=task_attributes,
        )
        if prepared["actual_target"] != "RC_READY":
            raise WorkflowEngineError(
                "RC_READY gate preview requires a direct policy-authorized RC_READY transition"
            )
        current = prepared["current"]
        manifest_binding = prepared["evidence_bindings"][0]
        return {
            "status": "RC_READY_GATE_PREVIEW",
            "task_id": current["task_id"],
            "project_id": current["project_id"],
            "current_state": current["current_state"],
            "target_state": "RC_READY",
            "required_actor": "VERIFIER",
            "evidence_status": "VALIDATED",
            "manifest_path": manifest_binding["path"],
            "manifest_sha256": manifest_binding["content_sha256"],
            "manifest_size_bytes": manifest_binding["size_bytes"],
            "audit_generation": current["audit_generation"],
            "audit_head_event_id": current["audit_head_event_id"],
            "audit_head_hash": current["audit_head_hash"],
            "authorization_status": "NOT_GRANTED",
            "controls": {
                "model_execution": "NOT_STARTED",
                "process_launch": "NOT_STARTED",
                "state_write": "NOT_PERFORMED",
                "workflow_transition": "NOT_PERFORMED",
            },
        }

    def _prepare_transition_validation(
        self,
        task_id: str,
        to_state: str,
        *,
        actor: str,
        evidence_paths: Iterable[Path],
        created_at_utc: str,
        risk_triggers: Iterable[str] = (),
        human_triggers: Iterable[str] = (),
        task_attributes: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        current = self.status(task_id)
        events = self.audit(task_id)
        sequence = len(events) + 1
        token = self._task_token(task_id)
        evaluation_id = f"eval-{token}-{sequence:04d}"
        policy_record = {
            "schema_version": 1,
            "evaluation_id": evaluation_id,
            "project_id": current["project_id"],
            "task_id": task_id,
            "input": {
                "current_state": current["current_state"],
                "risk_triggers": list(risk_triggers),
                "human_triggers": list(human_triggers),
                "task_attributes": dict(task_attributes or {}),
                "project_profile_id": self.profile_id,
            },
            "created_at_utc": created_at_utc,
        }
        policy_result = evaluate_policy(policy_record, bundle=self.bundle)
        result = policy_result["result"]
        if result["fail_closed"]:
            raise WorkflowEngineError(f"policy evaluation failed closed: {result['error_code']}")

        actual_target = "WAITING_HUMAN" if result["human_gate"] and to_state != "ABANDONED" else to_state
        if actual_target not in result["authorized_transitions"]:
            raise WorkflowEngineError(
                f"transition {current['current_state']} -> {actual_target} is not policy-authorized"
            )
        required_actor = self._required_transition_actor(
            current["current_state"],
            actual_target,
        )
        if required_actor is not None and actor != required_actor:
            raise WorkflowEngineError(f"{actual_target} requires actor {required_actor}")
        evidence_items = [Path(path) for path in evidence_paths]
        if not evidence_items:
            raise WorkflowEngineError("every accepted transition requires evidence")
        validated_evidence = self._validate_gate_evidence(actual_target, evidence_items, current)
        evidence_bindings = [
            self._path_evidence_binding(path, token, sequence, index, actual_target, created_at_utc)
            for index, path in enumerate(evidence_items, start=1)
        ]
        if validated_evidence is not None:
            bound_evidence = [
                (binding["path"], binding["size_bytes"], binding["content_sha256"])
                for binding in evidence_bindings
            ]
            if bound_evidence != validated_evidence:
                raise WorkflowEngineError(f"{actual_target} evidence changed after validation")
        if actual_target == "RC_READY":
            bound_manifest, _ = self._read_bound_evidence_json_snapshot(evidence_bindings[0])
            try:
                validate_release_candidate_manifest(
                    bound_manifest,
                    evidence_items[0],
                    expected_project_id=current["project_id"],
                    expected_task_id=current["task_id"],
                )
            except ReviewEvidenceError as exc:
                raise WorkflowEngineError(str(exc)) from exc
            self._validate_rc_verification_lineage(bound_manifest, evidence_items[0], current)
        return {
            "current": current,
            "sequence": sequence,
            "token": token,
            "evaluation_id": evaluation_id,
            "policy_result": policy_result,
            "result": result,
            "actual_target": actual_target,
            "evidence_items": evidence_items,
            "evidence_bindings": evidence_bindings,
        }

    def advance(
        self,
        task_id: str,
        to_state: str,
        *,
        actor: str,
        evidence_paths: Iterable[Path],
        created_at_utc: str,
        risk_triggers: Iterable[str] = (),
        human_triggers: Iterable[str] = (),
        task_attributes: dict[str, str] | None = None,
        decision_resolution: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_writable()
        prepared = self._prepare_transition_validation(
            task_id,
            to_state,
            actor=actor,
            evidence_paths=evidence_paths,
            created_at_utc=created_at_utc,
            risk_triggers=risk_triggers,
            human_triggers=human_triggers,
            task_attributes=task_attributes,
        )
        current = prepared["current"]
        sequence = prepared["sequence"]
        token = prepared["token"]
        evaluation_id = prepared["evaluation_id"]
        policy_result = prepared["policy_result"]
        result = prepared["result"]
        actual_target = prepared["actual_target"]
        evidence_bindings = prepared["evidence_bindings"]

        decision_binding = None
        pending_decision_id = None
        if actual_target == "WAITING_HUMAN":
            trigger_items = list(result["required_human_triggers"])
            if not trigger_items:
                raise WorkflowEngineError("WAITING_HUMAN requires a policy-defined human trigger")
            pending_decision_id = f"decision-{token}-{sequence:04d}"
            self.decisions.create(
                {
                    "schema_version": 1,
                    "decision_id": pending_decision_id,
                    "project_id": current["project_id"],
                    "task_id": task_id,
                    "stage": to_state,
                    "risk_level": result["risk_level"],
                    "trigger": trigger_items[0],
                    "question": f"Authorize transition to {to_state}?",
                    "recommended_option": "RESUME",
                    "recommendation_rationale": "Resume only within the existing bounded task.",
                    "options": [
                        {
                            "id": "RESUME",
                            "description": f"Resume at {to_state}.",
                            "benefits": ["continues the approved task"],
                            "costs": [],
                            "risks": [],
                            "reversible": True,
                        }
                    ],
                    "default_without_response": "PAUSE",
                    "evidence_paths": [binding["path"] for binding in evidence_bindings],
                    "created_at_utc": created_at_utc,
                    "status": "PENDING",
                }
            )
        elif current["current_state"] == "WAITING_HUMAN":
            if decision_resolution is None or decision_resolution.get("decision_id") != current["pending_decision_id"]:
                raise WorkflowEngineError("WAITING_HUMAN requires its matching decision resolution")
            try:
                self.decisions.validate_resolution(decision_resolution)
            except DecisionQueueError as exc:
                raise WorkflowEngineError(str(exc)) from exc
            decision_binding = {
                "schema_version": 1,
                "decision_id": decision_resolution["decision_id"],
                "project_id": decision_resolution["project_id"],
                "task_id": decision_resolution["task_id"],
                "status": decision_resolution["status"],
                "authorized_target_state": decision_resolution["resume_state"],
                "source": "embedded",
                "path": None,
                "embedded_record": decision_resolution,
                "resolution_sha256": self._canonical_sha(decision_resolution),
                "resolved_at_utc": decision_resolution["resolved_at_utc"],
            }
        elif decision_resolution is not None:
            raise WorkflowEngineError("decision resolution is only valid when resuming WAITING_HUMAN")

        policy_binding = {
            "schema_version": 1,
            "evaluation_id": evaluation_id,
            "source": "embedded",
            "path": None,
            "embedded_record": policy_result,
            "result_sha256": self._canonical_sha(policy_result),
            "policy_bundle_digest": policy_result["policy_bundle_digest"],
            "authorized_transitions": list(result["authorized_transitions"]),
            "human_gate": result["human_gate"],
            "created_at_utc": created_at_utc,
        }
        transition_id = f"tr-{token}-{sequence:04d}"
        request = {
            "schema_version": 1,
            "transition_id": transition_id,
            "task_id": task_id,
            "project_id": current["project_id"],
            "from_state": current["current_state"],
            "to_state": actual_target,
            "actor": actor,
            "idempotency_key": transition_id,
            "policy_evaluation_binding": policy_binding,
            "evidence_bindings": evidence_bindings,
            "decision_resolution_binding": decision_binding,
            "created_at_utc": created_at_utc,
        }
        outcome = validate_transition_request(request)
        if not outcome.valid:
            raise WorkflowEngineError(outcome.issues[0].message)
        event_id = f"evt-{token}-{sequence:04d}"
        event = {
            "schema_version": 1,
            "event_id": event_id,
            "generation": current["audit_generation"],
            "sequence": sequence,
            "project_id": current["project_id"],
            "task_id": task_id,
            "event_type": "TRANSITION_ACCEPTED",
            "actor": actor,
            "from_state": current["current_state"],
            "to_state": actual_target,
            "transition_id": transition_id,
            "policy_evaluation_binding": policy_binding,
            "evidence_bindings": evidence_bindings,
            "decision_resolution_binding": decision_binding,
            "previous_event_hash": current["audit_head_hash"],
            "event_hash": None,
            "created_at_utc": created_at_utc,
            "details": {},
        }
        event["event_hash"] = self._canonical_sha(dict(event, event_hash=None))
        state = {
            "schema_version": 1,
            "task_id": task_id,
            "project_id": current["project_id"],
            "current_state": actual_target,
            "previous_state": current["current_state"],
            "last_transition_id": transition_id,
            "audit_generation": current["audit_generation"],
            "audit_head_event_id": event_id,
            "audit_head_hash": event["event_hash"],
            "policy_evaluation_id": evaluation_id,
            "pending_decision_id": pending_decision_id,
            "updated_at_utc": created_at_utc,
        }
        if decision_resolution is not None:
            try:
                self.decisions.resolve(decision_resolution)
            except DecisionQueueError as exc:
                raise WorkflowEngineError(str(exc)) from exc
        try:
            self.store.commit_task_state_and_audit(event, state)
        except WorkflowStoreError as exc:
            raise WorkflowEngineError(str(exc)) from exc
        return self.status(task_id)

    def _require_writable(self) -> None:
        if self.read_only:
            raise WorkflowEngineError("read-only workflow engine cannot modify state")

    @staticmethod
    def _required_transition_actor(from_state: str, target: str) -> str | None:
        return {
            ("CLASSIFIED", "SPEC_READY"): "PLANNER",
            ("SPEC_READY", "PLAN_READY"): "PLANNER",
            ("PLAN_READY", "IMPLEMENTING"): "CODER",
            ("FIX_REQUIRED", "IMPLEMENTING"): "CODER",
            ("INTEGRATING", "FIX_REQUIRED"): "VERIFIER",
        }.get((from_state, target)) or {
            "FIX_REQUIRED": "REVIEWER",
            "INTEGRATING": "REVIEWER",
            "TASK_REVIEW": "CODER",
            "VERIFIED": "VERIFIER",
            "RC_READY": "VERIFIER",
        }.get(target)

    @staticmethod
    def _gate_evidence_kind(from_state: str, target: str) -> str:
        if (from_state, target) in {
            ("CLASSIFIED", "SPEC_READY"),
            ("SPEC_READY", "PLAN_READY"),
        }:
            return "PLANNER_RESULT"
        if (from_state, target) == ("PLAN_READY", "IMPLEMENTING"):
            return "CODER_HANDOFF"
        if (from_state, target) == ("FIX_REQUIRED", "IMPLEMENTING"):
            return "CODER_REMEDIATION_HANDOFF"
        if (from_state, target) == ("INTEGRATING", "FIX_REQUIRED"):
            return "VERIFIER_RESULT"
        if from_state == "TASK_REVIEW" and target in {"FIX_REQUIRED", "INTEGRATING"}:
            return "REVIEWER_RESULT"
        if target == "FIX_REQUIRED":
            return "FIX_REQUIRED_FINDINGS"
        if target == "INTEGRATING":
            return "INTEGRATING_FINDINGS"
        if target == "TASK_REVIEW":
            return "CODER_RESULT"
        if target == "VERIFIED":
            return "VERIFIER_RESULT"
        if target == "RC_READY":
            return "RELEASE_CANDIDATE_MANIFEST"
        return "GENERIC_EVIDENCE"

    def _preview_evidence_contract(
        self,
        current: dict[str, Any],
        target: str,
    ) -> dict[str, Any]:
        def bound(
            ordered_kinds: list[str],
            *,
            minimum_count: int,
            maximum_count: int | None,
            repeatable_tail: bool = False,
        ) -> dict[str, Any]:
            return {
                "status": "BOUND_EXISTING_CONTRACT",
                "minimum_count": minimum_count,
                "maximum_count": maximum_count,
                "ordered_kinds": ordered_kinds,
                "repeatable_tail": repeatable_tail,
            }

        evidence_kind = self._gate_evidence_kind(current["current_state"], target)
        if evidence_kind == "PLANNER_RESULT":
            return bound(
                ["PLANNER_TASK_PACKET", "PLANNER_RESULT"],
                minimum_count=2,
                maximum_count=2,
            )
        if evidence_kind == "CODER_HANDOFF":
            return bound(
                ["CODER_TASK_PACKET"],
                minimum_count=1,
                maximum_count=1,
            )
        if evidence_kind == "CODER_REMEDIATION_HANDOFF":
            evidence_count = 1 + len(self._current_fix_cycle_blockers(current))
            return bound(
                ["CODER_TASK_PACKET", "CURRENT_BLOCKING_REMEDIATION_EVIDENCE"],
                minimum_count=evidence_count,
                maximum_count=evidence_count,
                repeatable_tail=True,
            )
        if evidence_kind == "VERIFIER_RESULT":
            return bound(
                ["VERIFIER_TASK_PACKET", "VERIFIER_RESULT", "VERIFICATION_RECORD"],
                minimum_count=3,
                maximum_count=None,
                repeatable_tail=True,
            )
        if evidence_kind == "REVIEWER_RESULT":
            minimum_count = 3
            if target == "INTEGRATING":
                minimum_count = 2 + max(
                    1,
                    len(self._current_fix_cycle_blocker_ids(current)),
                )
            return bound(
                ["REVIEWER_TASK_PACKET", "REVIEWER_RESULT", "REVIEW_FINDING"],
                minimum_count=minimum_count,
                maximum_count=None,
                repeatable_tail=True,
            )
        if evidence_kind == "FIX_REQUIRED_FINDINGS":
            return bound(
                ["REVIEW_FINDING"],
                minimum_count=1,
                maximum_count=None,
                repeatable_tail=True,
            )
        if evidence_kind == "INTEGRATING_FINDINGS":
            return bound(
                ["REVIEW_FINDING"],
                minimum_count=max(
                    1,
                    len(self._current_fix_cycle_blocker_ids(current)),
                ),
                maximum_count=None,
                repeatable_tail=True,
            )
        if evidence_kind == "CODER_RESULT":
            return bound(
                ["CODER_TASK_PACKET", "CODER_RESULT"],
                minimum_count=2,
                maximum_count=2,
            )
        if evidence_kind == "RELEASE_CANDIDATE_MANIFEST":
            return bound(
                ["RELEASE_CANDIDATE_MANIFEST"],
                minimum_count=1,
                maximum_count=1,
            )
        return {
            "status": "UNSPECIFIED_EXISTING_CONTRACT",
            "minimum_count": 1,
            "maximum_count": None,
            "ordered_kinds": [],
            "repeatable_tail": False,
        }

    def _validate_gate_evidence(
        self,
        target: str,
        paths: list[Path],
        current: dict[str, Any],
    ) -> list[tuple[str, int, str]] | None:
        try:
            evidence_kind = self._gate_evidence_kind(current["current_state"], target)
            if evidence_kind == "PLANNER_RESULT":
                return self._validate_planner_transition_evidence(target, paths, current)
            if evidence_kind == "CODER_HANDOFF":
                return self._validate_coder_handoff_evidence(paths, current)
            if evidence_kind == "CODER_REMEDIATION_HANDOFF":
                return self._validate_coder_remediation_handoff_evidence(paths, current)
            if evidence_kind == "VERIFIER_RESULT":
                return self._validate_verifier_transition_evidence(target, paths, current)
            if evidence_kind == "REVIEWER_RESULT":
                return self._validate_reviewer_transition_evidence(target, paths, current)
            if evidence_kind == "FIX_REQUIRED_FINDINGS":
                validate_fix_required_findings(paths)
            elif evidence_kind == "INTEGRATING_FINDINGS":
                records = validate_review_findings(paths)
                required_ids = self._current_fix_cycle_blocker_ids(current)
                closed_ids = {
                    record["finding_id"]
                    for record in records
                    if record["status"] in {"VERIFIED", "CLOSED"}
                }
                missing_ids = sorted(required_ids - closed_ids)
                if missing_ids:
                    raise WorkflowEngineError(
                        "INTEGRATING requires closed review evidence for: " + ", ".join(missing_ids)
                    )
            elif evidence_kind == "CODER_RESULT":
                return self._validate_task_review_evidence(paths, current)
            elif evidence_kind == "RELEASE_CANDIDATE_MANIFEST":
                if len(paths) != 1:
                    raise WorkflowEngineError(
                        "RC_READY requires exactly one release-candidate manifest"
                    )
                manifest, snapshot = self._read_evidence_json_snapshot(paths[0])
                if not validate_release_candidate_manifest(
                    manifest,
                    paths[0],
                    expected_project_id=current["project_id"],
                    expected_task_id=current["task_id"],
                ):
                    raise WorkflowEngineError("RC_READY requires a valid release-candidate manifest")
                self._validate_rc_verification_lineage(manifest, paths[0], current)
                return [snapshot]
        except (ContractValidationError, ReviewEvidenceError) as exc:
            raise WorkflowEngineError(str(exc)) from exc

    def _validate_rc_verification_lineage(
        self,
        manifest: dict[str, Any],
        manifest_path: Path,
        current: dict[str, Any],
    ) -> None:
        latest_verified = next(
            (
                event
                for event in reversed(self._trusted_audit_lineage(current))
                if event["to_state"] == "VERIFIED"
            ),
            None,
        )
        bindings = latest_verified.get("evidence_bindings") if latest_verified else None
        if not isinstance(bindings, list) or len(bindings) < 3:
            raise WorkflowEngineError(
                "RC_READY requires the latest VERIFIED audit evidence lineage"
            )

        packet, _ = self._read_bound_canonical_evidence_json(bindings[0])
        agent_result, _ = self._read_bound_canonical_evidence_json(bindings[1])
        self._validate_verifier_result_binding(packet, agent_result, "VERIFIED", current)

        verified_snapshots: list[tuple[str, int, str]] = []
        for binding in bindings[2:]:
            record, snapshot = self._read_bound_evidence_json_snapshot(binding)
            validate_contract("verification_record", record, mode="runtime")
            if record["recommendation"] == "VERIFIED":
                verified_snapshots.append(snapshot)

        manifest_snapshots = [
            self._read_evidence_json_snapshot(
                manifest_path.parent / relative_path
            )[1]
            for relative_path in manifest["verification_records"]
        ]
        if Counter(manifest_snapshots) != Counter(verified_snapshots):
            raise WorkflowEngineError(
                "RC_READY manifest verification records must exactly match "
                "the latest VERIFIED audit evidence"
            )

    def _validate_planner_transition_evidence(
        self,
        target: str,
        paths: list[Path],
        current: dict[str, Any],
    ) -> list[tuple[str, int, str]]:
        if len(paths) != 2:
            raise WorkflowEngineError(
                f"{target} requires the canonical PLANNER packet and result as exactly two evidence files"
            )
        packet, packet_snapshot = self._read_canonical_evidence_json(paths[0])
        agent_result, result_snapshot = self._read_canonical_evidence_json(paths[1])
        try:
            build_supervised_planner_result_receipt_preview(packet, agent_result)
        except (ContractValidationError, ValueError) as exc:
            raise WorkflowEngineError(str(exc)) from exc
        if (
            packet["project_id"] != current["project_id"]
            or packet["task_id"] != current["task_id"]
        ):
            raise WorkflowEngineError(
                "PLANNER packet project_id and task_id must match the current task"
            )
        if agent_result["status"] not in {"DONE", "DONE_WITH_CONCERNS"}:
            raise WorkflowEngineError(f"{target} requires a completed PLANNER result")
        if agent_result["recommended_next_state"] != target:
            raise WorkflowEngineError(f"PLANNER result must recommend {target}")
        return [packet_snapshot, result_snapshot]

    def _validate_coder_handoff_evidence(
        self,
        paths: list[Path],
        current: dict[str, Any],
    ) -> list[tuple[str, int, str]]:
        if len(paths) != 1:
            raise WorkflowEngineError(
                "IMPLEMENTING requires the canonical CODER packet as exactly one evidence file"
            )
        packet, packet_snapshot = self._read_canonical_evidence_json(paths[0])
        try:
            build_supervised_coder_handoff_preview(packet)
        except (ContractValidationError, ValueError) as exc:
            raise WorkflowEngineError(str(exc)) from exc
        if (
            packet["project_id"] != current["project_id"]
            or packet["task_id"] != current["task_id"]
        ):
            raise WorkflowEngineError(
                "CODER packet project_id and task_id must match the current task"
            )
        self._validate_coder_packet_against_frozen_plan(
            packet,
            current,
            require_latest_transition=True,
        )
        return [packet_snapshot]

    def _validate_coder_packet_against_frozen_plan(
        self,
        packet: dict[str, Any],
        current: dict[str, Any],
        *,
        require_latest_transition: bool,
    ) -> None:
        events = self._trusted_audit_lineage(current)
        transitions = [
            event for event in events if event["event_type"] == "TRANSITION_ACCEPTED"
        ]
        if require_latest_transition:
            plan_boundary = transitions[-1] if transitions else None
        else:
            plan_boundary = next(
                (
                    event
                    for event in reversed(transitions)
                    if event["from_state"] == "SPEC_READY"
                    and event["to_state"] == "PLAN_READY"
                ),
                None,
            )
        if (
            plan_boundary is None
            or plan_boundary["from_state"] != "SPEC_READY"
            or plan_boundary["to_state"] != "PLAN_READY"
        ):
            raise WorkflowEngineError(
                "IMPLEMENTING requires the current frozen SPEC_READY to PLAN_READY boundary"
            )
        planner_bindings = plan_boundary["evidence_bindings"]
        if len(planner_bindings) != 2:
            raise WorkflowEngineError(
                "IMPLEMENTING requires the frozen PLAN_READY PLANNER packet and result"
            )
        planner_packet, _ = self._read_bound_canonical_evidence_json(
            planner_bindings[0]
        )
        planner_result, _ = self._read_bound_canonical_evidence_json(
            planner_bindings[1]
        )
        try:
            build_supervised_planner_result_receipt_preview(
                planner_packet,
                planner_result,
            )
        except (ContractValidationError, ValueError) as exc:
            raise WorkflowEngineError(str(exc)) from exc
        if (
            planner_packet["project_id"] != current["project_id"]
            or planner_packet["task_id"] != current["task_id"]
            or planner_result["status"] not in {"DONE", "DONE_WITH_CONCERNS"}
            or planner_result["recommended_next_state"] != "PLAN_READY"
        ):
            raise WorkflowEngineError(
                "IMPLEMENTING requires the accepted frozen PLAN_READY PLANNER boundary"
            )

        expected_packet = dict(planner_packet)
        expected_packet["packet_id"] = f"{current['task_id']}-coder-v1"
        expected_packet["role"] = "CODER"
        if packet != expected_packet:
            raise WorkflowEngineError(
                "CODER packet must preserve the frozen PLAN_READY task boundary"
            )

    def _validate_coder_remediation_handoff_evidence(
        self,
        paths: list[Path],
        current: dict[str, Any],
    ) -> list[tuple[str, int, str]]:
        if len(paths) < 2:
            raise WorkflowEngineError(
                "FIX_REQUIRED to IMPLEMENTING requires the canonical CODER packet "
                "followed by current blocking review findings"
            )
        packet, packet_snapshot = self._read_canonical_evidence_json(paths[0])
        try:
            build_supervised_coder_handoff_preview(packet)
        except (ContractValidationError, ValueError) as exc:
            raise WorkflowEngineError(str(exc)) from exc
        if (
            packet["project_id"] != current["project_id"]
            or packet["task_id"] != current["task_id"]
        ):
            raise WorkflowEngineError(
                "CODER packet project_id and task_id must match the current task"
            )
        self._validate_coder_packet_against_frozen_plan(
            packet,
            current,
            require_latest_transition=False,
        )

        expected_blockers = self._current_fix_cycle_blockers(current)
        if not expected_blockers:
            raise WorkflowEngineError(
                "FIX_REQUIRED to IMPLEMENTING requires current blocking review findings"
            )
        submitted_snapshots: list[tuple[str, int, str]] = []
        for path in paths[1:]:
            record, snapshot = self._read_evidence_json_snapshot(path)
            if "finding_id" in record:
                validate_contract("review_finding", record, mode="runtime")
                valid_blocker = self._is_current_fix_blocker(record)
            elif "verification_id" in record:
                validate_contract("verification_record", record, mode="runtime")
                valid_blocker = (
                    record["project_id"] == current["project_id"]
                    and record["task_id"] == current["task_id"]
                    and self._is_current_verification_failure(record)
                )
            else:
                valid_blocker = False
            if not valid_blocker:
                raise WorkflowEngineError(
                    "FIX_REQUIRED to IMPLEMENTING requires current blocking remediation evidence"
                )
            submitted_snapshots.append(snapshot)
        expected_snapshots = [snapshot for _, snapshot in expected_blockers]
        if submitted_snapshots != expected_snapshots:
            raise WorkflowEngineError(
                "FIX_REQUIRED to IMPLEMENTING requires the exact current blocking review findings"
            )
        return [packet_snapshot, *submitted_snapshots]

    def _validate_task_review_evidence(
        self,
        paths: list[Path],
        current: dict[str, Any],
    ) -> list[tuple[str, int, str]]:
        if len(paths) != 2:
            raise WorkflowEngineError(
                "TASK_REVIEW requires the canonical CODER packet and result as exactly two evidence files"
            )
        packet, packet_snapshot = self._read_canonical_evidence_json(paths[0])
        agent_result, result_snapshot = self._read_canonical_evidence_json(paths[1])
        try:
            build_supervised_coder_result_receipt_preview(packet, agent_result)
        except (ContractValidationError, ValueError) as exc:
            raise WorkflowEngineError(str(exc)) from exc
        if (
            packet["project_id"] != current["project_id"]
            or packet["task_id"] != current["task_id"]
        ):
            raise WorkflowEngineError(
                "CODER packet project_id and task_id must match the current task"
            )
        if agent_result["status"] not in {"DONE", "DONE_WITH_CONCERNS"}:
            raise WorkflowEngineError("TASK_REVIEW requires a completed CODER result")
        if agent_result["recommended_next_state"] != "TASK_REVIEW":
            raise WorkflowEngineError("CODER result must recommend TASK_REVIEW")
        return [packet_snapshot, result_snapshot]

    def _validate_reviewer_transition_evidence(
        self,
        target: str,
        paths: list[Path],
        current: dict[str, Any],
    ) -> list[tuple[str, int, str]]:
        if len(paths) < 3:
            raise WorkflowEngineError(
                f"{target} from TASK_REVIEW requires the canonical REVIEWER packet and result "
                "followed by review findings"
            )
        packet, packet_snapshot = self._read_canonical_evidence_json(paths[0])
        agent_result, result_snapshot = self._read_canonical_evidence_json(paths[1])
        try:
            build_supervised_reviewer_result_receipt_preview(packet, agent_result)
        except (ContractValidationError, ValueError) as exc:
            raise WorkflowEngineError(str(exc)) from exc
        if (
            packet["project_id"] != current["project_id"]
            or packet["task_id"] != current["task_id"]
        ):
            raise WorkflowEngineError(
                "REVIEWER packet project_id and task_id must match the current task"
            )
        if agent_result["status"] not in {"DONE", "DONE_WITH_CONCERNS"}:
            raise WorkflowEngineError(f"{target} requires a completed REVIEWER result")
        if agent_result["recommended_next_state"] != target:
            raise WorkflowEngineError(f"REVIEWER result must recommend {target}")

        finding_paths = paths[2:]
        if target == "FIX_REQUIRED":
            records = validate_fix_required_findings(finding_paths)
        else:
            records = validate_review_findings(finding_paths)
            required_ids = self._current_fix_cycle_blocker_ids(current)
            closed_ids = {
                record["finding_id"]
                for record in records
                if record["status"] in {"VERIFIED", "CLOSED"}
            }
            missing_ids = sorted(required_ids - closed_ids)
            if missing_ids:
                raise WorkflowEngineError(
                    "INTEGRATING requires closed review evidence for: " + ", ".join(missing_ids)
                )

        finding_snapshots: list[tuple[str, int, str]] = []
        for path, validated_record in zip(finding_paths, records, strict=True):
            current_record, snapshot = self._read_evidence_json_snapshot(path)
            if current_record != validated_record:
                raise WorkflowEngineError(f"{target} review finding changed during validation")
            finding_snapshots.append(snapshot)
        return [packet_snapshot, result_snapshot, *finding_snapshots]

    def _validate_verifier_transition_evidence(
        self,
        target: str,
        paths: list[Path],
        current: dict[str, Any],
    ) -> list[tuple[str, int, str]]:
        if len(paths) < 3:
            raise WorkflowEngineError(
                f"{target} requires the canonical VERIFIER packet and result "
                "followed by verification records"
            )
        packet, packet_snapshot = self._read_canonical_evidence_json(paths[0])
        agent_result, result_snapshot = self._read_canonical_evidence_json(paths[1])
        self._validate_verifier_result_binding(packet, agent_result, target, current)

        accepted_recommendation = False
        boundary = (
            self._fix_cycle_integration_boundary(current)
            if target == "VERIFIED"
            else None
        )
        verification_snapshots: list[tuple[str, int, str]] = []
        for path in paths[2:]:
            record, snapshot = self._read_evidence_json_snapshot(path)
            if target == "FIX_REQUIRED":
                self._validate_fix_required_verification_record(record, current)
                accepted_recommendation = True
            else:
                validate_contract("verification_record", record, mode="runtime")
                if (
                    record["project_id"] != current["project_id"]
                    or record["task_id"] != current["task_id"]
                ):
                    raise WorkflowEngineError(
                        "verification evidence project_id and task_id must match the current task"
                    )
                if record["recommendation"] == "VERIFIED":
                    if (
                        boundary is not None
                        and self._utc_instant(record["verified_at_utc"]) < boundary
                    ):
                        raise WorkflowEngineError(
                            "verification evidence predates the current fix-cycle integration boundary"
                        )
                    accepted_recommendation = True
            verification_snapshots.append(snapshot)
        if not accepted_recommendation:
            if target == "VERIFIED":
                raise WorkflowEngineError("VERIFIED requires a successful verification record")
            raise WorkflowEngineError(
                "FIX_REQUIRED requires a failed verification record"
            )
        return [packet_snapshot, result_snapshot, *verification_snapshots]

    @staticmethod
    def _validate_verifier_result_binding(
        packet: dict[str, Any],
        agent_result: dict[str, Any],
        target: str,
        current: dict[str, Any],
    ) -> None:
        try:
            build_supervised_verifier_result_receipt_preview(packet, agent_result)
        except (ContractValidationError, ValueError) as exc:
            raise WorkflowEngineError(str(exc)) from exc
        if (
            packet["project_id"] != current["project_id"]
            or packet["task_id"] != current["task_id"]
        ):
            raise WorkflowEngineError(
                "VERIFIER packet project_id and task_id must match the current task"
            )
        if agent_result["status"] not in {"DONE", "DONE_WITH_CONCERNS"}:
            raise WorkflowEngineError(f"{target} requires a completed VERIFIER result")
        if agent_result["recommended_next_state"] != target:
            raise WorkflowEngineError(f"VERIFIER result must recommend {target}")

    @classmethod
    def _validate_fix_required_verification_record(
        cls,
        record: dict[str, Any],
        current: dict[str, Any],
    ) -> None:
        validate_contract("verification_record", record, mode="runtime")
        if (
            record["project_id"] != current["project_id"]
            or record["task_id"] != current["task_id"]
        ):
            raise WorkflowEngineError(
                "verification evidence project_id and task_id must match the current task"
            )
        if record["recommendation"] != "FIX_REQUIRED":
            raise WorkflowEngineError(
                "FIX_REQUIRED requires every verification record to recommend FIX_REQUIRED"
            )
        if not cls._is_current_verification_failure(record):
            raise WorkflowEngineError(
                "FIX_REQUIRED verification evidence requires failed requirements"
            )

    @staticmethod
    def _is_current_fix_blocker(record: dict[str, Any]) -> bool:
        return (
            record["severity"] in {"P0", "P1"}
            and record["status"] in {"OPEN", "IN_PROGRESS"}
            and record["disposition"] in {"ACCEPTED", "PARTIAL"}
        )

    @staticmethod
    def _is_current_verification_failure(record: dict[str, Any]) -> bool:
        return (
            record["recommendation"] == "FIX_REQUIRED"
            and any(
                requirement.strip()
                for requirement in record["failed_requirements"]
            )
        )

    def _current_fix_cycle_blockers(
        self,
        current: dict[str, Any],
    ) -> list[tuple[dict[str, Any], tuple[str, int, str]]]:
        blocker_records: list[tuple[dict[str, Any], tuple[str, int, str]]] = []
        for event in self._current_fix_cycle_events(current):
            if event["to_state"] != "FIX_REQUIRED":
                continue
            evidence_bindings = event["evidence_bindings"]
            finding_bindings = evidence_bindings
            if event["from_state"] == "INTEGRATING" and evidence_bindings:
                first_record, _ = self._read_bound_evidence_json_snapshot(
                    evidence_bindings[0]
                )
                if first_record.get("role") == "VERIFIER":
                    if len(evidence_bindings) < 3:
                        raise WorkflowEngineError(
                            "stored FIX_REQUIRED verifier evidence is incomplete"
                        )
                    packet, _ = self._read_bound_canonical_evidence_json(
                        evidence_bindings[0]
                    )
                    agent_result, _ = self._read_bound_canonical_evidence_json(
                        evidence_bindings[1]
                    )
                    try:
                        self._validate_verifier_result_binding(
                            packet,
                            agent_result,
                            "FIX_REQUIRED",
                            current,
                        )
                    except WorkflowEngineError as exc:
                        raise WorkflowEngineError(
                            f"stored FIX_REQUIRED verifier evidence is invalid: {exc}"
                        ) from exc
                    verification_bindings = evidence_bindings[2:]
                    event_has_blocker = False
                    for binding in verification_bindings:
                        record, snapshot = self._read_bound_evidence_json_snapshot(
                            binding
                        )
                        try:
                            self._validate_fix_required_verification_record(
                                record,
                                current,
                            )
                        except (ContractValidationError, WorkflowEngineError) as exc:
                            raise WorkflowEngineError(
                                f"stored FIX_REQUIRED verifier evidence is invalid: {exc}"
                            ) from exc
                        event_has_blocker = True
                        blocker_records.append((record, snapshot))
                    if not event_has_blocker:
                        raise WorkflowEngineError(
                            "stored FIX_REQUIRED verifier evidence has no failed requirement"
                        )
                    continue
            if event["from_state"] == "TASK_REVIEW" and evidence_bindings:
                first_record, _ = self._read_bound_evidence_json_snapshot(
                    evidence_bindings[0]
                )
                if first_record.get("role") == "REVIEWER":
                    if len(evidence_bindings) < 3:
                        raise WorkflowEngineError(
                            "stored FIX_REQUIRED reviewer evidence is incomplete"
                        )
                    packet, _ = self._read_bound_canonical_evidence_json(
                        evidence_bindings[0]
                    )
                    agent_result, _ = self._read_bound_canonical_evidence_json(
                        evidence_bindings[1]
                    )
                    try:
                        build_supervised_reviewer_result_receipt_preview(packet, agent_result)
                    except (ContractValidationError, ValueError) as exc:
                        raise WorkflowEngineError(
                            f"stored FIX_REQUIRED reviewer evidence is invalid: {exc}"
                        ) from exc
                    if (
                        packet["project_id"] != current["project_id"]
                        or packet["task_id"] != current["task_id"]
                        or agent_result["status"] not in {"DONE", "DONE_WITH_CONCERNS"}
                        or agent_result["recommended_next_state"] != "FIX_REQUIRED"
                    ):
                        raise WorkflowEngineError(
                            "stored FIX_REQUIRED reviewer evidence is invalid"
                        )
                    finding_bindings = evidence_bindings[2:]
            event_has_blocker = False
            for binding in finding_bindings:
                record, snapshot = self._read_bound_evidence_json_snapshot(binding)
                validate_contract("review_finding", record, mode="runtime")
                if not self._is_current_fix_blocker(record):
                    continue
                event_has_blocker = True
                blocker_records.append((record, snapshot))
            if not event_has_blocker:
                raise WorkflowEngineError(
                    "stored FIX_REQUIRED evidence has no accepted open P0 or P1 blocker"
                )
        return blocker_records

    def _current_fix_cycle_blocker_ids(self, current: dict[str, Any]) -> set[str]:
        return {
            record["finding_id"]
            for record, _ in self._current_fix_cycle_blockers(current)
            if "finding_id" in record
        }

    def _fix_cycle_integration_boundary(self, current: dict[str, Any]) -> datetime | None:
        events = self._current_fix_cycle_events(current)
        if not events:
            return None
        latest_fix_index = max(index for index, event in enumerate(events) if event["to_state"] == "FIX_REQUIRED")
        integrations = [
            event
            for event in events[latest_fix_index + 1 :]
            if event["to_state"] == "INTEGRATING"
        ]
        if not integrations:
            raise WorkflowEngineError("VERIFIED requires an INTEGRATING boundary after the latest FIX_REQUIRED")
        return self._utc_instant(integrations[-1]["created_at_utc"])

    def _current_fix_cycle_events(self, current: dict[str, Any]) -> list[dict[str, Any]]:
        events = self._trusted_audit_lineage(current)
        previous_verified = max(
            (index for index, event in enumerate(events) if event["to_state"] == "VERIFIED"),
            default=-1,
        )
        current_interval = events[previous_verified + 1 :]
        if not any(event["to_state"] == "FIX_REQUIRED" for event in current_interval):
            return []
        return current_interval

    def _trusted_audit_lineage(self, current: dict[str, Any]) -> list[dict[str, Any]]:
        task_id = current["task_id"]
        project_id = current["project_id"]
        current_generation = current["audit_generation"]
        generation = current_generation
        expected_head_event_id = current["audit_head_event_id"]
        expected_head_sequence: int | None = None
        expected_head_hash = current["audit_head_hash"]
        visited: set[int] = set()
        generations: list[list[dict[str, Any]]] = []
        while True:
            if generation in visited or generation < 1 or generation > current_generation:
                raise WorkflowEngineError("audit generation lineage is cyclic or invalid")
            visited.add(generation)
            try:
                rows = self.store.read_audit_events(task_id, generation=generation)
            except WorkflowStoreError as exc:
                raise WorkflowEngineError(str(exc)) from exc
            prefix: list[dict[str, Any]] = []
            previous_hash = None
            head_index = None
            for event in rows:
                if (
                    event["project_id"] != project_id
                    or event["task_id"] != task_id
                    or event["generation"] != generation
                    or event["sequence"] != len(prefix) + 1
                    or event["previous_event_hash"] != previous_hash
                    or event["event_hash"] != self._canonical_sha(dict(event, event_hash=None))
                ):
                    raise WorkflowEngineError("audit prefix identity or hash chain mismatch")
                prefix.append(event)
                previous_hash = event["event_hash"]
                if event["event_hash"] == expected_head_hash:
                    head_index = len(prefix) - 1
                    break
            if head_index is None:
                raise WorkflowEngineError("trusted audit head is missing")
            head = prefix[head_index]
            if head["event_id"] != expected_head_event_id:
                raise WorkflowEngineError("trusted audit head event identity mismatch")
            if expected_head_sequence is not None and head["sequence"] != expected_head_sequence:
                raise WorkflowEngineError("trusted audit head sequence mismatch")
            if generation == current_generation and head_index != len(rows) - 1:
                raise WorkflowEngineError("current audit head is not the authoritative tail")
            generations.append(prefix)
            generation_record = prefix[0].get("details", {}).get("audit_generation")
            if not isinstance(generation_record, dict) or generation_record.get("generation") != generation:
                raise WorkflowEngineError("audit generation start record is missing")
            predecessor = generation_record.get("predecessor_generation")
            predecessor_hash = generation_record.get("predecessor_valid_head_hash")
            if predecessor is None:
                if generation != 1 or predecessor_hash is not None:
                    raise WorkflowEngineError("audit generation lineage ended before generation one")
                break
            if not isinstance(predecessor, int) or isinstance(predecessor, bool) or predecessor >= generation:
                raise WorkflowEngineError("audit predecessor is invalid")
            trusted_prefix = prefix[0].get("details", {}).get("previous_trusted_prefix")
            if (
                not isinstance(trusted_prefix, dict)
                or trusted_prefix.get("generation") != predecessor
                or trusted_prefix.get("event_hash") != predecessor_hash
            ):
                raise WorkflowEngineError("audit predecessor binding mismatch")
            generation = predecessor
            expected_head_event_id = trusted_prefix.get("event_id")
            expected_head_sequence = trusted_prefix.get("sequence")
            expected_head_hash = predecessor_hash
        return [event for events in reversed(generations) for event in events]

    @staticmethod
    def _utc_instant(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError) as exc:
            raise WorkflowEngineError("evidence timestamp must be an RFC 3339 instant") from exc
        if parsed.tzinfo is None:
            raise WorkflowEngineError("evidence timestamp must include a UTC offset")
        return parsed.astimezone(timezone.utc)

    def _path_evidence_binding(
        self,
        path: Path,
        token: str,
        sequence: int,
        index: int,
        target: str,
        created_at_utc: str,
    ) -> dict[str, Any]:
        logical_path, resolved = self._evidence_location(path)
        payload = resolved.read_bytes()
        return {
            "schema_version": 1,
            "binding_id": f"ev-{token}-{sequence:04d}-{index:02d}",
            "evidence_kind": f"transition_{target.lower()}",
            "source": "path",
            "path": logical_path,
            "embedded_record": None,
            "embedded_sha256": None,
            "content_sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "created_at_utc": created_at_utc,
        }

    def _evidence_location(self, path: Path) -> tuple[str, Path]:
        if path.is_symlink():
            raise WorkflowEngineError(f"evidence path must not be a symlink: {path}")
        try:
            resolved = path.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise WorkflowEngineError(f"evidence path is missing: {path}") from exc
        if not resolved.is_file():
            raise WorkflowEngineError(f"evidence path is not a regular file: {path}")
        for label, root in (("project", self.project_root), ("state", self.state_root)):
            root_resolved = root.resolve(strict=True)
            if resolved.is_relative_to(root_resolved):
                return f"{label}/{resolved.relative_to(root_resolved).as_posix()}", resolved
        raise WorkflowEngineError("evidence must be contained by the managed project or ACGPS state root")

    @staticmethod
    def _embedded_evidence_binding(
        *,
        binding_id: str,
        evidence_kind: str,
        record: dict[str, Any],
        created_at_utc: str,
    ) -> dict[str, Any]:
        payload = canonical_json_bytes(record)
        digest = hashlib.sha256(payload).hexdigest()
        return {
            "schema_version": 1,
            "binding_id": binding_id,
            "evidence_kind": evidence_kind,
            "source": "embedded",
            "path": None,
            "embedded_record": record,
            "embedded_sha256": digest,
            "content_sha256": digest,
            "size_bytes": len(payload),
            "created_at_utc": created_at_utc,
        }

    def _read_canonical_evidence_json(
        self,
        path: Path,
    ) -> tuple[dict[str, Any], tuple[str, int, str]]:
        logical_path, resolved = self._evidence_location(path)
        try:
            payload = resolved.read_bytes()
        except OSError as exc:
            raise WorkflowEngineError(f"evidence is unreadable: {path}") from exc
        record = self._parse_canonical_evidence_json(payload, path)
        return record, (logical_path, len(payload), hashlib.sha256(payload).hexdigest())

    def _read_bound_canonical_evidence_json(
        self,
        binding: dict[str, Any],
    ) -> tuple[dict[str, Any], tuple[str, int, str]]:
        logical_path = binding.get("path")
        if binding.get("source") != "path" or not isinstance(logical_path, str):
            raise WorkflowEngineError("bound evidence binding must reference a path")
        prefix, separator, relative = logical_path.partition("/")
        roots = {"project": self.project_root, "state": self.state_root}
        if not separator or prefix not in roots or not relative:
            raise WorkflowEngineError("bound evidence binding path is invalid")
        rebound_logical, resolved = self._evidence_location(
            roots[prefix] / Path(relative)
        )
        try:
            payload = resolved.read_bytes()
        except OSError as exc:
            raise WorkflowEngineError(f"evidence is unreadable: {resolved}") from exc
        digest = hashlib.sha256(payload).hexdigest()
        if (
            rebound_logical != logical_path
            or binding.get("size_bytes") != len(payload)
            or binding.get("content_sha256") != digest
        ):
            raise WorkflowEngineError("bound evidence binding content changed")
        record = self._parse_canonical_evidence_json(payload, resolved)
        return record, (rebound_logical, len(payload), digest)

    def _read_bound_evidence_json_snapshot(
        self,
        binding: dict[str, Any],
    ) -> tuple[dict[str, Any], tuple[str, int, str]]:
        logical_path = binding.get("path")
        if binding.get("source") != "path" or not isinstance(logical_path, str):
            raise WorkflowEngineError("bound evidence binding must reference a path")
        prefix, separator, relative = logical_path.partition("/")
        roots = {"project": self.project_root, "state": self.state_root}
        if not separator or prefix not in roots or not relative:
            raise WorkflowEngineError("bound evidence binding path is invalid")
        rebound_logical, resolved = self._evidence_location(
            roots[prefix] / Path(relative)
        )
        try:
            payload = resolved.read_bytes()
            record = json.loads(payload.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkflowEngineError(f"evidence is unreadable: {resolved}") from exc
        digest = hashlib.sha256(payload).hexdigest()
        if (
            rebound_logical != logical_path
            or binding.get("size_bytes") != len(payload)
            or binding.get("content_sha256") != digest
        ):
            raise WorkflowEngineError("bound evidence binding content changed")
        if not isinstance(record, dict):
            raise WorkflowEngineError(f"evidence must be a mapping: {resolved}")
        return record, (rebound_logical, len(payload), digest)

    def _bound_evidence_path(self, binding: dict[str, Any]) -> Path:
        logical_path = binding.get("path")
        if binding.get("source") != "path" or not isinstance(logical_path, str):
            raise WorkflowEngineError("fix-cycle evidence binding must reference a path")
        prefix, separator, relative = logical_path.partition("/")
        roots = {"project": self.project_root, "state": self.state_root}
        if not separator or prefix not in roots or not relative:
            raise WorkflowEngineError("fix-cycle evidence binding path is invalid")
        rebound_logical, resolved = self._evidence_location(
            roots[prefix] / Path(relative)
        )
        payload = resolved.read_bytes()
        if (
            rebound_logical != logical_path
            or binding.get("size_bytes") != len(payload)
            or binding.get("content_sha256")
            != hashlib.sha256(payload).hexdigest()
        ):
            raise WorkflowEngineError("fix-cycle evidence binding content changed")
        return resolved

    @staticmethod
    def _parse_canonical_evidence_json(
        payload: bytes,
        path: Path,
    ) -> dict[str, Any]:
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkflowEngineError(f"evidence is unreadable: {path}") from exc

        def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            record: dict[str, Any] = {}
            folded: set[str] = set()
            for key, value in pairs:
                if key in record or key.casefold() in folded:
                    raise WorkflowEngineError(
                        f"evidence has a duplicate or case-fold-colliding JSON key: {key}"
                    )
                record[key] = value
                folded.add(key.casefold())
            return record

        try:
            record = json.loads(text, object_pairs_hook=reject_duplicate_pairs)
        except json.JSONDecodeError as exc:
            raise WorkflowEngineError(f"evidence is unreadable: {path}") from exc
        if not isinstance(record, dict):
            raise WorkflowEngineError(f"evidence must be a mapping: {path}")
        if canonical_json_bytes(record) + b"\n" != payload:
            raise WorkflowEngineError(
                f"evidence must use canonical JSON bytes with one terminal LF: {path}"
            )
        return record

    def _read_evidence_json_snapshot(
        self,
        path: Path,
    ) -> tuple[dict[str, Any], tuple[str, int, str]]:
        logical_path, resolved = self._evidence_location(path)
        try:
            payload = resolved.read_bytes()
            record = json.loads(payload.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkflowEngineError(f"evidence is unreadable: {path}") from exc
        if not isinstance(record, dict):
            raise WorkflowEngineError(f"evidence must be a mapping: {path}")
        return record, (logical_path, len(payload), hashlib.sha256(payload).hexdigest())

    @staticmethod
    def _canonical_sha(record: object) -> str:
        return hashlib.sha256(canonical_json_bytes(record)).hexdigest()

    @staticmethod
    def _task_token(task_id: str) -> str:
        return hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:16]
