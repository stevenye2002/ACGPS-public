from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from acgps.contracts import TASK_STATES, ContractValidationError, validate_contract
from acgps.workflow_errors import WORKFLOW_ERROR_CODES
from acgps.yaml_loader import load_yaml_strict


ACTORS = {"PLANNER", "CODER", "REVIEWER", "VERIFIER", "CONTROLLER", "HUMAN"}
HUMAN_RESUME_ACTORS = {"CONTROLLER", "HUMAN"}
RECOVERY_ACTORS = {"CONTROLLER", "HUMAN", "VERIFIER"}
SOURCES = {"path", "embedded"}
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
EVENT_TYPES = {"TASK_CREATED", "TRANSITION_ACCEPTED", "RECOVERY_RECORDED", "ROLLBACK_RECORDED"}
RECOVERY_ACTIONS = {"replay", "quarantine_and_start_generation", "rollback_to_valid_prefix", "classify_threat_model_limit"}
RECOVERY_EVENT_TYPES = {"RECOVERY_RECORDED", "ROLLBACK_RECORDED"}
THREAT_MODELS = {"CORRUPTION_AND_NON_COORDINATED_TAMPER_ONLY"}
TRANSITION_OPERATION_KINDS = {"INITIALIZATION", "TRANSITION"}
RECOVERY_OPERATION_KINDS = {"RECOVERY", "ROLLBACK"}
TRANSITION_PHASES = {"PREPARED", "AUDIT_APPENDED", "STATE_REPLACED", "IDEMPOTENCY_RECORDED", "COMMITTED", "ABORTED"}
RECOVERY_PHASES = {
    "PREPARED",
    "QUARANTINE_WRITTEN",
    "RECOVERY_RECORD_WRITTEN",
    "GENERATION_STARTED",
    "STATE_REPLACED",
    "RESULT_RECORDED",
    "COMMITTED",
    "ABORTED",
}
RECOVERY_PLANNED_HASH_KEYS = {
    "request",
    "result",
    "quarantine",
    "recovery_record",
    "generation_event",
    "state",
    "idempotency_record",
}
HUMAN_GATE_AUTHORIZED_TRANSITIONS = {"WAITING_HUMAN", "ABANDONED"}


@dataclass(frozen=True)
class WorkflowIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class WorkflowValidationOutcome:
    valid: bool
    error_code: str | None
    issues: tuple[WorkflowIssue, ...]


@dataclass(frozen=True)
class WorkflowTransitionResult:
    schema_version: int
    transition_id: str
    task_id: str
    accepted: bool
    resulting_state: str | None
    audit_event_id: str | None
    fail_closed: bool
    error_code: str | None
    issues: tuple[WorkflowIssue, ...]
    idempotent_replay: bool
    created_at_utc: str


@dataclass(frozen=True)
class WorkflowTaskInitializationRequest:
    schema_version: int
    initialization_id: str
    task_id: str
    project_id: str
    initial_state: str
    actor: str
    idempotency_key: str
    task_intake_binding: dict[str, Any]
    created_at_utc: str


@dataclass(frozen=True)
class WorkflowTaskInitializationResult:
    schema_version: int
    initialization_id: str
    task_id: str
    project_id: str
    accepted: bool
    resulting_state: str | None
    audit_event_id: str | None
    audit_generation: int | None
    audit_sequence: int | None
    fail_closed: bool
    error_code: str | None
    issues: tuple[WorkflowIssue, ...]
    idempotent_replay: bool
    created_at_utc: str


@dataclass(frozen=True)
class WorkflowTaskState:
    schema_version: int
    task_id: str
    project_id: str
    current_state: str
    previous_state: str | None
    last_transition_id: str | None
    audit_generation: int
    audit_head_event_id: str
    audit_head_hash: str
    policy_evaluation_id: str | None
    pending_decision_id: str | None
    updated_at_utc: str


@dataclass(frozen=True)
class EvidenceBinding:
    schema_version: int
    binding_id: str
    evidence_kind: str
    source: str
    path: str | None
    embedded_record: Any
    embedded_sha256: str | None
    content_sha256: str
    size_bytes: int
    created_at_utc: str | None


@dataclass(frozen=True)
class PolicyEvaluationBinding:
    schema_version: int
    evaluation_id: str
    source: str
    path: str | None
    embedded_record: dict[str, Any] | None
    result_sha256: str
    policy_bundle_digest: str
    authorized_transitions: list[str]
    human_gate: bool
    created_at_utc: str | None


@dataclass(frozen=True)
class HumanDecisionResolutionBinding:
    schema_version: int
    decision_id: str
    project_id: str
    task_id: str
    status: str
    authorized_target_state: str
    source: str
    path: str | None
    embedded_record: dict[str, Any] | None
    resolution_sha256: str
    resolved_at_utc: str


@dataclass(frozen=True)
class WorkflowTransitionRequest:
    schema_version: int
    transition_id: str
    task_id: str
    project_id: str
    from_state: str
    to_state: str
    actor: str
    idempotency_key: str
    policy_evaluation_binding: dict[str, Any]
    evidence_bindings: list[dict[str, Any]]
    decision_resolution_binding: dict[str, Any] | None
    created_at_utc: str


@dataclass(frozen=True)
class WorkflowAuditEvent:
    schema_version: int
    event_id: str
    generation: int
    sequence: int
    project_id: str
    task_id: str
    event_type: str
    actor: str
    from_state: str | None
    to_state: str | None
    transition_id: str | None
    policy_evaluation_binding: dict[str, Any] | None
    evidence_bindings: list[dict[str, Any]]
    decision_resolution_binding: dict[str, Any] | None
    previous_event_hash: str | None
    event_hash: str
    created_at_utc: str
    details: dict[str, Any]


@dataclass(frozen=True)
class WorkflowTransitionTransaction:
    schema_version: int
    transaction_id: str
    operation_kind: str
    operation_id: str
    initialization_id: str | None
    transition_id: str | None
    task_id: str
    idempotency_key: str
    request_fingerprint: str
    phase_journal_path: str
    phase_journal_index_path: str
    first_journal_segment_id: str
    latest_phase: str
    canonical_request: dict[str, Any]
    planned_audit_event: dict[str, Any]
    planned_state: dict[str, Any]
    canonical_result: dict[str, Any]
    planned_audit_event_hash: str
    planned_state_hash: str
    planned_result_hash: str
    created_at_utc: str
    updated_at_utc: str


@dataclass(frozen=True)
class WorkflowRecoveryTransaction:
    schema_version: int
    transaction_id: str
    operation_kind: str
    operation_id: str
    task_id: str
    idempotency_key: str
    canonical_recovery_request: dict[str, Any]
    canonical_recovery_result: dict[str, Any]
    planned_quarantine_manifest: dict[str, Any] | None
    planned_recovery_record: dict[str, Any]
    planned_generation_event: dict[str, Any] | None
    planned_state: dict[str, Any] | None
    planned_idempotency_record: dict[str, Any] | None
    planned_hashes: dict[str, Any]
    phase_journal_path: str
    phase_journal_index_path: str
    created_at_utc: str


@dataclass(frozen=True)
class WorkflowRecoveryRequest:
    schema_version: int
    recovery_id: str
    task_id: str
    project_id: str
    actor: str
    idempotency_key: str
    recovery_action: str
    observed_state_path: str | None
    observed_audit_generation: int | None
    observed_audit_path: str | None
    requested_at_utc: str


@dataclass(frozen=True)
class WorkflowRecoveryResult:
    schema_version: int
    recovery_id: str
    task_id: str
    project_id: str
    accepted: bool
    fail_closed: bool
    error_code: str | None
    issues: tuple[WorkflowIssue, ...]
    quarantine_path: str | None
    previous_generation: int | None
    previous_valid_head_hash: str | None
    new_generation: int | None
    started_by_event_id: str | None
    started_by_event_type: str | None
    resulting_state: str | None
    created_at_utc: str


@dataclass(frozen=True)
class WorkflowAuditGeneration:
    schema_version: int
    task_id: str
    generation: int
    predecessor_generation: int | None
    predecessor_valid_head_hash: str | None
    quarantine_path: str | None
    started_by_event_id: str
    started_by_event_type: str
    threat_model: str
    created_at_utc: str


@dataclass(frozen=True)
class WorkflowRecoveryDiagnostic:
    recovery_reason: str
    previous_trusted_prefix: dict[str, Any]
    threat_model: str
    stale_phase_classification: str


@dataclass(frozen=True)
class WorkflowRecoveryRecord:
    schema_version: int
    recovery_id: str
    task_id: str
    project_id: str
    operation_kind: str
    canonical_recovery_request_sha256: str
    canonical_recovery_result_sha256: str
    quarantine_manifest_sha256: str | None
    generation_event_sha256: str | None
    state_sha256: str | None
    diagnostic: dict[str, Any]
    record_sha256: str
    created_at_utc: str


@dataclass(frozen=True)
class WorkflowIdempotencyRecord:
    schema_version: int
    operation_kind: str
    operation_id: str
    task_id: str
    idempotency_key: str
    request_fingerprint: str
    result_fingerprint: str
    canonical_result: dict[str, Any]
    transaction_path: str
    created_at_utc: str


TRANSITION_REQUEST_FIELDS = {
    "schema_version",
    "transition_id",
    "task_id",
    "project_id",
    "from_state",
    "to_state",
    "actor",
    "idempotency_key",
    "policy_evaluation_binding",
    "evidence_bindings",
    "decision_resolution_binding",
    "created_at_utc",
}
EVIDENCE_BINDING_FIELDS = {
    "schema_version",
    "binding_id",
    "evidence_kind",
    "source",
    "path",
    "embedded_record",
    "embedded_sha256",
    "content_sha256",
    "size_bytes",
    "created_at_utc",
}
POLICY_BINDING_FIELDS = {
    "schema_version",
    "evaluation_id",
    "source",
    "path",
    "embedded_record",
    "result_sha256",
    "policy_bundle_digest",
    "authorized_transitions",
    "human_gate",
    "created_at_utc",
}
DECISION_BINDING_FIELDS = {
    "schema_version",
    "decision_id",
    "project_id",
    "task_id",
    "status",
    "authorized_target_state",
    "source",
    "path",
    "embedded_record",
    "resolution_sha256",
    "resolved_at_utc",
}
TRANSITION_RESULT_FIELDS = {
    "schema_version",
    "transition_id",
    "task_id",
    "accepted",
    "resulting_state",
    "audit_event_id",
    "fail_closed",
    "error_code",
    "issues",
    "idempotent_replay",
    "created_at_utc",
}
INITIALIZATION_REQUEST_FIELDS = {
    "schema_version",
    "initialization_id",
    "task_id",
    "project_id",
    "initial_state",
    "actor",
    "idempotency_key",
    "task_intake_binding",
    "created_at_utc",
}
INITIALIZATION_RESULT_FIELDS = {
    "schema_version",
    "initialization_id",
    "task_id",
    "project_id",
    "accepted",
    "resulting_state",
    "audit_event_id",
    "audit_generation",
    "audit_sequence",
    "fail_closed",
    "error_code",
    "issues",
    "idempotent_replay",
    "created_at_utc",
}
TASK_STATE_FIELDS = {
    "schema_version",
    "task_id",
    "project_id",
    "current_state",
    "previous_state",
    "last_transition_id",
    "audit_generation",
    "audit_head_event_id",
    "audit_head_hash",
    "policy_evaluation_id",
    "pending_decision_id",
    "updated_at_utc",
}
AUDIT_EVENT_FIELDS = {
    "schema_version",
    "event_id",
    "generation",
    "sequence",
    "project_id",
    "task_id",
    "event_type",
    "actor",
    "from_state",
    "to_state",
    "transition_id",
    "policy_evaluation_binding",
    "evidence_bindings",
    "decision_resolution_binding",
    "previous_event_hash",
    "event_hash",
    "created_at_utc",
    "details",
}
TRANSITION_TRANSACTION_FIELDS = {
    "schema_version",
    "transaction_id",
    "operation_kind",
    "operation_id",
    "initialization_id",
    "transition_id",
    "task_id",
    "idempotency_key",
    "request_fingerprint",
    "phase_journal_path",
    "phase_journal_index_path",
    "first_journal_segment_id",
    "latest_phase",
    "canonical_request",
    "planned_audit_event",
    "planned_state",
    "canonical_result",
    "planned_audit_event_hash",
    "planned_state_hash",
    "planned_result_hash",
    "created_at_utc",
    "updated_at_utc",
}
RECOVERY_TRANSACTION_FIELDS = {
    "schema_version",
    "transaction_id",
    "operation_kind",
    "operation_id",
    "task_id",
    "idempotency_key",
    "canonical_recovery_request",
    "canonical_recovery_result",
    "planned_quarantine_manifest",
    "planned_recovery_record",
    "planned_generation_event",
    "planned_state",
    "planned_idempotency_record",
    "planned_hashes",
    "phase_journal_path",
    "phase_journal_index_path",
    "created_at_utc",
}
QUARANTINE_MANIFEST_FIELDS = {
    "source_path",
    "destination_path",
    "size_bytes",
    "content_sha256",
}
TRUSTED_PREFIX_FIELDS = {
    "generation",
    "sequence",
    "event_id",
    "event_hash",
}
RECOVERY_DIAGNOSTIC_FIELDS = {
    "recovery_reason",
    "previous_trusted_prefix",
    "threat_model",
    "stale_phase_classification",
}
RECOVERY_RECORD_FIELDS = {
    "schema_version",
    "recovery_id",
    "task_id",
    "project_id",
    "operation_kind",
    "canonical_recovery_request_sha256",
    "canonical_recovery_result_sha256",
    "quarantine_manifest_sha256",
    "generation_event_sha256",
    "state_sha256",
    "diagnostic",
    "record_sha256",
    "created_at_utc",
}
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
RECOVERY_REQUEST_FIELDS = {
    "schema_version",
    "recovery_id",
    "task_id",
    "project_id",
    "actor",
    "idempotency_key",
    "recovery_action",
    "observed_state_path",
    "observed_audit_generation",
    "observed_audit_path",
    "requested_at_utc",
}
RECOVERY_RESULT_FIELDS = {
    "schema_version",
    "recovery_id",
    "task_id",
    "project_id",
    "accepted",
    "fail_closed",
    "error_code",
    "issues",
    "quarantine_path",
    "previous_generation",
    "previous_valid_head_hash",
    "new_generation",
    "started_by_event_id",
    "started_by_event_type",
    "resulting_state",
    "created_at_utc",
}
AUDIT_GENERATION_FIELDS = {
    "schema_version",
    "task_id",
    "generation",
    "predecessor_generation",
    "predecessor_valid_head_hash",
    "quarantine_path",
    "started_by_event_id",
    "started_by_event_type",
    "threat_model",
    "created_at_utc",
}
STALE_PHASE_CLASSIFICATIONS = {
    "NONE",
    "RECORD_EXISTS_PHASE_MISSING",
    "PHASE_EXISTS_RECORD_MISSING",
    "RECORD_HASH_MISMATCH",
    "GENERATION_EVENT_EXISTS_PHASE_MISSING",
    "STATE_EXISTS_PHASE_MISSING",
    "RESULT_RECORD_EXISTS_PHASE_MISSING",
}

