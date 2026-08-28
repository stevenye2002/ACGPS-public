from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from acgps.review_adapter import build_release_candidate_manifest
from acgps.task_packets import generate_task_packet
from acgps.workflow_contracts import canonical_json_bytes
from tests.test_mvp_cli import (
    valid_agent_result,
    valid_coder_packet,
    valid_decision_request,
    valid_intake,
    valid_policy_result,
    valid_review_finding,
    valid_verification_record,
)


ROOT = Path(__file__).resolve().parents[1]
MVP_FTIC_ROOT = ROOT / "tests" / "fixtures" / "mvp_ftic"


def tree_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def write_task_review_evidence(engine) -> list[Path]:
    evidence_dir = engine.state_root / "task-review-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    packet_path = evidence_dir / "coder-packet.json"
    result_path = evidence_dir / "coder-result.json"
    packet_path.write_bytes(canonical_json_bytes(valid_coder_packet()) + b"\n")
    result_path.write_bytes(canonical_json_bytes(valid_agent_result()) + b"\n")
    return [packet_path, result_path]


def valid_planner_packet() -> dict[str, object]:
    return generate_task_packet("PLANNER", valid_intake(), valid_policy_result())


def valid_planner_result(*, recommended_next_state: str) -> dict[str, object]:
    return dict(
        valid_agent_result(),
        packet_id="ftic-governance-1-planner-v1",
        role="PLANNER",
        summary="Completed the bounded planning task.",
        changed_files=[],
        created_files=[],
        recommended_next_state=recommended_next_state,
    )


