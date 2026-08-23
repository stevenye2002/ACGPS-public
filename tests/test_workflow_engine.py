from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from acgps.review_adapter import build_release_candidate_manifest
from tests.test_mvp_cli import (
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


class WorkflowEngineTests(unittest.TestCase):
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
                    actor="CONTROLLER",
                    evidence_paths=[generic_evidence],
                    created_at_utc="2026-08-23T01:00:00Z",
                )
                self.assertEqual(state["current_state"], target)

            evidence_dir = state_root / "evidence"
            evidence_dir.mkdir()
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


if __name__ == "__main__":
    unittest.main()