_RECOVERY_MATRIX_CACHE: dict[str, Any] | None = None
_TASK1_INVARIANTS_CACHE: dict[str, Any] | None = None
TASK1_ALLOWED_INVARIANT_DSL_OPCODES = {
    "equal",
    "must_be_null",
    "must_be_non_null",
    "member_of",
    "derived_path",
    "increment_by",
    "allowed_only_when",
}
TASK1_INVARIANT_CATALOG_FIELDS = {
    "schema_version",
    "catalog_id",
    "invariant_dsl",
    "operation_graphs",
    "recovery_graph",
    "event_type_matrix",
}
TASK1_INVARIANT_DSL_FIELDS = {"schema_version", "schema_authority", "field_path_policy", "opcodes"}
TASK1_OPERATION_GRAPH_FIELDS = {
    "initialization": {
        "operation_kind",
        "result_contract",
        "audit_event_type",
        "result_audit_bindings",
        "state_audit_bindings",
        "request_audit_bindings",
        "state_null_bindings",
    },
    "transition": {
        "operation_kind",
        "result_contract",
        "audit_event_type",
        "binding_copies",
        "identity_bindings",
    },
}
TASK1_OPERATION_GRAPH_CONSTANTS = {
    "initialization": {
        "operation_kind": "INITIALIZATION",
        "result_contract": "WorkflowTaskInitializationResult.v1",
        "audit_event_type": "TASK_CREATED",
    },
    "transition": {
        "operation_kind": "TRANSITION",
        "result_contract": "WorkflowTransitionResult.v1",
        "audit_event_type": "TRANSITION_ACCEPTED",
    },
}
TASK1_RECOVERY_GRAPH_FIELDS = {
    "recovery_reason_registry",
    "artifact_truth_table",
    "result_status_truth_table",
    "identity_bindings",
    "quarantine_bindings",
    "trusted_prefix_bindings",
    "generation_continuity",
    "path_derivations",
}
TASK1_EVENT_TYPE_ROLE_FIELDS = {
    "TASK_CREATED": {"required", "nullable", "empty", "generation_role", "context_bindings"},
    "TRANSITION_ACCEPTED": {"required", "nullable", "non_empty", "generation_role", "context_bindings"},
    "RECOVERY_RECORDED": {"required", "nullable", "empty", "generation_role", "context_bindings"},
    "ROLLBACK_RECORDED": {"required", "nullable", "empty", "generation_role", "context_bindings"},
}
TASK1_EVENT_GENERATION_ROLE_FIELDS = {
    "TASK_CREATED": {"sequence", "generation", "first_event_type"},
    "TRANSITION_ACCEPTED": {"sequence_must_not_be"},
    "RECOVERY_RECORDED": {"sequence", "minimum_generation", "first_event_type"},
    "ROLLBACK_RECORDED": {"sequence", "minimum_generation", "first_event_type"},
}
TASK1_EVENT_CONTEXT_BINDING_FIELDS = {
    "TASK_CREATED": set(),
    "TRANSITION_ACCEPTED": {
        "policy_project_id",
        "policy_task_id",
        "policy_authorizes_to_state",
        "decision_only_from_state",
    },
    "RECOVERY_RECORDED": set(),
    "ROLLBACK_RECORDED": set(),
}
TASK1_OPERATION_GRAPH_EXPECTED: dict[str, Any] = {
    "initialization": {
        "operation_kind": "INITIALIZATION",
        "result_contract": "WorkflowTaskInitializationResult.v1",
        "audit_event_type": "TASK_CREATED",
        "result_audit_bindings": {
            "audit_event_id": "planned_audit_event.event_id",
            "audit_generation": "planned_audit_event.generation",
            "audit_sequence": "planned_audit_event.sequence",
        },
        "state_audit_bindings": {
            "audit_head_event_id": "planned_audit_event.event_id",
            "audit_head_hash": "planned_audit_event.event_hash",
            "audit_generation": "planned_audit_event.generation",
        },
        "request_audit_bindings": {
            "actor": "planned_audit_event.actor",
        },
        "state_null_bindings": {
            "policy_evaluation_id": None,
            "pending_decision_id": None,
        },
    },
    "transition": {
        "operation_kind": "TRANSITION",
        "result_contract": "WorkflowTransitionResult.v1",
        "audit_event_type": "TRANSITION_ACCEPTED",
        "binding_copies": {
            "decision_resolution_binding": "planned_audit_event.decision_resolution_binding",
            "policy_evaluation_binding": "planned_audit_event.policy_evaluation_binding",
            "evidence_bindings": "planned_audit_event.evidence_bindings",
        },
        "identity_bindings": {
            "transition_actor": {
                "planned_audit_event.actor": "canonical_request.actor",
            },
        },
    },
}
TASK1_RECOVERY_GRAPH_EXPECTED: dict[str, Any] = {
    "recovery_reason_registry": [
        "AUDIT_TAIL_CORRUPT",
        "STATE_AUDIT_MISMATCH",
        "TRANSACTION_PHASE_STALE",
        "THREAT_MODEL_LIMIT",
        "OPERATOR_REQUESTED_ROLLBACK",
    ],
    "artifact_truth_table": {
        "replay": {
            "accepted": {
                "quarantine_path": None,
                "new_generation": None,
                "started_by_event_id": None,
                "started_by_event_type": None,
            },
        },
        "classify_threat_model_limit": {
            "accepted": {
                "quarantine_path": None,
                "new_generation": None,
                "started_by_event_id": None,
                "started_by_event_type": None,
            },
        },
        "quarantine_and_start_generation": {
            "accepted": {
                "quarantine_path": "planned_quarantine_manifest.destination_path",
                "new_generation": "planned_generation_event.generation",
                "started_by_event_id": "planned_generation_event.event_id",
                "started_by_event_type": "planned_generation_event.event_type",
            },
        },
        "rollback_to_valid_prefix": {
            "accepted": {
                "quarantine_path": "planned_quarantine_manifest.destination_path",
                "new_generation": "planned_generation_event.generation",
                "started_by_event_id": "planned_generation_event.event_id",
                "started_by_event_type": "planned_generation_event.event_type",
            },
        },
    },
    "result_status_truth_table": {
        "fail_closed": {
            "accepted": False,
            "fail_closed": True,
            "side_effect_fields_must_be_null": [
                "quarantine_path",
                "new_generation",
                "started_by_event_id",
                "started_by_event_type",
                "resulting_state",
            ],
            "planned_artifacts_must_be_null": [
                "planned_quarantine_manifest",
                "planned_generation_event",
                "planned_state",
                "planned_idempotency_record",
            ],
        },
        "diagnostic_only": {
            "accepted": False,
            "fail_closed": False,
            "side_effect_fields_must_be_null": [
                "quarantine_path",
                "new_generation",
                "started_by_event_id",
                "started_by_event_type",
                "resulting_state",
            ],
            "planned_artifacts_must_be_null": [
                "planned_quarantine_manifest",
                "planned_generation_event",
                "planned_state",
                "planned_idempotency_record",
            ],
        },
    },
    "identity_bindings": {
        "request_generation_actor": {
            "planned_generation_event.actor": "canonical_recovery_request.actor",
        },
    },
    "quarantine_bindings": {
        "planned_quarantine_manifest.source_path": "canonical_recovery_request.observed_audit_path",
        "planned_quarantine_manifest.destination_path": "canonical_recovery_result.quarantine_path",
        "planned_generation_event.details.quarantine_path": "planned_quarantine_manifest.destination_path",
        "planned_generation_event.details.audit_generation.quarantine_path": "planned_quarantine_manifest.destination_path",
    },
    "trusted_prefix_bindings": {
        "canonical_recovery_result.previous_generation": "planned_recovery_record.diagnostic.previous_trusted_prefix.generation",
        "canonical_recovery_result.previous_valid_head_hash": "planned_recovery_record.diagnostic.previous_trusted_prefix.event_hash",
        "planned_generation_event.details.previous_trusted_prefix": "planned_recovery_record.diagnostic.previous_trusted_prefix",
        "planned_generation_event.details.audit_generation.predecessor_generation": "planned_recovery_record.diagnostic.previous_trusted_prefix.generation",
        "planned_generation_event.details.audit_generation.predecessor_valid_head_hash": "planned_recovery_record.diagnostic.previous_trusted_prefix.event_hash",
    },
    "generation_continuity": {
        "new_generation": {
            "predecessor": "planned_recovery_record.diagnostic.previous_trusted_prefix.generation",
            "increment": 1,
            "result_field": "canonical_recovery_result.new_generation",
            "matching_fields": [
                "planned_generation_event.generation",
                "planned_generation_event.details.audit_generation.generation",
                "planned_state.audit_generation",
            ],
        },
    },
    "path_derivations": {
        "quarantine_destination": {
            "field": "planned_quarantine_manifest.destination_path",
            "template": "state/quarantine/{canonical_recovery_request.task_id}/{canonical_recovery_request.recovery_id}/audit-tail.bin",
        },
    },
}
TASK1_EVENT_TYPE_MATRIX_EXPECTED: dict[str, Any] = {
    "TASK_CREATED": {
        "required": ["details.audit_generation"],
        "nullable": [
            "from_state",
            "to_state",
            "transition_id",
            "policy_evaluation_binding",
            "decision_resolution_binding",
        ],
        "empty": ["evidence_bindings"],
        "generation_role": {
            "sequence": 1,
            "generation": 1,
            "first_event_type": "TASK_CREATED",
        },
        "context_bindings": {},
    },
    "TRANSITION_ACCEPTED": {
        "required": [
            "from_state",
            "to_state",
            "transition_id",
            "policy_evaluation_binding",
        ],
        "nullable": ["decision_resolution_binding"],
        "non_empty": ["evidence_bindings"],
        "generation_role": {"sequence_must_not_be": 1},
        "context_bindings": {
            "policy_project_id": "project_id",
            "policy_task_id": "task_id",
            "policy_authorizes_to_state": "to_state",
            "decision_only_from_state": "WAITING_HUMAN",
        },
    },
    "RECOVERY_RECORDED": {
        "required": [
            "details.recovery_id",
            "details.recovery_action",
            "details.recovery_transaction_id",
            "details.previous_trusted_prefix",
            "details.quarantine_path",
            "details.threat_model",
            "details.audit_generation",
        ],
        "nullable": [
            "from_state",
            "to_state",
            "transition_id",
            "policy_evaluation_binding",
            "decision_resolution_binding",
        ],
        "empty": ["evidence_bindings"],
        "generation_role": {
            "sequence": 1,
            "minimum_generation": 2,
            "first_event_type": "RECOVERY_RECORDED",
        },
        "context_bindings": {},
    },
    "ROLLBACK_RECORDED": {
        "required": [
            "details.recovery_id",
            "details.recovery_action",
            "details.recovery_transaction_id",
            "details.previous_trusted_prefix",
            "details.quarantine_path",
            "details.threat_model",
            "details.audit_generation",
        ],
        "nullable": [
            "from_state",
            "to_state",
            "transition_id",
            "policy_evaluation_binding",
            "decision_resolution_binding",
        ],
        "empty": ["evidence_bindings"],
        "generation_role": {
            "sequence": 1,
            "minimum_generation": 2,
            "first_event_type": "ROLLBACK_RECORDED",
        },
        "context_bindings": {},
    },
}


def canonical_json_bytes(record: object) -> bytes:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _canonical_sha(record: object) -> str:
    return hashlib.sha256(canonical_json_bytes(record)).hexdigest()


def _operation_request_fingerprint(record: dict[str, Any]) -> str:
    return _canonical_sha({key: value for key, value in record.items() if not key.endswith("_at_utc")})


def operation_request_fingerprint(record: dict[str, Any]) -> str:
    return _operation_request_fingerprint(record)


def valid_outcome() -> WorkflowValidationOutcome:
    return WorkflowValidationOutcome(True, None, ())


def invalid_outcome(code: str, path: str, message: str) -> WorkflowValidationOutcome:
    if code not in WORKFLOW_ERROR_CODES:
        code = "WORKFLOW_INVALID_INPUT"
    return WorkflowValidationOutcome(False, code, (WorkflowIssue(code, path, message),))


def _require_equal(
    actual: object,
    expected: object,
    path: str,
    message: str,
    *,
    code: str = "WORKFLOW_TRANSACTION_INCOMPLETE",
) -> WorkflowValidationOutcome | None:
    if actual != expected:
        return invalid_outcome(code, path, message)
    return None


def _get_path(record: object, dotted_path: str) -> object:
    current = record
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _is_present(record: object, dotted_path: str) -> bool:
    current = record
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return current is not None


def _path_exists(record: object, dotted_path: str) -> bool:
    current = record
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _transaction_artifact_path(task_id: str, prefix: str, operation_id: str, leaf: str) -> str:
    return f"state/transactions/{task_id}/{prefix}-{operation_id}/{leaf}"


def _load_recovery_matrix() -> tuple[dict[str, Any] | None, WorkflowValidationOutcome | None]:
    global _RECOVERY_MATRIX_CACHE
    if _RECOVERY_MATRIX_CACHE is None:
        matrix_path = Path(__file__).resolve().parents[1] / "config" / "wp3_recovery_artifact_matrix.yaml"
        try:
            matrix = load_yaml_strict(matrix_path.read_text(encoding="utf-8"), logical_path="config/wp3_recovery_artifact_matrix.yaml")
        except Exception as exc:  # pragma: no cover - defensive fail-closed boundary
            return None, invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "recovery_artifact_matrix", str(exc))
        if not isinstance(matrix, dict):
            return None, invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "recovery_artifact_matrix", "matrix must be a mapping")
        expected_top = {"schema_version", "matrix_id", "artifact_fields", "applicability_values", "applicability_roles", "phase_states", "rules"}
        if set(matrix) != expected_top:
            return None, invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "recovery_artifact_matrix", "matrix top-level fields are invalid")
        if matrix["schema_version"] != 1 or matrix["matrix_id"] != "WP3_RECOVERY_ARTIFACT_APPLICABILITY.v1":
            return None, invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "recovery_artifact_matrix.matrix_id", "unsupported recovery matrix")
        if not isinstance(matrix["artifact_fields"], dict) or not isinstance(matrix["applicability_roles"], dict) or not isinstance(matrix["rules"], list):
            return None, invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "recovery_artifact_matrix", "matrix field types are invalid")
        role_values = set(matrix["applicability_roles"].values())
        if role_values != {"required", "optional", "forbidden"}:
            return None, invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "recovery_artifact_matrix.applicability_roles", "matrix roles must map to required, optional, and forbidden")
        _RECOVERY_MATRIX_CACHE = matrix
    return _RECOVERY_MATRIX_CACHE, None


def _load_task1_invariants() -> tuple[dict[str, Any] | None, WorkflowValidationOutcome | None]:
    global _TASK1_INVARIANTS_CACHE
    if _TASK1_INVARIANTS_CACHE is not None:
        validation = _validate_task1_invariant_catalog(_TASK1_INVARIANTS_CACHE)
        if validation:
            return None, validation
        return _TASK1_INVARIANTS_CACHE, None
    if _TASK1_INVARIANTS_CACHE is None:
        catalog_path = Path(__file__).resolve().parents[1] / "config" / "wp3_task1_invariants.yaml"
        try:
            catalog = load_yaml_strict(catalog_path.read_text(encoding="utf-8"), logical_path="config/wp3_task1_invariants.yaml")
        except Exception as exc:  # pragma: no cover - defensive fail-closed boundary
            return None, invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants", str(exc))
        if not isinstance(catalog, dict):
            return None, invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants", "invariant catalog must be a mapping")
        validation = _validate_task1_invariant_catalog(catalog)
        if validation:
            return None, validation
        _TASK1_INVARIANTS_CACHE = catalog
    return _TASK1_INVARIANTS_CACHE, None


