from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import acgps.workflow_store as workflow_store
from acgps.workflow_contracts import canonical_json_bytes
from acgps.workflow_store import (
    WorkflowStore,
    WorkflowStoreError,
    read_idempotency_record,
    safe_state_path,
    write_state_atomic,
)
from tests.test_contracts import (
    _valid_attempt_hold_coding_execution_record,
    _valid_candidate_ready_coding_execution_record,
    _valid_prelaunch_hold_coding_execution_record,
)


def canonical_sha(record: object) -> str:
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


def valid_request_fingerprint(record: dict[str, object]) -> str:
    request_identity = {
        "schema_version": 1,
        "operation_kind": record["operation_kind"],
        "operation_id": record["operation_id"],
        "task_id": record["task_id"],
        "idempotency_key": record["idempotency_key"],
        "transaction_path": record["transaction_path"],
    }
    return canonical_sha(request_identity)


def timestamp_free_request_fingerprint(record: dict[str, object]) -> str:
    return canonical_sha({key: value for key, value in record.items() if not key.endswith("_at_utc")})


def valid_initialization_request(**overrides):
    intake = {"intake_id": "intake-1", "title": "Task 1"}
    intake_payload = canonical_json_bytes(intake)
    task_intake_binding = {
        "schema_version": 1,
        "binding_id": "intake-binding-1",
        "evidence_kind": "task_intake",
        "source": "embedded",
        "path": None,
        "embedded_record": intake,
        "embedded_sha256": hashlib.sha256(intake_payload).hexdigest(),
        "content_sha256": hashlib.sha256(intake_payload).hexdigest(),
        "size_bytes": len(intake_payload),
        "created_at_utc": "2026-07-28T12:00:00Z",
    }
    record = {
        "schema_version": 1,
        "initialization_id": "init-1",
        "task_id": "task-1",
        "project_id": "ACGPS",
        "initial_state": "DRAFT",
        "actor": "PLANNER",
        "idempotency_key": "idem-1",
        "task_intake_binding": task_intake_binding,
        "created_at_utc": "2026-07-28T12:00:00Z",
    }
    record.update(overrides)
    return record


def replace_directory_with_symlink(path: Path, target: Path) -> None:
    if path.exists() or path.is_symlink():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    target.mkdir(parents=True, exist_ok=True)
    os.symlink(target, path, target_is_directory=True)


def restore_directory(path: Path) -> None:
    if path.is_symlink() or path.exists():
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    path.mkdir(parents=True, exist_ok=True)


def valid_audit_generation(**overrides):
    record = {
        "schema_version": 1,
        "generation": 1,
        "task_id": "task-1",
        "started_by_event_id": "event-1",
        "started_by_event_type": "TASK_CREATED",
        "predecessor_generation": None,
        "predecessor_valid_head_hash": None,
        "quarantine_path": None,
        "threat_model": "CORRUPTION_AND_NON_COORDINATED_TAMPER_ONLY",
        "created_at_utc": "2026-07-28T12:00:00Z",
    }
    record.update(overrides)
    return record


def valid_task_state(**overrides):
    record = {
        "schema_version": 1,
        "task_id": "task-1",
        "project_id": "ACGPS",
        "current_state": "DRAFT",
        "previous_state": None,
        "last_transition_id": None,
        "audit_generation": 1,
        "audit_head_event_id": "event-1",
        "audit_head_hash": "3" * 64,
        "policy_evaluation_id": None,
        "pending_decision_id": None,
        "updated_at_utc": "2026-07-28T12:00:00Z",
    }
    record.update(overrides)
    return record


def valid_task_created_event(**overrides):
    record = {
        "schema_version": 1,
        "event_id": "event-1",
        "generation": 1,
        "sequence": 1,
        "project_id": "ACGPS",
        "task_id": "task-1",
        "event_type": "TASK_CREATED",
        "actor": "PLANNER",
        "from_state": None,
        "to_state": None,
        "transition_id": None,
        "policy_evaluation_binding": None,
        "evidence_bindings": [],
        "decision_resolution_binding": None,
        "previous_event_hash": None,
        "event_hash": None,
        "created_at_utc": "2026-07-28T12:00:00Z",
        "details": {"audit_generation": valid_audit_generation()},
    }
    record.update(overrides)
    record["details"]["audit_generation"]["started_by_event_id"] = record["event_id"]
    record["details"]["audit_generation"]["task_id"] = record["task_id"]
    record["event_hash"] = canonical_sha(dict(record, event_hash=None))
    return record


def valid_policy_binding(*, to_state: str = "READY_FOR_CLASSIFICATION") -> dict[str, object]:
    policy_body = {
        "decision_emitted": True,
        "risk_level": "R0",
        "human_gate": False,
        "required_human_triggers": [],
        "required_skills": [],
        "model_roles": {},
        "mandatory_gates": [],
        "legal_transitions": [to_state],
        "authorized_transitions": [to_state],
        "provenance": ["config/workflow_policy.yaml:transitions.DRAFT"],
        "fail_closed": False,
        "error_code": None,
        "issues": [],
    }
    policy_result = {
        "schema_version": 1,
        "evaluation_id": "eval-1",
        "project_id": "ACGPS",
        "task_id": "task-1",
        "policy_bundle_digest": "f" * 64,
        "result": policy_body,
        "created_at_utc": "2026-07-28T12:01:00Z",
    }
    return {
        "schema_version": 1,
        "evaluation_id": "eval-1",
        "source": "embedded",
        "path": None,
        "embedded_record": policy_result,
        "result_sha256": canonical_sha(policy_result),
        "policy_bundle_digest": "f" * 64,
        "authorized_transitions": [to_state],
        "human_gate": False,
        "created_at_utc": "2026-07-28T12:01:00Z",
    }


def valid_evidence_binding() -> dict[str, object]:
    return {
        "schema_version": 1,
        "binding_id": "evidence-1",
        "evidence_kind": "task_intake",
        "source": "embedded",
        "path": None,
        "embedded_record": {"accepted": True},
        "embedded_sha256": canonical_sha({"accepted": True}),
        "content_sha256": canonical_sha({"accepted": True}),
        "size_bytes": len(canonical_json_bytes({"accepted": True})),
        "created_at_utc": "2026-07-28T12:01:00Z",
    }


def valid_transition_event(previous: dict[str, object], **overrides) -> dict[str, object]:
    record = {
        "schema_version": 1,
        "event_id": "event-2",
        "generation": 1,
        "sequence": 2,
        "project_id": "ACGPS",
        "task_id": "task-1",
        "event_type": "TRANSITION_ACCEPTED",
        "actor": "CONTROLLER",
        "from_state": "DRAFT",
        "to_state": "READY_FOR_CLASSIFICATION",
        "transition_id": "transition-1",
        "policy_evaluation_binding": valid_policy_binding(),
        "evidence_bindings": [valid_evidence_binding()],
        "decision_resolution_binding": None,
        "previous_event_hash": previous["event_hash"],
        "event_hash": None,
        "created_at_utc": "2026-07-28T12:01:00Z",
        "details": {},
    }
    record.update(overrides)
    record["event_hash"] = canonical_sha(dict(record, event_hash=None))
    return record


def valid_idempotency_record(**overrides):
    result = {
        "schema_version": 1,
        "initialization_id": "init-1",
        "task_id": "task-1",
        "project_id": "ACGPS",
        "accepted": True,
        "resulting_state": "DRAFT",
        "audit_event_id": "event-1",
        "audit_generation": 1,
        "audit_sequence": 1,
        "fail_closed": False,
        "error_code": None,
        "issues": [],
        "idempotent_replay": False,
        "created_at_utc": "2026-07-28T12:00:00Z",
    }
    transaction_path = "state/transactions/task-1/initialization-init-1"
    record = {
        "schema_version": 1,
        "operation_kind": "INITIALIZATION",
        "operation_id": "init-1",
        "task_id": "task-1",
        "idempotency_key": "idem-1",
        "request_fingerprint": "0" * 64,
        "result_fingerprint": canonical_sha(result),
        "canonical_result": result,
        "transaction_path": transaction_path,
        "created_at_utc": "2026-07-28T12:00:00Z",
    }
    request = valid_initialization_request(
        initialization_id=record["operation_id"],
        task_id=record["task_id"],
        idempotency_key=record["idempotency_key"],
    )
    record["request_fingerprint"] = timestamp_free_request_fingerprint(request)
    record.update(overrides)
    return record


