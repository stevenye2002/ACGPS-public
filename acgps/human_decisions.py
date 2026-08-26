from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from acgps.contracts import ContractValidationError, validate_contract
from acgps.workflow_store import WorkflowStore, WorkflowStoreError, safe_state_path


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
    def __init__(
        self,
        root: Path,
        *,
        workflow_store: WorkflowStore | None = None,
        create_root: bool = True,
    ):
        self.root = Path(root)
        self.workflow_store = workflow_store
        if create_root:
            self.root.mkdir(parents=True, exist_ok=True)

    def pending_path(self, decision_id: str) -> Path:
        return self._contained_path(f"pending/{decision_id}.json")

    def resolved_path(self, decision_id: str) -> Path:
        return self._contained_path(f"resolved/{decision_id}.json")

    def _contained_path(self, relative_path: str) -> Path:
        try:
            return safe_state_path(self.root, relative_path)
        except WorkflowStoreError as exc:
            raise DecisionQueueError(str(exc)) from exc

    @staticmethod
    def _validate_request(request: dict[str, Any]) -> None:
        try:
            validate_contract("human_decision_request", request, mode="runtime")
        except ContractValidationError as exc:
            raise DecisionQueueError(str(exc)) from exc
        if request["status"] != "PENDING":
            raise DecisionQueueError("pending decision request status must be PENDING")

    @staticmethod
    def _validate_resolution_against_request(
        resolution: dict[str, Any],
        request: dict[str, Any],
    ) -> None:
        try:
            validate_contract("human_decision_resolution", resolution, mode="runtime")
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

    def create(self, request: dict[str, Any]) -> Path:
        self._validate_request(request)
        path = self.pending_path(request["decision_id"])
        _write_once(path, request)
        return path

    def validate_resolution(self, resolution: dict[str, Any]) -> dict[str, Any]:
        try:
            validate_contract("human_decision_resolution", resolution, mode="runtime")
        except ContractValidationError as exc:
            raise DecisionQueueError(str(exc)) from exc
        request_path = self.pending_path(resolution["decision_id"])
        if not request_path.is_file():
            raise DecisionQueueError("matching pending decision request is missing")
        request = _read_mapping(request_path)
        self._validate_request(request)
        self._validate_resolution_against_request(resolution, request)
        return request

    def resolve(self, resolution: dict[str, Any]) -> Path:
        self.validate_resolution(resolution)
        path = self.resolved_path(resolution["decision_id"])
        _write_once(path, resolution)
        return path

    def _resolution_is_committed(self, resolution: dict[str, Any]) -> bool:
        if self.workflow_store is None:
            return True
        try:
            return self.workflow_store.has_committed_decision_resolution(resolution)
        except WorkflowStoreError as exc:
            raise DecisionQueueError(str(exc)) from exc

    def _require_authoritative_pending_match(self, records: list[dict[str, Any]]) -> None:
        if self.workflow_store is None:
            return
        try:
            waiting_decisions = self.workflow_store.read_waiting_human_decisions()
        except WorkflowStoreError as exc:
            raise DecisionQueueError(str(exc)) from exc
        pending_by_task = {record["task_id"]: record["decision_id"] for record in records}
        if len(pending_by_task) != len(records) or pending_by_task != waiting_decisions:
            raise DecisionQueueError("pending decision records do not match authoritative WAITING_HUMAN tasks")

    def list_pending(self) -> list[dict[str, Any]]:
        pending_dir = self._contained_path("pending")
        if not pending_dir.exists():
            self._require_authoritative_pending_match([])
            return []
        if not pending_dir.is_dir():
            raise DecisionQueueError("pending decision path must be a directory")
        records: list[dict[str, Any]] = []
        for path in sorted(pending_dir.glob("*.json"), key=lambda item: item.name):
            contained_path = self._contained_path(f"pending/{path.name}")
            if not contained_path.is_file():
                raise DecisionQueueError(f"pending decision record must be a file: {path.name}")
            request = _read_mapping(contained_path)
            self._validate_request(request)
            resolution_path = self.resolved_path(request["decision_id"])
            if resolution_path.exists():
                if not resolution_path.is_file():
                    raise DecisionQueueError(
                        f"resolved decision record must be a file: {resolution_path.name}"
                    )
                resolution = _read_mapping(resolution_path)
                self._validate_resolution_against_request(resolution, request)
                if self._resolution_is_committed(resolution):
                    continue
            records.append(request)
        self._require_authoritative_pending_match(records)
        return records
