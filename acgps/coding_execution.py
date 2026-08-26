from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from acgps.contracts import (
    CODING_DISABLED_SURFACES,
    CODING_EXECUTOR_PLATFORM_PROFILES,
    CODING_OPERATION_CLASSES,
    validate_contract,
)
from acgps.workflow_contracts import canonical_json_bytes
from acgps.yaml_loader import load_yaml_strict


@dataclass
class PreflightContext:
    project_id: str
    packet: dict[str, Any]
    packet_bytes: bytes
    baseline: dict[str, Any]
    baseline_before_state: bytes
    baseline_after_state: bytes
    slot: dict[str, Any]
    clone_before: dict[str, Any]
    executor: dict[str, Any]
    expected_executor: dict[str, Any]
    capabilities: dict[str, Any]
    baseline_root: Path
    state_root: Path
    evidence_root: Path
    clone_root: Path
    evidence_destinations: tuple[Path, ...]
    environment: dict[str, str]
    check_argv_allowlist: tuple[tuple[str, ...], ...]
    git_read_argv_allowlist: tuple[tuple[str, ...], ...]
    controller_boundary_observation: "ControllerBoundaryObservation | None"
    wall_clock_limit_seconds: int
    model_request_started: bool
    process_start_requested: bool


@dataclass(frozen=True)
class PreflightEvaluation:
    state: str
    gate_rows: list[dict[str, Any]]
    blocker_ids: list[str]


@dataclass(frozen=True)
class ParsedOperationEvents:
    jsonl_sha256: str
    size_bytes: int
    parsed_count: int
    unknown_count: int
    prohibited_count: int
    final_response_sha256: str | None
    operation_rows: list[dict[str, Any]]


@dataclass(frozen=True)
class ControllerBoundaryObservation:
    effective_config_bytes: bytes
    network_policy_bytes: bytes
    authorized_write_paths: tuple[str, ...]
    writable_roots: tuple[Path, ...]
    immutable_roots: tuple[Path, ...]
    environment: tuple[tuple[str, str], ...]
    check_argv_allowlist: tuple[tuple[str, ...], ...]
    git_read_argv_allowlist: tuple[tuple[str, ...], ...]
    event_capture_source: str
    filesystem_reconciliation_source: str
    git_reconciliation_source: str
    network_enforcement_source: str
    process_capture_source: str


@dataclass(frozen=True)
class ControllerOperationObservation:
    operation_class: str
    source: str
    event_id: str | None
    executable: str | None
    argv: tuple[str, ...]
    cwd: str | None
    path_set: tuple[str, ...]
    evidence_bytes: bytes


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _evidence_hash(value: object) -> str:
    return _sha256(canonical_json_bytes(value))


def _is_under(path: Path, root: Path) -> bool:
    resolved_path = path.resolve(strict=False)
    resolved_root = root.resolve(strict=False)
    return resolved_path == resolved_root or resolved_path.is_relative_to(resolved_root)


def _roots_are_separate(clone_root: Path, roots: tuple[Path, ...]) -> bool:
    return all(not _is_under(root, clone_root) and not _is_under(clone_root, root) for root in roots)


def _contains_secret(environment: Mapping[str, str]) -> bool:
    secret_name = re.compile(r"(?:API[_-]?KEY|AUTH|PASSWORD|SECRET|TOKEN)", re.IGNORECASE)
    secret_value = re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|-----BEGIN [A-Z ]+PRIVATE KEY-----)")
    return any(secret_name.search(key) or secret_value.search(value) for key, value in environment.items())


def _contains_secret_bytes(value: bytes) -> bool:
    try:
        text = value.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return bool(
        re.search(r"(?:API[_-]?KEY|PASSWORD|SECRET|TOKEN)\s*[:=]", text, re.IGNORECASE)
        or re.search(r"sk-[A-Za-z0-9_-]{12,}|-----BEGIN [A-Z ]+PRIVATE KEY-----", text)
    )


def coding_execution_binding_sha256(
    *,
    baseline: Mapping[str, Any],
    expected_executor: Mapping[str, Any],
    authorized_write_paths: tuple[str, ...],
    check_argv_allowlist: tuple[tuple[str, ...], ...],
    git_read_argv_allowlist: tuple[tuple[str, ...], ...],
    effective_config_sha256: str,
    network_policy_sha256: str,
    wall_clock_limit_seconds: int,
) -> str:
    binding = {
        "authorized_write_paths": list(authorized_write_paths),
        "baseline": {
            "commit": baseline.get("commit"),
            "repository_path": baseline.get("repository_path"),
            "tree": baseline.get("tree"),
        },
        "check_argv_allowlist": [list(argv) for argv in check_argv_allowlist],
        "effective_config_sha256": effective_config_sha256,
        "executor": dict(expected_executor),
        "git_read_argv_allowlist": [list(argv) for argv in git_read_argv_allowlist],
        "network_policy_sha256": network_policy_sha256,
        "wall_clock_limit_seconds": wall_clock_limit_seconds,
    }
    return _evidence_hash(binding)


