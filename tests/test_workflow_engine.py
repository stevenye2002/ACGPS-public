from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from acgps.review_adapter import build_release_candidate_manifest
from acgps.workflow_contracts import canonical_json_bytes
from tests.test_mvp_cli import (
    valid_agent_result,
    valid_coder_packet,
    valid_decision_request,
    valid_intake,
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


def advance_to_implementing(engine, *, hour: int) -> Path:
    engine.intake(valid_intake())
    evidence = MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
    for minute, target in enumerate(
        (
            "READY_FOR_CLASSIFICATION",
            "CLASSIFIED",
            "SPEC_READY",
            "PLAN_READY",
            "IMPLEMENTING",
        ),
        start=1,
    ):
        engine.advance(
            "ftic-governance-1",
            target,
            actor="CONTROLLER",
            evidence_paths=[evidence],
            created_at_utc=f"2026-08-23T{hour:02d}:{minute:02d}:00Z",
        )
    return evidence


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
                state = engine.advance(
                    "ftic-governance-1",
                    target,
                    actor="CODER" if target == "TASK_REVIEW" else "CONTROLLER",
                    evidence_paths=(
                        task_review_evidence if target == "TASK_REVIEW" else [generic_evidence]
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
            with self.assertRaises(WorkflowEngineError):
                engine.advance(
                    "ftic-governance-1",
                    "INTEGRATING",
                    actor="CODER",
                    evidence_paths=[review_path],
                    created_at_utc="2026-08-23T01:01:00Z",
                )
            state = engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=[review_path],
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
            with self.assertRaises(WorkflowEngineError):
                engine.advance(
                    "ftic-governance-1",
                    "VERIFIED",
                    actor="VERIFIER",
                    evidence_paths=[verification_path],
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
                    evidence_paths=[verification_path],
                    created_at_utc="2026-08-23T01:02:00Z",
                )
            state = engine.advance(
                "ftic-governance-1",
                "VERIFIED",
                actor="VERIFIER",
                evidence_paths=[verification_path],
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
            state = engine.advance(
                "ftic-governance-1",
                "RC_READY",
                actor="CONTROLLER",
                evidence_paths=[manifest_path],
                created_at_utc="2026-08-23T01:04:00Z",
            )

            self.assertEqual(state["current_state"], "RC_READY")
            self.assertEqual(len(engine.audit("ftic-governance-1")), 10)
            self.assertEqual(tree_bytes(MVP_FTIC_ROOT), managed_before)

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
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(WorkflowEngineError, "open P0 or P1 review finding"):
                engine.advance(
                    "ftic-governance-1",
                    "FIX_REQUIRED",
                    actor="REVIEWER",
                    evidence_paths=[closed_finding],
                    created_at_utc="2026-08-23T11:07:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)

    def test_repeated_fix_required_events_accumulate_all_blockers(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            generic_evidence = advance_to_task_review(engine, hour=12)
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
                evidence_paths=[open_a],
                created_at_utc="2026-08-23T12:07:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=[generic_evidence],
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
                evidence_paths=[open_b],
                created_at_utc="2026-08-23T12:10:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=[generic_evidence],
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
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(WorkflowEngineError, "finding-a"):
                engine.advance(
                    "ftic-governance-1",
                    "INTEGRATING",
                    actor="REVIEWER",
                    evidence_paths=[closed_b],
                    created_at_utc="2026-08-23T12:13:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)
            integrated = engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=[closed_a, closed_b],
                created_at_utc="2026-08-23T12:14:00Z",
            )
            self.assertEqual(integrated["current_state"], "INTEGRATING")

    def test_fix_cycle_rejects_tampered_bound_finding_without_mutation(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            generic_evidence = advance_to_task_review(engine, hour=13)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            open_a = evidence_dir / "open-a.json"
            original = write_review_finding(open_a, "finding-a", status="OPEN")
            engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=[open_a],
                created_at_utc="2026-08-23T13:07:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=[generic_evidence],
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
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(WorkflowEngineError, "binding content changed"):
                engine.advance(
                    "ftic-governance-1",
                    "INTEGRATING",
                    actor="REVIEWER",
                    evidence_paths=[closed_a],
                    created_at_utc="2026-08-23T13:10:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)
            open_a.write_bytes(original)
            integrated = engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=[closed_a],
                created_at_utc="2026-08-23T13:11:00Z",
            )
            self.assertEqual(integrated["current_state"], "INTEGRATING")

    def test_fix_cycle_survives_audit_generation_recovery(self) -> None:
        from acgps.workflow_engine import WorkflowEngine, WorkflowEngineError

        with tempfile.TemporaryDirectory() as tmp:
            state_root = Path(tmp) / "state"
            engine = WorkflowEngine(ROOT, state_root, MVP_FTIC_ROOT, "ftic-v1")
            generic_evidence = advance_to_task_review(engine, hour=14)
            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
            open_a = evidence_dir / "open-a.json"
            write_review_finding(open_a, "finding-a", status="OPEN")
            fixed = engine.advance(
                "ftic-governance-1",
                "FIX_REQUIRED",
                actor="REVIEWER",
                evidence_paths=[open_a],
                created_at_utc="2026-08-23T14:07:00Z",
            )
            start_recovery_generation(engine, fixed, created_at_utc="2026-08-23T14:08:00Z")
            engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=[generic_evidence],
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
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(WorkflowEngineError, "finding-a"):
                engine.advance(
                    "ftic-governance-1",
                    "INTEGRATING",
                    actor="REVIEWER",
                    evidence_paths=[unrelated],
                    created_at_utc="2026-08-23T14:11:00Z",
                )

            self.assertEqual(tree_bytes(state_root), before)
            integrated = engine.advance(
                "ftic-governance-1",
                "INTEGRATING",
                actor="REVIEWER",
                evidence_paths=[closed_a],
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
                evidence_paths=[open_a],
                created_at_utc="2026-08-23T15:07:00Z",
            )
            engine.advance(
                "ftic-governance-1",
                "IMPLEMENTING",
                actor="CODER",
                evidence_paths=[generic_evidence],
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
                evidence_paths=[closed_a],
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
            before = tree_bytes(state_root)

            with self.assertRaisesRegex(WorkflowEngineError, "integration boundary"):
                engine.advance(
                    "ftic-governance-1",
                    "VERIFIED",
                    actor="VERIFIER",
                    evidence_paths=[stale],
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
            verified = engine.advance(
                "ftic-governance-1",
                "VERIFIED",
                actor="VERIFIER",
                evidence_paths=[fresh],
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
                actor="CONTROLLER",
                evidence_paths=[evidence],
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
                actor="CONTROLLER",
                evidence_paths=[evidence],
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

            with patch.object(
                engine.store,
                "commit_task_state_and_audit",
                side_effect=commit_failure,
            ):
                with self.assertRaises(WorkflowEngineError):
                    engine.advance(
                        "ftic-governance-1",
                        "SPEC_READY",
                        actor="CONTROLLER",
                        evidence_paths=[evidence],
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
                actor="CONTROLLER",
                evidence_paths=[evidence],
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

            with patch.object(
                engine.decisions,
                "resolve",
                side_effect=DecisionQueueError("injected resolution publication failure"),
            ):
                with self.assertRaises(WorkflowEngineError):
                    engine.advance(
                        "ftic-governance-1",
                        "SPEC_READY",
                        actor="CONTROLLER",
                        evidence_paths=[evidence],
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