def _validate_task1_invariant_catalog(catalog: object) -> WorkflowValidationOutcome | None:
    if not isinstance(catalog, dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants", "invariant catalog must be a mapping")
    if "catalog_schema" in catalog:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.catalog_schema", "catalog must not define its own schema")
    if set(catalog) != TASK1_INVARIANT_CATALOG_FIELDS:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants", "invariant catalog top-level fields are invalid")
    if catalog["schema_version"] != 1 or catalog["catalog_id"] != "WP3_TASK1_INVARIANTS.v1":
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.catalog_id", "unsupported invariant catalog")
    dsl = catalog["invariant_dsl"]
    if not isinstance(dsl, dict) or set(dsl) != TASK1_INVARIANT_DSL_FIELDS:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.invariant_dsl", "invariant DSL declaration is invalid")
    if dsl["schema_version"] != 1:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.invariant_dsl.schema_version", "unsupported invariant DSL version")
    if dsl["schema_authority"] != "CODE_OWNED_FIXED_SCHEMA":
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.invariant_dsl.schema_authority", "schema authority must be code-owned")
    if dsl["field_path_policy"] != "CODE_OWNED_DOTTED_PATHS":
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.invariant_dsl.field_path_policy", "field path policy must be code-owned")
    opcodes = dsl["opcodes"]
    if not isinstance(opcodes, list) or len(opcodes) != len(set(opcodes)) or set(opcodes) != TASK1_ALLOWED_INVARIANT_DSL_OPCODES:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.invariant_dsl.opcodes", "invariant DSL opcodes are invalid")
    for path, actual, expected in (
        ("task1_invariants.operation_graphs", catalog["operation_graphs"], TASK1_OPERATION_GRAPH_EXPECTED),
        ("task1_invariants.recovery_graph", catalog["recovery_graph"], TASK1_RECOVERY_GRAPH_EXPECTED),
        ("task1_invariants.event_type_matrix", catalog["event_type_matrix"], TASK1_EVENT_TYPE_MATRIX_EXPECTED),
    ):
        exact = _validate_exact_catalog_value(actual, expected, path)
        if exact:
            return exact
    consumed = _validate_catalog_consumed_node_coverage(catalog)
    if consumed:
        return consumed
    operation_graphs = catalog["operation_graphs"]
    if not isinstance(operation_graphs, dict) or set(operation_graphs) != {"initialization", "transition"}:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.operation_graphs", "operation graphs must cover initialization and transition")
    for graph_name, graph in operation_graphs.items():
        expected_fields = TASK1_OPERATION_GRAPH_FIELDS[graph_name]
        if not isinstance(graph, dict) or set(graph) != expected_fields:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"task1_invariants.operation_graphs.{graph_name}", "operation graph fields are invalid")
        for const_field, expected_value in TASK1_OPERATION_GRAPH_CONSTANTS[graph_name].items():
            if graph[const_field] != expected_value:
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"task1_invariants.operation_graphs.{graph_name}.{const_field}", "operation graph constant is invalid")
        for field, value in graph.items():
            if field.endswith("_bindings") or field in {"binding_copies", "identity_bindings", "state_null_bindings"}:
                if not isinstance(value, dict):
                    return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"task1_invariants.operation_graphs.{graph_name}.{field}", "binding table must be a mapping")
        if graph_name == "initialization":
            for field, value in graph["state_null_bindings"].items():
                if value is not None:
                    return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"task1_invariants.operation_graphs.initialization.state_null_bindings.{field}", "state-null binding values must be null")
    recovery_graph = catalog["recovery_graph"]
    if not isinstance(recovery_graph, dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.recovery_graph", "recovery graph fields are invalid")
    for field in TASK1_RECOVERY_GRAPH_FIELDS:
        if field not in recovery_graph:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"task1_invariants.recovery_graph.{field}", "missing recovery graph field")
    for field in recovery_graph:
        if field not in TASK1_RECOVERY_GRAPH_FIELDS:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"task1_invariants.recovery_graph.{field}", "unknown recovery graph field")
    if not isinstance(recovery_graph["recovery_reason_registry"], list) or len(recovery_graph["recovery_reason_registry"]) != len(set(recovery_graph["recovery_reason_registry"])):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.recovery_graph.recovery_reason_registry", "recovery reason registry must be a unique list")
    for field in ("artifact_truth_table", "result_status_truth_table", "identity_bindings", "quarantine_bindings", "trusted_prefix_bindings", "generation_continuity", "path_derivations"):
        if not isinstance(recovery_graph[field], dict):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"task1_invariants.recovery_graph.{field}", "recovery graph table must be a mapping")
    event_matrix = catalog["event_type_matrix"]
    if not isinstance(event_matrix, dict) or set(event_matrix) != EVENT_TYPES:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.event_type_matrix", "event-type matrix must cover all audit event types")
    for event_type, roles in event_matrix.items():
        if not isinstance(roles, dict) or set(roles) != TASK1_EVENT_TYPE_ROLE_FIELDS[event_type]:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"task1_invariants.event_type_matrix.{event_type}", "event roles are invalid")
        generation_role = roles["generation_role"]
        if not isinstance(generation_role, dict) or set(generation_role) != TASK1_EVENT_GENERATION_ROLE_FIELDS[event_type]:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"task1_invariants.event_type_matrix.{event_type}.generation_role", "event generation role is invalid")
        context = roles["context_bindings"]
        if not isinstance(context, dict) or set(context) != TASK1_EVENT_CONTEXT_BINDING_FIELDS[event_type]:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"task1_invariants.event_type_matrix.{event_type}.context_bindings", "event context bindings are invalid")
        for list_field in ("required", "nullable", "empty", "non_empty"):
            if list_field in roles and (not isinstance(roles[list_field], list) or len(roles[list_field]) != len(set(roles[list_field]))):
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"task1_invariants.event_type_matrix.{event_type}.{list_field}", "event role paths must be a unique list")
    return None


def _validate_exact_catalog_value(actual: object, expected: object, path: str) -> WorkflowValidationOutcome | None:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", path, "catalog node must be a mapping")
        actual_keys = set(actual)
        expected_keys = set(expected)
        for key in sorted(actual_keys - expected_keys):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"{path}.{key}", "unknown catalog node")
        for key in sorted(expected_keys - actual_keys):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"{path}.{key}", "missing catalog node")
        for key in expected:
            child = _validate_exact_catalog_value(actual[key], expected[key], f"{path}.{key}")
            if child:
                return child
        return None
    if isinstance(expected, list):
        if not isinstance(actual, list):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", path, "catalog node must be a list")
        if len(actual) != len(set(json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True) for item in actual)):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", path, "catalog list values must be unique")
        if actual != expected:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", path, "catalog list values are invalid")
        return None
    if actual != expected or type(actual) is not type(expected):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", path, "catalog scalar value is invalid")
    return None


def _catalog_leaf_paths(value: object, path: str) -> set[str]:
    if isinstance(value, dict):
        paths: set[str] = set()
        for key, child in value.items():
            paths.update(_catalog_leaf_paths(child, f"{path}.{key}"))
        return paths
    if isinstance(value, list):
        if not value:
            return {path}
        paths: set[str] = set()
        for index, child in enumerate(value):
            paths.update(_catalog_leaf_paths(child, f"{path}[{index}]"))
        return paths
    return {path}


def _validate_catalog_consumed_node_coverage(catalog: dict[str, Any]) -> WorkflowValidationOutcome | None:
    accepted_leaf_paths = (
        _catalog_leaf_paths(catalog["operation_graphs"], "task1_invariants.operation_graphs")
        | _catalog_leaf_paths(catalog["recovery_graph"], "task1_invariants.recovery_graph")
        | _catalog_leaf_paths(catalog["event_type_matrix"], "task1_invariants.event_type_matrix")
    )
    consumed_leaf_paths = (
        _catalog_leaf_paths(TASK1_OPERATION_GRAPH_EXPECTED, "task1_invariants.operation_graphs")
        | _catalog_leaf_paths(TASK1_RECOVERY_GRAPH_EXPECTED, "task1_invariants.recovery_graph")
        | _catalog_leaf_paths(TASK1_EVENT_TYPE_MATRIX_EXPECTED, "task1_invariants.event_type_matrix")
    )
    unconsumed = sorted(accepted_leaf_paths - consumed_leaf_paths)
    if unconsumed:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", unconsumed[0], "accepted catalog leaf is not consumed by the runtime")
    missing = sorted(consumed_leaf_paths - accepted_leaf_paths)
    if missing:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", missing[0], "consumed catalog leaf is missing")
    return None


def _validate_catalog_bindings(
    record: dict[str, Any],
    bindings: object,
    *,
    table_path: str,
    code: str,
) -> WorkflowValidationOutcome | None:
    if not isinstance(bindings, dict):
        return invalid_outcome(code, table_path, "binding table must be a mapping")
    for left_path, right_path in bindings.items():
        if not isinstance(left_path, str) or not isinstance(right_path, str):
            return invalid_outcome(code, table_path, "binding paths must be strings")
        if not _path_exists(record, left_path):
            return invalid_outcome(code, left_path, "left binding path is missing")
        if not _path_exists(record, right_path):
            return invalid_outcome(code, right_path, "right binding path is missing")
        check = _require_equal(
            _get_path(record, left_path),
            _get_path(record, right_path),
            left_path,
            "catalog binding mismatch",
            code=code,
        )
        if check:
            return check
    return None


def _render_catalog_template(record: dict[str, Any], template: str, *, code: str) -> tuple[str | None, WorkflowValidationOutcome | None]:
    rendered = template
    for match in re.findall(r"\{([^}]+)\}", template):
        if not _path_exists(record, match):
            return None, invalid_outcome(code, match, "template binding path is missing")
        value = _get_path(record, match)
        if not isinstance(value, str):
            return None, invalid_outcome(code, match, "template binding value must be a string")
        rendered = rendered.replace("{" + match + "}", value)
    return rendered, None


def _validate_catalog_path_derivations(
    record: dict[str, Any],
    derivations: object,
    *,
    table_path: str,
    code: str,
) -> WorkflowValidationOutcome | None:
    if not isinstance(derivations, dict):
        return invalid_outcome(code, table_path, "path derivation table must be a mapping")
    for rule_name, rule in derivations.items():
        if not isinstance(rule, dict) or set(rule) != {"field", "template"}:
            return invalid_outcome(code, f"{table_path}.{rule_name}", "path derivation rule fields are invalid")
        field = rule["field"]
        template = rule["template"]
        if not isinstance(field, str) or not isinstance(template, str):
            return invalid_outcome(code, f"{table_path}.{rule_name}", "path derivation field/template must be strings")
        if not _path_exists(record, field):
            return invalid_outcome(code, field, "derived path field is missing")
        expected, error = _render_catalog_template(record, template, code=code)
        if error:
            return error
        if _get_path(record, field) != expected:
            return invalid_outcome(code, field, "derived path does not match catalog template")
    return None


def _validate_generation_continuity(
    record: dict[str, Any],
    rules: object,
    *,
    table_path: str,
    code: str,
) -> WorkflowValidationOutcome | None:
    if not isinstance(rules, dict):
        return invalid_outcome(code, table_path, "generation continuity table must be a mapping")
    for rule_name, rule in rules.items():
        if not isinstance(rule, dict) or set(rule) != {"predecessor", "increment", "result_field", "matching_fields"}:
            return invalid_outcome(code, f"{table_path}.{rule_name}", "generation rule fields are invalid")
        predecessor_path = rule["predecessor"]
        result_path = rule["result_field"]
        if not _path_exists(record, predecessor_path) or not _path_exists(record, result_path):
            return invalid_outcome(code, f"{table_path}.{rule_name}", "generation rule path is missing")
        predecessor = _get_path(record, predecessor_path)
        result_value = _get_path(record, result_path)
        increment = rule["increment"]
        if type(predecessor) is not int or type(result_value) is not int or type(increment) is not int:
            return invalid_outcome(code, result_path, "generation values must be integers")
        if result_value != predecessor + increment:
            return invalid_outcome(code, result_path, "new generation must increment from predecessor")
        matching_fields = rule["matching_fields"]
        if not isinstance(matching_fields, list):
            return invalid_outcome(code, f"{table_path}.{rule_name}.matching_fields", "matching_fields must be a list")
        for field in matching_fields:
            if not _path_exists(record, field):
                return invalid_outcome(code, field, "generation matching field is missing")
            if _get_path(record, field) != result_value:
                return invalid_outcome(code, field, "generation field must match result generation")
    return None


def fail_closed_result(
    transition_id: object,
    task_id: object,
    error_code: str,
    path: str,
    message: str,
) -> WorkflowTransitionResult:
    if error_code not in WORKFLOW_ERROR_CODES:
        error_code = "WORKFLOW_INVALID_INPUT"
    return WorkflowTransitionResult(
        schema_version=1,
        transition_id=transition_id if isinstance(transition_id, str) and transition_id else "<invalid>",
        task_id=task_id if isinstance(task_id, str) and task_id else "<invalid>",
        accepted=False,
        resulting_state=None,
        audit_event_id=None,
        fail_closed=True,
        error_code=error_code,
        issues=(WorkflowIssue(error_code, path, message),),
        idempotent_replay=False,
        created_at_utc="1970-01-01T00:00:00Z",
    )