def _strict_json_mapping(value: str) -> dict[str, Any]:
    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        folded: set[str] = set()
        for key, item in pairs:
            if key in result or key.casefold() in folded:
                raise ValueError(f"duplicate or case-fold-colliding JSON key: {key}")
            result[key] = item
            folded.add(key.casefold())
        return result

    record = json.loads(value, object_pairs_hook=reject_duplicate_pairs)
    if not isinstance(record, dict):
        raise ValueError("expected a JSON mapping")
    return record


def _gate_row(gate_id: str, passed: bool, blocker_id: str, evidence: object) -> dict[str, Any]:
    return {
        "gate_id": gate_id,
        "status": "PASS" if passed else "HOLD",
        "evidence_sha256": _evidence_hash(evidence),
        "blocker_ids": [] if passed else [blocker_id],
    }


def observe_agent_result(
    payload: bytes,
    *,
    logical_path: str,
    format_suffix: str,
    changed_paths: tuple[str, ...],
    commands_run: tuple[str, ...],
) -> dict[str, Any]:
    null_record = {
        "path": None,
        "sha256": None,
        "size_bytes": 0,
        "contract_valid": False,
        "claimed_status": None,
        "claims_match": False,
    }
    if _safe_event_paths([logical_path]) is None:
        return null_record
    try:
        text = payload.decode("utf-8")
        if format_suffix.casefold() == ".json":
            result = json.loads(text)
        elif format_suffix.casefold() in (".yaml", ".yml"):
            result = load_yaml_strict(text, logical_path=logical_path)
        else:
            return null_record
        if not isinstance(result, dict):
            return null_record
        validate_contract("agent_result", result)
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return null_record
    claimed_paths = sorted(
        [
            path
            for field_name in ("changed_files", "created_files")
            for path in result.get(field_name, [])
            if isinstance(path, str)
        ]
    )
    claims_match = (
        claimed_paths == list(changed_paths)
        and result.get("commands_run") == list(commands_run)
    )
    return {
        "path": logical_path,
        "sha256": _sha256(payload),
        "size_bytes": len(payload),
        "contract_valid": True,
        "claimed_status": result.get("status"),
        "claims_match": claims_match,
    }


