from __future__ import annotations

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
    validate_review_findings,
    verify_release_candidate_manifest,
)
from acgps.supervised_handoff import build_supervised_coder_result_receipt_preview
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
    ):
        self.policy_root = Path(policy_root)
        self.state_root = Path(state_root)
        self.project_root = Path(project_root)
        self.profile_id = profile_id
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
        self.store = WorkflowStore(self.state_root)
        self.decisions = DecisionQueue(self.state_root / "decisions", workflow_store=self.store)

    def intake(self, intake: dict[str, Any], *, actor: str = "PLANNER") -> dict[str, Any]:
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
        required_actor = {
            "FIX_REQUIRED": "REVIEWER",
            "INTEGRATING": "REVIEWER",
            "TASK_REVIEW": "CODER",
            "VERIFIED": "VERIFIER",
        }.get(actual_target)
        if required_actor is not None and actor != required_actor:
            raise WorkflowEngineError(f"{actual_target} requires actor {required_actor}")
        evidence_items = [Path(path) for path in evidence_paths]
        if not evidence_items:
            raise WorkflowEngineError("every accepted transition requires evidence")
        self._validate_gate_evidence(actual_target, evidence_items, current)
        evidence_bindings = [
            self._path_evidence_binding(path, token, sequence, index, actual_target, created_at_utc)
            for index, path in enumerate(evidence_items, start=1)
        ]

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

    def _validate_gate_evidence(
        self,
        target: str,
        paths: list[Path],
        current: dict[str, Any],
    ) -> None:
        try:
            if target == "FIX_REQUIRED":
                validate_fix_required_findings(paths)
            elif target == "INTEGRATING":
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
            elif target == "TASK_REVIEW":
                self._validate_task_review_evidence(paths, current)
            elif target == "VERIFIED":
                verified = False
                boundary = self._fix_cycle_integration_boundary(current)
                for path in paths:
                    record = self._read_json(path)
                    validate_contract("verification_record", record, mode="runtime")
                    if record["project_id"] != current["project_id"] or record["task_id"] != current["task_id"]:
                        raise WorkflowEngineError(
                            "verification evidence project_id and task_id must match the current task"
                        )
                    if record["recommendation"] == "VERIFIED":
                        if boundary is not None and self._utc_instant(record["verified_at_utc"]) < boundary:
                            raise WorkflowEngineError(
                                "verification evidence predates the current fix-cycle integration boundary"
                            )
                        verified = True
                if not verified:
                    raise WorkflowEngineError("VERIFIED requires a successful verification record")
            elif target == "RC_READY":
                if not any(
                    verify_release_candidate_manifest(
                        path,
                        expected_project_id=current["project_id"],
                        expected_task_id=current["task_id"],
                    )
                    for path in paths
                ):
                    raise WorkflowEngineError("RC_READY requires a valid release-candidate manifest")
        except (ContractValidationError, ReviewEvidenceError) as exc:
            raise WorkflowEngineError(str(exc)) from exc

    def _validate_task_review_evidence(
        self,
        paths: list[Path],
        current: dict[str, Any],
    ) -> None:
        if len(paths) != 2:
            raise WorkflowEngineError(
                "TASK_REVIEW requires the canonical CODER packet and result as exactly two evidence files"
            )
        packet = self._read_canonical_evidence_json(paths[0])
        agent_result = self._read_canonical_evidence_json(paths[1])
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

    def _current_fix_cycle_blocker_ids(self, current: dict[str, Any]) -> set[str]:
        blocker_ids: set[str] = set()
        for event in self._current_fix_cycle_events(current):
            if event["to_state"] != "FIX_REQUIRED":
                continue
            paths = [self._bound_evidence_path(binding) for binding in event["evidence_bindings"]]
            records = validate_fix_required_findings(paths)
            blocker_ids.update(
                record["finding_id"]
                for record in records
                if record["severity"] in {"P0", "P1"}
                and record["status"] in {"OPEN", "IN_PROGRESS"}
                and record["disposition"] in {"ACCEPTED", "PARTIAL"}
            )
        return blocker_ids

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

    def _bound_evidence_path(self, binding: dict[str, Any]) -> Path:
        logical_path = binding.get("path")
        if binding.get("source") != "path" or not isinstance(logical_path, str):
            raise WorkflowEngineError("fix-cycle evidence binding must reference a path")
        prefix, separator, relative = logical_path.partition("/")
        roots = {"project": self.project_root, "state": self.state_root}
        if not separator or prefix not in roots or not relative:
            raise WorkflowEngineError("fix-cycle evidence binding path is invalid")
        rebound_logical, resolved = self._evidence_location(roots[prefix] / Path(relative))
        payload = resolved.read_bytes()
        if (
            rebound_logical != logical_path
            or binding.get("size_bytes") != len(payload)
            or binding.get("content_sha256") != hashlib.sha256(payload).hexdigest()
        ):
            raise WorkflowEngineError("fix-cycle evidence binding content changed")
        return resolved

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

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowEngineError(f"evidence is unreadable: {path}") from exc
        if not isinstance(record, dict):
            raise WorkflowEngineError(f"evidence must be a mapping: {path}")
        return record

    def _read_canonical_evidence_json(self, path: Path) -> dict[str, Any]:
        _, resolved = self._evidence_location(path)
        try:
            payload = resolved.read_bytes()
            text = payload.decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
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

    @staticmethod
    def _canonical_sha(record: object) -> str:
        return hashlib.sha256(canonical_json_bytes(record)).hexdigest()

    @staticmethod
    def _task_token(task_id: str) -> str:
        return hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:16]
