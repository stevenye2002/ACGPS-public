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


def prepare_r2_classified_packet(
    state_root: Path,
    *,
    role: str = "PLANNER",
):
    from acgps.workflow_engine import WorkflowEngine

    writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
    writer.intake(valid_intake())
    evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
    writer.advance(
        "ftic-governance-1",
        "READY_FOR_CLASSIFICATION",
        actor="CONTROLLER",
        evidence_paths=[evidence],
        created_at_utc="2026-08-29T04:01:00Z",
    )
    writer.advance(
        "ftic-governance-1",
        "CLASSIFIED",
        actor="CONTROLLER",
        evidence_paths=[evidence],
        risk_triggers=["public_api"],
        task_attributes={"change_type": "review_artifact"},
        created_at_utc="2026-08-29T04:02:00Z",
    )
    reader = WorkflowEngine(
        ROOT,
        state_root,
        MVP_FTIC_ROOT,
        "ftic-v1",
        read_only=True,
    )
    policy_result = reader.trusted_classification_policy_result(
        "ftic-governance-1"
    )
    packet = generate_task_packet(role, valid_intake(), policy_result)
    packet_path = state_root / "packets" / f"{role.casefold()}.json"
    packet_path.parent.mkdir(parents=True)
    packet_path.write_bytes(canonical_json_bytes(packet) + b"\n")
    return writer, reader, packet_path, packet


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


def prepare_waiting_human_resume_transition(
    state_root: Path,
    *,
    hour: int = 12,
):
    from acgps.workflow_engine import WorkflowEngine

    writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
    waiting = advance_to_waiting_human(writer, hour=hour)
    resolution = waiting_human_resolution(waiting)
    evidence_paths = write_planner_transition_evidence(
        writer,
        target="SPEC_READY",
    )
    writer.advance(
        "ftic-governance-1",
        "SPEC_READY",
        actor="PLANNER",
        evidence_paths=evidence_paths,
        decision_resolution=resolution,
        created_at_utc=f"2026-08-29T{hour:02d}:04:00Z",
    )
    return writer, resolution, evidence_paths


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