def validate_transition_request(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", "$", "transition request must be a mapping")
    error = _validate_exact_mapping(record, TRANSITION_REQUEST_FIELDS, "transition request")
    if error:
        return error
    for check in (
        _validate_schema_version(record.get("schema_version"), "schema_version"),
        _require_safe_id(record.get("transition_id"), "transition_id"),
        _require_safe_id(record.get("task_id"), "task_id"),
        _require_safe_id(record.get("project_id"), "project_id"),
        _require_non_empty_string(record.get("idempotency_key"), "idempotency_key"),
        _require_member(record.get("from_state"), TASK_STATES, "from_state", "WORKFLOW_UNKNOWN_STATE"),
        _require_member(record.get("to_state"), TASK_STATES, "to_state", "WORKFLOW_UNKNOWN_STATE"),
        _require_member(record.get("actor"), ACTORS, "actor"),
        _validate_utc(record.get("created_at_utc"), "created_at_utc"),
    ):
        if check:
            return check
    policy = validate_policy_evaluation_binding(record["policy_evaluation_binding"])
    if not policy.valid:
        return policy
    if record["policy_evaluation_binding"].get("source") != "embedded":
        return invalid_outcome(
            "WORKFLOW_POLICY_RESULT_INVALID",
            "policy_evaluation_binding.source",
            "Task 1 transition validation requires an embedded validated policy result",
        )
    embedded_policy = record["policy_evaluation_binding"].get("embedded_record")
    if embedded_policy is not None:
        for field in ("project_id", "task_id"):
            check = _require_equal(
                embedded_policy.get(field),
                record[field],
                f"policy_evaluation_binding.embedded_record.{field}",
                f"embedded policy {field} must match transition request",
                code="WORKFLOW_POLICY_RESULT_INVALID",
            )
            if check:
                return check
    if record["to_state"] not in record["policy_evaluation_binding"]["authorized_transitions"]:
        return invalid_outcome(
            "WORKFLOW_POLICY_RESULT_INVALID",
            "policy_evaluation_binding.authorized_transitions",
            "target state is not authorized by policy binding",
        )
    if record["from_state"] == "WAITING_HUMAN":
        decision = validate_human_decision_resolution_binding(
            record["decision_resolution_binding"],
            expected_target_state=record["to_state"],
            expected_project_id=record["project_id"],
            expected_task_id=record["task_id"],
        )
        if not decision.valid:
            return decision
    elif record["decision_resolution_binding"] is not None:
        return invalid_outcome("WORKFLOW_DECISION_BINDING_INVALID", "decision_resolution_binding", "decision binding is only valid from WAITING_HUMAN")
    if not isinstance(record["evidence_bindings"], list):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", "evidence_bindings", "evidence_bindings must be a list")
    seen: set[str] = set()
    for index, binding in enumerate(record["evidence_bindings"]):
        evidence = validate_evidence_binding(binding, prefix=f"evidence_bindings[{index}]")
        if not evidence.valid:
            return evidence
        binding_id = binding["binding_id"]
        if binding_id in seen:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", f"evidence_bindings[{index}].binding_id", "duplicate evidence binding_id")
        seen.add(binding_id)
    return valid_outcome()


def validate_task_initialization_request(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", "$", "initialization request must be a mapping")
    error = _validate_exact_mapping(record, INITIALIZATION_REQUEST_FIELDS, "initialization request")
    if error:
        return error
    for check in (
        _validate_schema_version(record.get("schema_version"), "schema_version"),
        _require_safe_id(record.get("initialization_id"), "initialization_id"),
        _require_safe_id(record.get("task_id"), "task_id"),
        _require_safe_id(record.get("project_id"), "project_id"),
        _require_member(record.get("initial_state"), {"DRAFT"}, "initial_state", "WORKFLOW_ILLEGAL_TRANSITION"),
        _require_member(record.get("actor"), ACTORS, "actor"),
        _require_non_empty_string(record.get("idempotency_key"), "idempotency_key"),
        _validate_utc(record.get("created_at_utc"), "created_at_utc"),
    ):
        if check:
            return check
    task_intake = validate_evidence_binding(record["task_intake_binding"], prefix="task_intake_binding")
    if not task_intake.valid:
        return task_intake
    return valid_outcome()


def validate_task_initialization_result(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", "$", "initialization result must be a mapping")
    error = _validate_exact_mapping(record, INITIALIZATION_RESULT_FIELDS, "initialization result")
    if error:
        return error
    for check in (
        _validate_schema_version(record.get("schema_version"), "schema_version"),
        _require_safe_id(record.get("initialization_id"), "initialization_id"),
        _require_safe_id(record.get("task_id"), "task_id"),
        _require_safe_id(record.get("project_id"), "project_id"),
        _validate_utc(record.get("created_at_utc"), "created_at_utc"),
        _require_bool(record.get("accepted"), "accepted"),
        _require_bool(record.get("fail_closed"), "fail_closed"),
        _require_bool(record.get("idempotent_replay"), "idempotent_replay"),
    ):
        if check:
            return check
    if record["accepted"]:
        if record["resulting_state"] != "DRAFT":
            return invalid_outcome("WORKFLOW_ILLEGAL_TRANSITION", "resulting_state", "accepted initialization must result in DRAFT")
        if record["audit_generation"] != 1:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "audit_generation", "accepted initialization must use audit_generation 1")
        if record["audit_sequence"] != 1:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "audit_sequence", "accepted initialization must use audit_sequence 1")
    return _validate_result_envelope(
        record,
        id_path="initialization_id",
        allow_audit_coordinates=True,
    )


def validate_task_state(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_STATE_CORRUPT", "$", "task state must be a mapping")
    error = _validate_exact_mapping(record, TASK_STATE_FIELDS, "task state")
    if error:
        return _with_code(error, "WORKFLOW_STATE_CORRUPT")
    for check in (
        _validate_schema_version(record.get("schema_version"), "schema_version"),
        _require_safe_id(record.get("task_id"), "task_id"),
        _require_safe_id(record.get("project_id"), "project_id"),
        _require_member(record.get("current_state"), TASK_STATES, "current_state", "WORKFLOW_UNKNOWN_STATE"),
        _require_positive_int(record.get("audit_generation"), "audit_generation"),
        _require_safe_id(record.get("audit_head_event_id"), "audit_head_event_id"),
        _require_sha(record.get("audit_head_hash"), "audit_head_hash"),
        _validate_utc(record.get("updated_at_utc"), "updated_at_utc"),
    ):
        if check:
            return _with_code(check, "WORKFLOW_STATE_CORRUPT")
    if record["previous_state"] is not None and record["previous_state"] not in TASK_STATES:
        return invalid_outcome("WORKFLOW_UNKNOWN_STATE", "previous_state", "unknown previous_state")
    if record["current_state"] == "WAITING_HUMAN" and not isinstance(record["pending_decision_id"], str):
        return invalid_outcome("WORKFLOW_STATE_CORRUPT", "pending_decision_id", "WAITING_HUMAN requires pending_decision_id")
    if record["current_state"] != "WAITING_HUMAN" and record["pending_decision_id"] is not None:
        return invalid_outcome("WORKFLOW_STATE_CORRUPT", "pending_decision_id", "pending_decision_id is only valid for WAITING_HUMAN")
    for field in ("last_transition_id", "policy_evaluation_id", "pending_decision_id"):
        if record[field] is not None:
            check = _require_safe_id(record[field], field)
            if check:
                return _with_code(check, "WORKFLOW_STATE_CORRUPT")
    return valid_outcome()


def _validate_audit_event_field_matrix(record: dict[str, Any]) -> WorkflowValidationOutcome:
    catalog, error = _load_task1_invariants()
    if error:
        return _with_code(error, "WORKFLOW_AUDIT_CORRUPT")
    assert catalog is not None
    roles = catalog["event_type_matrix"][record["event_type"]]
    for dotted_path in roles.get("required", []):
        if not _is_present(record, dotted_path):
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", dotted_path, "audit event type requires this field")
    null_required_event_types = {"TASK_CREATED", "RECOVERY_RECORDED", "ROLLBACK_RECORDED"}
    if record["event_type"] in null_required_event_types:
        for dotted_path in roles.get("nullable", []):
            if _get_path(record, dotted_path) is not None:
                return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", dotted_path, "audit event type requires this field to be null")
    for dotted_path in roles.get("empty", []):
        if _get_path(record, dotted_path) != []:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", dotted_path, "audit event type requires this field to be empty")
    for dotted_path in roles.get("non_empty", []):
        value = _get_path(record, dotted_path)
        if not isinstance(value, list) or not value:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", dotted_path, "audit event type requires a non-empty list")
    return valid_outcome()


def _validate_audit_event_generation_role(record: dict[str, Any]) -> WorkflowValidationOutcome:
    catalog, error = _load_task1_invariants()
    if error:
        return _with_code(error, "WORKFLOW_AUDIT_CORRUPT")
    assert catalog is not None
    role = catalog["event_type_matrix"][record["event_type"]]["generation_role"]
    if not isinstance(role, dict):
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "task1_invariants.event_type_matrix.generation_role", "generation role must be a mapping")
    if "sequence_must_not_be" in role and record["sequence"] == role["sequence_must_not_be"]:
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "event_type", "event type is not valid as a generation starter")
    if "sequence" in role and record["sequence"] != role["sequence"]:
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "sequence", "event generation role sequence mismatch")
    if "generation" in role and record["generation"] != role["generation"]:
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "generation", "event generation role mismatch")
    if "minimum_generation" in role and record["generation"] < role["minimum_generation"]:
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "generation", "event generation is below role minimum")
    if record["sequence"] == 1:
        expected_event_type = role.get("first_event_type")
        if record["event_type"] != expected_event_type:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "event_type", "first event type does not match generation role")
    return valid_outcome()


def _validate_audit_event_context_bindings(record: dict[str, Any]) -> WorkflowValidationOutcome:
    catalog, error = _load_task1_invariants()
    if error:
        return _with_code(error, "WORKFLOW_AUDIT_CORRUPT")
    assert catalog is not None
    context = catalog["event_type_matrix"][record["event_type"]]["context_bindings"]
    if not isinstance(context, dict):
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "task1_invariants.event_type_matrix.context_bindings", "context bindings must be a mapping")
    if record["event_type"] != "TRANSITION_ACCEPTED":
        return valid_outcome()
    policy_binding = record["policy_evaluation_binding"]
    if not isinstance(policy_binding, dict):
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "policy_evaluation_binding", "transition audit requires policy binding")
    embedded_policy = policy_binding.get("embedded_record")
    if embedded_policy is not None:
        project_field = context.get("policy_project_id")
        task_field = context.get("policy_task_id")
        for policy_path, event_field in (
            ("project_id", project_field),
            ("task_id", task_field),
        ):
            if not isinstance(event_field, str):
                return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "task1_invariants.event_type_matrix.context_bindings", "policy context binding is invalid")
            check = _require_equal(
                embedded_policy.get(policy_path),
                record[event_field],
                f"policy_evaluation_binding.embedded_record.{policy_path}",
                "policy binding context must match audit event",
                code="WORKFLOW_AUDIT_CORRUPT",
            )
            if check:
                return check
    target_field = context.get("policy_authorizes_to_state")
    if isinstance(target_field, str) and record[target_field] not in policy_binding["authorized_transitions"]:
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "policy_evaluation_binding.authorized_transitions", "policy binding does not authorize audit event target")
    decision_source_state = context.get("decision_only_from_state")
    if record["decision_resolution_binding"] is not None:
        if record["from_state"] != decision_source_state:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "decision_resolution_binding", "decision binding is only valid from the catalog-declared source state")
        decision = validate_human_decision_resolution_binding(
            record["decision_resolution_binding"],
            expected_target_state=record["to_state"],
            expected_project_id=record["project_id"],
            expected_task_id=record["task_id"],
        )
        if not decision.valid:
            return _with_code(decision, "WORKFLOW_AUDIT_CORRUPT")
    elif record["from_state"] == decision_source_state:
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "decision_resolution_binding", "catalog-declared human-resume transition requires decision binding")
    return valid_outcome()


def validate_audit_event(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "$", "audit event must be a mapping")
    error = _validate_exact_mapping(record, AUDIT_EVENT_FIELDS, "audit event")
    if error:
        return _with_code(error, "WORKFLOW_AUDIT_CORRUPT")
    for check in (
        _validate_schema_version(record.get("schema_version"), "schema_version"),
        _require_safe_id(record.get("event_id"), "event_id"),
        _require_positive_int(record.get("generation"), "generation"),
        _require_positive_int(record.get("sequence"), "sequence"),
        _require_safe_id(record.get("project_id"), "project_id"),
        _require_safe_id(record.get("task_id"), "task_id"),
        _require_member(record.get("event_type"), EVENT_TYPES, "event_type", "WORKFLOW_AUDIT_CORRUPT"),
        _require_member(record.get("actor"), ACTORS, "actor"),
        _require_sha(record.get("event_hash"), "event_hash"),
        _validate_utc(record.get("created_at_utc"), "created_at_utc"),
    ):
        if check:
            return _with_code(check, "WORKFLOW_AUDIT_CORRUPT")
    for state_field in ("from_state", "to_state"):
        if record[state_field] is not None and record[state_field] not in TASK_STATES:
            return invalid_outcome("WORKFLOW_UNKNOWN_STATE", state_field, "unknown workflow state")
    if record["transition_id"] is not None:
        check = _require_safe_id(record["transition_id"], "transition_id")
        if check:
            return _with_code(check, "WORKFLOW_AUDIT_CORRUPT")
    if record["previous_event_hash"] is not None:
        check = _require_sha(record["previous_event_hash"], "previous_event_hash")
        if check:
            return _with_code(check, "WORKFLOW_AUDIT_CORRUPT")
    if record["sequence"] == 1 and record["previous_event_hash"] is not None:
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "previous_event_hash", "sequence 1 must not have previous_event_hash")
    if record["sequence"] > 1 and record["previous_event_hash"] is None:
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "previous_event_hash", "sequence greater than 1 requires previous_event_hash")
    if record["event_type"] == "TASK_CREATED" and (record["generation"] != 1 or record["sequence"] != 1):
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "event_type", "TASK_CREATED is only valid for generation 1 sequence 1")
    if not isinstance(record["details"], dict):
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "details", "details must be a mapping")
    evidence = _validate_evidence_binding_list(record["evidence_bindings"], "evidence_bindings")
    if not evidence.valid:
        return _with_code(evidence, "WORKFLOW_AUDIT_CORRUPT")
    if record["policy_evaluation_binding"] is not None:
        policy = validate_policy_evaluation_binding(record["policy_evaluation_binding"])
        if not policy.valid:
            return _with_code(policy, "WORKFLOW_AUDIT_CORRUPT")
        if record["event_type"] == "TRANSITION_ACCEPTED" and record["policy_evaluation_binding"].get("source") != "embedded":
            return invalid_outcome(
                "WORKFLOW_AUDIT_CORRUPT",
                "policy_evaluation_binding.source",
                "Task 1 transition audit validation requires an embedded validated policy result",
            )
    if record["decision_resolution_binding"] is not None:
        decision = validate_human_decision_resolution_binding(record["decision_resolution_binding"])
        if not decision.valid:
            return _with_code(decision, "WORKFLOW_AUDIT_CORRUPT")
    if record["event_type"] == "TASK_CREATED":
        for field in ("transition_id", "from_state", "to_state"):
            if record[field] is not None:
                return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", field, "TASK_CREATED must not carry transition fields")
        if record["policy_evaluation_binding"] is not None or record["decision_resolution_binding"] is not None:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "policy_evaluation_binding", "TASK_CREATED must not carry policy or decision bindings")
        if set(record["details"]) != {"audit_generation"}:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "details.audit_generation", "TASK_CREATED requires only details.audit_generation")
        generation = validate_audit_generation(record["details"]["audit_generation"])
        if not generation.valid:
            return _with_code(generation, "WORKFLOW_AUDIT_CORRUPT")
        for check in (
            _require_equal(record["details"]["audit_generation"]["generation"], 1, "details.audit_generation.generation", "TASK_CREATED must start generation 1", code="WORKFLOW_AUDIT_CORRUPT"),
            _require_equal(record["details"]["audit_generation"]["task_id"], record["task_id"], "details.audit_generation.task_id", "audit generation task_id must match event", code="WORKFLOW_AUDIT_CORRUPT"),
            _require_equal(record["details"]["audit_generation"]["started_by_event_id"], record["event_id"], "details.audit_generation.started_by_event_id", "audit generation starter must match event", code="WORKFLOW_AUDIT_CORRUPT"),
            _require_equal(record["details"]["audit_generation"]["started_by_event_type"], "TASK_CREATED", "details.audit_generation.started_by_event_type", "generation 1 must start with TASK_CREATED", code="WORKFLOW_AUDIT_CORRUPT"),
        ):
            if check:
                return check
    elif record["event_type"] == "TRANSITION_ACCEPTED":
        for field in ("from_state", "to_state"):
            if record[field] is None:
                return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", field, "TRANSITION_ACCEPTED requires workflow states")
        if not isinstance(record["transition_id"], str):
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "transition_id", "TRANSITION_ACCEPTED requires transition_id")
        if record["policy_evaluation_binding"] is None:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "policy_evaluation_binding", "TRANSITION_ACCEPTED requires policy binding")
        if not record["evidence_bindings"]:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "evidence_bindings", "TRANSITION_ACCEPTED requires evidence bindings")
    else:
        if record["event_type"] not in RECOVERY_EVENT_TYPES:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "event_type", "unknown audit event type")
        if record["sequence"] != 1:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "sequence", "recovery events must start an audit generation")
        if record["previous_event_hash"] is not None:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "previous_event_hash", "generation-start recovery events must not have previous_event_hash")
        expected_detail_fields = {
            "recovery_id",
            "recovery_action",
            "recovery_transaction_id",
            "previous_trusted_prefix",
            "quarantine_path",
            "threat_model",
            "audit_generation",
        }
        if set(record["details"]) != expected_detail_fields:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "details", "recovery events require exact generation-start details")
        prefix = _validate_trusted_prefix(record["details"]["previous_trusted_prefix"], "details.previous_trusted_prefix")
        if not prefix.valid:
            return _with_code(prefix, "WORKFLOW_AUDIT_CORRUPT")
        for check in (
            _require_safe_id(record["details"]["recovery_id"], "details.recovery_id"),
            _require_safe_id(record["details"]["recovery_transaction_id"], "details.recovery_transaction_id"),
            _require_member(record["details"]["recovery_action"], RECOVERY_ACTIONS, "details.recovery_action", "WORKFLOW_AUDIT_CORRUPT"),
            _require_member(record["details"]["threat_model"], THREAT_MODELS, "details.threat_model", "WORKFLOW_AUDIT_CORRUPT"),
        ):
            if check:
                return _with_code(check, "WORKFLOW_AUDIT_CORRUPT")
        if not _is_safe_relative_path(record["details"]["quarantine_path"]):
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "details.quarantine_path", "quarantine_path must be safe relative POSIX path")
        generation = validate_audit_generation(record["details"]["audit_generation"])
        if not generation.valid:
            return _with_code(generation, "WORKFLOW_AUDIT_CORRUPT")
        expected_event_type = "ROLLBACK_RECORDED" if record["details"]["recovery_action"] == "rollback_to_valid_prefix" else "RECOVERY_RECORDED"
        if record["event_type"] != expected_event_type:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "event_type", "event_type must match recovery action")
        for check in (
            _require_equal(record["details"]["audit_generation"]["generation"], record["generation"], "details.audit_generation.generation", "audit generation must match event generation", code="WORKFLOW_AUDIT_CORRUPT"),
            _require_equal(record["details"]["audit_generation"]["task_id"], record["task_id"], "details.audit_generation.task_id", "audit generation task_id must match event", code="WORKFLOW_AUDIT_CORRUPT"),
            _require_equal(record["details"]["audit_generation"]["started_by_event_id"], record["event_id"], "details.audit_generation.started_by_event_id", "audit generation starter must match event", code="WORKFLOW_AUDIT_CORRUPT"),
            _require_equal(record["details"]["audit_generation"]["started_by_event_type"], record["event_type"], "details.audit_generation.started_by_event_type", "audit generation starter type must match event", code="WORKFLOW_AUDIT_CORRUPT"),
            _require_equal(record["details"]["audit_generation"]["predecessor_generation"], record["details"]["previous_trusted_prefix"]["generation"], "details.audit_generation.predecessor_generation", "predecessor generation must match trusted prefix", code="WORKFLOW_AUDIT_CORRUPT"),
            _require_equal(record["details"]["audit_generation"]["predecessor_valid_head_hash"], record["details"]["previous_trusted_prefix"]["event_hash"], "details.audit_generation.predecessor_valid_head_hash", "predecessor hash must match trusted prefix", code="WORKFLOW_AUDIT_CORRUPT"),
            _require_equal(record["details"]["audit_generation"]["quarantine_path"], record["details"]["quarantine_path"], "details.audit_generation.quarantine_path", "audit generation quarantine path must match details", code="WORKFLOW_AUDIT_CORRUPT"),
            _require_equal(record["details"]["audit_generation"]["threat_model"], record["details"]["threat_model"], "details.audit_generation.threat_model", "audit generation threat model must match details", code="WORKFLOW_AUDIT_CORRUPT"),
        ):
            if check:
                return check
    matrix = _validate_audit_event_field_matrix(record)
    if not matrix.valid:
        return matrix
    generation_role = _validate_audit_event_generation_role(record)
    if not generation_role.valid:
        return generation_role
    context_bindings = _validate_audit_event_context_bindings(record)
    if not context_bindings.valid:
        return context_bindings
    expected_hash = _canonical_sha(dict(record, event_hash=None))
    if record["event_hash"] != expected_hash:
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "event_hash", "event_hash does not match canonical audit event bytes")
    return valid_outcome()