def evaluate_prelaunch(context: PreflightContext) -> PreflightEvaluation:
    packet_sha = _sha256(context.packet_bytes)
    packet_contract_valid = False
    packet_payload: dict[str, Any] | None = None
    try:
        decoded_packet = _strict_json_mapping(context.packet_bytes.decode("utf-8"))
        if isinstance(decoded_packet, dict):
            validate_contract("agent_task_contract", decoded_packet)
            packet_contract_valid = canonical_json_bytes(decoded_packet) + b"\n" == context.packet_bytes
            packet_payload = decoded_packet
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        packet_contract_valid = False
    before_sha = _sha256(context.baseline_before_state)
    after_sha = _sha256(context.baseline_after_state)
    p0_evidence = {
        "packet": context.packet,
        "packet_sha256": packet_sha,
        "packet_size": len(context.packet_bytes),
        "packet_contract_valid": packet_contract_valid,
        "baseline": context.baseline,
        "before_sha256": before_sha,
        "after_sha256": after_sha,
        "clone_commit": context.clone_before.get("commit"),
        "clone_tree": context.clone_before.get("tree"),
    }
    capabilities = context.capabilities
    authorized_write_paths = capabilities.get("authorized_write_paths")
    effective_config_sha256 = capabilities.get("effective_config_sha256")
    network_policy_sha256 = capabilities.get("network_policy_sha256")
    expected_binding_sha256 = None
    if (
        isinstance(authorized_write_paths, list)
        and all(isinstance(path, str) for path in authorized_write_paths)
        and isinstance(effective_config_sha256, str)
        and isinstance(network_policy_sha256, str)
    ):
        expected_binding_sha256 = coding_execution_binding_sha256(
            baseline=context.baseline,
            expected_executor=context.expected_executor,
            authorized_write_paths=tuple(authorized_write_paths),
            check_argv_allowlist=context.check_argv_allowlist,
            git_read_argv_allowlist=context.git_read_argv_allowlist,
            effective_config_sha256=effective_config_sha256,
            network_policy_sha256=network_policy_sha256,
            wall_clock_limit_seconds=context.wall_clock_limit_seconds,
        )
    expected_binding_constraint = (
        [f"ACGPS-CODING-BINDING-SHA256:{expected_binding_sha256}"]
        if expected_binding_sha256 is not None
        else None
    )
    p0 = all(
        (
            context.packet.get("validation_status") == "PASS",
            packet_contract_valid,
            isinstance(packet_payload, dict),
            isinstance(packet_payload, dict) and packet_payload.get("packet_id") == context.packet.get("packet_id"),
            isinstance(packet_payload, dict) and packet_payload.get("project_id") == context.project_id,
            isinstance(packet_payload, dict) and packet_payload.get("task_id") == context.slot.get("task_id"),
            isinstance(packet_payload, dict) and packet_payload.get("role") == "CODER",
            isinstance(packet_payload, dict)
            and packet_payload.get("relevant_paths") == authorized_write_paths,
            isinstance(packet_payload, dict)
            and packet_payload.get("binding_constraints") == expected_binding_constraint,
            context.packet.get("sha256") == packet_sha,
            context.packet.get("size_bytes") == len(context.packet_bytes),
            context.baseline.get("before_state_sha256") == before_sha,
            context.baseline.get("after_state_sha256") == after_sha,
            context.baseline.get("unchanged") is True,
            before_sha == after_sha,
            context.clone_before.get("commit") == context.baseline.get("commit"),
            context.clone_before.get("tree") == context.baseline.get("tree"),
        )
    )

    slot_state = context.slot.get("state")
    remaining = context.slot.get("remaining_attempts")
    p1_ordinary = (
        slot_state == "EMPTY"
        and remaining in (1, 2)
        and context.slot.get("active_candidate_id") is None
        and context.slot.get("reserved_attempt") is None
    )
    p1_remediation = (
        slot_state == "EMPTY_FOR_REMEDIATION"
        and remaining == 1
        and context.slot.get("active_candidate_id") is None
        and context.slot.get("reserved_attempt") is None
        and isinstance(context.slot.get("historical_candidate_ids"), list)
        and len(context.slot["historical_candidate_ids"]) == 1
        and isinstance(context.slot.get("remediation_authorization_id"), str)
    )
    p1 = p1_ordinary or p1_remediation

    clone_path = context.clone_before.get("path")
    p2 = all(
        (
            isinstance(clone_path, str) and Path(clone_path).resolve(strict=False) == context.clone_root.resolve(strict=False),
            context.clone_before.get("commit") == context.baseline.get("commit"),
            context.clone_before.get("tree") == context.baseline.get("tree"),
            context.clone_before.get("remote_count") == 0,
            context.clone_before.get("independent_git") is True,
            context.clone_before.get("detached") is True,
            context.clone_before.get("clean") is True,
        )
    )

    executor = context.executor
    p3 = all(
        (
            executor == context.expected_executor,
            executor.get("identity_complete") is True,
            executor.get("authenticode_status") == "VALID",
            isinstance(executor.get("signer"), str),
            isinstance(executor.get("sha256"), str),
            isinstance(executor.get("size_bytes"), int),
            isinstance(executor.get("cli_version"), str),
            isinstance(executor.get("argv"), list) and len(executor["argv"]) >= 2 and executor["argv"][1] == "exec",
            executor.get("model") == "gpt-5.6-sol",
            executor.get("reasoning_effort") == "high",
            executor.get("auth_mode") == "CHATGPT_SUBSCRIPTION",
            executor.get("sandbox") == "ISOLATED_CLONE",
            executor.get("approval_policy") == "NEVER",
            executor.get("platform") in CODING_EXECUTOR_PLATFORM_PROFILES,
            context.wall_clock_limit_seconds == 1800,
        )
    )

    observation = context.controller_boundary_observation
    check_allowlist_sha256 = _evidence_hash([list(argv) for argv in context.check_argv_allowlist])
    git_read_allowlist_sha256 = _evidence_hash([list(argv) for argv in context.git_read_argv_allowlist])
    observation_complete = isinstance(observation, ControllerBoundaryObservation)
    effective_config_observed_sha256 = (
        _sha256(observation.effective_config_bytes) if observation_complete else None
    )
    network_policy_observed_sha256 = (
        _sha256(observation.network_policy_bytes) if observation_complete else None
    )
    p4 = all(
        (
            observation_complete,
            capabilities.get("boundary_mode") == "FIVE_CLASS_OPERATION_AND_PROMOTION_POLICY",
            capabilities.get("shell_identity_present") is True,
            capabilities.get("accepted_operation_classes") == list(CODING_OPERATION_CLASSES),
            capabilities.get("disabled_surfaces") == list(CODING_DISABLED_SURFACES),
            capabilities.get("automatic_resume_enabled") is False,
            capabilities.get("hooks_enabled") is False,
            capabilities.get("memories_enabled") is False,
            capabilities.get("observations_complete") is True,
            effective_config_observed_sha256 == capabilities.get("effective_config_sha256"),
            network_policy_observed_sha256 == capabilities.get("network_policy_sha256"),
            isinstance(capabilities.get("check_allowlist_sha256"), str),
            isinstance(capabilities.get("git_read_allowlist_sha256"), str),
            capabilities.get("check_allowlist_sha256") == check_allowlist_sha256,
            capabilities.get("git_read_allowlist_sha256") == git_read_allowlist_sha256,
            isinstance(observation, ControllerBoundaryObservation)
            and list(observation.authorized_write_paths) == authorized_write_paths,
            isinstance(observation, ControllerBoundaryObservation)
            and observation.check_argv_allowlist == context.check_argv_allowlist,
            isinstance(observation, ControllerBoundaryObservation)
            and observation.git_read_argv_allowlist == context.git_read_argv_allowlist,
            isinstance(observation, ControllerBoundaryObservation)
            and observation.environment == tuple(sorted(context.environment.items())),
            isinstance(observation, ControllerBoundaryObservation)
            and observation.event_capture_source == "CONTROLLER_EVENT_RECONCILER_V1",
            isinstance(observation, ControllerBoundaryObservation)
            and observation.filesystem_reconciliation_source == "CONTROLLER_FILESYSTEM_SNAPSHOT_V1",
            isinstance(observation, ControllerBoundaryObservation)
            and observation.git_reconciliation_source == "CONTROLLER_GIT_SNAPSHOT_V1",
            isinstance(observation, ControllerBoundaryObservation)
            and observation.network_enforcement_source == "WINDOWS_NETWORK_POLICY_OBSERVER_V1",
            isinstance(observation, ControllerBoundaryObservation)
            and observation.process_capture_source == "WINDOWS_JOB_OBJECT_V1",
        )
    )

    roots_separate = _roots_are_separate(
        context.clone_root,
        (context.baseline_root, context.state_root, context.evidence_root),
    )
    evidence_contained = all(
        _is_under(path, context.evidence_root) and not _is_under(path, context.clone_root)
        for path in context.evidence_destinations
    )
    observed_roots_match = isinstance(observation, ControllerBoundaryObservation) and (
        observation.writable_roots == (context.clone_root,)
        and observation.immutable_roots == (context.baseline_root, context.state_root, context.evidence_root)
    )
    observation_evidence = (
        None
        if not isinstance(observation, ControllerBoundaryObservation)
        else {
            "authorized_write_paths": list(observation.authorized_write_paths),
            "check_argv_allowlist": [list(argv) for argv in observation.check_argv_allowlist],
            "effective_config_sha256": effective_config_observed_sha256,
            "environment_names": [name for name, _value in observation.environment],
            "event_capture_source": observation.event_capture_source,
            "filesystem_reconciliation_source": observation.filesystem_reconciliation_source,
            "git_read_argv_allowlist": [list(argv) for argv in observation.git_read_argv_allowlist],
            "git_reconciliation_source": observation.git_reconciliation_source,
            "immutable_roots": [str(path) for path in observation.immutable_roots],
            "network_enforcement_source": observation.network_enforcement_source,
            "network_policy_sha256": network_policy_observed_sha256,
            "process_capture_source": observation.process_capture_source,
            "writable_roots": [str(path) for path in observation.writable_roots],
        }
    )
    executor_argv_bytes = canonical_json_bytes(context.executor.get("argv"))
    p5 = all(
        (
            roots_separate,
            evidence_contained,
            observed_roots_match,
            not _contains_secret(context.environment),
            not _contains_secret_bytes(context.packet_bytes),
            not _contains_secret_bytes(executor_argv_bytes),
            isinstance(observation, ControllerBoundaryObservation)
            and bool(observation.network_policy_bytes),
            network_policy_observed_sha256 == capabilities.get("network_policy_sha256"),
        )
    )

    p6 = all(
        (
            context.model_request_started is False,
            context.process_start_requested is False,
            context.clone_before.get("index_sha256") is not None,
            context.clone_before.get("status_sha256") is not None,
            context.clone_before.get("git_control_sha256") is not None,
            context.clone_before.get("file_inventory_sha256") is not None,
            len(context.evidence_destinations) > 0,
        )
    )

    rows = [
        _gate_row("P0", p0, "P0-IDENTITY-MISMATCH", p0_evidence),
        _gate_row("P1", p1, "P1-SLOT-OR-BUDGET-INVALID", context.slot),
        _gate_row("P2", p2, "P2-CLONE-INVALID", context.clone_before),
        _gate_row(
            "P3",
            p3,
            "P3-EXECUTOR-INVALID",
            {"expected": context.expected_executor, "observed": context.executor},
        ),
        _gate_row(
            "P4",
            p4,
            "P4-CAPABILITY-INCOMPLETE",
            {
                "capabilities": context.capabilities,
                "check_allowlist_sha256": check_allowlist_sha256,
                "git_read_allowlist_sha256": git_read_allowlist_sha256,
                "observation": observation_evidence,
            },
        ),
        _gate_row(
            "P5",
            p5,
            "P5-SECRET-OR-ROOT-BOUNDARY",
            {
                "baseline_root": str(context.baseline_root),
                "state_root": str(context.state_root),
                "evidence_root": str(context.evidence_root),
                "clone_root": str(context.clone_root),
                "environment_names": sorted(context.environment),
            },
        ),
        _gate_row(
            "P6",
            p6,
            "P6-BEFORE-STATE-NOT-FROZEN",
            {
                "model_request_started": context.model_request_started,
                "process_start_requested": context.process_start_requested,
                "evidence_destinations": [str(path) for path in context.evidence_destinations],
            },
        ),
    ]
    blockers = [blocker for row in rows for blocker in row["blocker_ids"]]
    return PreflightEvaluation(
        state="PASS" if not blockers else "HOLD",
        gate_rows=rows,
        blocker_ids=blockers,
    )


