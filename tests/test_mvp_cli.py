from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from acgps.contracts import validate_contract
from acgps.task_packets import generate_task_packet
from acgps.workflow_contracts import canonical_json_bytes
from tests.test_contracts import _valid_prelaunch_hold_coding_execution_record


def valid_intake() -> dict[str, object]:
    return {
        "schema_version": 1,
        "task_id": "ftic-governance-1",
        "project_id": "FTIC",
        "title": "Exercise the bounded FTIC governance workflow",
        "requested_outcome": "Produce a reviewable governance-only release candidate.",
        "business_context": "First ACGPS dogfood task without FTIC domain changes.",
        "in_scope": ["governance workflow evidence"],
        "out_of_scope": ["FTIC production intelligence changes"],
        "acceptance_criteria": ["independent review evidence is closed", "verification evidence is green"],
        "known_constraints": ["managed FTIC root is read-only"],
        "known_risks": [],
        "affected_surfaces": ["report_copy_only"],
        "source_paths": ["docs/FTIC_PROJECT_REPLAN.md"],
        "requested_by": "human_owner",
        "created_at_utc": "2026-08-23T00:00:00Z",
    }


def valid_policy_result() -> dict[str, object]:
    return {
        "schema_version": 1,
        "evaluation_id": "eval-1",
        "project_id": "FTIC",
        "task_id": "ftic-governance-1",
        "policy_bundle_digest": "a" * 64,
        "result": {
            "decision_emitted": True,
            "risk_level": "R1",
            "human_gate": False,
            "required_human_triggers": [],
            "required_skills": ["superpowers_writing_plans"],
            "model_roles": {"planner": "planner_architect"},
            "mandatory_gates": ["focused_check", "lightweight_review"],
            "legal_transitions": ["SPEC_READY"],
            "authorized_transitions": ["SPEC_READY"],
            "provenance": ["config/workflow_policy.yaml:transitions.CLASSIFIED"],
            "fail_closed": False,
            "error_code": None,
            "issues": [],
        },
        "created_at_utc": "2026-08-23T00:01:00Z",
    }


def valid_agent_result() -> dict[str, object]:
    return {
        "schema_version": 1,
        "packet_id": "ftic-governance-1-coder-v1",
        "role": "CODER",
        "status": "DONE",
        "summary": "Completed the bounded implementation.",
        "changed_files": ["docs/FTIC_PROJECT_REPLAN.md"],
        "created_files": [],
        "commands_run": ["python -m unittest tests.test_supervised_handoff"],
        "evidence_paths": ["evidence/focused.txt"],
        "assumptions": [],
        "concerns": [],
        "blocker": None,
        "recommended_next_state": "TASK_REVIEW",
    }


def valid_coder_packet() -> dict[str, object]:
    return generate_task_packet("CODER", valid_intake(), valid_policy_result())


def valid_decision_request() -> dict[str, object]:
    return {
        "schema_version": 1,
        "decision_id": "decision-1",
        "project_id": "FTIC",
        "task_id": "ftic-governance-1",
        "stage": "SPEC_READY",
        "risk_level": "R1",
        "trigger": "H1_PRODUCT_INTENT",
        "question": "Resume the bounded governance task?",
        "recommended_option": "RESUME",
        "recommendation_rationale": "The approved intent is unchanged.",
        "options": [
            {
                "id": "RESUME",
                "description": "Resume at SPEC_READY.",
                "benefits": ["continues bounded work"],
                "costs": [],
                "risks": [],
                "reversible": True,
            }
        ],
        "default_without_response": "PAUSE",
        "evidence_paths": [],
        "created_at_utc": "2026-08-23T00:02:00Z",
        "status": "PENDING",
    }


def valid_review_finding(*, severity: str = "P1", status: str = "CLOSED") -> dict[str, object]:
    return {
        "schema_version": 1,
        "finding_id": "finding-1",
        "review_id": "review-1",
        "severity": severity,
        "category": "correctness",
        "summary": "Frozen candidate is acceptable.",
        "evidence_paths": ["evidence/review.txt"],
        "impact": "No blocking impact remains.",
        "recommendation": "Keep the bounded implementation.",
        "disposition": "ALREADY_FIXED",
        "status": status,
        "rationale": "Verified against the frozen source.",
        "verification_required": ["focused tests"],
    }


def valid_verification_record() -> dict[str, object]:
    return {
        "schema_version": 1,
        "verification_id": "verification-1",
        "project_id": "FTIC",
        "task_id": "ftic-governance-1",
        "baseline_hash": "b" * 64,
        "checks": [
            {
                "name": "focused",
                "command": "python -m unittest tests.test_mvp_cli",
                "exit_code": 0,
                "result_summary": "pass",
                "output_path": "evidence/focused.txt",
            }
        ],
        "requirements_checked": ["bounded governance flow"],
        "failed_requirements": [],
        "verified_at_utc": "2026-08-23T00:03:00Z",
        "verifier_role": "VERIFIER",
        "recommendation": "VERIFIED",
    }