def write_planner_transition_evidence(
    engine,
    *,
    target: str,
    packet: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
) -> list[Path]:
    evidence_dir = (
        engine.state_root
        / "planner-transition-evidence"
        / f"{target.casefold()}-{len(engine.audit('ftic-governance-1')) + 1:04d}"
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    packet_path = evidence_dir / "planner-packet.json"
    result_path = evidence_dir / "planner-result.json"
    packet_path.write_bytes(canonical_json_bytes(packet or valid_planner_packet()) + b"\n")
    result_path.write_bytes(
        canonical_json_bytes(
            result or valid_planner_result(recommended_next_state=target)
        )
        + b"\n"
    )
    return [packet_path, result_path]


def valid_coder_handoff_packet() -> dict[str, object]:
    packet = dict(valid_planner_packet())
    packet["packet_id"] = "ftic-governance-1-coder-v1"
    packet["role"] = "CODER"
    return packet


def write_coder_handoff_evidence(
    engine,
    *,
    packet: dict[str, object] | None = None,
) -> Path:
    evidence_dir = (
        engine.state_root
        / "coder-handoff-evidence"
        / f"implementing-{len(engine.audit('ftic-governance-1')) + 1:04d}"
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    packet_path = evidence_dir / "coder-packet.json"
    packet_path.write_bytes(
        canonical_json_bytes(packet or valid_coder_handoff_packet()) + b"\n"
    )
    return packet_path


def write_coder_remediation_handoff_evidence(
    engine,
    finding_paths: list[Path],
    *,
    packet: dict[str, object] | None = None,
) -> list[Path]:
    return [write_coder_handoff_evidence(engine, packet=packet), *finding_paths]


def valid_reviewer_packet() -> dict[str, object]:
    return generate_task_packet("REVIEWER", valid_intake(), valid_policy_result())


def valid_reviewer_result(*, recommended_next_state: str) -> dict[str, object]:
    return dict(
        valid_agent_result(),
        packet_id="ftic-governance-1-reviewer-v1",
        role="REVIEWER",
        summary="Completed the bounded independent review.",
        changed_files=[],
        created_files=[],
        recommended_next_state=recommended_next_state,
    )


def write_reviewer_transition_evidence(
    engine,
    finding_paths: list[Path],
    *,
    target: str,
    packet: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
) -> list[Path]:
    evidence_dir = (
        engine.state_root
        / "reviewer-transition-evidence"
        / f"{target.casefold()}-{len(engine.audit('ftic-governance-1')) + 1:04d}"
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    packet_path = evidence_dir / "reviewer-packet.json"
    result_path = evidence_dir / "reviewer-result.json"
    packet_path.write_bytes(canonical_json_bytes(packet or valid_reviewer_packet()) + b"\n")
    result_path.write_bytes(
        canonical_json_bytes(result or valid_reviewer_result(recommended_next_state=target)) + b"\n"
    )
    return [packet_path, result_path, *finding_paths]


def valid_verifier_packet() -> dict[str, object]:
    return generate_task_packet("VERIFIER", valid_intake(), valid_policy_result())


def valid_verifier_result() -> dict[str, object]:
    return dict(
        valid_agent_result(),
        packet_id="ftic-governance-1-verifier-v1",
        role="VERIFIER",
        summary="Completed the bounded independent verification.",
        changed_files=[],
        created_files=[],
        recommended_next_state="VERIFIED",
    )


def write_verifier_transition_evidence(
    engine,
    verification_paths: list[Path],
    *,
    packet: dict[str, object] | None = None,
    result: dict[str, object] | None = None,
) -> list[Path]:
    evidence_dir = engine.state_root / "verifier-transition-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    packet_path = evidence_dir / "verifier-packet.json"
    result_path = evidence_dir / "verifier-result.json"
    packet_path.write_bytes(canonical_json_bytes(packet or valid_verifier_packet()) + b"\n")
    result_path.write_bytes(canonical_json_bytes(result or valid_verifier_result()) + b"\n")
    return [packet_path, result_path, *verification_paths]


def advance_to_implementing(engine, *, hour: int) -> Path:
    evidence = advance_to_plan_ready(engine, hour=hour)
    engine.advance(
        "ftic-governance-1",
        "IMPLEMENTING",
        actor="CODER",
        evidence_paths=[write_coder_handoff_evidence(engine)],
        created_at_utc=f"2026-08-23T{hour:02d}:05:00Z",
    )
    return evidence


def advance_to_plan_ready(engine, *, hour: int) -> Path:
    engine.intake(valid_intake())
    evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
    for minute, target in enumerate(
        (
            "READY_FOR_CLASSIFICATION",
            "CLASSIFIED",
            "SPEC_READY",
            "PLAN_READY",
        ),
        start=1,
    ):
        planner_gate = target in {"SPEC_READY", "PLAN_READY"}
        engine.advance(
            "ftic-governance-1",
            target,
            actor="PLANNER" if planner_gate else "CONTROLLER",
            evidence_paths=(
                write_planner_transition_evidence(engine, target=target)
                if planner_gate
                else [evidence]
            ),
            created_at_utc=f"2026-08-23T{hour:02d}:{minute:02d}:00Z",
        )
    return evidence


def advance_to_waiting_human(engine, *, hour: int) -> dict[str, object]:
    engine.intake(valid_intake())
    evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
    for minute, target in enumerate(
        ("READY_FOR_CLASSIFICATION", "CLASSIFIED"),
        start=1,
    ):
        engine.advance(
            "ftic-governance-1",
            target,
            actor="CONTROLLER",
            evidence_paths=[evidence],
            created_at_utc=f"2026-08-27T{hour:02d}:0{minute}:00Z",
        )
    return engine.advance(
        "ftic-governance-1",
        "SPEC_READY",
        actor="CONTROLLER",
        evidence_paths=[evidence],
        human_triggers=["H1_PRODUCT_INTENT"],
        created_at_utc=f"2026-08-27T{hour:02d}:03:00Z",
    )


def advance_plan_ready_to_waiting_human(engine, *, hour: int) -> dict[str, object]:
    evidence = advance_to_plan_ready(engine, hour=hour)
    return engine.advance(
        "ftic-governance-1",
        "IMPLEMENTING",
        actor="CONTROLLER",
        evidence_paths=[evidence],
        human_triggers=["H1_PRODUCT_INTENT"],
        created_at_utc=f"2026-08-27T{hour:02d}:05:00Z",
    )


def waiting_human_resolution(
    waiting: dict[str, object],
    *,
    resume_state: str = "SPEC_READY",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "decision_id": waiting["pending_decision_id"],
        "project_id": "FTIC",
        "task_id": "ftic-governance-1",
        "selected_option": "RESUME",
        "resolved_by": "human_owner",
        "resolved_at_utc": "2026-08-27T07:04:00Z",
        "rationale": "Continue the approved supervised workflow.",
        "evidence_paths": [],
        "resume_state": resume_state,
        "status": "RESOLVED",
    }


def advance_to_task_review(engine, *, hour: int) -> Path:
    evidence = advance_to_implementing(engine, hour=hour)
    engine.advance(
        "ftic-governance-1",
        "TASK_REVIEW",
        actor="CODER",
        evidence_paths=write_task_review_evidence(engine),
        created_at_utc=f"2026-08-23T{hour:02d}:06:00Z",
    )
    return evidence


def advance_to_integrating(engine, *, hour: int) -> Path:
    advance_to_task_review(engine, hour=hour)
    evidence_dir = engine.state_root / "integration-evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    finding_path = evidence_dir / "review-finding.json"
    write_review_finding(finding_path, "finding-integration", status="CLOSED")
    engine.advance(
        "ftic-governance-1",
        "INTEGRATING",
        actor="REVIEWER",
        evidence_paths=write_reviewer_transition_evidence(
            engine,
            [finding_path],
            target="INTEGRATING",
        ),
        created_at_utc=f"2026-08-23T{hour:02d}:07:00Z",
    )
    return finding_path


def write_review_finding(path: Path, finding_id: str, *, status: str) -> bytes:
    record = dict(
        valid_review_finding(status=status),
        finding_id=finding_id,
        review_id=f"review-{finding_id}",
        summary=f"Review finding {finding_id}.",
        disposition="ACCEPTED" if status in {"OPEN", "IN_PROGRESS"} else "ALREADY_FIXED",
    )
    payload = json.dumps(record, sort_keys=True).encode("utf-8") + b"\n"
    path.write_bytes(payload)
    return payload


def write_verification_record(path: Path, verification_id: str) -> Path:
    record = dict(valid_verification_record(), verification_id=verification_id)
    path.write_bytes(canonical_json_bytes(record) + b"\n")
    return path


def build_test_release_candidate_manifest(
    engine,
    *,
    review_path: Path,
    verification_paths: list[Path],
) -> Path:
    source_path = engine.state_root / "source.txt"
    source_path.write_text("frozen governance source\n", encoding="utf-8")
    rollback_path = engine.state_root / "rollback.md"
    rollback_path.write_text("Remove generated runtime state.\n", encoding="utf-8")
    return build_release_candidate_manifest(
        output_dir=engine.state_root,
        project_id="FTIC",
        rc_id="ftic-governance-rc-1",
        version="1.0",
        source_path=source_path,
        verification_paths=verification_paths,
        review_paths=[review_path],
        rollback_path=rollback_path,
        created_at_utc="2026-08-23T01:09:00Z",
    )


def prepare_verified_rc_lineage(
    state_root: Path,
    verification_ids: list[str],
):
    from acgps.workflow_engine import WorkflowEngine

    engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
    review_path = advance_to_integrating(engine, hour=1)
    verification_paths = [
        write_verification_record(state_root / f"{verification_id}.json", verification_id)
        for verification_id in verification_ids
    ]
    engine.advance(
        "ftic-governance-1",
        "VERIFIED",
        actor="VERIFIER",
        evidence_paths=write_verifier_transition_evidence(engine, verification_paths),
        created_at_utc="2026-08-23T01:08:00Z",
    )
    return engine, review_path, verification_paths


def prepare_rc_ready_lineage(state_root: Path):
    engine, review_path, verification_paths = prepare_verified_rc_lineage(
        state_root,
        ["verification-current"],
    )
    manifest_path = build_test_release_candidate_manifest(
        engine,
        review_path=review_path,
        verification_paths=verification_paths,
    )
    engine.advance(
        "ftic-governance-1",
        "RC_READY",
        actor="VERIFIER",
        evidence_paths=[manifest_path],
        created_at_utc="2026-08-23T01:10:00Z",
    )
    return engine, manifest_path


def start_recovery_generation(engine, state: dict[str, object], *, created_at_utc: str) -> None:
    current_generation = int(state["audit_generation"])
    next_generation = current_generation + 1
    trusted_events = engine.audit("ftic-governance-1")
    event_id = f"evt-ftic-governance-1-recovery-{next_generation:04d}"
    event = {
        "schema_version": 1,
        "event_id": event_id,
        "generation": next_generation,
        "sequence": 1,
        "project_id": "FTIC",
        "task_id": "ftic-governance-1",
        "event_type": "RECOVERY_RECORDED",
        "actor": "VERIFIER",
        "from_state": None,
        "to_state": None,
        "transition_id": None,
        "policy_evaluation_binding": None,
        "evidence_bindings": [],
        "decision_resolution_binding": None,
        "previous_event_hash": None,
        "event_hash": None,
        "created_at_utc": created_at_utc,
        "details": {
            "recovery_id": f"recovery-ftic-governance-1-{next_generation:04d}",
            "recovery_action": "quarantine_and_start_generation",
            "recovery_transaction_id": f"recovery-tx-ftic-governance-1-{next_generation:04d}",
            "previous_trusted_prefix": {
                "generation": current_generation,
                "sequence": len(trusted_events),
                "event_id": state["audit_head_event_id"],
                "event_hash": state["audit_head_hash"],
            },
            "quarantine_path": f"state/quarantine/ftic-governance-1/recovery-{next_generation:04d}/audit-tail.bin",
            "threat_model": "CORRUPTION_AND_NON_COORDINATED_TAMPER_ONLY",
            "audit_generation": {
                "schema_version": 1,
                "generation": next_generation,
                "task_id": "ftic-governance-1",
                "started_by_event_id": event_id,
                "started_by_event_type": "RECOVERY_RECORDED",
                "predecessor_generation": current_generation,
                "predecessor_valid_head_hash": state["audit_head_hash"],
                "quarantine_path": (
                    f"state/quarantine/ftic-governance-1/recovery-{next_generation:04d}/audit-tail.bin"
                ),
                "threat_model": "CORRUPTION_AND_NON_COORDINATED_TAMPER_ONLY",
                "created_at_utc": created_at_utc,
            },
        },
    }
    event["event_hash"] = hashlib.sha256(
        canonical_json_bytes(dict(event, event_hash=None))
    ).hexdigest()
    engine.store.append_audit_event(event)
    engine.store.write_task_state(
        dict(
            state,
            audit_generation=next_generation,
            audit_head_event_id=event_id,
            audit_head_hash=event["event_hash"],
            updated_at_utc=created_at_utc,
        )
    )


class WorkflowEngineTests(unittest.TestCase):
    def test_audit_lineage_verification_derives_multi_generation_identity_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            writer.intake(valid_intake())
            start_recovery_generation(
                writer,
                writer.status("ftic-governance-1"),
                created_at_utc="2026-08-28T09:00:00Z",
            )
            current = writer.status("ftic-governance-1")
            before = tree_bytes(state_root)

            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            result = reader.audit_lineage_verification("ftic-governance-1")

            self.assertEqual(
                result,
                {
                    "status": "AUDIT_LINEAGE_VERIFIED",
                    "task_id": "ftic-governance-1",
                    "project_id": "FTIC",
                    "current_state": "DRAFT",
                    "audit_generation": 2,
                    "trusted_generation_count": 2,
                    "trusted_event_count": 2,
                    "audit_head_event_id": "evt-ftic-governance-1-recovery-0002",
                    "audit_head_hash": current["audit_head_hash"],
                    "state_identity_status": "UNCHANGED_DURING_QUERY",
                    "controls": {
                        "model_execution": "NOT_STARTED",
                        "process_launch": "NOT_STARTED",
                        "state_write": "NOT_PERFORMED",
                        "workflow_transition": "NOT_PERFORMED",
                    },
                },
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_audit_lineage_verification_rejects_task_state_identity_drift(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            writer.intake(valid_intake())
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            initial = reader.status("ftic-governance-1")
            changed = dict(initial, updated_at_utc="2026-08-28T09:01:00Z")

            with patch.object(reader, "status", side_effect=[initial, changed]):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "task state identity changed during audit lineage verification",
                ):
                    reader.audit_lineage_verification("ftic-governance-1")

    def test_audit_lineage_verification_rejects_audit_only_drift(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            writer.intake(valid_intake())
            initial = writer.status("ftic-governance-1")
            initial_lineage = writer._trusted_audit_lineage(initial)
            start_recovery_generation(
                writer,
                initial,
                created_at_utc="2026-08-28T09:02:00Z",
            )
            changed = writer.status("ftic-governance-1")
            changed_lineage = writer._trusted_audit_lineage(changed)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            with (
                patch.object(reader, "status", side_effect=[initial, initial]),
                patch.object(
                    reader,
                    "_trusted_audit_lineage",
                    side_effect=[initial_lineage, changed_lineage],
                ),
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "audit lineage identity changed during audit lineage verification",
                ):
                    reader.audit_lineage_verification("ftic-governance-1")

    def test_next_action_preview_derives_existing_plan_ready_contract_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_plan_ready(writer, hour=0)
            before = tree_bytes(state_root)

            try:
                reader = WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                )
                preview = reader.next_action_preview("ftic-governance-1")
            except (AttributeError, TypeError) as exc:
                self.fail(f"read-only next-action preview is unavailable: {exc}")

            self.assertEqual(preview["status"], "NEXT_ACTION_PREVIEW")
            self.assertEqual(preview["task_id"], "ftic-governance-1")
            self.assertEqual(preview["project_id"], "FTIC")
            self.assertEqual(preview["current_state"], "PLAN_READY")
            self.assertEqual(preview["authorization_status"], "NOT_EVALUATED")
            self.assertIsNone(preview["selected_transition"])
            self.assertEqual(
                preview["options"],
                [
                    {
                        "target_state": "IMPLEMENTING",
                        "required_actor": "CODER",
                        "evidence_contract": {
                            "status": "BOUND_EXISTING_CONTRACT",
                            "minimum_count": 1,
                            "maximum_count": 1,
                            "ordered_kinds": ["CODER_TASK_PACKET"],
                            "repeatable_tail": False,
                        },
                    },
                    {
                        "target_state": "WAITING_HUMAN",
                        "required_actor": None,
                        "evidence_contract": {
                            "status": "UNSPECIFIED_EXISTING_CONTRACT",
                            "minimum_count": 1,
                            "maximum_count": None,
                            "ordered_kinds": [],
                            "repeatable_tail": False,
                        },
                    },
                    {
                        "target_state": "ABANDONED",
                        "required_actor": None,
                        "evidence_contract": {
                            "status": "UNSPECIFIED_EXISTING_CONTRACT",
                            "minimum_count": 1,
                            "maximum_count": None,
                            "ordered_kinds": [],
                            "repeatable_tail": False,
                        },
                    },
                ],
            )
            self.assertEqual(preview["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(preview["controls"]["workflow_transition"], "NOT_PERFORMED")
            with self.assertRaisesRegex(WorkflowEngineError, "read-only workflow engine"):
                reader.intake(valid_intake())
            self.assertEqual(tree_bytes(state_root), before)

    def test_waiting_human_next_action_preview_binds_pending_decision_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=7)
            before = tree_bytes(state_root)

            preview = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).next_action_preview("ftic-governance-1")

            self.assertEqual(preview["current_state"], "WAITING_HUMAN")
            self.assertEqual(
                preview["pending_decision_requirement"],
                {
                    "decision_id": waiting["pending_decision_id"],
                    "status": "PENDING",
                    "required_resume_state": "SPEC_READY",
                    "allowed_option_ids": ["RESUME"],
                    "default_without_response": "PAUSE",
                    "resolution_required": True,
                },
            )
            self.assertEqual(
                preview["options"],
                [
                    {
                        "target_state": "SPEC_READY",
                        "required_actor": "PLANNER",
                        "evidence_contract": {
                            "status": "BOUND_EXISTING_CONTRACT",
                            "minimum_count": 2,
                            "maximum_count": 2,
                            "ordered_kinds": [
                                "PLANNER_TASK_PACKET",
                                "PLANNER_RESULT",
                            ],
                            "repeatable_tail": False,
                        },
                    }
                ],
            )
            self.assertIsNone(preview["selected_transition"])
            self.assertEqual(preview["authorization_status"], "NOT_EVALUATED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_waiting_human_resume_gate_preview_enforces_original_gate_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=7)
            resolution = waiting_human_resolution(waiting)
            planner_evidence = write_planner_transition_evidence(
                writer,
                target="SPEC_READY",
            )
            before = tree_bytes(state_root)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            with self.assertRaisesRegex(WorkflowEngineError, "requires actor PLANNER"):
                reader.waiting_human_resume_gate_preview(
                    "ftic-governance-1",
                    to_state="SPEC_READY",
                    actor="CONTROLLER",
                    evidence_paths=[MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"],
                    decision_resolution=resolution,
                    created_at_utc="2026-08-27T07:04:00Z",
                )

            preview = reader.waiting_human_resume_gate_preview(
                "ftic-governance-1",
                to_state="SPEC_READY",
                actor="PLANNER",
                evidence_paths=planner_evidence,
                decision_resolution=resolution,
                created_at_utc="2026-08-27T07:04:00Z",
            )

            self.assertEqual(preview["status"], "WAITING_HUMAN_RESUME_GATE_PREVIEW")
            self.assertEqual(preview["current_state"], "WAITING_HUMAN")
            self.assertEqual(preview["source_state_before_human_gate"], "CLASSIFIED")
            self.assertEqual(preview["target_state"], "SPEC_READY")
            self.assertEqual(preview["required_actor"], "PLANNER")
            self.assertEqual(preview["decision_id"], waiting["pending_decision_id"])
            self.assertEqual(preview["resolution_status"], "VALIDATED")
            self.assertEqual(preview["evidence_status"], "VALIDATED")
            self.assertEqual(preview["state_identity_status"], "UNCHANGED_DURING_QUERY")
            self.assertEqual(
                preview["pending_decision_identity_status"],
                "UNCHANGED_DURING_QUERY",
            )
            self.assertEqual(preview["authorization_status"], "NOT_GRANTED")
            self.assertEqual(preview["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(preview["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_waiting_human_resume_advance_rejects_generic_gate_bypass(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            writer = WorkflowEngine(ROOT, Path(tmp) / "state", MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=7)
            resolution = waiting_human_resolution(waiting)

            with self.assertRaisesRegex(WorkflowEngineError, "requires actor PLANNER"):
                writer.advance(
                    "ftic-governance-1",
                    "SPEC_READY",
                    actor="CONTROLLER",
                    evidence_paths=[MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"],
                    decision_resolution=resolution,
                    created_at_utc="2026-08-27T07:04:00Z",
                )

            self.assertEqual(
                writer.status("ftic-governance-1")["current_state"],
                "WAITING_HUMAN",
            )

    def test_waiting_human_resume_advance_rejects_second_human_pause(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=7)
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "transition WAITING_HUMAN -> WAITING_HUMAN is not policy-authorized",
            ):
                writer.advance(
                    "ftic-governance-1",
                    "SPEC_READY",
                    actor="CONTROLLER",
                    evidence_paths=[MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"],
                    decision_resolution=waiting_human_resolution(waiting),
                    created_at_utc="2026-08-27T07:04:00Z",
                    human_triggers=["H1_PRODUCT_INTENT"],
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_waiting_human_resume_rejects_source_state_not_bound_to_audit_head(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_plan_ready_to_waiting_human(writer, hour=7)
            corrupted = dict(writer.status("ftic-governance-1"), previous_state="BLOCKED")
            writer.store.write_task_state(corrupted)
            before = tree_bytes(state_root)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "previous_state does not match the trusted WAITING_HUMAN audit boundary",
            ):
                reader.waiting_human_resume_gate_preview(
                    "ftic-governance-1",
                    to_state="IMPLEMENTING",
                    actor="CONTROLLER",
                    evidence_paths=[MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"],
                    decision_resolution=waiting_human_resolution(
                        waiting,
                        resume_state="IMPLEMENTING",
                    ),
                    created_at_utc="2026-08-27T07:06:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_waiting_human_resume_from_plan_ready_uses_frozen_plan_boundary(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_plan_ready_to_waiting_human(writer, hour=7)
            resolution = waiting_human_resolution(waiting, resume_state="IMPLEMENTING")
            coder_packet = write_coder_handoff_evidence(writer)
            before = tree_bytes(state_root)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            try:
                preview = reader.waiting_human_resume_gate_preview(
                    "ftic-governance-1",
                    to_state="IMPLEMENTING",
                    actor="CODER",
                    evidence_paths=[coder_packet],
                    decision_resolution=resolution,
                    created_at_utc="2026-08-27T07:06:00Z",
                )
            except WorkflowEngineError as exc:
                self.fail(f"valid PLAN_READY resume preview was rejected: {exc}")

            self.assertEqual(preview["source_state_before_human_gate"], "PLAN_READY")
            self.assertEqual(preview["required_actor"], "CODER")
            self.assertEqual(preview["evidence_status"], "VALIDATED")
            self.assertEqual(tree_bytes(state_root), before)

            resumed = writer.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=[coder_packet],
                decision_resolution=resolution,
                created_at_utc="2026-08-27T07:06:00Z",
            )
            self.assertEqual(resumed["current_state"], "IMPLEMENTING")

    def test_waiting_human_resume_preview_rejects_conflicting_stored_resolution(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=7)
            stored_resolution = waiting_human_resolution(waiting)
            writer.decisions.resolve(stored_resolution)
            conflicting_resolution = dict(
                stored_resolution,
                rationale="A different otherwise-valid human rationale.",
            )
            planner_evidence = write_planner_transition_evidence(
                writer,
                target="SPEC_READY",
            )
            before = tree_bytes(state_root)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "resolution does not match the existing resolved decision record",
            ):
                reader.waiting_human_resume_gate_preview(
                    "ftic-governance-1",
                    to_state="SPEC_READY",
                    actor="PLANNER",
                    evidence_paths=planner_evidence,
                    decision_resolution=conflicting_resolution,
                    created_at_utc="2026-08-27T07:04:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_waiting_human_resume_gate_preview_rejects_identity_drift(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=7)
            resolution = waiting_human_resolution(waiting)
            planner_evidence = write_planner_transition_evidence(writer, target="SPEC_READY")
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            original_prepare = reader._prepare_transition_validation

            def mutate_state_after_validation(*args, **kwargs):
                prepared = original_prepare(*args, **kwargs)
                writer.store.write_task_state(
                    dict(
                        prepared["current"],
                        updated_at_utc="2026-08-27T07:04:01Z",
                    )
                )
                return prepared

            with patch.object(
                reader,
                "_prepare_transition_validation",
                side_effect=mutate_state_after_validation,
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "task state identity changed during resume gate preview",
                ):
                    reader.waiting_human_resume_gate_preview(
                        "ftic-governance-1",
                        to_state="SPEC_READY",
                        actor="PLANNER",
                        evidence_paths=planner_evidence,
                        decision_resolution=resolution,
                        created_at_utc="2026-08-27T07:04:00Z",
                    )

    def test_waiting_human_resume_gate_preview_rejects_pending_decision_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=7)
            resolution = waiting_human_resolution(waiting)
            planner_evidence = write_planner_transition_evidence(writer, target="SPEC_READY")
            pending_path = writer.decisions.pending_path(waiting["pending_decision_id"])
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            original_prepare = reader._prepare_transition_validation

            def mutate_pending_after_validation(*args, **kwargs):
                prepared = original_prepare(*args, **kwargs)
                pending = json.loads(pending_path.read_text(encoding="utf-8"))
                pending_path.write_bytes(
                    canonical_json_bytes(
                        dict(pending, question="Authorize the same bounded resume now?")
                    )
                    + b"\n"
                )
                return prepared

            with patch.object(
                reader,
                "_prepare_transition_validation",
                side_effect=mutate_pending_after_validation,
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "pending decision identity changed during resume gate preview",
                ):
                    reader.waiting_human_resume_gate_preview(
                        "ftic-governance-1",
                        to_state="SPEC_READY",
                        actor="PLANNER",
                        evidence_paths=planner_evidence,
                        decision_resolution=resolution,
                        created_at_utc="2026-08-27T07:04:00Z",
                    )

    def test_waiting_human_next_action_preview_rejects_illegal_pending_target(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=8)
            pending_path = writer.decisions.pending_path(waiting["pending_decision_id"])
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            pending_path.write_bytes(canonical_json_bytes(dict(pending, stage="DRAFT")) + b"\n")
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "pending decision target DRAFT is not legal from WAITING_HUMAN",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).next_action_preview("ftic-governance-1")

            self.assertEqual(tree_bytes(state_root), before)

    def test_waiting_human_next_action_preview_rejects_foreign_pending_project(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=10)
            pending_path = writer.decisions.pending_path(waiting["pending_decision_id"])
            pending = json.loads(pending_path.read_text(encoding="utf-8"))
            pending_path.write_bytes(
                canonical_json_bytes(dict(pending, project_id="OTHER")) + b"\n"
            )
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "pending decision project does not match WAITING_HUMAN state",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).next_action_preview("ftic-governance-1")

            self.assertEqual(tree_bytes(state_root), before)

    def test_next_action_preview_derives_multi_blocker_evidence_counts_from_audit(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(writer, hour=6)
            evidence_dir = state_root / "preview-evidence"
            evidence_dir.mkdir()
            open_a = evidence_dir / "open-a.json"
            open_b = evidence_dir / "open-b.json"
            write_review_finding(open_a, "finding-a", status="OPEN")
            write_review_finding(open_b, "finding-b", status="OPEN")
            writer.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    writer,
                    [open_a, open_b],
                    target="FIX_REQUIRED",
                ),
                created_at_utc="2026-08-27T06:07:00Z",
            )
            before_fix_preview = tree_bytes(state_root)

            fix_preview = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).next_action_preview("ftic-governance-1")
            implementing = next(
                option
                for option in fix_preview["options"]
                if option["target_state"] == "IMPLEMENTING"
            )

            self.assertEqual(
                implementing["evidence_contract"],
                {
                    "status": "BOUND_EXISTING_CONTRACT",
                    "minimum_count": 3,
                    "maximum_count": 3,
                    "ordered_kinds": [
                        "CODER_TASK_PACKET",
                        "CURRENT_BLOCKING_REMEDIATION_EVIDENCE",
                    ],
                    "repeatable_tail": True,
                },
            )
            self.assertEqual(tree_bytes(state_root), before_fix_preview)

            writer.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=write_coder_remediation_handoff_evidence(
                    writer,
                    [open_a, open_b],
                ),
                created_at_utc="2026-08-27T06:08:00Z",
            )
            writer.advance(
                "ftic-governance-1",
                "TASK_REVIEW",
                actor="CODER",
                evidence_paths=write_task_review_evidence(writer),
                created_at_utc="2026-08-27T06:09:00Z",
            )
            before_review_preview = tree_bytes(state_root)

            review_preview = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).next_action_preview("ftic-governance-1")
            integrating = next(
                option
                for option in review_preview["options"]
                if option["target_state"] == "INTEGRATING"
            )

            self.assertEqual(integrating["evidence_contract"]["minimum_count"], 4)
            self.assertIsNone(integrating["evidence_contract"]["maximum_count"])
            self.assertEqual(tree_bytes(state_root), before_review_preview)

    def test_planning_gates_require_planner_actor_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        cases = (
            ("SPEC_READY", False),
            ("PLAN_READY", True),
        )
        for target, enter_spec_ready in cases:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
                engine.intake(valid_intake())
                evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
                for minute, initial_target in enumerate(
                    ("READY_FOR_CLASSIFICATION", "CLASSIFIED"),
                    start=1,
                ):
                    engine.advance(
                        "ftic-governance-1",
                        initial_target,
                        actor="CONTROLLER",
                        evidence_paths=[evidence],
                        created_at_utc=f"2026-08-27T01:0{minute}:00Z",
                    )
                if enter_spec_ready:
                    engine.advance(
                        "ftic-governance-1",
                        "SPEC_READY",
                        actor="PLANNER",
                        evidence_paths=write_planner_transition_evidence(
                            engine,
                            target="SPEC_READY",
                        ),
                        created_at_utc="2026-08-27T01:03:00Z",
                    )
                before_state = engine.status("ftic-governance-1")
                before_audit = engine.audit("ftic-governance-1")

                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    f"{target} requires actor PLANNER",
                ):
                    engine.advance(
                        "ftic-governance-1",
                        target,
                        actor="CONTROLLER",
                        evidence_paths=[evidence],
                        created_at_utc="2026-08-27T01:04:00Z",
                    )

                self.assertEqual(engine.status("ftic-governance-1"), before_state)
                self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_planning_gates_accept_bound_planner_results(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            engine.intake(valid_intake())
            generic_evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            for minute, target in enumerate(
                ("READY_FOR_CLASSIFICATION", "CLASSIFIED"),
                start=1,
            ):
                engine.advance(
                    "ftic-governance-1",
                    target,
                    actor="CONTROLLER",
                    evidence_paths=[generic_evidence],
                    created_at_utc=f"2026-08-27T02:0{minute}:00Z",
                )

            for minute, target in enumerate(("SPEC_READY", "PLAN_READY"), start=3):
                evidence_paths = write_planner_transition_evidence(engine, target=target)
                state = engine.advance(
                    "ftic-governance-1",
                    target,
                    actor="PLANNER",
                    evidence_paths=evidence_paths,
                    created_at_utc=f"2026-08-27T02:0{minute}:00Z",
                )

                self.assertEqual(state["current_state"], target)
                self.assertEqual(
                    [
                        binding["content_sha256"]
                        for binding in engine.audit("ftic-governance-1")[-1][
                            "evidence_bindings"
                        ]
                    ],
                    [hashlib.sha256(path.read_bytes()).hexdigest() for path in evidence_paths],
                )

    def test_planning_gates_reject_unbound_or_invalid_planner_results_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        packet = valid_planner_packet()
        for target in ("SPEC_READY", "PLAN_READY"):
            result = valid_planner_result(recommended_next_state=target)
            cases = (
                (
                    "generic evidence",
                    packet,
                    result,
                    "canonical PLANNER packet and result",
                    True,
                ),
                (
                    "wrong task",
                    dict(packet, task_id="other-task"),
                    result,
                    "project_id and task_id must match",
                    False,
                ),
                (
                    "mismatched packet",
                    packet,
                    dict(result, packet_id="other-planner-v1"),
                    "packet_id does not match",
                    False,
                ),
                (
                    "unfinished result",
                    packet,
                    dict(result, status="NEEDS_CONTEXT"),
                    "completed PLANNER result",
                    False,
                ),
                (
                    "wrong next state",
                    packet,
                    dict(result, recommended_next_state="WAITING_HUMAN"),
                    f"recommend {target}",
                    False,
                ),
            )
            for name, candidate_packet, candidate_result, message, generic_only in cases:
                with (
                    self.subTest(target=target, case=name),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    state_root = Path(tmp) / "state"
                    engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
                    engine.intake(valid_intake())
                    generic_evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
                    for minute, initial_target in enumerate(
                        ("READY_FOR_CLASSIFICATION", "CLASSIFIED"),
                        start=1,
                    ):
                        engine.advance(
                            "ftic-governance-1",
                            initial_target,
                            actor="CONTROLLER",
                            evidence_paths=[generic_evidence],
                            created_at_utc=f"2026-08-27T03:0{minute}:00Z",
                        )
                    if target == "PLAN_READY":
                        engine.advance(
                            "ftic-governance-1",
                            "SPEC_READY",
                            actor="PLANNER",
                            evidence_paths=write_planner_transition_evidence(
                                engine,
                                target="SPEC_READY",
                            ),
                            created_at_utc="2026-08-27T03:03:00Z",
                        )
                    evidence_paths = (
                        [generic_evidence]
                        if generic_only
                        else write_planner_transition_evidence(
                            engine,
                            target=target,
                            packet=candidate_packet,
                            result=candidate_result,
                        )
                    )
                    before_state = engine.status("ftic-governance-1")
                    before_audit = engine.audit("ftic-governance-1")

                    with self.assertRaisesRegex(WorkflowEngineError, message):
                        engine.advance(
                            "ftic-governance-1",
                            target,
                            actor="PLANNER",
                            evidence_paths=evidence_paths,
                            created_at_utc="2026-08-27T03:04:00Z",
                        )

                    self.assertEqual(engine.status("ftic-governance-1"), before_state)
                    self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_planning_gate_rejects_result_replaced_after_validation_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            engine.intake(valid_intake())
            generic_evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            for minute, target in enumerate(
                ("READY_FOR_CLASSIFICATION", "CLASSIFIED"),
                start=1,
            ):
                engine.advance(
                    "ftic-governance-1",
                    target,
                    actor="CONTROLLER",
                    evidence_paths=[generic_evidence],
                    created_at_utc=f"2026-08-27T04:0{minute}:00Z",
                )
            packet_path, result_path = write_planner_transition_evidence(
                engine,
                target="SPEC_READY",
            )
            replacement = dict(
                valid_planner_result(recommended_next_state="SPEC_READY"),
                summary="Planner result was replaced after validation.",
            )
            replacement_payload = canonical_json_bytes(replacement) + b"\n"
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")
            original_binding = engine._path_evidence_binding

            def replace_before_binding(path, *args):
                if Path(path) == result_path:
                    result_path.write_bytes(replacement_payload)
                return original_binding(path, *args)

            with patch.object(
                engine,
                "_path_evidence_binding",
                side_effect=replace_before_binding,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "SPEC_READY evidence changed after validation",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "SPEC_READY",
                    actor="PLANNER",
                    evidence_paths=[packet_path, result_path],
                    created_at_utc="2026-08-27T04:03:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_implementing_requires_coder_actor_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_plan_ready(engine, hour=5)
            packet_path = write_coder_handoff_evidence(engine)
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "IMPLEMENTING requires actor CODER",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "IMPLEMENTING",
                    actor="CONTROLLER",
                    evidence_paths=[packet_path],
                    created_at_utc="2026-08-27T05:05:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_implementing_accepts_coder_packet_bound_to_plan_ready(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_plan_ready(engine, hour=6)
            packet_path = write_coder_handoff_evidence(engine)

            state = engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=[packet_path],
                created_at_utc="2026-08-27T06:05:00Z",
            )

            self.assertEqual(state["current_state"], "IMPLEMENTING")
            self.assertEqual(
                engine.audit("ftic-governance-1")[-1]["evidence_bindings"][0][
                    "content_sha256"
                ],
                hashlib.sha256(packet_path.read_bytes()).hexdigest(),
            )

    def test_implementing_rejects_unbound_or_expanded_coder_packet_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        generic_evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
        valid_packet = valid_coder_handoff_packet()
        expanded_packets = (
            ("changed objective", dict(valid_packet, objective="Expanded objective.")),
            (
                "changed constraints",
                dict(
                    valid_packet,
                    binding_constraints=[
                        *valid_packet["binding_constraints"],
                        "Add an unapproved runtime.",
                    ],
                ),
            ),
            (
                "changed non-goals",
                dict(valid_packet, non_goals=[]),
            ),
            (
                "changed paths",
                dict(
                    valid_packet,
                    relevant_paths=[*valid_packet["relevant_paths"], "extra/path.py"],
                ),
            ),
            (
                "changed acceptance",
                dict(
                    valid_packet,
                    acceptance_criteria=[
                        *valid_packet["acceptance_criteria"],
                        "Unapproved acceptance criterion.",
                    ],
                ),
            ),
        )
        cases = [
            (
                "generic evidence",
                [generic_evidence],
                "evidence is unreadable",
            ),
            (
                "wrong role",
                valid_planner_packet(),
                "supervised coder handoff requires a CODER task packet",
            ),
            (
                "wrong task",
                dict(valid_packet, task_id="other-task"),
                "project_id and task_id must match",
            ),
            *[
                (
                    name,
                    packet,
                    "must preserve the frozen PLAN_READY task boundary",
                )
                for name, packet in expanded_packets
            ],
        ]
        for name, candidate, message in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
                advance_to_plan_ready(engine, hour=7)
                evidence_paths = (
                    candidate
                    if isinstance(candidate, list)
                    else [write_coder_handoff_evidence(engine, packet=candidate)]
                )
                before_state = engine.status("ftic-governance-1")
                before_audit = engine.audit("ftic-governance-1")

                with self.assertRaisesRegex(WorkflowEngineError, message):
                    engine.advance(
                        "ftic-governance-1",
                        "IMPLEMENTING",
                        actor="CODER",
                        evidence_paths=evidence_paths,
                        created_at_utc="2026-08-27T07:05:00Z",
                    )

                self.assertEqual(engine.status("ftic-governance-1"), before_state)
                self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

        with self.subTest(case="extra evidence"), tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_plan_ready(engine, hour=8)
            packet_path = write_coder_handoff_evidence(engine)
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "canonical CODER packet as exactly one evidence file",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "IMPLEMENTING",
                    actor="CODER",
                    evidence_paths=[packet_path, generic_evidence],
                    created_at_utc="2026-08-27T08:05:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_implementing_rejects_packet_replaced_after_validation_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_plan_ready(engine, hour=9)
            packet_path = write_coder_handoff_evidence(engine)
            replacement = dict(
                valid_coder_handoff_packet(),
                objective="Packet replaced after validation.",
            )
            replacement_payload = canonical_json_bytes(replacement) + b"\n"
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")
            original_binding = engine._path_evidence_binding

            def replace_before_binding(path, *args):
                if Path(path) == packet_path:
                    packet_path.write_bytes(replacement_payload)
                return original_binding(path, *args)

            with patch.object(
                engine,
                "_path_evidence_binding",
                side_effect=replace_before_binding,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "IMPLEMENTING evidence changed after validation",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "IMPLEMENTING",
                    actor="CODER",
                    evidence_paths=[packet_path],
                    created_at_utc="2026-08-27T09:05:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_implementing_rejects_planner_packet_replaced_after_bound_read(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_plan_ready(engine, hour=10)
            planner_binding = engine.audit("ftic-governance-1")[-1][
                "evidence_bindings"
            ][0]
            planner_packet_path = engine._bound_evidence_path(planner_binding)
            replacement_planner = dict(
                valid_planner_packet(),
                objective="Expanded objective inserted after the bound read.",
            )
            replacement_payload = canonical_json_bytes(replacement_planner) + b"\n"
            replacement_coder = dict(replacement_planner)
            replacement_coder["packet_id"] = "ftic-governance-1-coder-v1"
            replacement_coder["role"] = "CODER"
            coder_packet_path = write_coder_handoff_evidence(
                engine,
                packet=replacement_coder,
            )
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")
            path_type = type(planner_packet_path)
            original_read_bytes = path_type.read_bytes
            replacement_performed = False

            def replace_after_first_bound_read(path):
                nonlocal replacement_performed
                payload = original_read_bytes(path)
                if Path(path) == planner_packet_path and not replacement_performed:
                    planner_packet_path.write_bytes(replacement_payload)
                    replacement_performed = True
                return payload

            with patch.object(
                path_type,
                "read_bytes",
                autospec=True,
                side_effect=replace_after_first_bound_read,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "CODER packet must preserve the frozen PLAN_READY task boundary",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "IMPLEMENTING",
                    actor="CODER",
                    evidence_paths=[coder_packet_path],
                    created_at_utc="2026-08-27T10:05:00Z",
                )

            self.assertTrue(replacement_performed)
            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_task_review_rejects_unbound_evidence_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            generic_evidence = advance_to_implementing(engine, hour=16)
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "TASK_REVIEW requires the canonical CODER packet and result",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "TASK_REVIEW",
                    actor="CODER",
                    evidence_paths=[generic_evidence],
                    created_at_utc="2026-08-23T16:06:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_task_review_requires_current_completed_coder_result_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        packet = valid_coder_packet()
        result = valid_agent_result()
        cases = (
            (
                "wrong actor",
                "CONTROLLER",
                packet,
                result,
                "TASK_REVIEW requires actor CODER",
            ),
            (
                "wrong task",
                "CODER",
                dict(packet, task_id="other-task"),
                result,
                "project_id and task_id must match",
            ),
            (
                "mismatched packet",
                "CODER",
                packet,
                dict(result, packet_id="other-coder-v1"),
                "packet_id does not match",
            ),
            (
                "unfinished result",
                "CODER",
                packet,
                dict(result, status="NEEDS_CONTEXT"),
                "completed CODER result",
            ),
            (
                "wrong next state",
                "CODER",
                packet,
                dict(result, recommended_next_state="WAITING_HUMAN"),
                "recommend TASK_REVIEW",
            ),
        )
        for name, actor, candidate_packet, candidate_result, message in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
                advance_to_implementing(engine, hour=17)
                packet_path, result_path = write_task_review_evidence(engine)
                packet_path.write_bytes(canonical_json_bytes(candidate_packet) + b"\n")
                result_path.write_bytes(canonical_json_bytes(candidate_result) + b"\n")
                before = tree_bytes(state_root)

                with self.assertRaisesRegex(WorkflowEngineError, message):
                    engine.advance(
                        "ftic-governance-1",
                        "TASK_REVIEW",
                        actor=actor,
                        evidence_paths=[packet_path, result_path],
                        created_at_utc="2026-08-23T17:06:00Z",
                    )

                self.assertEqual(tree_bytes(state_root), before)

    def test_task_review_rejects_result_replaced_after_validation_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_implementing(engine, hour=18)
            packet_path, result_path = write_task_review_evidence(engine)
            replacement = dict(
                valid_agent_result(),
                status="BLOCKED",
                blocker="Coder result was replaced after validation.",
                recommended_next_state="WAITING_HUMAN",
            )
            replacement_payload = canonical_json_bytes(replacement) + b"\n"
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")
            original_binding = engine._path_evidence_binding

            def replace_before_binding(path, *args):
                if Path(path) == result_path:
                    result_path.write_bytes(replacement_payload)
                return original_binding(path, *args)

            with patch.object(
                engine,
                "_path_evidence_binding",
                side_effect=replace_before_binding,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "TASK_REVIEW evidence changed after validation",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "TASK_REVIEW",
                    actor="CODER",
                    evidence_paths=[packet_path, result_path],
                    created_at_utc="2026-08-23T18:06:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_task_review_accepts_bound_reviewer_result_for_review_outcomes(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        cases = (
            ("FIX_REQUIRED", "OPEN"),
            ("INTEGRATING", "CLOSED"),
        )
        for target, finding_status in cases:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
                advance_to_task_review(engine, hour=19)
                finding_path = state_root / "review-finding.json"
                write_review_finding(finding_path, "finding-a", status=finding_status)
                evidence_paths = write_reviewer_transition_evidence(
                    engine,
                    [finding_path],
                    target=target,
                )

                state = engine.advance(
                    "ftic-governance-1",
                    target,
                    actor="REVIEWER",
                    evidence_paths=evidence_paths,
                    created_at_utc="2026-08-23T19:07:00Z",
                )

                self.assertEqual(state["current_state"], target)
                self.assertEqual(
                    [binding["content_sha256"] for binding in engine.audit("ftic-governance-1")[-1]["evidence_bindings"]],
                    [hashlib.sha256(path.read_bytes()).hexdigest() for path in evidence_paths],
                )

    def test_task_review_rejects_unbound_or_invalid_reviewer_result_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        packet = valid_reviewer_packet()
        result = valid_reviewer_result(recommended_next_state="INTEGRATING")
        cases = (
            (
                "finding only",
                packet,
                result,
                "canonical REVIEWER packet and result",
                True,
            ),
            (
                "wrong task",
                dict(packet, task_id="other-task"),
                result,
                "project_id and task_id must match",
                False,
            ),
            (
                "mismatched packet",
                packet,
                dict(result, packet_id="other-reviewer-v1"),
                "packet_id does not match",
                False,
            ),
            (
                "unfinished result",
                packet,
                dict(result, status="NEEDS_CONTEXT"),
                "completed REVIEWER result",
                False,
            ),
            (
                "wrong next state",
                packet,
                dict(result, recommended_next_state="FIX_REQUIRED"),
                "recommend INTEGRATING",
                False,
            ),
        )
        for name, candidate_packet, candidate_result, message, finding_only in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
                advance_to_task_review(engine, hour=20)
                finding_path = state_root / "review-finding.json"
                write_review_finding(finding_path, "finding-a", status="CLOSED")
                evidence_paths = (
                    [finding_path]
                    if finding_only
                    else write_reviewer_transition_evidence(
                        engine,
                        [finding_path],
                        target="INTEGRATING",
                        packet=candidate_packet,
                        result=candidate_result,
                    )
                )
                before_state = engine.status("ftic-governance-1")
                before_audit = engine.audit("ftic-governance-1")

                with self.assertRaisesRegex(WorkflowEngineError, message):
                    engine.advance(
                        "ftic-governance-1",
                        "INTEGRATING",
                        actor="REVIEWER",
                        evidence_paths=evidence_paths,
                        created_at_utc="2026-08-23T20:07:00Z",
                    )

                self.assertEqual(engine.status("ftic-governance-1"), before_state)
                self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_reviewer_transition_rejects_finding_replaced_after_validation_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=21)
            finding_path = state_root / "review-finding.json"
            write_review_finding(finding_path, "finding-a", status="CLOSED")
            evidence_paths = write_reviewer_transition_evidence(
                engine,
                [finding_path],
                target="INTEGRATING",
            )
            replacement = dict(
                valid_review_finding(status="CLOSED"),
                finding_id="finding-replaced",
                review_id="review-finding-replaced",
                summary="Finding replaced after validation.",
                disposition="ALREADY_FIXED",
            )
            replacement_payload = json.dumps(replacement, sort_keys=True).encode("utf-8") + b"\n"
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")
            original_binding = engine._path_evidence_binding

            def replace_before_binding(path, *args):
                if Path(path) == finding_path:
                    finding_path.write_bytes(replacement_payload)
                return original_binding(path, *args)

            with patch.object(
                engine,
                "_path_evidence_binding",
                side_effect=replace_before_binding,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "INTEGRATING evidence changed after validation",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "INTEGRATING",
                    actor="REVIEWER",
                    evidence_paths=evidence_paths,
                    created_at_utc="2026-08-23T21:07:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_governance_task_reaches_rc_ready_with_independent_evidence(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        managed_before = tree_bytes(MVP_FTIC_ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(
                policy_root=ROOT,
                state_root=state_root,
                project_root=MVP_FTIC_ROOT,
                profile_id="ftic-v1",
            )
            state = engine.intake(valid_intake())
            self.assertEqual(state["current_state"], "DRAFT")

            generic_evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            task_review_evidence = write_task_review_evidence(engine)
            for target in (
                "READY_FOR_CLASSIFICATION",
                "CLASSIFIED",
                "SPEC_READY",
                "PLAN_READY",
                "IMPLEMENTING",
                "TASK_REVIEW",
            ):
                planner_gate = target in {"SPEC_READY", "PLAN_READY"}
                state = engine.advance(
                    "ftic-governance-1",
                    target,
                    actor=(
                        "CODER"
                        if target in {"IMPLEMENTING", "TASK_REVIEW"}
                        else "PLANNER" if planner_gate else "CONTROLLER"
                    ),
                    evidence_paths=(
                        task_review_evidence
                        if target == "TASK_REVIEW"
                        else [task_review_evidence[0]]
                        if target == "IMPLEMENTING"
                        else write_planner_transition_evidence(engine, target=target)
                        if planner_gate
                        else [generic_evidence]
                    ),
                    created_at_utc="2026-08-23T01:00:00Z",
                )
                self.assertEqual(state["current_state"], target)
            task_review_bindings = engine.audit("ftic-governance-1")[-1]["evidence_bindings"]
            self.assertEqual(
                [binding["content_sha256"] for binding in task_review_bindings],
                [hashlib.sha256(path.read_bytes()).hexdigest() for path in task_review_evidence],
            )

            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir(exist_ok=True)
            review_path = evidence_dir / "review.json"
            review_path.write_text(json.dumps(valid_review_finding(), sort_keys=True) + "\n", encoding="utf-8")
            reviewer_integration_evidence = write_reviewer_transition_evidence(
                engine,
                [review_path],
                target="INTEGRATING",
            )
            with self.assertRaises(WorkflowEngineError):
                engine.advance(
                    "ftic-governance-1",
                    "INTEGRATING",
                    actor="CODER",
                    evidence_paths=reviewer_integration_evidence,
                    created_at_utc="2026-08-23T01:01:00Z",
                )
            state = engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=reviewer_integration_evidence,
                created_at_utc="2026-08-23T01:01:00Z",
            )
            self.assertEqual(state["current_state"], "INTEGRATING")

            verification_path = evidence_dir / "verification.json"
            foreign_verification = dict(
                valid_verification_record(),
                project_id="OTHER",
                task_id="other-task",
            )
            verification_path.write_text(
                json.dumps(foreign_verification, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            verifier_evidence = write_verifier_transition_evidence(
                engine,
                [verification_path],
            )
            with self.assertRaises(WorkflowEngineError):
                engine.advance(
                    "ftic-governance-1",
                    "VERIFIED",
                    actor="VERIFIER",
                    evidence_paths=verifier_evidence,
                    created_at_utc="2026-08-23T01:02:00Z",
                )
            verification_path.write_text(
                json.dumps(valid_verification_record(), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(WorkflowEngineError):
                engine.advance(
                    "ftic-governance-1",
                    "VERIFIED",
                    actor="CODER",
                    evidence_paths=verifier_evidence,
                    created_at_utc="2026-08-23T01:02:00Z",
                )
            state = engine.advance(
                "ftic-governance-1",
                "VERIFIED",
                actor="VERIFIER",
                evidence_paths=verifier_evidence,
                created_at_utc="2026-08-23T01:02:00Z",
            )
            self.assertEqual(state["current_state"], "VERIFIED")

            source_path = state_root / "source.txt"
            source_path.write_text("frozen governance source\n", encoding="utf-8")
            rollback_path = state_root / "rollback.md"
            rollback_path.write_text("Remove only the generated ACGPS runtime state.\n", encoding="utf-8")
            manifest_path = build_release_candidate_manifest(
                output_dir=state_root,
                project_id="FTIC",
                rc_id="ftic-governance-rc-1",
                version="0.1-dogfood",
                source_path=source_path,
                verification_paths=[verification_path],
                review_paths=[review_path],
                rollback_path=rollback_path,
                created_at_utc="2026-08-23T01:03:00Z",
            )
            with self.assertRaisesRegex(WorkflowEngineError, "RC_READY requires actor VERIFIER"):
                engine.advance(
                    "ftic-governance-1",
                    "RC_READY",
                    actor="CONTROLLER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:04:00Z",
                )
            with self.assertRaisesRegex(
                WorkflowEngineError,
                "RC_READY requires exactly one release-candidate manifest",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "RC_READY",
                    actor="VERIFIER",
                    evidence_paths=[manifest_path, source_path],
                    created_at_utc="2026-08-23T01:04:00Z",
                )
            state = engine.advance(
                "ftic-governance-1",
                "RC_READY",
                actor="VERIFIER",
                evidence_paths=[manifest_path],
                created_at_utc="2026-08-23T01:04:00Z",
            )

            self.assertEqual(state["current_state"], "RC_READY")
            self.assertEqual(len(engine.audit("ftic-governance-1")), 10)
            self.assertEqual(tree_bytes(MVP_FTIC_ROOT), managed_before)

    def test_rc_ready_gate_preview_validates_exact_lineage_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, review_path, verification_paths = prepare_verified_rc_lineage(
                state_root,
                ["verification-current"],
            )
            manifest_path = build_test_release_candidate_manifest(
                writer,
                review_path=review_path,
                verification_paths=verification_paths,
            )
            current = writer.status("ftic-governance-1")
            before = tree_bytes(state_root)

            preview = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).rc_ready_gate_preview(
                "ftic-governance-1",
                manifest_path=manifest_path,
                actor="VERIFIER",
                created_at_utc="2026-08-23T01:10:00Z",
            )

            self.assertEqual(
                preview,
                {
                    "status": "RC_READY_GATE_PREVIEW",
                    "task_id": "ftic-governance-1",
                    "project_id": "FTIC",
                    "current_state": "VERIFIED",
                    "target_state": "RC_READY",
                    "required_actor": "VERIFIER",
                    "evidence_status": "VALIDATED",
                    "manifest_path": "state/release-candidate.json",
                    "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                    "manifest_size_bytes": manifest_path.stat().st_size,
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
                },
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_rc_ready_to_closed_preview_exposes_bound_controller_contract_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, review_path, verification_paths = prepare_verified_rc_lineage(
                state_root,
                ["verification-current"],
            )
            manifest_path = build_test_release_candidate_manifest(
                writer,
                review_path=review_path,
                verification_paths=verification_paths,
            )
            writer.advance(
                "ftic-governance-1",
                "RC_READY",
                actor="VERIFIER",
                evidence_paths=[manifest_path],
                created_at_utc="2026-08-23T01:10:00Z",
            )
            before = tree_bytes(state_root)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            next_action = reader.next_action_preview("ftic-governance-1")
            closed_option = next(
                option
                for option in next_action["options"]
                if option["target_state"] == "CLOSED"
            )
            self.assertEqual(
                closed_option,
                {
                    "target_state": "CLOSED",
                    "required_actor": "CONTROLLER",
                    "evidence_contract": {
                        "status": "BOUND_EXISTING_CONTRACT",
                        "minimum_count": 1,
                        "maximum_count": 1,
                        "ordered_kinds": ["RELEASE_CANDIDATE_MANIFEST"],
                        "repeatable_tail": False,
                    },
                },
            )

            preview = reader.direct_transition_gate_preview(
                "ftic-governance-1",
                "CLOSED",
                actor="CONTROLLER",
                evidence_paths=[manifest_path],
                created_at_utc="2026-08-23T01:11:00Z",
            )

            self.assertEqual(preview["required_actor"], "CONTROLLER")
            self.assertEqual(preview["evidence_status"], "VALIDATED")
            self.assertEqual(preview["authorization_status"], "NOT_GRANTED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_rc_ready_to_closed_rejects_actor_other_than_controller(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            _, manifest_path = prepare_rc_ready_lineage(state_root)
            before = tree_bytes(state_root)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            with self.assertRaisesRegex(WorkflowEngineError, "CLOSED requires actor CONTROLLER"):
                reader.direct_transition_gate_preview(
                    "ftic-governance-1",
                    "CLOSED",
                    actor="VERIFIER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:11:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_rc_ready_to_closed_rejects_manifest_not_bound_by_rc_ready_audit(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            _, manifest_path = prepare_rc_ready_lineage(state_root)
            unbound_manifest_path = manifest_path.with_name("unbound-release-candidate.json")
            unbound_manifest_path.write_bytes(manifest_path.read_bytes())
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "CLOSED manifest must exactly match the trusted RC_READY audit evidence",
            ):
                reader.direct_transition_gate_preview(
                    "ftic-governance-1",
                    "CLOSED",
                    actor="CONTROLLER",
                    evidence_paths=[unbound_manifest_path],
                    created_at_utc="2026-08-23T01:11:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_rc_ready_to_closed_rejects_replaced_bound_manifest(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            _, manifest_path = prepare_rc_ready_lineage(state_root)
            replacement = json.loads(manifest_path.read_text(encoding="utf-8"))
            replacement["rc_id"] = "ftic-governance-rc-replacement"
            manifest_path.write_bytes(canonical_json_bytes(replacement) + b"\n")
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "bound evidence binding content changed",
            ):
                reader.direct_transition_gate_preview(
                    "ftic-governance-1",
                    "CLOSED",
                    actor="CONTROLLER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:11:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_rc_ready_to_closed_commits_exact_manifest_as_controller(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine, manifest_path = prepare_rc_ready_lineage(state_root)

            state = engine.advance(
                "ftic-governance-1",
                "CLOSED",
                actor="CONTROLLER",
                evidence_paths=[manifest_path],
                created_at_utc="2026-08-23T01:11:00Z",
            )

            event = engine.audit("ftic-governance-1")[-1]
            self.assertEqual(state["current_state"], "CLOSED")
            self.assertEqual(event["from_state"], "RC_READY")
            self.assertEqual(event["to_state"], "CLOSED")
            self.assertEqual(event["actor"], "CONTROLLER")
            self.assertEqual(len(event["evidence_bindings"]), 1)
            self.assertEqual(
                event["evidence_bindings"][0]["content_sha256"],
                hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            )

    def test_rc_ready_to_closed_revalidates_references_after_manifest_binding(self) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine, manifest_path = prepare_rc_ready_lineage(state_root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            source_path = manifest_path.parent / manifest["source_artifact"]["path"]
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")
            original_binding = engine._path_evidence_binding

            def mutate_source_after_binding(path, *args):
                binding = original_binding(path, *args)
                if Path(path) == manifest_path:
                    source_path.write_text("mutated after closure binding\n", encoding="utf-8")
                return binding

            with patch.object(
                engine,
                "_path_evidence_binding",
                side_effect=mutate_source_after_binding,
            ), self.assertRaisesRegex(WorkflowEngineError, "artifact hash mismatch: source.txt"):
                engine.advance(
                    "ftic-governance-1",
                    "CLOSED",
                    actor="CONTROLLER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:11:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_rc_ready_to_closed_revalidates_references_before_commit(self) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine, manifest_path = prepare_rc_ready_lineage(state_root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            source_path = manifest_path.parent / manifest["source_artifact"]["path"]
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")
            from acgps import workflow_engine as workflow_engine_module

            original_validate_transition_request = (
                workflow_engine_module.validate_transition_request
            )

            def mutate_source_after_transition_validation(request):
                outcome = original_validate_transition_request(request)
                source_path.write_text("mutated before closure commit\n", encoding="utf-8")
                return outcome

            with patch.object(
                workflow_engine_module,
                "validate_transition_request",
                side_effect=mutate_source_after_transition_validation,
            ), self.assertRaisesRegex(WorkflowEngineError, "artifact hash mismatch: source.txt"):
                engine.advance(
                    "ftic-governance-1",
                    "CLOSED",
                    actor="CONTROLLER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:11:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_rc_ready_gate_preview_rejects_human_gated_policy_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, review_path, verification_paths = prepare_verified_rc_lineage(
                state_root,
                ["verification-current"],
            )
            manifest_path = build_test_release_candidate_manifest(
                writer,
                review_path=review_path,
                verification_paths=verification_paths,
            )
            before = tree_bytes(state_root)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "direct policy-authorized RC_READY transition",
            ):
                reader.rc_ready_gate_preview(
                    "ftic-governance-1",
                    manifest_path=manifest_path,
                    actor="VERIFIER",
                    created_at_utc="2026-08-23T01:10:00Z",
                    human_triggers=["H1_PRODUCT_INTENT"],
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_direct_transition_gate_preview_validates_existing_gate_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_plan_ready(writer, hour=2)
            packet_path = write_coder_handoff_evidence(writer)
            current = writer.status("ftic-governance-1")
            before = tree_bytes(state_root)

            preview = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).direct_transition_gate_preview(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=[packet_path],
                created_at_utc="2026-08-23T02:10:00Z",
            )

            self.assertEqual(preview["status"], "DIRECT_TRANSITION_GATE_PREVIEW")
            self.assertEqual(preview["task_id"], "ftic-governance-1")
            self.assertEqual(preview["project_id"], "FTIC")
            self.assertEqual(preview["current_state"], "PLAN_READY")
            self.assertEqual(preview["target_state"], "IMPLEMENTING")
            self.assertEqual(preview["required_actor"], "CODER")
            self.assertEqual(preview["evidence_status"], "VALIDATED")
            self.assertEqual(len(preview["evidence_bindings"]), 1)
            self.assertEqual(
                preview["evidence_bindings"][0]["path"],
                "state/coder-handoff-evidence/implementing-0006/coder-packet.json",
            )
            self.assertEqual(
                preview["evidence_bindings"][0]["content_sha256"],
                hashlib.sha256(packet_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                preview["evidence_bindings"][0]["size_bytes"],
                packet_path.stat().st_size,
            )
            self.assertEqual(preview["audit_generation"], current["audit_generation"])
            self.assertEqual(preview["audit_head_event_id"], current["audit_head_event_id"])
            self.assertEqual(preview["audit_head_hash"], current["audit_head_hash"])
            self.assertEqual(preview["authorization_status"], "NOT_GRANTED")
            self.assertEqual(
                preview["controls"],
                {
                    "model_execution": "NOT_STARTED",
                    "process_launch": "NOT_STARTED",
                    "state_write": "NOT_PERFORMED",
                    "workflow_transition": "NOT_PERFORMED",
                },
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_direct_transition_gate_preview_rejects_human_gate_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_plan_ready(writer, hour=3)
            packet_path = write_coder_handoff_evidence(writer)
            before = tree_bytes(state_root)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "direct transition gate preview cannot create a WAITING_HUMAN decision",
            ):
                reader.direct_transition_gate_preview(
                    "ftic-governance-1",
                    "IMPLEMENTING",
                    actor="CODER",
                    evidence_paths=[packet_path],
                    created_at_utc="2026-08-23T03:10:00Z",
                    human_triggers=["H1_PRODUCT_INTENT"],
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_direct_transition_gate_preview_rejects_explicit_waiting_human_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_plan_ready(writer, hour=5)
            packet_path = write_coder_handoff_evidence(writer)
            before = tree_bytes(state_root)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            for human_triggers in ([], ["H1_PRODUCT_INTENT"]):
                with self.subTest(human_triggers=human_triggers):
                    with self.assertRaisesRegex(
                        WorkflowEngineError,
                        "direct transition gate preview does not accept WAITING_HUMAN as a target",
                    ):
                        reader.direct_transition_gate_preview(
                            "ftic-governance-1",
                            "WAITING_HUMAN",
                            actor="CODER",
                            evidence_paths=[packet_path],
                            created_at_utc="2026-08-23T05:10:00Z",
                            human_triggers=human_triggers,
                        )
                    self.assertEqual(tree_bytes(state_root), before)

    def test_direct_transition_gate_preview_rejects_waiting_human_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_plan_ready(writer, hour=4)
            packet_path = write_coder_handoff_evidence(writer)
            waiting = writer.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=[packet_path],
                created_at_utc="2026-08-23T04:05:00Z",
                human_triggers=["H1_PRODUCT_INTENT"],
            )
            self.assertEqual(waiting["current_state"], "WAITING_HUMAN")
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "use decision resolution-preview",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).direct_transition_gate_preview(
                    "ftic-governance-1",
                    "IMPLEMENTING",
                    actor="CODER",
                    evidence_paths=[packet_path],
                    created_at_utc="2026-08-23T04:10:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_rc_ready_rejects_manifest_changed_after_validation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            review_path = advance_to_integrating(engine, hour=1)
            verification_path = state_root / "verification.json"
            verification_path.write_bytes(
                canonical_json_bytes(valid_verification_record()) + b"\n"
            )
            engine.advance(
                "ftic-governance-1",
                "VERIFIED",
                actor="VERIFIER",
                evidence_paths=write_verifier_transition_evidence(engine, [verification_path]),
                created_at_utc="2026-08-23T01:08:00Z",
            )
            source_path = state_root / "source.txt"
            source_path.write_text("frozen governance source\n", encoding="utf-8")
            rollback_path = state_root / "rollback.md"
            rollback_path.write_text("Remove generated runtime state.\n", encoding="utf-8")
            manifest_path = build_release_candidate_manifest(
                output_dir=state_root,
                project_id="FTIC",
                rc_id="ftic-governance-rc-1",
                version="1.0",
                source_path=source_path,
                verification_paths=[verification_path],
                review_paths=[review_path],
                rollback_path=rollback_path,
                created_at_utc="2026-08-23T01:09:00Z",
            )
            replacement = json.loads(manifest_path.read_text(encoding="utf-8"))
            replacement["version"] = "1.0-replaced"
            replacement_payload = canonical_json_bytes(replacement) + b"\n"
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")
            original_binding = engine._path_evidence_binding

            def replace_before_binding(path, *args):
                if Path(path) == manifest_path:
                    manifest_path.write_bytes(replacement_payload)
                return original_binding(path, *args)

            with patch.object(
                engine,
                "_path_evidence_binding",
                side_effect=replace_before_binding,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "RC_READY evidence changed after validation",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "RC_READY",
                    actor="VERIFIER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:10:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_rc_ready_rejects_referenced_verification_changed_after_manifest_binding(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine, review_path, verification_paths = prepare_verified_rc_lineage(
                state_root,
                ["verification-current"],
            )
            manifest_path = build_test_release_candidate_manifest(
                engine,
                review_path=review_path,
                verification_paths=verification_paths,
            )
            replacement_payload = canonical_json_bytes(
                dict(
                    valid_verification_record(),
                    verification_id="verification-replaced-after-binding",
                )
            ) + b"\n"
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")
            original_binding = engine._path_evidence_binding

            def replace_reference_after_binding(path, *args):
                binding = original_binding(path, *args)
                if Path(path) == manifest_path:
                    verification_paths[0].write_bytes(replacement_payload)
                return binding

            with patch.object(
                engine,
                "_path_evidence_binding",
                side_effect=replace_reference_after_binding,
            ), self.assertRaises(WorkflowEngineError):
                engine.advance(
                    "ftic-governance-1",
                    "RC_READY",
                    actor="VERIFIER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:10:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_rc_ready_revalidates_nonverification_references_after_manifest_binding(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        cases = (
            ("source artifact", "artifact hash mismatch"),
            ("review closure", "blocking review finding remains open"),
            ("rollback path", "required evidence file is missing"),
        )
        for case_name, expected_error in cases:
            with self.subTest(case=case_name), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                engine, review_path, verification_paths = prepare_verified_rc_lineage(
                    state_root,
                    ["verification-current"],
                )
                manifest_path = build_test_release_candidate_manifest(
                    engine,
                    review_path=review_path,
                    verification_paths=verification_paths,
                )
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                source_path = manifest_path.parent / manifest["source_artifact"]["path"]
                rollback_path = manifest_path.parent / manifest["rollback_plan_path"]
                before_state = engine.status("ftic-governance-1")
                before_audit = engine.audit("ftic-governance-1")
                original_binding = engine._path_evidence_binding

                def mutate_reference_after_binding(path, *args):
                    binding = original_binding(path, *args)
                    if Path(path) == manifest_path:
                        if case_name == "source artifact":
                            source_path.write_text(
                                "mutated governance source\n",
                                encoding="utf-8",
                            )
                        elif case_name == "review closure":
                            review_record = json.loads(
                                review_path.read_text(encoding="utf-8")
                            )
                            review_record["status"] = "OPEN"
                            review_record["disposition"] = "ACCEPTED"
                            review_path.write_bytes(
                                canonical_json_bytes(review_record) + b"\n"
                            )
                        else:
                            rollback_path.unlink()
                    return binding

                with patch.object(
                    engine,
                    "_path_evidence_binding",
                    side_effect=mutate_reference_after_binding,
                ), self.assertRaisesRegex(WorkflowEngineError, expected_error):
                    engine.advance(
                        "ftic-governance-1",
                        "RC_READY",
                        actor="VERIFIER",
                        evidence_paths=[manifest_path],
                        created_at_utc="2026-08-23T01:10:00Z",
                    )

                self.assertEqual(engine.status("ftic-governance-1"), before_state)
                self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_rc_ready_rejects_valid_verification_outside_latest_verified_event(self) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine, review_path, _ = prepare_verified_rc_lineage(
                state_root,
                ["verification-current"],
            )
            stale_path = write_verification_record(
                state_root / "stale-verification.json",
                "verification-stale",
            )
            manifest_path = build_test_release_candidate_manifest(
                engine,
                review_path=review_path,
                verification_paths=[stale_path],
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "latest VERIFIED audit evidence",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "RC_READY",
                    actor="VERIFIER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:10:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1")["current_state"], "VERIFIED")

    def test_rc_ready_rejects_missing_latest_verified_record(self) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine, review_path, verification_paths = prepare_verified_rc_lineage(
                state_root,
                ["verification-a", "verification-b"],
            )
            manifest_path = build_test_release_candidate_manifest(
                engine,
                review_path=review_path,
                verification_paths=verification_paths[:1],
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "latest VERIFIED audit evidence",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "RC_READY",
                    actor="VERIFIER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:10:00Z",
                )

    def test_rc_ready_rejects_additional_verification_record(self) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine, review_path, verification_paths = prepare_verified_rc_lineage(
                state_root,
                ["verification-current"],
            )
            additional_path = write_verification_record(
                state_root / "additional-verification.json",
                "verification-additional",
            )
            manifest_path = build_test_release_candidate_manifest(
                engine,
                review_path=review_path,
                verification_paths=[*verification_paths, additional_path],
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "latest VERIFIED audit evidence",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "RC_READY",
                    actor="VERIFIER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:10:00Z",
                )

    def test_rc_ready_rejects_legacy_record_only_verified_layout(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            review_path = advance_to_integrating(engine, hour=1)
            legacy_paths = [
                write_verification_record(
                    state_root / f"legacy-verification-{index}.json",
                    f"legacy-verification-{index}",
                )
                for index in range(1, 4)
            ]
            legacy_snapshots = [
                engine._read_evidence_json_snapshot(path)[1]
                for path in legacy_paths
            ]
            with patch.object(
                engine,
                "_validate_gate_evidence",
                return_value=legacy_snapshots,
            ):
                engine.advance(
                    "ftic-governance-1",
                    "VERIFIED",
                    actor="VERIFIER",
                    evidence_paths=legacy_paths,
                    created_at_utc="2026-08-23T01:08:00Z",
                )
            manifest_path = build_test_release_candidate_manifest(
                engine,
                review_path=review_path,
                verification_paths=legacy_paths[2:],
            )
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")

            with self.assertRaises(WorkflowEngineError):
                engine.advance(
                    "ftic-governance-1",
                    "RC_READY",
                    actor="VERIFIER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:10:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_rc_ready_rejects_mutated_bound_verifier_packet(self) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine, review_path, verification_paths = prepare_verified_rc_lineage(
                state_root,
                ["verification-current"],
            )
            packet_path = (
                state_root
                / "verifier-transition-evidence"
                / "verifier-packet.json"
            )
            packet_path.write_bytes(
                canonical_json_bytes(
                    dict(valid_verifier_packet(), packet_id="tampered-verifier-packet")
                )
                + b"\n"
            )
            manifest_path = build_test_release_candidate_manifest(
                engine,
                review_path=review_path,
                verification_paths=verification_paths,
            )
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "bound evidence binding content changed",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "RC_READY",
                    actor="VERIFIER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:10:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_rc_ready_accepts_reordered_exact_latest_verified_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine, review_path, verification_paths = prepare_verified_rc_lineage(
                state_root,
                ["verification-a", "verification-b"],
            )
            manifest_path = build_test_release_candidate_manifest(
                engine,
                review_path=review_path,
                verification_paths=list(reversed(verification_paths)),
            )

            state = engine.advance(
                "ftic-governance-1",
                "RC_READY",
                actor="VERIFIER",
                evidence_paths=[manifest_path],
                created_at_utc="2026-08-23T01:10:00Z",
            )

            self.assertEqual(state["current_state"], "RC_READY")

    def test_verified_requires_bound_verifier_result_and_hashes_all_evidence(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_integrating(engine, hour=2)
            verification_path = state_root / "verification.json"
            verification_path.write_bytes(
                canonical_json_bytes(valid_verification_record()) + b"\n"
            )
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "canonical VERIFIER packet and result",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "VERIFIED",
                    actor="VERIFIER",
                    evidence_paths=[verification_path],
                    created_at_utc="2026-08-23T02:08:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)
            evidence_paths = write_verifier_transition_evidence(
                engine,
                [verification_path],
            )
            state = engine.advance(
                "ftic-governance-1",
                "VERIFIED",
                actor="VERIFIER",
                evidence_paths=evidence_paths,
                created_at_utc="2026-08-23T02:09:00Z",
            )

            self.assertEqual(state["current_state"], "VERIFIED")
            self.assertEqual(
                [
                    binding["content_sha256"]
                    for binding in engine.audit("ftic-governance-1")[-1]["evidence_bindings"]
                ],
                [hashlib.sha256(path.read_bytes()).hexdigest() for path in evidence_paths],
            )

    def test_verified_requires_current_completed_verifier_result_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        packet = valid_verifier_packet()
        result = valid_verifier_result()
        verification = valid_verification_record()
        cases = (
            (
                "wrong task",
                dict(packet, task_id="other-task"),
                result,
                verification,
                "project_id and task_id must match",
            ),
            (
                "mismatched packet",
                packet,
                dict(result, packet_id="other-verifier-v1"),
                verification,
                "packet_id does not match",
            ),
            (
                "unfinished result",
                packet,
                dict(result, status="NEEDS_CONTEXT"),
                verification,
                "completed VERIFIER result",
            ),
            (
                "wrong next state",
                packet,
                dict(result, recommended_next_state="WAITING_HUMAN"),
                verification,
                "recommend VERIFIED",
            ),
            (
                "foreign verification",
                packet,
                result,
                dict(verification, task_id="other-task"),
                "verification evidence project_id and task_id must match",
            ),
        )
        for name, candidate_packet, candidate_result, candidate_verification, message in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
                advance_to_integrating(engine, hour=3)
                verification_path = state_root / "verification.json"
                verification_path.write_bytes(
                    canonical_json_bytes(candidate_verification) + b"\n"
                )
                evidence_paths = write_verifier_transition_evidence(
                    engine,
                    [verification_path],
                    packet=candidate_packet,
                    result=candidate_result,
                )
                before = tree_bytes(state_root)

                with self.assertRaisesRegex(WorkflowEngineError, message):
                    engine.advance(
                        "ftic-governance-1",
                        "VERIFIED",
                        actor="VERIFIER",
                        evidence_paths=evidence_paths,
                        created_at_utc="2026-08-23T03:08:00Z",
                    )

                self.assertEqual(tree_bytes(state_root), before)

    def test_verified_rejects_result_replaced_after_validation_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_integrating(engine, hour=4)
            verification_path = state_root / "verification.json"
            verification_path.write_bytes(
                canonical_json_bytes(valid_verification_record()) + b"\n"
            )
            packet_path, result_path, bound_verification_path = write_verifier_transition_evidence(
                engine,
                [verification_path],
            )
            replacement = dict(
                valid_verifier_result(),
                status="BLOCKED",
                blocker="Verifier result was replaced after validation.",
                recommended_next_state="WAITING_HUMAN",
            )
            replacement_payload = canonical_json_bytes(replacement) + b"\n"
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")
            original_binding = engine._path_evidence_binding

            def replace_before_binding(path, *args):
                if Path(path) == result_path:
                    result_path.write_bytes(replacement_payload)
                return original_binding(path, *args)

            with patch.object(
                engine,
                "_path_evidence_binding",
                side_effect=replace_before_binding,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "VERIFIED evidence changed after validation",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "VERIFIED",
                    actor="VERIFIER",
                    evidence_paths=[packet_path, result_path, bound_verification_path],
                    created_at_utc="2026-08-23T04:08:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_verifier_fix_required_binds_failed_verification_for_coder_reentry(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_integrating(engine, hour=5)
            verification_path = state_root / "failed-verification.json"
            failed_verification = dict(
                valid_verification_record(),
                checks=[
                    {
                        "name": "focused",
                        "command": "python -m unittest tests.test_workflow_engine",
                        "exit_code": 1,
                        "result_summary": "failed",
                        "output_path": "evidence/focused.txt",
                    }
                ],
                failed_requirements=["bounded governance flow"],
                recommendation="FIX_REQUIRED",
                verified_at_utc="2026-08-23T05:08:00Z",
            )
            verification_path.write_bytes(
                canonical_json_bytes(failed_verification) + b"\n"
            )
            verifier_result = dict(
                valid_verifier_result(),
                status="DONE_WITH_CONCERNS",
                recommended_next_state="FIX_REQUIRED",
            )

            fix_required = engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="VERIFIER",
                evidence_paths=write_verifier_transition_evidence(
                    engine,
                    [verification_path],
                    result=verifier_result,
                ),
                created_at_utc="2026-08-23T05:09:00Z",
            )
            self.assertEqual(fix_required["current_state"], "FIX_REQUIRED")

            implementing = engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=write_coder_remediation_handoff_evidence(
                    engine,
                    [verification_path],
                ),
                created_at_utc="2026-08-23T05:10:00Z",
            )
            self.assertEqual(implementing["current_state"], "IMPLEMENTING")

            engine.advance(
                "ftic-governance-1",
                "TASK_REVIEW",
                actor="CODER",
                evidence_paths=write_task_review_evidence(engine),
                created_at_utc="2026-08-23T05:11:00Z",
            )
            closed_finding = state_root / "closed-after-remediation.json"
            write_review_finding(
                closed_finding,
                "finding-after-remediation",
                status="CLOSED",
            )
            engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [closed_finding],
                    target="INTEGRATING",
                ),
                created_at_utc="2026-08-23T05:12:00Z",
            )
            successful_verification_path = state_root / "successful-verification.json"
            successful_verification_path.write_bytes(
                canonical_json_bytes(
                    dict(
                        valid_verification_record(),
                        verification_id="verification-after-remediation",
                        verified_at_utc="2026-08-23T05:13:00Z",
                    )
                )
                + b"\n"
            )
            verified = engine.advance(
                "ftic-governance-1",
                "VERIFIED",
                actor="VERIFIER",
                evidence_paths=write_verifier_transition_evidence(
                    engine,
                    [successful_verification_path],
                ),
                created_at_utc="2026-08-23T05:14:00Z",
            )
            self.assertEqual(verified["current_state"], "VERIFIED")

    def test_verifier_fix_required_rejects_nonfailing_evidence_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        cases = (
            (
                "wrong result recommendation",
                dict(valid_verifier_result(), recommended_next_state="VERIFIED"),
                dict(
                    valid_verification_record(),
                    failed_requirements=["bounded governance flow"],
                    recommendation="FIX_REQUIRED",
                ),
                "VERIFIER result must recommend FIX_REQUIRED",
            ),
            (
                "successful verification record",
                dict(
                    valid_verifier_result(),
                    status="DONE_WITH_CONCERNS",
                    recommended_next_state="FIX_REQUIRED",
                ),
                valid_verification_record(),
                "every verification record to recommend FIX_REQUIRED",
            ),
            (
                "missing failed requirements",
                dict(
                    valid_verifier_result(),
                    status="DONE_WITH_CONCERNS",
                    recommended_next_state="FIX_REQUIRED",
                ),
                dict(valid_verification_record(), recommendation="FIX_REQUIRED"),
                "requires failed requirements",
            ),
            (
                "empty failed requirement",
                dict(
                    valid_verifier_result(),
                    status="DONE_WITH_CONCERNS",
                    recommended_next_state="FIX_REQUIRED",
                ),
                dict(
                    valid_verification_record(),
                    failed_requirements=[""],
                    recommendation="FIX_REQUIRED",
                ),
                "requires failed requirements",
            ),
            (
                "whitespace-only failed requirement",
                dict(
                    valid_verifier_result(),
                    status="DONE_WITH_CONCERNS",
                    recommended_next_state="FIX_REQUIRED",
                ),
                dict(
                    valid_verification_record(),
                    failed_requirements=["   "],
                    recommendation="FIX_REQUIRED",
                ),
                "requires failed requirements",
            ),
            (
                "foreign verification record",
                dict(
                    valid_verifier_result(),
                    status="DONE_WITH_CONCERNS",
                    recommended_next_state="FIX_REQUIRED",
                ),
                dict(
                    valid_verification_record(),
                    project_id="OTHER",
                    failed_requirements=["bounded governance flow"],
                    recommendation="FIX_REQUIRED",
                ),
                "project_id and task_id must match",
            ),
        )
        for label, result, verification, expected_error in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
                advance_to_integrating(engine, hour=6)
                verification_path = state_root / "verification.json"
                verification_path.write_bytes(
                    canonical_json_bytes(verification) + b"\n"
                )
                evidence_paths = write_verifier_transition_evidence(
                    engine,
                    [verification_path],
                    result=result,
                )
                before = tree_bytes(state_root)

                with self.assertRaisesRegex(WorkflowEngineError, expected_error):
                    engine.advance(
                        "ftic-governance-1",
                        "FIX_REQUIRED",
                        actor="VERIFIER",
                        evidence_paths=evidence_paths,
                        created_at_utc="2026-08-23T06:09:00Z",
                    )

                self.assertEqual(tree_bytes(state_root), before)

    def test_fix_required_requires_reviewer_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=10)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            open_finding = evidence_dir / "open-a.json"
            write_review_finding(open_finding, "finding-a", status="OPEN")
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(WorkflowEngineError, "FIX_REQUIRED requires actor REVIEWER"):
                engine.advance(
                    "ftic-governance-1",
                    "FIX_REQUIRED",
                    actor="CODER",
                    evidence_paths=[open_finding],
                    created_at_utc="2026-08-23T10:07:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_fix_required_requires_an_open_blocking_finding_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=11)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            closed_finding = evidence_dir / "closed-a.json"
            write_review_finding(closed_finding, "finding-a", status="CLOSED")
            reviewer_fix_evidence = write_reviewer_transition_evidence(
                engine,
                [closed_finding],
                target="FIX_REQUIRED",
            )
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(WorkflowEngineError, "open P0 or P1 review finding"):
                engine.advance(
                    "ftic-governance-1",
                    "FIX_REQUIRED",
                    actor="REVIEWER",
                    evidence_paths=reviewer_fix_evidence,
                    created_at_utc="2026-08-23T11:07:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_fix_required_reentry_rejects_generic_evidence_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            generic_evidence = advance_to_task_review(engine, hour=23)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            open_finding = evidence_dir / "open-a.json"
            write_review_finding(open_finding, "finding-a", status="OPEN")
            engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [open_finding],
                    target="FIX_REQUIRED",
                ),
                created_at_utc="2026-08-23T23:07:00Z",
            )
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "FIX_REQUIRED to IMPLEMENTING requires the canonical CODER packet",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "IMPLEMENTING",
                    actor="CODER",
                    evidence_paths=[generic_evidence],
                    created_at_utc="2026-08-23T23:08:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_fix_required_reentry_requires_coder_actor_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=9)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            open_finding = evidence_dir / "open-a.json"
            write_review_finding(open_finding, "finding-a", status="OPEN")
            engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [open_finding],
                    target="FIX_REQUIRED",
                ),
                created_at_utc="2026-08-24T09:07:00Z",
            )
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")

            with self.assertRaisesRegex(WorkflowEngineError, "IMPLEMENTING requires actor CODER"):
                engine.advance(
                    "ftic-governance-1",
                    "IMPLEMENTING",
                    actor="CONTROLLER",
                    evidence_paths=[write_coder_handoff_evidence(engine), open_finding],
                    created_at_utc="2026-08-24T09:08:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_fix_required_reentry_rejects_foreign_finding_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=8)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            current_finding = evidence_dir / "open-a.json"
            foreign_finding = evidence_dir / "open-b.json"
            write_review_finding(current_finding, "finding-a", status="OPEN")
            write_review_finding(foreign_finding, "finding-b", status="OPEN")
            engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [current_finding],
                    target="FIX_REQUIRED",
                ),
                created_at_utc="2026-08-24T08:07:00Z",
            )
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "current blocking review findings",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "IMPLEMENTING",
                    actor="CODER",
                    evidence_paths=[
                        write_coder_handoff_evidence(engine),
                        foreign_finding,
                    ],
                    created_at_utc="2026-08-24T08:08:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_fix_required_reentry_rejects_expanded_coder_packet_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=7)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            open_finding = evidence_dir / "open-a.json"
            write_review_finding(open_finding, "finding-a", status="OPEN")
            engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [open_finding],
                    target="FIX_REQUIRED",
                ),
                created_at_utc="2026-08-24T07:07:00Z",
            )
            expanded_packet = valid_coder_handoff_packet()
            expanded_packet["binding_constraints"] = [
                *expanded_packet["binding_constraints"],
                "unapproved remediation scope",
            ]
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "CODER packet must preserve the frozen PLAN_READY task boundary",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "IMPLEMENTING",
                    actor="CODER",
                    evidence_paths=[
                        write_coder_handoff_evidence(engine, packet=expanded_packet),
                        open_finding,
                    ],
                    created_at_utc="2026-08-24T07:08:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

    def test_repeated_fix_required_events_accumulate_all_blockers(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=12)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            open_a = evidence_dir / "open-a.json"
            open_b = evidence_dir / "open-b.json"
            write_review_finding(open_a, "finding-a", status="OPEN")
            write_review_finding(open_b, "finding-b", status="OPEN")

            engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [open_a],
                    target="FIX_REQUIRED",
                ),
                created_at_utc="2026-08-23T12:07:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=write_coder_remediation_handoff_evidence(
                    engine,
                    [open_a],
                ),
                created_at_utc="2026-08-23T12:08:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "TASK_REVIEW",
                actor="CODER",
                evidence_paths=write_task_review_evidence(engine),
                created_at_utc="2026-08-23T12:09:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [open_b],
                    target="FIX_REQUIRED",
                ),
                created_at_utc="2026-08-23T12:10:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=write_coder_remediation_handoff_evidence(
                    engine,
                    [open_a, open_b],
                ),
                created_at_utc="2026-08-23T12:11:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "TASK_REVIEW",
                actor="CODER",
                evidence_paths=write_task_review_evidence(engine),
                created_at_utc="2026-08-23T12:12:00Z",
            )
            closed_a = evidence_dir / "closed-a.json"
            closed_b = evidence_dir / "closed-b.json"
            write_review_finding(closed_a, "finding-a", status="CLOSED")
            write_review_finding(closed_b, "finding-b", status="CLOSED")
            unrelated_integration_evidence = write_reviewer_transition_evidence(
                engine,
                [closed_b],
                target="INTEGRATING",
            )
            complete_integration_evidence = write_reviewer_transition_evidence(
                engine,
                [closed_a, closed_b],
                target="INTEGRATING",
            )
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(WorkflowEngineError, "finding-a"):
                engine.advance(
                    "ftic-governance-1",
                    "INTEGRATING",
                    actor="REVIEWER",
                    evidence_paths=unrelated_integration_evidence,
                    created_at_utc="2026-08-23T12:13:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)
            integrated = engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=complete_integration_evidence,
                created_at_utc="2026-08-23T12:14:00Z",
            )
            self.assertEqual(integrated["current_state"], "INTEGRATING")

    def test_repeated_fix_required_events_preserve_duplicate_finding_id_occurrences(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=11)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            first_occurrence = evidence_dir / "first-finding-a.json"
            second_occurrence = evidence_dir / "second-finding-a.json"
            write_review_finding(first_occurrence, "finding-a", status="OPEN")
            write_review_finding(second_occurrence, "finding-a", status="OPEN")

            engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [first_occurrence],
                    target="FIX_REQUIRED",
                ),
                created_at_utc="2026-08-24T11:07:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=write_coder_remediation_handoff_evidence(
                    engine,
                    [first_occurrence],
                ),
                created_at_utc="2026-08-24T11:08:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "TASK_REVIEW",
                actor="CODER",
                evidence_paths=write_task_review_evidence(engine),
                created_at_utc="2026-08-24T11:09:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [second_occurrence],
                    target="FIX_REQUIRED",
                ),
                created_at_utc="2026-08-24T11:10:00Z",
            )

            try:
                implementing = engine.advance(
                    "ftic-governance-1",
                    "IMPLEMENTING",
                    actor="CODER",
                    evidence_paths=write_coder_remediation_handoff_evidence(
                        engine,
                        [first_occurrence, second_occurrence],
                    ),
                    created_at_utc="2026-08-24T11:11:00Z",
                )
            except WorkflowEngineError as exc:
                self.fail(f"valid duplicate finding occurrence was rejected: {exc}")

            self.assertEqual(implementing["current_state"], "IMPLEMENTING")

    def test_reviewer_binding_preserves_legacy_fix_cycle_evidence(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=22)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            legacy_open = evidence_dir / "legacy-open.json"
            write_review_finding(legacy_open, "finding-legacy", status="OPEN")

            with patch.object(engine, "_validate_gate_evidence", return_value=None):
                engine.advance(
                    "ftic-governance-1",
                    "FIX_REQUIRED",
                    actor="REVIEWER",
                    evidence_paths=[legacy_open],
                    created_at_utc="2026-08-23T22:07:00Z",
                )
            engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=write_coder_remediation_handoff_evidence(
                    engine,
                    [legacy_open],
                ),
                created_at_utc="2026-08-23T22:08:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "TASK_REVIEW",
                actor="CODER",
                evidence_paths=write_task_review_evidence(engine),
                created_at_utc="2026-08-23T22:09:00Z",
            )
            closed = evidence_dir / "legacy-closed.json"
            write_review_finding(closed, "finding-legacy", status="CLOSED")

            integrated = engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [closed],
                    target="INTEGRATING",
                ),
                created_at_utc="2026-08-23T22:10:00Z",
            )

            self.assertEqual(integrated["current_state"], "INTEGRATING")

    def test_fix_cycle_rejects_tampered_bound_finding_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=13)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            open_a = evidence_dir / "open-a.json"
            original = write_review_finding(open_a, "finding-a", status="OPEN")
            engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [open_a],
                    target="FIX_REQUIRED",
                ),
                created_at_utc="2026-08-23T13:07:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=write_coder_remediation_handoff_evidence(
                    engine,
                    [open_a],
                ),
                created_at_utc="2026-08-23T13:08:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "TASK_REVIEW",
                actor="CODER",
                evidence_paths=write_task_review_evidence(engine),
                created_at_utc="2026-08-23T13:09:00Z",
            )
            tampered = json.loads(original)
            tampered["summary"] = "Tampered after acceptance."
            open_a.write_text(json.dumps(tampered, sort_keys=True) + "\n", encoding="utf-8")
            closed_a = evidence_dir / "closed-a.json"
            write_review_finding(closed_a, "finding-a", status="CLOSED")
            reviewer_integration_evidence = write_reviewer_transition_evidence(
                engine,
                [closed_a],
                target="INTEGRATING",
            )
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(WorkflowEngineError, "binding content changed"):
                engine.advance(
                    "ftic-governance-1",
                    "INTEGRATING",
                    actor="REVIEWER",
                    evidence_paths=reviewer_integration_evidence,
                    created_at_utc="2026-08-23T13:10:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)
            open_a.write_bytes(original)
            integrated = engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=reviewer_integration_evidence,
                created_at_utc="2026-08-23T13:11:00Z",
            )
            self.assertEqual(integrated["current_state"], "INTEGRATING")

    def test_fix_cycle_survives_audit_generation_recovery(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=14)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            open_a = evidence_dir / "open-a.json"
            write_review_finding(open_a, "finding-a", status="OPEN")
            fixed = engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [open_a],
                    target="FIX_REQUIRED",
                ),
                created_at_utc="2026-08-23T14:07:00Z",
            )
            start_recovery_generation(engine, fixed, created_at_utc="2026-08-23T14:08:00Z")
            engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=write_coder_remediation_handoff_evidence(
                    engine,
                    [open_a],
                ),
                created_at_utc="2026-08-23T14:09:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "TASK_REVIEW",
                actor="CODER",
                evidence_paths=write_task_review_evidence(engine),
                created_at_utc="2026-08-23T14:10:00Z",
            )
            unrelated = evidence_dir / "closed-b.json"
            closed_a = evidence_dir / "closed-a.json"
            write_review_finding(unrelated, "finding-b", status="CLOSED")
            write_review_finding(closed_a, "finding-a", status="CLOSED")
            unrelated_integration_evidence = write_reviewer_transition_evidence(
                engine,
                [unrelated],
                target="INTEGRATING",
            )
            closed_integration_evidence = write_reviewer_transition_evidence(
                engine,
                [closed_a],
                target="INTEGRATING",
            )
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(WorkflowEngineError, "finding-a"):
                engine.advance(
                    "ftic-governance-1",
                    "INTEGRATING",
                    actor="REVIEWER",
                    evidence_paths=unrelated_integration_evidence,
                    created_at_utc="2026-08-23T14:11:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)
            integrated = engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=closed_integration_evidence,
                created_at_utc="2026-08-23T14:12:00Z",
            )
            self.assertEqual(integrated["current_state"], "INTEGRATING")

    def test_reentered_integration_keeps_latest_verification_boundary(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            generic_evidence = advance_to_task_review(engine, hour=15)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            open_a = evidence_dir / "open-a.json"
            closed_a = evidence_dir / "closed-a.json"
            write_review_finding(open_a, "finding-a", status="OPEN")
            write_review_finding(closed_a, "finding-a", status="CLOSED")
            engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [open_a],
                    target="FIX_REQUIRED",
                ),
                created_at_utc="2026-08-23T15:07:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=write_coder_remediation_handoff_evidence(
                    engine,
                    [open_a],
                ),
                created_at_utc="2026-08-23T15:08:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "TASK_REVIEW",
                actor="CODER",
                evidence_paths=write_task_review_evidence(engine),
                created_at_utc="2026-08-23T15:09:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=write_reviewer_transition_evidence(
                    engine,
                    [closed_a],
                    target="INTEGRATING",
                ),
                created_at_utc="2026-08-23T15:10:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "BLOCKED",
                actor="CODER",
                evidence_paths=[generic_evidence],
                created_at_utc="2026-08-23T15:11:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=[closed_a],
                created_at_utc="2026-08-23T15:12:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "SYSTEM_QA",
                actor="VERIFIER",
                evidence_paths=[generic_evidence],
                created_at_utc="2026-08-23T15:13:00Z",
            )
            stale = evidence_dir / "stale-verification.json"
            stale.write_text(
                json.dumps(
                    dict(valid_verification_record(), verified_at_utc="2026-08-23T15:10:30Z"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            stale_evidence = write_verifier_transition_evidence(engine, [stale])
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(WorkflowEngineError, "integration boundary"):
                engine.advance(
                    "ftic-governance-1",
                    "VERIFIED",
                    actor="VERIFIER",
                    evidence_paths=stale_evidence,
                    created_at_utc="2026-08-23T15:14:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)
            fresh = evidence_dir / "fresh-verification.json"
            fresh.write_text(
                json.dumps(
                    dict(valid_verification_record(), verified_at_utc="2026-08-23T15:12:30Z"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            fresh_evidence = write_verifier_transition_evidence(engine, [fresh])
            verified = engine.advance(
                "ftic-governance-1",
                "VERIFIED",
                actor="VERIFIER",
                evidence_paths=fresh_evidence,
                created_at_utc="2026-08-23T15:15:00Z",
            )
            self.assertEqual(verified["current_state"], "VERIFIED")

    def test_illegal_transition_fails_without_advancing_state(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            managed_root = Path(tmp) / "managed"
            shutil.copytree(MVP_FTIC_ROOT, managed_root)
            with self.assertRaises(WorkflowEngineError):
                WorkflowEngine(
                    ROOT,
                    managed_root / ".acgps-state",
                    managed_root,
                    "ftic-v1",
                )

            engine = WorkflowEngine(ROOT, Path(tmp) / "state", MVP_FTIC_ROOT, "ftic-v1")
            engine.intake(valid_intake())

            with self.assertRaises(WorkflowEngineError):
                engine.advance(
                    "ftic-governance-1",
                    "CLASSIFIED",
                    actor="CONTROLLER",
                    evidence_paths=[MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"],
                    created_at_utc="2026-08-23T02:00:00Z",
                )

            self.assertEqual(engine.status("ftic-governance-1")["current_state"], "DRAFT")
            self.assertEqual(len(engine.audit("ftic-governance-1")), 1)

    def test_policy_human_gate_pauses_and_only_matching_resolution_resumes(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            engine = WorkflowEngine(ROOT, Path(tmp) / "state", MVP_FTIC_ROOT, "ftic-v1")
            engine.intake(valid_intake())
            evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            engine.advance(
                "ftic-governance-1",
                "READY_FOR_CLASSIFICATION",
                actor="CONTROLLER",
                evidence_paths=[evidence],
                created_at_utc="2026-08-23T03:00:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "CLASSIFIED",
                actor="CONTROLLER",
                evidence_paths=[evidence],
                created_at_utc="2026-08-23T03:01:00Z",
            )

            waiting = engine.advance(
                "ftic-governance-1",
                "SPEC_READY",
                actor="CONTROLLER",
                evidence_paths=[evidence],
                human_triggers=["H1_PRODUCT_INTENT"],
                created_at_utc="2026-08-23T03:02:00Z",
            )

            self.assertEqual(waiting["current_state"], "WAITING_HUMAN")
            decision_id = waiting["pending_decision_id"]
            pending = engine.decisions.list_pending()
            self.assertEqual([row["decision_id"] for row in pending], [decision_id])
            self.assertEqual(pending[0]["stage"], "SPEC_READY")
            resolution = {
                "schema_version": 1,
                "decision_id": decision_id,
                "project_id": "FTIC",
                "task_id": "ftic-governance-1",
                "selected_option": "RESUME",
                "resolved_by": "human_owner",
                "resolved_at_utc": "2026-08-23T03:03:00Z",
                "rationale": "Approved bounded continuation.",
                "evidence_paths": [],
                "resume_state": "SPEC_READY",
                "status": "RESOLVED",
            }
            with self.assertRaises(WorkflowEngineError):
                engine.advance(
                    "ftic-governance-1",
                    "PLAN_READY",
                    actor="CONTROLLER",
                    evidence_paths=[evidence],
                    decision_resolution=dict(resolution, resume_state="PLAN_READY"),
                    created_at_utc="2026-08-23T03:03:00Z",
                )
            self.assertEqual(
                engine.status("ftic-governance-1")["current_state"],
                "WAITING_HUMAN",
            )
            resumed = engine.advance(
                "ftic-governance-1",
                "SPEC_READY",
                actor="PLANNER",
                evidence_paths=write_planner_transition_evidence(
                    engine,
                    target="SPEC_READY",
                ),
                decision_resolution=resolution,
                created_at_utc="2026-08-23T03:03:00Z",
            )

            self.assertEqual(resumed["current_state"], "SPEC_READY")
            self.assertIsNone(resumed["pending_decision_id"])
            self.assertEqual(engine.decisions.list_pending(), [])

    def test_committed_resolution_remains_clear_after_audit_generation_recovery(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = WorkflowEngine(ROOT, Path(tmp) / "state", MVP_FTIC_ROOT, "ftic-v1")
            engine.intake(valid_intake())
            evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            for index, target in enumerate(("READY_FOR_CLASSIFICATION", "CLASSIFIED"), start=1):
                engine.advance(
                    "ftic-governance-1",
                    target,
                    actor="CONTROLLER",
                    evidence_paths=[evidence],
                    created_at_utc=f"2026-08-23T07:0{index}:00Z",
                )
            waiting = engine.advance(
                "ftic-governance-1",
                "SPEC_READY",
                actor="CONTROLLER",
                evidence_paths=[evidence],
                human_triggers=["H1_PRODUCT_INTENT"],
                created_at_utc="2026-08-23T07:03:00Z",
            )
            resolution = {
                "schema_version": 1,
                "decision_id": waiting["pending_decision_id"],
                "project_id": "FTIC",
                "task_id": "ftic-governance-1",
                "selected_option": "RESUME",
                "resolved_by": "human_owner",
                "resolved_at_utc": "2026-08-23T07:04:00Z",
                "rationale": "Approved bounded continuation.",
                "evidence_paths": [],
                "resume_state": "SPEC_READY",
                "status": "RESOLVED",
            }
            resumed = engine.advance(
                "ftic-governance-1",
                "SPEC_READY",
                actor="PLANNER",
                evidence_paths=write_planner_transition_evidence(
                    engine,
                    target="SPEC_READY",
                ),
                decision_resolution=resolution,
                created_at_utc="2026-08-23T07:04:00Z",
            )

            recovery_event = {
                "schema_version": 1,
                "event_id": "evt-ftic-governance-1-recovery-0001",
                "generation": 2,
                "sequence": 1,
                "project_id": "FTIC",
                "task_id": "ftic-governance-1",
                "event_type": "RECOVERY_RECORDED",
                "actor": "VERIFIER",
                "from_state": None,
                "to_state": None,
                "transition_id": None,
                "policy_evaluation_binding": None,
                "evidence_bindings": [],
                "decision_resolution_binding": None,
                "previous_event_hash": None,
                "event_hash": None,
                "created_at_utc": "2026-08-23T07:05:00Z",
                "details": {
                    "recovery_id": "recovery-ftic-governance-1-0001",
                    "recovery_action": "quarantine_and_start_generation",
                    "recovery_transaction_id": "recovery-tx-ftic-governance-1-0001",
                    "previous_trusted_prefix": {
                        "generation": 1,
                        "sequence": len(engine.audit("ftic-governance-1")),
                        "event_id": resumed["audit_head_event_id"],
                        "event_hash": resumed["audit_head_hash"],
                    },
                    "quarantine_path": "state/quarantine/ftic-governance-1/recovery-0001/audit-tail.bin",
                    "threat_model": "CORRUPTION_AND_NON_COORDINATED_TAMPER_ONLY",
                    "audit_generation": {
                        "schema_version": 1,
                        "generation": 2,
                        "task_id": "ftic-governance-1",
                        "started_by_event_id": "evt-ftic-governance-1-recovery-0001",
                        "started_by_event_type": "RECOVERY_RECORDED",
                        "predecessor_generation": 1,
                        "predecessor_valid_head_hash": resumed["audit_head_hash"],
                        "quarantine_path": "state/quarantine/ftic-governance-1/recovery-0001/audit-tail.bin",
                        "threat_model": "CORRUPTION_AND_NON_COORDINATED_TAMPER_ONLY",
                        "created_at_utc": "2026-08-23T07:05:00Z",
                    },
                },
            }
            recovery_event["event_hash"] = hashlib.sha256(
                canonical_json_bytes(dict(recovery_event, event_hash=None))
            ).hexdigest()
            engine.store.append_audit_event(recovery_event)
            engine.store.write_task_state(
                dict(
                    resumed,
                    audit_generation=2,
                    audit_head_event_id=recovery_event["event_id"],
                    audit_head_hash=recovery_event["event_hash"],
                    updated_at_utc="2026-08-23T07:05:00Z",
                )
            )

            self.assertEqual(engine.decisions.list_pending(), [])

    def test_missing_decision_sidecars_cannot_clear_authoritative_waiting_state(self) -> None:
        from acgps.human_decisions import DecisionQueueError
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            engine = WorkflowEngine(ROOT, Path(tmp) / "state", MVP_FTIC_ROOT, "ftic-v1")
            engine.intake(valid_intake())
            evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            for index, target in enumerate(("READY_FOR_CLASSIFICATION", "CLASSIFIED"), start=1):
                engine.advance(
                    "ftic-governance-1",
                    target,
                    actor="CONTROLLER",
                    evidence_paths=[evidence],
                    created_at_utc=f"2026-08-23T08:0{index}:00Z",
                )
            waiting = engine.advance(
                "ftic-governance-1",
                "SPEC_READY",
                actor="CONTROLLER",
                evidence_paths=[evidence],
                human_triggers=["H1_PRODUCT_INTENT"],
                created_at_utc="2026-08-23T08:03:00Z",
            )
            self.assertEqual(waiting["current_state"], "WAITING_HUMAN")

            shutil.rmtree(engine.decisions.root)

            with self.assertRaisesRegex(DecisionQueueError, "do not match authoritative"):
                engine.decisions.list_pending()

    def test_failed_resume_commit_keeps_matching_request_pending(self) -> None:
        from acgps.workflow_contracts import WorkflowIssue
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError
        from acgps.workflow_store import WorkflowStoreError

        with tempfile.TemporaryDirectory() as tmp:
            engine = WorkflowEngine(ROOT, Path(tmp) / "state", MVP_FTIC_ROOT, "ftic-v1")
            engine.intake(valid_intake())
            evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            for index, target in enumerate(("READY_FOR_CLASSIFICATION", "CLASSIFIED"), start=1):
                engine.advance(
                    "ftic-governance-1",
                    target,
                    actor="CONTROLLER",
                    evidence_paths=[evidence],
                    created_at_utc=f"2026-08-23T05:0{index}:00Z",
                )
            waiting = engine.advance(
                "ftic-governance-1",
                "SPEC_READY",
                actor="CONTROLLER",
                evidence_paths=[evidence],
                human_triggers=["H1_PRODUCT_INTENT"],
                created_at_utc="2026-08-23T05:03:00Z",
            )
            decision_id = waiting["pending_decision_id"]
            resolution = {
                "schema_version": 1,
                "decision_id": decision_id,
                "project_id": "FTIC",
                "task_id": "ftic-governance-1",
                "selected_option": "RESUME",
                "resolved_by": "human_owner",
                "resolved_at_utc": "2026-08-23T05:04:00Z",
                "rationale": "Approved bounded continuation.",
                "evidence_paths": [],
                "resume_state": "SPEC_READY",
                "status": "RESOLVED",
            }
            commit_failure = WorkflowStoreError(
                WorkflowIssue("WORKFLOW_STATE_CORRUPT", "task_state", "injected commit failure")
            )
            resume_evidence = write_planner_transition_evidence(
                engine,
                target="SPEC_READY",
            )

            with patch.object(
                engine.store,
                "commit_task_state_and_audit",
                side_effect=commit_failure,
            ):
                with self.assertRaises(WorkflowEngineError):
                    engine.advance(
                        "ftic-governance-1",
                        "SPEC_READY",
                        actor="PLANNER",
                        evidence_paths=resume_evidence,
                        decision_resolution=resolution,
                        created_at_utc="2026-08-23T05:04:00Z",
                    )

            self.assertEqual(engine.status("ftic-governance-1")["current_state"], "WAITING_HUMAN")
            self.assertTrue(engine.decisions.resolved_path(decision_id).exists())
            self.assertEqual(
                [row["decision_id"] for row in engine.decisions.list_pending()],
                [decision_id],
            )

            resumed = engine.advance(
                "ftic-governance-1",
                "SPEC_READY",
                actor="PLANNER",
                evidence_paths=resume_evidence,
                decision_resolution=resolution,
                created_at_utc="2026-08-23T05:04:00Z",
            )
            self.assertEqual(resumed["current_state"], "SPEC_READY")
            self.assertEqual(engine.decisions.list_pending(), [])

    def test_resolution_publication_failure_does_not_advance_authoritative_state(self) -> None:
        from acgps.human_decisions import DecisionQueueError
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            engine = WorkflowEngine(ROOT, Path(tmp) / "state", MVP_FTIC_ROOT, "ftic-v1")
            engine.intake(valid_intake())
            evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            for index, target in enumerate(("READY_FOR_CLASSIFICATION", "CLASSIFIED"), start=1):
                engine.advance(
                    "ftic-governance-1",
                    target,
                    actor="CONTROLLER",
                    evidence_paths=[evidence],
                    created_at_utc=f"2026-08-23T06:0{index}:00Z",
                )
            waiting = engine.advance(
                "ftic-governance-1",
                "SPEC_READY",
                actor="CONTROLLER",
                evidence_paths=[evidence],
                human_triggers=["H1_PRODUCT_INTENT"],
                created_at_utc="2026-08-23T06:03:00Z",
            )
            decision_id = waiting["pending_decision_id"]
            resolution = {
                "schema_version": 1,
                "decision_id": decision_id,
                "project_id": "FTIC",
                "task_id": "ftic-governance-1",
                "selected_option": "RESUME",
                "resolved_by": "human_owner",
                "resolved_at_utc": "2026-08-23T06:04:00Z",
                "rationale": "Approved bounded continuation.",
                "evidence_paths": [],
                "resume_state": "SPEC_READY",
                "status": "RESOLVED",
            }
            resume_evidence = write_planner_transition_evidence(
                engine,
                target="SPEC_READY",
            )

            with patch.object(
                engine.decisions,
                "resolve",
                side_effect=DecisionQueueError("injected resolution publication failure"),
            ):
                with self.assertRaises(WorkflowEngineError):
                    engine.advance(
                        "ftic-governance-1",
                        "SPEC_READY",
                        actor="PLANNER",
                        evidence_paths=resume_evidence,
                        decision_resolution=resolution,
                        created_at_utc="2026-08-23T06:04:00Z",
                    )

            self.assertEqual(engine.status("ftic-governance-1")["current_state"], "WAITING_HUMAN")
            self.assertEqual(len(engine.audit("ftic-governance-1")), 4)
            self.assertEqual(
                [row["decision_id"] for row in engine.decisions.list_pending()],
                [decision_id],
            )


if __name__ == "__main__":
    unittest.main()