def build_prelaunch_hold_record(
    context: PreflightContext,
    evaluation: PreflightEvaluation,
    *,
    execution_id: str,
    checked_at_utc: str,
) -> dict[str, Any]:
    if evaluation.state != "HOLD" or not evaluation.blocker_ids:
        raise ValueError("a prelaunch HOLD record requires at least one failed gate")
    remaining = context.slot.get("remaining_attempts")
    if remaining not in (0, 1, 2):
        raise ValueError("slot remaining-attempt count is invalid")
    state = context.slot.get("state")
    active_candidate = context.slot.get("active_candidate_id")
    historical = context.slot.get("historical_candidate_ids")
    if not isinstance(state, str) or not isinstance(historical, list):
        raise ValueError("slot evidence is incomplete")
    record = {
        "schema_version": 2,
        "execution_id": execution_id,
        "gate_id": context.slot.get("gate_id"),
        "project_id": context.project_id,
        "task_id": context.slot.get("task_id"),
        "packet": deepcopy(context.packet),
        "baseline": deepcopy(context.baseline),
        "slot": {
            "slot_id": context.slot.get("gate_id"),
            "state_before": state,
            "state_after": state,
            "active_candidate_before": active_candidate,
            "active_candidate_after": active_candidate,
            "historical_candidate_ids": list(historical),
        },
        "attempt": {
            "number": None,
            "reserved_at_utc": None,
            "parent_candidate_id": None,
            "kind": "PRELAUNCH",
            "remaining_before": remaining,
            "remaining_after": remaining,
            "process_start_request_count": 0,
        },
        "executor": deepcopy(context.executor),
        "capabilities": deepcopy(context.capabilities),
        "clone_before": deepcopy(context.clone_before),
        "prelaunch": {
            "state": "HOLD",
            "checked_at_utc": checked_at_utc,
            "gate_rows": deepcopy(evaluation.gate_rows),
            "model_request_started": False,
            "process_start_requested": False,
            "blocker_ids": list(evaluation.blocker_ids),
        },
        "process": {
            "start_requested": False,
            "pid": None,
            "started_at_utc": None,
            "ended_at_utc": None,
            "exit_code": None,
            "timed_out": False,
            "cancelled": False,
            "error": None,
            "descendant_count": 0,
            "all_descendants_terminated": True,
            "stdout_sha256": None,
            "stderr_sha256": None,
        },
        "events": {
            "jsonl_sha256": None,
            "size_bytes": 0,
            "parsed_count": 0,
            "unknown_count": 0,
            "prohibited_count": 0,
            "final_response_sha256": None,
            "output_schema_valid": False,
        },
        "agent_result": {
            "path": None,
            "sha256": None,
            "size_bytes": 0,
            "contract_valid": False,
            "claimed_status": None,
            "claims_match": False,
        },
        "clone_after": None,
        "candidate": {
            "candidate_id": None,
            "version": None,
            "status": "NONE",
            "parent_candidate_id": None,
            "diff_sha256": None,
            "file_set_sha256": None,
            "checks_sha256": None,
            "promotion_predicates_passed": False,
        },
        "outcome": "PRELAUNCH_HOLD",
        "created_at_utc": checked_at_utc,
    }
    validate_contract("coding_execution_record", record)
    return record