def prepare_committed_rc_ready(
    state_root: Path,
    verification_ids: list[str],
):
    writer, review_path, verification_paths = prepare_verified_rc_lineage(
        state_root,
        verification_ids,
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
    return writer, manifest_path, verification_paths


def prepare_trusted_result_transition(
    state_root: Path,
    *,
    role: str,
):
    writer, _, packet_path, packet = prepare_r2_classified_packet(
        state_root,
        role=role,
    )
    if role != "PLANNER":
        for minute, target in enumerate(("SPEC_READY", "PLAN_READY"), start=3):
            writer.advance(
                "ftic-governance-1",
                target,
                actor="PLANNER",
                evidence_paths=write_planner_transition_evidence(
                    writer,
                    target=target,
                ),
                created_at_utc=f"2026-08-29T08:0{minute}:00Z",
            )
        writer.advance(
            "ftic-governance-1",
            "IMPLEMENTING",
            actor="CODER",
            evidence_paths=[write_coder_handoff_evidence(writer)],
            created_at_utc="2026-08-29T08:05:00Z",
        )
    if role in {"REVIEWER", "VERIFIER"}:
        writer.advance(
            "ftic-governance-1",
            "TASK_REVIEW",
            actor="CODER",
            evidence_paths=write_task_review_evidence(writer),
            created_at_utc="2026-08-29T08:06:00Z",
        )
    if role == "VERIFIER":
        review_path = state_root / "review-closed.json"
        write_review_finding(review_path, "finding-transition", status="CLOSED")
        writer.advance(
            "ftic-governance-1",
            "INTEGRATING",
            actor="REVIEWER",
            evidence_paths=write_reviewer_transition_evidence(
                writer,
                [review_path],
                target="INTEGRATING",
            ),
            created_at_utc="2026-08-29T08:07:00Z",
        )

    target_by_role = {
        "PLANNER": "SPEC_READY",
        "CODER": "TASK_REVIEW",
        "REVIEWER": "INTEGRATING",
        "VERIFIER": "VERIFIED",
    }
    target = target_by_role[role]
    result = dict(
        valid_agent_result(),
        packet_id=packet["packet_id"],
        role=role,
        changed_files=[],
        recommended_next_state=target,
    )
    result_path = state_root / "results" / f"{role.casefold()}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_bytes(canonical_json_bytes(result) + b"\n")
    additional_paths: list[Path] = []
    if role == "REVIEWER":
        finding_path = state_root / "review-result-closed.json"
        write_review_finding(finding_path, "finding-result", status="CLOSED")
        additional_paths.append(finding_path)
    elif role == "VERIFIER":
        additional_paths.append(
            write_verification_record(
                state_root / "verification-result.json",
                "verification-result",
            )
        )
    writer.trusted_task_packet_result_transition_advance(
        "ftic-governance-1",
        packet_path,
        result_path,
        evidence_paths=additional_paths,
        created_at_utc="2026-08-29T08:08:00Z",
    )
    return writer, packet_path, result_path, additional_paths


def prepare_trusted_handoff_transition(
    state_root: Path,
    *,
    remediation: bool,
):
    from acgps.workflow_engine import WorkflowEngine

    writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
    if remediation:
        advance_to_task_review(writer, hour=11)
        finding_path = state_root / "review-open.json"
        write_review_finding(finding_path, "finding-remediation", status="OPEN")
        writer.advance(
            "ftic-governance-1",
            "FIX_REQUIRED",
            actor="REVIEWER",
            evidence_paths=write_reviewer_transition_evidence(
                writer,
                [finding_path],
                target="FIX_REQUIRED",
            ),
            created_at_utc="2026-08-29T11:07:00Z",
        )
        packet_path = write_coder_handoff_evidence(writer)
        evidence_paths = [packet_path, finding_path]
        from_state = "FIX_REQUIRED"
        evidence_kind = "CODER_REMEDIATION_HANDOFF"
    else:
        advance_to_plan_ready(writer, hour=11)
        packet_path = write_coder_handoff_evidence(writer)
        evidence_paths = [packet_path]
        from_state = "PLAN_READY"
        evidence_kind = "CODER_HANDOFF"
    writer.advance(
        "ftic-governance-1",
        "IMPLEMENTING",
        actor="CODER",
        evidence_paths=evidence_paths,
        created_at_utc="2026-08-29T11:08:00Z",
    )
    return writer, packet_path, evidence_paths, from_state, evidence_kind


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
    def test_intake_persists_initialization_idempotency_proof(self) -> None:
        from acgps.workflow_engine import WorkflowEngine
        from acgps.workflow_store import read_idempotency_record

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")

            writer.intake(valid_intake())

            token = hashlib.sha256(b"ftic-governance-1").hexdigest()[:16]
            record = read_idempotency_record(
                state_root,
                "ftic-governance-1",
                "INITIALIZATION",
                f"intake-{token}",
            )
            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record["operation_id"], f"init-{token}")
            self.assertEqual(record["canonical_result"]["audit_event_id"], f"evt-{token}-0001")
            self.assertEqual(record["canonical_result"]["audit_generation"], 1)
            self.assertEqual(record["canonical_result"]["audit_sequence"], 1)

    def test_intake_partial_failure_cannot_rebind_proof_to_changed_content(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            original = valid_intake()
            with patch(
                "acgps.workflow_engine.write_state_atomic",
                side_effect=OSError("simulated intake publication failure"),
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "simulated intake publication failure",
                ):
                    writer.intake(original)
            changed = dict(
                original,
                requested_outcome="Replace the original task objective.",
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "WORKFLOW_IDEMPOTENCY_CONFLICT",
            ):
                writer.intake(changed)

    def test_intake_rejects_historical_task_without_backfilling_initialization_proof(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError
        from acgps.workflow_store import read_idempotency_record

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            intake = valid_intake()
            with patch.object(writer.store, "write_idempotency_record_once"):
                writer.intake(intake)
            evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            for minute, target in enumerate(
                ("READY_FOR_CLASSIFICATION", "CLASSIFIED"),
                start=1,
            ):
                writer.advance(
                    "ftic-governance-1",
                    target,
                    actor="CONTROLLER",
                    evidence_paths=[evidence],
                    created_at_utc=f"2026-08-29T00:3{minute}:00Z",
                )
            token = hashlib.sha256(b"ftic-governance-1").hexdigest()[:16]
            key = f"intake-{token}"
            self.assertIsNone(
                read_idempotency_record(
                    state_root,
                    "ftic-governance-1",
                    "INITIALIZATION",
                    key,
                )
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "WORKFLOW_AUDIT_CORRUPT",
            ):
                writer.intake(intake)

            self.assertIsNone(
                read_idempotency_record(
                    state_root,
                    "ftic-governance-1",
                    "INITIALIZATION",
                    key,
                )
            )

    def test_trusted_classification_policy_result_preserves_accepted_r2_routing_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            writer.intake(valid_intake())
            evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            writer.advance(
                "ftic-governance-1",
                "READY_FOR_CLASSIFICATION",
                actor="CONTROLLER",
                evidence_paths=[evidence],
                created_at_utc="2026-08-29T00:01:00Z",
            )
            writer.advance(
                "ftic-governance-1",
                "CLASSIFIED",
                actor="CONTROLLER",
                evidence_paths=[evidence],
                risk_triggers=["public_api"],
                task_attributes={"change_type": "review_artifact"},
                created_at_utc="2026-08-29T00:02:00Z",
            )
            before = tree_bytes(state_root)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            policy_result = reader.trusted_classification_policy_result(
                "ftic-governance-1"
            )

            self.assertEqual(policy_result["result"]["risk_level"], "R2")
            self.assertEqual(
                policy_result["result"]["required_skills"],
                [
                    "superpowers_writing_plans",
                    "superpowers_requesting_code_review",
                    "superpowers_verification_before_completion",
                ],
            )
            self.assertEqual(
                policy_result["result"]["mandatory_gates"],
                [
                    "architecture",
                    "plan",
                    "broad_verification",
                    "high_capability_review",
                    "rc_evidence",
                ],
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_task_packet_verification_matches_current_trusted_lineage_without_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            _, reader, packet_path, packet = prepare_r2_classified_packet(state_root)
            before = tree_bytes(state_root)

            result = reader.task_packet_verification(
                "ftic-governance-1",
                packet_path,
            )

            self.assertEqual(result["status"], "TASK_PACKET_VERIFIED")
            self.assertEqual(result["task_id"], "ftic-governance-1")
            self.assertEqual(result["role"], "PLANNER")
            self.assertEqual(
                result["packet_sha256"],
                hashlib.sha256(canonical_json_bytes(packet)).hexdigest(),
            )
            self.assertEqual(result["packet_identity_status"], "UNCHANGED_DURING_QUERY")
            self.assertEqual(result["intake_identity_status"], "UNCHANGED_DURING_QUERY")
            self.assertEqual(result["state_identity_status"], "UNCHANGED_DURING_QUERY")
            self.assertEqual(result["audit_identity_status"], "UNCHANGED_DURING_QUERY")
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_task_packet_handoff_preview_accepts_each_supported_role_without_mutation(
        self,
    ) -> None:
        for role in ("PLANNER", "CODER", "REVIEWER", "VERIFIER"):
            with self.subTest(role=role), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                _, reader, packet_path, packet = prepare_r2_classified_packet(
                    state_root,
                    role=role,
                )
                before = tree_bytes(state_root)

                result = reader.trusted_task_packet_handoff_preview(
                    "ftic-governance-1",
                    packet_path,
                )

                self.assertEqual(
                    result["status"],
                    "TRUSTED_TASK_PACKET_HANDOFF_PREVIEW",
                )
                verification = result["task_packet_verification"]
                self.assertEqual(verification["status"], "TASK_PACKET_VERIFIED")
                self.assertEqual(verification["role"], role)
                self.assertEqual(
                    verification["packet_sha256"],
                    hashlib.sha256(canonical_json_bytes(packet)).hexdigest(),
                )
                handoff = result["handoff_preview"]
                self.assertEqual(handoff["status"], "HANDOFF_PREVIEW")
                self.assertEqual(handoff["packet"], packet)
                self.assertEqual(
                    handoff["packet_sha256"],
                    verification["packet_sha256"],
                )
                self.assertEqual(handoff["controls"]["state_write"], "NOT_PERFORMED")
                self.assertEqual(handoff["controls"]["model_execution"], "NOT_STARTED")
                self.assertEqual(handoff["controls"]["process_launch"], "NOT_STARTED")
                self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_task_packet_handoff_preview_rejects_post_verification_packet_drift(
        self,
    ) -> None:
        from acgps.supervised_handoff import (
            build_supervised_planner_handoff_preview,
        )
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, reader, packet_path, _ = prepare_r2_classified_packet(state_root)
            before_status = writer.status("ftic-governance-1")

            def mutate_after_preview(packet: dict[str, object]) -> dict[str, object]:
                preview = build_supervised_planner_handoff_preview(packet)
                packet_path.write_bytes(
                    canonical_json_bytes(
                        dict(packet, objective="Mutated after trusted verification.")
                    )
                    + b"\n"
                )
                return preview

            with patch(
                "acgps.workflow_engine.build_supervised_planner_handoff_preview",
                side_effect=mutate_after_preview,
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "identity changed during trusted handoff preview",
                ):
                    reader.trusted_task_packet_handoff_preview(
                        "ftic-governance-1",
                        packet_path,
                    )

            self.assertEqual(writer.status("ftic-governance-1"), before_status)

    def test_trusted_task_packet_result_receipt_preview_accepts_each_supported_role_without_mutation(
        self,
    ) -> None:
        recommended_states = {
            "PLANNER": "SPEC_READY",
            "CODER": "TASK_REVIEW",
            "REVIEWER": "INTEGRATING",
            "VERIFIER": "VERIFIED",
        }
        for role, recommended_state in recommended_states.items():
            with self.subTest(role=role), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                _, reader, packet_path, packet = prepare_r2_classified_packet(
                    state_root,
                    role=role,
                )
                agent_result = dict(
                    valid_agent_result(),
                    packet_id=packet["packet_id"],
                    role=role,
                    changed_files=[],
                    recommended_next_state=recommended_state,
                )
                result_path = state_root / "results" / f"{role.casefold()}.json"
                result_path.parent.mkdir(parents=True)
                result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
                before = tree_bytes(state_root)

                result = reader.trusted_task_packet_result_receipt_preview(
                    "ftic-governance-1",
                    packet_path,
                    result_path,
                )

                self.assertEqual(
                    result["status"],
                    "TRUSTED_TASK_PACKET_RESULT_RECEIPT_PREVIEW",
                )
                verification = result["task_packet_verification"]
                self.assertEqual(verification["status"], "TASK_PACKET_VERIFIED")
                self.assertEqual(verification["role"], role)
                receipt = result["result_receipt_preview"]
                self.assertEqual(receipt["status"], "RESULT_RECEIPT_PREVIEW")
                self.assertEqual(receipt["packet_id"], packet["packet_id"])
                self.assertEqual(
                    receipt["packet_sha256"],
                    verification["packet_sha256"],
                )
                self.assertEqual(receipt["agent_result"], agent_result)
                self.assertEqual(
                    receipt["agent_result_sha256"],
                    hashlib.sha256(canonical_json_bytes(agent_result)).hexdigest(),
                )
                self.assertEqual(receipt["controls"]["state_write"], "NOT_PERFORMED")
                self.assertEqual(receipt["controls"]["model_execution"], "NOT_STARTED")
                self.assertEqual(receipt["controls"]["process_launch"], "NOT_STARTED")
                self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_task_packet_result_receipt_preview_rejects_post_validation_result_drift(
        self,
    ) -> None:
        from acgps.supervised_handoff import (
            build_supervised_planner_result_receipt_preview,
        )
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, reader, packet_path, packet = prepare_r2_classified_packet(
                state_root
            )
            agent_result = dict(
                valid_agent_result(),
                packet_id=packet["packet_id"],
                role="PLANNER",
                changed_files=[],
                recommended_next_state="SPEC_READY",
            )
            result_path = state_root / "results" / "planner.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
            before_status = writer.status("ftic-governance-1")

            def mutate_after_preview(
                packet_record: dict[str, object],
                result_record: dict[str, object],
            ) -> dict[str, object]:
                preview = build_supervised_planner_result_receipt_preview(
                    packet_record,
                    result_record,
                )
                result_path.write_bytes(
                    canonical_json_bytes(
                        dict(result_record, summary="Mutated after receipt validation.")
                    )
                    + b"\n"
                )
                return preview

            with patch(
                "acgps.workflow_engine.build_supervised_planner_result_receipt_preview",
                side_effect=mutate_after_preview,
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "agent result identity changed during trusted result receipt preview",
                ):
                    reader.trusted_task_packet_result_receipt_preview(
                        "ftic-governance-1",
                        packet_path,
                        result_path,
                    )

            self.assertEqual(writer.status("ftic-governance-1"), before_status)

    def test_trusted_task_packet_result_receipt_preview_rejects_result_drift_during_final_packet_verification(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, reader, packet_path, packet = prepare_r2_classified_packet(
                state_root
            )
            agent_result = dict(
                valid_agent_result(),
                packet_id=packet["packet_id"],
                role="PLANNER",
                changed_files=[],
                recommended_next_state="SPEC_READY",
            )
            result_path = state_root / "results" / "planner.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
            before_status = writer.status("ftic-governance-1")
            real_task_packet_verification = reader.task_packet_verification
            verification_calls = 0

            def mutate_after_final_packet_verification(
                task_id: str,
                current_packet_path: Path,
            ) -> dict[str, object]:
                nonlocal verification_calls
                verification_calls += 1
                verification = real_task_packet_verification(
                    task_id,
                    current_packet_path,
                )
                if verification_calls == 2:
                    result_path.write_bytes(
                        canonical_json_bytes(
                            dict(
                                agent_result,
                                summary="Mutated during final packet verification.",
                            )
                        )
                        + b"\n"
                    )
                return verification

            with patch.object(
                reader,
                "task_packet_verification",
                side_effect=mutate_after_final_packet_verification,
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "agent result identity changed during trusted result receipt preview",
                ):
                    reader.trusted_task_packet_result_receipt_preview(
                        "ftic-governance-1",
                        packet_path,
                        result_path,
                    )

            self.assertEqual(verification_calls, 2)
            self.assertEqual(writer.status("ftic-governance-1"), before_status)

    def test_trusted_result_transition_gate_preview_composes_existing_planner_gate_without_mutation(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            _, reader, packet_path, packet = prepare_r2_classified_packet(state_root)
            agent_result = dict(
                valid_agent_result(),
                packet_id=packet["packet_id"],
                role="PLANNER",
                changed_files=[],
                recommended_next_state="SPEC_READY",
            )
            result_path = state_root / "results" / "planner.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
            before = tree_bytes(state_root)

            preview = reader.trusted_task_packet_result_transition_gate_preview(
                "ftic-governance-1",
                packet_path,
                result_path,
                evidence_paths=[],
                created_at_utc="2026-08-29T05:00:00Z",
            )

            self.assertEqual(
                preview["status"],
                "TRUSTED_TASK_PACKET_RESULT_TO_TRANSITION_GATE_PREVIEW",
            )
            self.assertEqual(
                preview["trusted_result_receipt_preview"]["status"],
                "TRUSTED_TASK_PACKET_RESULT_RECEIPT_PREVIEW",
            )
            gate = preview["transition_gate_preview"]
            self.assertEqual(gate["status"], "DIRECT_TRANSITION_GATE_PREVIEW")
            self.assertEqual(gate["current_state"], "CLASSIFIED")
            self.assertEqual(gate["target_state"], "SPEC_READY")
            self.assertEqual(gate["required_actor"], "PLANNER")
            self.assertEqual(gate["evidence_status"], "VALIDATED")
            self.assertEqual(
                [binding["content_sha256"] for binding in gate["evidence_bindings"]],
                [
                    hashlib.sha256(packet_path.read_bytes()).hexdigest(),
                    hashlib.sha256(result_path.read_bytes()).hexdigest(),
                ],
            )
            self.assertEqual(gate["authorization_status"], "NOT_GRANTED")
            self.assertEqual(gate["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(gate["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_result_transition_gate_preview_rejects_generic_transition_contract(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            _, reader, packet_path, packet = prepare_r2_classified_packet(state_root)
            agent_result = dict(
                valid_agent_result(),
                packet_id=packet["packet_id"],
                role="PLANNER",
                changed_files=[],
                recommended_next_state="ABANDONED",
            )
            result_path = state_root / "results" / "planner.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "does not match the current transition evidence contract",
            ):
                reader.trusted_task_packet_result_transition_gate_preview(
                    "ftic-governance-1",
                    packet_path,
                    result_path,
                    evidence_paths=[],
                    created_at_utc="2026-08-29T05:01:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_result_transition_gate_preview_rejects_result_drift_after_gate_validation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, reader, packet_path, packet = prepare_r2_classified_packet(state_root)
            agent_result = dict(
                valid_agent_result(),
                packet_id=packet["packet_id"],
                role="PLANNER",
                changed_files=[],
                recommended_next_state="SPEC_READY",
            )
            result_path = state_root / "results" / "planner.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
            before_status = writer.status("ftic-governance-1")
            real_gate_preview = reader.direct_transition_gate_preview

            def mutate_after_gate(*args, **kwargs):
                gate_preview = real_gate_preview(*args, **kwargs)
                result_path.write_bytes(
                    canonical_json_bytes(
                        dict(agent_result, summary="Mutated after gate validation.")
                    )
                    + b"\n"
                )
                return gate_preview

            with patch.object(
                reader,
                "direct_transition_gate_preview",
                side_effect=mutate_after_gate,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "identity changed during transition gate preview",
            ):
                reader.trusted_task_packet_result_transition_gate_preview(
                    "ftic-governance-1",
                    packet_path,
                    result_path,
                    evidence_paths=[],
                    created_at_utc="2026-08-29T05:02:00Z",
                )

            self.assertEqual(writer.status("ftic-governance-1"), before_status)

    def test_trusted_result_transition_gate_preview_preserves_reviewer_evidence_tail(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(writer, hour=6)
            finding_path = state_root / "review-finding.json"
            write_review_finding(finding_path, "finding-gate-preview", status="CLOSED")
            packet_path, result_path, bound_finding_path = (
                write_reviewer_transition_evidence(
                    writer,
                    [finding_path],
                    target="INTEGRATING",
                )
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            trusted_packet = generate_task_packet(
                "REVIEWER",
                valid_intake(),
                reader.trusted_classification_policy_result("ftic-governance-1"),
            )
            packet_path.write_bytes(canonical_json_bytes(trusted_packet) + b"\n")
            result_path.write_bytes(
                canonical_json_bytes(
                    dict(
                        valid_reviewer_result(recommended_next_state="INTEGRATING"),
                        packet_id=trusted_packet["packet_id"],
                    )
                )
                + b"\n"
            )
            before = tree_bytes(state_root)

            preview = reader.trusted_task_packet_result_transition_gate_preview(
                "ftic-governance-1",
                packet_path,
                result_path,
                evidence_paths=[bound_finding_path],
                created_at_utc="2026-08-29T06:00:00Z",
            )

            gate = preview["transition_gate_preview"]
            self.assertEqual(gate["target_state"], "INTEGRATING")
            self.assertEqual(gate["required_actor"], "REVIEWER")
            self.assertEqual(
                [binding["content_sha256"] for binding in gate["evidence_bindings"]],
                [
                    hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in (packet_path, result_path, bound_finding_path)
                ],
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_result_transition_advance_commits_planner_result_atomically(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, packet_path, packet = prepare_r2_classified_packet(state_root)
            agent_result = dict(
                valid_agent_result(),
                packet_id=packet["packet_id"],
                role="PLANNER",
                changed_files=[],
                recommended_next_state="SPEC_READY",
            )
            result_path = state_root / "results" / "planner.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")

            state = writer.trusted_task_packet_result_transition_advance(
                "ftic-governance-1",
                packet_path,
                result_path,
                evidence_paths=[],
                created_at_utc="2026-08-29T06:10:00Z",
            )

            self.assertEqual(state["current_state"], "SPEC_READY")
            event = writer.audit("ftic-governance-1")[-1]
            self.assertEqual(event["from_state"], "CLASSIFIED")
            self.assertEqual(event["to_state"], "SPEC_READY")
            self.assertEqual(event["actor"], "PLANNER")
            self.assertEqual(
                [binding["content_sha256"] for binding in event["evidence_bindings"]],
                [
                    hashlib.sha256(packet_path.read_bytes()).hexdigest(),
                    hashlib.sha256(result_path.read_bytes()).hexdigest(),
                ],
            )

    def test_trusted_result_transition_commit_verification_revalidates_tail_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, packet_path, packet = prepare_r2_classified_packet(state_root)
            agent_result = dict(
                valid_agent_result(),
                packet_id=packet["packet_id"],
                role="PLANNER",
                changed_files=[],
                recommended_next_state="SPEC_READY",
            )
            result_path = state_root / "results" / "planner.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
            writer.trusted_task_packet_result_transition_advance(
                "ftic-governance-1",
                packet_path,
                result_path,
                evidence_paths=[],
                created_at_utc="2026-08-29T06:13:00Z",
            )
            before = tree_bytes(state_root)

            result = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).trusted_task_packet_result_transition_commit_verification(
                "ftic-governance-1"
            )

            event = writer.audit("ftic-governance-1")[-1]
            self.assertEqual(
                result["status"],
                "TRUSTED_TASK_PACKET_RESULT_TRANSITION_COMMIT_VERIFIED",
            )
            self.assertEqual(result["transition_id"], event["transition_id"])
            self.assertEqual(result["from_state"], "CLASSIFIED")
            self.assertEqual(result["to_state"], "SPEC_READY")
            self.assertEqual(result["actor"], "PLANNER")
            self.assertEqual(result["packet_id"], packet["packet_id"])
            self.assertEqual(result["role"], "PLANNER")
            self.assertEqual(result["evidence_count"], 2)
            self.assertEqual(result["additional_evidence_count"], 0)
            self.assertEqual(
                result["packet_content_sha256"],
                hashlib.sha256(packet_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                result["result_content_sha256"],
                hashlib.sha256(result_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(result["audit_head_event_id"], event["event_id"])
            self.assertEqual(result["audit_head_hash"], event["event_hash"])
            self.assertEqual(result["state_identity_status"], "UNCHANGED_DURING_QUERY")
            self.assertEqual(result["audit_identity_status"], "UNCHANGED_DURING_QUERY")
            self.assertEqual(result["evidence_identity_status"], "REVALIDATED")
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_handoff_transition_commit_verification_accepts_initial_and_remediation_handoffs(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        for remediation in (False, True):
            with self.subTest(remediation=remediation), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                writer, packet_path, evidence_paths, from_state, evidence_kind = (
                    prepare_trusted_handoff_transition(
                        state_root,
                        remediation=remediation,
                    )
                )
                before = tree_bytes(state_root)

                result = WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).trusted_task_packet_handoff_transition_commit_verification(
                    "ftic-governance-1"
                )

                event = writer.audit("ftic-governance-1")[-1]
                self.assertEqual(
                    result["status"],
                    "TRUSTED_TASK_PACKET_HANDOFF_TRANSITION_COMMIT_VERIFIED",
                )
                self.assertEqual(result["transition_id"], event["transition_id"])
                self.assertEqual(result["from_state"], from_state)
                self.assertEqual(result["to_state"], "IMPLEMENTING")
                self.assertEqual(result["actor"], "CODER")
                self.assertEqual(result["role"], "CODER")
                self.assertEqual(result["evidence_kind"], evidence_kind)
                self.assertEqual(result["evidence_count"], len(evidence_paths))
                self.assertEqual(
                    result["additional_evidence_count"],
                    len(evidence_paths) - 1,
                )
                self.assertEqual(
                    result["packet_content_sha256"],
                    hashlib.sha256(packet_path.read_bytes()).hexdigest(),
                )
                self.assertEqual(result["audit_head_event_id"], event["event_id"])
                self.assertEqual(result["audit_head_hash"], event["event_hash"])
                self.assertEqual(result["state_identity_status"], "UNCHANGED_DURING_QUERY")
                self.assertEqual(result["audit_identity_status"], "UNCHANGED_DURING_QUERY")
                self.assertEqual(result["evidence_identity_status"], "REVALIDATED")
                self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
                self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
                self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_handoff_transition_commit_verification_rejects_bound_evidence_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        for remediation in (False, True):
            with self.subTest(remediation=remediation), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                writer, packet_path, evidence_paths, _, _ = (
                    prepare_trusted_handoff_transition(
                        state_root,
                        remediation=remediation,
                    )
                )
                drift_path = evidence_paths[-1] if remediation else packet_path
                before_state = writer.status("ftic-governance-1")
                before_audit = writer.audit("ftic-governance-1")
                drift_path.write_bytes(drift_path.read_bytes() + b" ")

                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "bound evidence binding content changed",
                ):
                    WorkflowEngine(
                        ROOT,
                        state_root,
                        MVP_FTIC_ROOT,
                        "ftic-v1",
                        read_only=True,
                    ).trusted_task_packet_handoff_transition_commit_verification(
                        "ftic-governance-1"
                    )

                self.assertEqual(writer.status("ftic-governance-1"), before_state)
                self.assertEqual(writer.audit("ftic-governance-1"), before_audit)

    def test_trusted_handoff_transition_commit_verification_rejects_non_handoff_tail(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            writer.intake(valid_intake())
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "authoritative audit tail is not a supported trusted Packet handoff transition",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).trusted_task_packet_handoff_transition_commit_verification(
                    "ftic-governance-1"
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_handoff_transition_commit_verification_rejects_concurrent_state_and_audit_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, _, _, _ = prepare_trusted_handoff_transition(
                state_root,
                remediation=False,
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            validate_frozen_plan = reader._validate_coder_packet_against_frozen_plan
            validation_count = 0

            def advance_after_final_frozen_plan_validation(*args, **kwargs):
                nonlocal validation_count
                result = validate_frozen_plan(*args, **kwargs)
                validation_count += 1
                if validation_count == 2:
                    writer.advance(
                        "ftic-governance-1",
                        "TASK_REVIEW",
                        actor="CODER",
                        evidence_paths=write_task_review_evidence(writer),
                        created_at_utc="2026-08-29T11:09:00Z",
                    )
                return result

            with patch.object(
                reader,
                "_validate_coder_packet_against_frozen_plan",
                side_effect=advance_after_final_frozen_plan_validation,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "trusted handoff transition commit identity changed during verification",
            ):
                reader.trusted_task_packet_handoff_transition_commit_verification(
                    "ftic-governance-1"
                )

    def test_waiting_human_resume_transition_commit_verification_revalidates_committed_resume_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, resolution, evidence_paths = (
                prepare_waiting_human_resume_transition(state_root)
            )
            event = writer.audit("ftic-governance-1")[-1]
            before = tree_bytes(state_root)

            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            verifier = getattr(
                reader,
                "waiting_human_resume_transition_commit_verification",
                None,
            )
            self.assertIsNotNone(verifier, "committed resume verifier is missing")
            result = verifier("ftic-governance-1")

            self.assertEqual(
                result["status"],
                "WAITING_HUMAN_RESUME_TRANSITION_COMMIT_VERIFIED",
            )
            self.assertEqual(result["transition_id"], event["transition_id"])
            self.assertEqual(result["source_state_before_human_gate"], "CLASSIFIED")
            self.assertEqual(result["from_state"], "WAITING_HUMAN")
            self.assertEqual(result["to_state"], "SPEC_READY")
            self.assertEqual(result["actor"], "PLANNER")
            self.assertEqual(result["decision_id"], resolution["decision_id"])
            self.assertEqual(result["evidence_count"], len(evidence_paths))
            self.assertEqual(result["decision_identity_status"], "REVALIDATED")
            self.assertEqual(result["evidence_identity_status"], "REVALIDATED")
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_waiting_human_resume_transition_commit_verification_rejects_target_illegal_from_original_state(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, _ = prepare_waiting_human_resume_transition(
                state_root,
                hour=17,
            )
            before = tree_bytes(state_root)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            reader.bundle.workflow["transitions"]["CLASSIFIED"] = [
                "WAITING_HUMAN",
                "ABANDONED",
            ]

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "resume target SPEC_READY is not legal from original state CLASSIFIED",
            ):
                reader.waiting_human_resume_transition_commit_verification(
                    "ftic-governance-1"
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_waiting_human_resume_transition_commit_verification_accepts_coder_resume_from_frozen_plan(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_plan_ready_to_waiting_human(writer, hour=18)
            resolution = waiting_human_resolution(
                waiting,
                resume_state="IMPLEMENTING",
            )
            coder_packet_path = write_coder_handoff_evidence(writer)
            writer.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=[coder_packet_path],
                decision_resolution=resolution,
                created_at_utc="2026-08-29T18:06:00Z",
            )
            before = tree_bytes(state_root)

            try:
                result = WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).waiting_human_resume_transition_commit_verification(
                    "ftic-governance-1"
                )
            except WorkflowEngineError as exc:
                self.fail(f"valid committed Coder resume was rejected: {exc}")

            self.assertEqual(
                result["status"],
                "WAITING_HUMAN_RESUME_TRANSITION_COMMIT_VERIFIED",
            )
            self.assertEqual(result["source_state_before_human_gate"], "PLAN_READY")
            self.assertEqual(result["from_state"], "WAITING_HUMAN")
            self.assertEqual(result["to_state"], "IMPLEMENTING")
            self.assertEqual(result["actor"], "CODER")
            self.assertEqual(result["evidence_kind"], "CODER_HANDOFF")
            self.assertEqual(result["evidence_count"], 1)
            self.assertEqual(tree_bytes(state_root), before)

    def test_waiting_human_resume_transition_commit_verification_rejects_non_resume_tail(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            writer.intake(valid_intake())
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "authoritative audit tail is not a committed WAITING_HUMAN resume transition",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).waiting_human_resume_transition_commit_verification(
                    "ftic-governance-1"
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_waiting_human_resume_transition_commit_verification_rejects_bound_evidence_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, evidence_paths = prepare_waiting_human_resume_transition(
                state_root,
                hour=13,
            )
            before_state = writer.status("ftic-governance-1")
            before_audit = writer.audit("ftic-governance-1")
            evidence_paths[-1].write_bytes(evidence_paths[-1].read_bytes() + b" ")

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "bound evidence binding content changed",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).waiting_human_resume_transition_commit_verification(
                    "ftic-governance-1"
                )

            self.assertEqual(writer.status("ftic-governance-1"), before_state)
            self.assertEqual(writer.audit("ftic-governance-1"), before_audit)

    def test_waiting_human_resume_transition_commit_verification_rejects_resolution_sidecar_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, resolution, _ = prepare_waiting_human_resume_transition(
                state_root,
                hour=14,
            )
            before_state = writer.status("ftic-governance-1")
            before_audit = writer.audit("ftic-governance-1")
            resolved_path = writer.decisions.resolved_path(resolution["decision_id"])
            resolved_path.write_bytes(
                canonical_json_bytes(
                    dict(resolution, rationale="Changed after the committed resume.")
                )
                + b"\n"
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "resolved decision record does not match the audit binding",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).waiting_human_resume_transition_commit_verification(
                    "ftic-governance-1"
                )

            self.assertEqual(writer.status("ftic-governance-1"), before_state)
            self.assertEqual(writer.audit("ftic-governance-1"), before_audit)

    def test_waiting_human_resume_transition_commit_verification_rejects_pause_request_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, resolution, _ = prepare_waiting_human_resume_transition(
                state_root,
                hour=15,
            )
            before_state = writer.status("ftic-governance-1")
            before_audit = writer.audit("ftic-governance-1")
            pending_path = writer.decisions.pending_path(resolution["decision_id"])
            request = json.loads(pending_path.read_text(encoding="utf-8"))
            pending_path.write_bytes(
                canonical_json_bytes(
                    dict(request, created_at_utc="2026-08-29T15:03:30Z")
                )
                + b"\n"
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "pending decision request does not match the authoritative pause",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).waiting_human_resume_transition_commit_verification(
                    "ftic-governance-1"
                )

            self.assertEqual(writer.status("ftic-governance-1"), before_state)
            self.assertEqual(writer.audit("ftic-governance-1"), before_audit)

    def test_waiting_human_resume_transition_commit_verification_rejects_pending_request_semantic_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, resolution, _ = prepare_waiting_human_resume_transition(
                state_root,
                hour=19,
            )
            before_state = writer.status("ftic-governance-1")
            before_audit = writer.audit("ftic-governance-1")
            pending_path = writer.decisions.pending_path(resolution["decision_id"])
            request = json.loads(pending_path.read_text(encoding="utf-8"))
            pending_path.write_bytes(
                canonical_json_bytes(
                    dict(
                        request,
                        question="Authorize an unrelated transition?",
                    )
                )
                + b"\n"
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "pending decision request does not match the authoritative pause",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).waiting_human_resume_transition_commit_verification(
                    "ftic-governance-1"
                )

            self.assertEqual(writer.status("ftic-governance-1"), before_state)
            self.assertEqual(writer.audit("ftic-governance-1"), before_audit)

    def test_waiting_human_resume_transition_commit_verification_rejects_concurrent_state_and_audit_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, _ = prepare_waiting_human_resume_transition(
                state_root,
                hour=16,
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            validate_gate_evidence = reader._validate_gate_evidence
            advanced = False

            def advance_after_gate_evidence_validation(*args, **kwargs):
                nonlocal advanced
                result = validate_gate_evidence(*args, **kwargs)
                if not advanced:
                    advanced = True
                    writer.advance(
                        "ftic-governance-1",
                        "PLAN_READY",
                        actor="PLANNER",
                        evidence_paths=write_planner_transition_evidence(
                            writer,
                            target="PLAN_READY",
                        ),
                        created_at_utc="2026-08-29T16:05:00Z",
                    )
                return result

            with patch.object(
                reader,
                "_validate_gate_evidence",
                side_effect=advance_after_gate_evidence_validation,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "WAITING_HUMAN resume transition commit identity changed during verification",
            ):
                reader.waiting_human_resume_transition_commit_verification(
                    "ftic-governance-1"
                )

    def test_trusted_result_transition_commit_verification_rejects_non_result_tail(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            writer.intake(valid_intake())
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "authoritative audit tail is not a supported trusted Packet/Result transition",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).trusted_task_packet_result_transition_commit_verification(
                    "ftic-governance-1"
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_result_transition_commit_verification_rejects_bound_result_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, packet_path, packet = prepare_r2_classified_packet(state_root)
            agent_result = dict(
                valid_agent_result(),
                packet_id=packet["packet_id"],
                role="PLANNER",
                changed_files=[],
                recommended_next_state="SPEC_READY",
            )
            result_path = state_root / "results" / "planner.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
            writer.trusted_task_packet_result_transition_advance(
                "ftic-governance-1",
                packet_path,
                result_path,
                evidence_paths=[],
                created_at_utc="2026-08-29T06:14:00Z",
            )
            before_state = writer.status("ftic-governance-1")
            before_audit = writer.audit("ftic-governance-1")
            result_path.write_bytes(
                canonical_json_bytes(dict(agent_result, summary="Tampered after commit."))
                + b"\n"
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "bound evidence binding content changed",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).trusted_task_packet_result_transition_commit_verification(
                    "ftic-governance-1"
                )

            self.assertEqual(writer.status("ftic-governance-1"), before_state)
            self.assertEqual(writer.audit("ftic-governance-1"), before_audit)

    def test_trusted_result_transition_commit_verification_accepts_all_four_roles(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        expected_transitions = {
            "PLANNER": ("CLASSIFIED", "SPEC_READY"),
            "CODER": ("IMPLEMENTING", "TASK_REVIEW"),
            "REVIEWER": ("TASK_REVIEW", "INTEGRATING"),
            "VERIFIER": ("INTEGRATING", "VERIFIED"),
        }
        for role, (from_state, to_state) in expected_transitions.items():
            with self.subTest(role=role), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                writer, _, _, _ = prepare_trusted_result_transition(
                    state_root,
                    role=role,
                )

                result = WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).trusted_task_packet_result_transition_commit_verification(
                    "ftic-governance-1"
                )

                self.assertEqual(result["role"], role)
                self.assertEqual(result["from_state"], from_state)
                self.assertEqual(result["to_state"], to_state)
                self.assertEqual(
                    result["audit_head_event_id"],
                    writer.audit("ftic-governance-1")[-1]["event_id"],
                )

    def test_trusted_result_transition_commit_verification_rejects_waiting_human_resume_tail(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, packet_path, packet = prepare_r2_classified_packet(
                state_root,
                role="CODER",
            )
            for minute, target in enumerate(("SPEC_READY", "PLAN_READY"), start=3):
                writer.advance(
                    "ftic-governance-1",
                    target,
                    actor="PLANNER",
                    evidence_paths=write_planner_transition_evidence(
                        writer,
                        target=target,
                    ),
                    created_at_utc=f"2026-08-29T09:0{minute}:00Z",
                )
            writer.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=[write_coder_handoff_evidence(writer)],
                created_at_utc="2026-08-29T09:05:00Z",
            )
            result = dict(
                valid_agent_result(),
                packet_id=packet["packet_id"],
                role="CODER",
                changed_files=[],
                recommended_next_state="TASK_REVIEW",
            )
            result_path = state_root / "results" / "coder.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_bytes(canonical_json_bytes(result) + b"\n")
            waiting = writer.advance(
                "ftic-governance-1",
                "TASK_REVIEW",
                actor="CONTROLLER",
                evidence_paths=[packet_path, result_path],
                human_triggers=["H1_PRODUCT_INTENT"],
                created_at_utc="2026-08-29T09:06:00Z",
            )
            writer.advance(
                "ftic-governance-1",
                "TASK_REVIEW",
                actor="CODER",
                evidence_paths=[packet_path, result_path],
                decision_resolution=waiting_human_resolution(
                    waiting,
                    resume_state="TASK_REVIEW",
                ),
                created_at_utc="2026-08-29T09:07:00Z",
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "authoritative audit tail is not a supported trusted Packet/Result transition",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).trusted_task_packet_result_transition_commit_verification(
                    "ftic-governance-1"
                )

    def test_trusted_result_transition_commit_verification_rejects_packet_and_additional_evidence_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        scenarios = (("PLANNER", "packet"), ("VERIFIER", "additional"))
        for role, drift_kind in scenarios:
            with self.subTest(role=role, drift_kind=drift_kind), tempfile.TemporaryDirectory() as tmp:
                state_root = Path(tmp) / "state"
                _, packet_path, _, additional_paths = prepare_trusted_result_transition(
                    state_root,
                    role=role,
                )
                drift_path = (
                    packet_path
                    if drift_kind == "packet"
                    else additional_paths[0]
                )
                drift_path.write_bytes(drift_path.read_bytes() + b" ")

                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "bound evidence binding content changed",
                ):
                    WorkflowEngine(
                        ROOT,
                        state_root,
                        MVP_FTIC_ROOT,
                        "ftic-v1",
                        read_only=True,
                    ).trusted_task_packet_result_transition_commit_verification(
                        "ftic-governance-1"
                    )

    def test_trusted_result_transition_commit_verification_rejects_concurrent_state_and_audit_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, _, _ = prepare_trusted_result_transition(
                state_root,
                role="PLANNER",
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            validate_gate_evidence = reader._validate_gate_evidence
            validation_count = 0

            def advance_after_final_evidence_validation(*args, **kwargs):
                nonlocal validation_count
                snapshots = validate_gate_evidence(*args, **kwargs)
                validation_count += 1
                if validation_count == 2:
                    writer.advance(
                        "ftic-governance-1",
                        "PLAN_READY",
                        actor="PLANNER",
                        evidence_paths=write_planner_transition_evidence(
                            writer,
                            target="PLAN_READY",
                        ),
                        created_at_utc="2026-08-29T10:04:00Z",
                    )
                return snapshots

            with patch.object(
                reader,
                "_validate_gate_evidence",
                side_effect=advance_after_final_evidence_validation,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "trusted transition commit identity changed during verification",
            ):
                reader.trusted_task_packet_result_transition_commit_verification(
                    "ftic-governance-1"
                )

    def test_trusted_result_transition_advance_rejects_human_gate_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, packet_path, packet = prepare_r2_classified_packet(state_root)
            agent_result = dict(
                valid_agent_result(),
                packet_id=packet["packet_id"],
                role="PLANNER",
                changed_files=[],
                recommended_next_state="SPEC_READY",
            )
            result_path = state_root / "results" / "planner.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "direct policy-authorized transition",
            ):
                writer.trusted_task_packet_result_transition_advance(
                    "ftic-governance-1",
                    packet_path,
                    result_path,
                    evidence_paths=[],
                    created_at_utc="2026-08-29T06:11:00Z",
                    human_triggers=["H1_PRODUCT_INTENT"],
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_result_transition_advance_rejects_final_result_drift_without_mutation(
        self,
    ) -> None:
        from acgps import workflow_engine as workflow_engine_module
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, packet_path, packet = prepare_r2_classified_packet(state_root)
            agent_result = dict(
                valid_agent_result(),
                packet_id=packet["packet_id"],
                role="PLANNER",
                changed_files=[],
                recommended_next_state="SPEC_READY",
            )
            result_path = state_root / "results" / "planner.json"
            result_path.parent.mkdir(parents=True)
            result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
            before_status = writer.status("ftic-governance-1")
            before_audit = writer.audit("ftic-governance-1")
            real_validate = workflow_engine_module.validate_transition_request

            def mutate_after_request_validation(request):
                outcome = real_validate(request)
                result_path.write_bytes(
                    canonical_json_bytes(
                        dict(agent_result, summary="Mutated before authoritative commit.")
                    )
                    + b"\n"
                )
                return outcome

            with patch(
                "acgps.workflow_engine.validate_transition_request",
                side_effect=mutate_after_request_validation,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "identity changed before trusted transition commit",
            ):
                writer.trusted_task_packet_result_transition_advance(
                    "ftic-governance-1",
                    packet_path,
                    result_path,
                    evidence_paths=[],
                    created_at_utc="2026-08-29T06:12:00Z",
                )

            self.assertEqual(writer.status("ftic-governance-1"), before_status)
            self.assertEqual(writer.audit("ftic-governance-1"), before_audit)

    def test_task_packet_verification_rejects_packet_not_derived_from_current_lineage(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            _, reader, packet_path, packet = prepare_r2_classified_packet(state_root)
            packet_path.write_bytes(
                canonical_json_bytes(
                    dict(packet, objective="Replace the trusted task objective.")
                )
                + b"\n"
            )
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "does not match the current trusted task policy and intake lineage",
            ):
                reader.task_packet_verification("ftic-governance-1", packet_path)

            self.assertEqual(tree_bytes(state_root), before)

    def test_task_packet_verification_rejects_packet_identity_drift(self) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            _, reader, packet_path, packet = prepare_r2_classified_packet(state_root)
            trusted_lookup = reader.trusted_classification_policy_result

            def mutate_packet_after_lookup(task_id, *, intake=None):
                policy_result = trusted_lookup(task_id, intake=intake)
                packet_path.write_bytes(
                    canonical_json_bytes(
                        dict(packet, objective="Drift after trusted lookup.")
                    )
                    + b"\n"
                )
                return policy_result

            with patch.object(
                reader,
                "trusted_classification_policy_result",
                side_effect=mutate_packet_after_lookup,
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "task packet identity changed during task packet verification",
                ):
                    reader.task_packet_verification("ftic-governance-1", packet_path)

    def test_task_packet_verification_rejects_intake_identity_drift(self) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            _, reader, packet_path, _ = prepare_r2_classified_packet(state_root)
            trusted_lookup = reader.trusted_classification_policy_result
            intake_path = state_root / "tasks" / "ftic-governance-1" / "intake.json"

            def mutate_intake_after_lookup(task_id, *, intake=None):
                policy_result = trusted_lookup(task_id, intake=intake)
                changed_intake = dict(
                    intake,
                    requested_outcome="Drift after trusted lookup.",
                )
                intake_path.write_bytes(canonical_json_bytes(changed_intake) + b"\n")
                return policy_result

            with patch.object(
                reader,
                "trusted_classification_policy_result",
                side_effect=mutate_intake_after_lookup,
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "task intake identity changed during task packet verification",
                ):
                    reader.task_packet_verification("ftic-governance-1", packet_path)

    def test_task_packet_verification_rejects_final_task_state_identity_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, reader, packet_path, _ = prepare_r2_classified_packet(state_root)
            trusted_lookup = reader.trusted_classification_policy_result

            def mutate_state_after_lookup(task_id, *, intake=None):
                policy_result = trusted_lookup(task_id, intake=intake)
                current = writer.status(task_id)
                writer.store.write_task_state(
                    dict(current, updated_at_utc="2026-08-29T04:03:00Z")
                )
                return policy_result

            with patch.object(
                reader,
                "trusted_classification_policy_result",
                side_effect=mutate_state_after_lookup,
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "task state identity changed during task packet verification",
                ):
                    reader.task_packet_verification("ftic-governance-1", packet_path)

    def test_task_packet_verification_rejects_final_audit_lineage_identity_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            _, reader, packet_path, _ = prepare_r2_classified_packet(state_root)
            trusted_lookup = reader.trusted_classification_policy_result
            trusted_lineage = reader._trusted_audit_lineage
            lookup_complete = False

            def mark_lookup_complete(task_id, *, intake=None):
                nonlocal lookup_complete
                policy_result = trusted_lookup(task_id, intake=intake)
                lookup_complete = True
                return policy_result

            def drift_after_lookup(current):
                lineage = trusted_lineage(current)
                if not lookup_complete:
                    return lineage
                return [*lineage[:-1], dict(lineage[-1], sequence=999)]

            with (
                patch.object(
                    reader,
                    "trusted_classification_policy_result",
                    side_effect=mark_lookup_complete,
                ),
                patch.object(
                    reader,
                    "_trusted_audit_lineage",
                    side_effect=drift_after_lookup,
                ),
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "audit lineage identity changed during task packet verification",
                ):
                    reader.task_packet_verification("ftic-governance-1", packet_path)

    def test_trusted_classification_policy_result_rejects_before_classification_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            writer.intake(valid_intake())
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
                "exactly one trusted accepted CLASSIFIED policy",
            ):
                reader.trusted_classification_policy_result("ftic-governance-1")

            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_classification_policy_result_rejects_state_not_bound_to_audit_tail(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            writer.intake(valid_intake())
            evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            for minute, target in enumerate(
                ("READY_FOR_CLASSIFICATION", "CLASSIFIED"),
                start=1,
            ):
                writer.advance(
                    "ftic-governance-1",
                    target,
                    actor="CONTROLLER",
                    evidence_paths=[evidence],
                    created_at_utc=f"2026-08-29T00:1{minute}:00Z",
                )
            current = writer.status("ftic-governance-1")
            writer.store.write_task_state(dict(current, current_state="SPEC_READY"))
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "task state does not match the trusted audit tail",
            ):
                reader.trusted_classification_policy_result("ftic-governance-1")

    def test_trusted_classification_policy_result_rejects_pending_decision_state_tail_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=9)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            self.assertEqual(
                reader.trusted_classification_policy_result("ftic-governance-1")["result"][
                    "risk_level"
                ],
                "R0",
            )
            writer.store.write_task_state(
                dict(waiting, pending_decision_id="decision-foreign-valid")
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "task state does not match the trusted audit tail",
            ):
                reader.trusted_classification_policy_result("ftic-governance-1")

    def test_trusted_classification_policy_result_rejects_missing_initialization_proof(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            with patch.object(writer.store, "write_idempotency_record_once"):
                writer.intake(valid_intake())
            evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            for minute, target in enumerate(
                ("READY_FOR_CLASSIFICATION", "CLASSIFIED"),
                start=1,
            ):
                writer.advance(
                    "ftic-governance-1",
                    target,
                    actor="CONTROLLER",
                    evidence_paths=[evidence],
                    created_at_utc=f"2026-08-29T00:2{minute}:00Z",
                )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "trusted initialization proof is missing",
            ):
                reader.trusted_classification_policy_result("ftic-governance-1")

    def test_trusted_classification_policy_result_rejects_task_state_identity_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            writer.intake(valid_intake())
            evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            for minute, target in enumerate(
                ("READY_FOR_CLASSIFICATION", "CLASSIFIED"),
                start=1,
            ):
                writer.advance(
                    "ftic-governance-1",
                    target,
                    actor="CONTROLLER",
                    evidence_paths=[evidence],
                    created_at_utc=f"2026-08-29T01:0{minute}:00Z",
                )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            initial = reader.status("ftic-governance-1")
            changed = dict(initial, updated_at_utc="2026-08-29T01:03:00Z")

            with patch.object(reader, "status", side_effect=[initial, changed]):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "task state identity changed during classification policy lookup",
                ):
                    reader.trusted_classification_policy_result("ftic-governance-1")

    def test_trusted_classification_policy_result_rejects_audit_lineage_identity_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            writer.intake(valid_intake())
            evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
            for minute, target in enumerate(
                ("READY_FOR_CLASSIFICATION", "CLASSIFIED"),
                start=1,
            ):
                writer.advance(
                    "ftic-governance-1",
                    target,
                    actor="CONTROLLER",
                    evidence_paths=[evidence],
                    created_at_utc=f"2026-08-29T02:0{minute}:00Z",
                )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            current = reader.status("ftic-governance-1")
            initial_lineage = reader._trusted_audit_lineage(current)
            changed_lineage = [*initial_lineage, dict(initial_lineage[-1], sequence=4)]

            with (
                patch.object(reader, "status", side_effect=[current, current]),
                patch.object(
                    reader,
                    "_trusted_audit_lineage",
                    side_effect=[initial_lineage, changed_lineage],
                ),
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "audit lineage identity changed during classification policy lookup",
                ):
                    reader.trusted_classification_policy_result("ftic-governance-1")

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

    def test_trusted_task_progress_summary_composes_existing_read_only_contracts(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            current = writer.intake(valid_intake())
            before = tree_bytes(state_root)

            result = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).trusted_task_progress_summary("ftic-governance-1")

            self.assertEqual(result["status"], "TRUSTED_TASK_PROGRESS_SUMMARY")
            self.assertEqual(result["task_id"], "ftic-governance-1")
            self.assertEqual(result["project_id"], "FTIC")
            self.assertEqual(result["current_state"], "DRAFT")
            self.assertEqual(result["audit_generation"], 1)
            self.assertEqual(result["audit_head_event_id"], current["audit_head_event_id"])
            self.assertEqual(result["audit_head_hash"], current["audit_head_hash"])
            self.assertEqual(
                result["audit_verification"]["status"],
                "AUDIT_LINEAGE_VERIFIED",
            )
            self.assertEqual(
                result["next_action_preview"]["status"],
                "NEXT_ACTION_PREVIEW",
            )
            self.assertEqual(
                [
                    option["target_state"]
                    for option in result["next_action_preview"]["options"]
                ],
                ["READY_FOR_CLASSIFICATION", "ABANDONED"],
            )
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_task_progress_summary_binds_waiting_human_requirement(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=7)
            before = tree_bytes(state_root)

            result = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).trusted_task_progress_summary("ftic-governance-1")

            self.assertEqual(result["current_state"], "WAITING_HUMAN")
            self.assertEqual(
                result["next_action_preview"]["pending_decision_requirement"],
                {
                    "decision_id": waiting["pending_decision_id"],
                    "status": "PENDING",
                    "required_resume_state": "SPEC_READY",
                    "allowed_option_ids": ["RESUME"],
                    "default_without_response": "PAUSE",
                    "resolution_required": True,
                },
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_task_progress_summary_reports_closed_as_terminal(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, manifest_path = prepare_rc_ready_lineage(state_root)
            writer.advance(
                "ftic-governance-1",
                "CLOSED",
                actor="CONTROLLER",
                evidence_paths=[manifest_path],
                created_at_utc="2026-08-23T01:11:00Z",
            )
            before = tree_bytes(state_root)

            result = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).trusted_task_progress_summary("ftic-governance-1")

            self.assertEqual(result["current_state"], "CLOSED")
            self.assertEqual(result["next_action_preview"]["options"], [])
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_task_progress_summary_rejects_component_identity_mismatch(
        self,
    ) -> None:
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
            preview = reader.next_action_preview("ftic-governance-1")
            mismatched_preview = dict(preview, audit_head_hash="0" * 64)

            with patch.object(
                reader,
                "next_action_preview",
                return_value=mismatched_preview,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "progress summary components do not share one task and audit identity",
            ):
                reader.trusted_task_progress_summary("ftic-governance-1")

    def test_trusted_task_progress_summary_rejects_final_audit_drift(self) -> None:
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
            initial = reader.audit_lineage_verification("ftic-governance-1")
            changed = dict(initial, trusted_event_count=initial["trusted_event_count"] + 1)

            with patch.object(
                reader,
                "audit_lineage_verification",
                side_effect=[initial, changed],
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "audit lineage identity changed during task progress summary",
            ):
                reader.trusted_task_progress_summary("ftic-governance-1")

    def test_trusted_task_progress_summary_rejects_pending_decision_drift(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_waiting_human(writer, hour=7)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            initial = reader.next_action_preview("ftic-governance-1")
            changed = json.loads(json.dumps(initial))
            changed["pending_decision_requirement"]["default_without_response"] = "RESUME"

            with patch.object(
                reader,
                "next_action_preview",
                side_effect=[initial, changed],
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "next action identity changed during task progress summary",
            ):
                reader.trusted_task_progress_summary("ftic-governance-1")

    def test_trusted_project_progress_summary_composes_all_project_tasks_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            first_intake = valid_intake()
            second_intake = dict(
                first_intake,
                task_id="ftic-governance-2",
                title="Second bounded FTIC governance task",
                created_at_utc="2026-08-23T00:10:00Z",
            )
            writer.intake(first_intake)
            writer.intake(second_intake)
            before = tree_bytes(state_root)

            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            result = reader.trusted_project_progress_summary()

            self.assertEqual(result["status"], "TRUSTED_PROJECT_PROGRESS_SUMMARY")
            self.assertEqual(result["project_id"], "FTIC")
            self.assertEqual(result["task_count"], 2)
            self.assertEqual(result["state_counts"], {"DRAFT": 2})
            self.assertEqual(
                [task["task_id"] for task in result["tasks"]],
                ["ftic-governance-1", "ftic-governance-2"],
            )
            self.assertTrue(
                all(
                    task["status"] == "TRUSTED_TASK_PROGRESS_SUMMARY"
                    for task in result["tasks"]
                )
            )
            self.assertEqual(
                result["control_store_authority"],
                {
                    "authority_id": reader.store.control_authority_id,
                    "authority_generation": reader.store.control_authority_generation,
                },
            )
            self.assertEqual(
                result["task_set_identity_status"],
                "UNCHANGED_DURING_QUERY",
            )
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_assurance_overview_composes_existing_components_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            first_intake = valid_intake()
            second_intake = dict(
                first_intake,
                task_id="ftic-governance-2",
                title="Second bounded FTIC governance task",
                created_at_utc="2026-08-23T00:10:00Z",
            )
            writer.intake(first_intake)
            writer.intake(second_intake)
            before = tree_bytes(state_root)

            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            result = reader.trusted_project_assurance_overview()

            self.assertEqual(result["status"], "TRUSTED_PROJECT_ASSURANCE_OVERVIEW")
            self.assertEqual(result["project_id"], "FTIC")
            self.assertEqual(result["task_count"], 2)
            self.assertEqual(result["state_counts"], {"DRAFT": 2})
            self.assertEqual(
                [task["task_id"] for task in result["progress_summary"]["tasks"]],
                ["ftic-governance-1", "ftic-governance-2"],
            )
            self.assertEqual(
                result["audit_lineage_summary"]["tasks"],
                [
                    task["audit_verification"]
                    for task in result["progress_summary"]["tasks"]
                ],
            )
            self.assertEqual(
                result["next_action_queue"]["queue"],
                [
                    task["next_action_preview"]
                    for task in result["progress_summary"]["tasks"]
                ],
            )
            self.assertEqual(result["pending_decision_queue"]["queue_status"], "CLEAR")
            self.assertEqual(result["component_identity_status"], "CONSISTENT")
            self.assertEqual(
                result["overview_identity_status"],
                "UNCHANGED_DURING_QUERY",
            )
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_assurance_overview_rejects_component_identity_mismatch(
        self,
    ) -> None:
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
            audit_summary = reader.trusted_project_audit_lineage_summary()
            mismatched_audit = dict(audit_summary, project_id="OTHER")

            with patch.object(
                reader,
                "trusted_project_audit_lineage_summary",
                return_value=mismatched_audit,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "assurance overview components do not share one project identity",
            ):
                reader.trusted_project_assurance_overview()

    def test_trusted_project_assurance_overview_rejects_final_component_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            first_state_root = Path(tmp) / "first-state"
            first_writer = WorkflowEngine(
                ROOT,
                first_state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
            )
            first_writer.intake(valid_intake())
            reader = WorkflowEngine(
                ROOT,
                first_state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            initial_components = (
                reader.trusted_project_progress_summary(),
                reader.trusted_project_audit_lineage_summary(),
                reader.trusted_project_next_action_queue(),
                reader.trusted_project_pending_decision_queue(),
            )

            second_state_root = Path(tmp) / "second-state"
            second_writer = WorkflowEngine(
                ROOT,
                second_state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
            )
            second_writer.intake(valid_intake())
            second_writer.intake(
                dict(
                    valid_intake(),
                    task_id="ftic-governance-2",
                    title="Second bounded FTIC governance task",
                    created_at_utc="2026-08-23T00:10:00Z",
                )
            )
            second_reader = WorkflowEngine(
                ROOT,
                second_state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            final_components = (
                second_reader.trusted_project_progress_summary(),
                second_reader.trusted_project_audit_lineage_summary(),
                second_reader.trusted_project_next_action_queue(),
                second_reader.trusted_project_pending_decision_queue(),
            )

            with patch.object(
                reader,
                "trusted_project_progress_summary",
                side_effect=[initial_components[0], final_components[0]],
            ), patch.object(
                reader,
                "trusted_project_audit_lineage_summary",
                side_effect=[initial_components[1], final_components[1]],
            ), patch.object(
                reader,
                "trusted_project_next_action_queue",
                side_effect=[initial_components[2], final_components[2]],
            ), patch.object(
                reader,
                "trusted_project_pending_decision_queue",
                side_effect=[initial_components[3], final_components[3]],
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "trusted project assurance overview changed during query",
            ):
                reader.trusted_project_assurance_overview()

    def test_trusted_project_progress_summary_reports_empty_project(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            before = tree_bytes(state_root)

            result = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).trusted_project_progress_summary()

            self.assertEqual(result["project_id"], "FTIC")
            self.assertEqual(result["task_count"], 0)
            self.assertEqual(result["state_counts"], {})
            self.assertEqual(result["tasks"], [])
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_audit_lineage_summary_projects_existing_verifications_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            first_intake = valid_intake()
            second_intake = dict(
                first_intake,
                task_id="ftic-governance-2",
                title="Second bounded FTIC governance task",
                created_at_utc="2026-08-23T00:10:00Z",
            )
            writer.intake(first_intake)
            writer.intake(second_intake)
            before = tree_bytes(state_root)

            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            result = reader.trusted_project_audit_lineage_summary()

            self.assertEqual(result["status"], "TRUSTED_PROJECT_AUDIT_LINEAGE_SUMMARY")
            self.assertEqual(result["project_id"], "FTIC")
            self.assertEqual(result["task_count"], 2)
            self.assertEqual(
                [task["task_id"] for task in result["tasks"]],
                ["ftic-governance-1", "ftic-governance-2"],
            )
            self.assertTrue(
                all(task["status"] == "AUDIT_LINEAGE_VERIFIED" for task in result["tasks"])
            )
            self.assertEqual(
                result["control_store_authority"],
                {
                    "authority_id": reader.store.control_authority_id,
                    "authority_generation": reader.store.control_authority_generation,
                },
            )
            self.assertEqual(
                result["task_set_identity_status"],
                "UNCHANGED_DURING_QUERY",
            )
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_audit_lineage_summary_reports_empty_project(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            before = tree_bytes(state_root)

            result = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).trusted_project_audit_lineage_summary()

            self.assertEqual(result["project_id"], "FTIC")
            self.assertEqual(result["task_count"], 0)
            self.assertEqual(result["tasks"], [])
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_audit_lineage_summary_rejects_task_set_drift(
        self,
    ) -> None:
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
            initial = reader.store.read_task_states()
            changed = [
                *initial,
                dict(
                    initial[0],
                    task_id="ftic-governance-2",
                    audit_head_event_id="evt-ftic-governance-2-0001",
                    audit_head_hash="2" * 64,
                ),
            ]

            with patch.object(
                reader.store,
                "read_task_states",
                side_effect=[initial, changed],
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "project task set identity changed during progress summary",
            ):
                reader.trusted_project_audit_lineage_summary()

    def test_trusted_project_audit_lineage_summary_verification_matches_capture_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

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
            captured = reader.trusted_project_audit_lineage_summary()
            capture_path = (
                state_root / "captures" / "project-audit-lineage-summary.json"
            )
            capture_path.parent.mkdir(parents=True)
            capture_bytes = (json.dumps(captured, sort_keys=True) + "\n").encode(
                "utf-8"
            )
            capture_path.write_bytes(capture_bytes)
            before = tree_bytes(state_root)

            verifier = getattr(
                reader,
                "trusted_project_audit_lineage_summary_verification",
                None,
            )
            self.assertIsNotNone(verifier, "audit-lineage summary verifier is missing")
            result = verifier(capture_path)

            self.assertEqual(
                result,
                {
                    "status": "TRUSTED_PROJECT_AUDIT_LINEAGE_SUMMARY_VERIFIED",
                    "project_id": "FTIC",
                    "task_count": 1,
                    "captured_summary_path": (
                        "state/captures/project-audit-lineage-summary.json"
                    ),
                    "captured_summary_size_bytes": len(capture_bytes),
                    "captured_summary_sha256": hashlib.sha256(
                        capture_bytes
                    ).hexdigest(),
                    "captured_summary_identity_status": "UNCHANGED_DURING_QUERY",
                    "current_summary_identity_status": "UNCHANGED_DURING_QUERY",
                    "control_store_authority": captured["control_store_authority"],
                    "controls": {
                        "model_execution": "NOT_STARTED",
                        "process_launch": "NOT_STARTED",
                        "state_write": "NOT_PERFORMED",
                        "workflow_transition": "NOT_PERFORMED",
                    },
                },
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_audit_lineage_summary_verification_preserves_json_types(
        self,
    ) -> None:
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
            captured = reader.trusted_project_audit_lineage_summary()
            capture_path = state_root / "project-audit-lineage-summary.json"

            for replacement in (True, 1.0):
                with self.subTest(replacement=replacement):
                    changed = dict(captured, task_count=replacement)
                    capture_path.write_text(
                        json.dumps(changed, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        WorkflowEngineError,
                        "captured project audit-lineage summary does not match current trusted project state",
                    ):
                        reader.trusted_project_audit_lineage_summary_verification(
                            capture_path
                        )

    def test_trusted_project_audit_lineage_summary_verification_rejects_ambiguous_keys(
        self,
    ) -> None:
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
            captured = reader.trusted_project_audit_lineage_summary()
            encoded_tail = json.dumps(captured, sort_keys=True)[1:]
            capture_path = state_root / "project-audit-lineage-summary.json"

            for ambiguous_key in ("status", "STATUS"):
                with self.subTest(ambiguous_key=ambiguous_key):
                    capture_path.write_text(
                        f'{{"{ambiguous_key}":"TAMPERED",{encoded_tail}\n',
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        WorkflowEngineError,
                        "duplicate or case-fold-colliding JSON key",
                    ):
                        reader.trusted_project_audit_lineage_summary_verification(
                            capture_path
                        )

    def test_trusted_project_audit_lineage_summary_verification_rejects_capture_drift(
        self,
    ) -> None:
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
            captured = reader.trusted_project_audit_lineage_summary()
            capture_path = state_root / "project-audit-lineage-summary.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            read_snapshot = reader._read_strict_evidence_json_snapshot
            read_count = 0

            def mutate_after_first_read(path: Path):
                nonlocal read_count
                record, snapshot = read_snapshot(path)
                read_count += 1
                if read_count == 1:
                    capture_path.write_text(
                        json.dumps(dict(captured, task_count=2), sort_keys=True)
                        + "\n",
                        encoding="utf-8",
                    )
                return record, snapshot

            with patch.object(
                reader,
                "_read_strict_evidence_json_snapshot",
                side_effect=mutate_after_first_read,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "captured project audit-lineage summary identity changed during verification",
            ):
                reader.trusted_project_audit_lineage_summary_verification(capture_path)

    def test_trusted_project_audit_lineage_summary_verification_rejects_current_summary_drift(
        self,
    ) -> None:
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
            captured = reader.trusted_project_audit_lineage_summary()
            capture_path = state_root / "project-audit-lineage-summary.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            current_summary = reader.trusted_project_audit_lineage_summary
            query_count = 0

            def mutate_after_first_query():
                nonlocal query_count
                result = current_summary()
                query_count += 1
                if query_count == 1:
                    writer.intake(
                        dict(
                            valid_intake(),
                            task_id="ftic-governance-2",
                            title="Second bounded FTIC governance task",
                            created_at_utc="2026-08-23T00:10:00Z",
                        )
                    )
                return result

            with patch.object(
                reader,
                "trusted_project_audit_lineage_summary",
                side_effect=mutate_after_first_query,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "trusted project audit-lineage summary changed during verification",
            ):
                reader.trusted_project_audit_lineage_summary_verification(capture_path)

    def test_trusted_project_progress_summary_verification_matches_capture_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

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
            captured = reader.trusted_project_progress_summary()
            capture_path = state_root / "captures" / "project-progress-summary.json"
            capture_path.parent.mkdir(parents=True)
            capture_bytes = (json.dumps(captured, sort_keys=True) + "\n").encode("utf-8")
            capture_path.write_bytes(capture_bytes)
            before = tree_bytes(state_root)

            result = reader.trusted_project_progress_summary_verification(capture_path)

            self.assertEqual(
                result,
                {
                    "status": "TRUSTED_PROJECT_PROGRESS_SUMMARY_VERIFIED",
                    "project_id": "FTIC",
                    "task_count": 1,
                    "state_counts": {"DRAFT": 1},
                    "captured_summary_path": "state/captures/project-progress-summary.json",
                    "captured_summary_size_bytes": len(capture_bytes),
                    "captured_summary_sha256": hashlib.sha256(capture_bytes).hexdigest(),
                    "captured_summary_identity_status": "UNCHANGED_DURING_QUERY",
                    "current_summary_identity_status": "UNCHANGED_DURING_QUERY",
                    "control_store_authority": captured["control_store_authority"],
                    "controls": {
                        "model_execution": "NOT_STARTED",
                        "process_launch": "NOT_STARTED",
                        "state_write": "NOT_PERFORMED",
                        "workflow_transition": "NOT_PERFORMED",
                    },
                },
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_progress_summary_verification_preserves_json_types(
        self,
    ) -> None:
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
            captured = reader.trusted_project_progress_summary()
            capture_path = state_root / "project-progress-summary.json"

            for field_path, replacement in (
                (("task_count",), True),
                (("state_counts", "DRAFT"), 1.0),
            ):
                with self.subTest(field_path=field_path, replacement=replacement):
                    changed = json.loads(json.dumps(captured))
                    target = changed
                    for field in field_path[:-1]:
                        target = target[field]
                    target[field_path[-1]] = replacement
                    capture_path.write_text(
                        json.dumps(changed, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        WorkflowEngineError,
                        "captured project progress summary does not match current trusted project state",
                    ):
                        reader.trusted_project_progress_summary_verification(capture_path)

    def test_trusted_project_progress_summary_verification_rejects_ambiguous_json_keys(
        self,
    ) -> None:
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
            captured = reader.trusted_project_progress_summary()
            encoded_tail = json.dumps(captured, sort_keys=True)[1:]
            capture_path = state_root / "project-progress-summary.json"

            for ambiguous_key in ("status", "STATUS"):
                with self.subTest(ambiguous_key=ambiguous_key):
                    capture_path.write_text(
                        f'{{"{ambiguous_key}":"TAMPERED",{encoded_tail}\n',
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        WorkflowEngineError,
                        "duplicate or case-fold-colliding JSON key",
                    ):
                        reader.trusted_project_progress_summary_verification(capture_path)

    def test_trusted_project_progress_summary_verification_rejects_stale_capture(
        self,
    ) -> None:
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
            captured = reader.trusted_project_progress_summary()
            capture_path = state_root / "project-progress-summary.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            writer.intake(
                dict(
                    valid_intake(),
                    task_id="ftic-governance-2",
                    title="Second bounded FTIC governance task",
                    created_at_utc="2026-08-23T00:10:00Z",
                )
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "captured project progress summary does not match current trusted project state",
            ):
                reader.trusted_project_progress_summary_verification(capture_path)

    def test_trusted_project_progress_summary_verification_rejects_capture_drift(
        self,
    ) -> None:
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
            captured = reader.trusted_project_progress_summary()
            capture_path = state_root / "project-progress-summary.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            read_snapshot = reader._read_strict_evidence_json_snapshot
            read_count = 0

            def mutate_after_first_read(path: Path):
                nonlocal read_count
                record, snapshot = read_snapshot(path)
                read_count += 1
                if read_count == 1:
                    capture_path.write_text(
                        json.dumps(dict(captured, task_count=2), sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                return record, snapshot

            with patch.object(
                reader,
                "_read_strict_evidence_json_snapshot",
                side_effect=mutate_after_first_read,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "captured project progress summary identity changed during verification",
            ):
                reader.trusted_project_progress_summary_verification(capture_path)

    def test_trusted_project_progress_summary_verification_rejects_current_summary_drift(
        self,
    ) -> None:
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
            captured = reader.trusted_project_progress_summary()
            capture_path = state_root / "project-progress-summary.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            current_summary = reader.trusted_project_progress_summary
            query_count = 0

            def mutate_after_first_query():
                nonlocal query_count
                result = current_summary()
                query_count += 1
                if query_count == 1:
                    writer.intake(
                        dict(
                            valid_intake(),
                            task_id="ftic-governance-2",
                            title="Second bounded FTIC governance task",
                            created_at_utc="2026-08-23T00:10:00Z",
                        )
                    )
                return result

            with patch.object(
                reader,
                "trusted_project_progress_summary",
                side_effect=mutate_after_first_query,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "trusted project progress summary changed during verification",
            ):
                reader.trusted_project_progress_summary_verification(capture_path)

    def test_trusted_project_next_action_queue_projects_all_tasks_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            first_intake = valid_intake()
            second_intake = dict(
                first_intake,
                task_id="ftic-governance-2",
                title="Second bounded FTIC governance task",
                created_at_utc="2026-08-23T00:10:00Z",
            )
            writer.intake(first_intake)
            writer.intake(second_intake)
            before = tree_bytes(state_root)

            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            result = reader.trusted_project_next_action_queue()

            self.assertEqual(result["status"], "TRUSTED_PROJECT_NEXT_ACTION_QUEUE")
            self.assertEqual(result["project_id"], "FTIC")
            self.assertEqual(result["task_count"], 2)
            self.assertEqual(result["state_counts"], {"DRAFT": 2})
            self.assertEqual(
                [item["task_id"] for item in result["queue"]],
                ["ftic-governance-1", "ftic-governance-2"],
            )
            self.assertEqual(
                [item["current_state"] for item in result["queue"]],
                ["DRAFT", "DRAFT"],
            )
            self.assertEqual(
                [
                    [option["target_state"] for option in item["options"]]
                    for item in result["queue"]
                ],
                [
                    ["READY_FOR_CLASSIFICATION", "ABANDONED"],
                    ["READY_FOR_CLASSIFICATION", "ABANDONED"],
                ],
            )
            self.assertTrue(
                all(item["authorization_status"] == "NOT_EVALUATED" for item in result["queue"])
            )
            self.assertTrue(
                all(item["selected_transition"] is None for item in result["queue"])
            )
            self.assertEqual(
                result["control_store_authority"],
                {
                    "authority_id": reader.store.control_authority_id,
                    "authority_generation": reader.store.control_authority_generation,
                },
            )
            self.assertEqual(
                result["task_set_identity_status"],
                "UNCHANGED_DURING_QUERY",
            )
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_pending_decision_queue_projects_full_requests_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=12)
            writer.intake(
                dict(
                    valid_intake(),
                    task_id="ftic-governance-2",
                    title="Second bounded FTIC governance task",
                    created_at_utc="2026-08-27T12:10:00Z",
                )
            )
            pending_path = writer.decisions.pending_path(waiting["pending_decision_id"])
            expected_request = json.loads(pending_path.read_text(encoding="utf-8"))
            before = tree_bytes(state_root)

            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            result = reader.trusted_project_pending_decision_queue()

            self.assertEqual(result["status"], "TRUSTED_PROJECT_PENDING_DECISION_QUEUE")
            self.assertEqual(result["queue_status"], "PENDING")
            self.assertEqual(result["project_id"], "FTIC")
            self.assertEqual(result["task_count"], 2)
            self.assertEqual(result["state_counts"], {"DRAFT": 1, "WAITING_HUMAN": 1})
            self.assertEqual(result["pending_decision_count"], 1)
            self.assertEqual(result["decisions"], [expected_request])
            self.assertEqual(result["task_set_identity_status"], "UNCHANGED_DURING_QUERY")
            self.assertEqual(
                result["pending_decision_set_identity_status"],
                "UNCHANGED_DURING_QUERY",
            )
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_pending_decision_resolution_preview_binds_current_queue_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=13)
            resolution = waiting_human_resolution(waiting)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_bytes = canonical_json_bytes(resolution) + b"\n"
            resolution_path.write_bytes(resolution_bytes)
            before = tree_bytes(state_root)

            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            result = reader.trusted_project_pending_decision_resolution_preview(
                resolution_path
            )

            self.assertEqual(
                result["status"],
                "TRUSTED_PROJECT_PENDING_DECISION_RESOLUTION_PREVIEW",
            )
            self.assertEqual(result["decision_id"], resolution["decision_id"])
            self.assertEqual(result["project_id"], "FTIC")
            self.assertEqual(result["task_id"], "ftic-governance-1")
            self.assertEqual(result["selected_option"], "RESUME")
            self.assertEqual(result["resume_state"], "SPEC_READY")
            self.assertEqual(result["pending_request_status"], "PENDING")
            self.assertEqual(result["authorization_status"], "NOT_EVALUATED")
            self.assertEqual(
                result["resolution_identity"],
                {
                    "path": "state/decision-resolution-preview.json",
                    "size_bytes": len(resolution_bytes),
                    "sha256": hashlib.sha256(resolution_bytes).hexdigest(),
                    "status": "UNCHANGED_DURING_QUERY",
                },
            )
            self.assertEqual(
                result["project_queue_identity_status"],
                "UNCHANGED_DURING_QUERY",
            )
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_pending_decision_resolution_preview_rejects_noncanonical_resolution(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=14)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_text(
                json.dumps(waiting_human_resolution(waiting), indent=2) + "\n",
                encoding="utf-8",
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "canonical JSON bytes",
            ):
                reader.trusted_project_pending_decision_resolution_preview(
                    resolution_path
                )

    def test_trusted_project_pending_decision_resolution_preview_rejects_resolution_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=15)
            resolution = waiting_human_resolution(waiting)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(canonical_json_bytes(resolution) + b"\n")
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            read_snapshot = reader._read_strict_evidence_json_snapshot
            read_count = 0

            def mutate_after_first_read(path: Path):
                nonlocal read_count
                result = read_snapshot(path)
                read_count += 1
                if read_count == 1:
                    changed = dict(
                        resolution,
                        rationale="A changed human decision rationale.",
                    )
                    resolution_path.write_bytes(canonical_json_bytes(changed) + b"\n")
                return result

            with patch.object(
                reader,
                "_read_strict_evidence_json_snapshot",
                side_effect=mutate_after_first_read,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "resolution identity changed",
            ):
                reader.trusted_project_pending_decision_resolution_preview(
                    resolution_path
                )

    def test_trusted_project_pending_decision_resolution_preview_rejects_project_queue_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=16)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(
                canonical_json_bytes(waiting_human_resolution(waiting)) + b"\n"
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            trusted_queue = reader.trusted_project_pending_decision_queue
            query_count = 0

            def mutate_after_first_query():
                nonlocal query_count
                result = trusted_queue()
                query_count += 1
                if query_count == 1:
                    writer.intake(
                        dict(
                            valid_intake(),
                            task_id="ftic-governance-2",
                            title="Second bounded FTIC governance task",
                            created_at_utc="2026-08-27T16:10:00Z",
                        )
                    )
                return result

            with patch.object(
                reader,
                "trusted_project_pending_decision_queue",
                side_effect=mutate_after_first_query,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "pending-decision queue changed",
            ):
                reader.trusted_project_pending_decision_resolution_preview(
                    resolution_path
                )

    def test_trusted_project_pending_decision_resolution_preview_verification_matches_capture_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=17)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(
                canonical_json_bytes(waiting_human_resolution(waiting)) + b"\n"
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_resolution_preview(
                resolution_path
            )
            capture_path = (
                state_root / "captures" / "pending-decision-resolution-preview.json"
            )
            capture_path.parent.mkdir(parents=True)
            capture_bytes = (json.dumps(captured, sort_keys=True) + "\n").encode("utf-8")
            capture_path.write_bytes(capture_bytes)
            before = tree_bytes(state_root)

            result = (
                reader.trusted_project_pending_decision_resolution_preview_verification(
                    capture_path
                )
            )

            self.assertEqual(
                result,
                {
                    "status": "TRUSTED_PROJECT_PENDING_DECISION_RESOLUTION_PREVIEW_VERIFIED",
                    "decision_id": captured["decision_id"],
                    "project_id": "FTIC",
                    "task_id": "ftic-governance-1",
                    "selected_option": "RESUME",
                    "resume_state": "SPEC_READY",
                    "pending_request_status": "PENDING",
                    "authorization_status": "NOT_EVALUATED",
                    "captured_preview_path": (
                        "state/captures/pending-decision-resolution-preview.json"
                    ),
                    "captured_preview_size_bytes": len(capture_bytes),
                    "captured_preview_sha256": hashlib.sha256(
                        capture_bytes
                    ).hexdigest(),
                    "captured_preview_identity_status": "UNCHANGED_DURING_QUERY",
                    "current_preview_identity_status": "UNCHANGED_DURING_QUERY",
                    "resolution_identity": captured["resolution_identity"],
                    "project_queue_identity_status": "UNCHANGED_DURING_QUERY",
                    "control_store_authority": captured["control_store_authority"],
                    "controls": {
                        "model_execution": "NOT_STARTED",
                        "process_launch": "NOT_STARTED",
                        "state_write": "NOT_PERFORMED",
                        "workflow_transition": "NOT_PERFORMED",
                    },
                },
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_pending_decision_resolution_preview_verification_preserves_json_types(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=18)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(
                canonical_json_bytes(waiting_human_resolution(waiting)) + b"\n"
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_resolution_preview(
                resolution_path
            )
            capture_path = state_root / "pending-decision-resolution-preview.json"

            for replacement in (True, 1.0):
                with self.subTest(replacement=replacement):
                    changed = json.loads(json.dumps(captured))
                    changed["resolution_identity"]["size_bytes"] = replacement
                    capture_path.write_text(
                        json.dumps(changed, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        WorkflowEngineError,
                        "captured pending-decision resolution preview does not match",
                    ):
                        reader.trusted_project_pending_decision_resolution_preview_verification(
                            capture_path
                        )

    def test_trusted_project_pending_decision_resolution_preview_verification_rejects_ambiguous_json_keys(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=19)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(
                canonical_json_bytes(waiting_human_resolution(waiting)) + b"\n"
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_resolution_preview(
                resolution_path
            )
            encoded_tail = json.dumps(captured, sort_keys=True)[1:]
            capture_path = state_root / "pending-decision-resolution-preview.json"

            for ambiguous_key in ("status", "STATUS"):
                with self.subTest(ambiguous_key=ambiguous_key):
                    capture_path.write_text(
                        f'{{"{ambiguous_key}":"TAMPERED",{encoded_tail}\n',
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        WorkflowEngineError,
                        "duplicate or case-fold-colliding JSON key",
                    ):
                        reader.trusted_project_pending_decision_resolution_preview_verification(
                            capture_path
                        )

    def test_trusted_project_pending_decision_resolution_preview_verification_rejects_invalid_resolution_path(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=20)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(
                canonical_json_bytes(waiting_human_resolution(waiting)) + b"\n"
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_resolution_preview(
                resolution_path
            )
            captured["resolution_identity"]["path"] = (
                "state/../state/decision-resolution-preview.json"
            )
            capture_path = state_root / "pending-decision-resolution-preview.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "captured resolution path is invalid",
            ):
                reader.trusted_project_pending_decision_resolution_preview_verification(
                    capture_path
                )

    def test_trusted_project_pending_decision_resolution_preview_verification_rejects_capture_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=21)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(
                canonical_json_bytes(waiting_human_resolution(waiting)) + b"\n"
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_resolution_preview(
                resolution_path
            )
            capture_path = state_root / "pending-decision-resolution-preview.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            read_snapshot = reader._read_strict_evidence_json_snapshot
            capture_reads = 0

            def mutate_after_first_capture_read(path: Path):
                nonlocal capture_reads
                result = read_snapshot(path)
                if path == capture_path:
                    capture_reads += 1
                    if capture_reads == 1:
                        changed = dict(captured, authorization_status="TAMPERED")
                        capture_path.write_text(
                            json.dumps(changed, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                return result

            with patch.object(
                reader,
                "_read_strict_evidence_json_snapshot",
                side_effect=mutate_after_first_capture_read,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "captured pending-decision resolution preview identity changed",
            ):
                reader.trusted_project_pending_decision_resolution_preview_verification(
                    capture_path
                )

    def test_trusted_project_pending_decision_resolution_preview_verification_rejects_current_preview_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=22)
            resolution = waiting_human_resolution(waiting)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(canonical_json_bytes(resolution) + b"\n")
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_resolution_preview(
                resolution_path
            )
            capture_path = state_root / "pending-decision-resolution-preview.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            current_preview = (
                reader.trusted_project_pending_decision_resolution_preview
            )
            query_count = 0

            def mutate_after_first_query(path: Path):
                nonlocal query_count
                result = current_preview(path)
                query_count += 1
                if query_count == 1:
                    changed = dict(
                        resolution,
                        rationale="A changed human decision rationale.",
                    )
                    resolution_path.write_bytes(canonical_json_bytes(changed) + b"\n")
                return result

            with patch.object(
                reader,
                "trusted_project_pending_decision_resolution_preview",
                side_effect=mutate_after_first_query,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "trusted pending-decision resolution preview changed during verification",
            ):
                reader.trusted_project_pending_decision_resolution_preview_verification(
                    capture_path
                )

    def test_trusted_project_pending_decision_resolution_to_resume_gate_preview_reuses_existing_gate_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=23)
            resolution = waiting_human_resolution(waiting)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(canonical_json_bytes(resolution) + b"\n")
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_resolution_preview(
                resolution_path
            )
            capture_path = state_root / "pending-decision-resolution-preview.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            planner_evidence = write_planner_transition_evidence(
                writer,
                target="SPEC_READY",
            )
            before = tree_bytes(state_root)

            preview = reader.trusted_project_pending_decision_resolution_to_resume_gate_preview(
                capture_path,
                actor="PLANNER",
                evidence_paths=planner_evidence,
                created_at_utc="2026-08-27T23:04:00Z",
            )

            self.assertEqual(preview["status"], "WAITING_HUMAN_RESUME_GATE_PREVIEW")
            self.assertEqual(preview["task_id"], "ftic-governance-1")
            self.assertEqual(preview["current_state"], "WAITING_HUMAN")
            self.assertEqual(preview["source_state_before_human_gate"], "CLASSIFIED")
            self.assertEqual(preview["target_state"], "SPEC_READY")
            self.assertEqual(preview["required_actor"], "PLANNER")
            self.assertEqual(preview["decision_id"], resolution["decision_id"])
            self.assertEqual(preview["resolution_status"], "VALIDATED")
            self.assertEqual(preview["evidence_status"], "VALIDATED")
            self.assertEqual(preview["authorization_status"], "NOT_GRANTED")
            self.assertEqual(preview["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(
                preview["controls"]["workflow_transition"],
                "NOT_PERFORMED",
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_pending_decision_resolution_to_resume_gate_preview_rejects_capture_drift_after_gate(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=0)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(
                canonical_json_bytes(waiting_human_resolution(waiting)) + b"\n"
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_resolution_preview(
                resolution_path
            )
            capture_path = state_root / "pending-decision-resolution-preview.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            planner_evidence = write_planner_transition_evidence(
                writer,
                target="SPEC_READY",
            )
            resume_gate_preview = reader.waiting_human_resume_gate_preview

            def mutate_capture_after_gate(*args, **kwargs):
                result = resume_gate_preview(*args, **kwargs)
                changed = dict(captured, authorization_status="TAMPERED")
                capture_path.write_text(
                    json.dumps(changed, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                return result

            with patch.object(
                reader,
                "waiting_human_resume_gate_preview",
                side_effect=mutate_capture_after_gate,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "captured pending-decision resolution preview identity changed during resume gate preview",
            ):
                reader.trusted_project_pending_decision_resolution_to_resume_gate_preview(
                    capture_path,
                    actor="PLANNER",
                    evidence_paths=planner_evidence,
                    created_at_utc="2026-08-28T00:04:00Z",
                )

    def test_trusted_project_pending_decision_resolution_to_resume_gate_preview_verification_matches_capture_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=1)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(
                canonical_json_bytes(waiting_human_resolution(waiting)) + b"\n"
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            resolution_preview = (
                reader.trusted_project_pending_decision_resolution_preview(
                    resolution_path
                )
            )
            resolution_preview_path = (
                state_root / "pending-decision-resolution-preview.json"
            )
            resolution_preview_path.write_text(
                json.dumps(resolution_preview, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            planner_evidence = write_planner_transition_evidence(
                writer,
                target="SPEC_READY",
            )
            gate_preview = (
                reader.trusted_project_pending_decision_resolution_to_resume_gate_preview(
                    resolution_preview_path,
                    actor="PLANNER",
                    evidence_paths=planner_evidence,
                    created_at_utc="2026-08-28T01:04:00Z",
                )
            )
            gate_preview_path = (
                state_root / "captures" / "project-resolution-resume-gate-preview.json"
            )
            gate_preview_path.parent.mkdir(parents=True)
            gate_preview_bytes = (
                json.dumps(gate_preview, sort_keys=True) + "\n"
            ).encode("utf-8")
            gate_preview_path.write_bytes(gate_preview_bytes)
            before = tree_bytes(state_root)

            result = reader.trusted_project_pending_decision_resolution_to_resume_gate_preview_verification(
                gate_preview_path,
                resolution_preview_path,
                actor="PLANNER",
                evidence_paths=planner_evidence,
                created_at_utc="2026-08-28T01:04:00Z",
            )

            self.assertEqual(
                result["status"],
                "TRUSTED_PROJECT_PENDING_DECISION_RESOLUTION_TO_RESUME_GATE_PREVIEW_VERIFIED",
            )
            self.assertEqual(result["project_id"], "FTIC")
            self.assertEqual(result["task_id"], "ftic-governance-1")
            self.assertEqual(result["decision_id"], resolution_preview["decision_id"])
            self.assertEqual(result["target_state"], "SPEC_READY")
            self.assertEqual(result["required_actor"], "PLANNER")
            self.assertEqual(
                result["captured_gate_preview_path"],
                "state/captures/project-resolution-resume-gate-preview.json",
            )
            self.assertEqual(
                result["captured_gate_preview_size_bytes"],
                len(gate_preview_bytes),
            )
            self.assertEqual(
                result["captured_gate_preview_sha256"],
                hashlib.sha256(gate_preview_bytes).hexdigest(),
            )
            self.assertEqual(
                result["captured_gate_preview_identity_status"],
                "UNCHANGED_DURING_QUERY",
            )
            self.assertEqual(
                result["current_gate_preview_identity_status"],
                "UNCHANGED_DURING_QUERY",
            )
            self.assertEqual(result["authorization_status"], "NOT_GRANTED")
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(
                result["controls"]["workflow_transition"],
                "NOT_PERFORMED",
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_pending_decision_resolution_to_resume_gate_preview_verification_preserves_json_types(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=2)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(
                canonical_json_bytes(waiting_human_resolution(waiting)) + b"\n"
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            resolution_preview = (
                reader.trusted_project_pending_decision_resolution_preview(
                    resolution_path
                )
            )
            resolution_preview_path = (
                state_root / "pending-decision-resolution-preview.json"
            )
            resolution_preview_path.write_text(
                json.dumps(resolution_preview, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            planner_evidence = write_planner_transition_evidence(
                writer,
                target="SPEC_READY",
            )
            gate_preview = (
                reader.trusted_project_pending_decision_resolution_to_resume_gate_preview(
                    resolution_preview_path,
                    actor="PLANNER",
                    evidence_paths=planner_evidence,
                    created_at_utc="2026-08-28T02:04:00Z",
                )
            )
            gate_preview["audit_generation"] = True
            gate_preview_path = state_root / "project-resolution-resume-gate-preview.json"
            gate_preview_path.write_text(
                json.dumps(gate_preview, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "captured project resolution-to-resume gate preview does not match",
            ):
                reader.trusted_project_pending_decision_resolution_to_resume_gate_preview_verification(
                    gate_preview_path,
                    resolution_preview_path,
                    actor="PLANNER",
                    evidence_paths=planner_evidence,
                    created_at_utc="2026-08-28T02:04:00Z",
                )

    def test_trusted_project_pending_decision_resolution_to_resume_gate_preview_verification_rejects_capture_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=3)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(
                canonical_json_bytes(waiting_human_resolution(waiting)) + b"\n"
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            resolution_preview = (
                reader.trusted_project_pending_decision_resolution_preview(
                    resolution_path
                )
            )
            resolution_preview_path = (
                state_root / "pending-decision-resolution-preview.json"
            )
            resolution_preview_path.write_text(
                json.dumps(resolution_preview, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            planner_evidence = write_planner_transition_evidence(
                writer,
                target="SPEC_READY",
            )
            gate_preview = (
                reader.trusted_project_pending_decision_resolution_to_resume_gate_preview(
                    resolution_preview_path,
                    actor="PLANNER",
                    evidence_paths=planner_evidence,
                    created_at_utc="2026-08-28T03:04:00Z",
                )
            )
            gate_preview_path = state_root / "project-resolution-resume-gate-preview.json"
            gate_preview_path.write_text(
                json.dumps(gate_preview, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            strict_read = reader._read_strict_evidence_json_snapshot
            gate_capture_reads = 0

            def mutate_after_first_capture_read(path: Path):
                nonlocal gate_capture_reads
                result = strict_read(path)
                if path == gate_preview_path:
                    gate_capture_reads += 1
                    if gate_capture_reads == 1:
                        changed = dict(gate_preview, authorization_status="TAMPERED")
                        gate_preview_path.write_text(
                            json.dumps(changed, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                return result

            with patch.object(
                reader,
                "_read_strict_evidence_json_snapshot",
                side_effect=mutate_after_first_capture_read,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "captured project resolution-to-resume gate preview identity changed",
            ):
                reader.trusted_project_pending_decision_resolution_to_resume_gate_preview_verification(
                    gate_preview_path,
                    resolution_preview_path,
                    actor="PLANNER",
                    evidence_paths=planner_evidence,
                    created_at_utc="2026-08-28T03:04:00Z",
                )

    def test_trusted_project_pending_decision_resolution_to_resume_gate_preview_verification_rejects_current_preview_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            waiting = advance_to_waiting_human(writer, hour=4)
            resolution_path = state_root / "decision-resolution-preview.json"
            resolution_path.write_bytes(
                canonical_json_bytes(waiting_human_resolution(waiting)) + b"\n"
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            resolution_preview = (
                reader.trusted_project_pending_decision_resolution_preview(
                    resolution_path
                )
            )
            resolution_preview_path = (
                state_root / "pending-decision-resolution-preview.json"
            )
            resolution_preview_path.write_text(
                json.dumps(resolution_preview, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            planner_evidence = write_planner_transition_evidence(
                writer,
                target="SPEC_READY",
            )
            gate_preview = (
                reader.trusted_project_pending_decision_resolution_to_resume_gate_preview(
                    resolution_preview_path,
                    actor="PLANNER",
                    evidence_paths=planner_evidence,
                    created_at_utc="2026-08-28T04:04:00Z",
                )
            )
            gate_preview_path = state_root / "project-resolution-resume-gate-preview.json"
            gate_preview_path.write_text(
                json.dumps(gate_preview, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            current_preview = (
                reader.trusted_project_pending_decision_resolution_to_resume_gate_preview
            )
            query_count = 0

            def mutate_second_current_preview(*args, **kwargs):
                nonlocal query_count
                result = current_preview(*args, **kwargs)
                query_count += 1
                if query_count == 2:
                    return dict(result, authorization_status="TAMPERED")
                return result

            with patch.object(
                reader,
                "trusted_project_pending_decision_resolution_to_resume_gate_preview",
                side_effect=mutate_second_current_preview,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "trusted project resolution-to-resume gate preview changed during verification",
            ):
                reader.trusted_project_pending_decision_resolution_to_resume_gate_preview_verification(
                    gate_preview_path,
                    resolution_preview_path,
                    actor="PLANNER",
                    evidence_paths=planner_evidence,
                    created_at_utc="2026-08-28T04:04:00Z",
                )

    def test_trusted_project_pending_decision_queue_rejects_request_identity_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_waiting_human(writer, hour=13)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            summary = reader.trusted_project_progress_summary()
            initial_records = reader.decisions.list_pending()
            changed_records = json.loads(json.dumps(initial_records))
            changed_records[0]["question"] = "A changed human decision question"

            with patch.object(
                reader,
                "trusted_project_progress_summary",
                return_value=summary,
            ), patch.object(
                reader.decisions,
                "list_pending",
                side_effect=[initial_records, changed_records],
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "pending decision set identity changed",
            ):
                reader.trusted_project_pending_decision_queue()

    def test_trusted_project_pending_decision_queue_verification_matches_capture_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_waiting_human(writer, hour=14)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_queue()
            capture_path = state_root / "captures" / "project-pending-decision-queue.json"
            capture_path.parent.mkdir(parents=True)
            capture_bytes = (json.dumps(captured, sort_keys=True) + "\n").encode("utf-8")
            capture_path.write_bytes(capture_bytes)
            before = tree_bytes(state_root)

            result = reader.trusted_project_pending_decision_queue_verification(
                capture_path
            )

            self.assertEqual(
                result,
                {
                    "status": "TRUSTED_PROJECT_PENDING_DECISION_QUEUE_VERIFIED",
                    "queue_status": "PENDING",
                    "project_id": "FTIC",
                    "task_count": 1,
                    "state_counts": {"WAITING_HUMAN": 1},
                    "pending_decision_count": 1,
                    "captured_queue_path": "state/captures/project-pending-decision-queue.json",
                    "captured_queue_size_bytes": len(capture_bytes),
                    "captured_queue_sha256": hashlib.sha256(capture_bytes).hexdigest(),
                    "captured_queue_identity_status": "UNCHANGED_DURING_QUERY",
                    "current_queue_identity_status": "UNCHANGED_DURING_QUERY",
                    "control_store_authority": captured["control_store_authority"],
                    "controls": {
                        "model_execution": "NOT_STARTED",
                        "process_launch": "NOT_STARTED",
                        "state_write": "NOT_PERFORMED",
                        "workflow_transition": "NOT_PERFORMED",
                    },
                },
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_pending_decision_queue_verification_preserves_json_types(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_waiting_human(writer, hour=15)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            capture_path = state_root / "project-pending-decision-queue.json"

            for field, value in (
                ("pending_decision_count", True),
                ("task_count", 1.0),
            ):
                with self.subTest(field=field, value=value):
                    captured = reader.trusted_project_pending_decision_queue()
                    captured[field] = value
                    capture_path.write_text(
                        json.dumps(captured, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        WorkflowEngineError,
                        "captured project pending-decision queue does not match current trusted project state",
                    ):
                        reader.trusted_project_pending_decision_queue_verification(
                            capture_path
                        )

    def test_trusted_project_pending_decision_queue_verification_rejects_ambiguous_json_keys(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_waiting_human(writer, hour=16)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_queue()
            encoded_tail = json.dumps(captured, sort_keys=True)[1:]
            capture_path = state_root / "project-pending-decision-queue.json"

            for ambiguous_key in ("status", "STATUS"):
                with self.subTest(ambiguous_key=ambiguous_key):
                    capture_path.write_text(
                        f'{{"{ambiguous_key}":"TAMPERED",{encoded_tail}\n',
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        WorkflowEngineError,
                        "duplicate or case-fold-colliding JSON key",
                    ):
                        reader.trusted_project_pending_decision_queue_verification(
                            capture_path
                        )

    def test_trusted_project_pending_decision_queue_verification_rejects_stale_capture(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_waiting_human(writer, hour=17)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_queue()
            capture_path = state_root / "project-pending-decision-queue.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            writer.intake(
                dict(
                    valid_intake(),
                    task_id="ftic-governance-2",
                    title="Second bounded FTIC governance task",
                    created_at_utc="2026-08-27T17:10:00Z",
                )
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "captured project pending-decision queue does not match current trusted project state",
            ):
                reader.trusted_project_pending_decision_queue_verification(capture_path)

    def test_trusted_project_pending_decision_queue_verification_rejects_capture_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_waiting_human(writer, hour=18)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_queue()
            capture_path = state_root / "project-pending-decision-queue.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            read_snapshot = reader._read_strict_evidence_json_snapshot
            read_count = 0

            def mutate_after_first_read(path: Path):
                nonlocal read_count
                record, snapshot = read_snapshot(path)
                read_count += 1
                if read_count == 1:
                    capture_path.write_text(
                        json.dumps(dict(captured, task_count=2), sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                return record, snapshot

            with patch.object(
                reader,
                "_read_strict_evidence_json_snapshot",
                side_effect=mutate_after_first_read,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "captured project pending-decision queue identity changed during verification",
            ):
                reader.trusted_project_pending_decision_queue_verification(capture_path)

    def test_trusted_project_pending_decision_queue_verification_rejects_current_queue_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_waiting_human(writer, hour=19)
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            captured = reader.trusted_project_pending_decision_queue()
            capture_path = state_root / "project-pending-decision-queue.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            current_queue = reader.trusted_project_pending_decision_queue
            query_count = 0

            def mutate_after_first_query():
                nonlocal query_count
                result = current_queue()
                query_count += 1
                if query_count == 1:
                    writer.intake(
                        dict(
                            valid_intake(),
                            task_id="ftic-governance-2",
                            title="Second bounded FTIC governance task",
                            created_at_utc="2026-08-27T19:10:00Z",
                        )
                    )
                return result

            with patch.object(
                reader,
                "trusted_project_pending_decision_queue",
                side_effect=mutate_after_first_query,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "trusted project pending-decision queue changed during verification",
            ):
                reader.trusted_project_pending_decision_queue_verification(capture_path)

    def test_trusted_project_next_action_queue_verification_matches_captured_queue_without_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

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
            captured = reader.trusted_project_next_action_queue()
            capture_path = state_root / "captures" / "project-next-action-queue.json"
            capture_path.parent.mkdir(parents=True)
            capture_bytes = (json.dumps(captured, sort_keys=True) + "\n").encode("utf-8")
            capture_path.write_bytes(capture_bytes)
            before = tree_bytes(state_root)

            result = reader.trusted_project_next_action_queue_verification(capture_path)

            self.assertEqual(
                result,
                {
                    "status": "TRUSTED_PROJECT_NEXT_ACTION_QUEUE_VERIFIED",
                    "project_id": "FTIC",
                    "task_count": 1,
                    "state_counts": {"DRAFT": 1},
                    "captured_queue_path": "state/captures/project-next-action-queue.json",
                    "captured_queue_size_bytes": len(capture_bytes),
                    "captured_queue_sha256": hashlib.sha256(capture_bytes).hexdigest(),
                    "captured_queue_identity_status": "UNCHANGED_DURING_QUERY",
                    "current_queue_identity_status": "UNCHANGED_DURING_QUERY",
                    "control_store_authority": captured["control_store_authority"],
                    "controls": {
                        "model_execution": "NOT_STARTED",
                        "process_launch": "NOT_STARTED",
                        "state_write": "NOT_PERFORMED",
                        "workflow_transition": "NOT_PERFORMED",
                    },
                },
            )
            self.assertEqual(tree_bytes(state_root), before)

    def test_trusted_project_next_action_queue_verification_rejects_boolean_integer_confusion(
        self,
    ) -> None:
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
            captured = reader.trusted_project_next_action_queue()
            captured["task_count"] = True
            capture_path = state_root / "project-next-action-queue.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "captured project next-action queue does not match current trusted project state",
            ):
                reader.trusted_project_next_action_queue_verification(capture_path)

    def test_trusted_project_next_action_queue_verification_rejects_float_integer_confusion(
        self,
    ) -> None:
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
            captured = reader.trusted_project_next_action_queue()
            captured["state_counts"]["DRAFT"] = 1.0
            capture_path = state_root / "project-next-action-queue.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "captured project next-action queue does not match current trusted project state",
            ):
                reader.trusted_project_next_action_queue_verification(capture_path)

    def test_trusted_project_next_action_queue_verification_rejects_ambiguous_json_keys(
        self,
    ) -> None:
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
            captured = reader.trusted_project_next_action_queue()
            encoded_tail = json.dumps(captured, sort_keys=True)[1:]
            capture_path = state_root / "project-next-action-queue.json"

            for ambiguous_key in ("status", "STATUS"):
                with self.subTest(ambiguous_key=ambiguous_key):
                    capture_path.write_text(
                        f'{{"{ambiguous_key}":"TAMPERED",{encoded_tail}\n',
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        WorkflowEngineError,
                        "duplicate or case-fold-colliding JSON key",
                    ):
                        reader.trusted_project_next_action_queue_verification(
                            capture_path
                        )

    def test_trusted_project_next_action_queue_verification_rejects_stale_capture(
        self,
    ) -> None:
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
            captured = reader.trusted_project_next_action_queue()
            capture_path = state_root / "project-next-action-queue.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            writer.intake(
                dict(
                    valid_intake(),
                    task_id="ftic-governance-2",
                    title="Second bounded FTIC governance task",
                    created_at_utc="2026-08-23T00:10:00Z",
                )
            )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "captured project next-action queue does not match current trusted project state",
            ):
                reader.trusted_project_next_action_queue_verification(capture_path)

    def test_trusted_project_next_action_queue_verification_rejects_capture_drift(
        self,
    ) -> None:
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
            captured = reader.trusted_project_next_action_queue()
            capture_path = state_root / "project-next-action-queue.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            read_snapshot = reader._read_strict_evidence_json_snapshot
            read_count = 0

            def mutate_after_first_read(path: Path):
                nonlocal read_count
                record, snapshot = read_snapshot(path)
                read_count += 1
                if read_count == 1:
                    capture_path.write_text(
                        json.dumps(dict(captured, task_count=2), sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                return record, snapshot

            with patch.object(
                reader,
                "_read_strict_evidence_json_snapshot",
                side_effect=mutate_after_first_read,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "captured project next-action queue identity changed during verification",
            ):
                reader.trusted_project_next_action_queue_verification(capture_path)

    def test_trusted_project_next_action_queue_verification_rejects_current_queue_drift(
        self,
    ) -> None:
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
            captured = reader.trusted_project_next_action_queue()
            capture_path = state_root / "project-next-action-queue.json"
            capture_path.write_text(
                json.dumps(captured, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            current_queue = reader.trusted_project_next_action_queue
            query_count = 0

            def mutate_after_first_query():
                nonlocal query_count
                result = current_queue()
                query_count += 1
                if query_count == 1:
                    writer.intake(
                        dict(
                            valid_intake(),
                            task_id="ftic-governance-2",
                            title="Second bounded FTIC governance task",
                            created_at_utc="2026-08-23T00:10:00Z",
                        )
                    )
                return result

            with patch.object(
                reader,
                "trusted_project_next_action_queue",
                side_effect=mutate_after_first_query,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "trusted project next-action queue changed during verification",
            ):
                reader.trusted_project_next_action_queue_verification(capture_path)

    def test_trusted_project_progress_summary_excludes_other_project_tasks(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            current = writer.intake(valid_intake())
            writer.store.write_task_state(
                dict(
                    current,
                    task_id="other-project-task",
                    project_id="OTHER",
                    audit_head_event_id="evt-other-project-task-0001",
                    audit_head_hash="3" * 64,
                )
            )

            result = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).trusted_project_progress_summary()

            self.assertEqual(result["task_count"], 1)
            self.assertEqual(
                [task["task_id"] for task in result["tasks"]],
                ["ftic-governance-1"],
            )

    def test_trusted_project_progress_summary_rejects_enumerated_task_identity_drift(
        self,
    ) -> None:
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
            changed = reader.trusted_task_progress_summary("ftic-governance-1")
            changed = dict(changed, current_state="CLASSIFIED")

            with patch.object(
                reader,
                "trusted_task_progress_summary",
                return_value=changed,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "project task identity changed during progress summary",
            ):
                reader.trusted_project_progress_summary()

    def test_trusted_project_progress_summary_rejects_task_set_drift(self) -> None:
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
            initial = reader.store.read_task_states()
            changed = [
                *initial,
                dict(
                    initial[0],
                    task_id="ftic-governance-2",
                    audit_head_event_id="evt-ftic-governance-2-0001",
                    audit_head_hash="2" * 64,
                ),
            ]

            with patch.object(
                reader.store,
                "read_task_states",
                side_effect=[initial, changed],
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "project task set identity changed during progress summary",
            ):
                reader.trusted_project_progress_summary()

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

    def test_task_review_accepts_zero_findings_when_reviewer_completes_without_blockers(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=19)
            evidence_paths = write_reviewer_transition_evidence(
                engine,
                [],
                target="INTEGRATING",
            )

            preview = engine.next_action_preview("ftic-governance-1")
            integrating = next(
                option
                for option in preview["options"]
                if option["target_state"] == "INTEGRATING"
            )
            self.assertEqual(integrating["evidence_contract"]["minimum_count"], 2)

            state = engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=evidence_paths,
                created_at_utc="2026-08-23T19:07:00Z",
            )

            self.assertEqual(state["current_state"], "INTEGRATING")
            self.assertEqual(
                [
                    binding["content_sha256"]
                    for binding in engine.audit("ftic-governance-1")[-1][
                        "evidence_bindings"
                    ]
                ],
                [hashlib.sha256(path.read_bytes()).hexdigest() for path in evidence_paths],
            )

    def test_task_review_zero_findings_requires_done_reviewer_result(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            advance_to_task_review(engine, hour=19)
            reviewer_result = dict(
                valid_reviewer_result(recommended_next_state="INTEGRATING"),
                status="DONE_WITH_CONCERNS",
                concerns=["A non-blocking concern remains."],
            )
            evidence_paths = write_reviewer_transition_evidence(
                engine,
                [],
                target="INTEGRATING",
                result=reviewer_result,
            )
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "zero review findings requires reviewer status DONE",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "INTEGRATING",
                    actor="REVIEWER",
                    evidence_paths=evidence_paths,
                    created_at_utc="2026-08-23T19:07:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

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

    def test_rc_ready_transition_commit_verification_revalidates_tail_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, manifest_path, _ = prepare_committed_rc_ready(
                state_root,
                ["verification-current"],
            )
            current = writer.status("ftic-governance-1")
            tail = writer.audit("ftic-governance-1")[-1]
            before = tree_bytes(state_root)

            result = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).rc_ready_transition_commit_verification("ftic-governance-1")

            self.assertEqual(result["status"], "RC_READY_TRANSITION_COMMIT_VERIFIED")
            self.assertEqual(result["task_id"], "ftic-governance-1")
            self.assertEqual(result["project_id"], "FTIC")
            self.assertEqual(result["current_state"], "RC_READY")
            self.assertEqual(result["transition_id"], tail["transition_id"])
            self.assertEqual(result["from_state"], "VERIFIED")
            self.assertEqual(result["to_state"], "RC_READY")
            self.assertEqual(result["actor"], "VERIFIER")
            self.assertEqual(result["manifest_path"], "state/release-candidate.json")
            self.assertEqual(
                result["manifest_sha256"],
                hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
            )
            self.assertEqual(result["manifest_size_bytes"], manifest_path.stat().st_size)
            self.assertEqual(result["audit_generation"], current["audit_generation"])
            self.assertEqual(result["audit_head_event_id"], current["audit_head_event_id"])
            self.assertEqual(result["audit_head_hash"], current["audit_head_hash"])
            self.assertEqual(result["state_identity_status"], "UNCHANGED_DURING_QUERY")
            self.assertEqual(result["audit_identity_status"], "UNCHANGED_DURING_QUERY")
            self.assertEqual(result["evidence_identity_status"], "REVALIDATED")
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_rc_ready_transition_commit_verification_rejects_non_rc_ready_tail(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            prepare_verified_rc_lineage(state_root, ["verification-current"])
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "authoritative audit tail is not a committed VERIFIED to RC_READY transition",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).rc_ready_transition_commit_verification("ftic-governance-1")

            self.assertEqual(tree_bytes(state_root), before)

    def test_rc_ready_transition_commit_verification_rejects_verified_evidence_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            _, _, verification_paths = prepare_committed_rc_ready(
                state_root,
                ["verification-current"],
            )
            verification_path = verification_paths[0]
            verification = json.loads(verification_path.read_text(encoding="utf-8"))
            verification_path.write_bytes(
                canonical_json_bytes(
                    dict(verification, verification_id="verification-replaced")
                )
                + b"\n"
            )
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "bound evidence binding content changed",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).rc_ready_transition_commit_verification("ftic-governance-1")

            self.assertEqual(tree_bytes(state_root), before)

    def test_rc_ready_transition_commit_verification_rejects_concurrent_state_and_audit_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, manifest_path, _ = prepare_committed_rc_ready(
                state_root,
                ["verification-current"],
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            original_validate = reader._validate_gate_evidence
            closed = False

            def close_after_validation(*args, **kwargs):
                nonlocal closed
                result = original_validate(*args, **kwargs)
                if not closed:
                    writer.advance(
                        "ftic-governance-1",
                        "CLOSED",
                        actor="CONTROLLER",
                        evidence_paths=[manifest_path],
                        created_at_utc="2026-08-23T01:11:00Z",
                    )
                    closed = True
                return result

            with patch.object(
                reader,
                "_validate_gate_evidence",
                side_effect=close_after_validation,
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "RC_READY transition commit identity changed during verification",
                ):
                    reader.rc_ready_transition_commit_verification("ftic-governance-1")

            self.assertEqual(writer.status("ftic-governance-1")["current_state"], "CLOSED")

    def test_rc_ready_transition_commit_verification_rejects_evidence_drift_during_query(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            _, manifest_path, verification_paths = prepare_committed_rc_ready(
                state_root,
                ["verification-current"],
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            original_validate = reader._validate_gate_evidence
            verification_path = verification_paths[0]

            def mutate_after_validation(*args, **kwargs):
                result = original_validate(*args, **kwargs)
                verification = json.loads(
                    verification_path.read_text(encoding="utf-8")
                )
                verification_path.write_bytes(
                    canonical_json_bytes(
                        dict(verification, verification_id="verification-replaced")
                    )
                    + b"\n"
                )
                return result

            with patch.object(
                reader,
                "_validate_gate_evidence",
                side_effect=mutate_after_validation,
            ):
                with self.assertRaisesRegex(
                    WorkflowEngineError,
                    "bound evidence binding content changed",
                ):
                    reader.rc_ready_transition_commit_verification("ftic-governance-1")

    def test_closed_transition_commit_verification_enforces_exact_existing_contracts_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "verified-closure-state"
            writer, _, _ = prepare_verified_rc_lineage(
                state_root,
                ["verification-current"],
            )
            verified_event = writer.audit("ftic-governance-1")[-1]
            evidence_paths = [
                writer._bound_evidence_path(binding)
                for binding in verified_event["evidence_bindings"]
            ]
            writer.advance(
                "ftic-governance-1",
                "CLOSED",
                actor="CONTROLLER",
                evidence_paths=evidence_paths,
                created_at_utc="2026-08-30T01:11:00Z",
            )
            before = tree_bytes(state_root)

            result = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).closed_transition_commit_verification("ftic-governance-1")

            self.assertEqual(result["status"], "CLOSED_TRANSITION_COMMIT_VERIFIED")
            self.assertEqual(result["from_state"], "VERIFIED")
            self.assertEqual(result["to_state"], "CLOSED")
            self.assertEqual(result["actor"], "CONTROLLER")
            self.assertEqual(result["evidence_kind"], "VERIFIED_CLOSURE_EVIDENCE")
            self.assertEqual(result["evidence_count"], len(evidence_paths))
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "rc-ready-closure-state"
            writer, manifest_path = prepare_rc_ready_lineage(state_root)
            writer.advance(
                "ftic-governance-1",
                "CLOSED",
                actor="CONTROLLER",
                evidence_paths=[manifest_path],
                created_at_utc="2026-08-30T01:12:00Z",
            )
            before = tree_bytes(state_root)

            result = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).closed_transition_commit_verification("ftic-governance-1")

            self.assertEqual(result["status"], "CLOSED_TRANSITION_COMMIT_VERIFIED")
            self.assertEqual(result["from_state"], "RC_READY")
            self.assertEqual(result["to_state"], "CLOSED")
            self.assertEqual(result["actor"], "CONTROLLER")
            self.assertEqual(result["evidence_kind"], "RELEASE_CANDIDATE_MANIFEST")
            self.assertEqual(result["evidence_count"], 1)
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
            self.assertEqual(tree_bytes(state_root), before)

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "unsupported-tail-state"
            prepare_committed_rc_ready(state_root, ["verification-current"])
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "authoritative audit tail is not a supported committed CLOSED transition",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).closed_transition_commit_verification("ftic-governance-1")

            self.assertEqual(tree_bytes(state_root), before)

    def test_closed_transition_commit_verification_rejects_evidence_drift_during_query(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, verification_paths = prepare_verified_rc_lineage(
                state_root,
                ["verification-current"],
            )
            verified_event = writer.audit("ftic-governance-1")[-1]
            evidence_paths = [
                writer._bound_evidence_path(binding)
                for binding in verified_event["evidence_bindings"]
            ]
            writer.advance(
                "ftic-governance-1",
                "CLOSED",
                actor="CONTROLLER",
                evidence_paths=evidence_paths,
                created_at_utc="2026-08-30T01:11:00Z",
            )
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            original_validate = reader._validate_gate_evidence
            verification_path = verification_paths[0]
            mutated = False

            def mutate_after_validation(*args, **kwargs):
                nonlocal mutated
                snapshots = original_validate(*args, **kwargs)
                if not mutated:
                    record = json.loads(verification_path.read_text(encoding="utf-8"))
                    verification_path.write_bytes(
                        canonical_json_bytes(
                            dict(record, verification_id="verification-replaced")
                        )
                        + b"\n"
                    )
                    mutated = True
                return snapshots

            with patch.object(
                reader,
                "_validate_gate_evidence",
                side_effect=mutate_after_validation,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "CLOSED evidence must exactly match the latest trusted VERIFIED audit evidence",
            ):
                reader.closed_transition_commit_verification("ftic-governance-1")

            self.assertTrue(mutated)

    def test_transition_commit_verification_dispatches_existing_verifiers_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        def verify(state_root: Path, expected_status: str) -> dict[str, object]:
            before = tree_bytes(state_root)
            result = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            ).transition_commit_verification("ftic-governance-1")
            self.assertEqual(result["status"], expected_status)
            self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
            self.assertEqual(
                result["controls"]["workflow_transition"],
                "NOT_PERFORMED",
            )
            self.assertEqual(tree_bytes(state_root), before)
            return result

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "result-state"
            prepare_trusted_result_transition(state_root, role="PLANNER")
            result = verify(
                state_root,
                "TRUSTED_TASK_PACKET_RESULT_TRANSITION_COMMIT_VERIFIED",
            )
            self.assertEqual((result["from_state"], result["to_state"]), (
                "CLASSIFIED",
                "SPEC_READY",
            ))

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "handoff-state"
            prepare_trusted_handoff_transition(state_root, remediation=False)
            result = verify(
                state_root,
                "TRUSTED_TASK_PACKET_HANDOFF_TRANSITION_COMMIT_VERIFIED",
            )
            self.assertEqual((result["from_state"], result["to_state"]), (
                "PLAN_READY",
                "IMPLEMENTING",
            ))

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "resume-state"
            prepare_waiting_human_resume_transition(state_root)
            result = verify(
                state_root,
                "WAITING_HUMAN_RESUME_TRANSITION_COMMIT_VERIFIED",
            )
            self.assertEqual(result["from_state"], "WAITING_HUMAN")

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "rc-ready-state"
            prepare_committed_rc_ready(state_root, ["verification-current"])
            result = verify(state_root, "RC_READY_TRANSITION_COMMIT_VERIFIED")
            self.assertEqual((result["from_state"], result["to_state"]), (
                "VERIFIED",
                "RC_READY",
            ))

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "closed-state"
            writer, manifest_path, _ = prepare_committed_rc_ready(
                state_root,
                ["verification-current"],
            )
            writer.advance(
                "ftic-governance-1",
                "CLOSED",
                actor="CONTROLLER",
                evidence_paths=[manifest_path],
                created_at_utc="2026-08-30T01:12:00Z",
            )
            result = verify(state_root, "CLOSED_TRANSITION_COMMIT_VERIFIED")
            self.assertEqual((result["from_state"], result["to_state"]), (
                "RC_READY",
                "CLOSED",
            ))

    def test_transition_commit_verification_rejects_unsupported_tail_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            prepare_r2_classified_packet(state_root, role="PLANNER")
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "authoritative audit tail is not supported by unified committed transition verification",
            ):
                WorkflowEngine(
                    ROOT,
                    state_root,
                    MVP_FTIC_ROOT,
                    "ftic-v1",
                    read_only=True,
                ).transition_commit_verification("ftic-governance-1")

            self.assertEqual(tree_bytes(state_root), before)

    def test_transition_commit_verification_rejects_same_family_route_drift(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, packet_path, _, _ = prepare_trusted_result_transition(
                state_root,
                role="PLANNER",
            )
            packet = json.loads(packet_path.read_text(encoding="utf-8"))
            reader = WorkflowEngine(
                ROOT,
                state_root,
                MVP_FTIC_ROOT,
                "ftic-v1",
                read_only=True,
            )
            original_verify = (
                reader.trusted_task_packet_result_transition_commit_verification
            )
            advanced = False

            def advance_then_verify(task_id: str):
                nonlocal advanced
                writer.advance(
                    task_id,
                    "PLAN_READY",
                    actor="PLANNER",
                    evidence_paths=write_planner_transition_evidence(
                        writer,
                        target="PLAN_READY",
                        packet=packet,
                    ),
                    created_at_utc="2026-08-30T02:01:00Z",
                )
                advanced = True
                return original_verify(task_id)

            with patch.object(
                reader,
                "trusted_task_packet_result_transition_commit_verification",
                side_effect=advance_then_verify,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "unified transition commit identity changed during routing",
            ):
                reader.transition_commit_verification("ftic-governance-1")

            self.assertTrue(advanced)

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

    def test_verified_to_closed_preview_exposes_exact_latest_verifier_contract_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, _ = prepare_verified_rc_lineage(
                state_root,
                ["verification-first", "verification-second"],
            )
            verified_event = writer.audit("ftic-governance-1")[-1]
            evidence_paths = [
                writer._bound_evidence_path(binding)
                for binding in verified_event["evidence_bindings"]
            ]
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
                        "minimum_count": 4,
                        "maximum_count": 4,
                        "ordered_kinds": [
                            "VERIFIER_TASK_PACKET",
                            "VERIFIER_RESULT",
                            "VERIFICATION_RECORD",
                        ],
                        "repeatable_tail": True,
                    },
                },
            )

            preview = reader.direct_transition_gate_preview(
                "ftic-governance-1",
                "CLOSED",
                actor="CONTROLLER",
                evidence_paths=evidence_paths,
                created_at_utc="2026-08-23T01:09:00Z",
            )

            self.assertEqual(preview["current_state"], "VERIFIED")
            self.assertEqual(preview["target_state"], "CLOSED")
            self.assertEqual(preview["required_actor"], "CONTROLLER")
            self.assertEqual(preview["evidence_status"], "VALIDATED")
            self.assertEqual(
                [
                    (
                        binding["path"],
                        binding["size_bytes"],
                        binding["content_sha256"],
                    )
                    for binding in preview["evidence_bindings"]
                ],
                [
                    (
                        binding["path"],
                        binding["size_bytes"],
                        binding["content_sha256"],
                    )
                    for binding in verified_event["evidence_bindings"]
                ],
            )
            self.assertEqual(preview["authorization_status"], "NOT_GRANTED")
            self.assertEqual(tree_bytes(state_root), before)

    def test_verified_to_closed_rejects_non_controller_and_unbound_evidence_without_mutation(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            writer, _, _ = prepare_verified_rc_lineage(
                state_root,
                ["verification-current"],
            )
            verified_event = writer.audit("ftic-governance-1")[-1]
            evidence_paths = [
                writer._bound_evidence_path(binding)
                for binding in verified_event["evidence_bindings"]
            ]
            copied_packet = state_root / "copied-verifier-packet.json"
            copied_packet.write_bytes(evidence_paths[0].read_bytes())
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
                "CLOSED requires actor CONTROLLER",
            ):
                reader.direct_transition_gate_preview(
                    "ftic-governance-1",
                    "CLOSED",
                    actor="VERIFIER",
                    evidence_paths=evidence_paths,
                    created_at_utc="2026-08-23T01:09:00Z",
                )

            with self.assertRaisesRegex(
                WorkflowEngineError,
                "CLOSED evidence must exactly match the latest trusted VERIFIED audit evidence",
            ):
                reader.direct_transition_gate_preview(
                    "ftic-governance-1",
                    "CLOSED",
                    actor="CONTROLLER",
                    evidence_paths=[copied_packet, *evidence_paths[1:]],
                    created_at_utc="2026-08-23T01:09:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_verified_to_closed_commits_exact_latest_verifier_evidence_as_controller(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine, _, _ = prepare_verified_rc_lineage(
                state_root,
                ["verification-current"],
            )
            verified_event = engine.audit("ftic-governance-1")[-1]
            evidence_paths = [
                engine._bound_evidence_path(binding)
                for binding in verified_event["evidence_bindings"]
            ]

            state = engine.advance(
                "ftic-governance-1",
                "CLOSED",
                actor="CONTROLLER",
                evidence_paths=evidence_paths,
                created_at_utc="2026-08-23T01:09:00Z",
            )

            event = engine.audit("ftic-governance-1")[-1]
            self.assertEqual(state["current_state"], "CLOSED")
            self.assertEqual(event["from_state"], "VERIFIED")
            self.assertEqual(event["to_state"], "CLOSED")
            self.assertEqual(event["actor"], "CONTROLLER")
            self.assertEqual(
                [
                    (
                        binding["path"],
                        binding["size_bytes"],
                        binding["content_sha256"],
                    )
                    for binding in event["evidence_bindings"]
                ],
                [
                    (
                        binding["path"],
                        binding["size_bytes"],
                        binding["content_sha256"],
                    )
                    for binding in verified_event["evidence_bindings"]
                ],
            )

    def test_verified_to_closed_revalidates_evidence_after_event_construction(self) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine, _, verification_paths = prepare_verified_rc_lineage(
                state_root,
                ["verification-current"],
            )
            verified_event = engine.audit("ftic-governance-1")[-1]
            evidence_paths = [
                engine._bound_evidence_path(binding)
                for binding in verified_event["evidence_bindings"]
            ]
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")
            original_canonical_sha = engine._canonical_sha
            evidence_mutated = False

            def mutate_evidence_while_hashing_closed_event(record):
                nonlocal evidence_mutated
                digest = original_canonical_sha(record)
                if (
                    not evidence_mutated
                    and record.get("event_type") == "TRANSITION_ACCEPTED"
                    and record.get("to_state") == "CLOSED"
                ):
                    write_verification_record(
                        verification_paths[0],
                        "verification-mutated-after-event-construction",
                    )
                    evidence_mutated = True
                return digest

            with patch.object(
                engine,
                "_canonical_sha",
                side_effect=mutate_evidence_while_hashing_closed_event,
            ), self.assertRaisesRegex(
                WorkflowEngineError,
                "CLOSED evidence must exactly match the latest trusted VERIFIED audit evidence",
            ):
                engine.advance(
                    "ftic-governance-1",
                    "CLOSED",
                    actor="CONTROLLER",
                    evidence_paths=evidence_paths,
                    created_at_utc="2026-08-23T01:09:00Z",
                )

            self.assertTrue(evidence_mutated)
            self.assertEqual(engine.status("ftic-governance-1"), before_state)
            self.assertEqual(engine.audit("ftic-governance-1"), before_audit)

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

    def test_rc_ready_to_closed_revalidates_references_after_event_construction(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine, manifest_path = prepare_rc_ready_lineage(state_root)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            source_path = manifest_path.parent / manifest["source_artifact"]["path"]
            before_state = engine.status("ftic-governance-1")
            before_audit = engine.audit("ftic-governance-1")
            original_canonical_sha = engine._canonical_sha
            source_mutated = False

            def mutate_source_while_hashing_closed_event(record):
                nonlocal source_mutated
                digest = original_canonical_sha(record)
                if (
                    not source_mutated
                    and record.get("event_type") == "TRANSITION_ACCEPTED"
                    and record.get("to_state") == "CLOSED"
                ):
                    source_path.write_text(
                        "mutated after closure event construction\n",
                        encoding="utf-8",
                    )
                    source_mutated = True
                return digest

            with patch.object(
                engine,
                "_canonical_sha",
                side_effect=mutate_source_while_hashing_closed_event,
            ), self.assertRaisesRegex(WorkflowEngineError, "artifact hash mismatch: source.txt"):
                engine.advance(
                    "ftic-governance-1",
                    "CLOSED",
                    actor="CONTROLLER",
                    evidence_paths=[manifest_path],
                    created_at_utc="2026-08-23T01:11:00Z",
                )

            self.assertTrue(source_mutated)
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
