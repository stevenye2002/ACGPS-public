from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path
from pathlib import PureWindowsPath
import re
import secrets
import tempfile
from datetime import datetime
from typing import Any

from acgps.workflow_contracts import (
    WorkflowIssue,
    canonical_json_bytes,
    validate_audit_event,
    validate_recovery_request,
    validate_recovery_result,
    validate_task_state,
    validate_task_initialization_request,
    validate_task_initialization_result,
    validate_transition_request,
    validate_transition_result,
)


SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
IDEMPOTENCY_RECORD_FIELDS = {
    "schema_version",
    "operation_kind",
    "operation_id",
    "task_id",
    "idempotency_key",
    "request_fingerprint",
    "result_fingerprint",
    "canonical_result",
    "transaction_path",
    "created_at_utc",
}
OPERATION_KINDS = {"INITIALIZATION", "TRANSITION", "RECOVERY", "ROLLBACK"}
LOCK_RECORD_FIELDS = {
    "schema_version",
    "task_id",
    "owner_id",
    "lock_instance_id",
    "process_id",
    "boot_session_id",
    "acquired_at_monotonic",
}
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
BOOT_SESSION_ID = secrets.token_hex(16)
_HELD_LOCK_PATHS: set[Path] = set()
_CONTROL_CONNECTION_BINDINGS: dict[int, tuple[str, tuple[object, ...]]] = {}
CONTROL_STORE_FILENAME = "control.sqlite3"
CONTROL_STORE_MARKER_FILENAME = ".control_store_authority.json"
CONTROL_STORE_APPLICATION_ID = 0x41434750
CONTROL_STORE_USER_VERSION = 1
CONTROL_STORE_AUTHORITY_DIGEST_VERSION = 2
MAX_SQLITE_JSON_BYTES = 262_144
MAX_SQLITE_JSON_DEPTH = 256


class WorkflowStoreError(RuntimeError):
    def __init__(self, issue: WorkflowIssue):
        super().__init__(f"{issue.code}: {issue.path}: {issue.message}")
        self.issue = issue


class WorkflowTaskLock:
    def __init__(
        self,
        path: Path,
        owner_id: str,
        lock_instance_id: str,
        lock_key: Path,
        db_path: Path,
        task_id: str,
        authority_id: str,
        root_binding: str,
        authority_digest: str,
    ):
        self.path = path
        self.owner_id = owner_id
        self.lock_instance_id = lock_instance_id
        self._lock_key = lock_key
        self._db_path = db_path
        self._task_id = task_id
        self._authority_id = authority_id
        self._root_binding = root_binding
        self._authority_digest = authority_digest
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        with _control_connection(
            self._db_path,
            expected_authority_id=self._authority_id,
            expected_root_binding=self._root_binding,
        ) as connection:
            try:
                previous_generation, previous_digest = _begin_authority_transaction(
                    connection,
                    self._db_path,
                    expected_authority_id=self._authority_id,
                    expected_root_binding=self._root_binding,
                )
                connection.execute(
                    "DELETE FROM task_locks WHERE task_id = ? AND lock_instance_id = ?",
                    (self._task_id, self.lock_instance_id),
                )
                self._authority_digest = _commit_authority_transaction(
                    connection,
                    self._db_path,
                    self._db_path.parent,
                    self._authority_id,
                    previous_generation,
                    previous_digest,
                )
            except Exception:
                _rollback_quietly(connection)
                raise
        _HELD_LOCK_PATHS.discard(self._lock_key)
        self._released = True

    def __enter__(self) -> WorkflowTaskLock:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.release()


def _raise(code: str, path: str, message: str) -> None:
    raise WorkflowStoreError(WorkflowIssue(code, path, message))


def _raise_outcome(outcome: object) -> None:
    issue = getattr(outcome, "issues", ())[0]
    raise WorkflowStoreError(issue)


def _require_safe_id(value: str, path: str) -> None:
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        _raise("WORKFLOW_INVALID_INPUT", path, "value must be a safe id")


