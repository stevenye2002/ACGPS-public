from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
import unittest

from acgps.coding_execution import (
    ControllerBoundaryObservation,
    ControllerOperationObservation,
    PreflightContext,
    build_completed_attempt_record,
    build_prelaunch_hold_record,
    coding_execution_binding_sha256,
    evaluate_prelaunch,
    observe_agent_result,
    parse_operation_events,
)
from acgps.contracts import validate_contract
from acgps.workflow_contracts import canonical_json_bytes
from tests.test_contracts import _valid_candidate_ready_coding_execution_record


def _preflight_context(
    *,
    platform: str = "WINDOWS_11_X64_NTFS_PYTHON_3_13_ELEVATED_PRIVATE_DESKTOP",
) -> PreflightContext:
    record = _valid_candidate_ready_coding_execution_record()
    packet_payload = {
        "schema_version": 1,
        "packet_id": "PACKET-1",
        "role": "CODER",
        "project_id": "ACGPS",
        "task_id": "TASK-1",
        "objective": "Implement the bounded executor",
        "binding_constraints": [],
        "non_goals": ["remote writes"],
        "relevant_paths": ["acgps/example.py"],
        "interfaces_consumed": ["coding_execution_record"],
        "interfaces_produced": ["bounded executor evidence"],
        "acceptance_criteria": ["fail closed before launch"],
        "required_skills": [],
        "required_evidence": ["python scripts/check.py full"],
        "prohibited_actions": ["production release"],
        "return_schema": "templates/AGENT_RESULT.yaml",
    }
    packet_bytes = canonical_json_bytes(packet_payload) + b"\n"
    packet = deepcopy(record["packet"])
    baseline = deepcopy(record["baseline"])
    clone_before = deepcopy(record["clone_before"])
    executor = deepcopy(record["executor"])
    capabilities = deepcopy(record["capabilities"])
    assert isinstance(packet, dict)
    assert isinstance(baseline, dict)
    assert isinstance(clone_before, dict)
    assert isinstance(executor, dict)
    assert isinstance(capabilities, dict)
    executor["platform"] = platform
    packet["sha256"] = hashlib.sha256(packet_bytes).hexdigest()
    packet["size_bytes"] = len(packet_bytes)
    baseline_inventory = b"baseline-inventory"
    baseline_sha = hashlib.sha256(baseline_inventory).hexdigest()
    baseline["before_state_sha256"] = baseline_sha
    baseline["after_state_sha256"] = baseline_sha
    baseline["unchanged"] = True
    capabilities["operation_rows"] = []
    check_allowlist = (("python", "-m", "unittest"),)
    git_read_allowlist = (("git", "status", "--short"),)
    capabilities["check_allowlist_sha256"] = hashlib.sha256(
        canonical_json_bytes([list(argv) for argv in check_allowlist])
    ).hexdigest()
    capabilities["git_read_allowlist_sha256"] = hashlib.sha256(
        canonical_json_bytes([list(argv) for argv in git_read_allowlist])
    ).hexdigest()
    effective_config_bytes = b'{"apps":false,"hooks":false,"multi_agent":false}\n'
    network_policy_bytes = b'{"agent_tool_network":"deny","model_transport":"allow"}\n'
    capabilities["effective_config_sha256"] = hashlib.sha256(effective_config_bytes).hexdigest()
    capabilities["network_policy_sha256"] = hashlib.sha256(network_policy_bytes).hexdigest()
    capabilities["observations_complete"] = True
    packet_payload["binding_constraints"] = [
        "ACGPS-CODING-BINDING-SHA256:"
        + coding_execution_binding_sha256(
            baseline=baseline,
            expected_executor=executor,
            authorized_write_paths=tuple(capabilities["authorized_write_paths"]),
            check_argv_allowlist=check_allowlist,
            git_read_argv_allowlist=git_read_allowlist,
            effective_config_sha256=capabilities["effective_config_sha256"],
            network_policy_sha256=capabilities["network_policy_sha256"],
            wall_clock_limit_seconds=1800,
        )
    ]
    packet_bytes = canonical_json_bytes(packet_payload) + b"\n"
    packet["sha256"] = hashlib.sha256(packet_bytes).hexdigest()
    packet["size_bytes"] = len(packet_bytes)
    baseline_root = Path(r"C:\work\baseline")
    state_root = Path(r"C:\controller\state")
    evidence_root = Path(r"C:\controller\evidence")
    clone_root = Path(r"C:\work\clone")
    environment = {"PATH": r"C:\Windows\System32"}
    boundary_observation = ControllerBoundaryObservation(
        effective_config_bytes=effective_config_bytes,
        network_policy_bytes=network_policy_bytes,
        authorized_write_paths=tuple(capabilities["authorized_write_paths"]),
        writable_roots=(clone_root,),
        immutable_roots=(baseline_root, state_root, evidence_root),
        environment=tuple(sorted(environment.items())),
        check_argv_allowlist=check_allowlist,
        git_read_argv_allowlist=git_read_allowlist,
        event_capture_source="CONTROLLER_EVENT_RECONCILER_V1",
        filesystem_reconciliation_source="CONTROLLER_FILESYSTEM_SNAPSHOT_V1",
        git_reconciliation_source="CONTROLLER_GIT_SNAPSHOT_V1",
        network_enforcement_source="WINDOWS_NETWORK_POLICY_OBSERVER_V1",
        process_capture_source="WINDOWS_JOB_OBJECT_V1",
    )
    return PreflightContext(
        project_id="ACGPS",
        packet=packet,
        packet_bytes=packet_bytes,
        baseline=baseline,
        baseline_before_state=baseline_inventory,
        baseline_after_state=baseline_inventory,
        slot={
            "gate_id": "GATE-1",
            "task_id": "TASK-1",
            "state": "EMPTY",
            "remaining_attempts": 2,
            "active_candidate_id": None,
            "historical_candidate_ids": [],
            "remediation_authorization_id": None,
            "reserved_attempt": None,
        },
        clone_before=clone_before,
        executor=executor,
        expected_executor=deepcopy(executor),
        capabilities=capabilities,
        baseline_root=baseline_root,
        state_root=state_root,
        evidence_root=evidence_root,
        clone_root=clone_root,
        evidence_destinations=(Path(r"C:\controller\evidence\execution.json"),),
        environment=environment,
        check_argv_allowlist=check_allowlist,
        git_read_argv_allowlist=git_read_allowlist,
        controller_boundary_observation=boundary_observation,
        wall_clock_limit_seconds=1800,
        model_request_started=False,
        process_start_requested=False,
    )