def build_completed_attempt_record(
    context: PreflightContext,
    evaluation: PreflightEvaluation,
    *,
    execution_id: str,
    checked_at_utc: str,
    reservation: dict[str, Any],
    process: dict[str, Any],
    events: ParsedOperationEvents,
    agent_result: dict[str, Any],
    clone_after: dict[str, Any] | None,
    candidate_id: str,
) -> dict[str, Any]:
    if evaluation.state != "PASS" or evaluation.blocker_ids:
        raise ValueError("an attempt can be reconciled only after all prelaunch gates pass")
    required_reservation_fields = {
        "number",
        "reserved_at_utc",
        "parent_candidate_id",
        "kind",
        "remaining_before",
        "remaining_after",
    }
    if set(reservation) != required_reservation_fields:
        raise ValueError("reservation fields do not match the bounded attempt contract")
    if reservation.get("number") not in (1, 2):
        raise ValueError("a completed attempt requires Attempt 1 or Attempt 2")

    capabilities = deepcopy(context.capabilities)
    capabilities["operation_rows"] = deepcopy(events.operation_rows)
    output_schema_valid = (
        events.final_response_sha256 is not None
        and events.final_response_sha256 == agent_result.get("sha256")
        and events.unknown_count == 0
        and events.prohibited_count == 0
    )
    event_record = {
        "jsonl_sha256": events.jsonl_sha256,
        "size_bytes": events.size_bytes,
        "parsed_count": events.parsed_count,
        "unknown_count": events.unknown_count,
        "prohibited_count": events.prohibited_count,
        "final_response_sha256": events.final_response_sha256,
        "output_schema_valid": output_schema_valid,
    }

    changed_paths = clone_after.get("changed_paths") if isinstance(clone_after, dict) else None
    patch_paths = sorted(
        {
            path
            for row in events.operation_rows
            if row.get("class") == "APPROVED_FILE_PATCH"
            for path in row.get("path_set", [])
            if isinstance(path, str)
        }
    )
    authorized_paths = capabilities.get("authorized_write_paths")
    rows_reconciled = all(
        row.get("status") == "PASS"
        and row.get("sequence") == index
        and (
            row.get("class") != "APPROVED_FILE_PATCH"
            or (
                row.get("source") == "FILESYSTEM_DIFF"
                and row.get("event_id") is None
                and isinstance(clone_after, dict)
                and row.get("evidence_sha256") == clone_after.get("diff_sha256")
            )
        )
        and (
            row.get("class") != "LOCAL_CHECK_PROCESS"
            or (
                row.get("source") == "PROCESS_OBSERVATION"
                and tuple(row.get("argv", [])) in context.check_argv_allowlist
            )
        )
        and (
            row.get("class") != "GIT_READ_ONLY_INSPECTION"
            or (
                row.get("source") in {"PROCESS_OBSERVATION", "GIT_DIFF"}
                and tuple(row.get("argv", [])) in context.git_read_argv_allowlist
            )
        )
        for index, row in enumerate(events.operation_rows)
    )
    process_succeeded = all(
        (
            process.get("start_requested") is True,
            isinstance(process.get("pid"), int),
            process.get("exit_code") == 0,
            process.get("error") is None,
            process.get("timed_out") is False,
            process.get("cancelled") is False,
            process.get("all_descendants_terminated") is True,
        )
    )
    clone_reconciled = isinstance(clone_after, dict) and all(
        (
            clone_after.get("commit") == context.clone_before.get("commit"),
            clone_after.get("tree") == context.clone_before.get("tree"),
            clone_after.get("git_control_sha256") == context.clone_before.get("git_control_sha256"),
            changed_paths == patch_paths,
            isinstance(authorized_paths, list),
            isinstance(changed_paths, list),
            set(changed_paths or []).issubset(set(authorized_paths or [])),
        )
    )
    agent_promotable = all(
        (
            agent_result.get("contract_valid") is True,
            agent_result.get("claims_match") is True,
            agent_result.get("claimed_status") == "DONE",
        )
    )
    promotable = all(
        (
            process_succeeded,
            output_schema_valid,
            rows_reconciled,
            clone_reconciled,
            agent_promotable,
            context.executor.get("identity_complete") is True,
            capabilities.get("observations_complete") is True,
        )
    )

    version = 2 if reservation.get("kind") == "REMEDIATION" else 1
    state_before = context.slot.get("state")
    active_before = context.slot.get("active_candidate_id")
    historical = context.slot.get("historical_candidate_ids")
    if not isinstance(state_before, str) or not isinstance(historical, list):
        raise ValueError("slot evidence is incomplete")
    if promotable:
        state_after = f"FROZEN_REVIEW_V{version}"
        active_after: str | None = candidate_id
        assert isinstance(clone_after, dict)
        candidate = {
            "candidate_id": candidate_id,
            "version": version,
            "status": "FROZEN_REVIEW",
            "parent_candidate_id": reservation.get("parent_candidate_id"),
            "diff_sha256": clone_after.get("diff_sha256"),
            "file_set_sha256": _evidence_hash(
                {
                    "changed_paths": clone_after.get("changed_paths"),
                    "file_inventory_sha256": clone_after.get("file_inventory_sha256"),
                }
            ),
            "checks_sha256": _evidence_hash(
                [row for row in events.operation_rows if row.get("class") == "LOCAL_CHECK_PROCESS"]
            ),
            "promotion_predicates_passed": True,
        }
        outcome = "CANDIDATE_READY"
    else:
        state_after = state_before
        active_after = active_before
        candidate = {
            "candidate_id": None,
            "version": None,
            "status": "NONE",
            "parent_candidate_id": None,
            "diff_sha256": None,
            "file_set_sha256": None,
            "checks_sha256": None,
            "promotion_predicates_passed": False,
        }
        process_failed = any(
            (
                process.get("start_requested") is not True,
                process.get("pid") is None,
                process.get("error") is not None,
                process.get("timed_out") is True,
                process.get("cancelled") is True,
                process.get("all_descendants_terminated") is not True,
                isinstance(process.get("exit_code"), int) and process.get("exit_code") != 0,
                agent_result.get("claimed_status") == "FAILED",
            )
        )
        outcome = "ATTEMPT_FAILED" if process_failed else "ATTEMPT_HOLD"

    record = {
        "schema_version": 2,
        "execution_id": execution_id,
        "gate_id": context.slot.get("gate_id"),
        "project_id": context.project_id,
        "task_id": context.slot.get("task_id"),
        "packet": deepcopy(context.packet),
        "baseline": deepcopy(context.baseline),
        "slot": {
            "slot_id": context.slot.get("gate_id"),
            "state_before": state_before,
            "state_after": state_after,
            "active_candidate_before": active_before,
            "active_candidate_after": active_after,
            "historical_candidate_ids": list(historical),
        },
        "attempt": {
            **deepcopy(reservation),
            "process_start_request_count": 1,
        },
        "executor": deepcopy(context.executor),
        "capabilities": capabilities,
        "clone_before": deepcopy(context.clone_before),
        "prelaunch": {
            "state": "PASS",
            "checked_at_utc": checked_at_utc,
            "gate_rows": deepcopy(evaluation.gate_rows),
            "model_request_started": True,
            "process_start_requested": True,
            "blocker_ids": [],
        },
        "process": deepcopy(process),
        "events": event_record,
        "agent_result": deepcopy(agent_result),
        "clone_after": deepcopy(clone_after),
        "candidate": candidate,
        "outcome": outcome,
        "created_at_utc": checked_at_utc,
    }
    validate_contract("coding_execution_record", record)
    return record


