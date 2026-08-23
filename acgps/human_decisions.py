from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from acgps.contracts import ContractValidationError, validate_contract
from acgps.workflow_store import safe_state_path


class DecisionQueueError(ValueError):
    pass


def _canonical_json_bytes(record: object) -> bytes:
    return (json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode("utf-8")


def _write_once(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json_bytes(record)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        try:
            if path.read_bytes() == payload:
                return
        except OSError:
            pass
        raise DecisionQueueError(f"decision record already exists: {path.name}") from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DecisionQueueError(f"decision record is unreadable: {path.name}") from exc
    if not isinstance(record, dict):
        raise DecisionQueueError(f"decision record must be a mapping: {path.name}")
    return record


class DecisionQueue:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def pending_path(self, decision_id: str) -> Path:
        return safe_state_path(self.root, f"pending/{decision_id}.json")

    def resolved_path(self, decision_id: str) -> Path:
        return safe_state_path(self.root, f"resolved/{decision_id}.json")

    def create(self, request: dict[str, Any]) -> Path:
        try:
            validate_contract("human_decision_request", request, mode="runtime")
        except ContractValidationError as exc:
            raise DecisionQueueError(str(exc)) from exc
        if request["status"] != "PENDING":
            raise DecisionQueueError("new decision request must be PENDING")
        path = self.pending_path(request["decision_id"])
        _write_once(path, request)
        return path

    def resolve(self, resolution: dict[str, Any]) -> Path:
        try:
            validate_contract("human_decision_resolution", resolution, mode="runtime")
        except ContractValidationError as exc:
            raise DecisionQueueError(str(exc)) from exc
        request_path = self.pending_path(resolution["decision_id"])
        if not request_path.is_file():
            raise DecisionQueueError("matching pending decision request is missing")
        request = _read_mapping(request_path)
        try:
            validate_contract("human_decision_request", request, mode="runtime")
        except ContractValidationError as exc:
            raise DecisionQueueError(str(exc)) from exc
        for field in ("decision_id", "project_id", "task_id"):
            if resolution[field] != request[field]:
                raise DecisionQueueError(f"resolution {field} does not match pending request")
        if resolution["resume_state"] != request["stage"]:
            raise DecisionQueueError("resolution resume_state does not match the approved target stage")
        option_ids = {item["id"] for item in request["options"]}
        if resolution["selected_option"] not in option_ids:
            raise DecisionQueueError("selected_option is not offered by the pending request")
        path = self.resolved_path(resolution["decision_id"])
        _write_once(path, resolution)
        return path

    def list_pending(self) -> list[dict[str, Any]]:
        pending_dir = self.root / "pending"
        if not pending_dir.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(pending_dir.glob("*.json"), key=lambda item: item.name):
            record = _read_mapping(path)
            decision_id = record.get("decision_id")
            if isinstance(decision_id, str) and not self.resolved_path(decision_id).exists():
                records.append(record)
        return records