def _operation_prefix(operation_kind: str) -> str:
    return "initialization" if operation_kind == "INITIALIZATION" else "transition"


def _validate_transition_operation_graph(
    record: dict[str, Any],
    *,
    request: dict[str, Any],
    result: dict[str, Any],
    planned_audit: dict[str, Any],
    planned_state: dict[str, Any],
) -> WorkflowValidationOutcome:
    catalog, error = _load_task1_invariants()
    if error:
        return error
    assert catalog is not None
    graph_key = "initialization" if record["operation_kind"] == "INITIALIZATION" else "transition"
    graph = catalog["operation_graphs"][graph_key]
    if graph["operation_kind"] != record["operation_kind"]:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.operation_graphs", "operation graph kind mismatch")
    if record["operation_kind"] == "INITIALIZATION":
        for result_field, audit_path in graph["result_audit_bindings"].items():
            check = _require_equal(
                result[result_field],
                _get_path(record, audit_path),
                f"canonical_result.{result_field}",
                f"initialization result {result_field} must match planned audit event",
            )
            if check:
                return check
        for state_field, audit_path in graph["state_audit_bindings"].items():
            check = _require_equal(
                planned_state[state_field],
                _get_path(record, audit_path),
                f"planned_state.{state_field}",
                f"initialization state {state_field} must match planned audit event",
            )
            if check:
                return check
        for request_field, audit_path in graph["request_audit_bindings"].items():
            check = _require_equal(
                request[request_field],
                _get_path(record, audit_path),
                f"planned_audit_event.{request_field}",
                f"initialization planned audit {request_field} must match request",
            )
            if check:
                return check
        for state_field in graph["state_null_bindings"]:
            if planned_state[state_field] is not None:
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"planned_state.{state_field}", "initialization state field must be null")
    else:
        for request_field, audit_path in graph["binding_copies"].items():
            check = _require_equal(
                request[request_field],
                _get_path(record, audit_path),
                f"planned_audit_event.{request_field}",
                f"transition planned audit {request_field} must match request",
            )
            if check:
                return check
        for binding_name, bindings in graph["identity_bindings"].items():
            binding = _validate_catalog_bindings(
                record,
                bindings,
                table_path=f"task1_invariants.operation_graphs.transition.identity_bindings.{binding_name}",
                code="WORKFLOW_TRANSACTION_INCOMPLETE",
            )
            if binding:
                return binding
    return valid_outcome()


def validate_transition_transaction(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "$", "transition transaction must be a mapping")
    error = _validate_exact_mapping(record, TRANSITION_TRANSACTION_FIELDS, "transition transaction")
    if error:
        return _with_code(error, "WORKFLOW_TRANSACTION_INCOMPLETE")
    for check in (
        _validate_schema_version(record.get("schema_version"), "schema_version"),
        _require_safe_id(record.get("transaction_id"), "transaction_id"),
        _require_member(record.get("operation_kind"), TRANSITION_OPERATION_KINDS, "operation_kind", "WORKFLOW_TRANSACTION_INCOMPLETE"),
        _require_safe_id(record.get("operation_id"), "operation_id"),
        _require_safe_id(record.get("task_id"), "task_id"),
        _require_non_empty_string(record.get("idempotency_key"), "idempotency_key"),
        _require_sha(record.get("request_fingerprint"), "request_fingerprint"),
        _require_member(record.get("latest_phase"), TRANSITION_PHASES, "latest_phase", "WORKFLOW_TRANSACTION_INCOMPLETE"),
        _require_sha(record.get("planned_audit_event_hash"), "planned_audit_event_hash"),
        _require_sha(record.get("planned_state_hash"), "planned_state_hash"),
        _require_sha(record.get("planned_result_hash"), "planned_result_hash"),
        _validate_utc(record.get("created_at_utc"), "created_at_utc"),
        _validate_utc(record.get("updated_at_utc"), "updated_at_utc"),
    ):
        if check:
            return _with_code(check, "WORKFLOW_TRANSACTION_INCOMPLETE")
    if isinstance(record.get("canonical_request"), dict):
        for check in (
            _require_equal(record["task_id"], record["canonical_request"].get("task_id"), "task_id", "transaction task_id must match request task_id"),
            _require_equal(record["idempotency_key"], record["canonical_request"].get("idempotency_key"), "idempotency_key", "transaction idempotency_key must match request"),
        ):
            if check:
                return check
    prefix = _operation_prefix(record["operation_kind"])
    expected_paths = {
        "phase_journal_path": _transaction_artifact_path(record["task_id"], prefix, record["operation_id"], "phases.0001.jsonl"),
        "phase_journal_index_path": _transaction_artifact_path(record["task_id"], prefix, record["operation_id"], "phase_segments.jsonl"),
    }
    for path_field, expected_path in expected_paths.items():
        if not isinstance(record[path_field], str) or not _is_safe_relative_path(record[path_field]) or record[path_field] != expected_path:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", path_field, f"{path_field} must be {expected_path}")
    if record["first_journal_segment_id"] != "0001":
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "first_journal_segment_id", "first_journal_segment_id must be 0001")
    if record["operation_kind"] == "INITIALIZATION":
        if record["initialization_id"] != record["operation_id"] or record["transition_id"] is not None:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "initialization_id", "INITIALIZATION requires initialization_id=operation_id and transition_id=null")
        request = validate_task_initialization_request(record["canonical_request"])
        result = validate_task_initialization_result(record["canonical_result"])
    else:
        if record["transition_id"] != record["operation_id"] or record["initialization_id"] is not None:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "transition_id", "TRANSITION requires transition_id=operation_id and initialization_id=null")
        request = validate_transition_request(record["canonical_request"])
        result = validate_transition_result(record["canonical_result"])
    if not request.valid:
        return _with_code(request, "WORKFLOW_TRANSACTION_INCOMPLETE")
    if not result.valid:
        return _with_code(result, "WORKFLOW_TRANSACTION_INCOMPLETE")
    canonical_request = record["canonical_request"]
    canonical_result = record["canonical_result"]
    for check in (
        _require_equal(record["task_id"], canonical_request["task_id"], "task_id", "transaction task_id must match request task_id"),
        _require_equal(record["idempotency_key"], canonical_request["idempotency_key"], "idempotency_key", "transaction idempotency_key must match request"),
        _require_equal(record["request_fingerprint"], _operation_request_fingerprint(canonical_request), "request_fingerprint", "request_fingerprint must match timestamp-free canonical_request"),
    ):
        if check:
            return check
    if record["operation_kind"] == "INITIALIZATION":
        for check in (
            _require_equal(record["operation_id"], canonical_request["initialization_id"], "operation_id", "operation_id must match initialization request"),
            _require_equal(record["operation_id"], canonical_result["initialization_id"], "canonical_result.initialization_id", "result initialization_id must match operation_id"),
            _require_equal(record["task_id"], canonical_result["task_id"], "canonical_result.task_id", "result task_id must match transaction task_id"),
            _require_equal(canonical_request["project_id"], canonical_result["project_id"], "canonical_result.project_id", "result project_id must match request"),
        ):
            if check:
                return check
    else:
        for check in (
            _require_equal(record["operation_id"], canonical_request["transition_id"], "operation_id", "operation_id must match transition request"),
            _require_equal(record["operation_id"], canonical_result["transition_id"], "canonical_result.transition_id", "result transition_id must match operation_id"),
            _require_equal(record["task_id"], canonical_result["task_id"], "canonical_result.task_id", "result task_id must match transaction task_id"),
            _require_equal(canonical_request["to_state"], canonical_result["resulting_state"], "canonical_result.resulting_state", "resulting_state must match requested target"),
        ):
            if check:
                return check
    audit = validate_audit_event(record["planned_audit_event"])
    state = validate_task_state(record["planned_state"])
    if not audit.valid:
        return _with_code(audit, "WORKFLOW_TRANSACTION_INCOMPLETE")
    if not state.valid:
        return _with_code(state, "WORKFLOW_TRANSACTION_INCOMPLETE")
    planned_audit = record["planned_audit_event"]
    planned_state = record["planned_state"]
    for check in (
        _require_equal(planned_audit["task_id"], record["task_id"], "planned_audit_event.task_id", "planned audit task_id must match transaction"),
        _require_equal(planned_audit["project_id"], canonical_request["project_id"], "planned_audit_event.project_id", "planned audit project_id must match request"),
        _require_equal(planned_state["task_id"], record["task_id"], "planned_state.task_id", "planned state task_id must match transaction"),
        _require_equal(planned_state["project_id"], canonical_request["project_id"], "planned_state.project_id", "planned state project_id must match request"),
    ):
        if check:
            return check
    if record["operation_kind"] == "INITIALIZATION":
        for check in (
            _require_equal(planned_audit["event_type"], "TASK_CREATED", "planned_audit_event.event_type", "initialization must plan TASK_CREATED audit event"),
            _require_equal(planned_state["current_state"], canonical_result["resulting_state"], "planned_state.current_state", "planned state must match initialization result"),
            _require_equal(planned_state["previous_state"], None, "planned_state.previous_state", "initialization state must not have previous_state"),
            _require_equal(planned_state["last_transition_id"], None, "planned_state.last_transition_id", "initialization state must not have transition id"),
        ):
            if check:
                return check
    else:
        for check in (
            _require_equal(planned_audit["event_type"], "TRANSITION_ACCEPTED", "planned_audit_event.event_type", "transition must plan TRANSITION_ACCEPTED audit event"),
            _require_equal(planned_audit["transition_id"], record["operation_id"], "planned_audit_event.transition_id", "planned audit transition_id must match operation_id"),
            _require_equal(planned_audit["from_state"], canonical_request["from_state"], "planned_audit_event.from_state", "planned audit from_state must match request"),
            _require_equal(planned_audit["to_state"], canonical_request["to_state"], "planned_audit_event.to_state", "planned audit to_state must match request"),
            _require_equal(planned_state["current_state"], canonical_request["to_state"], "planned_state.current_state", "planned state current_state must match request target"),
            _require_equal(planned_state["previous_state"], canonical_request["from_state"], "planned_state.previous_state", "planned state previous_state must match request source"),
            _require_equal(planned_state["last_transition_id"], record["operation_id"], "planned_state.last_transition_id", "planned state last_transition_id must match operation_id"),
            _require_equal(planned_state["policy_evaluation_id"], canonical_request["policy_evaluation_binding"]["evaluation_id"], "planned_state.policy_evaluation_id", "planned state must bind policy evaluation id"),
            _require_equal(canonical_result["audit_event_id"], planned_audit["event_id"], "canonical_result.audit_event_id", "result audit_event_id must match planned audit event"),
            _require_equal(planned_state["audit_head_event_id"], planned_audit["event_id"], "planned_state.audit_head_event_id", "planned state audit head event must match planned audit event"),
            _require_equal(planned_state["audit_head_hash"], planned_audit["event_hash"], "planned_state.audit_head_hash", "planned state audit head hash must match planned audit event"),
            _require_equal(planned_state["audit_generation"], planned_audit["generation"], "planned_state.audit_generation", "planned state audit generation must match planned audit event"),
            _require_equal(planned_audit["policy_evaluation_binding"], canonical_request["policy_evaluation_binding"], "planned_audit_event.policy_evaluation_binding", "planned audit policy binding must match request"),
            _require_equal(planned_audit["evidence_bindings"], canonical_request["evidence_bindings"], "planned_audit_event.evidence_bindings", "planned audit evidence bindings must match request"),
        ):
            if check:
                return check
    graph = _validate_transition_operation_graph(
        record,
        request=canonical_request,
        result=canonical_result,
        planned_audit=planned_audit,
        planned_state=planned_state,
    )
    if not graph.valid:
        return graph
    for field, target in (
        ("planned_audit_event_hash", record["planned_audit_event"]),
        ("planned_state_hash", record["planned_state"]),
        ("planned_result_hash", record["canonical_result"]),
    ):
        if record[field] != _canonical_sha(target):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", field, "planned hash mismatch")
    return valid_outcome()


def _validate_trusted_prefix(record: object, prefix: str) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", prefix, "trusted prefix must be a mapping")
    error = _validate_exact_mapping(record, TRUSTED_PREFIX_FIELDS, "trusted prefix", prefix=prefix)
    if error:
        return _with_code(error, "WORKFLOW_TRANSACTION_INCOMPLETE")
    for check in (
        _require_positive_int(record["generation"], _join(prefix, "generation")),
        _require_positive_int(record["sequence"], _join(prefix, "sequence")),
        _require_safe_id(record["event_id"], _join(prefix, "event_id")),
        _require_sha(record["event_hash"], _join(prefix, "event_hash")),
    ):
        if check:
            return _with_code(check, "WORKFLOW_TRANSACTION_INCOMPLETE")
    return valid_outcome()


def _validate_recovery_diagnostic(record: object, prefix: str = "planned_recovery_record.diagnostic") -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", prefix, "recovery diagnostic must be a mapping")
    error = _validate_exact_mapping(record, RECOVERY_DIAGNOSTIC_FIELDS, "recovery diagnostic", prefix=prefix)
    if error:
        return _with_code(error, "WORKFLOW_TRANSACTION_INCOMPLETE")
    for check in (
        _require_non_empty_string(record["recovery_reason"], _join(prefix, "recovery_reason")),
        _require_member(record["threat_model"], THREAT_MODELS, _join(prefix, "threat_model"), "WORKFLOW_TRANSACTION_INCOMPLETE"),
        _require_member(record["stale_phase_classification"], STALE_PHASE_CLASSIFICATIONS, _join(prefix, "stale_phase_classification"), "WORKFLOW_TRANSACTION_INCOMPLETE"),
    ):
        if check:
            return _with_code(check, "WORKFLOW_TRANSACTION_INCOMPLETE")
    trusted = _validate_trusted_prefix(record["previous_trusted_prefix"], _join(prefix, "previous_trusted_prefix"))
    if not trusted.valid:
        return trusted
    return valid_outcome()


def _validate_quarantine_manifest(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "planned_quarantine_manifest", "planned quarantine manifest must be a mapping")
    error = _validate_exact_mapping(record, QUARANTINE_MANIFEST_FIELDS, "planned quarantine manifest", prefix="planned_quarantine_manifest")
    if error:
        return _with_code(error, "WORKFLOW_TRANSACTION_INCOMPLETE")
    for check in (
        _require_non_negative_int(record["size_bytes"], "planned_quarantine_manifest.size_bytes"),
        _require_sha(record["content_sha256"], "planned_quarantine_manifest.content_sha256"),
    ):
        if check:
            return _with_code(check, "WORKFLOW_TRANSACTION_INCOMPLETE")
    for path_field in ("source_path", "destination_path"):
        if not _is_safe_relative_path(record[path_field]):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"planned_quarantine_manifest.{path_field}", "path must be safe relative POSIX path")
    return valid_outcome()


