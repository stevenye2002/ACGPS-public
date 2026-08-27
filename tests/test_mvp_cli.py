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
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-23T04:04:00Z",
            "--evidence",
            str(evidence),
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
            ("READY_FOR_CLASSIFICATION", "PLANNER", [source]),
            ("CLASSIFIED", "CONTROLLER", [source]),
            ("SPEC_READY", "PLANNER", [source]),
            ("PLAN_READY", "PLANNER", [source]),
            ("IMPLEMENTING", "CODER", [source]),
            ("TASK_REVIEW", "CODER", [coder_packet_path, coder_result_path]),
            (
                "INTEGRATING",
                "REVIEWER",
                [reviewer_packet_path, reviewer_result_path, review],
            ),
            (
                "VERIFIED",
                "VERIFIER",
                [verifier_packet_path, verifier_result_path, verification],
            ),
        ]
        for index, (target, actor, evidence_paths) in enumerate(transitions, start=1):
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

        state = self._run(
            "task",
            "advance",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--to-state",
            "RC_READY",
            "--actor",
            "CONTROLLER",
            "--created-at-utc",
            "2026-08-23T00:10:00Z",
            "--evidence",
            str(manifest_path),
        )
        self.assertEqual(state["current_state"], "RC_READY")

        status = self._run(
            "task",
            "status",
            *self._engine_arguments(),
            "--task-id",
            "ftic-governance-1",
            "--include-audit",
        )
        self.assertEqual(status["state"]["current_state"], "RC_READY")
        self.assertEqual([event["sequence"] for event in status["audit"]], list(range(1, 11)))

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