_EVENT_CLASS = {
    "workspace_read": "WORKSPACE_READ",
    "targeted_text_search": "TARGETED_TEXT_SEARCH",
    "approved_file_patch": "APPROVED_FILE_PATCH",
    "local_check_process": "LOCAL_CHECK_PROCESS",
    "git_read_only_inspection": "GIT_READ_ONLY_INSPECTION",
}
_PROCESS_EVENT_TYPES = {"local_check_process", "git_read_only_inspection"}


def _safe_event_paths(value: object) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    paths = list(value)
    if paths != sorted(set(paths)):
        return None
    if any(
        not item
        or "\\" in item
        or item.startswith("/")
        or re.match(r"^[A-Za-z]:", item)
        or any(part in ("", ".", "..") for part in item.split("/"))
        for item in paths
    ):
        return None
    return paths


def parse_operation_events(
    payload: bytes,
    *,
    controller_observations: tuple[ControllerOperationObservation, ...] = (),
) -> ParsedOperationEvents:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError:
        return ParsedOperationEvents(_sha256(payload), len(payload), 0, 1, 0, None, [])
    parsed_count = 0
    unknown_count = 0
    prohibited_count = 0
    final_response_sha256: str | None = None
    operation_rows: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    claims: dict[str, dict[str, Any]] = {}
    for raw_line in text.splitlines():
        if not raw_line:
            continue
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            unknown_count += 1
            continue
        if not isinstance(event, dict):
            unknown_count += 1
            continue
        parsed_count += 1
        event_type = event.get("type")
        if event_type == "final_response":
            response = event.get("response")
            if set(event) == {"type", "response"} and isinstance(response, str) and final_response_sha256 is None:
                response_bytes = response.encode("utf-8")
                try:
                    response_record = _strict_json_mapping(response)
                    validate_contract("agent_result", response_record)
                    if canonical_json_bytes(response_record) + b"\n" != response_bytes:
                        raise ValueError("final response is not canonical agent-result JSON")
                except (json.JSONDecodeError, TypeError, ValueError):
                    unknown_count += 1
                else:
                    final_response_sha256 = _sha256(response_bytes)
            else:
                unknown_count += 1
            continue
        if event_type == "prohibited":
            prohibited_count += 1
            continue
        operation_class = _EVENT_CLASS.get(event_type)
        process_event = event_type in _PROCESS_EVENT_TYPES
        expected_keys = {"event_id", "type", "paths", "evidence_sha256"}
        if process_event:
            expected_keys.update(("executable", "argv", "cwd"))
        paths = _safe_event_paths(event.get("paths"))
        event_id = event.get("event_id")
        evidence_sha256 = event.get("evidence_sha256")
        if (
            operation_class is None
            or set(event) != expected_keys
            or paths is None
            or not isinstance(event_id, str)
            or not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,127}", event_id)
            or event_id in event_ids
            or not isinstance(evidence_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", evidence_sha256)
        ):
            unknown_count += 1
            continue
        executable = event.get("executable") if process_event else None
        argv = event.get("argv") if process_event else []
        cwd = event.get("cwd") if process_event else None
        if process_event and (
            not isinstance(executable, str)
            or not isinstance(argv, list)
            or not argv
            or not all(isinstance(item, str) and item for item in argv)
            or not isinstance(cwd, str)
        ):
            unknown_count += 1
            continue
        event_ids.add(event_id)
        claims[event_id] = {
            "class": operation_class,
            "event_id": event_id,
            "executable": executable,
            "argv": argv,
            "cwd": cwd,
            "path_set": paths,
            "evidence_sha256": evidence_sha256,
        }
    matched_claims: set[str] = set()
    for observation in controller_observations:
        paths = _safe_event_paths(list(observation.path_set))
        evidence_sha256 = _sha256(observation.evidence_bytes)
        process_class = observation.operation_class in {"LOCAL_CHECK_PROCESS", "GIT_READ_ONLY_INSPECTION"}
        valid = all(
            (
                observation.operation_class in CODING_OPERATION_CLASSES,
                observation.source in {"CONTROLLER_EVENT", "PROCESS_OBSERVATION", "FILESYSTEM_DIFF", "GIT_DIFF"},
                paths is not None,
                bool(observation.evidence_bytes),
                (not process_class)
                or (
                    isinstance(observation.executable, str)
                    and bool(observation.argv)
                    and all(item for item in observation.argv)
                    and isinstance(observation.cwd, str)
                ),
                process_class
                or (observation.executable is None and not observation.argv and observation.cwd is None),
            )
        )
        if observation.event_id is not None:
            claim = claims.get(observation.event_id)
            expected_claim = {
                "class": observation.operation_class,
                "event_id": observation.event_id,
                "executable": observation.executable,
                "argv": list(observation.argv),
                "cwd": observation.cwd,
                "path_set": list(observation.path_set),
                "evidence_sha256": evidence_sha256,
            }
            valid = valid and claim == expected_claim
            if claim == expected_claim:
                matched_claims.add(observation.event_id)
        elif observation.source not in {"PROCESS_OBSERVATION", "FILESYSTEM_DIFF", "GIT_DIFF"}:
            valid = False
        if not valid:
            unknown_count += 1
        operation_rows.append(
            {
                "sequence": len(operation_rows),
                "class": observation.operation_class,
                "source": observation.source,
                "event_id": observation.event_id,
                "executable": observation.executable,
                "argv": list(observation.argv),
                "cwd": observation.cwd,
                "path_set": list(observation.path_set),
                "status": "PASS" if valid else "HOLD",
                "evidence_sha256": evidence_sha256,
            }
        )
    unknown_count += len(set(claims) - matched_claims)
    return ParsedOperationEvents(
        jsonl_sha256=_sha256(payload),
        size_bytes=len(payload),
        parsed_count=parsed_count,
        unknown_count=unknown_count,
        prohibited_count=prohibited_count,
        final_response_sha256=final_response_sha256,
        operation_rows=operation_rows,
    )