def _require_mapping(record: object, path: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        _raise("WORKFLOW_INVALID_INPUT", path, "record must be a mapping")
    return record


def _canonical_sha(record: object) -> str:
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


def _operation_request_fingerprint(record: dict[str, Any]) -> str:
    return _canonical_sha({key: value for key, value in record.items() if not key.endswith("_at_utc")})


def _norm_path(path: Path) -> str:
    return os.path.normcase(str(path.resolve(strict=False)))


def _require_finite_float(value: object, path: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _raise("WORKFLOW_INVALID_INPUT", path, "value must be a finite number")
    number = float(value)
    if not math.isfinite(number):
        _raise("WORKFLOW_INVALID_INPUT", path, "value must be finite")
    if positive and number <= 0:
        _raise("WORKFLOW_INVALID_INPUT", path, "value must be positive")
    return number


def _validate_utc(value: object, path: str) -> None:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        _raise("WORKFLOW_INVALID_INPUT", path, "value must be a canonical RFC3339 UTC timestamp")
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        _raise("WORKFLOW_INVALID_INPUT", path, "value must be a valid canonical RFC3339 UTC timestamp")


def _validate_result_for_operation(data: dict[str, Any]) -> None:
    result = data["canonical_result"]
    operation_kind = data["operation_kind"]
    if operation_kind == "INITIALIZATION":
        outcome = validate_task_initialization_result(result)
        id_field = "initialization_id"
    elif operation_kind == "TRANSITION":
        outcome = validate_transition_result(result)
        id_field = "transition_id"
    else:
        outcome = validate_recovery_result(result)
        id_field = "recovery_id"
    if not outcome.valid:
        issue = outcome.issues[0]
        _raise("WORKFLOW_INVALID_INPUT", f"idempotency_record.canonical_result.{issue.path}", issue.message)
    if result.get(id_field) != data["operation_id"]:
        _raise("WORKFLOW_INVALID_INPUT", "idempotency_record.operation_id", "operation_id must match canonical result")
    if result.get("task_id") != data["task_id"]:
        _raise("WORKFLOW_INVALID_INPUT", "idempotency_record.task_id", "task_id must match canonical result")
    if data["result_fingerprint"] != _canonical_sha(result):
        _raise("WORKFLOW_INVALID_INPUT", "idempotency_record.result_fingerprint", "result fingerprint must match canonical result")


def _validate_transaction_path(data: dict[str, Any]) -> None:
    transaction_path = data["transaction_path"]
    safe_state_path(Path("."), transaction_path)
    operation_prefix = data["operation_kind"].lower()
    expected = f"state/transactions/{data['task_id']}/{operation_prefix}-{data['operation_id']}"
    if transaction_path != expected:
        _raise("WORKFLOW_INVALID_INPUT", "idempotency_record.transaction_path", "transaction path must bind task, operation kind, and operation id")


def _validate_canonical_request_for_operation(data: dict[str, Any], request: object) -> dict[str, Any]:
    request_data = _require_mapping(request, "canonical_request")
    operation_kind = data["operation_kind"]
    if operation_kind == "INITIALIZATION":
        outcome = validate_task_initialization_request(request_data)
        id_field = "initialization_id"
    elif operation_kind == "TRANSITION":
        outcome = validate_transition_request(request_data)
        id_field = "transition_id"
    else:
        outcome = validate_recovery_request(request_data)
        id_field = "recovery_id"
    if not outcome.valid:
        issue = outcome.issues[0]
        _raise("WORKFLOW_INVALID_INPUT", f"canonical_request.{issue.path}", issue.message)
    if request_data.get(id_field) != data["operation_id"]:
        _raise("WORKFLOW_INVALID_INPUT", "canonical_request", "canonical request id must match operation_id")
    if request_data.get("task_id") != data["task_id"]:
        _raise("WORKFLOW_INVALID_INPUT", "canonical_request.task_id", "canonical request task_id must match idempotency record")
    if request_data.get("idempotency_key") != data["idempotency_key"]:
        _raise("WORKFLOW_INVALID_INPUT", "canonical_request.idempotency_key", "canonical request idempotency_key must match idempotency record")
    if data["request_fingerprint"] != _operation_request_fingerprint(request_data):
        _raise("WORKFLOW_INVALID_INPUT", "idempotency_record.request_fingerprint", "request fingerprint must equal timestamp-free canonical request hash")
    return request_data


def _canonical_request_proof_path(state_root: Path, data: dict[str, Any]) -> Path:
    return safe_state_path(state_root, f"{data['transaction_path']}/canonical_request.json")


def _idempotency_identity(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if key != "created_at_utc"}


def _idempotency_key_digest(idempotency_key: str) -> str:
    return hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()


def _require_idempotency_record(record: object, *, canonical_request: object | None = None, state_root: Path | None = None) -> dict[str, Any]:
    data = _require_mapping(record, "idempotency_record")
    if set(data) != IDEMPOTENCY_RECORD_FIELDS:
        _raise("WORKFLOW_INVALID_INPUT", "idempotency_record", "idempotency record fields are invalid")
    if data["schema_version"] != 1:
        _raise("WORKFLOW_UNSUPPORTED_SCHEMA_VERSION", "idempotency_record.schema_version", "unsupported idempotency schema")
    if data["operation_kind"] not in OPERATION_KINDS:
        _raise("WORKFLOW_INVALID_INPUT", "idempotency_record.operation_kind", "unknown operation kind")
    for field in ("operation_id", "task_id"):
        _require_safe_id(data[field], f"idempotency_record.{field}")
    if not isinstance(data["idempotency_key"], str) or not data["idempotency_key"]:
        _raise("WORKFLOW_INVALID_INPUT", "idempotency_record.idempotency_key", "idempotency key must be non-empty")
    for field in ("request_fingerprint", "result_fingerprint"):
        if not isinstance(data[field], str) or not re.fullmatch(r"[0-9a-f]{64}", data[field]):
            _raise("WORKFLOW_INVALID_INPUT", f"idempotency_record.{field}", "fingerprint must be a SHA-256 hex digest")
    if not isinstance(data["canonical_result"], dict):
        _raise("WORKFLOW_INVALID_INPUT", "idempotency_record.canonical_result", "canonical result must be a mapping")
    _validate_transaction_path(data)
    _validate_result_for_operation(data)
    if canonical_request is not None:
        _validate_canonical_request_for_operation(data, canonical_request)
    elif state_root is not None:
        proof_path = _canonical_request_proof_path(state_root, data)
        try:
            proof = _read_json_mapping(proof_path, code="WORKFLOW_INVALID_INPUT", issue_path="canonical_request")
        except FileNotFoundError:
            _raise("WORKFLOW_INVALID_INPUT", "idempotency_record.request_fingerprint", "canonical request proof is required")
        _validate_canonical_request_for_operation(data, proof)
    else:
        _raise("WORKFLOW_INVALID_INPUT", "idempotency_record.request_fingerprint", "canonical request proof is required")
    _validate_utc(data["created_at_utc"], "idempotency_record.created_at_utc")
    return data


def _read_json_mapping(path: Path, *, code: str, issue_path: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise
    except UnicodeDecodeError as exc:
        _raise(code, issue_path, f"record is not valid UTF-8: {exc.reason}")
    except json.JSONDecodeError as exc:
        _raise(code, issue_path, f"malformed JSON: {exc.msg}")
    except OSError as exc:
        _raise(code, issue_path, f"record could not be read: {exc}")
    if not isinstance(payload, dict):
        _raise(code, issue_path, "record must be a mapping")
    return payload


def _loads_json_mapping(text: str, *, code: str, issue_path: str) -> dict[str, Any]:
    if not isinstance(text, str):
        _raise(code, issue_path, "record must be stored as SQLite TEXT")
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        _raise(code, issue_path, f"record is not valid UTF-8: {exc.reason}")
    if size > MAX_SQLITE_JSON_BYTES:
        _raise(code, issue_path, "record JSON exceeds maximum SQLite JSON size")
    if _json_nesting_depth(text) > MAX_SQLITE_JSON_DEPTH:
        _raise(code, issue_path, "record JSON exceeds maximum SQLite JSON depth")
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError, ValueError, RecursionError, MemoryError) as exc:
        detail = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
        _raise(code, issue_path, f"malformed JSON: {detail}")
    if not isinstance(payload, dict):
        _raise(code, issue_path, "record must be a mapping")
    return payload


def _validate_sqlite_json_text(text: str, *, code: str, issue_path: str) -> None:
    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError as exc:
        _raise(code, issue_path, f"record is not valid UTF-8: {exc.reason}")
    if size > MAX_SQLITE_JSON_BYTES:
        _raise(code, issue_path, "record JSON exceeds maximum SQLite JSON size")
    if _json_nesting_depth(text) > MAX_SQLITE_JSON_DEPTH:
        _raise(code, issue_path, "record JSON exceeds maximum SQLite JSON depth")


def _sqlite_json_text(record: object, *, code: str, issue_path: str) -> str:
    text = canonical_json_bytes(record).decode("utf-8")
    _validate_sqlite_json_text(text, code=code, issue_path=issue_path)
    return text


def _json_nesting_depth(text: str) -> int:
    depth = 0
    maximum = 0
    in_string = False
    escaped = False
    for char in text:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in "[{":
            depth += 1
            maximum = max(maximum, depth)
        elif char in "]}":
            depth = max(0, depth - 1)
    return maximum


def _read_lock_record(path: Path) -> dict[str, Any]:
    payload = _read_json_mapping(path, code="WORKFLOW_CONCURRENT_WRITE", issue_path="lock")
    if set(payload) != LOCK_RECORD_FIELDS:
        _raise("WORKFLOW_CONCURRENT_WRITE", "lock", "lock record fields are invalid")
    if payload["schema_version"] != 1:
        _raise("WORKFLOW_CONCURRENT_WRITE", "lock.schema_version", "unsupported lock schema")
    _require_safe_id(payload["task_id"], "lock.task_id")
    _require_safe_id(payload["owner_id"], "lock.owner_id")
    if not isinstance(payload["lock_instance_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", payload["lock_instance_id"]):
        _raise("WORKFLOW_CONCURRENT_WRITE", "lock.lock_instance_id", "lock instance id is invalid")
    if isinstance(payload["process_id"], bool) or not isinstance(payload["process_id"], int) or payload["process_id"] < 0:
        _raise("WORKFLOW_CONCURRENT_WRITE", "lock.process_id", "process_id is invalid")
    if not isinstance(payload["boot_session_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", payload["boot_session_id"]):
        _raise("WORKFLOW_CONCURRENT_WRITE", "lock.boot_session_id", "boot session id is invalid")
    _require_finite_float(payload["acquired_at_monotonic"], "lock.acquired_at_monotonic")
    return payload


def _read_idempotency_file(path: Path, *, state_root: Path | None = None) -> dict[str, Any]:
    payload = _read_json_mapping(path, code="WORKFLOW_IDEMPOTENCY_CONFLICT", issue_path="idempotency_record")
    try:
        return _require_idempotency_record(payload, state_root=state_root)
    except WorkflowStoreError as exc:
        raise WorkflowStoreError(WorkflowIssue("WORKFLOW_IDEMPOTENCY_CONFLICT", exc.issue.path, exc.issue.message)) from exc


def _validated_idempotency_row(
    row: tuple[Any, ...],
    *,
    task_id: str,
    operation_kind: str,
    idempotency_key: str,
) -> dict[str, Any]:
    try:
        identity = _loads_json_mapping(row[0], code="WORKFLOW_IDEMPOTENCY_CONFLICT", issue_path="idempotency_record.identity")
        record = _loads_json_mapping(row[1], code="WORKFLOW_IDEMPOTENCY_CONFLICT", issue_path="idempotency_record")
        canonical_request = _loads_json_mapping(row[2], code="WORKFLOW_IDEMPOTENCY_CONFLICT", issue_path="canonical_request")
    except WorkflowStoreError:
        raise
    stored_key = row[3]
    if stored_key != idempotency_key:
        _raise("WORKFLOW_IDEMPOTENCY_CONFLICT", "idempotency_record.idempotency_key", "stored key must match requested key")
    try:
        data = _require_idempotency_record(record, canonical_request=canonical_request)
    except WorkflowStoreError as exc:
        raise WorkflowStoreError(WorkflowIssue("WORKFLOW_IDEMPOTENCY_CONFLICT", exc.issue.path, exc.issue.message)) from exc
    if data["task_id"] != task_id or data["operation_kind"] != operation_kind or data["idempotency_key"] != idempotency_key:
        _raise("WORKFLOW_IDEMPOTENCY_CONFLICT", "idempotency_record", "idempotency record does not match requested identity")
    if identity != _idempotency_identity(data):
        _raise("WORKFLOW_IDEMPOTENCY_CONFLICT", "idempotency_record.identity", "stored identity must match canonical record identity")
    return data


def _reject_symlink_ancestors(path: Path) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink():
            _raise("WORKFLOW_INVALID_INPUT", "path", "path contains a symlink component")


def _fd_resolved_path(fd: int) -> Path | None:
    if os.name == "nt":
        import ctypes
        import msvcrt

        handle = msvcrt.get_osfhandle(fd)
        buffer = ctypes.create_unicode_buffer(32768)
        result = ctypes.windll.kernel32.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if result == 0 or result >= len(buffer):
            return None
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return Path(value)
    proc_path = Path(f"/proc/self/fd/{fd}")
    if proc_path.exists():
        return Path(os.readlink(proc_path))
    return None


def _close_untrusted_fd(fd: int, actual_path: Path | None) -> None:
    try:
        try:
            stat = os.fstat(fd)
        except OSError:
            stat = None
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    if actual_path is not None and stat is not None and stat.st_size == 0 and getattr(stat, "st_nlink", 1) == 1:
        try:
            actual_path.unlink()
        except OSError:
            pass


def _verify_fd_matches_path(fd: int, intended_path: Path, *, expected_path: Path | None = None) -> None:
    actual_path = _fd_resolved_path(fd)
    expected = expected_path if expected_path is not None else intended_path
    if actual_path is None or _norm_path(actual_path) != _norm_path(expected):
        _close_untrusted_fd(fd, actual_path)
        _raise("WORKFLOW_INVALID_INPUT", "path", "opened file descriptor does not match the verified state path")


def _open_contained(path: Path, flags: int, mode: int = 0o600) -> int:
    _reject_symlink_ancestors(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_ancestors(path)
    expected_path = path.resolve(strict=False)
    fd = os.open(path, flags | getattr(os, "O_BINARY", 0), mode)
    try:
        _verify_fd_matches_path(fd, path, expected_path=expected_path)
    except Exception:
        raise
    return fd


def _write_bytes_contained(path: Path, payload: bytes, *, exclusive: bool = False) -> None:
    flags = os.O_WRONLY | os.O_CREAT
    if exclusive:
        flags |= os.O_EXCL
    fd = _open_contained(path, flags)
    try:
        try:
            _reject_symlink_ancestors(path)
        except Exception:
            _close_untrusted_fd(fd, _fd_resolved_path(fd))
            raise
        with os.fdopen(fd, "wb") as handle:
            if not exclusive:
                handle.truncate()
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        raise


def _write_bytes_contained_atomic(path: Path, payload: bytes) -> None:
    _reject_symlink_ancestors(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_ancestors(path)
    temp_path = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        _write_bytes_contained(temp_path, payload, exclusive=True)
        _reject_symlink_ancestors(path)
        os.replace(temp_path, path)
        if os.name != "nt":
            dir_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def _write_json_export_once_or_same(path: Path, payload: bytes, *, code: str, issue_path: str) -> None:
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            _raise(code, issue_path, f"existing export could not be read: {exc}")
        if existing != payload:
            _raise(code, issue_path, "existing export has different bytes")
        return
    try:
        _write_bytes_contained_atomic(path, payload)
    except OSError as exc:
        _raise(code, issue_path, f"export could not be published: {exc}")


def _reject_json_export_conflict(path: Path, payload: bytes, *, code: str, issue_path: str) -> None:
    if not path.exists():
        return
    try:
        existing = path.read_bytes()
    except OSError as exc:
        _raise(code, issue_path, f"existing export could not be read: {exc}")
    if existing != payload:
        _raise(code, issue_path, "existing export has different bytes")


def _acquire_os_file_lock(handle: object) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        _raise("WORKFLOW_CONCURRENT_WRITE", "lock", f"lock already held: {exc}")


def _release_os_file_lock(handle: object) -> None:
    if sys.platform == "win32":
        import msvcrt

        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def safe_state_path(root: Path, relative_path: str) -> Path:
    if not isinstance(relative_path, str) or not relative_path:
        _raise("WORKFLOW_INVALID_INPUT", "path", "path must be a non-empty relative POSIX string")
    if "\\" in relative_path:
        _raise("WORKFLOW_INVALID_INPUT", "path", "path must use POSIX separators")
    if PureWindowsPath(relative_path).drive or re.match(r"^[A-Za-z]:", relative_path):
        _raise("WORKFLOW_INVALID_INPUT", "path", "Windows drive prefixes are not allowed")
    relative = Path(relative_path)
    if relative.is_absolute():
        _raise("WORKFLOW_INVALID_INPUT", "path", "absolute paths are not allowed")
    parts = relative_path.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        _raise("WORKFLOW_INVALID_INPUT", "path", "path must not contain empty, current, or parent segments")

    root_resolved = root.resolve()
    candidate = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            _raise("WORKFLOW_INVALID_INPUT", "path", "path contains a symlink component")
        if current.exists():
            resolved = current.resolve()
            if resolved != root_resolved and root_resolved not in resolved.parents:
                _raise("WORKFLOW_INVALID_INPUT", "path", "path escapes the state root")
    return candidate


def write_state_atomic(path: Path, record: dict[str, Any]) -> None:
    _require_mapping(record, "record")
    payload = canonical_json_bytes(record) + b"\n"
    _write_bytes_contained_atomic(path, payload)


def _control_marker_path(path: Path) -> Path:
    return path.with_name(CONTROL_STORE_MARKER_FILENAME)


def _root_binding(state_root: Path) -> str:
    return hashlib.sha256(_norm_path(state_root).encode("utf-8")).hexdigest()


def _authority_digest_value(value: object) -> dict[str, object]:
    if isinstance(value, bytes):
        return {"storage_class": "blob", "sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    if value is None:
        return {"storage_class": "null", "value": None}
    if isinstance(value, str):
        return {"storage_class": "text", "value": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"storage_class": "integer", "value": value}
    if isinstance(value, float) and math.isfinite(value):
        return {"storage_class": "real", "value": value}
    return {"storage_class": type(value).__name__, "repr_sha256": hashlib.sha256(repr(value).encode("utf-8")).hexdigest()}


def _connection_file_binding(path: Path) -> tuple[object, ...]:
    stat = path.stat()
    return (
        _norm_path(path),
        getattr(stat, "st_dev", None),
        getattr(stat, "st_ino", None),
    )


def _control_store_authority_generation(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT authority_generation FROM control_authority WHERE singleton = 1").fetchone()
    if row is None or not isinstance(row[0], int) or isinstance(row[0], bool) or row[0] < 0:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.authority_generation", "authority generation is invalid")
    return row[0]


def _control_store_authority_digest(connection: sqlite3.Connection) -> str:
    tables: list[dict[str, object]] = []
    table_specs = (
        ("control_authority", ("singleton", "authority_id", "root_binding", "application_id", "user_version", "authority_generation"), "singleton"),
        ("task_locks", ("task_id", "owner_id", "lock_instance_id", "lock_record_json"), "task_id"),
    )
    for table, columns, order_by in table_specs:
        rows = connection.execute(
            f"SELECT {', '.join(columns)} FROM {table} ORDER BY {order_by}"
        ).fetchall()
        tables.append(
            {
                "table": table,
                "columns": list(columns),
                "rows": [[_authority_digest_value(value) for value in row] for row in rows],
            }
        )
    return _canonical_sha({"schema_version": CONTROL_STORE_AUTHORITY_DIGEST_VERSION, "tables": tables})


def _authority_marker(state_root: Path, authority_id: str, authority_generation: int, control_store_authority_digest: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "authority_id": authority_id,
        "root_binding": _root_binding(state_root),
        "control_store_filename": CONTROL_STORE_FILENAME,
        "application_id": CONTROL_STORE_APPLICATION_ID,
        "user_version": CONTROL_STORE_USER_VERSION,
        "export_artifacts_authoritative": False,
        "authority_digest_version": CONTROL_STORE_AUTHORITY_DIGEST_VERSION,
        "authority_generation": authority_generation,
        "control_store_authority_digest": control_store_authority_digest,
    }


def _read_authority_marker(path: Path, state_root: Path) -> dict[str, Any] | None:
    marker_path = _control_marker_path(path)
    if not marker_path.exists():
        return None
    marker = _read_json_mapping(marker_path, code="WORKFLOW_STATE_CORRUPT", issue_path="control_store_authority")
    expected_keys = {
        "schema_version",
        "authority_id",
        "root_binding",
        "control_store_filename",
        "application_id",
        "user_version",
        "export_artifacts_authoritative",
        "authority_digest_version",
        "authority_generation",
        "control_store_authority_digest",
    }
    if set(marker) != expected_keys:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority", "control-store authority marker fields are invalid")
    if marker["schema_version"] != 1:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.schema_version", "unsupported control-store authority marker")
    if not isinstance(marker["authority_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", marker["authority_id"]):
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.authority_id", "authority id is invalid")
    if marker["root_binding"] != _root_binding(state_root):
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.root_binding", "authority marker is bound to a different state root")
    if marker["control_store_filename"] != CONTROL_STORE_FILENAME:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.control_store_filename", "unexpected control-store filename")
    if marker["application_id"] != CONTROL_STORE_APPLICATION_ID or marker["user_version"] != CONTROL_STORE_USER_VERSION:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority", "control-store version metadata mismatch")
    if marker["export_artifacts_authoritative"] is not False:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.export_artifacts_authoritative", "exports must not be runtime authority")
    if marker["authority_digest_version"] != CONTROL_STORE_AUTHORITY_DIGEST_VERSION:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.authority_digest_version", "unsupported authority digest version")
    if not isinstance(marker["authority_generation"], int) or isinstance(marker["authority_generation"], bool) or marker["authority_generation"] < 0:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.authority_generation", "authority generation is invalid")
    if not isinstance(marker["control_store_authority_digest"], str) or not re.fullmatch(r"[0-9a-f]{64}", marker["control_store_authority_digest"]):
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.control_store_authority_digest", "authority digest is invalid")
    return marker


def _write_authority_marker(
    path: Path,
    state_root: Path,
    authority_id: str,
    authority_generation: int,
    control_store_authority_digest: str,
    *,
    expected_previous_digest: str | None = None,
    expected_previous_generation: int | None = None,
) -> None:
    if expected_previous_digest is not None:
        current = _read_authority_marker(path, state_root)
        if current is None:
            _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority", "control-store authority marker is missing")
        current_digest = current["control_store_authority_digest"]
        current_generation = current["authority_generation"]
        if current_digest != expected_previous_digest or (
            expected_previous_generation is not None and current_generation != expected_previous_generation
        ):
            _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority", "stale authority marker publication rejected")
    payload = canonical_json_bytes(_authority_marker(state_root, authority_id, authority_generation, control_store_authority_digest)) + b"\n"
    _write_bytes_contained_atomic(_control_marker_path(path), payload)


def _refresh_authority_marker(
    path: Path,
    state_root: Path,
    authority_id: str,
    *,
    expected_previous_digest: str | None = None,
) -> str:
    try:
        connection = _connect_control_store(path)
        try:
            _validate_control_store_connection(
                connection,
                expected_authority_id=authority_id,
                expected_root_binding=_root_binding(state_root),
            )
            generation = _control_store_authority_generation(connection)
            digest = _control_store_authority_digest(connection)
        finally:
            connection.close()
    except sqlite3.Error as exc:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store", f"control-store authority marker refresh failed: {exc}")
    _write_authority_marker(path, state_root, authority_id, generation, digest, expected_previous_digest=expected_previous_digest)
    return digest


def _require_control_store_path(path: Path) -> None:
    if path.is_symlink():
        _raise("WORKFLOW_STATE_CORRUPT", "control_store", "control store must not be a symlink")
    _reject_symlink_ancestors(path)


def _connect_control_store(path: Path) -> sqlite3.Connection:
    _require_control_store_path(path)
    connection = sqlite3.connect(str(path), timeout=30.0, isolation_level=None)
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    _CONTROL_CONNECTION_BINDINGS[id(connection)] = (_norm_path(path), _connection_file_binding(path))
    return connection


def _connection_database_path(connection: sqlite3.Connection) -> Path:
    row = connection.execute("PRAGMA database_list").fetchone()
    if row is None or len(row) < 3 or not row[2]:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store", "control-store database path is unavailable")
    return Path(str(row[2]))


def _require_connection_bound_to_path(connection: sqlite3.Connection, path: Path) -> None:
    if _norm_path(_connection_database_path(connection)) != _norm_path(path):
        _raise("WORKFLOW_STATE_CORRUPT", "control_store", "control-store connection is detached from the authoritative path")
    bound = _CONTROL_CONNECTION_BINDINGS.get(id(connection))
    if bound is not None:
        bound_path, bound_identity = bound
        if bound_path != _norm_path(path) or bound_identity != _connection_file_binding(path):
            _raise("WORKFLOW_STATE_CORRUPT", "control_store", "control-store file identity changed during authority operation")


def _rollback_quietly(connection: sqlite3.Connection) -> None:
    try:
        connection.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _reconcile_authority_marker(
    connection: sqlite3.Connection,
    path: Path,
    state_root: Path,
    marker: dict[str, Any],
) -> tuple[int, str]:
    _validate_control_store_connection(
        connection,
        expected_authority_id=marker["authority_id"],
        expected_root_binding=marker["root_binding"],
    )
    actual_generation = _control_store_authority_generation(connection)
    actual_digest = _control_store_authority_digest(connection)
    marker_generation = marker["authority_generation"]
    marker_digest = marker["control_store_authority_digest"]
    if actual_generation == marker_generation and actual_digest == marker_digest:
        return actual_generation, actual_digest
    if actual_generation > marker_generation:
        try:
            _write_authority_marker(path, state_root, marker["authority_id"], actual_generation, actual_digest)
        except (WorkflowStoreError, OSError):
            pass
        return actual_generation, actual_digest
    _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority", "control-store authority marker is not recoverable")


def _begin_authority_transaction(
    connection: sqlite3.Connection,
    path: Path,
    *,
    expected_authority_id: str,
    expected_root_binding: str,
) -> tuple[int, str]:
    connection.execute("BEGIN IMMEDIATE")
    _require_connection_bound_to_path(connection, path)
    marker = _read_authority_marker(path, path.parent)
    if marker is None:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority", "control-store authority marker is missing")
    if marker["authority_id"] != expected_authority_id:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.authority_id", "authority marker identity mismatch")
    if marker["root_binding"] != expected_root_binding:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.root_binding", "authority marker root binding mismatch")
    generation, digest = _reconcile_authority_marker(connection, path, path.parent, marker)
    return generation, digest


def _commit_authority_transaction(
    connection: sqlite3.Connection,
    path: Path,
    state_root: Path,
    authority_id: str,
    previous_generation: int,
    previous_digest: str,
) -> str:
    _require_connection_bound_to_path(connection, path)
    connection.execute("UPDATE control_authority SET authority_generation = authority_generation + 1 WHERE singleton = 1")
    new_generation = _control_store_authority_generation(connection)
    new_digest = _control_store_authority_digest(connection)
    if new_generation != previous_generation + 1:
        _rollback_quietly(connection)
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.authority_generation", "authority generation did not advance by one")
    _require_connection_bound_to_path(connection, path)
    connection.execute("COMMIT")
    current_connection = _connect_control_store(path)
    try:
        _validate_control_store_connection(
            current_connection,
            expected_authority_id=authority_id,
            expected_root_binding=_root_binding(state_root),
        )
        current_generation = _control_store_authority_generation(current_connection)
        current_digest = _control_store_authority_digest(current_connection)
        if current_generation != new_generation or current_digest != new_digest:
            _raise("WORKFLOW_STATE_CORRUPT", "control_store", "authority commit did not land in the current control store")
    finally:
        _CONTROL_CONNECTION_BINDINGS.pop(id(current_connection), None)
        current_connection.close()
    try:
        _write_authority_marker(
            path,
            state_root,
            authority_id,
            new_generation,
            new_digest,
            expected_previous_digest=previous_digest,
            expected_previous_generation=previous_generation,
        )
    except (WorkflowStoreError, OSError):
        pass
    return new_digest


@contextmanager
def _control_connection(
    path: Path,
    *,
    expected_authority_id: str | None = None,
    expected_root_binding: str | None = None,
):
    if not path.exists():
        _raise("WORKFLOW_STATE_CORRUPT", "control_store", "control store is missing")
    connection = None
    try:
        marker = _read_authority_marker(path, path.parent)
        if marker is None:
            _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority", "control-store authority marker is missing")
        if expected_authority_id is not None and marker["authority_id"] != expected_authority_id:
            _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.authority_id", "authority marker identity mismatch")
        if expected_root_binding is not None and marker["root_binding"] != expected_root_binding:
            _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.root_binding", "authority marker root binding mismatch")
        connection = _connect_control_store(path)
        _reconcile_authority_marker(connection, path, path.parent, marker)
        yield connection
    except sqlite3.Error as exc:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store", f"control store failure: {exc}")
    finally:
        if connection is not None:
            _CONTROL_CONNECTION_BINDINGS.pop(id(connection), None)
            connection.close()


def _validate_control_store_connection(
    connection: sqlite3.Connection,
    *,
    expected_authority_id: str | None = None,
    expected_root_binding: str | None = None,
    expected_authority_digest: str | None = None,
) -> str:
    application_id = connection.execute("PRAGMA application_id").fetchone()[0]
    user_version = connection.execute("PRAGMA user_version").fetchone()[0]
    if application_id != CONTROL_STORE_APPLICATION_ID or user_version != CONTROL_STORE_USER_VERSION:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store", "control-store SQLite metadata mismatch")
    integrity = connection.execute("PRAGMA quick_check").fetchone()[0]
    if integrity != "ok":
        _raise("WORKFLOW_STATE_CORRUPT", "control_store", "control-store integrity check failed")
    row = connection.execute(
        "SELECT authority_id, root_binding, application_id, user_version, authority_generation FROM control_authority WHERE singleton = 1"
    ).fetchone()
    if row is None:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store", "control-store authority row is missing")
    authority_id, root_hash, app_id, version, generation = row
    if app_id != CONTROL_STORE_APPLICATION_ID or version != CONTROL_STORE_USER_VERSION:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store", "control-store authority row version mismatch")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 0:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority.authority_generation", "authority generation is invalid")
    if expected_root_binding is not None and root_hash != expected_root_binding:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store", "control-store root binding mismatch")
    if expected_authority_id is not None and authority_id != expected_authority_id:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store", "control-store authority identity mismatch")
    if expected_authority_digest is not None:
        actual_digest = _control_store_authority_digest(connection)
        if actual_digest != expected_authority_digest:
            _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority", "control-store authority incarnation mismatch")
    return str(authority_id)


def _state_root_is_fresh_for_initialization(state_root: Path) -> bool:
    return not any(state_root.iterdir())


def _initialize_control_store(path: Path, state_root: Path) -> tuple[str, str]:
    path.parent.mkdir(parents=True, exist_ok=True)
    _require_control_store_path(path)
    marker = _read_authority_marker(path, state_root)
    if not path.exists():
        if marker is not None:
            _raise("WORKFLOW_STATE_CORRUPT", "control_store", "control store is missing for initialized state root")
        if not _state_root_is_fresh_for_initialization(state_root):
            _raise("WORKFLOW_STATE_CORRUPT", "control_store", "explicit initialization or recovery is required for a non-fresh state root")
        authority_id = secrets.token_hex(16)
        digest = ""
        try:
            connection = _connect_control_store(path)
            try:
                connection.execute(f"PRAGMA application_id = {CONTROL_STORE_APPLICATION_ID}")
                connection.execute(f"PRAGMA user_version = {CONTROL_STORE_USER_VERSION}")
                _create_control_store_schema(connection)
                connection.execute(
                    """
                    INSERT INTO control_authority(singleton, authority_id, root_binding, application_id, user_version, authority_generation)
                    VALUES (1, ?, ?, ?, ?, 0)
                    """,
                    (authority_id, _root_binding(state_root), CONTROL_STORE_APPLICATION_ID, CONTROL_STORE_USER_VERSION),
                )
                generation = _control_store_authority_generation(connection)
                digest = _control_store_authority_digest(connection)
            finally:
                connection.close()
        except sqlite3.Error as exc:
            _raise("WORKFLOW_STATE_CORRUPT", "control_store", f"control store initialization failed: {exc}")
        _write_authority_marker(path, state_root, authority_id, generation, digest)
        return authority_id, digest
    if marker is None:
        _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority", "existing control store requires explicit versioned migration")
    with _control_connection(
        path,
        expected_authority_id=marker["authority_id"],
        expected_root_binding=marker["root_binding"],
    ) as connection:
        authority_id = _validate_control_store_connection(
            connection,
            expected_authority_id=marker["authority_id"],
            expected_root_binding=marker["root_binding"],
        )
        digest = _control_store_authority_digest(connection)
    return authority_id, digest


def _create_control_store_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS control_authority (
            singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
            authority_id TEXT NOT NULL UNIQUE,
            root_binding TEXT NOT NULL,
            application_id INTEGER NOT NULL,
            user_version INTEGER NOT NULL,
            authority_generation INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS task_states (
            task_id TEXT PRIMARY KEY,
            state_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS audit_events (
            task_id TEXT NOT NULL,
            generation INTEGER NOT NULL,
            sequence INTEGER NOT NULL,
            event_json TEXT NOT NULL,
            PRIMARY KEY (task_id, generation, sequence)
        );
        CREATE TABLE IF NOT EXISTS task_locks (
            task_id TEXT PRIMARY KEY,
            owner_id TEXT NOT NULL,
            lock_instance_id TEXT NOT NULL,
            lock_record_json TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS idempotency_records (
            task_id TEXT NOT NULL,
            operation_kind TEXT NOT NULL,
            idempotency_key_sha256 TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            identity_json TEXT NOT NULL,
            record_json TEXT NOT NULL,
            canonical_request_json TEXT NOT NULL,
            PRIMARY KEY (task_id, operation_kind, idempotency_key_sha256)
        );
        """
    )


class WorkflowStore:
    def __init__(self, state_root: Path):
        self.state_root = state_root
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.control_store_path = self.state_root / CONTROL_STORE_FILENAME
        self.control_authority_id, self.control_store_authority_digest = _initialize_control_store(self.control_store_path, self.state_root)
        self.control_root_binding = _root_binding(self.state_root)

    @contextmanager
    def _connection(self):
        with _control_connection(
            self.control_store_path,
            expected_authority_id=self.control_authority_id,
            expected_root_binding=self.control_root_binding,
        ) as connection:
            yield connection

    def state_path(self, task_id: str) -> Path:
        _require_safe_id(task_id, "task_id")
        return safe_state_path(self.state_root, f"tasks/{task_id}/state.json")

    def audit_path(self, task_id: str, *, generation: int = 1) -> Path:
        _require_safe_id(task_id, "task_id")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            _raise("WORKFLOW_INVALID_INPUT", "generation", "generation must be a positive integer")
        return safe_state_path(self.state_root, f"audit/{task_id}/generation-{generation:06d}.jsonl")

    def lock_path(self, task_id: str) -> Path:
        _require_safe_id(task_id, "task_id")
        return safe_state_path(self.state_root, f"locks/{task_id}.lock.json")

    def operation_idempotency_path(self, task_id: str, operation_kind: str, idempotency_key: str) -> Path:
        _require_safe_id(task_id, "task_id")
        if operation_kind not in OPERATION_KINDS:
            _raise("WORKFLOW_INVALID_INPUT", "operation_kind", "unknown operation kind")
        if not isinstance(idempotency_key, str) or not idempotency_key:
            _raise("WORKFLOW_INVALID_INPUT", "idempotency_key", "idempotency key must be non-empty")
        digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
        return safe_state_path(self.state_root, f"idempotency/{task_id}/{operation_kind}/{digest}.json")

    def write_task_state(self, state: dict[str, Any]) -> None:
        outcome = validate_task_state(state)
        if not outcome.valid:
            _raise_outcome(outcome)
        payload = _sqlite_json_text(state, code="WORKFLOW_INVALID_INPUT", issue_path="task_state")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT INTO task_states(task_id, state_json)
                VALUES (?, ?)
                ON CONFLICT(task_id) DO UPDATE SET state_json = excluded.state_json
                """,
                (state["task_id"], payload),
            )
            connection.execute("COMMIT")
        write_state_atomic(self.state_path(state["task_id"]), state)

    def read_task_state(self, task_id: str) -> dict[str, Any]:
        _require_safe_id(task_id, "task_id")
        with self._connection() as connection:
            row = connection.execute(
                "SELECT state_json FROM task_states WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            _raise("WORKFLOW_STATE_CORRUPT", "task_state", "authoritative task-state row is missing")
        payload = _loads_json_mapping(row[0], code="WORKFLOW_STATE_CORRUPT", issue_path="task_state")
        outcome = validate_task_state(payload)
        if not outcome.valid:
            _raise_outcome(outcome)
        if payload.get("task_id") != task_id:
            _raise("WORKFLOW_STATE_CORRUPT", "task_state.task_id", "task-state payload must match requested task_id")
        return payload

    def read_audit_events(self, task_id: str, *, generation: int = 1) -> list[dict[str, Any]]:
        _require_safe_id(task_id, "task_id")
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            _raise("WORKFLOW_INVALID_INPUT", "generation", "generation must be a positive integer")
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT sequence, event_json
                FROM audit_events
                WHERE task_id = ? AND generation = ?
                ORDER BY sequence
                """,
                (task_id, generation),
            ).fetchall()
        events: list[dict[str, Any]] = []
        for expected_sequence, row in enumerate(rows, start=1):
            if row[0] != expected_sequence:
                _raise("WORKFLOW_AUDIT_CORRUPT", "sequence", "authoritative audit sequence is not contiguous")
            event = _loads_json_mapping(row[1], code="WORKFLOW_AUDIT_CORRUPT", issue_path="audit_event")
            outcome = validate_audit_event(event)
            if not outcome.valid:
                _raise_outcome(outcome)
            if event["task_id"] != task_id or event["generation"] != generation or event["sequence"] != row[0]:
                _raise("WORKFLOW_AUDIT_CORRUPT", "audit_event", "audit row key does not match event payload")
            events.append(event)
        return events

    def append_audit_event(self, event: dict[str, Any]) -> None:
        outcome = validate_audit_event(event)
        if not outcome.valid:
            _raise_outcome(outcome)
        path = self.audit_path(event["task_id"], generation=event["generation"])
        event_json = _sqlite_json_text(event, code="WORKFLOW_AUDIT_CORRUPT", issue_path="audit_event")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                """
                SELECT event_json
                FROM audit_events
                WHERE task_id = ? AND generation = ? AND sequence = ?
                """,
                (event["task_id"], event["generation"], event["sequence"]),
            ).fetchone()
            if existing is not None:
                connection.execute("ROLLBACK")
                _raise("WORKFLOW_AUDIT_CORRUPT", "audit_event", "audit event sequence already exists")
            try:
                connection.execute(
                    """
                    INSERT INTO audit_events(task_id, generation, sequence, event_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (event["task_id"], event["generation"], event["sequence"], event_json),
                )
            except sqlite3.IntegrityError as exc:
                connection.execute("ROLLBACK")
                _raise("WORKFLOW_AUDIT_CORRUPT", "audit_event", f"audit event sequence already exists: {exc}")
            connection.execute("COMMIT")
        self._ensure_audit_export_line(path, event_json)

    def commit_task_state_and_audit(
        self,
        event: dict[str, Any],
        state: dict[str, Any],
    ) -> bool:
        """Commit one validated audit event and its resulting state atomically.

        SQLite rows are authoritative. JSON and JSONL files are reconciled
        exports, including after an exact idempotent replay.
        """
        event_outcome = validate_audit_event(event)
        if not event_outcome.valid:
            _raise_outcome(event_outcome)
        state_outcome = validate_task_state(state)
        if not state_outcome.valid:
            _raise_outcome(state_outcome)
        self._validate_state_event_pair(event, state)

        event_json = _sqlite_json_text(event, code="WORKFLOW_AUDIT_CORRUPT", issue_path="audit_event")
        state_json = _sqlite_json_text(state, code="WORKFLOW_STATE_CORRUPT", issue_path="task_state")
        committed = True
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing_event = connection.execute(
                    """
                    SELECT event_json
                    FROM audit_events
                    WHERE task_id = ? AND generation = ? AND sequence = ?
                    """,
                    (event["task_id"], event["generation"], event["sequence"]),
                ).fetchone()
                existing_state = connection.execute(
                    "SELECT state_json FROM task_states WHERE task_id = ?",
                    (state["task_id"],),
                ).fetchone()

                if existing_event is not None:
                    if existing_event[0] != event_json or existing_state is None or existing_state[0] != state_json:
                        _raise(
                            "WORKFLOW_AUDIT_CORRUPT",
                            "audit_event",
                            "audit coordinate already has a conflicting event or state",
                        )
                    committed = False
                    connection.execute("COMMIT")
                else:
                    self._validate_authoritative_predecessor(connection, event, state, existing_state)
                    connection.execute(
                        """
                        INSERT INTO audit_events(task_id, generation, sequence, event_json)
                        VALUES (?, ?, ?, ?)
                        """,
                        (event["task_id"], event["generation"], event["sequence"], event_json),
                    )
                    connection.execute(
                        """
                        INSERT INTO task_states(task_id, state_json)
                        VALUES (?, ?)
                        ON CONFLICT(task_id) DO UPDATE SET state_json = excluded.state_json
                        """,
                        (state["task_id"], state_json),
                    )
                    connection.execute("COMMIT")
            except Exception:
                _rollback_quietly(connection)
                raise

        self._ensure_audit_export_line(
            self.audit_path(event["task_id"], generation=event["generation"]),
            event_json,
        )
        write_state_atomic(self.state_path(state["task_id"]), state)
        return committed

    @staticmethod
    def _validate_state_event_pair(event: dict[str, Any], state: dict[str, Any]) -> None:
        for field in ("task_id", "project_id"):
            if event[field] != state[field]:
                _raise("WORKFLOW_STATE_CORRUPT", field, f"state and audit event {field} must match")
        if state["audit_generation"] != event["generation"]:
            _raise("WORKFLOW_STATE_CORRUPT", "audit_generation", "state must bind the audit event generation")
        if state["audit_head_event_id"] != event["event_id"] or state["audit_head_hash"] != event["event_hash"]:
            _raise("WORKFLOW_STATE_CORRUPT", "audit_head_hash", "state must bind the committed audit event head")
        if event["event_type"] == "TASK_CREATED":
            expected = {
                "current_state": "DRAFT",
                "previous_state": None,
                "last_transition_id": None,
                "policy_evaluation_id": None,
            }
        elif event["event_type"] == "TRANSITION_ACCEPTED":
            policy_binding = event["policy_evaluation_binding"]
            assert isinstance(policy_binding, dict)
            expected = {
                "current_state": event["to_state"],
                "previous_state": event["from_state"],
                "last_transition_id": event["transition_id"],
                "policy_evaluation_id": policy_binding["evaluation_id"],
            }
        else:
            _raise("WORKFLOW_AUDIT_CORRUPT", "event_type", "atomic state commit accepts task and transition events only")
        for field, expected_value in expected.items():
            if state[field] != expected_value:
                _raise("WORKFLOW_STATE_CORRUPT", field, "state does not match its audit event")

    @staticmethod
    def _validate_authoritative_predecessor(
        connection: sqlite3.Connection,
        event: dict[str, Any],
        state: dict[str, Any],
        existing_state: tuple[str] | None,
    ) -> None:
        if existing_state is None:
            stray = connection.execute(
                "SELECT 1 FROM audit_events WHERE task_id = ? LIMIT 1",
                (event["task_id"],),
            ).fetchone()
            if stray is not None or event["event_type"] != "TASK_CREATED" or event["generation"] != 1 or event["sequence"] != 1:
                _raise("WORKFLOW_AUDIT_CORRUPT", "audit_event", "new task must start with generation 1 sequence 1")
            return

        current = _loads_json_mapping(
            existing_state[0],
            code="WORKFLOW_STATE_CORRUPT",
            issue_path="task_state",
        )
        current_outcome = validate_task_state(current)
        if not current_outcome.valid:
            _raise_outcome(current_outcome)
        latest = connection.execute(
            """
            SELECT sequence, event_json
            FROM audit_events
            WHERE task_id = ? AND generation = ?
            ORDER BY sequence DESC
            LIMIT 1
            """,
            (event["task_id"], current["audit_generation"]),
        ).fetchone()
        if latest is None:
            _raise("WORKFLOW_AUDIT_CORRUPT", "audit_event", "current state has no authoritative audit head")
        previous = _loads_json_mapping(latest[1], code="WORKFLOW_AUDIT_CORRUPT", issue_path="audit_event")
        previous_outcome = validate_audit_event(previous)
        if not previous_outcome.valid:
            _raise_outcome(previous_outcome)
        if (
            event["event_type"] != "TRANSITION_ACCEPTED"
            or event["generation"] != current["audit_generation"]
            or event["sequence"] != latest[0] + 1
            or event["previous_event_hash"] != current["audit_head_hash"]
            or previous["event_id"] != current["audit_head_event_id"]
            or previous["event_hash"] != current["audit_head_hash"]
            or event["from_state"] != current["current_state"]
            or state["previous_state"] != current["current_state"]
        ):
            _raise("WORKFLOW_AUDIT_CORRUPT", "previous_event_hash", "audit successor does not match the authoritative head")

    def _ensure_audit_export_line(self, path: Path, event_json: str) -> None:
        line = (event_json + "\n").encode("utf-8")
        if path.exists():
            try:
                lines = path.read_bytes().splitlines(keepends=True)
            except OSError as exc:
                _raise("WORKFLOW_AUDIT_CORRUPT", "audit_event", f"audit export could not be read: {exc}")
            if line in lines:
                if lines.count(line) > 1:
                    _raise("WORKFLOW_AUDIT_CORRUPT", "audit_event", "audit export contains duplicate event")
                return
        fd = _open_contained(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        with os.fdopen(fd, "ab") as handle:
            _reject_symlink_ancestors(path)
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())

    def acquire_task_lock(
        self,
        task_id: str,
        *,
        owner_id: str,
        now_monotonic: float,
        stale_after_seconds: float,
    ) -> WorkflowTaskLock:
        _require_safe_id(task_id, "task_id")
        _require_safe_id(owner_id, "owner_id")
        now = _require_finite_float(now_monotonic, "now_monotonic")
        stale_after = _require_finite_float(stale_after_seconds, "stale_after_seconds", positive=True)
        path = self.lock_path(task_id)
        lock_key = path.resolve(strict=False)
        if lock_key in _HELD_LOCK_PATHS:
            _raise("WORKFLOW_CONCURRENT_WRITE", "lock", "lock already held in this process")
        lock_instance_id = secrets.token_hex(16)
        payload = {
            "schema_version": 1,
            "task_id": task_id,
            "owner_id": owner_id,
            "lock_instance_id": lock_instance_id,
            "process_id": os.getpid(),
            "boot_session_id": BOOT_SESSION_ID,
            "acquired_at_monotonic": now,
        }
        try:
            marker = _read_authority_marker(self.control_store_path, self.state_root)
            if marker is None:
                _raise("WORKFLOW_STATE_CORRUPT", "control_store_authority", "control-store authority marker is missing")
            payload_bytes = canonical_json_bytes(payload) + b"\n"
            with self._connection() as connection:
                previous_generation, previous_digest = _begin_authority_transaction(
                    connection,
                    self.control_store_path,
                    expected_authority_id=self.control_authority_id,
                    expected_root_binding=self.control_root_binding,
                )
                try:
                    connection.execute(
                        """
                        INSERT INTO task_locks(task_id, owner_id, lock_instance_id, lock_record_json)
                        VALUES (?, ?, ?, ?)
                        """,
                        (task_id, owner_id, lock_instance_id, payload_bytes.decode("utf-8")),
                    )
                except sqlite3.IntegrityError as exc:
                    _rollback_quietly(connection)
                    _raise("WORKFLOW_CONCURRENT_WRITE", "lock", f"lock already held: {exc}")
                self.control_store_authority_digest = _commit_authority_transaction(
                    connection,
                    self.control_store_path,
                    self.state_root,
                    self.control_authority_id,
                    previous_generation,
                    previous_digest,
                )
            try:
                _write_bytes_contained_atomic(path, payload_bytes)
            except OSError:
                pass
            with self._connection() as current_connection:
                row = current_connection.execute(
                    "SELECT owner_id, lock_instance_id FROM task_locks WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
            if row != (owner_id, lock_instance_id):
                _raise("WORKFLOW_STATE_CORRUPT", "lock", "lock acquisition did not commit to the current authority")
        except Exception:
            raise
        _HELD_LOCK_PATHS.add(lock_key)
        return WorkflowTaskLock(
            path,
            owner_id,
            lock_instance_id,
            lock_key,
            self.control_store_path,
            task_id,
            self.control_authority_id,
            self.control_root_binding,
            self.control_store_authority_digest,
        )

    def write_idempotency_record_once(self, record: dict[str, Any], *, canonical_request: object | None = None) -> dict[str, Any]:
        data = _require_idempotency_record(record, canonical_request=canonical_request)
        path = self.operation_idempotency_path(data["task_id"], data["operation_kind"], data["idempotency_key"])
        key_digest = _idempotency_key_digest(data["idempotency_key"])
        identity = _idempotency_identity(data)
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT identity_json, record_json, canonical_request_json, idempotency_key
                FROM idempotency_records
                WHERE task_id = ? AND operation_kind = ? AND idempotency_key_sha256 = ?
                """,
                (data["task_id"], data["operation_kind"], key_digest),
            ).fetchone()
        if row is not None:
            existing = _validated_idempotency_row(
                row,
                task_id=data["task_id"],
                operation_kind=data["operation_kind"],
                idempotency_key=data["idempotency_key"],
            )
            existing_identity = _idempotency_identity(existing)
            if existing_identity != identity:
                _raise("WORKFLOW_IDEMPOTENCY_CONFLICT", "idempotency_record", "idempotency key already has different content")
            return existing
        record_json = _sqlite_json_text(data, code="WORKFLOW_INVALID_INPUT", issue_path="idempotency_record")
        identity_json = _sqlite_json_text(identity, code="WORKFLOW_INVALID_INPUT", issue_path="idempotency_record.identity")
        payload = record_json.encode("utf-8") + b"\n"
        if canonical_request is not None:
            proof_path = _canonical_request_proof_path(self.state_root, data)
            canonical_request_json = _sqlite_json_text(
                canonical_request,
                code="WORKFLOW_INVALID_INPUT",
                issue_path="canonical_request",
            )
            proof_payload = canonical_request_json.encode("utf-8") + b"\n"
        try:
            _reject_json_export_conflict(
                proof_path,
                proof_payload,
                code="WORKFLOW_IDEMPOTENCY_CONFLICT",
                issue_path="canonical_request",
            )
            _reject_json_export_conflict(
                path,
                payload,
                code="WORKFLOW_IDEMPOTENCY_CONFLICT",
                issue_path="idempotency_record",
            )
            with self._connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                try:
                    connection.execute(
                        """
                        INSERT INTO idempotency_records(
                            task_id,
                            operation_kind,
                            idempotency_key_sha256,
                            idempotency_key,
                            identity_json,
                            record_json,
                            canonical_request_json
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            data["task_id"],
                            data["operation_kind"],
                            key_digest,
                            data["idempotency_key"],
                            identity_json,
                            record_json,
                            canonical_request_json,
                        ),
                    )
                except sqlite3.IntegrityError:
                    connection.execute("ROLLBACK")
                    existing = read_idempotency_record(self.state_root, data["task_id"], data["operation_kind"], data["idempotency_key"])
                    if existing is not None and _idempotency_identity(existing) == identity:
                        return existing
                    _raise("WORKFLOW_IDEMPOTENCY_CONFLICT", "idempotency_record", "idempotency key already has different content")
                connection.execute("COMMIT")
            _write_json_export_once_or_same(
                proof_path,
                proof_payload,
                code="WORKFLOW_IDEMPOTENCY_CONFLICT",
                issue_path="canonical_request",
            )
            _write_json_export_once_or_same(
                path,
                payload,
                code="WORKFLOW_IDEMPOTENCY_CONFLICT",
                issue_path="idempotency_record",
            )
            return data
        except OSError as exc:
            _raise("WORKFLOW_IDEMPOTENCY_CONFLICT", "idempotency_record", f"idempotency record could not be published: {exc}")


def operation_idempotency_path(root: Path, task_id: str, operation_kind: str, idempotency_key: str) -> Path:
    return WorkflowStore(root).operation_idempotency_path(task_id, operation_kind, idempotency_key)


def append_audit_event(root: Path, event: dict[str, Any]) -> None:
    WorkflowStore(root).append_audit_event(event)


def acquire_task_lock(
    root: Path,
    task_id: str,
    *,
    owner_id: str,
    now_monotonic: float,
    stale_after_seconds: float,
) -> WorkflowTaskLock:
    return WorkflowStore(root).acquire_task_lock(
        task_id,
        owner_id=owner_id,
        now_monotonic=now_monotonic,
        stale_after_seconds=stale_after_seconds,
    )


def read_idempotency_record(root: Path, task_id: str, operation_kind: str, idempotency_key: str) -> dict[str, Any] | None:
    store = WorkflowStore(root)
    store.operation_idempotency_path(task_id, operation_kind, idempotency_key)
    key_digest = _idempotency_key_digest(idempotency_key)
    with store._connection() as connection:
        row = connection.execute(
            """
            SELECT identity_json, record_json, canonical_request_json, idempotency_key
            FROM idempotency_records
            WHERE task_id = ? AND operation_kind = ? AND idempotency_key_sha256 = ?
            """,
            (task_id, operation_kind, key_digest),
        ).fetchone()
    if row is not None:
        return _validated_idempotency_row(row, task_id=task_id, operation_kind=operation_kind, idempotency_key=idempotency_key)
    return None


def write_idempotency_record_once(root: Path, record: dict[str, Any], *, canonical_request: object | None = None) -> dict[str, Any]:
    return WorkflowStore(root).write_idempotency_record_once(record, canonical_request=canonical_request)
