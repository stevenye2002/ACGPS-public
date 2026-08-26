from __future__ import annotations

import hashlib
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from acgps.contracts import validate_contract
from acgps.workflow_contracts import canonical_json_bytes


_WINDOWS_FORBIDDEN_FILENAME_CHARACTERS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_DEVICE_NAMES = frozenset(
    {
        "aux",
        "clock$",
        "con",
        "conin$",
        "conout$",
        "nul",
        "prn",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
        "com¹",
        "com²",
        "com³",
        "lpt¹",
        "lpt²",
        "lpt³",
    }
)


def _is_unsafe_windows_component(segment: str) -> bool:
    device_stem = segment.split(".", 1)[0].rstrip(" ").casefold()
    return (
        segment.endswith((".", " "))
        or any(
            ord(character) < 32
            or character in _WINDOWS_FORBIDDEN_FILENAME_CHARACTERS
            for character in segment
        )
        or device_stem in _WINDOWS_RESERVED_DEVICE_NAMES
    )


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
            or any(_is_unsafe_windows_component(segment) for segment in segments)
        ):
            raise ValueError(f"{label} must be a safe relative POSIX path: {value}")


def _validate_relevant_paths(paths: list[str]) -> None:
    _validate_safe_relative_paths(paths, label="relevant path")


def _build_supervised_handoff_preview(
    packet: dict[str, Any],
    *,
    role: str,
) -> dict[str, Any]:
    validate_contract("agent_task_contract", packet, mode="runtime")
    if packet["role"] != role:
        raise ValueError(
            f"supervised {role.casefold()} handoff requires a {role} task packet"
        )
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


def build_supervised_coder_handoff_preview(packet: dict[str, Any]) -> dict[str, Any]:
    """Return a validated, non-authoritative preview for a human-supervised coder."""

    return _build_supervised_handoff_preview(packet, role="CODER")


def build_supervised_reviewer_handoff_preview(packet: dict[str, Any]) -> dict[str, Any]:
    """Return a validated, non-authoritative preview for a human-supervised reviewer."""

    return _build_supervised_handoff_preview(packet, role="REVIEWER")


def _build_supervised_result_receipt_preview(
    packet: dict[str, Any],
    agent_result: dict[str, Any],
    *,
    role: str,
) -> dict[str, Any]:
    validate_contract("agent_task_contract", packet, mode="runtime")
    validate_contract("agent_result", agent_result, mode="runtime")
    _validate_relevant_paths(packet["relevant_paths"])
    if packet["role"] != role or agent_result["role"] != role:
        raise ValueError(
            f"supervised {role.casefold()} result receipt requires {role} records"
        )
    if agent_result["packet_id"] != packet["packet_id"]:
        raise ValueError(f"agent result packet_id does not match the {role} packet")
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


def build_supervised_coder_result_receipt_preview(
    packet: dict[str, Any],
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    """Return a validated, non-authoritative result receipt preview."""

    return _build_supervised_result_receipt_preview(packet, agent_result, role="CODER")


def build_supervised_reviewer_result_receipt_preview(
    packet: dict[str, Any],
    agent_result: dict[str, Any],
) -> dict[str, Any]:
    """Return a validated, non-authoritative reviewer result receipt preview."""

    return _build_supervised_result_receipt_preview(
        packet,
        agent_result,
        role="REVIEWER",
    )