class WorkflowStoreTests(unittest.TestCase):
    def test_atomic_state_and_audit_commit_is_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            event = valid_task_created_event()
            state = valid_task_state(
                audit_head_event_id=event["event_id"],
                audit_head_hash=event["event_hash"],
            )

            committed = store.commit_task_state_and_audit(event, state)

            self.assertTrue(committed)
            self.assertEqual(store.read_task_state("task-1"), state)
            self.assertEqual(
                [json.loads(line) for line in store.audit_path("task-1").read_text(encoding="utf-8").splitlines()],
                [event],
            )

    def test_atomic_state_and_audit_commit_accepts_exact_successor_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            first = valid_task_created_event()
            first_state = valid_task_state(
                audit_head_event_id=first["event_id"],
                audit_head_hash=first["event_hash"],
            )
            store.commit_task_state_and_audit(first, first_state)
            second = valid_transition_event(first)
            second_state = valid_task_state(
                current_state="READY_FOR_CLASSIFICATION",
                previous_state="DRAFT",
                last_transition_id="transition-1",
                audit_head_event_id=second["event_id"],
                audit_head_hash=second["event_hash"],
                policy_evaluation_id="eval-1",
                updated_at_utc="2026-07-28T12:01:00Z",
            )

            self.assertTrue(store.commit_task_state_and_audit(second, second_state))
            self.assertFalse(store.commit_task_state_and_audit(second, second_state))
            self.assertEqual(len(store.audit_path("task-1").read_text(encoding="utf-8").splitlines()), 2)

    def test_atomic_state_and_audit_conflict_rolls_back_both_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            first = valid_task_created_event()
            first_state = valid_task_state(
                audit_head_event_id=first["event_id"],
                audit_head_hash=first["event_hash"],
            )
            store.commit_task_state_and_audit(first, first_state)
            conflicting_event = valid_transition_event(first, previous_event_hash="9" * 64)
            conflicting_state = valid_task_state(
                current_state="READY_FOR_CLASSIFICATION",
                previous_state="DRAFT",
                last_transition_id="transition-1",
                audit_head_event_id=conflicting_event["event_id"],
                audit_head_hash=conflicting_event["event_hash"],
                policy_evaluation_id="eval-1",
                updated_at_utc="2026-07-28T12:01:00Z",
            )

            with self.assertRaises(WorkflowStoreError) as conflict:
                store.commit_task_state_and_audit(conflicting_event, conflicting_state)

            self.assertEqual(conflict.exception.issue.code, "WORKFLOW_AUDIT_CORRUPT")
            self.assertEqual(store.read_task_state("task-1"), first_state)
            self.assertEqual(len(store.audit_path("task-1").read_text(encoding="utf-8").splitlines()), 1)

    def test_read_audit_events_uses_authoritative_rows_not_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            event = valid_task_created_event()
            state = valid_task_state(
                audit_head_event_id=event["event_id"],
                audit_head_hash=event["event_hash"],
            )
            store.commit_task_state_and_audit(event, state)
            store.audit_path("task-1").write_text("{not-json\n", encoding="utf-8")

            self.assertEqual(store.read_audit_events("task-1"), [event])

    def test_persistence_core_uses_sqlite_authority_for_state_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            state = valid_task_state()

            store.write_task_state(state)
            self.assertTrue(store.control_store_path.exists())

            exported_state = store.state_path("task-1")
            exported_state.write_text(
                json.dumps(valid_task_state(current_state="PLAN_READY"), sort_keys=True) + "\n",
                encoding="utf-8",
            )

            self.assertEqual(store.read_task_state("task-1"), state)

    def test_persistence_core_lock_does_not_depend_on_finite_tcp_port_anchor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            self.assertNotIn("_lock_anchor_port", Path("acgps/workflow_store.py").read_text(encoding="utf-8"))
            self.assertNotIn("_acquire_lock_anchor", Path("acgps/workflow_store.py").read_text(encoding="utf-8"))

            lock = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)
            with self.assertRaises(WorkflowStoreError) as contended:
                store.acquire_task_lock("task-1", owner_id="owner-2", now_monotonic=2.0, stale_after_seconds=30.0)
            self.assertEqual(contended.exception.issue.code, "WORKFLOW_CONCURRENT_WRITE")
            lock.release()

    def test_persistence_core_idempotency_ignores_poisoned_json_exports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            canonical_request = valid_initialization_request()
            record = valid_idempotency_record(request_fingerprint=timestamp_free_request_fingerprint(canonical_request))

            store.write_idempotency_record_once(record, canonical_request=canonical_request)
            store.operation_idempotency_path("task-1", "INITIALIZATION", "idem-1").write_text(
                '{"schema_version":1',
                encoding="utf-8",
            )
            (store.state_root / record["transaction_path"] / "canonical_request.json").write_text(
                json.dumps(valid_initialization_request(actor="CODER"), sort_keys=True) + "\n",
                encoding="utf-8",
            )

            self.assertEqual(read_idempotency_record(store.state_root, "task-1", "INITIALIZATION", "idem-1"), record)
            self.assertEqual(store.write_idempotency_record_once(dict(record), canonical_request=canonical_request), record)

    def test_persistence_core_r02_rejects_replaced_or_symlinked_control_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "state"
            store = WorkflowStore(root)
            first = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)
            replaced = tmp_path / "control.replaced.sqlite3"
            store.control_store_path.rename(replaced)
            probe = (
                "from pathlib import Path\n"
                "from acgps.workflow_store import WorkflowStore, WorkflowStoreError\n"
                f"root=Path({str(root)!r})\n"
                "try:\n"
                "    store=WorkflowStore(root)\n"
                "    lock=store.acquire_task_lock('task-1', owner_id='owner-2', now_monotonic=2.0, stale_after_seconds=30.0)\n"
                "except WorkflowStoreError:\n"
                "    raise SystemExit(0)\n"
                "else:\n"
                "    lock.release()\n"
                "    raise SystemExit(7)\n"
            )
            try:
                completed = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=10)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            finally:
                if not store.control_store_path.exists() and replaced.exists():
                    replaced.replace(store.control_store_path)
                first.release()

            if store.control_store_path.exists() or store.control_store_path.is_symlink():
                store.control_store_path.unlink()
            outside = tmp_path / "outside-control.sqlite3"
            os.symlink(outside, store.control_store_path)
            with self.assertRaises(WorkflowStoreError) as symlinked:
                WorkflowStore(root)
            self.assertEqual(symlinked.exception.issue.code, "WORKFLOW_STATE_CORRUPT")
            self.assertFalse(outside.exists())

    def test_persistence_core_r02_exports_are_not_runtime_fallback_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            store.state_path("task-1").parent.mkdir(parents=True, exist_ok=True)
            store.state_path("task-1").write_text(
                json.dumps(valid_task_state(current_state="PLAN_READY"), sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(WorkflowStoreError) as missing_state:
                store.read_task_state("task-1")
            self.assertEqual(missing_state.exception.issue.code, "WORKFLOW_STATE_CORRUPT")

            canonical_request = valid_initialization_request()
            record = valid_idempotency_record(request_fingerprint=timestamp_free_request_fingerprint(canonical_request))
            idem_path = store.operation_idempotency_path("task-1", "INITIALIZATION", "idem-1")
            proof_path = store.state_root / record["transaction_path"] / "canonical_request.json"
            idem_path.parent.mkdir(parents=True, exist_ok=True)
            proof_path.parent.mkdir(parents=True, exist_ok=True)
            idem_path.write_text(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            proof_path.write_text(json.dumps(canonical_request, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")

            self.assertIsNone(read_idempotency_record(store.state_root, "task-1", "INITIALIZATION", "idem-1"))

    def test_persistence_core_r02_sqlite_rows_are_key_bound_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            task2_state = valid_task_state(task_id="task-2")
            connection = sqlite3.connect(store.control_store_path)
            try:
                connection.execute(
                    "INSERT INTO task_states(task_id, state_json) VALUES (?, ?)",
                    ("task-1", json.dumps(task2_state, sort_keys=True, separators=(",", ":"))),
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(WorkflowStoreError) as wrong_task:
                store.read_task_state("task-1")
            self.assertEqual(wrong_task.exception.issue.code, "WORKFLOW_STATE_CORRUPT")

            connection = sqlite3.connect(store.control_store_path)
            try:
                connection.execute("UPDATE task_states SET state_json = ? WHERE task_id = ?", ("{not-json", "task-1"))
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(WorkflowStoreError) as malformed:
                store.read_task_state("task-1")
            self.assertEqual(malformed.exception.issue.code, "WORKFLOW_STATE_CORRUPT")

            store.control_store_path.write_bytes(b"not a sqlite database")
            with self.assertRaises(WorkflowStoreError) as corrupt_db:
                WorkflowStore(store.state_root)
            self.assertEqual(corrupt_db.exception.issue.code, "WORKFLOW_STATE_CORRUPT")

    def test_persistence_core_r02_idempotency_sqlite_rows_are_fully_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            canonical_request = valid_initialization_request()
            record = valid_idempotency_record(request_fingerprint=timestamp_free_request_fingerprint(canonical_request))
            store.write_idempotency_record_once(record, canonical_request=canonical_request)
            tampered = dict(record, result_fingerprint="0" * 64)
            connection = sqlite3.connect(store.control_store_path)
            try:
                connection.execute(
                    "UPDATE idempotency_records SET record_json = ? WHERE task_id = ?",
                    (json.dumps(tampered, sort_keys=True, separators=(",", ":")), "task-1"),
                )
                connection.commit()
            finally:
                connection.close()

            with self.assertRaises(WorkflowStoreError) as tamper:
                read_idempotency_record(store.state_root, "task-1", "INITIALIZATION", "idem-1")
            self.assertEqual(tamper.exception.issue.code, "WORKFLOW_IDEMPOTENCY_CONFLICT")

    def test_persistence_core_r02_duplicate_audit_does_not_mutate_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            event = valid_task_created_event()
            store.append_audit_event(event)
            before = store.audit_path("task-1").read_text(encoding="utf-8")

            with self.assertRaises(WorkflowStoreError) as duplicate:
                store.append_audit_event(dict(event))

            self.assertEqual(duplicate.exception.issue.code, "WORKFLOW_AUDIT_CORRUPT")
            self.assertEqual(store.audit_path("task-1").read_text(encoding="utf-8"), before)

    def test_persistence_core_r03_rejects_same_authority_old_database_lock_split(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "state"
            store = WorkflowStore(root)
            old_database = tmp_path / "old-control.sqlite3"
            shutil.copy2(store.control_store_path, old_database)

            lock = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)
            try:
                shutil.copy2(old_database, store.control_store_path)
                for suffix in ("-wal", "-shm"):
                    sidecar = Path(str(store.control_store_path) + suffix)
                    if sidecar.exists():
                        sidecar.unlink()

                probe = (
                    "from pathlib import Path\n"
                    "from acgps.workflow_store import WorkflowStore, WorkflowStoreError\n"
                    f"root=Path({str(root)!r})\n"
                    "try:\n"
                    "    store=WorkflowStore(root)\n"
                    "    lock=store.acquire_task_lock('task-1', owner_id='owner-2', now_monotonic=2.0, stale_after_seconds=30.0)\n"
                    "except WorkflowStoreError:\n"
                    "    raise SystemExit(0)\n"
                    "else:\n"
                    "    lock.release()\n"
                    "    raise SystemExit(7)\n"
                )
                completed = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=10)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            finally:
                try:
                    lock.release()
                except WorkflowStoreError as fail_closed_release:
                    self.assertEqual(fail_closed_release.issue.code, "WORKFLOW_STATE_CORRUPT")

    def test_persistence_core_r04_preopened_process_rejects_restored_authority_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "state"
            store = WorkflowStore(root)
            old_database = tmp_path / "old-control.sqlite3"
            ready = tmp_path / "opened.flag"
            go = tmp_path / "go.flag"
            shutil.copy2(store.control_store_path, old_database)
            probe = (
                "from pathlib import Path\n"
                "import time\n"
                "from acgps.workflow_store import WorkflowStore, WorkflowStoreError\n"
                f"root=Path({str(root)!r})\n"
                f"ready=Path({str(ready)!r})\n"
                f"go=Path({str(go)!r})\n"
                "store=WorkflowStore(root)\n"
                "ready.write_text('ready', encoding='utf-8')\n"
                "deadline=time.time()+10\n"
                "while not go.exists() and time.time()<deadline:\n"
                "    time.sleep(0.02)\n"
                "if not go.exists():\n"
                "    raise SystemExit(8)\n"
                "try:\n"
                "    lock=store.acquire_task_lock('task-1', owner_id='owner-2', now_monotonic=2.0, stale_after_seconds=30.0)\n"
                "except WorkflowStoreError:\n"
                "    raise SystemExit(0)\n"
                "else:\n"
                "    lock.release()\n"
                "    raise SystemExit(7)\n"
            )
            child = subprocess.Popen([sys.executable, "-c", probe], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = datetime.now().timestamp() + 10
                while not ready.exists() and datetime.now().timestamp() < deadline:
                    pass
                self.assertTrue(ready.exists(), "probe did not open the store before rollback")
                lock = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)
                try:
                    shutil.copy2(old_database, store.control_store_path)
                    for suffix in ("-wal", "-shm"):
                        sidecar = Path(str(store.control_store_path) + suffix)
                        if sidecar.exists():
                            sidecar.unlink()
                    go.write_text("go", encoding="utf-8")
                    stdout, stderr = child.communicate(timeout=10)
                    self.assertEqual(child.returncode, 0, stdout + stderr)
                finally:
                    try:
                        lock.release()
                    except WorkflowStoreError as fail_closed_release:
                        self.assertEqual(fail_closed_release.issue.code, "WORKFLOW_STATE_CORRUPT")
            finally:
                if child.poll() is None:
                    child.kill()
                    child.communicate(timeout=5)

    def test_persistence_core_r04_rejects_stale_authority_marker_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            old_marker = workflow_store._read_authority_marker(store.control_store_path, store.state_root)
            self.assertIsNotNone(old_marker)
            old_digest = store.control_store_authority_digest
            first = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)
            try:
                new_marker = workflow_store._read_authority_marker(
                    store.control_store_path,
                    store.state_root,
                )
                self.assertIsNotNone(new_marker)
                new_digest = new_marker["control_store_authority_digest"]
                self.assertNotEqual(old_digest, new_digest)

                with self.assertRaises(WorkflowStoreError) as stale:
                    workflow_store._write_authority_marker(
                        store.control_store_path,
                        store.state_root,
                        store.control_authority_id,
                        old_marker["authority_generation"],
                        old_digest,
                        expected_previous_digest=old_digest,
                        expected_previous_generation=old_marker["authority_generation"],
                    )
                self.assertEqual(stale.exception.issue.code, "WORKFLOW_STATE_CORRUPT")
                self.assertIsInstance(WorkflowStore(store.state_root), WorkflowStore)
            finally:
                first.release()

    def test_persistence_core_r04_deep_and_oversized_sqlite_json_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            store = WorkflowStore(root)
            store.write_task_state(valid_task_state())
            canonical_request = valid_initialization_request()
            record = valid_idempotency_record(request_fingerprint=timestamp_free_request_fingerprint(canonical_request))
            store.write_idempotency_record_once(record, canonical_request=canonical_request)
            deep_json = '{"schema_version":' + ("[" * 600) + "0" + ("]" * 600) + "}"
            oversized_json = '{"schema_version":1,"payload":"' + ("x" * (workflow_store.MAX_SQLITE_JSON_BYTES + 1)) + '"}'

            corruptions = [
                ("task_states", "state_json", "task_id = 'task-1'", deep_json, "WORKFLOW_STATE_CORRUPT", lambda: store.read_task_state("task-1")),
                ("idempotency_records", "identity_json", "task_id = 'task-1'", deep_json, "WORKFLOW_IDEMPOTENCY_CONFLICT", lambda: read_idempotency_record(root, "task-1", "INITIALIZATION", "idem-1")),
                ("idempotency_records", "record_json", "task_id = 'task-1'", oversized_json, "WORKFLOW_IDEMPOTENCY_CONFLICT", lambda: read_idempotency_record(root, "task-1", "INITIALIZATION", "idem-1")),
                ("idempotency_records", "canonical_request_json", "task_id = 'task-1'", deep_json, "WORKFLOW_IDEMPOTENCY_CONFLICT", lambda: read_idempotency_record(root, "task-1", "INITIALIZATION", "idem-1")),
            ]
            for table, column, predicate, value, code, operation in corruptions:
                with self.subTest(column=f"{table}.{column}"):
                    connection = sqlite3.connect(store.control_store_path)
                    try:
                        connection.execute(f"UPDATE {table} SET {column} = ? WHERE {predicate}", (value,))
                        connection.commit()
                    finally:
                        connection.close()
                    with self.assertRaises(WorkflowStoreError) as corrupt:
                        operation()
                    self.assertEqual(corrupt.exception.issue.code, code)
                    store = WorkflowStore(root)
                    if table == "task_states":
                        store.write_task_state(valid_task_state())
                    else:
                        connection = sqlite3.connect(store.control_store_path)
                        try:
                            connection.execute("DELETE FROM idempotency_records WHERE task_id = 'task-1'")
                            connection.commit()
                        finally:
                            connection.close()
                        store.write_idempotency_record_once(record, canonical_request=canonical_request)

    def test_authority_protocol_r05_rejects_detached_connection_after_authority_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "state"
            store = WorkflowStore(root)
            detached_database = tmp_path / "detached.sqlite3"
            shutil.copy2(store.control_store_path, detached_database)
            original_connect = workflow_store._connect_control_store
            injected = {"count": 0}

            def connect_detached_once(path: Path):
                if Path(path) == store.control_store_path and injected["count"] == 0:
                    injected["count"] += 1
                    return original_connect(detached_database)
                return original_connect(path)

            with patch("acgps.workflow_store._connect_control_store", side_effect=connect_detached_once):
                with self.assertRaises(WorkflowStoreError) as detached:
                    store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)

            self.assertEqual(injected["count"], 1)
            self.assertEqual(detached.exception.issue.code, "WORKFLOW_STATE_CORRUPT")

            connection = sqlite3.connect(store.control_store_path)
            try:
                current_rows = connection.execute("SELECT COUNT(*) FROM task_locks WHERE task_id = 'task-1'").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(current_rows, 0)

            second = WorkflowStore(root).acquire_task_lock("task-1", owner_id="owner-2", now_monotonic=2.0, stale_after_seconds=30.0)
            second.release()

    def test_authority_protocol_r05_marker_publication_failure_does_not_hide_committed_lock_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")

            def fail_marker_write(*args, **kwargs):
                workflow_store._raise("WORKFLOW_STATE_CORRUPT", "control_store_authority", "injected marker publication failure")

            with patch("acgps.workflow_store._write_authority_marker", side_effect=fail_marker_write):
                lock = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)
            connection = sqlite3.connect(store.control_store_path)
            try:
                rows_after_failed_acquire = connection.execute("SELECT COUNT(*) FROM task_locks WHERE task_id = 'task-1'").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(rows_after_failed_acquire, 1)

            with patch("acgps.workflow_store._write_authority_marker", side_effect=fail_marker_write):
                lock.release()
            connection = sqlite3.connect(store.control_store_path)
            try:
                rows_after_failed_release = connection.execute("SELECT COUNT(*) FROM task_locks WHERE task_id = 'task-1'").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(rows_after_failed_release, 0)
            recovered = WorkflowStore(store.state_root)
            second = recovered.acquire_task_lock("task-1", owner_id="owner-2", now_monotonic=2.0, stale_after_seconds=30.0)
            second.release()

    def test_authority_protocol_r05_rejects_oversized_idempotency_write_before_row_or_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            huge_key = "k" * (workflow_store.MAX_SQLITE_JSON_BYTES + 1)
            canonical_request = valid_initialization_request(idempotency_key=huge_key)
            record = valid_idempotency_record(
                idempotency_key=huge_key,
                request_fingerprint=timestamp_free_request_fingerprint(canonical_request),
            )
            record_path = store.operation_idempotency_path("task-1", "INITIALIZATION", huge_key)
            proof_path = store.state_root / record["transaction_path"] / "canonical_request.json"

            with self.assertRaises(WorkflowStoreError) as oversized:
                store.write_idempotency_record_once(record, canonical_request=canonical_request)

            self.assertEqual(oversized.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            connection = sqlite3.connect(store.control_store_path)
            try:
                rows = connection.execute(
                    "SELECT COUNT(*) FROM idempotency_records WHERE task_id = 'task-1' AND operation_kind = 'INITIALIZATION'"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(rows, 0)
            self.assertFalse(record_path.exists())
            self.assertFalse(proof_path.exists())

    def test_authority_transaction_r06_commit_failure_does_not_poison_authority_marker(self) -> None:
        class CommitFailingConnection:
            def __init__(self, inner):
                self._inner = inner
                self.failed_commit = False

            def execute(self, statement, *args, **kwargs):
                if statement == "COMMIT" and not self.failed_commit:
                    self.failed_commit = True
                    raise sqlite3.OperationalError("injected commit failure")
                return self._inner.execute(statement, *args, **kwargs)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            original_connect = workflow_store._connect_control_store
            injected = {"done": False}

            def connect_with_commit_failure(path: Path):
                connection = original_connect(path)
                if Path(path) == store.control_store_path and not injected["done"]:
                    injected["done"] = True
                    return CommitFailingConnection(connection)
                return connection

            with patch("acgps.workflow_store._connect_control_store", side_effect=connect_with_commit_failure):
                with self.assertRaises(WorkflowStoreError) as failed:
                    store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)

            self.assertEqual(failed.exception.issue.code, "WORKFLOW_STATE_CORRUPT")
            recovered_store = WorkflowStore(store.state_root)
            lock = recovered_store.acquire_task_lock("task-1", owner_id="owner-2", now_monotonic=2.0, stale_after_seconds=30.0)
            lock.release()

    def test_authority_transaction_r06_lock_export_failure_returns_releasable_committed_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            original_write = workflow_store._write_bytes_contained_atomic
            injected = {"count": 0}

            def fail_lock_export_once(path: Path, payload: bytes):
                if Path(path) == store.lock_path("task-1") and injected["count"] == 0:
                    injected["count"] += 1
                    raise PermissionError("injected lock export failure")
                return original_write(path, payload)

            with patch("acgps.workflow_store._write_bytes_contained_atomic", side_effect=fail_lock_export_once):
                lock = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)

            self.assertEqual(injected["count"], 1)
            lock.release()
            second = WorkflowStore(store.state_root).acquire_task_lock(
                "task-1",
                owner_id="owner-2",
                now_monotonic=2.0,
                stale_after_seconds=30.0,
            )
            second.release()

    def test_authority_transaction_r06_detects_connection_identity_change_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            original_digest = workflow_store._control_store_authority_digest
            injected = {"done": False}

            def invalidate_connection_binding(connection):
                if not injected["done"] and id(connection) in workflow_store._CONTROL_CONNECTION_BINDINGS:
                    injected["done"] = True
                    bound_path, binding = workflow_store._CONTROL_CONNECTION_BINDINGS[id(connection)]
                    workflow_store._CONTROL_CONNECTION_BINDINGS[id(connection)] = (bound_path, ("replaced", binding))
                return original_digest(connection)

            with patch("acgps.workflow_store._control_store_authority_digest", side_effect=invalidate_connection_binding):
                with self.assertRaises(WorkflowStoreError) as replaced:
                    store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)

            self.assertEqual(replaced.exception.issue.code, "WORKFLOW_STATE_CORRUPT")
            self.assertTrue(injected["done"])
            recovered_store = WorkflowStore(store.state_root)
            lock = recovered_store.acquire_task_lock("task-1", owner_id="owner-2", now_monotonic=2.0, stale_after_seconds=30.0)
            lock.release()

    def test_persistence_core_r03_rejects_bare_canonical_request_export_as_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            canonical_request = valid_initialization_request()
            record = valid_idempotency_record(request_fingerprint=timestamp_free_request_fingerprint(canonical_request))
            proof_path = store.state_root / record["transaction_path"] / "canonical_request.json"
            proof_path.parent.mkdir(parents=True, exist_ok=True)
            proof_path.write_text(
                json.dumps(canonical_request, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(WorkflowStoreError) as bare_proof:
                store.write_idempotency_record_once(record)

            self.assertEqual(bare_proof.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            self.assertIsNone(read_idempotency_record(store.state_root, "task-1", "INITIALIZATION", "idem-1"))

    def test_persistence_core_r03_sqlite_dynamic_types_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "state"
            store = WorkflowStore(root)
            store.write_task_state(valid_task_state())
            canonical_request = valid_initialization_request()
            record = valid_idempotency_record(request_fingerprint=timestamp_free_request_fingerprint(canonical_request))
            store.write_idempotency_record_once(record, canonical_request=canonical_request)

            corruptions = [
                ("task_states", "state_json", "task_id = 'task-1'", sqlite3.Binary(b"\xff"), "WORKFLOW_STATE_CORRUPT", lambda: store.read_task_state("task-1")),
                ("idempotency_records", "identity_json", "task_id = 'task-1'", sqlite3.Binary(b"\xff"), "WORKFLOW_IDEMPOTENCY_CONFLICT", lambda: read_idempotency_record(root, "task-1", "INITIALIZATION", "idem-1")),
                ("idempotency_records", "record_json", "task_id = 'task-1'", 42, "WORKFLOW_IDEMPOTENCY_CONFLICT", lambda: read_idempotency_record(root, "task-1", "INITIALIZATION", "idem-1")),
                ("idempotency_records", "canonical_request_json", "task_id = 'task-1'", 3.5, "WORKFLOW_IDEMPOTENCY_CONFLICT", lambda: read_idempotency_record(root, "task-1", "INITIALIZATION", "idem-1")),
            ]
            for table, column, predicate, value, code, operation in corruptions:
                with self.subTest(column=f"{table}.{column}"):
                    connection = sqlite3.connect(store.control_store_path)
                    try:
                        connection.execute(f"UPDATE {table} SET {column} = ? WHERE {predicate}", (value,))
                        connection.commit()
                    finally:
                        connection.close()
                    with self.assertRaises(WorkflowStoreError) as corrupt:
                        operation()
                    self.assertEqual(corrupt.exception.issue.code, code)
                    store = WorkflowStore(root)
                    if table == "task_states":
                        store.write_task_state(valid_task_state())
                    else:
                        connection = sqlite3.connect(store.control_store_path)
                        try:
                            connection.execute("DELETE FROM idempotency_records WHERE task_id = 'task-1'")
                            connection.commit()
                        finally:
                            connection.close()
                        store.write_idempotency_record_once(record, canonical_request=canonical_request)

    def test_persistence_core_r03_rejected_duplicate_audit_never_mutates_export(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            event = valid_task_created_event()
            store.append_audit_event(event)
            audit_path = store.audit_path("task-1")

            scenarios = [
                ("missing", None),
                ("different", canonical_json_bytes(valid_task_created_event(event_id="event-2", sequence=2)) + b"\n"),
                ("duplicate", audit_path.read_bytes() * 2),
                ("truncated", audit_path.read_bytes()[:10]),
            ]
            for name, payload in scenarios:
                with self.subTest(name=name):
                    if payload is None:
                        audit_path.unlink()
                        before = None
                    else:
                        audit_path.write_bytes(payload)
                        before = audit_path.read_bytes()

                    with self.assertRaises(WorkflowStoreError) as duplicate:
                        store.append_audit_event(dict(event))

                    self.assertEqual(duplicate.exception.issue.code, "WORKFLOW_AUDIT_CORRUPT")
                    if before is None:
                        self.assertFalse(audit_path.exists())
                    else:
                        self.assertEqual(audit_path.read_bytes(), before)

    def test_safe_state_path_rejects_absolute_traversal_backslash_and_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "state"
            outside = tmp_path / "outside"
            root.mkdir()
            outside.mkdir()
            (root / "tasks").mkdir()
            os.symlink(outside, root / "tasks" / "escape", target_is_directory=True)

            invalid_paths = [
                str(outside / "task-1.json"),
                "../outside/task-1.json",
                "tasks\\task-1.json",
                "tasks/escape/task-1.json",
            ]
            for relative_path in invalid_paths:
                with self.subTest(relative_path=relative_path):
                    with self.assertRaises(WorkflowStoreError) as raised:
                        safe_state_path(root, relative_path)
                    self.assertEqual(raised.exception.issue.code, "WORKFLOW_INVALID_INPUT")

            self.assertEqual(safe_state_path(root, "tasks/task-1/state.json"), root / "tasks" / "task-1" / "state.json")

    def test_write_state_atomic_replaces_complete_json_without_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "state" / "tasks" / "task-1" / "state.json"
            first = valid_task_state(audit_head_hash="1" * 64)
            second = valid_task_state(current_state="PLAN_READY", audit_head_hash="2" * 64)

            write_state_atomic(path, first)
            write_state_atomic(path, second)

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), second)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_store_writes_valid_state_and_rejects_invalid_state_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")

            state = valid_task_state()
            store.write_task_state(state)
            self.assertEqual(store.read_task_state("task-1"), state)

            with self.assertRaises(WorkflowStoreError) as raised:
                store.write_task_state(valid_task_state(current_state="UNKNOWN"))
            self.assertEqual(raised.exception.issue.code, "WORKFLOW_STATE_CORRUPT")

    def test_audit_append_does_not_rewrite_prior_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            first = valid_task_created_event()
            second = valid_task_created_event(
                event_id="event-2",
                generation=2,
                sequence=1,
                event_type="RECOVERY_RECORDED",
                actor="VERIFIER",
                details={
                    "recovery_id": "recovery-1",
                    "recovery_action": "quarantine_and_start_generation",
                    "recovery_transaction_id": "recovery-tx-1",
                    "previous_trusted_prefix": {
                        "generation": 1,
                        "sequence": 1,
                        "event_id": first["event_id"],
                        "event_hash": first["event_hash"],
                    },
                    "quarantine_path": "state/quarantine/task-1/recovery-1/audit-tail.bin",
                    "threat_model": "CORRUPTION_AND_NON_COORDINATED_TAMPER_ONLY",
                    "audit_generation": valid_audit_generation(
                        generation=2,
                        started_by_event_id="event-2",
                        started_by_event_type="RECOVERY_RECORDED",
                        predecessor_generation=1,
                        predecessor_valid_head_hash=first["event_hash"],
                        quarantine_path="state/quarantine/task-1/recovery-1/audit-tail.bin",
                    ),
                },
            )
            second["event_hash"] = canonical_sha(dict(second, event_hash=None))

            store.append_audit_event(first)
            before = store.audit_path("task-1", generation=1).read_bytes()
            store.append_audit_event(second)

            self.assertEqual(store.audit_path("task-1", generation=1).read_bytes(), before)
            self.assertEqual(len(store.audit_path("task-1", generation=2).read_text(encoding="utf-8").splitlines()), 1)

    def test_task_lock_rejects_contended_and_stale_locks_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            lock = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=100.0, stale_after_seconds=30.0)

            with self.assertRaises(WorkflowStoreError) as contended:
                store.acquire_task_lock("task-1", owner_id="owner-2", now_monotonic=101.0, stale_after_seconds=30.0)
            self.assertEqual(contended.exception.issue.code, "WORKFLOW_CONCURRENT_WRITE")

            with self.assertRaises(WorkflowStoreError) as stale:
                store.acquire_task_lock("task-1", owner_id="owner-2", now_monotonic=200.0, stale_after_seconds=30.0)
            self.assertEqual(stale.exception.issue.code, "WORKFLOW_CONCURRENT_WRITE")
            self.assertTrue(lock.path.exists(), "elapsed age alone must not steal a live holder")
            lock.release()

    def test_task2_r02_lock_instance_prevents_same_owner_aba_and_malformed_time_probes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            first = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=100.0, stale_after_seconds=30.0)
            with self.assertRaises(WorkflowStoreError) as held:
                store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=101.0, stale_after_seconds=30.0)
            self.assertEqual(held.exception.issue.code, "WORKFLOW_CONCURRENT_WRITE")
            first.release()
            second = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=101.0, stale_after_seconds=30.0)
            second.release()

            store.lock_path("task-2").parent.mkdir(parents=True, exist_ok=True)
            store.lock_path("task-2").write_text("{not json", encoding="utf-8")
            exported_lock = store.acquire_task_lock("task-2", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)
            exported_lock.release()

            for field, kwargs in (
                ("now_monotonic", {"now_monotonic": math.nan, "stale_after_seconds": 30.0}),
                ("stale_after_seconds", {"now_monotonic": 1.0, "stale_after_seconds": math.inf}),
                ("now_monotonic_bool", {"now_monotonic": True, "stale_after_seconds": 30.0}),
            ):
                with self.subTest(field=field):
                    with self.assertRaises(WorkflowStoreError) as invalid_time:
                        store.acquire_task_lock("task-3", owner_id="owner-1", **kwargs)
                    self.assertEqual(invalid_time.exception.issue.code, "WORKFLOW_INVALID_INPUT")

    def test_task2_r03_lock_release_and_stale_takeover_preserve_newer_live_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            first = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=100.0, stale_after_seconds=30.0)
            with self.assertRaises(WorkflowStoreError) as stale_takeover:
                store.acquire_task_lock("task-1", owner_id="owner-3", now_monotonic=1000.0, stale_after_seconds=30.0)
            self.assertEqual(stale_takeover.exception.issue.code, "WORKFLOW_CONCURRENT_WRITE")
            first.release()
            second = store.acquire_task_lock("task-1", owner_id="owner-3", now_monotonic=1000.0, stale_after_seconds=30.0)
            second.release()

    def test_persistence_rebase_lock_release_never_deletes_replacement_after_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            lock = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)

            def fail_if_unlink_called(path, *args, **kwargs):
                if path == lock.path:
                    raise AssertionError("lock release must not unlink the lock path")
                return Path.unlink(path, *args, **kwargs)

            with patch.object(Path, "unlink", fail_if_unlink_called):
                lock.release()

            self.assertTrue(lock.path.exists(), "release must not unlink a replacement lock record")
            replacement = store.acquire_task_lock("task-1", owner_id="owner-2", now_monotonic=2.0, stale_after_seconds=30.0)
            replacement.release()

    def test_task2_r02_path_safety_rejects_drive_prefix_and_broken_symlink_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "state"
            root.mkdir()
            (root / "tasks").mkdir()

            for relative_path in ("C:/outside/state.json", "C:outside/state.json"):
                with self.subTest(relative_path=relative_path):
                    with self.assertRaises(WorkflowStoreError) as raised:
                        safe_state_path(root, relative_path)
                    self.assertEqual(raised.exception.issue.code, "WORKFLOW_INVALID_INPUT")

            outside = tmp_path / "outside-not-created-yet"
            os.symlink(outside, root / "tasks" / "escape", target_is_directory=True)
            with self.assertRaises(WorkflowStoreError) as broken:
                safe_state_path(root, "tasks/escape/task-1/state.json")
            self.assertEqual(broken.exception.issue.code, "WORKFLOW_INVALID_INPUT")

            outside.mkdir()
            with self.assertRaises(WorkflowStoreError) as write_escape:
                write_state_atomic(root / "tasks" / "escape" / "task-1" / "state.json", valid_task_state())
            self.assertEqual(write_escape.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            self.assertFalse((outside / "task-1" / "state.json").exists())

    def test_task2_r03_mutating_operations_reject_operation_time_symlink_swaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "state"
            outside = tmp_path / "outside"
            store = WorkflowStore(root)

            state_parent = root / "tasks" / "task-1"
            original_os_open = os.open

            def swapping_state_open(path, *args, **kwargs):
                if Path(path).parent == state_parent:
                    replace_directory_with_symlink(state_parent, outside)
                return original_os_open(path, *args, **kwargs)

            with patch("acgps.workflow_store.os.open", side_effect=swapping_state_open):
                with self.assertRaises(WorkflowStoreError) as state_swap:
                    store.write_task_state(valid_task_state())
            self.assertEqual(state_swap.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            self.assertFalse((outside / "state.json").exists())

            audit_parent = root / "audit" / "task-1"
            original_mkdir = Path.mkdir

            def swapping_mkdir(path, *args, **kwargs):
                result = original_mkdir(path, *args, **kwargs)
                if path == audit_parent:
                    replace_directory_with_symlink(audit_parent, outside)
                return result

            with patch.object(Path, "mkdir", swapping_mkdir):
                with self.assertRaises(WorkflowStoreError) as audit_swap:
                    store.append_audit_event(valid_task_created_event())
            self.assertEqual(audit_swap.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            self.assertFalse((outside / "generation-000001.jsonl").exists())

            lock_parent = root / "locks"

            def lock_swapping_mkdir(path, *args, **kwargs):
                result = original_mkdir(path, *args, **kwargs)
                if path == lock_parent:
                    replace_directory_with_symlink(lock_parent, outside)
                return result

            with patch.object(Path, "mkdir", lock_swapping_mkdir):
                with self.assertRaises(WorkflowStoreError) as lock_swap:
                    store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)
            self.assertEqual(lock_swap.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            self.assertFalse((outside / "task-1.lock.json").exists())

            idem_parent = root / "idempotency" / "task-1" / "INITIALIZATION"

            def idem_swapping_mkdir(path, *args, **kwargs):
                result = original_mkdir(path, *args, **kwargs)
                if path == idem_parent:
                    replace_directory_with_symlink(idem_parent, outside)
                return result

            with patch.object(Path, "mkdir", idem_swapping_mkdir):
                with self.assertRaises(WorkflowStoreError) as idem_swap:
                    store.write_idempotency_record_once(valid_idempotency_record(), canonical_request=valid_initialization_request())
            self.assertEqual(idem_swap.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            self.assertEqual(list(outside.iterdir()), [])

    def test_persistence_rebase_rejects_final_scheduling_point_symlink_swaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "state"
            outside = tmp_path / "outside"
            store = WorkflowStore(root)

            state_parent = root / "tasks" / "task-1"
            original_os_open = os.open

            def swapping_state_open(path, *args, **kwargs):
                if Path(path).parent == state_parent:
                    replace_directory_with_symlink(state_parent, outside)
                return original_os_open(path, *args, **kwargs)

            with patch("acgps.workflow_store.os.open", side_effect=swapping_state_open):
                with self.assertRaises(WorkflowStoreError) as state_swap:
                    store.write_task_state(valid_task_state())
            self.assertEqual(state_swap.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            self.assertFalse((outside / "state.json").exists())

            audit_parent = root / "audit" / "task-1"
            original_os_open = os.open

            def swapping_open(path, *args, **kwargs):
                if path == audit_parent / "generation-000001.jsonl":
                    replace_directory_with_symlink(audit_parent, outside)
                return original_os_open(path, *args, **kwargs)

            with patch("acgps.workflow_store.os.open", side_effect=swapping_open):
                with self.assertRaises(WorkflowStoreError) as audit_swap:
                    store.append_audit_event(valid_task_created_event())
            self.assertEqual(audit_swap.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            self.assertFalse((outside / "generation-000001.jsonl").read_bytes() if (outside / "generation-000001.jsonl").exists() else b"")

            lock_parent = root / "locks"

            def lock_swapping_open(path, *args, **kwargs):
                if Path(path).parent == lock_parent:
                    replace_directory_with_symlink(lock_parent, outside)
                return original_os_open(path, *args, **kwargs)

            with patch("acgps.workflow_store.os.open", side_effect=lock_swapping_open):
                with self.assertRaises(WorkflowStoreError) as lock_swap:
                    store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)
            self.assertEqual(lock_swap.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            self.assertFalse((outside / "task-1.lock.json").read_bytes() if (outside / "task-1.lock.json").exists() else b"")

            idem_parent = root / "idempotency" / "task-1" / "INITIALIZATION"
            def idem_swapping_open(path, *args, **kwargs):
                if Path(path).parent == idem_parent:
                    replace_directory_with_symlink(idem_parent, outside)
                return original_os_open(path, *args, **kwargs)

            with patch("acgps.workflow_store.os.open", side_effect=idem_swapping_open):
                with self.assertRaises(WorkflowStoreError) as idem_swap:
                    store.write_idempotency_record_once(valid_idempotency_record(), canonical_request=valid_initialization_request())
            self.assertEqual(idem_swap.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            outside_files = list(outside.iterdir()) if outside.exists() else []
            self.assertTrue(all(path.read_bytes() == b"" for path in outside_files))

    def test_backend_rebase_lock_anchor_survives_transient_parent_redirection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "state"
            outside = tmp_path / "outside"
            store = WorkflowStore(root)
            lock_parent = root / "locks"
            original_os_open = os.open

            def transient_lock_open(path, *args, **kwargs):
                if Path(path) == lock_parent / "task-1.lock.json":
                    replace_directory_with_symlink(lock_parent, outside)
                    try:
                        return original_os_open(path, *args, **kwargs)
                    finally:
                        restore_directory(lock_parent)
                return original_os_open(path, *args, **kwargs)

            with patch("acgps.workflow_store.os.open", side_effect=transient_lock_open):
                try:
                    first = store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)
                except WorkflowStoreError as fail_closed:
                    self.assertEqual(fail_closed.issue.code, "WORKFLOW_INVALID_INPUT")
                    self.assertFalse((outside / "task-1.lock.json").exists())
                    return
            try:
                probe = (
                    "from pathlib import Path\n"
                    "from acgps.workflow_store import WorkflowStore, WorkflowStoreError\n"
                    f"store=WorkflowStore(Path({str(root)!r}))\n"
                    "try:\n"
                    "    lock=store.acquire_task_lock('task-1', owner_id='owner-2', now_monotonic=2.0, stale_after_seconds=30.0)\n"
                    "except WorkflowStoreError:\n"
                    "    raise SystemExit(0)\n"
                    "else:\n"
                    "    lock.release()\n"
                    "    raise SystemExit(7)\n"
                )
                completed = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=10)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            finally:
                first.release()

    def test_backend_rebase_rejects_transient_restore_before_post_open_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "state"
            outside = tmp_path / "outside"
            store = WorkflowStore(root)
            original_os_open = os.open

            def transient_restore_open(parent: Path, leaf: str):
                def _open(path, *args, **kwargs):
                    if Path(path).parent == parent:
                        replace_directory_with_symlink(parent, outside)
                        try:
                            return original_os_open(path, *args, **kwargs)
                        finally:
                            restore_directory(parent)
                    return original_os_open(path, *args, **kwargs)

                return _open

            audit_parent = root / "audit" / "task-1"
            with patch("acgps.workflow_store.os.open", side_effect=transient_restore_open(audit_parent, "generation-000001.jsonl")):
                with self.assertRaises(WorkflowStoreError) as audit_swap:
                    store.append_audit_event(valid_task_created_event())
            self.assertEqual(audit_swap.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            self.assertFalse((outside / "generation-000001.jsonl").exists())

            lock_parent = root / "locks"
            with patch("acgps.workflow_store.os.open", side_effect=transient_restore_open(lock_parent, "task-1.lock.json")):
                with self.assertRaises(WorkflowStoreError) as lock_swap:
                    store.acquire_task_lock("task-1", owner_id="owner-1", now_monotonic=1.0, stale_after_seconds=30.0)
            self.assertEqual(lock_swap.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            self.assertFalse((outside / "task-1.lock.json").exists())

            idem_parent = root / "state" / "transactions" / "task-1" / "initialization-init-1"
            canonical_request = valid_initialization_request()
            record = valid_idempotency_record(request_fingerprint=timestamp_free_request_fingerprint(canonical_request))
            with patch("acgps.workflow_store.os.open", side_effect=transient_restore_open(idem_parent, "canonical_request.json")):
                with self.assertRaises(WorkflowStoreError) as proof_swap:
                    store.write_idempotency_record_once(record, canonical_request=canonical_request)
            self.assertEqual(proof_swap.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            self.assertFalse((outside / "canonical_request.json").exists())

    def test_backend_rebase_state_publication_rejects_transient_restore_before_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            root = tmp_path / "state"
            outside = tmp_path / "outside"
            store = WorkflowStore(root)
            state_parent = root / "tasks" / "task-1"
            original_os_open = os.open

            def transient_restore_open(path, *args, **kwargs):
                if Path(path).parent == state_parent:
                    replace_directory_with_symlink(state_parent, outside)
                    try:
                        return original_os_open(path, *args, **kwargs)
                    finally:
                        restore_directory(state_parent)
                return original_os_open(path, *args, **kwargs)

            with patch("acgps.workflow_store.os.open", side_effect=transient_restore_open):
                with self.assertRaises(WorkflowStoreError) as state_swap:
                    store.write_task_state(valid_task_state())
            self.assertEqual(state_swap.exception.issue.code, "WORKFLOW_INVALID_INPUT")
            outside_files = list(outside.iterdir()) if outside.exists() else []
            self.assertTrue(all(path.read_bytes() == b"" for path in outside_files))

    def test_idempotency_record_is_create_once_and_conflicts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            record = valid_idempotency_record()
            path = store.operation_idempotency_path("task-1", "INITIALIZATION", "idem-1")

            store.write_idempotency_record_once(record, canonical_request=valid_initialization_request())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), record)
            self.assertEqual(store.write_idempotency_record_once(dict(record), canonical_request=valid_initialization_request()), record)

            conflict_result = dict(record["canonical_result"], audit_event_id="event-2")
            conflict = dict(record, canonical_result=conflict_result, result_fingerprint=canonical_sha(conflict_result))
            with self.assertRaises(WorkflowStoreError) as raised:
                store.write_idempotency_record_once(conflict, canonical_request=valid_initialization_request())
            self.assertEqual(raised.exception.issue.code, "WORKFLOW_IDEMPOTENCY_CONFLICT")

    def test_task2_r02_idempotency_rejects_semantic_corruption_and_replays_stable_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            record = valid_idempotency_record()

            invalid_result = dict(record, result_fingerprint="0" * 64)
            with self.assertRaises(WorkflowStoreError) as bad_result_hash:
                store.write_idempotency_record_once(invalid_result)
            self.assertEqual(bad_result_hash.exception.issue.code, "WORKFLOW_INVALID_INPUT")

            invalid_time = dict(record, created_at_utc="not-a-time")
            with self.assertRaises(WorkflowStoreError) as bad_time:
                store.write_idempotency_record_once(invalid_time)
            self.assertEqual(bad_time.exception.issue.code, "WORKFLOW_INVALID_INPUT")

            impossible_time = dict(record, created_at_utc="2026-99-99T99:99:99Z")
            with self.assertRaises(WorkflowStoreError) as impossible_calendar:
                store.write_idempotency_record_once(impossible_time)
            self.assertEqual(impossible_calendar.exception.issue.code, "WORKFLOW_INVALID_INPUT")

            arbitrary_fingerprint = dict(record, request_fingerprint="9" * 64)
            with self.assertRaises(WorkflowStoreError) as bad_request_fingerprint:
                store.write_idempotency_record_once(arbitrary_fingerprint, canonical_request=valid_initialization_request())
            self.assertEqual(bad_request_fingerprint.exception.issue.code, "WORKFLOW_INVALID_INPUT")

            wrong_task_path = dict(record, transaction_path="state/transactions/other-task/initialization-init-1")
            with self.assertRaises(WorkflowStoreError) as wrong_path:
                store.write_idempotency_record_once(wrong_task_path, canonical_request=valid_initialization_request())
            self.assertEqual(wrong_path.exception.issue.code, "WORKFLOW_INVALID_INPUT")

            journal_file_path = dict(record, transaction_path="state/transactions/task-1/initialization-init-1/phases.0001.jsonl")
            with self.assertRaises(WorkflowStoreError) as journal_path:
                store.write_idempotency_record_once(journal_file_path, canonical_request=valid_initialization_request())
            self.assertEqual(journal_path.exception.issue.code, "WORKFLOW_INVALID_INPUT")

            store.write_idempotency_record_once(record, canonical_request=valid_initialization_request())
            replay = dict(record, created_at_utc="2026-07-28T12:00:01Z")
            self.assertEqual(store.write_idempotency_record_once(replay, canonical_request=valid_initialization_request()), record)

            wrong_key_record = dict(record, idempotency_key="key-b")
            wrong_key_request = valid_initialization_request(idempotency_key="key-b")
            wrong_key_record["request_fingerprint"] = canonical_sha(wrong_key_request)
            wrong_key_identity = {key: value for key, value in wrong_key_record.items() if key != "created_at_utc"}
            key_a_digest = hashlib.sha256("key-a".encode("utf-8")).hexdigest()
            connection = sqlite3.connect(store.control_store_path)
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
                        "task-1",
                        "INITIALIZATION",
                        key_a_digest,
                        "key-b",
                        json.dumps(wrong_key_identity, sort_keys=True, separators=(",", ":")),
                        json.dumps(wrong_key_record, sort_keys=True, separators=(",", ":")),
                        json.dumps(wrong_key_request, sort_keys=True, separators=(",", ":")),
                    ),
                )
                connection.commit()
            finally:
                connection.close()
            with self.assertRaises(WorkflowStoreError) as wrong_key_read:
                read_idempotency_record(store.state_root, "task-1", "INITIALIZATION", "key-a")
            self.assertEqual(wrong_key_read.exception.issue.code, "WORKFLOW_IDEMPOTENCY_CONFLICT")

            path = store.operation_idempotency_path("task-2", "INITIALIZATION", "idem-1")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"schema_version":1', encoding="utf-8")
            task2_result = dict(record["canonical_result"], task_id="task-2")
            corrupt_record = dict(
                record,
                task_id="task-2",
                canonical_result=task2_result,
                result_fingerprint=canonical_sha(task2_result),
                transaction_path="state/transactions/task-2/initialization-init-1",
            )
            corrupt_record["request_fingerprint"] = timestamp_free_request_fingerprint(valid_initialization_request(task_id="task-2"))
            with self.assertRaises(WorkflowStoreError) as corrupt:
                store.write_idempotency_record_once(corrupt_record, canonical_request=valid_initialization_request(task_id="task-2"))
            self.assertEqual(corrupt.exception.issue.code, "WORKFLOW_IDEMPOTENCY_CONFLICT")

            path.write_bytes(b"\xff")
            with self.assertRaises(WorkflowStoreError) as invalid_utf8:
                store.write_idempotency_record_once(corrupt_record, canonical_request=valid_initialization_request(task_id="task-2"))
            self.assertEqual(invalid_utf8.exception.issue.code, "WORKFLOW_IDEMPOTENCY_CONFLICT")

            fresh_record = valid_idempotency_record(idempotency_key="idem-2")
            fresh_request = valid_initialization_request(idempotency_key="idem-2")
            fresh_record["request_fingerprint"] = timestamp_free_request_fingerprint(fresh_request)
            fresh_path = store.operation_idempotency_path("task-1", "INITIALIZATION", "idem-2")
            original_os_open = os.open

            def deny_idempotency_publish(path, flags, *args, **kwargs):
                if Path(path) == fresh_path:
                    raise PermissionError("publication denied")
                return original_os_open(path, flags, *args, **kwargs)

            with patch("acgps.workflow_store.os.open", side_effect=deny_idempotency_publish):
                with self.assertRaises(WorkflowStoreError) as publication_error:
                    store.write_idempotency_record_once(fresh_record, canonical_request=fresh_request)
            self.assertEqual(publication_error.exception.issue.code, "WORKFLOW_IDEMPOTENCY_CONFLICT")

    def test_persistence_rebase_requires_canonical_request_proof_for_idempotency(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            canonical_request = valid_initialization_request()
            record = valid_idempotency_record(request_fingerprint=timestamp_free_request_fingerprint(canonical_request))

            low_level_fingerprint = valid_request_fingerprint(record)
            self.assertNotEqual(low_level_fingerprint, timestamp_free_request_fingerprint(canonical_request))
            low_level_record = dict(record, request_fingerprint=low_level_fingerprint)
            with self.assertRaises(WorkflowStoreError) as low_level:
                store.write_idempotency_record_once(low_level_record)
            self.assertEqual(low_level.exception.issue.code, "WORKFLOW_INVALID_INPUT")

            store.write_idempotency_record_once(record, canonical_request=canonical_request)
            different_intake = {"intake_id": "intake-2", "title": "Task 2"}
            different_payload = canonical_json_bytes(different_intake)
            different_request = valid_initialization_request(
                task_intake_binding={
                    "schema_version": 1,
                    "binding_id": "intake-binding-2",
                    "evidence_kind": "task_intake",
                    "source": "embedded",
                    "path": None,
                    "embedded_record": different_intake,
                    "embedded_sha256": hashlib.sha256(different_payload).hexdigest(),
                    "content_sha256": hashlib.sha256(different_payload).hexdigest(),
                    "size_bytes": len(different_payload),
                    "created_at_utc": "2026-07-28T12:00:00Z",
                }
            )
            replay = dict(record, request_fingerprint=timestamp_free_request_fingerprint(different_request))
            with self.assertRaises(WorkflowStoreError) as different:
                store.write_idempotency_record_once(replay, canonical_request=different_request)
            self.assertEqual(different.exception.issue.code, "WORKFLOW_IDEMPOTENCY_CONFLICT")

    def test_backend_rebase_uses_task1_timestamp_free_request_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            canonical_request = valid_initialization_request(created_at_utc="2026-07-28T12:00:00Z")
            same_request_later = dict(canonical_request, created_at_utc="2026-07-28T12:00:01Z")
            fingerprint = timestamp_free_request_fingerprint(canonical_request)
            self.assertEqual(fingerprint, timestamp_free_request_fingerprint(same_request_later))
            self.assertNotEqual(fingerprint, canonical_sha(canonical_request))

            record = valid_idempotency_record(request_fingerprint=fingerprint)
            store.write_idempotency_record_once(record, canonical_request=canonical_request)
            replay = dict(record, created_at_utc="2026-07-28T12:00:01Z")
            self.assertEqual(store.write_idempotency_record_once(replay, canonical_request=same_request_later), record)

    def test_backend_rebase_conflicting_request_cannot_poison_existing_proof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            planner_request = valid_initialization_request(actor="PLANNER")
            planner_record = valid_idempotency_record(request_fingerprint=timestamp_free_request_fingerprint(planner_request))
            proof_path = store.state_root / planner_record["transaction_path"] / "canonical_request.json"

            store.write_idempotency_record_once(planner_record, canonical_request=planner_request)
            before = proof_path.read_bytes()

            coder_request = valid_initialization_request(actor="CODER")
            coder_record = dict(planner_record, request_fingerprint=timestamp_free_request_fingerprint(coder_request))
            with self.assertRaises(WorkflowStoreError) as conflict:
                store.write_idempotency_record_once(coder_record, canonical_request=coder_request)
            self.assertEqual(conflict.exception.issue.code, "WORKFLOW_IDEMPOTENCY_CONFLICT")
            self.assertEqual(proof_path.read_bytes(), before)
            self.assertEqual(read_idempotency_record(store.state_root, "task-1", "INITIALIZATION", "idem-1"), planner_record)

    def test_coding_execution_slot_atomically_installs_one_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            initialized = store.initialize_coding_execution_slot("GATE-1", "TASK-1")
            self.assertEqual(
                initialized,
                {
                    "gate_id": "GATE-1",
                    "task_id": "TASK-1",
                    "gate_binding": None,
                    "state": "EMPTY",
                    "remaining_attempts": 2,
                    "active_candidate_id": None,
                    "historical_candidate_ids": [],
                    "remediation_authorization_id": None,
                    "reserved_attempt": None,
                },
            )

            reservation = store.reserve_coding_execution_attempt(
                "GATE-1",
                kind="ORDINARY",
                parent_candidate_id=None,
                reserved_at_utc="2026-08-24T00:00:00.000Z",
            )
            self.assertEqual(reservation["number"], 1)
            self.assertEqual(reservation["remaining_after"], 1)

            record = _valid_candidate_ready_coding_execution_record()
            published = store.publish_coding_execution_record(record)
            self.assertEqual(published["state"], "FROZEN_REVIEW_V1")
            self.assertEqual(published["active_candidate_id"], "CANDIDATE-1")
            self.assertEqual(published["remaining_attempts"], 1)
            self.assertIsNone(published["reserved_attempt"])
            self.assertEqual(store.read_coding_execution_record("GATE-1", "EXECUTION-1"), record)

            replay = store.publish_coding_execution_record(record)
            self.assertEqual(replay, published)

            conflicting = _valid_candidate_ready_coding_execution_record()
            conflicting["execution_id"] = "EXECUTION-2"
            candidate = conflicting["candidate"]
            slot = conflicting["slot"]
            assert isinstance(candidate, dict) and isinstance(slot, dict)
            candidate["candidate_id"] = "CANDIDATE-2"
            slot["active_candidate_after"] = "CANDIDATE-2"
            with self.assertRaises(WorkflowStoreError):
                store.publish_coding_execution_record(conflicting)

            unchanged = store.read_coding_execution_slot("GATE-1")
            self.assertEqual(unchanged["active_candidate_id"], "CANDIDATE-1")
            self.assertEqual(unchanged["remaining_attempts"], 1)

    def test_coding_execution_prelaunch_hold_does_not_consume_attempt_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            before = store.initialize_coding_execution_slot("GATE-1", "TASK-1")
            record = _valid_prelaunch_hold_coding_execution_record()

            after = store.publish_coding_execution_record(record)

            self.assertEqual(after["state"], before["state"])
            self.assertEqual(after["remaining_attempts"], 2)
            self.assertIsNone(after["reserved_attempt"])
            self.assertEqual(store.read_coding_execution_record("GATE-1", "EXECUTION-1"), record)

    def test_coding_execution_attempt_budget_is_absolute(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            store.initialize_coding_execution_slot("GATE-1", "TASK-1")

            for number, before, after in ((1, 2, 1), (2, 1, 0)):
                reservation = store.reserve_coding_execution_attempt(
                    "GATE-1",
                    kind="ORDINARY",
                    parent_candidate_id=None,
                    reserved_at_utc=f"2026-08-24T00:00:0{number}.000Z",
                )
                self.assertEqual(reservation["number"], number)
                self.assertEqual(reservation["remaining_before"], before)
                self.assertEqual(reservation["remaining_after"], after)

                record = _valid_candidate_ready_coding_execution_record()
                record["execution_id"] = f"EXECUTION-{number}"
                attempt = record["attempt"]
                slot = record["slot"]
                agent_result = record["agent_result"]
                candidate = record["candidate"]
                assert isinstance(attempt, dict)
                assert isinstance(slot, dict)
                assert isinstance(agent_result, dict)
                assert isinstance(candidate, dict)
                attempt.update(
                    {
                        "number": number,
                        "reserved_at_utc": f"2026-08-24T00:00:0{number}.000Z",
                        "remaining_before": before,
                        "remaining_after": after,
                    }
                )
                slot.update(
                    {
                        "state_before": "EMPTY",
                        "state_after": "EMPTY",
                        "active_candidate_after": None,
                    }
                )
                agent_result["claimed_status"] = "BLOCKED"
                candidate.update(
                    {
                        "candidate_id": None,
                        "version": None,
                        "status": "NONE",
                        "diff_sha256": None,
                        "file_set_sha256": None,
                        "checks_sha256": None,
                        "promotion_predicates_passed": False,
                    }
                )
                record["outcome"] = "ATTEMPT_HOLD"
                store.publish_coding_execution_record(record)

            with self.assertRaises(WorkflowStoreError) as raised:
                store.reserve_coding_execution_attempt(
                    "GATE-1",
                    kind="ORDINARY",
                    parent_candidate_id=None,
                    reserved_at_utc="2026-08-24T00:00:03.000Z",
                )
            self.assertEqual(raised.exception.issue.code, "WORKFLOW_BUDGET_EXHAUSTED")
            self.assertEqual(store.read_coding_execution_slot("GATE-1")["remaining_attempts"], 0)

    def test_coding_execution_gate_rejects_identity_drift_between_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            store.initialize_coding_execution_slot("GATE-1", "TASK-1")
            store.reserve_coding_execution_attempt(
                "GATE-1",
                kind="ORDINARY",
                parent_candidate_id=None,
                reserved_at_utc="2026-08-24T00:00:00.000Z",
            )
            first = _valid_attempt_hold_coding_execution_record()
            store.publish_coding_execution_record(first)
            store.reserve_coding_execution_attempt(
                "GATE-1",
                kind="ORDINARY",
                parent_candidate_id=None,
                reserved_at_utc="2026-08-24T00:01:00.000Z",
            )
            drifted = _valid_attempt_hold_coding_execution_record()
            drifted["execution_id"] = "EXECUTION-2"
            attempt = drifted["attempt"]
            baseline = drifted["baseline"]
            assert isinstance(attempt, dict) and isinstance(baseline, dict)
            attempt.update(
                {
                    "number": 2,
                    "reserved_at_utc": "2026-08-24T00:01:00.000Z",
                    "remaining_before": 1,
                    "remaining_after": 0,
                }
            )
            baseline["repository_path"] = r"D:\other\repository"

            with self.assertRaises(WorkflowStoreError):
                store.publish_coding_execution_record(drifted)

    def test_coding_execution_remediation_requires_explicit_candidate_retirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            store.initialize_coding_execution_slot("GATE-1", "TASK-1")
            store.reserve_coding_execution_attempt(
                "GATE-1",
                kind="ORDINARY",
                parent_candidate_id=None,
                reserved_at_utc="2026-08-24T00:00:00.000Z",
            )
            store.publish_coding_execution_record(_valid_candidate_ready_coding_execution_record())

            with self.assertRaises(WorkflowStoreError):
                store.reserve_coding_execution_attempt(
                    "GATE-1",
                    kind="REMEDIATION",
                    parent_candidate_id="CANDIDATE-1",
                    reserved_at_utc="2026-08-24T00:01:00.000Z",
                )

            retired = store.retire_coding_execution_candidate_for_remediation(
                "GATE-1",
                "CANDIDATE-1",
                authorization_id="AUTH-REMEDIATION-1",
            )
            self.assertEqual(retired["state"], "EMPTY_FOR_REMEDIATION")
            self.assertIsNone(retired["active_candidate_id"])
            self.assertEqual(retired["historical_candidate_ids"], ["CANDIDATE-1"])
            self.assertEqual(retired["remediation_authorization_id"], "AUTH-REMEDIATION-1")

            reservation = store.reserve_coding_execution_attempt(
                "GATE-1",
                kind="REMEDIATION",
                parent_candidate_id="CANDIDATE-1",
                reserved_at_utc="2026-08-24T00:01:00.000Z",
            )
            self.assertEqual(reservation["number"], 2)
            self.assertEqual(reservation["remaining_after"], 0)
            self.assertEqual(reservation["parent_candidate_id"], "CANDIDATE-1")

            record = _valid_candidate_ready_coding_execution_record()
            record["execution_id"] = "EXECUTION-2"
            attempt = record["attempt"]
            slot = record["slot"]
            candidate = record["candidate"]
            assert isinstance(attempt, dict) and isinstance(slot, dict) and isinstance(candidate, dict)
            attempt.update(
                {
                    "number": 2,
                    "reserved_at_utc": "2026-08-24T00:01:00.000Z",
                    "parent_candidate_id": "CANDIDATE-1",
                    "kind": "REMEDIATION",
                    "remaining_before": 1,
                    "remaining_after": 0,
                }
            )
            slot.update(
                {
                    "state_before": "EMPTY_FOR_REMEDIATION",
                    "state_after": "FROZEN_REVIEW_V2",
                    "active_candidate_before": None,
                    "active_candidate_after": "CANDIDATE-2",
                    "historical_candidate_ids": ["CANDIDATE-1"],
                }
            )
            candidate.update(
                {
                    "candidate_id": "CANDIDATE-2",
                    "version": 2,
                    "parent_candidate_id": "CANDIDATE-1",
                }
            )
            published = store.publish_coding_execution_record(record)
            self.assertEqual(published["state"], "FROZEN_REVIEW_V2")
            self.assertEqual(published["active_candidate_id"], "CANDIDATE-2")
            self.assertEqual(published["remaining_attempts"], 0)

    def test_coding_execution_publication_failure_preserves_reserved_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = WorkflowStore(Path(tmp) / "state")
            store.initialize_coding_execution_slot("GATE-1", "TASK-1")
            store.reserve_coding_execution_attempt(
                "GATE-1",
                kind="ORDINARY",
                parent_candidate_id=None,
                reserved_at_utc="2026-08-24T00:00:00.000Z",
            )

            with patch("acgps.workflow_store.write_state_atomic", side_effect=OSError("publication denied")):
                with self.assertRaises(OSError):
                    store.publish_coding_execution_record(_valid_candidate_ready_coding_execution_record())

            state = store.read_coding_execution_slot("GATE-1")
            self.assertEqual(state["state"], "EMPTY")
            self.assertEqual(state["remaining_attempts"], 1)
            self.assertEqual(state["reserved_attempt"]["number"], 1)
            with self.assertRaises(WorkflowStoreError):
                store.read_coding_execution_record("GATE-1", "EXECUTION-1")


if __name__ == "__main__":
    unittest.main()