def _validate_idempotency_record(
    record: object,
    *,
    request: dict[str, Any],
    result: dict[str, Any],
    operation_kind: str,
    transaction_path: str,
    prefix: str = "planned_idempotency_record",
) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", prefix, "planned idempotency record must be a mapping")
    error = _validate_exact_mapping(record, IDEMPOTENCY_RECORD_FIELDS, "planned idempotency record", prefix=prefix)
    if error:
        return _with_code(error, "WORKFLOW_TRANSACTION_INCOMPLETE")
    for check in (
        _validate_schema_version(record["schema_version"], _join(prefix, "schema_version")),
        _require_member(record["operation_kind"], RECOVERY_OPERATION_KINDS | TRANSITION_OPERATION_KINDS, _join(prefix, "operation_kind"), "WORKFLOW_TRANSACTION_INCOMPLETE"),
        _require_safe_id(record["operation_id"], _join(prefix, "operation_id")),
        _require_safe_id(record["task_id"], _join(prefix, "task_id")),
        _require_non_empty_string(record["idempotency_key"], _join(prefix, "idempotency_key")),
        _require_sha(record["request_fingerprint"], _join(prefix, "request_fingerprint")),
        _require_sha(record["result_fingerprint"], _join(prefix, "result_fingerprint")),
        _validate_utc(record["created_at_utc"], _join(prefix, "created_at_utc")),
        _require_equal(record["operation_kind"], operation_kind, _join(prefix, "operation_kind"), "idempotency operation_kind must match transaction"),
        _require_equal(record["operation_id"], request["recovery_id"], _join(prefix, "operation_id"), "idempotency operation_id must match request"),
        _require_equal(record["task_id"], request["task_id"], _join(prefix, "task_id"), "idempotency task_id must match request"),
        _require_equal(record["idempotency_key"], request["idempotency_key"], _join(prefix, "idempotency_key"), "idempotency key must match request"),
        _require_equal(record["request_fingerprint"], _operation_request_fingerprint(request), _join(prefix, "request_fingerprint"), "idempotency request fingerprint must match timestamp-free request"),
        _require_equal(record["result_fingerprint"], _canonical_sha(result), _join(prefix, "result_fingerprint"), "idempotency result fingerprint must match result"),
        _require_equal(record["canonical_result"], result, _join(prefix, "canonical_result"), "idempotency canonical_result must match result"),
        _require_equal(record["transaction_path"], transaction_path, _join(prefix, "transaction_path"), "idempotency transaction path must match transaction"),
    ):
        if check:
            return _with_code(check, "WORKFLOW_TRANSACTION_INCOMPLETE")
    if not _is_safe_relative_path(record["transaction_path"]):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", _join(prefix, "transaction_path"), "transaction path must be safe relative POSIX path")
    return valid_outcome()


def _validate_planned_recovery_record(
    record: object,
    request: dict[str, Any],
    result: dict[str, Any],
    *,
    operation_kind: str,
    quarantine: object,
    generation_event: object,
    state: object,
) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "planned_recovery_record", "planned recovery record must be a mapping")
    error = _validate_exact_mapping(record, RECOVERY_RECORD_FIELDS, "planned recovery record", prefix="planned_recovery_record")
    if error:
        return _with_code(error, "WORKFLOW_TRANSACTION_INCOMPLETE")
    expected_hashes = {
        "canonical_recovery_request_sha256": _canonical_sha(request),
        "canonical_recovery_result_sha256": _canonical_sha(result),
        "quarantine_manifest_sha256": None if quarantine is None else _canonical_sha(quarantine),
        "generation_event_sha256": None if generation_event is None else _canonical_sha(generation_event),
        "state_sha256": None if state is None else _canonical_sha(state),
    }
    for check in (
        _validate_schema_version(record["schema_version"], "planned_recovery_record.schema_version"),
        _require_safe_id(record["recovery_id"], "planned_recovery_record.recovery_id"),
        _require_safe_id(record["task_id"], "planned_recovery_record.task_id"),
        _require_safe_id(record["project_id"], "planned_recovery_record.project_id"),
        _require_member(record["operation_kind"], RECOVERY_OPERATION_KINDS, "planned_recovery_record.operation_kind", "WORKFLOW_TRANSACTION_INCOMPLETE"),
        _require_sha(record["record_sha256"], "planned_recovery_record.record_sha256"),
        _validate_utc(record["created_at_utc"], "planned_recovery_record.created_at_utc"),
        _require_equal(record["recovery_id"], request["recovery_id"], "planned_recovery_record.recovery_id", "planned recovery_id must match request"),
        _require_equal(record["task_id"], request["task_id"], "planned_recovery_record.task_id", "planned task_id must match request"),
        _require_equal(record["project_id"], request["project_id"], "planned_recovery_record.project_id", "planned project_id must match request"),
        _require_equal(record["operation_kind"], operation_kind, "planned_recovery_record.operation_kind", "planned operation_kind must match transaction"),
    ):
        if check:
            return _with_code(check, "WORKFLOW_TRANSACTION_INCOMPLETE")
    for field, expected in expected_hashes.items():
        actual = record[field]
        if expected is None:
            if actual is not None:
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"planned_recovery_record.{field}", "hash must be null when planned artifact is null")
        else:
            check = _require_sha(actual, f"planned_recovery_record.{field}")
            if check:
                return _with_code(check, "WORKFLOW_TRANSACTION_INCOMPLETE")
            if actual != expected:
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"planned_recovery_record.{field}", "planned recovery record hash mismatch")
    diagnostic = _validate_recovery_diagnostic(record["diagnostic"])
    if not diagnostic.valid:
        return diagnostic
    if record["record_sha256"] != _canonical_sha(dict(record, record_sha256=None)):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "planned_recovery_record.record_sha256", "record_sha256 does not match canonical recovery record")
    return valid_outcome()


def _validate_recovery_artifact_matrix(
    record: dict[str, Any],
    *,
    request: dict[str, Any],
    result: dict[str, Any],
) -> WorkflowValidationOutcome:
    matrix, error = _load_recovery_matrix()
    if error:
        return error
    assert matrix is not None
    status = "accepted" if result["accepted"] else "fail_closed" if result["fail_closed"] else "diagnostic_only"
    matching_rule = None
    for rule in matrix["rules"]:
        if rule.get("recovery_action") == request["recovery_action"] and rule.get("result_status") == status:
            matching_rule = rule
            break
    if matching_rule is None:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "recovery_artifact_matrix.rules", "missing recovery matrix rule")
    artifact_fields = matrix["artifact_fields"]
    if set(matching_rule.get("artifacts", {})) != set(artifact_fields):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "recovery_artifact_matrix.rules.artifacts", "matrix rule artifact coverage is invalid")
    for artifact_name, token in matching_rule["artifacts"].items():
        role = matrix["applicability_roles"].get(token)
        if role not in {"required", "optional", "forbidden"}:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "recovery_artifact_matrix.applicability_roles", "unknown applicability role")
        mapping = artifact_fields[artifact_name]
        transaction_field = mapping["transaction_field"]
        planned_hash_key = mapping["planned_hash_key"]
        recovery_hash_field = mapping["recovery_record_hash_field"]
        if transaction_field not in record or planned_hash_key not in record["planned_hashes"]:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", transaction_field, "matrix references unknown transaction field")
        artifact = record[transaction_field]
        planned_hash = record["planned_hashes"][planned_hash_key]
        recovery_hash = None if recovery_hash_field is None else record["planned_recovery_record"][recovery_hash_field]
        if role == "forbidden":
            if artifact is not None:
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", transaction_field, "matrix forbids planned artifact")
            if planned_hash is not None:
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"planned_hashes.{planned_hash_key}", "forbidden artifact hash must be null")
            if recovery_hash_field is not None and recovery_hash is not None:
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"planned_recovery_record.{recovery_hash_field}", "forbidden artifact recovery-record hash must be null")
            continue
        if role == "required" and artifact is None:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", transaction_field, "matrix requires planned artifact")
        if artifact is None:
            if planned_hash is not None:
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"planned_hashes.{planned_hash_key}", "absent optional artifact hash must be null")
            if recovery_hash_field is not None and recovery_hash is not None:
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"planned_recovery_record.{recovery_hash_field}", "absent optional artifact recovery-record hash must be null")
            continue
        expected_hash = _canonical_sha(artifact)
        if planned_hash != expected_hash:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"planned_hashes.{planned_hash_key}", "planned hash mismatch")
        if recovery_hash_field is not None and recovery_hash != expected_hash:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"planned_recovery_record.{recovery_hash_field}", "recovery-record artifact hash mismatch")
        if isinstance(artifact, dict):
            for path_field in ("destination_path", "transaction_path"):
                if path_field in artifact and not _is_safe_relative_path(artifact[path_field]):
                    return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"{transaction_field}.{path_field}", "artifact destination path must be safe")
    return valid_outcome()


def _validate_recovery_operation_graph(
    record: dict[str, Any],
    *,
    request: dict[str, Any],
    result: dict[str, Any],
) -> WorkflowValidationOutcome:
    catalog, error = _load_task1_invariants()
    if error:
        return error
    assert catalog is not None
    graph = catalog["recovery_graph"]
    diagnostic = record["planned_recovery_record"]["diagnostic"]
    if diagnostic["recovery_reason"] not in graph["recovery_reason_registry"]:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "planned_recovery_record.diagnostic.recovery_reason", "recovery reason is not registered")
    if not result["accepted"]:
        status_key = "fail_closed" if result["fail_closed"] else "diagnostic_only"
        status_rule = graph["result_status_truth_table"].get(status_key)
        if not isinstance(status_rule, dict):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"task1_invariants.recovery_graph.result_status_truth_table.{status_key}", "missing recovery result status rule")
        if result["accepted"] != status_rule.get("accepted") or result["fail_closed"] != status_rule.get("fail_closed"):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "canonical_recovery_result", "recovery result status does not match catalog rule")
        for result_field in status_rule.get("side_effect_fields_must_be_null", []):
            if result.get(result_field) is not None:
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"canonical_recovery_result.{result_field}", "non-accepted recovery result must not claim side effects")
        for artifact_field in status_rule.get("planned_artifacts_must_be_null", []):
            if record.get(artifact_field) is not None:
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", artifact_field, "non-accepted recovery result must not plan side-effect artifacts")
    if result["accepted"]:
        action_rules = graph["artifact_truth_table"].get(request["recovery_action"], {})
        accepted_rule = action_rules.get("accepted")
        if not isinstance(accepted_rule, dict):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "task1_invariants.recovery_graph.artifact_truth_table", "missing accepted recovery action rule")
        for result_field, expectation in accepted_rule.items():
            if expectation is None:
                if result[result_field] is not None:
                    return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"canonical_recovery_result.{result_field}", "recovery result field must be null for this action")
            else:
                check = _require_equal(
                    result[result_field],
                    _get_path(record, expectation),
                    f"canonical_recovery_result.{result_field}",
                    f"recovery result {result_field} must match planned artifact graph",
                )
                if check:
                    return check
    if record["planned_generation_event"] is not None:
        for binding_name, bindings in graph["identity_bindings"].items():
            binding = _validate_catalog_bindings(
                record,
                bindings,
                table_path=f"task1_invariants.recovery_graph.identity_bindings.{binding_name}",
                code="WORKFLOW_TRANSACTION_INCOMPLETE",
            )
            if binding:
                return binding
    trusted_prefix = diagnostic["previous_trusted_prefix"]
    trusted_prefix_bindings = {
        left: right
        for left, right in graph["trusted_prefix_bindings"].items()
        if record["planned_generation_event"] is not None
        or ("planned_generation_event" not in left and "planned_generation_event" not in right)
    }
    prefix_binding = _validate_catalog_bindings(
        record,
        trusted_prefix_bindings,
        table_path="task1_invariants.recovery_graph.trusted_prefix_bindings",
        code="WORKFLOW_TRANSACTION_INCOMPLETE",
    )
    if prefix_binding:
        return prefix_binding
    if record["planned_quarantine_manifest"] is not None:
        quarantine_binding = _validate_catalog_bindings(
            record,
            graph["quarantine_bindings"],
            table_path="task1_invariants.recovery_graph.quarantine_bindings",
            code="WORKFLOW_TRANSACTION_INCOMPLETE",
        )
        if quarantine_binding:
            return quarantine_binding
        derivation = _validate_catalog_path_derivations(
            record,
            graph["path_derivations"],
            table_path="task1_invariants.recovery_graph.path_derivations",
            code="WORKFLOW_TRANSACTION_INCOMPLETE",
        )
        if derivation:
            return derivation
    if record["planned_generation_event"] is not None and result["new_generation"] is not None:
        continuity = _validate_generation_continuity(
            record,
            graph["generation_continuity"],
            table_path="task1_invariants.recovery_graph.generation_continuity",
            code="WORKFLOW_TRANSACTION_INCOMPLETE",
        )
        if continuity:
            return continuity
    if record["planned_generation_event"] is not None:
        event_prefix = record["planned_generation_event"]["details"]["previous_trusted_prefix"]
        if event_prefix != trusted_prefix:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "planned_recovery_record.diagnostic.previous_trusted_prefix", "generation event trusted prefix must match recovery diagnostic")
        if record["planned_quarantine_manifest"] is not None:
            destination = record["planned_quarantine_manifest"]["destination_path"]
            for check in (
                _require_equal(
                    record["planned_generation_event"]["details"]["quarantine_path"],
                    destination,
                    "planned_generation_event.details.quarantine_path",
                    "generation event quarantine path must match planned quarantine destination",
                ),
                _require_equal(
                    record["planned_generation_event"]["details"]["audit_generation"]["quarantine_path"],
                    destination,
                    "planned_generation_event.details.audit_generation.quarantine_path",
                    "audit generation quarantine path must match planned quarantine destination",
                ),
            ):
                if check:
                    return check
    return valid_outcome()


