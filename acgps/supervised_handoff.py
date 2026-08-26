from __future__ import annotations

import hashlib
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from acgps.contracts import validate_contract
from acgps.workflow_contracts import canonical_json_bytes


def _validate_safe_relative_paths(paths: list[str], *, label: str) -> None:
    for value in paths:
        segments = value.split("/")
        windows_path = PureWindowsPath(value)
        if (
            "\\" in value
            or PurePosixPath(value).is_absolute()
            or windows_path.is_absolute()
            or bool(windows_path.drive)
            or any(segment in {"", ".", ".."} for segment in segments)
        ):
            raise ValueError(f"{label} must be a safe relative POSIX path: {value}")


def _validate_relevant_paths(paths: list[str]) -> None:
    _validate_safe_relative_paths(paths, label="relevant path")


def build_supervised_coder_handoff_preview(packet: dict[str, Any]) -> dict[str, Any]:
    """Return a validated, non-authoritative preview for a human-supervised coder."""

    validate_contract("agent_task_contract", packet, mode="runtime")
    if packet["role"] != "CODER":
        raise ValueError("supervised coder handoff requires a CODER task packet")
    _validate_relevant_paths(packet["relevant_paths"])

    return {
        "controls": {
            "model_execution": "NOT_STARTED",
            "operator_authorization_required": True,
            "process_launch": "NOT_STARTED",
            "state_write": "NOT_PERFORMED",
        },
        "mode": "HUMAN_SUPERVISED",
        "packet": packet,
        "packet_sha256": hashlib.sha256(canonical_json_bytes(packet)).hexdigest(),
        "status": "HANDOFF_PREVIEW",
    }


def build_supervised_coder_result_receipt_preview(
    packet: dict[str, Any],
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    """Return a validated, non-authoritative result receipt preview."""

    validate_contract("agent_task_contract", packet, mode="runtime")
    validate_contract("agent_result", agent_result, mode="runtime")
    _validate_relevant_paths(packet["relevant_paths"])
    if packet["role"] != "CODER" or agent_result["role"] != "CODER":
        raise ValueError("supervised coder result receipt requires CODER records")
    if agent_result["packet_id"] != packet["packet_id"]:
        raise ValueError("agent result packet_id does not match the CODER packet")
    _validate_safe_relative_paths(
        [*agent_result["changed_files"], *agent_result["created_files"]],
        label="result path",
    )

    return {
        "agent_result": agent_result,
        "agent_result_sha256": hashlib.sha256(
            canonical_json_bytes(agent_result)
        ).hexdigest(),
        "controls": {
            "model_execution": "NOT_STARTED",
            "operator_authorization_required": True,
            "process_launch": "NOT_STARTED",
            "state_write": "NOT_PERFORMED",
            "workflow_transition": "NOT_PERFORMED",
        },
        "mode": "HUMAN_SUPERVISED",
        "packet_id": packet["packet_id"],
        "packet_sha256": hashlib.sha256(canonical_json_bytes(packet)).hexdigest(),
        "status": "RESULT_RECEIPT_PREVIEW",
    }