class CodingExecutionTests(unittest.TestCase):
    def test_executor_claims_cannot_create_passing_operation_evidence(self) -> None:
        payload = (
            json.dumps(
                {
                    "event_id": "EVENT-CLAIM-1",
                    "type": "approved_file_patch",
                    "paths": ["acgps/example.py"],
                    "evidence_sha256": "a" * 64,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")

        parsed = parse_operation_events(payload)

        self.assertEqual(parsed.operation_rows, [])
        self.assertEqual(parsed.unknown_count, 1)

    def test_prelaunch_rejects_asserted_boundary_without_controller_observation(self) -> None:
        context = _preflight_context()
        context.controller_boundary_observation = None

        evaluation = evaluate_prelaunch(context)

        self.assertEqual(evaluation.state, "HOLD")
        self.assertIn("P4-CAPABILITY-INCOMPLETE", evaluation.blocker_ids)

    def test_prelaunch_binds_authorized_paths_to_canonical_packet(self) -> None:
        context = _preflight_context()
        packet_payload = json.loads(context.packet_bytes.decode("utf-8"))
        packet_payload["relevant_paths"] = ["acgps/not-authorized.py"]
        context.packet_bytes = canonical_json_bytes(packet_payload) + b"\n"
        context.packet["sha256"] = hashlib.sha256(context.packet_bytes).hexdigest()
        context.packet["size_bytes"] = len(context.packet_bytes)

        evaluation = evaluate_prelaunch(context)

        self.assertEqual(evaluation.state, "HOLD")
        self.assertIn("P0-IDENTITY-MISMATCH", evaluation.blocker_ids)

    def test_agent_result_observation_validates_contract_and_exact_claims(self) -> None:
        payload_record = {
            "schema_version": 1,
            "packet_id": "PACKET-1",
            "role": "CODER",
            "status": "DONE",
            "summary": "Implemented the bounded change",
            "changed_files": ["acgps/example.py"],
            "created_files": [],
            "commands_run": ["python -m unittest"],
            "evidence_paths": ["evidence/test.txt"],
            "assumptions": [],
            "concerns": [],
            "blocker": None,
            "recommended_next_state": "TASK_REVIEW",
        }
        payload = (json.dumps(payload_record, sort_keys=True) + "\n").encode("utf-8")

        matching = observe_agent_result(
            payload,
            logical_path="artifacts/agent-result.json",
            format_suffix=".json",
            changed_paths=("acgps/example.py",),
            commands_run=("python -m unittest",),
        )
        mismatching = observe_agent_result(
            payload,
            logical_path="artifacts/agent-result.json",
            format_suffix=".json",
            changed_paths=("acgps/other.py",),
            commands_run=("python -m unittest",),
        )

        self.assertTrue(matching["contract_valid"])
        self.assertTrue(matching["claims_match"])
        self.assertEqual(matching["claimed_status"], "DONE")
        self.assertFalse(mismatching["claims_match"])

    def test_prelaunch_hold_record_is_derived_without_consuming_an_attempt(self) -> None:
        context = _preflight_context()
        context.capabilities["network_policy_sha256"] = None
        context.capabilities["observations_complete"] = False
        evaluation = evaluate_prelaunch(context)

        record = build_prelaunch_hold_record(
            context,
            evaluation,
            execution_id="EXECUTION-PREFLIGHT-1",
            checked_at_utc="2026-08-24T00:00:00.000Z",
        )

        validate_contract("coding_execution_record", record)
        self.assertEqual(record["outcome"], "PRELAUNCH_HOLD")
        self.assertEqual(record["attempt"]["kind"], "PRELAUNCH")
        self.assertEqual(record["attempt"]["remaining_before"], 2)
        self.assertEqual(record["attempt"]["remaining_after"], 2)
        self.assertEqual(record["attempt"]["process_start_request_count"], 0)
        self.assertIsNone(record["candidate"]["candidate_id"])

    def test_preflight_derives_exact_seven_pass_rows_from_observed_evidence(self) -> None:
        evaluation = evaluate_prelaunch(_preflight_context())

        self.assertEqual(evaluation.state, "PASS")
        self.assertEqual([row["gate_id"] for row in evaluation.gate_rows], ["P0", "P1", "P2", "P3", "P4", "P5", "P6"])
        self.assertTrue(all(row["status"] == "PASS" for row in evaluation.gate_rows))
        self.assertEqual(evaluation.blocker_ids, [])

    def test_preflight_accepts_exact_windows_server_2022_platform_profile(self) -> None:
        platform = "WINDOWS_SERVER_2022_X64_NTFS_PYTHON_3_13_ELEVATED_PRIVATE_DESKTOP"
        context = _preflight_context(platform=platform)

        evaluation = evaluate_prelaunch(context)

        self.assertEqual(evaluation.state, "PASS")
        self.assertTrue(all(row["status"] == "PASS" for row in evaluation.gate_rows))

    def test_preflight_holds_an_unqualified_platform_profile_at_p3(self) -> None:
        context = _preflight_context(platform="WINDOWS_SERVER_2025_UNQUALIFIED")

        evaluation = evaluate_prelaunch(context)

        self.assertEqual(evaluation.state, "HOLD")
        self.assertEqual(evaluation.blocker_ids, ["P3-EXECUTOR-INVALID"])

    def test_preflight_holds_when_network_evidence_secret_or_start_boundary_is_invalid(self) -> None:
        cases = []

        missing_network = _preflight_context()
        missing_network.capabilities["network_policy_sha256"] = None
        missing_network.capabilities["observations_complete"] = False
        cases.append(("network", missing_network, "P4-CAPABILITY-INCOMPLETE"))

        unenforced_network = _preflight_context()
        assert unenforced_network.controller_boundary_observation is not None
        unenforced_network.controller_boundary_observation = replace(
            unenforced_network.controller_boundary_observation,
            network_enforcement_source="UNVERIFIED",
        )
        cases.append(("network-enforcement", unenforced_network, "P4-CAPABILITY-INCOMPLETE"))

        missing_process_capture = _preflight_context()
        assert missing_process_capture.controller_boundary_observation is not None
        missing_process_capture.controller_boundary_observation = replace(
            missing_process_capture.controller_boundary_observation,
            process_capture_source="UNVERIFIED",
        )
        cases.append(("process-capture", missing_process_capture, "P4-CAPABILITY-INCOMPLETE"))

        allowlist_mismatch = _preflight_context()
        allowlist_mismatch.capabilities["check_allowlist_sha256"] = "f" * 64
        cases.append(("allowlist-hash", allowlist_mismatch, "P4-CAPABILITY-INCOMPLETE"))

        secret_environment = _preflight_context()
        secret_environment.environment["API_TOKEN"] = "secret-value"
        cases.append(("secret", secret_environment, "P5-SECRET-OR-ROOT-BOUNDARY"))

        already_started = _preflight_context()
        already_started.process_start_requested = True
        cases.append(("started", already_started, "P6-BEFORE-STATE-NOT-FROZEN"))

        executor_mismatch = _preflight_context()
        executor_mismatch.executor["sha256"] = "d" * 64
        cases.append(("executor", executor_mismatch, "P3-EXECUTOR-INVALID"))

        invalid_packet = _preflight_context()
        invalid_packet.packet_bytes = b"{}\n"
        invalid_packet.packet["sha256"] = hashlib.sha256(invalid_packet.packet_bytes).hexdigest()
        invalid_packet.packet["size_bytes"] = len(invalid_packet.packet_bytes)
        cases.append(("packet-schema", invalid_packet, "P0-IDENTITY-MISMATCH"))

        for name, context, blocker in cases:
            with self.subTest(name=name):
                evaluation = evaluate_prelaunch(context)
                self.assertEqual(evaluation.state, "HOLD")
                self.assertIn(blocker, evaluation.blocker_ids)

    def test_operation_event_parser_classifies_five_classes_and_counts_unknowns(self) -> None:
        evidence_bytes = b"controller-observed-operation"
        sha = hashlib.sha256(evidence_bytes).hexdigest()
        events = [
            {"event_id": "EVENT-1", "type": "workspace_read", "paths": ["acgps/a.py"], "evidence_sha256": sha},
            {"event_id": "EVENT-2", "type": "targeted_text_search", "paths": ["acgps/b.py"], "evidence_sha256": sha},
            {"event_id": "EVENT-3", "type": "approved_file_patch", "paths": ["acgps/c.py"], "evidence_sha256": sha},
            {
                "event_id": "EVENT-4",
                "type": "local_check_process",
                "paths": [],
                "executable": r"C:\Python313\python.exe",
                "argv": ["python", "-m", "unittest"],
                "cwd": r"C:\work\clone",
                "evidence_sha256": sha,
            },
            {
                "event_id": "EVENT-5",
                "type": "git_read_only_inspection",
                "paths": [],
                "executable": r"C:\Program Files\Git\cmd\git.exe",
                "argv": ["git", "status", "--short"],
                "cwd": r"C:\work\clone",
                "evidence_sha256": sha,
            },
            {"event_id": "EVENT-6", "type": "future_unknown", "paths": [], "evidence_sha256": sha},
        ]
        payload = b"".join(
            json.dumps(event, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
            for event in events
        )

        parsed = parse_operation_events(
            payload,
            controller_observations=(
                ControllerOperationObservation(
                    "WORKSPACE_READ",
                    "CONTROLLER_EVENT",
                    "EVENT-1",
                    None,
                    (),
                    None,
                    ("acgps/a.py",),
                    evidence_bytes,
                ),
                ControllerOperationObservation(
                    "TARGETED_TEXT_SEARCH",
                    "CONTROLLER_EVENT",
                    "EVENT-2",
                    None,
                    (),
                    None,
                    ("acgps/b.py",),
                    evidence_bytes,
                ),
                ControllerOperationObservation(
                    "APPROVED_FILE_PATCH",
                    "CONTROLLER_EVENT",
                    "EVENT-3",
                    None,
                    (),
                    None,
                    ("acgps/c.py",),
                    evidence_bytes,
                ),
                ControllerOperationObservation(
                    "LOCAL_CHECK_PROCESS",
                    "PROCESS_OBSERVATION",
                    "EVENT-4",
                    r"C:\Python313\python.exe",
                    ("python", "-m", "unittest"),
                    r"C:\work\clone",
                    (),
                    evidence_bytes,
                ),
                ControllerOperationObservation(
                    "GIT_READ_ONLY_INSPECTION",
                    "PROCESS_OBSERVATION",
                    "EVENT-5",
                    r"C:\Program Files\Git\cmd\git.exe",
                    ("git", "status", "--short"),
                    r"C:\work\clone",
                    (),
                    evidence_bytes,
                ),
            ),
        )

        self.assertEqual(parsed.parsed_count, 6)
        self.assertEqual(parsed.unknown_count, 1)
        self.assertEqual(parsed.prohibited_count, 0)
        self.assertEqual(
            [row["class"] for row in parsed.operation_rows],
            [
                "WORKSPACE_READ",
                "TARGETED_TEXT_SEARCH",
                "APPROVED_FILE_PATCH",
                "LOCAL_CHECK_PROCESS",
                "GIT_READ_ONLY_INSPECTION",
            ],
        )
        self.assertEqual([row["sequence"] for row in parsed.operation_rows], [0, 1, 2, 3, 4])
        self.assertEqual(parsed.jsonl_sha256, hashlib.sha256(payload).hexdigest())

    def test_completed_attempt_reconciliation_derives_candidate_ready_or_hold(self) -> None:
        context = _preflight_context()
        evaluation = evaluate_prelaunch(context)
        template = _valid_candidate_ready_coding_execution_record()
        result_record = {
            "schema_version": 1,
            "packet_id": "PACKET-1",
            "role": "CODER",
            "status": "DONE",
            "summary": "Completed bounded work",
            "changed_files": ["acgps/example.py"],
            "created_files": [],
            "commands_run": [],
            "evidence_paths": ["artifacts/execution.json"],
            "assumptions": [],
            "concerns": [],
            "blocker": None,
            "recommended_next_state": "TASK_REVIEW",
        }
        result_payload = canonical_json_bytes(result_record) + b"\n"
        event_payload = (
            json.dumps(
                {"type": "final_response", "response": result_payload.decode("utf-8")},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8")
        diff_evidence = b"controller-derived-diff"
        patch_observation = ControllerOperationObservation(
            operation_class="APPROVED_FILE_PATCH",
            source="FILESYSTEM_DIFF",
            event_id=None,
            executable=None,
            argv=(),
            cwd=None,
            path_set=("acgps/example.py",),
            evidence_bytes=diff_evidence,
        )
        reservation = deepcopy(template["attempt"])
        process = deepcopy(template["process"])
        agent_result = observe_agent_result(
            result_payload,
            logical_path="artifacts/agent-result.json",
            format_suffix=".json",
            changed_paths=("acgps/example.py",),
            commands_run=(),
        )
        clone_after = deepcopy(template["clone_after"])
        assert isinstance(reservation, dict)
        assert isinstance(process, dict)
        assert isinstance(agent_result, dict)
        assert isinstance(clone_after, dict)
        reservation.pop("process_start_request_count")
        clone_after["diff_sha256"] = hashlib.sha256(diff_evidence).hexdigest()

        ready = build_completed_attempt_record(
            context,
            evaluation,
            execution_id="EXECUTION-1",
            checked_at_utc="2026-08-24T00:00:00.000Z",
            reservation=reservation,
            process=process,
            events=parse_operation_events(event_payload, controller_observations=(patch_observation,)),
            agent_result=agent_result,
            clone_after=clone_after,
            candidate_id="CANDIDATE-1",
        )

        validate_contract("coding_execution_record", ready)
        self.assertEqual(ready["outcome"], "CANDIDATE_READY")
        self.assertEqual(ready["slot"]["state_after"], "FROZEN_REVIEW_V1")

        unknown_payload = event_payload + b'{"type":"future_unknown"}\n'
        held = build_completed_attempt_record(
            context,
            evaluation,
            execution_id="EXECUTION-2",
            checked_at_utc="2026-08-24T00:00:00.000Z",
            reservation=reservation,
            process=process,
            events=parse_operation_events(unknown_payload, controller_observations=(patch_observation,)),
            agent_result=agent_result,
            clone_after=clone_after,
            candidate_id="CANDIDATE-1",
        )
        validate_contract("coding_execution_record", held)
        self.assertEqual(held["outcome"], "ATTEMPT_HOLD")
        self.assertEqual(held["candidate"]["status"], "NONE")

        check_evidence = b"controller-observed-unapproved-check"
        unapproved_check = {
            "event_id": "EVENT-2",
            "type": "local_check_process",
            "paths": [],
            "executable": sys.executable,
            "argv": ["python", "-m", "pip", "install", "example"],
            "cwd": str(context.clone_root),
            "evidence_sha256": hashlib.sha256(check_evidence).hexdigest(),
        }
        unapproved_payload = (
            json.dumps(unapproved_check, sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n"
            + event_payload
        )
        unapproved = build_completed_attempt_record(
            context,
            evaluation,
            execution_id="EXECUTION-3",
            checked_at_utc="2026-08-24T00:00:00.000Z",
            reservation=reservation,
            process=process,
            events=parse_operation_events(
                unapproved_payload,
                controller_observations=(
                    patch_observation,
                    ControllerOperationObservation(
                        operation_class="LOCAL_CHECK_PROCESS",
                        source="PROCESS_OBSERVATION",
                        event_id="EVENT-2",
                        executable=sys.executable,
                        argv=("python", "-m", "pip", "install", "example"),
                        cwd=str(context.clone_root),
                        path_set=(),
                        evidence_bytes=check_evidence,
                    ),
                ),
            ),
            agent_result=agent_result,
            clone_after=clone_after,
            candidate_id="CANDIDATE-1",
        )
        self.assertEqual(unapproved["outcome"], "ATTEMPT_HOLD")


if __name__ == "__main__":
    unittest.main()