def validate_recovery_transaction(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "$", "recovery transaction must be a mapping")
    error = _validate_exact_mapping(record, RECOVERY_TRANSACTION_FIELDS, "recovery transaction")
    if error:
        return _with_code(error, "WORKFLOW_TRANSACTION_INCOMPLETE")
    _, catalog_error = _load_task1_invariants()
    if catalog_error:
        return catalog_error
    for check in (
        _validate_schema_version(record.get("schema_version"), "schema_version"),
        _require_safe_id(record.get("transaction_id"), "transaction_id"),
        _require_member(record.get("operation_kind"), RECOVERY_OPERATION_KINDS, "operation_kind", "WORKFLOW_TRANSACTION_INCOMPLETE"),
        _require_safe_id(record.get("operation_id"), "operation_id"),
        _require_safe_id(record.get("task_id"), "task_id"),
        _require_non_empty_string(record.get("idempotency_key"), "idempotency_key"),
        _validate_utc(record.get("created_at_utc"), "created_at_utc"),
    ):
        if check:
            return _with_code(check, "WORKFLOW_TRANSACTION_INCOMPLETE")
    if isinstance(record.get("canonical_recovery_request"), dict):
        for check in (
            _require_equal(record["task_id"], record["canonical_recovery_request"].get("task_id"), "task_id", "transaction task_id must match recovery request"),
            _require_equal(record["idempotency_key"], record["canonical_recovery_request"].get("idempotency_key"), "idempotency_key", "transaction idempotency_key must match request"),
        ):
            if check:
                return check
    for field in ("canonical_recovery_request", "canonical_recovery_result", "planned_recovery_record"):
        if not isinstance(record[field], dict):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", field, "must be a mapping")
    if record["planned_quarantine_manifest"] is not None and not isinstance(record["planned_quarantine_manifest"], dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "planned_quarantine_manifest", "must be null or mapping")
    if record["planned_generation_event"] is not None and not isinstance(record["planned_generation_event"], dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "planned_generation_event", "must be null or mapping")
    if record["planned_state"] is not None and not isinstance(record["planned_state"], dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "planned_state", "must be null or mapping")
    if record["planned_idempotency_record"] is not None and not isinstance(record["planned_idempotency_record"], dict):
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "planned_idempotency_record", "must be null or mapping")
    expected_paths = {
        "phase_journal_path": _transaction_artifact_path(record["task_id"], "recovery", record["operation_id"], "phases.0001.jsonl"),
        "phase_journal_index_path": _transaction_artifact_path(record["task_id"], "recovery", record["operation_id"], "phase_segments.jsonl"),
    }
    for path_field, expected_path in expected_paths.items():
        if not isinstance(record[path_field], str) or not _is_safe_relative_path(record[path_field]) or record[path_field] != expected_path:
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", path_field, f"{path_field} must be {expected_path}")
    if set(record["planned_hashes"]) != RECOVERY_PLANNED_HASH_KEYS:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "planned_hashes", "planned_hashes keys are invalid")
    request = validate_recovery_request(record["canonical_recovery_request"])
    result = validate_recovery_result(record["canonical_recovery_result"])
    if not request.valid:
        return _with_code(request, "WORKFLOW_TRANSACTION_INCOMPLETE")
    if not result.valid:
        return _with_code(result, "WORKFLOW_TRANSACTION_INCOMPLETE")
    request_record = record["canonical_recovery_request"]
    result_record = record["canonical_recovery_result"]
    expected_operation_kind = "ROLLBACK" if request_record["recovery_action"] == "rollback_to_valid_prefix" else "RECOVERY"
    for check in (
        _require_equal(record["operation_kind"], expected_operation_kind, "operation_kind", "operation_kind must match recovery_action"),
        _require_equal(record["operation_id"], request_record["recovery_id"], "operation_id", "operation_id must equal canonical request recovery_id"),
        _require_equal(record["operation_id"], result_record["recovery_id"], "canonical_recovery_result.recovery_id", "result recovery_id must match operation_id"),
        _require_equal(record["task_id"], request_record["task_id"], "task_id", "transaction task_id must match recovery request"),
        _require_equal(record["task_id"], result_record["task_id"], "canonical_recovery_result.task_id", "result task_id must match transaction"),
        _require_equal(record["idempotency_key"], request_record["idempotency_key"], "idempotency_key", "transaction idempotency_key must match request"),
        _require_equal(request_record["project_id"], result_record["project_id"], "canonical_recovery_result.project_id", "result project_id must match request"),
    ):
        if check:
            return check
    if record["operation_id"] != request_record["recovery_id"]:
        return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", "operation_id", "operation_id must equal canonical request recovery_id")
    if record["planned_quarantine_manifest"] is not None:
        manifest = _validate_quarantine_manifest(record["planned_quarantine_manifest"])
        if not manifest.valid:
            return manifest
    if record["planned_generation_event"] is not None:
        event = validate_audit_event(record["planned_generation_event"])
        if not event.valid:
            return _with_code(event, "WORKFLOW_TRANSACTION_INCOMPLETE")
        expected_event_type = "ROLLBACK_RECORDED" if request_record["recovery_action"] == "rollback_to_valid_prefix" else "RECOVERY_RECORDED"
        for check in (
            _require_equal(record["planned_generation_event"]["event_type"], expected_event_type, "planned_generation_event.event_type", "generation event type must match recovery action"),
            _require_equal(record["planned_generation_event"]["task_id"], record["task_id"], "planned_generation_event.task_id", "generation task_id must match transaction"),
            _require_equal(record["planned_generation_event"]["project_id"], request_record["project_id"], "planned_generation_event.project_id", "generation project_id must match request"),
            _require_equal(record["planned_generation_event"]["details"]["recovery_id"], request_record["recovery_id"], "planned_generation_event.details.recovery_id", "generation event recovery_id must match request"),
            _require_equal(record["planned_generation_event"]["details"]["recovery_action"], request_record["recovery_action"], "planned_generation_event.details.recovery_action", "generation event action must match request"),
            _require_equal(record["planned_generation_event"]["details"]["recovery_transaction_id"], record["transaction_id"], "planned_generation_event.details.recovery_transaction_id", "generation event transaction id must match transaction"),
            _require_equal(result_record["started_by_event_id"], record["planned_generation_event"]["event_id"], "canonical_recovery_result.started_by_event_id", "result started event must match planned generation event"),
            _require_equal(result_record["started_by_event_type"], record["planned_generation_event"]["event_type"], "canonical_recovery_result.started_by_event_type", "result started event type must match planned generation event"),
            _require_equal(result_record["new_generation"], record["planned_generation_event"]["generation"], "canonical_recovery_result.new_generation", "result new_generation must match planned event"),
            _require_equal(result_record["previous_generation"], record["planned_generation_event"]["details"]["previous_trusted_prefix"]["generation"], "canonical_recovery_result.previous_generation", "result previous_generation must match generation event trusted prefix"),
            _require_equal(result_record["previous_valid_head_hash"], record["planned_generation_event"]["details"]["previous_trusted_prefix"]["event_hash"], "canonical_recovery_result.previous_valid_head_hash", "result previous hash must match generation event trusted prefix"),
        ):
            if check:
                return check
    if record["planned_quarantine_manifest"] is not None:
        check = _require_equal(
            result_record["quarantine_path"],
            record["planned_quarantine_manifest"]["destination_path"],
            "canonical_recovery_result.quarantine_path",
            "result quarantine_path must match planned quarantine destination",
        )
        if check:
            return check
    if record["planned_state"] is not None:
        state = validate_task_state(record["planned_state"])
        if not state.valid:
            return _with_code(state, "WORKFLOW_TRANSACTION_INCOMPLETE")
        for check in (
            _require_equal(record["planned_state"]["task_id"], record["task_id"], "planned_state.task_id", "planned state task_id must match transaction"),
            _require_equal(record["planned_state"]["project_id"], request_record["project_id"], "planned_state.project_id", "planned state project_id must match request"),
            _require_equal(record["planned_state"]["current_state"], result_record["resulting_state"], "planned_state.current_state", "planned state current_state must match result"),
        ):
            if check:
                return check
        if record["planned_generation_event"] is not None:
            for check in (
                _require_equal(record["planned_state"]["audit_head_event_id"], record["planned_generation_event"]["event_id"], "planned_state.audit_head_event_id", "planned state audit head event must match generation event"),
                _require_equal(record["planned_state"]["audit_head_hash"], record["planned_generation_event"]["event_hash"], "planned_state.audit_head_hash", "planned state audit head hash must match generation event"),
                _require_equal(record["planned_state"]["audit_generation"], record["planned_generation_event"]["generation"], "planned_state.audit_generation", "planned state audit generation must match generation event"),
            ):
                if check:
                    return check
    transaction_path = f"state/transactions/{record['task_id']}/recovery-{record['operation_id']}"
    if record["planned_idempotency_record"] is not None:
        idempotency = _validate_idempotency_record(
            record["planned_idempotency_record"],
            request=request_record,
            result=result_record,
            operation_kind=record["operation_kind"],
            transaction_path=transaction_path,
        )
        if not idempotency.valid:
            return idempotency
    recovery_record = _validate_planned_recovery_record(
        record["planned_recovery_record"],
        request_record,
        result_record,
        operation_kind=record["operation_kind"],
        quarantine=record["planned_quarantine_manifest"],
        generation_event=record["planned_generation_event"],
        state=record["planned_state"],
    )
    if not recovery_record.valid:
        return recovery_record
    matrix = _validate_recovery_artifact_matrix(record, request=request_record, result=result_record)
    if not matrix.valid:
        return matrix
    graph = _validate_recovery_operation_graph(record, request=request_record, result=result_record)
    if not graph.valid:
        return graph
    planned_hash_expectations = {
        "request": record["canonical_recovery_request"],
        "result": record["canonical_recovery_result"],
        "recovery_record": record["planned_recovery_record"],
        "quarantine": record["planned_quarantine_manifest"],
        "generation_event": record["planned_generation_event"],
        "state": record["planned_state"],
        "idempotency_record": record["planned_idempotency_record"],
    }
    for key, planned in planned_hash_expectations.items():
        actual = record["planned_hashes"][key]
        if planned is None:
            if actual is not None:
                return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"planned_hashes.{key}", "hash must be null when planned artifact is null")
        elif actual != _canonical_sha(planned):
            return invalid_outcome("WORKFLOW_TRANSACTION_INCOMPLETE", f"planned_hashes.{key}", "planned hash mismatch")
    return valid_outcome()


def validate_recovery_request(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", "$", "recovery request must be a mapping")
    error = _validate_exact_mapping(record, RECOVERY_REQUEST_FIELDS, "recovery request")
    if error:
        return error
    for check in (
        _validate_schema_version(record.get("schema_version"), "schema_version"),
        _require_safe_id(record.get("recovery_id"), "recovery_id"),
        _require_safe_id(record.get("task_id"), "task_id"),
        _require_safe_id(record.get("project_id"), "project_id"),
        _require_member(record.get("actor"), RECOVERY_ACTORS, "actor"),
        _require_non_empty_string(record.get("idempotency_key"), "idempotency_key"),
        _require_member(record.get("recovery_action"), RECOVERY_ACTIONS, "recovery_action"),
        _validate_utc(record.get("requested_at_utc"), "requested_at_utc"),
    ):
        if check:
            return check
    for path_field in ("observed_state_path", "observed_audit_path"):
        if record[path_field] is not None and not _is_safe_relative_path(record[path_field]):
            return invalid_outcome("WORKFLOW_INVALID_INPUT", path_field, "path must be safe relative POSIX path")
    if record["observed_audit_generation"] is not None:
        check = _require_positive_int(record["observed_audit_generation"], "observed_audit_generation")
        if check:
            return check
    return valid_outcome()


def validate_recovery_result(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", "$", "recovery result must be a mapping")
    error = _validate_exact_mapping(record, RECOVERY_RESULT_FIELDS, "recovery result")
    if error:
        return error
    for check in (
        _validate_schema_version(record.get("schema_version"), "schema_version"),
        _require_safe_id(record.get("recovery_id"), "recovery_id"),
        _require_safe_id(record.get("task_id"), "task_id"),
        _require_safe_id(record.get("project_id"), "project_id"),
        _validate_utc(record.get("created_at_utc"), "created_at_utc"),
        _require_bool(record.get("accepted"), "accepted"),
        _require_bool(record.get("fail_closed"), "fail_closed"),
    ):
        if check:
            return check
    envelope = _validate_result_envelope(record, id_path="recovery_id", require_audit_event=False)
    if not envelope.valid:
        return envelope
    if record["accepted"]:
        if record["previous_generation"] is None:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "previous_generation", "accepted recovery needs previous trusted generation")
        if record["previous_valid_head_hash"] is None:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "previous_valid_head_hash", "accepted recovery needs previous trusted head hash")
        if record["new_generation"] is not None and (record["started_by_event_id"] is None or record["started_by_event_type"] is None):
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "started_by_event_id", "new generation requires start event")
    else:
        for field in ("quarantine_path", "new_generation", "started_by_event_id", "started_by_event_type", "resulting_state"):
            if record[field] is not None:
                return invalid_outcome("WORKFLOW_INVALID_INPUT", field, "rejected recovery result must not claim side effects")
    for int_field in ("previous_generation", "new_generation"):
        if record[int_field] is not None:
            check = _require_positive_int(record[int_field], int_field)
            if check:
                return check
    for hash_field in ("previous_valid_head_hash",):
        if record[hash_field] is not None:
            check = _require_sha(record[hash_field], hash_field)
            if check:
                return check
    for id_field in ("started_by_event_id",):
        if record[id_field] is not None:
            check = _require_safe_id(record[id_field], id_field)
            if check:
                return check
    if record["started_by_event_type"] is not None and record["started_by_event_type"] not in RECOVERY_EVENT_TYPES:
        return invalid_outcome("WORKFLOW_INVALID_INPUT", "started_by_event_type", "unknown recovery event type")
    if record["quarantine_path"] is not None and not _is_safe_relative_path(record["quarantine_path"]):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", "quarantine_path", "path must be safe relative POSIX path")
    return valid_outcome()


def validate_audit_generation(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "$", "audit generation must be a mapping")
    error = _validate_exact_mapping(record, AUDIT_GENERATION_FIELDS, "audit generation")
    if error:
        return _with_code(error, "WORKFLOW_AUDIT_CORRUPT")
    for check in (
        _validate_schema_version(record.get("schema_version"), "schema_version"),
        _require_safe_id(record.get("task_id"), "task_id"),
        _require_positive_int(record.get("generation"), "generation"),
        _require_safe_id(record.get("started_by_event_id"), "started_by_event_id"),
        _require_member(record.get("started_by_event_type"), EVENT_TYPES | RECOVERY_EVENT_TYPES, "started_by_event_type", "WORKFLOW_AUDIT_CORRUPT"),
        _require_member(record.get("threat_model"), THREAT_MODELS, "threat_model", "WORKFLOW_AUDIT_CORRUPT"),
        _validate_utc(record.get("created_at_utc"), "created_at_utc"),
    ):
        if check:
            return _with_code(check, "WORKFLOW_AUDIT_CORRUPT")
    if record["predecessor_generation"] is not None:
        check = _require_positive_int(record["predecessor_generation"], "predecessor_generation")
        if check:
            return _with_code(check, "WORKFLOW_AUDIT_CORRUPT")
    if record["predecessor_valid_head_hash"] is not None:
        check = _require_sha(record["predecessor_valid_head_hash"], "predecessor_valid_head_hash")
        if check:
            return _with_code(check, "WORKFLOW_AUDIT_CORRUPT")
    if record["generation"] == 1:
        if record["started_by_event_type"] != "TASK_CREATED":
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "started_by_event_type", "generation 1 must start with TASK_CREATED")
        if record["predecessor_generation"] is not None or record["predecessor_valid_head_hash"] is not None or record["quarantine_path"] is not None:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "predecessor_generation", "generation 1 must not have predecessor or quarantine")
    else:
        if record["predecessor_generation"] is None or record["predecessor_valid_head_hash"] is None:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "predecessor_generation", "generation greater than 1 requires predecessor")
        if record["started_by_event_type"] not in RECOVERY_EVENT_TYPES:
            return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "started_by_event_type", "generation greater than 1 must start with recovery or rollback")
    if record["quarantine_path"] is not None and not _is_safe_relative_path(record["quarantine_path"]):
        return invalid_outcome("WORKFLOW_AUDIT_CORRUPT", "quarantine_path", "path must be safe relative POSIX path")
    return valid_outcome()


def validate_evidence_binding(record: object, *, prefix: str = "") -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", prefix or "$", "evidence binding must be a mapping")
    error = _validate_exact_mapping(record, EVIDENCE_BINDING_FIELDS, "evidence binding", prefix=prefix)
    if error:
        return error
    for check in (
        _validate_schema_version(record.get("schema_version"), _join(prefix, "schema_version")),
        _require_safe_id(record.get("binding_id"), _join(prefix, "binding_id")),
        _require_non_empty_string(record.get("evidence_kind"), _join(prefix, "evidence_kind")),
        _require_sha(record.get("content_sha256"), _join(prefix, "content_sha256")),
        _require_non_negative_int(record.get("size_bytes"), _join(prefix, "size_bytes")),
        _validate_optional_utc(record.get("created_at_utc"), _join(prefix, "created_at_utc")),
    ):
        if check:
            return check
    tagged = _validate_tagged_source(record, hash_field="embedded_sha256", prefix=prefix)
    if not tagged.valid:
        return tagged
    if record["source"] == "embedded":
        payload = canonical_json_bytes(record["embedded_record"])
        if hashlib.sha256(payload).hexdigest() != record["content_sha256"]:
            return invalid_outcome("WORKFLOW_EVIDENCE_HASH_MISMATCH", _join(prefix, "content_sha256"), "content_sha256 does not match embedded evidence bytes")
        if len(payload) != record["size_bytes"]:
            return invalid_outcome("WORKFLOW_EVIDENCE_HASH_MISMATCH", _join(prefix, "size_bytes"), "size_bytes does not match embedded evidence bytes")
    return valid_outcome()