class MVPArtifactTests(unittest.TestCase):
    def test_decision_queue_is_create_once_and_resolves_a_matching_option(self) -> None:
        from acgps.human_decisions import DecisionQueue, DecisionQueueError

        with tempfile.TemporaryDirectory() as tmp:
            queue = DecisionQueue(Path(tmp) / "decisions")
            request = valid_decision_request()
            pending_path = queue.create(request)
            self.assertEqual(json.loads(pending_path.read_text(encoding="utf-8")), request)
            self.assertEqual(queue.create(dict(request)), pending_path)

            with self.assertRaises(DecisionQueueError):
                queue.create(dict(request, question="conflicting replacement"))

            resolution = {
                "schema_version": 1,
                "decision_id": "decision-1",
                "project_id": "FTIC",
                "task_id": "ftic-governance-1",
                "selected_option": "RESUME",
                "resolved_by": "human_owner",
                "resolved_at_utc": "2026-08-23T00:04:00Z",
                "rationale": "Continue within the approved boundary.",
                "evidence_paths": [],
                "resume_state": "SPEC_READY",
                "status": "RESOLVED",
            }
            with self.assertRaises(DecisionQueueError):
                queue.resolve(dict(resolution, resume_state="PLAN_READY"))
            self.assertFalse(queue.resolved_path("decision-1").exists())
            self.assertEqual([row["decision_id"] for row in queue.list_pending()], ["decision-1"])

            resolved_path = queue.resolve(resolution)

            self.assertEqual(json.loads(resolved_path.read_text(encoding="utf-8")), resolution)
            self.assertEqual(queue.resolve(dict(resolution)), resolved_path)
            self.assertEqual(queue.list_pending(), [])

    def test_task_packet_is_derived_from_existing_contracts(self) -> None:
        from acgps.task_packets import generate_task_packet

        packet = generate_task_packet("PLANNER", valid_intake(), valid_policy_result())

        validate_contract("agent_task_contract", packet, mode="runtime")
        self.assertEqual(packet["objective"], valid_intake()["requested_outcome"])
        self.assertEqual(packet["required_skills"], ["superpowers_writing_plans"])
        self.assertEqual(packet["acceptance_criteria"], valid_intake()["acceptance_criteria"])

    def test_review_and_rc_adapter_rejects_blocking_findings_and_tampering(self) -> None:
        from acgps.review_adapter import (
            ReviewEvidenceError,
            build_release_candidate_manifest,
            validate_review_findings,
            verify_release_candidate_manifest,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = root / "evidence"
            evidence.mkdir()
            open_finding_path = evidence / "open-finding.json"
            open_finding_path.write_text(
                json.dumps(valid_review_finding(status="OPEN"), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(ReviewEvidenceError):
                validate_review_findings([open_finding_path])

            closed_finding_path = evidence / "closed-finding.json"
            closed_finding_path.write_text(
                json.dumps(valid_review_finding(), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            verification_path = evidence / "verification.json"
            verification_path.write_text(
                json.dumps(valid_verification_record(), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            source_path = root / "source.txt"
            source_path.write_text("frozen source\n", encoding="utf-8")
            build_path = root / "acgps-mvp-v0.1-source.zip"
            build_path.write_bytes(b"frozen build artifact\n")
            rollback_path = root / "rollback.md"
            rollback_path.write_text("No production release; remove runtime output.\n", encoding="utf-8")

            manifest_path = build_release_candidate_manifest(
                output_dir=root,
                project_id="FTIC",
                rc_id="ftic-governance-rc-1",
                version="0.1-dogfood",
                source_path=source_path,
                build_artifact_paths=[build_path],
                verification_paths=[verification_path],
                review_paths=[closed_finding_path],
                rollback_path=rollback_path,
                created_at_utc="2026-08-23T00:05:00Z",
            )

            self.assertTrue(
                verify_release_candidate_manifest(
                    manifest_path,
                    expected_project_id="FTIC",
                    require_build_artifacts=True,
                )
            )
            original_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                original_manifest["build_artifacts"],
                [
                    {
                        "path": "acgps-mvp-v0.1-source.zip",
                        "sha256": hashlib.sha256(build_path.read_bytes()).hexdigest(),
                    }
                ],
            )
            invalid_manifests = {
                "blocked-status": dict(original_manifest, status="BLOCKED"),
                "foreign-project": dict(original_manifest, project_id="OTHER"),
                "release-authorized": dict(
                    original_manifest,
                    human_release_authorization="decision-release-1",
                ),
                "missing-verification": dict(original_manifest, verification_records=[]),
                "missing-review": dict(original_manifest, review_closures=[]),
            }
            for label, invalid_manifest in invalid_manifests.items():
                with self.subTest(label=label):
                    manifest_path.write_text(
                        json.dumps(invalid_manifest, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaises(ReviewEvidenceError):
                        verify_release_candidate_manifest(
                            manifest_path,
                            expected_project_id="FTIC",
                            require_build_artifacts=True,
                        )
            manifest_path.write_text(
                json.dumps(original_manifest, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            build_path.write_bytes(b"tampered build artifact\n")
            with self.assertRaises(ReviewEvidenceError):
                verify_release_candidate_manifest(
                    manifest_path,
                    expected_project_id="FTIC",
                    require_build_artifacts=True,
                )
            build_path.write_bytes(b"frozen build artifact\n")
            source_path.write_text("tampered source\n", encoding="utf-8")
            with self.assertRaises(ReviewEvidenceError):
                verify_release_candidate_manifest(manifest_path, expected_project_id="FTIC")


class MVPCLITests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]
    FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "mvp_ftic"

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.state_root = Path(self.temporary_directory.name) / "state"
        self.state_root.mkdir()
        self.environment = dict(os.environ)
        self.environment["PYTHONPATH"] = str(self.ROOT)
        self.fixture_before = self._tree_identity(self.FIXTURE_ROOT)

    def tearDown(self) -> None:
        self.assertEqual(self._tree_identity(self.FIXTURE_ROOT), self.fixture_before)
        self.temporary_directory.cleanup()

    @staticmethod
    def _tree_identity(root: Path) -> list[tuple[str, bytes]]:
        return [
            (path.relative_to(root).as_posix(), path.read_bytes())
            for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
            if path.is_file()
        ]

    @staticmethod
    def _state_root_identity(root: Path) -> list[tuple[str, int, int, int, bytes | None]]:
        paths = [root, *sorted(root.rglob("*"), key=lambda item: item.as_posix())]
        return [
            (
                "." if path == root else path.relative_to(root).as_posix(),
                path.lstat().st_mode,
                path.lstat().st_size,
                path.lstat().st_mtime_ns,
                path.read_bytes() if path.is_file() else None,
            )
            for path in paths
        ]

    def _run(self, *arguments: str, expected_exit: int = 0) -> dict[str, object]:
        completed = subprocess.run(
            [sys.executable, "-m", "acgps", *arguments],
            cwd=self.ROOT,
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(
            completed.returncode,
            expected_exit,
            msg=f"stdout={completed.stdout!r}\nstderr={completed.stderr!r}",
        )
        output = completed.stdout.strip()
        self.assertTrue(output, msg=f"stderr={completed.stderr!r}")
        return json.loads(output)

    def _engine_arguments(self) -> list[str]:
        return [
            "--policy-root",
            str(self.ROOT),
            "--state-root",
            str(self.state_root),
            "--project-root",
            str(self.FIXTURE_ROOT),
            "--profile-id",
            "ftic-v1",
        ]

    def _prepare_r2_packet(self) -> tuple[Path, dict[str, object]]:
        self._run(
            "task",
            "intake",
            *self._engine_arguments(),
            "--intake",
            str(self.FIXTURE_ROOT / "task-intake.yaml"),
        )
        evidence = self.FIXTURE_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
        self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "READY_FOR_CLASSIFICATION",
            "--actor",
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-29T04:11:00Z",
            "--evidence",
            str(evidence),
        )
        self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "CLASSIFIED",
            "--actor",
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-29T04:12:00Z",
            "--evidence",
            str(evidence),
            "--risk-trigger",
            "public_api",
            "--task-attribute",
            "change_type=review_artifact",
        )
        packet_path = self.state_root / "packets" / "planner.json"
        packet = self._run(
            "packet",
            "generate",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--role",
            "PLANNER",
            "--created-at-utc",
            "2026-08-29T04:13:00Z",
            "--output",
            str(packet_path),
        )
        return packet_path, packet

    def test_cli_packet_generate_rejects_before_classification_without_output(self) -> None:
        self._run(
            "task",
            "intake",
            *self._engine_arguments(),
            "--intake",
            str(self.FIXTURE_ROOT / "task-intake.yaml"),
        )
        output_path = self.state_root / "packets" / "planner.json"
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "packet",
            "generate",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--role",
            "PLANNER",
            "--created-at-utc",
            "2026-08-29T03:00:00Z",
            "--output",
            str(output_path),
            expected_exit=2,
        )

        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("exactly one trusted accepted CLASSIFIED policy", result["error"])
        self.assertFalse(output_path.exists())
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_packet_generate_preserves_trusted_accepted_r2_policy(self) -> None:
        self._run(
            "task",
            "intake",
            *self._engine_arguments(),
            "--intake",
            str(self.FIXTURE_ROOT / "task-intake.yaml"),
        )
        evidence = self.FIXTURE_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
        self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "READY_FOR_CLASSIFICATION",
            "--actor",
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-29T03:01:00Z",
            "--evidence",
            str(evidence),
        )
        self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "CLASSIFIED",
            "--actor",
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-29T03:02:00Z",
            "--evidence",
            str(evidence),
            "--risk-trigger",
            "public_api",
            "--task-attribute",
            "change_type=review_artifact",
        )
        output_path = self.state_root / "packets" / "planner.json"

        packet = self._run(
            "packet",
            "generate",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--role",
            "PLANNER",
            "--created-at-utc",
            "2026-08-29T03:03:00Z",
            "--output",
            str(output_path),
        )

        self.assertEqual(
            packet["required_skills"],
            [
                "superpowers_writing_plans",
                "superpowers_requesting_code_review",
                "superpowers_verification_before_completion",
            ],
        )
        self.assertEqual(
            packet["required_evidence"],
            [
                "architecture",
                "plan",
                "broad_verification",
                "high_capability_review",
                "rc_evidence",
            ],
        )
        self.assertEqual(json.loads(output_path.read_text(encoding="utf-8")), packet)

    def test_cli_packet_verify_matches_current_trusted_lineage_without_state_write(
        self,
    ) -> None:
        packet_path, packet = self._prepare_r2_packet()
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "packet",
            "verify",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--packet",
            str(packet_path),
        )

        self.assertEqual(result["status"], "TASK_PACKET_VERIFIED")
        self.assertEqual(result["packet_id"], packet["packet_id"])
        self.assertEqual(result["role"], "PLANNER")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_trusted_task_packet_handoff_without_state_write(self) -> None:
        packet_path, packet = self._prepare_r2_packet()
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "packet",
            "trusted-handoff-preview",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--packet",
            str(packet_path),
        )

        self.assertEqual(result["status"], "TRUSTED_TASK_PACKET_HANDOFF_PREVIEW")
        self.assertEqual(
            result["task_packet_verification"]["status"],
            "TASK_PACKET_VERIFIED",
        )
        self.assertEqual(result["task_packet_verification"]["role"], "PLANNER")
        self.assertEqual(result["handoff_preview"]["status"], "HANDOFF_PREVIEW")
        self.assertEqual(result["handoff_preview"]["packet"], packet)
        self.assertEqual(
            result["handoff_preview"]["controls"]["state_write"],
            "NOT_PERFORMED",
        )
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_trusted_task_packet_result_receipt_without_state_write(
        self,
    ) -> None:
        packet_path, packet = self._prepare_r2_packet()
        agent_result = dict(
            valid_agent_result(),
            packet_id=packet["packet_id"],
            role="PLANNER",
            changed_files=[],
            recommended_next_state="SPEC_READY",
        )
        result_path = self.state_root / "results" / "planner.json"
        result_path.parent.mkdir(parents=True)
        result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "packet",
            "trusted-result-receipt-preview",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--packet",
            str(packet_path),
            "--result",
            str(result_path),
        )

        self.assertEqual(
            result["status"],
            "TRUSTED_TASK_PACKET_RESULT_RECEIPT_PREVIEW",
        )
        self.assertEqual(
            result["task_packet_verification"]["status"],
            "TASK_PACKET_VERIFIED",
        )
        receipt = result["result_receipt_preview"]
        self.assertEqual(receipt["status"], "RESULT_RECEIPT_PREVIEW")
        self.assertEqual(receipt["agent_result"], agent_result)
        self.assertEqual(receipt["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_trusted_result_transition_gate_without_state_write(
        self,
    ) -> None:
        packet_path, packet = self._prepare_r2_packet()
        agent_result = dict(
            valid_agent_result(),
            packet_id=packet["packet_id"],
            role="PLANNER",
            changed_files=[],
            recommended_next_state="SPEC_READY",
        )
        result_path = self.state_root / "results" / "planner.json"
        result_path.parent.mkdir(parents=True)
        result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "packet",
            "trusted-result-transition-gate-preview",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--packet",
            str(packet_path),
            "--result",
            str(result_path),
            "--created-at-utc",
            "2026-08-29T05:10:00Z",
        )

        self.assertEqual(
            result["status"],
            "TRUSTED_TASK_PACKET_RESULT_TO_TRANSITION_GATE_PREVIEW",
        )
        self.assertEqual(
            result["trusted_result_receipt_preview"]["status"],
            "TRUSTED_TASK_PACKET_RESULT_RECEIPT_PREVIEW",
        )
        gate = result["transition_gate_preview"]
        self.assertEqual(gate["current_state"], "CLASSIFIED")
        self.assertEqual(gate["target_state"], "SPEC_READY")
        self.assertEqual(gate["required_actor"], "PLANNER")
        self.assertEqual(gate["authorization_status"], "NOT_GRANTED")
        self.assertEqual(gate["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(gate["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_advances_trusted_result_through_existing_transition_contract(
        self,
    ) -> None:
        packet_path, packet = self._prepare_r2_packet()
        agent_result = dict(
            valid_agent_result(),
            packet_id=packet["packet_id"],
            role="PLANNER",
            changed_files=[],
            recommended_next_state="SPEC_READY",
        )
        result_path = self.state_root / "results" / "planner.json"
        result_path.parent.mkdir(parents=True)
        result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")

        result = self._run(
            "packet",
            "trusted-result-transition-advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--packet",
            str(packet_path),
            "--result",
            str(result_path),
            "--created-at-utc",
            "2026-08-29T06:20:00Z",
        )

        self.assertEqual(result["current_state"], "SPEC_READY")
        status = self._run(
            "task",
            "status",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--include-audit",
        )
        event = status["audit"][-1]
        self.assertEqual(event["actor"], "PLANNER")
        self.assertEqual(event["to_state"], "SPEC_READY")
        self.assertEqual(
            [binding["content_sha256"] for binding in event["evidence_bindings"]],
            [
                hashlib.sha256(packet_path.read_bytes()).hexdigest(),
                hashlib.sha256(result_path.read_bytes()).hexdigest(),
            ],
        )

    def test_cli_verifies_committed_trusted_result_transition_without_state_writes(
        self,
    ) -> None:
        packet_path, packet = self._prepare_r2_packet()
        agent_result = dict(
            valid_agent_result(),
            packet_id=packet["packet_id"],
            role="PLANNER",
            changed_files=[],
            recommended_next_state="SPEC_READY",
        )
        result_path = self.state_root / "results" / "planner.json"
        result_path.parent.mkdir(parents=True)
        result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
        self._run(
            "packet",
            "trusted-result-transition-advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--packet",
            str(packet_path),
            "--result",
            str(result_path),
            "--created-at-utc",
            "2026-08-29T06:21:00Z",
        )
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "packet",
            "trusted-result-transition-commit-verify",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )

        self.assertEqual(
            result["status"],
            "TRUSTED_TASK_PACKET_RESULT_TRANSITION_COMMIT_VERIFIED",
        )
        self.assertEqual(result["from_state"], "CLASSIFIED")
        self.assertEqual(result["to_state"], "SPEC_READY")
        self.assertEqual(result["actor"], "PLANNER")
        self.assertEqual(result["packet_id"], packet["packet_id"])
        self.assertEqual(result["evidence_count"], 2)
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_verifies_committed_trusted_handoff_transition_without_state_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        packet_path, packet = self._prepare_r2_packet()
        engine = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        for index, target in enumerate(("SPEC_READY", "PLAN_READY"), start=1):
            result_path = self.state_root / "results" / f"planner-{target.casefold()}.json"
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_bytes(
                canonical_json_bytes(
                    dict(
                        valid_agent_result(),
                        packet_id=packet["packet_id"],
                        role="PLANNER",
                        changed_files=[],
                        created_files=[],
                        recommended_next_state=target,
                    )
                )
                + b"\n"
            )
            engine.advance(
                "ftic-governance-1",
                target,
                actor="PLANNER",
                evidence_paths=[packet_path, result_path],
                created_at_utc=f"2026-08-29T06:3{index}:00Z",
            )
        coder_packet_path = self.state_root / "packets" / "coder.json"
        coder_packet = self._run(
            "packet",
            "generate",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--role",
            "CODER",
            "--created-at-utc",
            "2026-08-29T06:33:00Z",
            "--output",
            str(coder_packet_path),
        )
        self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "IMPLEMENTING",
            "--actor",
            "CODER",
            "--created-at-utc",
            "2026-08-29T06:34:00Z",
            "--evidence",
            str(coder_packet_path),
        )
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "packet",
            "trusted-handoff-transition-commit-verify",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )

        self.assertEqual(
            result["status"],
            "TRUSTED_TASK_PACKET_HANDOFF_TRANSITION_COMMIT_VERIFIED",
        )
        self.assertEqual(result["from_state"], "PLAN_READY")
        self.assertEqual(result["to_state"], "IMPLEMENTING")
        self.assertEqual(result["actor"], "CODER")
        self.assertEqual(result["packet_id"], coder_packet["packet_id"])
        self.assertEqual(result["evidence_kind"], "CODER_HANDOFF")
        self.assertEqual(result["evidence_count"], 1)
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_packet_verify_rejects_tampering_without_state_write(self) -> None:
        packet_path, packet = self._prepare_r2_packet()
        packet_path.write_bytes(
            canonical_json_bytes(
                dict(packet, objective="Replace the trusted task objective.")
            )
            + b"\n"
        )
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "packet",
            "verify",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--packet",
            str(packet_path),
            expected_exit=2,
        )

        self.assertEqual(result["status"], "REJECTED")
        self.assertIn(
            "does not match the current trusted task policy and intake lineage",
            result["error"],
        )
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_packet_generate_rejects_same_identity_mutated_intake_without_output(self) -> None:
        self._run(
            "task",
            "intake",
            *self._engine_arguments(),
            "--intake",
            str(self.FIXTURE_ROOT / "task-intake.yaml"),
        )
        evidence = self.FIXTURE_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
        for index, target in enumerate(
            ("READY_FOR_CLASSIFICATION", "CLASSIFIED"),
            start=1,
        ):
            self._run(
                "task",
                "advance",
                *self._engine_arguments(),
                "--task-id",
                "ftic-governance-1",
                "--to-state",
                target,
                "--actor",
                "CONTROLLER",
                "--created-at-utc",
                f"2026-08-29T03:1{index}:00Z",
                "--evidence",
                str(evidence),
            )
        intake_path = self.state_root / "tasks" / "ftic-governance-1" / "intake.json"
        mutated = json.loads(intake_path.read_text(encoding="utf-8"))
        mutated["requested_outcome"] = "Replace the accepted task objective."
        intake_path.write_bytes(canonical_json_bytes(mutated) + b"\n")
        output_path = self.state_root / "packets" / "mutated-planner.json"
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "packet",
            "generate",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--role",
            "PLANNER",
            "--created-at-utc",
            "2026-08-29T03:13:00Z",
            "--output",
            str(output_path),
            expected_exit=2,
        )

        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("task intake does not match the trusted initialization proof", result["error"])
        self.assertFalse(output_path.exists())
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def _waiting_human_resolution(self) -> tuple[dict[str, object], Path]:
        self._run(
            "task",
            "intake",
            *self._engine_arguments(),
            "--intake",
            str(self.FIXTURE_ROOT / "task-intake.yaml"),
        )
        evidence = self.FIXTURE_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
        for index, target in enumerate(("READY_FOR_CLASSIFICATION", "CLASSIFIED"), start=1):
            self._run(
                "task",
                "advance",
                *self._engine_arguments(),
                "--task-id",
                "ftic-governance-1",
                "--to-state",
                target,
                "--actor",
                "CONTROLLER",
                "--created-at-utc",
                f"2026-08-28T01:0{index}:00Z",
                "--evidence",
                str(evidence),
            )
        waiting = self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "SPEC_READY",
            "--actor",
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-28T01:03:00Z",
            "--evidence",
            str(evidence),
            "--human-trigger",
            "H1_PRODUCT_INTENT",
        )
        resolution: dict[str, object] = {
            "schema_version": 1,
            "decision_id": waiting["pending_decision_id"],
            "project_id": "FTIC",
            "task_id": "ftic-governance-1",
            "selected_option": "RESUME",
            "resolved_by": "human_owner",
            "resolved_at_utc": "2026-08-28T01:04:00Z",
            "rationale": "Continue the approved supervised workflow.",
            "evidence_paths": [],
            "resume_state": "SPEC_READY",
            "status": "RESOLVED",
        }
        resolution_path = self.state_root / "decision-resolution-preview.json"
        resolution_path.write_bytes(canonical_json_bytes(resolution) + b"\n")
        return resolution, resolution_path

    def _release_candidate_manifest(
        self,
        *,
        include_build_artifact: bool = True,
    ) -> tuple[Path, Path, Path]:
        from acgps.review_adapter import build_release_candidate_manifest

        root = Path(self.temporary_directory.name) / "rc-verify"
        evidence = root / "evidence"
        evidence.mkdir(parents=True)
        source = root / "source.zip"
        source.write_bytes(b"frozen source\n")
        build = root / "build.zip"
        build.write_bytes(b"frozen build\n")
        verification = evidence / "verification.json"
        verification.write_text(
            json.dumps(valid_verification_record(), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        review = evidence / "review.json"
        review.write_text(
            json.dumps(valid_review_finding(), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rollback = root / "rollback.md"
        rollback.write_text("Delete the local candidate.\n", encoding="utf-8")
        manifest = build_release_candidate_manifest(
            output_dir=root,
            project_id="FTIC",
            rc_id="ftic-governance-rc-verify",
            version="1.0-test",
            source_path=source,
            build_artifact_paths=[build] if include_build_artifact else [],
            verification_paths=[verification],
            review_paths=[review],
            rollback_path=rollback,
            created_at_utc="2026-08-28T02:00:00Z",
        )
        return root, manifest, build

    def test_cli_verifies_existing_rc_manifest_without_writes(self) -> None:
        root, manifest, _ = self._release_candidate_manifest()
        before = self._state_root_identity(root)

        result = self._run(
            "rc",
            "verify",
            "--manifest",
            str(manifest),
            "--expected-project-id",
            "FTIC",
            "--expected-task-id",
            "ftic-governance-1",
            "--require-build-artifacts",
        )

        self.assertEqual(
            result,
            {
                "manifest_path": str(manifest.resolve(strict=True)),
                "status": "VALID",
            },
        )
        self.assertEqual(self._state_root_identity(root), before)

    def test_cli_rc_verify_rejects_identity_mismatch_without_writes(self) -> None:
        root, manifest, _ = self._release_candidate_manifest()
        before = self._state_root_identity(root)

        cases = (
            ("--expected-project-id", "OTHER", "project_id does not match"),
            ("--expected-task-id", "other-task", "task_id does not match"),
        )
        for flag, value, expected_error in cases:
            with self.subTest(flag=flag):
                result = self._run(
                    "rc",
                    "verify",
                    "--manifest",
                    str(manifest),
                    flag,
                    value,
                    expected_exit=2,
                )
                self.assertEqual(result["status"], "REJECTED")
                self.assertIn(expected_error, str(result["error"]))
        self.assertEqual(self._state_root_identity(root), before)

    def test_cli_rc_verify_enforces_required_build_artifacts_without_writes(self) -> None:
        root, manifest, _ = self._release_candidate_manifest(include_build_artifact=False)
        before = self._state_root_identity(root)

        result = self._run(
            "rc",
            "verify",
            "--manifest",
            str(manifest),
            "--require-build-artifacts",
            expected_exit=2,
        )

        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("requires at least one build artifact", str(result["error"]))
        self.assertEqual(self._state_root_identity(root), before)

    def test_cli_rc_verify_rejects_tampered_artifact_without_writes(self) -> None:
        root, manifest, build = self._release_candidate_manifest()
        build.write_bytes(b"tampered build\n")
        before = self._state_root_identity(root)

        result = self._run(
            "rc",
            "verify",
            "--manifest",
            str(manifest),
            "--require-build-artifacts",
            expected_exit=2,
        )

        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("artifact hash mismatch", str(result["error"]))
        self.assertEqual(self._state_root_identity(root), before)

    def test_cli_previews_task_next_actions_without_state_writes(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        engine = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        engine.intake(valid_intake())
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "task",
            "next-action-preview",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )

        self.assertEqual(result["status"], "NEXT_ACTION_PREVIEW")
        self.assertEqual(result["current_state"], "DRAFT")
        self.assertEqual(result["authorization_status"], "NOT_EVALUATED")
        self.assertEqual(
            [option["target_state"] for option in result["options"]],
            ["READY_FOR_CLASSIFICATION", "ABANDONED"],
        )
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_verifies_task_audit_lineage_without_state_writes(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        engine = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        current = engine.intake(valid_intake())
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "task",
            "audit-verify",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )

        self.assertEqual(result["status"], "AUDIT_LINEAGE_VERIFIED")
        self.assertEqual(result["task_id"], "ftic-governance-1")
        self.assertEqual(result["project_id"], "FTIC")
        self.assertEqual(result["current_state"], "DRAFT")
        self.assertEqual(result["audit_generation"], 1)
        self.assertEqual(result["trusted_generation_count"], 1)
        self.assertEqual(result["trusted_event_count"], 1)
        self.assertEqual(result["audit_head_event_id"], current["audit_head_event_id"])
        self.assertEqual(result["audit_head_hash"], current["audit_head_hash"])
        self.assertEqual(result["state_identity_status"], "UNCHANGED_DURING_QUERY")
        self.assertEqual(result["controls"]["model_execution"], "NOT_STARTED")
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_reports_trusted_task_progress_without_state_writes(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        engine = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        current = engine.intake(valid_intake())
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "task",
            "progress-summary",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )

        self.assertEqual(result["status"], "TRUSTED_TASK_PROGRESS_SUMMARY")
        self.assertEqual(result["current_state"], "DRAFT")
        self.assertEqual(result["audit_head_hash"], current["audit_head_hash"])
        self.assertEqual(
            result["audit_verification"]["status"],
            "AUDIT_LINEAGE_VERIFIED",
        )
        self.assertEqual(
            result["next_action_preview"]["status"],
            "NEXT_ACTION_PREVIEW",
        )
        self.assertEqual(result["controls"]["model_execution"], "NOT_STARTED")
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_reports_trusted_project_progress_without_state_writes(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        engine = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        first_intake = valid_intake()
        second_intake = dict(
            first_intake,
            task_id="ftic-governance-2",
            title="Second bounded FTIC governance task",
            created_at_utc="2026-08-23T00:10:00Z",
        )
        engine.intake(first_intake)
        engine.intake(second_intake)
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "project",
            "progress-summary",
            *self._engine_arguments(),
        )

        self.assertEqual(result["status"], "TRUSTED_PROJECT_PROGRESS_SUMMARY")
        self.assertEqual(result["project_id"], "FTIC")
        self.assertEqual(result["task_count"], 2)
        self.assertEqual(result["state_counts"], {"DRAFT": 2})
        self.assertEqual(
            [task["task_id"] for task in result["tasks"]],
            ["ftic-governance-1", "ftic-governance-2"],
        )
        self.assertEqual(result["controls"]["model_execution"], "NOT_STARTED")
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_reports_trusted_project_audit_lineage_summary_without_state_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        engine = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        first_intake = valid_intake()
        second_intake = dict(
            first_intake,
            task_id="ftic-governance-2",
            title="Second bounded FTIC governance task",
            created_at_utc="2026-08-23T00:10:00Z",
        )
        engine.intake(first_intake)
        engine.intake(second_intake)
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "project",
            "audit-lineage-summary",
            *self._engine_arguments(),
        )

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
        self.assertEqual(result["controls"]["model_execution"], "NOT_STARTED")
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_verifies_captured_project_audit_lineage_summary_without_state_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        writer = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        writer.intake(valid_intake())
        reader = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
            read_only=True,
        )
        captured = reader.trusted_project_audit_lineage_summary()
        capture_path = self.state_root / "project-audit-lineage-summary.json"
        capture_bytes = (json.dumps(captured, sort_keys=True) + "\n").encode("utf-8")
        capture_path.write_bytes(capture_bytes)
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "project",
            "audit-lineage-summary-verify",
            *self._engine_arguments(),
            "--summary",
            str(capture_path),
        )

        self.assertEqual(
            result["status"],
            "TRUSTED_PROJECT_AUDIT_LINEAGE_SUMMARY_VERIFIED",
        )
        self.assertEqual(result["project_id"], "FTIC")
        self.assertEqual(result["task_count"], 1)
        self.assertEqual(
            result["captured_summary_sha256"],
            hashlib.sha256(capture_bytes).hexdigest(),
        )
        self.assertEqual(
            result["captured_summary_identity_status"],
            "UNCHANGED_DURING_QUERY",
        )
        self.assertEqual(
            result["current_summary_identity_status"],
            "UNCHANGED_DURING_QUERY",
        )
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_verifies_captured_project_progress_summary_without_state_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        writer = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        writer.intake(valid_intake())
        reader = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
            read_only=True,
        )
        captured = reader.trusted_project_progress_summary()
        capture_path = self.state_root / "project-progress-summary.json"
        capture_bytes = (json.dumps(captured, sort_keys=True) + "\n").encode("utf-8")
        capture_path.write_bytes(capture_bytes)
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "project",
            "progress-summary-verify",
            *self._engine_arguments(),
            "--summary",
            str(capture_path),
        )

        self.assertEqual(result["status"], "TRUSTED_PROJECT_PROGRESS_SUMMARY_VERIFIED")
        self.assertEqual(result["project_id"], "FTIC")
        self.assertEqual(result["task_count"], 1)
        self.assertEqual(
            result["captured_summary_sha256"],
            hashlib.sha256(capture_bytes).hexdigest(),
        )
        self.assertEqual(
            result["captured_summary_identity_status"],
            "UNCHANGED_DURING_QUERY",
        )
        self.assertEqual(
            result["current_summary_identity_status"],
            "UNCHANGED_DURING_QUERY",
        )
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_reports_trusted_project_next_action_queue_without_state_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        engine = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        first_intake = valid_intake()
        second_intake = dict(
            first_intake,
            task_id="ftic-governance-2",
            title="Second bounded FTIC governance task",
            created_at_utc="2026-08-23T00:10:00Z",
        )
        engine.intake(first_intake)
        engine.intake(second_intake)
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "project",
            "next-action-queue",
            *self._engine_arguments(),
        )

        self.assertEqual(result["status"], "TRUSTED_PROJECT_NEXT_ACTION_QUEUE")
        self.assertEqual(result["project_id"], "FTIC")
        self.assertEqual(result["task_count"], 2)
        self.assertEqual(
            [item["task_id"] for item in result["queue"]],
            ["ftic-governance-1", "ftic-governance-2"],
        )
        self.assertTrue(
            all(item["authorization_status"] == "NOT_EVALUATED" for item in result["queue"])
        )
        self.assertTrue(
            all(item["selected_transition"] is None for item in result["queue"])
        )
        self.assertEqual(result["controls"]["model_execution"], "NOT_STARTED")
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_reports_trusted_project_pending_decision_queue_without_state_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        engine = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        engine.intake(valid_intake())
        evidence = self.FIXTURE_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
        for index, target in enumerate(("READY_FOR_CLASSIFICATION", "CLASSIFIED"), start=1):
            engine.advance(
                "ftic-governance-1",
                target,
                actor="CONTROLLER",
                evidence_paths=[evidence],
                created_at_utc=f"2026-08-27T14:0{index}:00Z",
            )
        waiting = engine.advance(
            "ftic-governance-1",
            "SPEC_READY",
            actor="CONTROLLER",
            evidence_paths=[evidence],
            human_triggers=["H1_PRODUCT_INTENT"],
            created_at_utc="2026-08-27T14:03:00Z",
        )
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "project",
            "pending-decision-queue",
            *self._engine_arguments(),
        )

        self.assertEqual(result["status"], "TRUSTED_PROJECT_PENDING_DECISION_QUEUE")
        self.assertEqual(result["queue_status"], "PENDING")
        self.assertEqual(result["project_id"], "FTIC")
        self.assertEqual(result["pending_decision_count"], 1)
        self.assertEqual(
            result["decisions"][0]["decision_id"],
            waiting["pending_decision_id"],
        )
        self.assertEqual(
            result["decisions"][0]["question"],
            "Authorize transition to SPEC_READY?",
        )
        self.assertEqual(result["decisions"][0]["recommended_option"], "RESUME")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_verifies_captured_project_pending_decision_queue_without_state_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        writer = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        writer.intake(valid_intake())
        evidence = self.FIXTURE_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
        for index, target in enumerate(("READY_FOR_CLASSIFICATION", "CLASSIFIED"), start=1):
            writer.advance(
                "ftic-governance-1",
                target,
                actor="CONTROLLER",
                evidence_paths=[evidence],
                created_at_utc=f"2026-08-27T15:0{index}:00Z",
            )
        writer.advance(
            "ftic-governance-1",
            "SPEC_READY",
            actor="CONTROLLER",
            evidence_paths=[evidence],
            human_triggers=["H1_PRODUCT_INTENT"],
            created_at_utc="2026-08-27T15:03:00Z",
        )
        reader = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
            read_only=True,
        )
        captured = reader.trusted_project_pending_decision_queue()
        capture_path = self.state_root / "project-pending-decision-queue.json"
        capture_bytes = (json.dumps(captured, sort_keys=True) + "\n").encode("utf-8")
        capture_path.write_bytes(capture_bytes)
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "project",
            "pending-decision-queue-verify",
            *self._engine_arguments(),
            "--queue",
            str(capture_path),
        )

        self.assertEqual(
            result["status"],
            "TRUSTED_PROJECT_PENDING_DECISION_QUEUE_VERIFIED",
        )
        self.assertEqual(result["project_id"], "FTIC")
        self.assertEqual(result["queue_status"], "PENDING")
        self.assertEqual(result["pending_decision_count"], 1)
        self.assertEqual(
            result["captured_queue_sha256"],
            hashlib.sha256(capture_bytes).hexdigest(),
        )
        self.assertEqual(
            result["captured_queue_identity_status"],
            "UNCHANGED_DURING_QUERY",
        )
        self.assertEqual(
            result["current_queue_identity_status"],
            "UNCHANGED_DURING_QUERY",
        )
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_verifies_captured_project_next_action_queue_without_state_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        writer = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        writer.intake(valid_intake())
        reader = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
            read_only=True,
        )
        captured = reader.trusted_project_next_action_queue()
        capture_path = self.state_root / "project-next-action-queue.json"
        capture_bytes = (json.dumps(captured, sort_keys=True) + "\n").encode("utf-8")
        capture_path.write_bytes(capture_bytes)
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "project",
            "next-action-queue-verify",
            *self._engine_arguments(),
            "--queue",
            str(capture_path),
        )

        self.assertEqual(
            result["status"],
            "TRUSTED_PROJECT_NEXT_ACTION_QUEUE_VERIFIED",
        )
        self.assertEqual(result["project_id"], "FTIC")
        self.assertEqual(result["task_count"], 1)
        self.assertEqual(
            result["captured_queue_sha256"],
            hashlib.sha256(capture_bytes).hexdigest(),
        )
        self.assertEqual(
            result["captured_queue_identity_status"],
            "UNCHANGED_DURING_QUERY",
        )
        self.assertEqual(
            result["current_queue_identity_status"],
            "UNCHANGED_DURING_QUERY",
        )
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_validated_direct_transition_gate_without_state_writes(self) -> None:
        from acgps.workflow_engine import WorkflowEngine

        engine = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        engine.intake(valid_intake())
        generic_evidence = self.FIXTURE_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
        for index, target in enumerate(("READY_FOR_CLASSIFICATION", "CLASSIFIED"), start=1):
            engine.advance(
                "ftic-governance-1",
                target,
                actor="CONTROLLER",
                evidence_paths=[generic_evidence],
                created_at_utc=f"2026-08-28T04:0{index}:00Z",
            )

        evidence_root = self.state_root / "gate-preview-evidence"
        evidence_root.mkdir()
        planner_packet = generate_task_packet("PLANNER", valid_intake(), valid_policy_result())
        planner_packet_path = evidence_root / "planner-packet.json"
        planner_packet_path.write_bytes(canonical_json_bytes(planner_packet) + b"\n")
        for index, target in enumerate(("SPEC_READY", "PLAN_READY"), start=3):
            planner_result_path = evidence_root / f"planner-{target.casefold()}-result.json"
            planner_result_path.write_bytes(
                canonical_json_bytes(
                    dict(
                        valid_agent_result(),
                        packet_id=planner_packet["packet_id"],
                        role="PLANNER",
                        summary=f"Completed the bounded Planner work for {target}.",
                        changed_files=[],
                        created_files=[],
                        recommended_next_state=target,
                    )
                )
                + b"\n"
            )
            engine.advance(
                "ftic-governance-1",
                target,
                actor="PLANNER",
                evidence_paths=[planner_packet_path, planner_result_path],
                created_at_utc=f"2026-08-28T04:0{index}:00Z",
            )

        coder_packet_path = evidence_root / "coder-packet.json"
        coder_packet_path.write_bytes(canonical_json_bytes(valid_coder_packet()) + b"\n")
        current = engine.status("ftic-governance-1")
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "task",
            "gate-preview",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "IMPLEMENTING",
            "--actor",
            "CODER",
            "--created-at-utc",
            "2026-08-28T04:05:00Z",
            "--evidence",
            str(coder_packet_path),
        )

        self.assertEqual(result["status"], "DIRECT_TRANSITION_GATE_PREVIEW")
        self.assertEqual(result["current_state"], "PLAN_READY")
        self.assertEqual(result["target_state"], "IMPLEMENTING")
        self.assertEqual(result["required_actor"], "CODER")
        self.assertEqual(result["evidence_status"], "VALIDATED")
        self.assertEqual(result["audit_head_hash"], current["audit_head_hash"])
        self.assertEqual(result["authorization_status"], "NOT_GRANTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

        rejected = self._run(
            "task",
            "gate-preview",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "IMPLEMENTING",
            "--actor",
            "CODER",
            "--created-at-utc",
            "2026-08-28T04:06:00Z",
            "--evidence",
            str(coder_packet_path),
            "--human-trigger",
            "H1_PRODUCT_INTENT",
            expected_exit=2,
        )
        self.assertEqual(rejected["status"], "REJECTED")
        self.assertIn("cannot create a WAITING_HUMAN decision", rejected["error"])
        self.assertEqual(self._state_root_identity(self.state_root), before)

        for label, extra_arguments in (
            ("ordinary", ()),
            ("human-gated", ("--human-trigger", "H1_PRODUCT_INTENT")),
        ):
            with self.subTest(explicit_waiting_human=label):
                explicit_waiting = self._run(
                    "task",
                    "gate-preview",
                    *self._engine_arguments(),
                    "--task-id",
                    "ftic-governance-1",
                    "--to-state",
                    "WAITING_HUMAN",
                    "--actor",
                    "CODER",
                    "--created-at-utc",
                    "2026-08-28T04:07:00Z",
                    "--evidence",
                    str(coder_packet_path),
                    *extra_arguments,
                    expected_exit=2,
                )
                self.assertEqual(explicit_waiting["status"], "REJECTED")
                self.assertIn(
                    "does not accept WAITING_HUMAN as a target",
                    explicit_waiting["error"],
                )
                self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_binds_waiting_human_next_action_to_pending_decision(self) -> None:
        self._run(
            "task",
            "intake",
            *self._engine_arguments(),
            "--intake",
            str(self.FIXTURE_ROOT / "task-intake.yaml"),
        )
        evidence = self.FIXTURE_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
        for index, target in enumerate(("READY_FOR_CLASSIFICATION", "CLASSIFIED"), start=1):
            self._run(
                "task",
                "advance",
                *self._engine_arguments(),
                "--task-id",
                "ftic-governance-1",
                "--to-state",
                target,
                "--actor",
                "CONTROLLER",
                "--created-at-utc",
                f"2026-08-27T09:0{index}:00Z",
                "--evidence",
                str(evidence),
            )
        waiting = self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "SPEC_READY",
            "--actor",
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-27T09:03:00Z",
            "--evidence",
            str(evidence),
            "--human-trigger",
            "H1_PRODUCT_INTENT",
        )
        before = self._state_root_identity(self.state_root)

        preview = self._run(
            "task",
            "next-action-preview",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )

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
            [option["target_state"] for option in preview["options"]],
            ["SPEC_READY"],
        )
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_validated_human_decision_resolution_without_state_writes(self) -> None:
        resolution, resolution_path = self._waiting_human_resolution()
        before = self._state_root_identity(self.state_root)

        preview = self._run(
            "decision",
            "resolution-preview",
            "--state-root",
            str(self.state_root),
            "--resolution",
            str(resolution_path),
        )

        self.assertEqual(
            preview,
            {
                "status": "RESOLUTION_PREVIEW",
                "decision_id": resolution["decision_id"],
                "project_id": "FTIC",
                "task_id": "ftic-governance-1",
                "selected_option": "RESUME",
                "resume_state": "SPEC_READY",
                "pending_request_status": "PENDING",
                "authorization_status": "NOT_EVALUATED",
                "controls": {
                    "model_execution": "NOT_STARTED",
                    "process_launch": "NOT_STARTED",
                    "state_write": "NOT_PERFORMED",
                    "workflow_transition": "NOT_PERFORMED",
                },
            },
        )
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_project_bound_pending_decision_resolution_without_state_writes(
        self,
    ) -> None:
        resolution, resolution_path = self._waiting_human_resolution()
        before = self._state_root_identity(self.state_root)

        preview = self._run(
            "project",
            "pending-decision-resolution-preview",
            *self._engine_arguments(),
            "--resolution",
            str(resolution_path),
        )

        self.assertEqual(
            preview["status"],
            "TRUSTED_PROJECT_PENDING_DECISION_RESOLUTION_PREVIEW",
        )
        self.assertEqual(preview["decision_id"], resolution["decision_id"])
        self.assertEqual(preview["project_id"], "FTIC")
        self.assertEqual(preview["task_id"], "ftic-governance-1")
        self.assertEqual(preview["selected_option"], "RESUME")
        self.assertEqual(preview["resume_state"], "SPEC_READY")
        self.assertEqual(preview["pending_request_status"], "PENDING")
        self.assertEqual(preview["authorization_status"], "NOT_EVALUATED")
        self.assertEqual(
            preview["resolution_identity"]["status"],
            "UNCHANGED_DURING_QUERY",
        )
        self.assertEqual(
            preview["project_queue_identity_status"],
            "UNCHANGED_DURING_QUERY",
        )
        self.assertEqual(preview["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(preview["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_verifies_captured_project_pending_decision_resolution_preview_without_state_writes(
        self,
    ) -> None:
        resolution, resolution_path = self._waiting_human_resolution()
        captured = self._run(
            "project",
            "pending-decision-resolution-preview",
            *self._engine_arguments(),
            "--resolution",
            str(resolution_path),
        )
        capture_path = self.state_root / "pending-decision-resolution-preview.json"
        capture_bytes = (json.dumps(captured, sort_keys=True) + "\n").encode("utf-8")
        capture_path.write_bytes(capture_bytes)
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "project",
            "pending-decision-resolution-preview-verify",
            *self._engine_arguments(),
            "--preview",
            str(capture_path),
        )

        self.assertEqual(
            result["status"],
            "TRUSTED_PROJECT_PENDING_DECISION_RESOLUTION_PREVIEW_VERIFIED",
        )
        self.assertEqual(result["decision_id"], resolution["decision_id"])
        self.assertEqual(result["project_id"], "FTIC")
        self.assertEqual(result["task_id"], "ftic-governance-1")
        self.assertEqual(result["authorization_status"], "NOT_EVALUATED")
        self.assertEqual(
            result["captured_preview_sha256"],
            hashlib.sha256(capture_bytes).hexdigest(),
        )
        self.assertEqual(
            result["captured_preview_identity_status"],
            "UNCHANGED_DURING_QUERY",
        )
        self.assertEqual(
            result["current_preview_identity_status"],
            "UNCHANGED_DURING_QUERY",
        )
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_composes_captured_project_resolution_with_resume_gate_without_state_writes(
        self,
    ) -> None:
        resolution, resolution_path = self._waiting_human_resolution()
        captured = self._run(
            "project",
            "pending-decision-resolution-preview",
            *self._engine_arguments(),
            "--resolution",
            str(resolution_path),
        )
        capture_path = self.state_root / "pending-decision-resolution-preview.json"
        capture_path.write_text(
            json.dumps(captured, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        evidence_root = self.state_root / "project-resume-gate-preview-evidence"
        evidence_root.mkdir()
        planner_packet = generate_task_packet(
            "PLANNER",
            valid_intake(),
            valid_policy_result(),
        )
        planner_packet_path = evidence_root / "planner-packet.json"
        planner_packet_path.write_bytes(canonical_json_bytes(planner_packet) + b"\n")
        planner_result_path = evidence_root / "planner-result.json"
        planner_result_path.write_bytes(
            canonical_json_bytes(
                dict(
                    valid_agent_result(),
                    packet_id=planner_packet["packet_id"],
                    role="PLANNER",
                    summary="Completed the bounded Planner work for SPEC_READY.",
                    changed_files=[],
                    created_files=[],
                    recommended_next_state="SPEC_READY",
                )
            )
            + b"\n"
        )
        before = self._state_root_identity(self.state_root)

        preview = self._run(
            "project",
            "pending-decision-resolution-to-resume-gate-preview",
            *self._engine_arguments(),
            "--preview",
            str(capture_path),
            "--actor",
            "PLANNER",
            "--created-at-utc",
            "2026-08-28T01:04:00Z",
            "--evidence",
            str(planner_packet_path),
            "--evidence",
            str(planner_result_path),
        )

        self.assertEqual(preview["status"], "WAITING_HUMAN_RESUME_GATE_PREVIEW")
        self.assertEqual(preview["task_id"], "ftic-governance-1")
        self.assertEqual(preview["target_state"], resolution["resume_state"])
        self.assertEqual(preview["required_actor"], "PLANNER")
        self.assertEqual(preview["decision_id"], resolution["decision_id"])
        self.assertEqual(preview["authorization_status"], "NOT_GRANTED")
        self.assertEqual(preview["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(
            preview["controls"]["workflow_transition"],
            "NOT_PERFORMED",
        )
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_verifies_captured_project_resolution_resume_gate_preview_without_state_writes(
        self,
    ) -> None:
        resolution, resolution_path = self._waiting_human_resolution()
        resolution_preview = self._run(
            "project",
            "pending-decision-resolution-preview",
            *self._engine_arguments(),
            "--resolution",
            str(resolution_path),
        )
        resolution_preview_path = (
            self.state_root / "pending-decision-resolution-preview.json"
        )
        resolution_preview_path.write_text(
            json.dumps(resolution_preview, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        evidence_root = self.state_root / "project-resume-gate-verification-evidence"
        evidence_root.mkdir()
        planner_packet = generate_task_packet(
            "PLANNER",
            valid_intake(),
            valid_policy_result(),
        )
        planner_packet_path = evidence_root / "planner-packet.json"
        planner_packet_path.write_bytes(canonical_json_bytes(planner_packet) + b"\n")
        planner_result_path = evidence_root / "planner-result.json"
        planner_result_path.write_bytes(
            canonical_json_bytes(
                dict(
                    valid_agent_result(),
                    packet_id=planner_packet["packet_id"],
                    role="PLANNER",
                    summary="Completed the bounded Planner work for SPEC_READY.",
                    changed_files=[],
                    created_files=[],
                    recommended_next_state="SPEC_READY",
                )
            )
            + b"\n"
        )
        gate_preview = self._run(
            "project",
            "pending-decision-resolution-to-resume-gate-preview",
            *self._engine_arguments(),
            "--preview",
            str(resolution_preview_path),
            "--actor",
            "PLANNER",
            "--created-at-utc",
            "2026-08-28T01:04:00Z",
            "--evidence",
            str(planner_packet_path),
            "--evidence",
            str(planner_result_path),
        )
        gate_preview_path = self.state_root / "project-resolution-resume-gate-preview.json"
        gate_preview_bytes = (
            json.dumps(gate_preview, sort_keys=True) + "\n"
        ).encode("utf-8")
        gate_preview_path.write_bytes(gate_preview_bytes)
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "project",
            "pending-decision-resolution-to-resume-gate-preview-verify",
            *self._engine_arguments(),
            "--gate-preview",
            str(gate_preview_path),
            "--preview",
            str(resolution_preview_path),
            "--actor",
            "PLANNER",
            "--created-at-utc",
            "2026-08-28T01:04:00Z",
            "--evidence",
            str(planner_packet_path),
            "--evidence",
            str(planner_result_path),
        )

        self.assertEqual(
            result["status"],
            "TRUSTED_PROJECT_PENDING_DECISION_RESOLUTION_TO_RESUME_GATE_PREVIEW_VERIFIED",
        )
        self.assertEqual(result["project_id"], "FTIC")
        self.assertEqual(result["task_id"], "ftic-governance-1")
        self.assertEqual(result["decision_id"], resolution["decision_id"])
        self.assertEqual(result["target_state"], resolution["resume_state"])
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
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_waiting_human_resume_gate_without_state_writes(self) -> None:
        resolution, resolution_path = self._waiting_human_resolution()
        evidence_root = self.state_root / "resume-gate-preview-evidence"
        evidence_root.mkdir()
        planner_packet = generate_task_packet("PLANNER", valid_intake(), valid_policy_result())
        planner_packet_path = evidence_root / "planner-packet.json"
        planner_packet_path.write_bytes(canonical_json_bytes(planner_packet) + b"\n")
        planner_result_path = evidence_root / "planner-result.json"
        planner_result_path.write_bytes(
            canonical_json_bytes(
                dict(
                    valid_agent_result(),
                    packet_id=planner_packet["packet_id"],
                    role="PLANNER",
                    summary="Completed the bounded Planner work for SPEC_READY.",
                    changed_files=[],
                    created_files=[],
                    recommended_next_state="SPEC_READY",
                )
            )
            + b"\n"
        )
        before = self._state_root_identity(self.state_root)

        preview = self._run(
            "task",
            "resume-gate-preview",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "SPEC_READY",
            "--actor",
            "PLANNER",
            "--created-at-utc",
            "2026-08-28T01:04:00Z",
            "--decision-resolution",
            str(resolution_path),
            "--evidence",
            str(planner_packet_path),
            "--evidence",
            str(planner_result_path),
        )

        self.assertEqual(preview["status"], "WAITING_HUMAN_RESUME_GATE_PREVIEW")
        self.assertEqual(preview["source_state_before_human_gate"], "CLASSIFIED")
        self.assertEqual(preview["target_state"], resolution["resume_state"])
        self.assertEqual(preview["required_actor"], "PLANNER")
        self.assertEqual(preview["decision_id"], resolution["decision_id"])
        self.assertEqual(preview["resolution_status"], "VALIDATED")
        self.assertEqual(preview["evidence_status"], "VALIDATED")
        self.assertEqual(preview["authorization_status"], "NOT_GRANTED")
        self.assertEqual(preview["controls"]["model_execution"], "NOT_STARTED")
        self.assertEqual(preview["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(preview["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(preview["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_verifies_committed_waiting_human_resume_transition_without_state_writes(
        self,
    ) -> None:
        resolution, resolution_path = self._waiting_human_resolution()
        evidence_root = self.state_root / "resume-commit-verification-evidence"
        evidence_root.mkdir()
        planner_packet = generate_task_packet(
            "PLANNER",
            valid_intake(),
            valid_policy_result(),
        )
        planner_packet_path = evidence_root / "planner-packet.json"
        planner_packet_path.write_bytes(canonical_json_bytes(planner_packet) + b"\n")
        planner_result_path = evidence_root / "planner-result.json"
        planner_result_path.write_bytes(
            canonical_json_bytes(
                dict(
                    valid_agent_result(),
                    packet_id=planner_packet["packet_id"],
                    role="PLANNER",
                    summary="Completed the bounded Planner work for SPEC_READY.",
                    changed_files=[],
                    created_files=[],
                    recommended_next_state="SPEC_READY",
                )
            )
            + b"\n"
        )
        self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "SPEC_READY",
            "--actor",
            "PLANNER",
            "--created-at-utc",
            "2026-08-28T01:04:00Z",
            "--decision-resolution",
            str(resolution_path),
            "--evidence",
            str(planner_packet_path),
            "--evidence",
            str(planner_result_path),
        )
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "task",
            "resume-transition-commit-verify",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )

        self.assertEqual(
            result["status"],
            "WAITING_HUMAN_RESUME_TRANSITION_COMMIT_VERIFIED",
        )
        self.assertEqual(result["source_state_before_human_gate"], "CLASSIFIED")
        self.assertEqual(result["from_state"], "WAITING_HUMAN")
        self.assertEqual(result["to_state"], "SPEC_READY")
        self.assertEqual(result["actor"], "PLANNER")
        self.assertEqual(result["decision_id"], resolution["decision_id"])
        self.assertEqual(result["decision_identity_status"], "REVALIDATED")
        self.assertEqual(result["evidence_identity_status"], "REVALIDATED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_verifies_committed_coder_resume_transition_without_state_writes(
        self,
    ) -> None:
        from acgps.workflow_engine import WorkflowEngine

        planner_packet_path, planner_packet = self._prepare_r2_packet()
        engine = WorkflowEngine(
            self.ROOT,
            self.state_root,
            self.FIXTURE_ROOT,
            "ftic-v1",
        )
        for index, target in enumerate(("SPEC_READY", "PLAN_READY"), start=1):
            planner_result_path = (
                self.state_root / "results" / f"planner-{target.casefold()}.json"
            )
            planner_result_path.parent.mkdir(parents=True, exist_ok=True)
            planner_result_path.write_bytes(
                canonical_json_bytes(
                    dict(
                        valid_agent_result(),
                        packet_id=planner_packet["packet_id"],
                        role="PLANNER",
                        changed_files=[],
                        created_files=[],
                        recommended_next_state=target,
                    )
                )
                + b"\n"
            )
            engine.advance(
                "ftic-governance-1",
                target,
                actor="PLANNER",
                evidence_paths=[planner_packet_path, planner_result_path],
                created_at_utc=f"2026-08-29T19:0{index}:00Z",
            )
        coder_packet_path = self.state_root / "packets" / "coder-resume.json"
        self._run(
            "packet",
            "generate",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--role",
            "CODER",
            "--created-at-utc",
            "2026-08-29T19:03:00Z",
            "--output",
            str(coder_packet_path),
        )
        waiting = engine.advance(
            "ftic-governance-1",
            "IMPLEMENTING",
            actor="CONTROLLER",
            evidence_paths=[coder_packet_path],
            human_triggers=["H1_PRODUCT_INTENT"],
            created_at_utc="2026-08-29T19:04:00Z",
        )
        resolution = {
            "schema_version": 1,
            "decision_id": waiting["pending_decision_id"],
            "project_id": "FTIC",
            "task_id": "ftic-governance-1",
            "selected_option": "RESUME",
            "resolved_by": "human_owner",
            "resolved_at_utc": "2026-08-29T19:05:00Z",
            "rationale": "Continue the approved supervised Coder workflow.",
            "evidence_paths": [],
            "resume_state": "IMPLEMENTING",
            "status": "RESOLVED",
        }
        engine.advance(
            "ftic-governance-1",
            "IMPLEMENTING",
            actor="CODER",
            evidence_paths=[coder_packet_path],
            decision_resolution=resolution,
            created_at_utc="2026-08-29T19:06:00Z",
        )
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "task",
            "resume-transition-commit-verify",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )

        self.assertEqual(
            result["status"],
            "WAITING_HUMAN_RESUME_TRANSITION_COMMIT_VERIFIED",
        )
        self.assertEqual(result["source_state_before_human_gate"], "PLAN_READY")
        self.assertEqual(result["from_state"], "WAITING_HUMAN")
        self.assertEqual(result["to_state"], "IMPLEMENTING")
        self.assertEqual(result["actor"], "CODER")
        self.assertEqual(result["evidence_kind"], "CODER_HANDOFF")
        self.assertEqual(result["decision_id"], resolution["decision_id"])
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_rejects_resolution_preview_for_non_authoritative_pending_request(self) -> None:
        from acgps.human_decisions import DecisionQueue
        from acgps.workflow_store import WorkflowStore

        WorkflowStore(self.state_root)
        request = valid_decision_request()
        DecisionQueue(self.state_root / "decisions").create(request)
        resolution = {
            "schema_version": 1,
            "decision_id": "decision-1",
            "project_id": "FTIC",
            "task_id": "ftic-governance-1",
            "selected_option": "RESUME",
            "resolved_by": "human_owner",
            "resolved_at_utc": "2026-08-28T01:04:00Z",
            "rationale": "Continue the approved supervised workflow.",
            "evidence_paths": [],
            "resume_state": "SPEC_READY",
            "status": "RESOLVED",
        }
        resolution_path = self.state_root / "decision-resolution-preview.json"
        resolution_path.write_bytes(canonical_json_bytes(resolution) + b"\n")
        before = self._state_root_identity(self.state_root)

        rejected = self._run(
            "decision",
            "resolution-preview",
            "--state-root",
            str(self.state_root),
            "--resolution",
            str(resolution_path),
            expected_exit=2,
        )

        self.assertEqual(rejected["status"], "REJECTED")
        self.assertIn("authoritative", rejected["error"])
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_rejects_resolution_preview_with_unoffered_option(self) -> None:
        resolution, resolution_path = self._waiting_human_resolution()
        invalid_resolution = dict(resolution, selected_option="UNAVAILABLE")
        resolution_path.write_bytes(canonical_json_bytes(invalid_resolution) + b"\n")
        before = self._state_root_identity(self.state_root)

        rejected = self._run(
            "decision",
            "resolution-preview",
            "--state-root",
            str(self.state_root),
            "--resolution",
            str(resolution_path),
            expected_exit=2,
        )

        self.assertEqual(rejected["status"], "REJECTED")
        self.assertIn("selected_option", rejected["error"])
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_rejects_malformed_resolution_preview_without_traceback(self) -> None:
        resolution, resolution_path = self._waiting_human_resolution()
        invalid_resolution = dict(resolution)
        invalid_resolution.pop("decision_id")
        resolution_path.write_bytes(canonical_json_bytes(invalid_resolution) + b"\n")
        before = self._state_root_identity(self.state_root)

        rejected = self._run(
            "decision",
            "resolution-preview",
            "--state-root",
            str(self.state_root),
            "--resolution",
            str(resolution_path),
            expected_exit=2,
        )

        self.assertEqual(rejected["status"], "REJECTED")
        self.assertIn("human_decision_resolution", rejected["error"])
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_initializes_and_reads_bounded_coding_gate(self) -> None:
        initialized = self._run(
            "coding",
            "gate-init",
            "--state-root",
            str(self.state_root),
            "--gate-id",
            "GATE-1",
            "--task-id",
            "TASK-1",
        )
        self.assertEqual(initialized["state"], "EMPTY")
        self.assertEqual(initialized["remaining_attempts"], 2)

        status = self._run(
            "coding",
            "gate-status",
            "--state-root",
            str(self.state_root),
            "--gate-id",
            "GATE-1",
        )
        self.assertEqual(status, initialized)

    def test_cli_validates_coding_execution_record_without_publishing_it(self) -> None:
        record_path = self.state_root / "record.json"
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_bytes(
            canonical_json_bytes(_valid_prelaunch_hold_coding_execution_record()) + b"\n"
        )

        result = self._run("coding", "record-validate", "--record", str(record_path))

        self.assertEqual(result["status"], "VALID")
        self.assertEqual(result["execution_id"], "EXECUTION-1")
        self.assertFalse((self.state_root / "coding-execution").exists())

    def test_cli_previews_validated_planner_handoff_without_state_writes(self) -> None:
        packet = generate_task_packet("PLANNER", valid_intake(), valid_policy_result())
        packet_path = self.state_root / "planner-packet.json"
        packet_path.write_bytes(canonical_json_bytes(packet) + b"\n")
        before = self._state_root_identity(self.state_root)

        result = self._run("plan", "handoff-preview", "--packet", str(packet_path))

        self.assertEqual(result["status"], "HANDOFF_PREVIEW")
        self.assertEqual(result["packet"], packet)
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_validated_planner_result_receipt_without_state_writes(self) -> None:
        packet = generate_task_packet("PLANNER", valid_intake(), valid_policy_result())
        agent_result = dict(
            valid_agent_result(),
            packet_id=packet["packet_id"],
            role="PLANNER",
            changed_files=[],
            created_files=[],
            recommended_next_state="SPEC_READY",
        )
        packet_path = self.state_root / "planner-packet.json"
        result_path = self.state_root / "planner-result.json"
        packet_path.write_bytes(canonical_json_bytes(packet) + b"\n")
        result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "plan",
            "result-receipt-preview",
            "--packet",
            str(packet_path),
            "--result",
            str(result_path),
        )

        self.assertEqual(result["status"], "RESULT_RECEIPT_PREVIEW")
        self.assertEqual(result["agent_result"], agent_result)
        self.assertEqual(
            result["agent_result_sha256"],
            hashlib.sha256(canonical_json_bytes(agent_result)).hexdigest(),
        )
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_validated_coder_handoff_without_state_writes(self) -> None:
        from acgps.task_packets import generate_task_packet

        packet = generate_task_packet("CODER", valid_intake(), valid_policy_result())
        packet_path = self.state_root / "coder-packet.json"
        packet_path.write_bytes(canonical_json_bytes(packet) + b"\n")
        before = self._state_root_identity(self.state_root)

        result = self._run("coding", "handoff-preview", "--packet", str(packet_path))

        self.assertEqual(result["status"], "HANDOFF_PREVIEW")
        self.assertEqual(result["packet"], packet)
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_validated_coder_result_receipt_without_state_writes(self) -> None:
        from acgps.task_packets import generate_task_packet

        packet = generate_task_packet("CODER", valid_intake(), valid_policy_result())
        agent_result = valid_agent_result()
        packet_path = self.state_root / "coder-packet.json"
        result_path = self.state_root / "coder-result.json"
        packet_path.write_bytes(canonical_json_bytes(packet) + b"\n")
        result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "coding",
            "result-receipt-preview",
            "--packet",
            str(packet_path),
            "--result",
            str(result_path),
        )

        self.assertEqual(result["status"], "RESULT_RECEIPT_PREVIEW")
        self.assertEqual(result["agent_result"], agent_result)
        self.assertEqual(
            result["agent_result_sha256"],
            hashlib.sha256(canonical_json_bytes(agent_result)).hexdigest(),
        )
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_validated_reviewer_handoff_without_state_writes(self) -> None:
        packet = generate_task_packet("REVIEWER", valid_intake(), valid_policy_result())
        packet_path = self.state_root / "reviewer-packet.json"
        packet_path.write_bytes(canonical_json_bytes(packet) + b"\n")
        before = self._state_root_identity(self.state_root)

        result = self._run("review", "handoff-preview", "--packet", str(packet_path))

        self.assertEqual(result["status"], "HANDOFF_PREVIEW")
        self.assertEqual(result["packet"], packet)
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_validated_reviewer_result_receipt_without_state_writes(self) -> None:
        packet = generate_task_packet("REVIEWER", valid_intake(), valid_policy_result())
        agent_result = dict(
            valid_agent_result(),
            packet_id=packet["packet_id"],
            role="REVIEWER",
            changed_files=[],
            recommended_next_state="INTEGRATING",
        )
        packet_path = self.state_root / "reviewer-packet.json"
        result_path = self.state_root / "reviewer-result.json"
        packet_path.write_bytes(canonical_json_bytes(packet) + b"\n")
        result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "review",
            "result-receipt-preview",
            "--packet",
            str(packet_path),
            "--result",
            str(result_path),
        )

        self.assertEqual(result["status"], "RESULT_RECEIPT_PREVIEW")
        self.assertEqual(result["agent_result"], agent_result)
        self.assertEqual(
            result["agent_result_sha256"],
            hashlib.sha256(canonical_json_bytes(agent_result)).hexdigest(),
        )
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_validated_verifier_handoff_without_state_writes(self) -> None:
        packet = generate_task_packet("VERIFIER", valid_intake(), valid_policy_result())
        packet_path = self.state_root / "verifier-packet.json"
        packet_path.write_bytes(canonical_json_bytes(packet) + b"\n")
        before = self._state_root_identity(self.state_root)

        result = self._run("verify", "handoff-preview", "--packet", str(packet_path))

        self.assertEqual(result["status"], "HANDOFF_PREVIEW")
        self.assertEqual(result["packet"], packet)
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_previews_validated_verifier_result_receipt_without_state_writes(self) -> None:
        packet = generate_task_packet("VERIFIER", valid_intake(), valid_policy_result())
        agent_result = dict(
            valid_agent_result(),
            packet_id=packet["packet_id"],
            role="VERIFIER",
            changed_files=[],
            recommended_next_state="VERIFIED",
        )
        packet_path = self.state_root / "verifier-packet.json"
        result_path = self.state_root / "verifier-result.json"
        packet_path.write_bytes(canonical_json_bytes(packet) + b"\n")
        result_path.write_bytes(canonical_json_bytes(agent_result) + b"\n")
        before = self._state_root_identity(self.state_root)

        result = self._run(
            "verify",
            "result-receipt-preview",
            "--packet",
            str(packet_path),
            "--result",
            str(result_path),
        )

        self.assertEqual(result["status"], "RESULT_RECEIPT_PREVIEW")
        self.assertEqual(result["agent_result"], agent_result)
        self.assertEqual(
            result["agent_result_sha256"],
            hashlib.sha256(canonical_json_bytes(agent_result)).hexdigest(),
        )
        self.assertEqual(result["controls"]["process_launch"], "NOT_STARTED")
        self.assertEqual(result["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(result["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), before)

    def test_cli_rejects_duplicate_keys_in_coding_execution_record(self) -> None:
        record_path = self.state_root / "duplicate-record.json"
        canonical = json.dumps(_valid_prelaunch_hold_coding_execution_record(), sort_keys=True)
        record_path.write_text(
            canonical.replace('{"agent_result":', '{"schema_version":2,"agent_result":', 1) + "\n",
            encoding="utf-8",
        )

        result = self._run("coding", "record-validate", "--record", str(record_path), expected_exit=2)

        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("duplicate", result["error"].casefold())

    def test_cli_lists_pending_human_decisions_before_and_after_resume(self) -> None:
        self._run(
            "task",
            "intake",
            *self._engine_arguments(),
            "--intake",
            str(self.FIXTURE_ROOT / "task-intake.yaml"),
        )
        evidence = self.FIXTURE_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
        planner_packet = generate_task_packet("PLANNER", valid_intake(), valid_policy_result())
        planner_packet_path = self.state_root / "planner-packet.json"
        planner_packet_path.write_bytes(canonical_json_bytes(planner_packet) + b"\n")
        planner_result_path = self.state_root / "planner-result.json"
        planner_result_path.write_bytes(
            canonical_json_bytes(
                dict(
                    valid_agent_result(),
                    packet_id=planner_packet["packet_id"],
                    role="PLANNER",
                    changed_files=[],
                    created_files=[],
                    recommended_next_state="SPEC_READY",
                )
            )
            + b"\n"
        )
        for index, target in enumerate(("READY_FOR_CLASSIFICATION", "CLASSIFIED"), start=1):
            self._run(
                "task",
                "advance",
                *self._engine_arguments(),
                "--task-id",
                "ftic-governance-1",
                "--to-state",
                target,
                "--actor",
                "CONTROLLER",
                "--created-at-utc",
                f"2026-08-23T04:0{index}:00Z",
                "--evidence",
                str(evidence),
            )

        waiting = self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "SPEC_READY",
            "--actor",
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-23T04:03:00Z",
            "--evidence",
            str(evidence),
            "--human-trigger",
            "H1_PRODUCT_INTENT",
        )
        decision_id = str(waiting["pending_decision_id"])

        state_before_pending_query = self._state_root_identity(self.state_root)
        pending = self._run("decision", "pending", "--state-root", str(self.state_root))
        self.assertEqual(pending["status"], "PENDING")
        self.assertEqual([row["decision_id"] for row in pending["decisions"]], [decision_id])
        self.assertEqual(self._state_root_identity(self.state_root), state_before_pending_query)

        resolution = {
            "schema_version": 1,
            "decision_id": decision_id,
            "project_id": "FTIC",
            "task_id": "ftic-governance-1",
            "selected_option": "RESUME",
            "resolved_by": "human_owner",
            "resolved_at_utc": "2026-08-23T04:04:00Z",
            "rationale": "Continue the approved supervised core workflow.",
            "evidence_paths": [],
            "resume_state": "SPEC_READY",
            "status": "RESOLVED",
        }
        resolution_path = self.state_root / "decision-resolution.json"
        resolution_path.write_text(
            json.dumps(resolution, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        from acgps.human_decisions import DecisionQueue

        DecisionQueue(self.state_root / "decisions").resolve(resolution)
        still_pending = self._run("decision", "pending", "--state-root", str(self.state_root))
        self.assertEqual(still_pending["status"], "PENDING")
        self.assertEqual([row["decision_id"] for row in still_pending["decisions"]], [decision_id])
        resumed = self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "SPEC_READY",
            "--actor",
            "PLANNER",
            "--created-at-utc",
            "2026-08-23T04:04:00Z",
            "--evidence",
            str(planner_packet_path),
            "--evidence",
            str(planner_result_path),
            "--decision-resolution",
            str(resolution_path),
        )
        self.assertEqual(resumed["current_state"], "SPEC_READY")

        cleared = self._run("decision", "pending", "--state-root", str(self.state_root))
        self.assertEqual(cleared, {"decisions": [], "status": "CLEAR"})

    def test_cli_rejects_pending_query_without_authoritative_control_store(self) -> None:
        result = self._run(
            "decision",
            "pending",
            "--state-root",
            str(self.state_root),
            expected_exit=2,
        )

        self.assertEqual(result["status"], "REJECTED")
        self.assertRegex(result["error"], r"control[-_]store")

    def test_cli_rejects_invalid_pending_human_decision_record(self) -> None:
        from acgps.workflow_store import WorkflowStore

        WorkflowStore(self.state_root)
        pending_root = self.state_root / "decisions" / "pending"
        pending_root.mkdir(parents=True)
        (pending_root / "decision-invalid.json").write_text(
            json.dumps({"decision_id": "decision-invalid"}) + "\n",
            encoding="utf-8",
        )

        result = self._run(
            "decision",
            "pending",
            "--state-root",
            str(self.state_root),
            expected_exit=2,
        )

        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("human_decision_request", result["error"])

    def test_cli_rejects_pending_directory_that_escapes_state_root(self) -> None:
        from acgps.workflow_store import WorkflowStore

        WorkflowStore(self.state_root)
        outside_pending = Path(self.temporary_directory.name) / "outside-pending"
        outside_pending.mkdir()
        (outside_pending / "decision-1.json").write_text(
            json.dumps(valid_decision_request(), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        decision_root = self.state_root / "decisions"
        decision_root.mkdir()
        os.symlink(outside_pending, decision_root / "pending", target_is_directory=True)

        result = self._run(
            "decision",
            "pending",
            "--state-root",
            str(self.state_root),
            expected_exit=2,
        )

        self.assertEqual(result["status"], "REJECTED")
        self.assertRegex(result["error"], r"symlink|escape")

    def test_cli_rejects_corrupt_resolution_instead_of_reporting_clear(self) -> None:
        from acgps.workflow_store import WorkflowStore

        WorkflowStore(self.state_root)
        decision_root = self.state_root / "decisions"
        pending_root = decision_root / "pending"
        resolved_root = decision_root / "resolved"
        pending_root.mkdir(parents=True)
        resolved_root.mkdir()
        (pending_root / "decision-1.json").write_text(
            json.dumps(valid_decision_request(), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        (resolved_root / "decision-1.json").write_text("", encoding="utf-8")

        result = self._run(
            "decision",
            "pending",
            "--state-root",
            str(self.state_root),
            expected_exit=2,
        )

        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("unreadable", result["error"])

    def test_cli_rejects_non_pending_request_in_pending_directory(self) -> None:
        from acgps.workflow_store import WorkflowStore

        WorkflowStore(self.state_root)
        pending_root = self.state_root / "decisions" / "pending"
        pending_root.mkdir(parents=True)
        (pending_root / "decision-1.json").write_text(
            json.dumps(dict(valid_decision_request(), status="CANCELLED"), sort_keys=True) + "\n",
            encoding="utf-8",
        )

        result = self._run(
            "decision",
            "pending",
            "--state-root",
            str(self.state_root),
            expected_exit=2,
        )

        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("must be PENDING", result["error"])

    def test_cli_runs_bounded_ftic_governance_slice_without_managed_writes(self) -> None:
        validation = self._run(
            "project",
            "validate",
            "--policy-root",
            str(self.ROOT),
            "--project-root",
            str(self.FIXTURE_ROOT),
            "--profile-id",
            "ftic-v1",
        )
        self.assertEqual(validation["status"], "VALID")
        self.assertEqual(
            validation["required_files"]["goal"],
            str((self.FIXTURE_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md").resolve()),
        )

        state = self._run(
            "task",
            "intake",
            *self._engine_arguments(),
            "--intake",
            str(self.FIXTURE_ROOT / "task-intake.yaml"),
        )
        self.assertEqual(state["current_state"], "DRAFT")

        classification_evidence = self.FIXTURE_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md"
        for index, (target, actor) in enumerate(
            (
                ("READY_FOR_CLASSIFICATION", "PLANNER"),
                ("CLASSIFIED", "CONTROLLER"),
            ),
            start=1,
        ):
            state = self._run(
                "task",
                "advance",
                *self._engine_arguments(),
                "--task-id",
                "ftic-governance-1",
                "--to-state",
                target,
                "--actor",
                actor,
                "--created-at-utc",
                f"2026-08-23T00:{index:02d}:00Z",
                "--evidence",
                str(classification_evidence),
            )
            self.assertEqual(state["current_state"], target)

        packet_path = self.state_root / "packets" / "planner.json"
        packet = self._run(
            "packet",
            "generate",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--role",
            "PLANNER",
            "--created-at-utc",
            "2026-08-23T00:00:30Z",
            "--output",
            str(packet_path),
        )
        validate_contract("agent_task_contract", packet, mode="runtime")
        self.assertEqual(json.loads(packet_path.read_text(encoding="utf-8")), packet)
        planner_result_paths = {}
        for target in ("SPEC_READY", "PLAN_READY"):
            result_path = (
                self.state_root / "packets" / f"planner-{target.casefold()}-result.json"
            )
            result_path.write_bytes(
                canonical_json_bytes(
                    dict(
                        valid_agent_result(),
                        packet_id=packet["packet_id"],
                        role="PLANNER",
                        summary=f"Completed the bounded Planner work for {target}.",
                        changed_files=[],
                        created_files=[],
                        recommended_next_state=target,
                    )
                )
                + b"\n"
            )
            planner_result_paths[target] = result_path

        coder_packet_path = self.state_root / "packets" / "coder.json"
        coder_packet = self._run(
            "packet",
            "generate",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--role",
            "CODER",
            "--created-at-utc",
            "2026-08-23T00:00:31Z",
            "--output",
            str(coder_packet_path),
        )
        validate_contract("agent_task_contract", coder_packet, mode="runtime")
        self.assertEqual(coder_packet["role"], "CODER")
        self.assertEqual(coder_packet["packet_id"], valid_agent_result()["packet_id"])
        coder_result_path = self.state_root / "packets" / "coder-result.json"
        coder_result_path.write_bytes(canonical_json_bytes(valid_agent_result()) + b"\n")
        reviewer_packet_path = self.state_root / "packets" / "reviewer.json"
        reviewer_packet = self._run(
            "packet",
            "generate",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--role",
            "REVIEWER",
            "--created-at-utc",
            "2026-08-23T00:00:32Z",
            "--output",
            str(reviewer_packet_path),
        )
        reviewer_result_path = self.state_root / "packets" / "reviewer-result.json"
        reviewer_result_path.write_bytes(
            canonical_json_bytes(
                dict(
                    valid_agent_result(),
                    packet_id=reviewer_packet["packet_id"],
                    role="REVIEWER",
                    summary="Completed the bounded independent review.",
                    changed_files=[],
                    created_files=[],
                    recommended_next_state="INTEGRATING",
                )
            )
            + b"\n"
        )
        verifier_packet_path = self.state_root / "packets" / "verifier.json"
        verifier_packet = self._run(
            "packet",
            "generate",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--role",
            "VERIFIER",
            "--created-at-utc",
            "2026-08-23T00:00:33Z",
            "--output",
            str(verifier_packet_path),
        )
        verifier_result_path = self.state_root / "packets" / "verifier-result.json"
        verifier_result_path.write_bytes(
            canonical_json_bytes(
                dict(
                    valid_agent_result(),
                    packet_id=verifier_packet["packet_id"],
                    role="VERIFIER",
                    summary="Completed the bounded independent verification.",
                    changed_files=[],
                    created_files=[],
                    recommended_next_state="VERIFIED",
                )
            )
            + b"\n"
        )

        rc_dir = self.state_root / "rc"
        source = rc_dir / "evidence" / "source-artifact.txt"
        build_artifact = rc_dir / "evidence" / "acgps-mvp-v0.1-source.zip"
        review = rc_dir / "evidence" / "review-finding.json"
        verification = rc_dir / "evidence" / "verification-record.json"
        source.parent.mkdir(parents=True)
        shutil.copyfile(self.FIXTURE_ROOT / "evidence" / source.name, source)
        build_artifact.write_bytes(b"deterministic source archive\n")
        shutil.copyfile(self.FIXTURE_ROOT / "evidence" / review.name, review)
        shutil.copyfile(self.FIXTURE_ROOT / "evidence" / verification.name, verification)
        rollback = rc_dir / "rollback.md"
        rollback.write_text("Delete the local runtime state directory.\n", encoding="utf-8")

        transitions = [
            ("SPEC_READY", "PLANNER", [packet_path, planner_result_paths["SPEC_READY"]]),
            ("PLAN_READY", "PLANNER", [packet_path, planner_result_paths["PLAN_READY"]]),
            ("IMPLEMENTING", "CODER", [coder_packet_path]),
            ("TASK_REVIEW", "CODER", [coder_packet_path, coder_result_path]),
            (
                "INTEGRATING",
                "REVIEWER",
                [reviewer_packet_path, reviewer_result_path],
            ),
            (
                "VERIFIED",
                "VERIFIER",
                [verifier_packet_path, verifier_result_path, verification],
            ),
        ]
        for index, (target, actor, evidence_paths) in enumerate(transitions, start=3):
            if target in {"TASK_REVIEW", "INTEGRATING", "VERIFIED"}:
                before = self._run(
                    "task",
                    "status",
                    *self._engine_arguments(),
                    "--task-id",
                    "ftic-governance-1",
                    "--include-audit",
                )
                rejection = self._run(
                    "task",
                    "advance",
                    *self._engine_arguments(),
                    "--task-id",
                    "ftic-governance-1",
                    "--to-state",
                    target,
                    "--actor",
                    actor,
                    "--created-at-utc",
                    f"2026-08-23T00:{index:02d}:00Z",
                    "--evidence",
                    str(
                        source
                        if target == "TASK_REVIEW"
                        else review
                        if target == "INTEGRATING"
                        else verification
                    ),
                    expected_exit=2,
                )
                self.assertEqual(rejection["status"], "REJECTED")
                after = self._run(
                    "task",
                    "status",
                    *self._engine_arguments(),
                    "--task-id",
                    "ftic-governance-1",
                    "--include-audit",
                )
                self.assertEqual(after, before)
            arguments = [
                "task",
                "advance",
                *self._engine_arguments(),
                "--task-id",
                "ftic-governance-1",
                "--to-state",
                target,
                "--actor",
                actor,
                "--created-at-utc",
                f"2026-08-23T00:{index:02d}:00Z",
            ]
            for evidence_path in evidence_paths:
                arguments.extend(("--evidence", str(evidence_path)))
            state = self._run(*arguments)
            self.assertEqual(state["current_state"], target)

        verified_before = self._state_root_identity(self.state_root)
        next_action = self._run(
            "task",
            "next-action-preview",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )
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
                    "minimum_count": 3,
                    "maximum_count": 3,
                    "ordered_kinds": [
                        "VERIFIER_TASK_PACKET",
                        "VERIFIER_RESULT",
                        "VERIFICATION_RECORD",
                    ],
                    "repeatable_tail": True,
                },
            },
        )

        verified_closure_preview_arguments = [
            "task",
            "gate-preview",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "CLOSED",
            "--actor",
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-23T00:09:00Z",
        ]
        for evidence_path in (
            verifier_packet_path,
            verifier_result_path,
            verification,
        ):
            verified_closure_preview_arguments.extend(("--evidence", str(evidence_path)))
        verified_closure_preview = self._run(*verified_closure_preview_arguments)
        self.assertEqual(
            verified_closure_preview["status"],
            "DIRECT_TRANSITION_GATE_PREVIEW",
        )
        self.assertEqual(verified_closure_preview["current_state"], "VERIFIED")
        self.assertEqual(verified_closure_preview["target_state"], "CLOSED")
        self.assertEqual(verified_closure_preview["required_actor"], "CONTROLLER")
        self.assertEqual(verified_closure_preview["evidence_status"], "VALIDATED")
        self.assertEqual(
            verified_closure_preview["authorization_status"],
            "NOT_GRANTED",
        )
        self.assertEqual(
            verified_closure_preview["controls"]["state_write"],
            "NOT_PERFORMED",
        )
        self.assertEqual(
            verified_closure_preview["controls"]["workflow_transition"],
            "NOT_PERFORMED",
        )
        self.assertEqual(self._state_root_identity(self.state_root), verified_before)

        manifest_result = self._run(
            "rc",
            "prepare",
            "--output-dir",
            str(rc_dir),
            "--project-id",
            "FTIC",
            "--rc-id",
            "ftic-governance-rc-1",
            "--version",
            "0.1-dogfood",
            "--source",
            str(source),
            "--build-artifact",
            str(build_artifact),
            "--verification",
            str(verification),
            "--review",
            str(review),
            "--rollback",
            str(rollback),
            "--created-at-utc",
            "2026-08-23T00:09:00Z",
        )
        manifest_path = Path(str(manifest_result["manifest_path"]))
        self.assertTrue(manifest_path.is_file())

        before_preview = self._run(
            "task",
            "status",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--include-audit",
        )
        state_root_before_preview = self._state_root_identity(self.state_root)
        preview = self._run(
            "rc",
            "task-gate-preview",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--manifest",
            str(manifest_path),
            "--actor",
            "VERIFIER",
            "--created-at-utc",
            "2026-08-23T00:10:00Z",
        )
        self.assertEqual(preview["status"], "RC_READY_GATE_PREVIEW")
        self.assertEqual(preview["target_state"], "RC_READY")
        self.assertEqual(preview["evidence_status"], "VALIDATED")
        self.assertEqual(preview["authorization_status"], "NOT_GRANTED")
        self.assertEqual(
            preview["manifest_sha256"],
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(preview["controls"]["state_write"], "NOT_PERFORMED")
        self.assertEqual(preview["controls"]["workflow_transition"], "NOT_PERFORMED")
        self.assertEqual(self._state_root_identity(self.state_root), state_root_before_preview)
        self.assertEqual(
            self._run(
                "task",
                "status",
                *self._engine_arguments(),
                "--task-id",
                "ftic-governance-1",
                "--include-audit",
            ),
            before_preview,
        )
        state_root_before_rejection = self._state_root_identity(self.state_root)

        rejection = self._run(
            "rc",
            "task-gate-preview",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--manifest",
            str(manifest_path),
            "--actor",
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-23T00:10:00Z",
            expected_exit=2,
        )
        self.assertEqual(rejection["status"], "REJECTED")
        self.assertIn("RC_READY requires actor VERIFIER", str(rejection["error"]))
        self.assertEqual(self._state_root_identity(self.state_root), state_root_before_rejection)

        state = self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "RC_READY",
            "--actor",
            "VERIFIER",
            "--created-at-utc",
            "2026-08-23T00:10:00Z",
            "--evidence",
            str(manifest_path),
        )
        self.assertEqual(state["current_state"], "RC_READY")

        state_root_before_commit_verification = self._state_root_identity(self.state_root)
        commit_verification = self._run(
            "rc",
            "task-transition-commit-verify",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )
        self.assertEqual(
            commit_verification["status"],
            "RC_READY_TRANSITION_COMMIT_VERIFIED",
        )
        self.assertEqual(commit_verification["current_state"], "RC_READY")
        self.assertEqual(commit_verification["from_state"], "VERIFIED")
        self.assertEqual(commit_verification["to_state"], "RC_READY")
        self.assertEqual(commit_verification["actor"], "VERIFIER")
        self.assertEqual(
            commit_verification["manifest_sha256"],
            hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        )
        self.assertEqual(
            commit_verification["controls"]["state_write"],
            "NOT_PERFORMED",
        )
        self.assertEqual(
            commit_verification["controls"]["workflow_transition"],
            "NOT_PERFORMED",
        )
        self.assertEqual(
            self._state_root_identity(self.state_root),
            state_root_before_commit_verification,
        )

        closed_state = self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "CLOSED",
            "--actor",
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-23T00:11:00Z",
            "--evidence",
            str(manifest_path),
        )
        self.assertEqual(closed_state["current_state"], "CLOSED")
        state_root_before_closed_verification = self._state_root_identity(self.state_root)

        closed_verification = self._run(
            "task",
            "closed-transition-commit-verify",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )

        self.assertEqual(
            closed_verification["status"],
            "CLOSED_TRANSITION_COMMIT_VERIFIED",
        )
        self.assertEqual(closed_verification["from_state"], "RC_READY")
        self.assertEqual(closed_verification["to_state"], "CLOSED")
        self.assertEqual(closed_verification["actor"], "CONTROLLER")
        self.assertEqual(
            closed_verification["evidence_kind"],
            "RELEASE_CANDIDATE_MANIFEST",
        )
        self.assertEqual(closed_verification["evidence_count"], 1)
        self.assertEqual(
            closed_verification["controls"]["state_write"],
            "NOT_PERFORMED",
        )
        self.assertEqual(
            closed_verification["controls"]["workflow_transition"],
            "NOT_PERFORMED",
        )
        self.assertEqual(
            self._state_root_identity(self.state_root),
            state_root_before_closed_verification,
        )

        unified_verification = self._run(
            "task",
            "transition-commit-verify",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )

        self.assertEqual(unified_verification, closed_verification)
        self.assertEqual(
            self._state_root_identity(self.state_root),
            state_root_before_closed_verification,
        )

        status = self._run(
            "task",
            "status",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--include-audit",
        )
        self.assertEqual(status["state"]["current_state"], "CLOSED")
        self.assertEqual([event["sequence"] for event in status["audit"]], list(range(1, 12)))

    def test_cli_rejection_is_nonzero_and_does_not_advance_state(self) -> None:
        self._run(
            "task",
            "intake",
            *self._engine_arguments(),
            "--intake",
            str(self.FIXTURE_ROOT / "task-intake.yaml"),
        )
        before = self._run(
            "task",
            "status",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )
        failure = self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "CLASSIFIED",
            "--actor",
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-23T00:01:00Z",
            "--evidence",
            str(self.FIXTURE_ROOT / "evidence" / "source-artifact.txt"),
            expected_exit=2,
        )
        self.assertEqual(failure["status"], "REJECTED")
        after = self._run(
            "task",
            "status",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
        )
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