def validate_policy_evaluation_binding(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_POLICY_RESULT_INVALID", "policy_evaluation_binding", "policy binding must be a mapping")
    error = _validate_exact_mapping(record, POLICY_BINDING_FIELDS, "policy binding", prefix="policy_evaluation_binding")
    if error:
        return _with_code(error, "WORKFLOW_POLICY_RESULT_INVALID")
    for check in (
        _validate_schema_version(record.get("schema_version"), "policy_evaluation_binding.schema_version"),
        _require_safe_id(record.get("evaluation_id"), "policy_evaluation_binding.evaluation_id"),
        _require_sha(record.get("result_sha256"), "policy_evaluation_binding.result_sha256"),
        _require_sha(record.get("policy_bundle_digest"), "policy_evaluation_binding.policy_bundle_digest"),
        _validate_optional_utc(record.get("created_at_utc"), "policy_evaluation_binding.created_at_utc"),
    ):
        if check:
            return _with_code(check, "WORKFLOW_POLICY_RESULT_INVALID")
    if type(record.get("human_gate")) is not bool:
        return invalid_outcome("WORKFLOW_POLICY_RESULT_INVALID", "policy_evaluation_binding.human_gate", "human_gate must be a boolean")
    if not _is_unique_state_list(record.get("authorized_transitions")):
        return invalid_outcome("WORKFLOW_POLICY_RESULT_INVALID", "policy_evaluation_binding.authorized_transitions", "authorized_transitions must be unique declared states")
    if record["human_gate"] and any(state not in HUMAN_GATE_AUTHORIZED_TRANSITIONS for state in record["authorized_transitions"]):
        return invalid_outcome(
            "WORKFLOW_POLICY_RESULT_INVALID",
            "policy_evaluation_binding.authorized_transitions",
            "human-gated policy bindings may authorize only WAITING_HUMAN or ABANDONED",
        )
    tagged = _validate_tagged_source(record, hash_field=None, prefix="policy_evaluation_binding")
    if not tagged.valid:
        return _with_code(tagged, "WORKFLOW_POLICY_RESULT_INVALID")
    embedded = record["embedded_record"]
    if embedded is not None:
        try:
            validate_contract("policy_evaluation_result", embedded)
        except ContractValidationError as exc:
            issue = exc.issues[0] if exc.issues else WorkflowIssue("WORKFLOW_POLICY_RESULT_INVALID", "$", str(exc))
            return invalid_outcome(
                "WORKFLOW_POLICY_RESULT_INVALID",
                f"policy_evaluation_binding.embedded_record.{issue.path}",
                issue.message,
            )
        if hashlib.sha256(canonical_json_bytes(embedded)).hexdigest() != record["result_sha256"]:
            return invalid_outcome("WORKFLOW_POLICY_RESULT_INVALID", "policy_evaluation_binding.result_sha256", "policy result hash mismatch")
        if record["evaluation_id"] != embedded["evaluation_id"]:
            return invalid_outcome("WORKFLOW_POLICY_RESULT_INVALID", "policy_evaluation_binding.embedded_record.evaluation_id", "embedded evaluation_id must match binding")
        if record["policy_bundle_digest"] != embedded["policy_bundle_digest"]:
            return invalid_outcome("WORKFLOW_POLICY_RESULT_INVALID", "policy_evaluation_binding.policy_bundle_digest", "policy_bundle_digest must equal embedded PolicyEvaluationResult.v1")
        result_body = embedded["result"]
        if record["authorized_transitions"] != result_body["authorized_transitions"]:
            return invalid_outcome("WORKFLOW_POLICY_RESULT_INVALID", "policy_evaluation_binding.authorized_transitions", "authorized transitions do not match embedded result")
        if record["human_gate"] != result_body["human_gate"]:
            return invalid_outcome("WORKFLOW_POLICY_RESULT_INVALID", "policy_evaluation_binding.human_gate", "human_gate does not match embedded result")
    return valid_outcome()


def validate_human_decision_resolution_binding(
    record: object,
    *,
    expected_target_state: str | None = None,
    expected_project_id: str | None = None,
    expected_task_id: str | None = None,
) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_DECISION_BINDING_INVALID", "decision_resolution_binding", "decision binding must be a mapping")
    error = _validate_exact_mapping(record, DECISION_BINDING_FIELDS, "decision binding")
    if error:
        return _with_code(error, "WORKFLOW_DECISION_BINDING_INVALID")
    for check in (
        _validate_schema_version(record.get("schema_version"), "schema_version"),
        _require_safe_id(record.get("decision_id"), "decision_id"),
        _require_safe_id(record.get("project_id"), "project_id"),
        _require_safe_id(record.get("task_id"), "task_id"),
        _require_member(record.get("status"), {"RESOLVED"}, "status", "WORKFLOW_DECISION_BINDING_INVALID"),
        _require_member(record.get("authorized_target_state"), TASK_STATES, "authorized_target_state", "WORKFLOW_DECISION_BINDING_INVALID"),
        _require_sha(record.get("resolution_sha256"), "resolution_sha256"),
        _validate_utc(record.get("resolved_at_utc"), "resolved_at_utc"),
    ):
        if check:
            return _with_code(check, "WORKFLOW_DECISION_BINDING_INVALID")
    if expected_target_state is not None and record["authorized_target_state"] != expected_target_state:
        return invalid_outcome("WORKFLOW_DECISION_BINDING_INVALID", "authorized_target_state", "authorized target does not match requested transition target")
    if expected_project_id is not None and record["project_id"] != expected_project_id:
        return invalid_outcome("WORKFLOW_DECISION_BINDING_INVALID", "project_id", "decision project_id mismatch")
    if expected_task_id is not None and record["task_id"] != expected_task_id:
        return invalid_outcome("WORKFLOW_DECISION_BINDING_INVALID", "task_id", "decision task_id mismatch")
    tagged = _validate_tagged_source(record, hash_field="resolution_sha256", prefix="")
    if not tagged.valid:
        return _with_code(tagged, "WORKFLOW_DECISION_BINDING_INVALID")
    embedded = record["embedded_record"]
    if embedded is not None:
        try:
            validate_contract("human_decision_resolution", embedded)
        except ContractValidationError as exc:
            return invalid_outcome("WORKFLOW_DECISION_BINDING_INVALID", "embedded_record", str(exc))
        if embedded["decision_id"] != record["decision_id"]:
            return invalid_outcome("WORKFLOW_DECISION_BINDING_INVALID", "embedded_record.decision_id", "decision_id mismatch")
        if embedded["project_id"] != record["project_id"]:
            return invalid_outcome("WORKFLOW_DECISION_BINDING_INVALID", "embedded_record.project_id", "project_id mismatch")
        if embedded["task_id"] != record["task_id"]:
            return invalid_outcome("WORKFLOW_DECISION_BINDING_INVALID", "embedded_record.task_id", "task_id mismatch")
        if embedded["status"] != record["status"]:
            return invalid_outcome("WORKFLOW_DECISION_BINDING_INVALID", "embedded_record.status", "status mismatch")
        if embedded["resume_state"] != record["authorized_target_state"]:
            return invalid_outcome("WORKFLOW_DECISION_BINDING_INVALID", "embedded_record.resume_state", "resume_state mismatch")
        if embedded["resolved_at_utc"] != record["resolved_at_utc"]:
            return invalid_outcome("WORKFLOW_DECISION_BINDING_INVALID", "embedded_record.resolved_at_utc", "resolved_at_utc mismatch")
    return valid_outcome()


def validate_transition_result(record: object) -> WorkflowValidationOutcome:
    if not isinstance(record, dict):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", "$", "transition result must be a mapping")
    error = _validate_exact_mapping(record, TRANSITION_RESULT_FIELDS, "transition result")
    if error:
        return error
    for check in (
        _validate_schema_version(record.get("schema_version"), "schema_version"),
        _require_safe_id(record.get("transition_id"), "transition_id"),
        _require_safe_id(record.get("task_id"), "task_id"),
        _validate_utc(record.get("created_at_utc"), "created_at_utc"),
        _require_bool(record.get("accepted"), "accepted"),
        _require_bool(record.get("fail_closed"), "fail_closed"),
        _require_bool(record.get("idempotent_replay"), "idempotent_replay"),
    ):
        if check:
            return check
    return _validate_result_envelope(record, id_path="transition_id")


def _validate_result_envelope(
    record: dict[str, Any],
    *,
    id_path: str,
    allow_audit_coordinates: bool = False,
    require_audit_event: bool = True,
) -> WorkflowValidationOutcome:
    issues = record["issues"]
    if not isinstance(issues, list):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", "issues", "issues must be a list")
    if record["accepted"]:
        if record["fail_closed"]:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "fail_closed", "accepted result cannot be fail_closed")
        if record["error_code"] is not None:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "error_code", "accepted result must not have error_code")
        if issues:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "issues", "accepted result must not have issues")
        if record["resulting_state"] not in TASK_STATES:
            return invalid_outcome("WORKFLOW_UNKNOWN_STATE", "resulting_state", "accepted result needs a declared resulting_state")
        if require_audit_event and (not isinstance(record.get("audit_event_id"), str) or not record.get("audit_event_id")):
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "audit_event_id", "accepted result needs audit_event_id")
        if allow_audit_coordinates:
            generation = _require_positive_int(record.get("audit_generation"), "audit_generation")
            if generation:
                return generation
            sequence = _require_positive_int(record.get("audit_sequence"), "audit_sequence")
            if sequence:
                return sequence
    else:
        if not record["fail_closed"]:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "fail_closed", "rejected result must be fail_closed")
        if record["error_code"] not in WORKFLOW_ERROR_CODES:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "error_code", "rejected result needs registered error_code")
        if "audit_event_id" in record and record["audit_event_id"] is not None:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "audit_event_id", "rejected result must not have audit_event_id")
        if record["resulting_state"] is not None:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "resulting_state", "rejected result must not have resulting_state")
        if allow_audit_coordinates and (record.get("audit_generation") is not None or record.get("audit_sequence") is not None):
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "audit_generation", "rejected result must not have audit coordinates")
        if not issues:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", "issues", "rejected result needs issues")
        issue_error = _validate_issue_records(issues, "issues")
        if issue_error:
            return issue_error
    if not isinstance(record[id_path], str) or not record[id_path]:
        return invalid_outcome("WORKFLOW_INVALID_INPUT", id_path, "result id must be a non-empty string")
    return valid_outcome()


def _validate_evidence_binding_list(records: object, path: str) -> WorkflowValidationOutcome:
    if not isinstance(records, list):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", path, "evidence bindings must be a list")
    seen: set[str] = set()
    for index, binding in enumerate(records):
        evidence = validate_evidence_binding(binding, prefix=f"{path}[{index}]")
        if not evidence.valid:
            return evidence
        binding_id = binding["binding_id"]
        if binding_id in seen:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", f"{path}[{index}].binding_id", "duplicate evidence binding_id")
        seen.add(binding_id)
    return valid_outcome()


def _validate_issue_records(records: object, path: str) -> WorkflowValidationOutcome | None:
    if not isinstance(records, list):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", path, "issues must be a list")
    for index, issue in enumerate(records):
        if not isinstance(issue, dict):
            return invalid_outcome("WORKFLOW_INVALID_INPUT", f"{path}[{index}]", "issue must be a mapping")
        if set(issue) != {"code", "path", "message"}:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", f"{path}[{index}]", "issue fields are invalid")
        if issue["code"] not in WORKFLOW_ERROR_CODES:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", f"{path}[{index}].code", "issue code is not registered")
        if not isinstance(issue["path"], str) or not isinstance(issue["message"], str) or not issue["message"]:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", f"{path}[{index}]", "issue path/message invalid")
    return None


def _validate_exact_mapping(record: dict[str, Any], allowed: set[str], label: str, *, prefix: str = "") -> WorkflowValidationOutcome | None:
    for key in record:
        if key not in allowed:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", _join(prefix, str(key)), f"unknown field in {label}")
    for key in allowed:
        if key not in record:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", _join(prefix, key), f"missing required field in {label}")
    return None


def _validate_schema_version(value: object, path: str) -> WorkflowValidationOutcome | None:
    if type(value) is not int:
        return invalid_outcome("WORKFLOW_INVALID_INPUT", path, "schema_version must be an integer")
    if value != 1:
        return invalid_outcome("WORKFLOW_UNSUPPORTED_SCHEMA_VERSION", path, "unsupported schema version")
    return None


def _require_non_empty_string(value: object, path: str) -> WorkflowValidationOutcome | None:
    if not isinstance(value, str) or not value:
        return invalid_outcome("WORKFLOW_INVALID_INPUT", path, "must be a non-empty string")
    return None


def _require_safe_id(value: object, path: str) -> WorkflowValidationOutcome | None:
    if not isinstance(value, str) or not SAFE_ID_RE.fullmatch(value):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", path, "must be a safe non-empty identifier")
    return None


def _require_sha(value: object, path: str) -> WorkflowValidationOutcome | None:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", path, "must be a lowercase SHA-256 hex string")
    return None


def _require_bool(value: object, path: str) -> WorkflowValidationOutcome | None:
    if type(value) is not bool:
        return invalid_outcome("WORKFLOW_INVALID_INPUT", path, "must be a boolean")
    return None


def _require_non_negative_int(value: object, path: str) -> WorkflowValidationOutcome | None:
    if type(value) is not int or value < 0:
        return invalid_outcome("WORKFLOW_INVALID_INPUT", path, "must be a non-negative integer")
    return None


def _require_positive_int(value: object, path: str) -> WorkflowValidationOutcome | None:
    if type(value) is not int or value < 1:
        return invalid_outcome("WORKFLOW_INVALID_INPUT", path, "must be a positive integer")
    return None


def _require_member(value: object, allowed: set[str] | tuple[str, ...], path: str, code: str = "WORKFLOW_INVALID_INPUT") -> WorkflowValidationOutcome | None:
    if not isinstance(value, str) or value not in allowed:
        return invalid_outcome(code, path, "unknown or invalid value")
    return None


def _validate_utc(value: object, path: str) -> WorkflowValidationOutcome | None:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        return invalid_outcome("WORKFLOW_INVALID_INPUT", path, "must be an RFC3339 UTC timestamp")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return invalid_outcome("WORKFLOW_INVALID_INPUT", path, "must be a valid RFC3339 UTC timestamp")
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        return invalid_outcome("WORKFLOW_INVALID_INPUT", path, "must be a canonical RFC3339 UTC timestamp")
    return None


def _validate_optional_utc(value: object, path: str) -> WorkflowValidationOutcome | None:
    if value is None:
        return None
    return _validate_utc(value, path)


def _validate_tagged_source(record: dict[str, Any], *, hash_field: str | None, prefix: str) -> WorkflowValidationOutcome:
    source = record.get("source")
    if source not in SOURCES:
        return invalid_outcome("WORKFLOW_INVALID_INPUT", _join(prefix, "source"), "source must be path or embedded")
    path = record.get("path")
    embedded = record.get("embedded_record")
    if source == "path":
        if not isinstance(path, str) or not _is_safe_relative_path(path):
            return invalid_outcome("WORKFLOW_INVALID_INPUT", _join(prefix, "path"), "path must be safe relative POSIX path")
        if embedded is not None:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", _join(prefix, "embedded_record"), "embedded_record must be null for path source")
        if hash_field is not None and record.get(hash_field) is not None:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", _join(prefix, hash_field), f"{hash_field} must be null for path source")
    else:
        if path is not None:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", _join(prefix, "path"), "path must be null for embedded source")
        if embedded is None:
            return invalid_outcome("WORKFLOW_INVALID_INPUT", _join(prefix, "embedded_record"), "embedded_record is required for embedded source")
        if hash_field is not None:
            check = _require_sha(record.get(hash_field), _join(prefix, hash_field))
            if check:
                return check
            if hashlib.sha256(canonical_json_bytes(embedded)).hexdigest() != record[hash_field]:
                return invalid_outcome("WORKFLOW_EVIDENCE_HASH_MISMATCH", _join(prefix, hash_field), f"{hash_field} does not match embedded_record")
    return valid_outcome()


def _is_safe_relative_path(value: str) -> bool:
    if not value or "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def _is_unique_state_list(value: object) -> bool:
    return isinstance(value, list) and len(value) == len(set(value)) and all(state in TASK_STATES for state in value)


def _with_code(outcome: WorkflowValidationOutcome, code: str) -> WorkflowValidationOutcome:
    if outcome.valid:
        return outcome
    return invalid_outcome(code, outcome.issues[0].path, outcome.issues[0].message)


def _join(prefix: str, path: str) -> str:
    return f"{prefix}.{path}" if prefix else path
