from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Mapping

from acgps.policy_errors import POLICY_ERROR_CODES


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


class ContractValidationError(ValueError):
    def __init__(self, contract_name: str, issues: list[ValidationIssue]) -> None:
        self.contract_name = contract_name
        self.issues = issues
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        super().__init__(f"{contract_name} failed validation: {details}")


class UnknownContractError(KeyError):
    pass


class UnsupportedContractVersionError(ValueError):
    pass


@dataclass(frozen=True)
class FieldSpec:
    expected_type: type | tuple[type, ...]
    required: bool = True
    allow_empty: bool = True
    allowed_values: tuple[object, ...] | None = None
    fields: dict[str, "FieldSpec"] | None = None
    item_fields: dict[str, "FieldSpec"] | None = None
    item_type: type | tuple[type, ...] | None = None
    map_value_type: type | tuple[type, ...] | None = None


@dataclass(frozen=True)
class ContractSpec:
    name: str
    version: int
    fields: dict[str, FieldSpec]


DICT = dict
LIST = list
NONE = type(None)
STRING = str

RISK_LEVELS = ("R0", "R1", "R2", "R3")
ROLES = ("PLANNER", "CODER", "REVIEWER", "VERIFIER")
HUMAN_DECISION_TRIGGERS = (
    "H1_PRODUCT_INTENT",
    "H2_IRREVERSIBLE_OR_COSTLY",
    "H3_RISK_ACCEPTANCE",
    "H4_NORMATIVE_EXPERIENCE",
    "H5_EXTERNAL_ACTION",
)
TEMPLATE_PLACEHOLDERS = {
    "AUTO",
    "COMMAND",
    "HASH",
    "OPTION_ID",
    "PACKET_ID",
    "PATH",
    "PROJECT_ID",
    "REVIEW_ID",
    "ROLE",
    "STAGE",
    "TASK_ID",
    "VERSION",
}
PATH_FIELDS = {
    "path",
    "output_path",
    "rollback_plan_path",
}
PATH_COLLECTION_FIELDS = {
    "evidence_paths",
    "required_files",
    "review_closures",
    "source_paths",
    "verification_records",
}
STRING_LIST = FieldSpec(LIST, item_type=STRING)
TASK_STATES = (
    "DRAFT",
    "READY_FOR_CLASSIFICATION",
    "CLASSIFIED",
    "SPEC_READY",
    "PLAN_READY",
    "IMPLEMENTING",
    "TASK_REVIEW",
    "FIX_REQUIRED",
    "INTEGRATING",
    "SYSTEM_QA",
    "VERIFIED",
    "RC_READY",
    "WAITING_HUMAN",
    "BLOCKED",
    "CLOSED",
    "ABANDONED",
)
POLICY_SKILL_IDS = (
    "superpowers_writing_plans",
    "superpowers_requesting_code_review",
    "figma_design",
    "superpowers_verification_before_completion",
)
POLICY_MODEL_ROLE_IDS = (
    "planner_architect",
    "task_reviewer",
    "final_reviewer",
    "verifier",
)
POLICY_MODEL_ACTORS = (
    "planner",
    "reviewer",
    "verifier",
)
POLICY_GATE_IDS = (
    "focused_check",
    "lightweight_review",
    "spec",
    "tests",
    "independent_review",
    "affected_checks",
    "architecture",
    "plan",
    "broad_verification",
    "high_capability_review",
    "rc_evidence",
    "human_approval",
    "risk_analysis",
    "strongest_planner",
    "strongest_reviewer",
    "full_verification",
    "rollback_plan",
    "human_release",
)
PROVENANCE_RE = re.compile(r"^[A-Za-z0-9_./-]+\.ya?ml:[A-Za-z0-9_.\[\]-]+$")

def _contract(name: str, fields: dict[str, FieldSpec]) -> ContractSpec:
    return ContractSpec(name=name, version=1, fields=fields)


HUMAN_DECISION_OPTION_FIELDS = {
    "id": FieldSpec(STRING),
    "description": FieldSpec(STRING),
    "benefits": STRING_LIST,
    "costs": STRING_LIST,
    "risks": STRING_LIST,
    "reversible": FieldSpec(bool),
}

SOURCE_ARTIFACT_FIELDS = {
    "path": FieldSpec(STRING),
    "sha256": FieldSpec(STRING),
}

POLICY_EVALUATION_INPUT_FIELDS = {
    "current_state": FieldSpec(STRING, allowed_values=TASK_STATES),
    "risk_triggers": STRING_LIST,
    "human_triggers": STRING_LIST,
    "task_attributes": FieldSpec(DICT, map_value_type=STRING),
    "project_profile_id": FieldSpec((STRING, NONE)),
}

POLICY_EVALUATION_ISSUE_FIELDS = {
    "code": FieldSpec(STRING),
    "path": FieldSpec(STRING),
    "message": FieldSpec(STRING),
}

POLICY_EVALUATION_RESULT_FIELDS = {
    "decision_emitted": FieldSpec(bool),
    "risk_level": FieldSpec(STRING, allowed_values=RISK_LEVELS),
    "human_gate": FieldSpec(bool),
    "required_human_triggers": STRING_LIST,
    "required_skills": STRING_LIST,
    "model_roles": FieldSpec(DICT, map_value_type=STRING),
    "mandatory_gates": STRING_LIST,
    "legal_transitions": STRING_LIST,
    "authorized_transitions": STRING_LIST,
    "provenance": STRING_LIST,
    "fail_closed": FieldSpec(bool),
    "error_code": FieldSpec((STRING, NONE)),
    "issues": FieldSpec(LIST, item_fields=POLICY_EVALUATION_ISSUE_FIELDS),
}

VERIFICATION_CHECK_FIELDS = {
    "name": FieldSpec(STRING),
    "command": FieldSpec(STRING),
    "exit_code": FieldSpec(int),
    "result_summary": FieldSpec(STRING),
    "output_path": FieldSpec(STRING),
}

CODING_OPERATION_CLASSES = (
    "APPROVED_FILE_PATCH",
    "GIT_READ_ONLY_INSPECTION",
    "LOCAL_CHECK_PROCESS",
    "TARGETED_TEXT_SEARCH",
    "WORKSPACE_READ",
)
CODING_DISABLED_SURFACES = (
    "APPS",
    "AUTOMATIC_RESUME",
    "BROWSER",
    "HOOKS",
    "MCP",
    "MEMORIES",
    "MODEL_SEARCH",
    "MULTI_AGENT",
    "PLUGINS",
)
CODING_EXECUTOR_PLATFORM_PROFILES = (
    "WINDOWS_11_X64_NTFS_PYTHON_3_13_ELEVATED_PRIVATE_DESKTOP",
    "WINDOWS_SERVER_2022_X64_NTFS_PYTHON_3_13_ELEVATED_PRIVATE_DESKTOP",
)
CODING_SLOT_STATES = (
    "EMPTY",
    "ACTIVE_V1",
    "FROZEN_REVIEW_V1",
    "REJECTED_HOLD_V1",
    "EMPTY_FOR_REMEDIATION",
    "ACTIVE_V2",
    "FROZEN_REVIEW_V2",
)

CODING_PACKET_FIELDS = {
    "packet_id": FieldSpec(STRING),
    "path": FieldSpec(STRING),
    "sha256": FieldSpec(STRING),
    "size_bytes": FieldSpec(int),
    "role": FieldSpec(STRING, allowed_values=("TASK_PACKET",)),
    "validation_status": FieldSpec(STRING, allowed_values=("PASS", "HOLD")),
}
CODING_BASELINE_FIELDS = {
    "repository_path": FieldSpec(STRING),
    "commit": FieldSpec(STRING),
    "tree": FieldSpec(STRING),
    "before_state_sha256": FieldSpec(STRING),
    "after_state_sha256": FieldSpec(STRING),
    "unchanged": FieldSpec(bool),
}
CODING_SLOT_FIELDS = {
    "slot_id": FieldSpec(STRING),
    "state_before": FieldSpec(STRING, allowed_values=CODING_SLOT_STATES),
    "state_after": FieldSpec(STRING, allowed_values=CODING_SLOT_STATES),
    "active_candidate_before": FieldSpec((STRING, NONE)),
    "active_candidate_after": FieldSpec((STRING, NONE)),
    "historical_candidate_ids": STRING_LIST,
}
CODING_ATTEMPT_FIELDS = {
    "number": FieldSpec((int, NONE), allowed_values=(None, 1, 2)),
    "reserved_at_utc": FieldSpec((STRING, NONE)),
    "parent_candidate_id": FieldSpec((STRING, NONE)),
    "kind": FieldSpec(STRING, allowed_values=("PRELAUNCH", "ORDINARY", "REMEDIATION")),
    "remaining_before": FieldSpec(int, allowed_values=(0, 1, 2)),
    "remaining_after": FieldSpec(int, allowed_values=(0, 1, 2)),
    "process_start_request_count": FieldSpec(int),
}
CODING_EXECUTOR_FIELDS = {
    "path": FieldSpec(STRING),
    "size_bytes": FieldSpec((int, NONE)),
    "sha256": FieldSpec((STRING, NONE)),
    "authenticode_status": FieldSpec(STRING, allowed_values=("VALID", "INVALID", "MISSING")),
    "signer": FieldSpec((STRING, NONE)),
    "cli_version": FieldSpec((STRING, NONE)),
    "identity_complete": FieldSpec(bool),
    "argv": FieldSpec(LIST, item_type=STRING),
    "model": FieldSpec(STRING, allowed_values=("gpt-5.6-sol",)),
    "reasoning_effort": FieldSpec(STRING, allowed_values=("high",)),
    "auth_mode": FieldSpec(STRING, allowed_values=("CHATGPT_SUBSCRIPTION",)),
    "sandbox": FieldSpec(STRING, allowed_values=("ISOLATED_CLONE",)),
    "approval_policy": FieldSpec(STRING, allowed_values=("NEVER",)),
    "platform": FieldSpec(
        STRING,
        allowed_values=CODING_EXECUTOR_PLATFORM_PROFILES,
    ),
}
CODING_OPERATION_ROW_FIELDS = {
    "sequence": FieldSpec(int),
    "class": FieldSpec(STRING, allowed_values=CODING_OPERATION_CLASSES),
    "source": FieldSpec(
        STRING,
        allowed_values=("CONTROLLER_EVENT", "PROCESS_OBSERVATION", "FILESYSTEM_DIFF", "GIT_DIFF"),
    ),
    "event_id": FieldSpec((STRING, NONE)),
    "executable": FieldSpec((STRING, NONE)),
    "argv": FieldSpec(LIST, item_type=STRING),
    "cwd": FieldSpec((STRING, NONE)),
    "path_set": STRING_LIST,
    "status": FieldSpec(STRING, allowed_values=("PASS", "HOLD")),
    "evidence_sha256": FieldSpec(STRING),
}
CODING_CAPABILITY_FIELDS = {
    "boundary_mode": FieldSpec(STRING, allowed_values=("FIVE_CLASS_OPERATION_AND_PROMOTION_POLICY",)),
    "shell_identity_present": FieldSpec(bool, allowed_values=(True,)),
    "accepted_operation_classes": FieldSpec(LIST, item_type=STRING),
    "effective_config_sha256": FieldSpec((STRING, NONE)),
    "automatic_resume_enabled": FieldSpec(bool, allowed_values=(False,)),
    "hooks_enabled": FieldSpec(bool, allowed_values=(False,)),
    "memories_enabled": FieldSpec(bool, allowed_values=(False,)),
    "disabled_surfaces": FieldSpec(LIST, item_type=STRING),
    "authorized_write_paths": STRING_LIST,
    "check_allowlist_sha256": FieldSpec(STRING),
    "git_read_allowlist_sha256": FieldSpec(STRING),
    "network_policy_sha256": FieldSpec((STRING, NONE)),
    "observations_complete": FieldSpec(bool),
    "operation_rows": FieldSpec(LIST, item_fields=CODING_OPERATION_ROW_FIELDS),
}
CODING_CLONE_BEFORE_FIELDS = {
    "path": FieldSpec(STRING),
    "commit": FieldSpec(STRING),
    "tree": FieldSpec(STRING),
    "index_sha256": FieldSpec(STRING),
    "status_sha256": FieldSpec(STRING),
    "git_control_sha256": FieldSpec(STRING),
    "file_inventory_sha256": FieldSpec(STRING),
    "remote_count": FieldSpec(int, allowed_values=(0,)),
    "independent_git": FieldSpec(bool, allowed_values=(True,)),
    "detached": FieldSpec(bool, allowed_values=(True,)),
    "clean": FieldSpec(bool, allowed_values=(True,)),
}
CODING_PRELAUNCH_GATE_FIELDS = {
    "gate_id": FieldSpec(STRING, allowed_values=("P0", "P1", "P2", "P3", "P4", "P5", "P6")),
    "status": FieldSpec(STRING, allowed_values=("PASS", "HOLD")),
    "evidence_sha256": FieldSpec(STRING),
    "blocker_ids": STRING_LIST,
}
CODING_PRELAUNCH_FIELDS = {
    "state": FieldSpec(STRING, allowed_values=("PASS", "HOLD")),
    "checked_at_utc": FieldSpec(STRING),
    "gate_rows": FieldSpec(LIST, item_fields=CODING_PRELAUNCH_GATE_FIELDS),
    "model_request_started": FieldSpec(bool),
    "process_start_requested": FieldSpec(bool),
    "blocker_ids": STRING_LIST,
}
CODING_PROCESS_FIELDS = {
    "start_requested": FieldSpec(bool),
    "pid": FieldSpec((int, NONE)),
    "started_at_utc": FieldSpec((STRING, NONE)),
    "ended_at_utc": FieldSpec((STRING, NONE)),
    "exit_code": FieldSpec((int, NONE)),
    "timed_out": FieldSpec(bool),
    "cancelled": FieldSpec(bool),
    "error": FieldSpec((STRING, NONE)),
    "descendant_count": FieldSpec(int),
    "all_descendants_terminated": FieldSpec(bool),
    "stdout_sha256": FieldSpec((STRING, NONE)),
    "stderr_sha256": FieldSpec((STRING, NONE)),
}
CODING_EVENT_FIELDS = {
    "jsonl_sha256": FieldSpec((STRING, NONE)),
    "size_bytes": FieldSpec(int),
    "parsed_count": FieldSpec(int),
    "unknown_count": FieldSpec(int),
    "prohibited_count": FieldSpec(int),
    "final_response_sha256": FieldSpec((STRING, NONE)),
    "output_schema_valid": FieldSpec(bool),
}
CODING_AGENT_RESULT_FIELDS = {
    "path": FieldSpec((STRING, NONE)),
    "sha256": FieldSpec((STRING, NONE)),
    "size_bytes": FieldSpec(int),
    "contract_valid": FieldSpec(bool),
    "claimed_status": FieldSpec(
        (STRING, NONE),
        allowed_values=(None, "DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED", "FAILED"),
    ),
    "claims_match": FieldSpec(bool),
}
CODING_CLONE_AFTER_FIELDS = {
    "commit": FieldSpec(STRING),
    "tree": FieldSpec(STRING),
    "index_sha256": FieldSpec(STRING),
    "status_sha256": FieldSpec(STRING),
    "git_control_sha256": FieldSpec(STRING),
    "file_inventory_sha256": FieldSpec(STRING),
    "changed_paths": STRING_LIST,
    "diff_sha256": FieldSpec(STRING),
}
CODING_CANDIDATE_FIELDS = {
    "candidate_id": FieldSpec((STRING, NONE)),
    "version": FieldSpec((int, NONE), allowed_values=(None, 1, 2)),
    "status": FieldSpec(STRING, allowed_values=("NONE", "FROZEN_REVIEW")),
    "parent_candidate_id": FieldSpec((STRING, NONE)),
    "diff_sha256": FieldSpec((STRING, NONE)),
    "file_set_sha256": FieldSpec((STRING, NONE)),
    "checks_sha256": FieldSpec((STRING, NONE)),
    "promotion_predicates_passed": FieldSpec(bool),
}

CODING_EXECUTION_FIELDS = {
    "schema_version": FieldSpec(int),
    "execution_id": FieldSpec(STRING),
    "gate_id": FieldSpec(STRING),
    "project_id": FieldSpec(STRING),
    "task_id": FieldSpec(STRING),
    "packet": FieldSpec(DICT, fields=CODING_PACKET_FIELDS),
    "baseline": FieldSpec(DICT, fields=CODING_BASELINE_FIELDS),
    "slot": FieldSpec(DICT, fields=CODING_SLOT_FIELDS),
    "attempt": FieldSpec(DICT, fields=CODING_ATTEMPT_FIELDS),
    "executor": FieldSpec(DICT, fields=CODING_EXECUTOR_FIELDS),
    "capabilities": FieldSpec(DICT, fields=CODING_CAPABILITY_FIELDS),
    "clone_before": FieldSpec((DICT, NONE), fields=CODING_CLONE_BEFORE_FIELDS),
    "prelaunch": FieldSpec(DICT, fields=CODING_PRELAUNCH_FIELDS),
    "process": FieldSpec(DICT, fields=CODING_PROCESS_FIELDS),
    "events": FieldSpec(DICT, fields=CODING_EVENT_FIELDS),
    "agent_result": FieldSpec(DICT, fields=CODING_AGENT_RESULT_FIELDS),
    "clone_after": FieldSpec((DICT, NONE), fields=CODING_CLONE_AFTER_FIELDS),
    "candidate": FieldSpec(DICT, fields=CODING_CANDIDATE_FIELDS),
    "outcome": FieldSpec(
        STRING,
        allowed_values=("PRELAUNCH_HOLD", "ATTEMPT_FAILED", "ATTEMPT_HOLD", "CANDIDATE_READY"),
    ),
    "created_at_utc": FieldSpec(STRING),
}


_CONTRACTS: dict[tuple[str, int], ContractSpec] = {
    ("project_profile", 1): _contract(
        "project_profile",
        {
            "schema_version": FieldSpec(int),
            "profile_id": FieldSpec(STRING),
            "project_name": FieldSpec(STRING),
            "project_type": FieldSpec(STRING),
            "required_files": FieldSpec(DICT, map_value_type=STRING),
            "critical_surfaces": STRING_LIST,
            "risk_overrides": FieldSpec(DICT, map_value_type=STRING),
            "pilot_restrictions": STRING_LIST,
            "commands": FieldSpec(DICT, map_value_type=STRING),
        },
    ),
    ("task_intake", 1): _contract(
        name="task_intake",
        fields={
            "schema_version": FieldSpec(int),
            "task_id": FieldSpec(STRING),
            "project_id": FieldSpec(STRING),
            "title": FieldSpec(STRING),
            "requested_outcome": FieldSpec(STRING),
            "business_context": FieldSpec(STRING),
            "in_scope": STRING_LIST,
            "out_of_scope": STRING_LIST,
            "acceptance_criteria": STRING_LIST,
            "known_constraints": STRING_LIST,
            "known_risks": STRING_LIST,
            "affected_surfaces": STRING_LIST,
            "source_paths": STRING_LIST,
            "requested_by": FieldSpec(STRING),
            "created_at_utc": FieldSpec(STRING),
        },
    ),
    ("task_state", 1): _contract(
        "task_state",
        {
            "schema_version": FieldSpec(int),
            "task_id": FieldSpec(STRING),
            "project_id": FieldSpec(STRING),
            "state": FieldSpec(STRING, allowed_values=TASK_STATES),
            "updated_at_utc": FieldSpec(STRING),
            "evidence": STRING_LIST,
            "pending_decision_id": FieldSpec((STRING, NONE)),
        },
    ),
    ("risk_assessment", 1): _contract(
        "risk_assessment",
        {
            "schema_version": FieldSpec(int),
            "assessment_id": FieldSpec(STRING),
            "project_id": FieldSpec(STRING),
            "task_id": FieldSpec(STRING),
            "risk_level": FieldSpec(STRING, allowed_values=RISK_LEVELS),
            "matched_triggers": STRING_LIST,
            "required_gates": STRING_LIST,
            "model_recommendation": FieldSpec((STRING, NONE)),
            "created_at_utc": FieldSpec(STRING),
        },
    ),
    ("routing_decision", 1): _contract(
        "routing_decision",
        {
            "schema_version": FieldSpec(int),
            "routing_id": FieldSpec(STRING),
            "project_id": FieldSpec(STRING),
            "task_id": FieldSpec(STRING),
            "required_skills": STRING_LIST,
            "primary_discovery_route": FieldSpec((STRING, NONE)),
            "model_roles": FieldSpec(DICT, map_value_type=STRING),
            "mandatory_gates": STRING_LIST,
            "created_at_utc": FieldSpec(STRING),
        },
    ),
    ("policy_evaluation_input", 1): _contract(
        "policy_evaluation_input",
        {
            "schema_version": FieldSpec(int),
            "evaluation_id": FieldSpec(STRING),
            "project_id": FieldSpec(STRING),
            "task_id": FieldSpec(STRING),
            "input": FieldSpec(DICT, fields=POLICY_EVALUATION_INPUT_FIELDS),
            "created_at_utc": FieldSpec(STRING),
        },
    ),
    ("policy_evaluation_result", 1): _contract(
        "policy_evaluation_result",
        {
            "schema_version": FieldSpec(int),
            "evaluation_id": FieldSpec(STRING),
            "project_id": FieldSpec(STRING),
            "task_id": FieldSpec(STRING),
            "policy_bundle_digest": FieldSpec((STRING, NONE)),
            "result": FieldSpec(DICT, fields=POLICY_EVALUATION_RESULT_FIELDS),
            "created_at_utc": FieldSpec(STRING),
        },
    ),
    ("human_decision_request", 1): _contract(
        "human_decision_request",
        {
            "schema_version": FieldSpec(int),
            "decision_id": FieldSpec(STRING),
            "project_id": FieldSpec(STRING),
            "task_id": FieldSpec(STRING),
            "stage": FieldSpec(STRING, allowed_values=TASK_STATES),
            "risk_level": FieldSpec(STRING, allowed_values=RISK_LEVELS),
            "trigger": FieldSpec(STRING, allowed_values=HUMAN_DECISION_TRIGGERS),
            "question": FieldSpec(STRING),
            "recommended_option": FieldSpec(STRING),
            "recommendation_rationale": FieldSpec(STRING),
            "options": FieldSpec(LIST, item_fields=HUMAN_DECISION_OPTION_FIELDS),
            "default_without_response": FieldSpec(STRING, allowed_values=("PAUSE",)),
            "evidence_paths": STRING_LIST,
            "created_at_utc": FieldSpec(STRING),
            "status": FieldSpec(STRING, allowed_values=("PENDING", "RESOLVED", "CANCELLED")),
        },
    ),
    ("human_decision_resolution", 1): _contract(
        "human_decision_resolution",
        {
            "schema_version": FieldSpec(int),
            "decision_id": FieldSpec(STRING),
            "project_id": FieldSpec(STRING),
            "task_id": FieldSpec(STRING),
            "selected_option": FieldSpec(STRING),
            "resolved_by": FieldSpec(STRING),
            "resolved_at_utc": FieldSpec(STRING),
            "rationale": FieldSpec(STRING),
            "evidence_paths": STRING_LIST,
            "resume_state": FieldSpec(STRING, allowed_values=TASK_STATES),
            "status": FieldSpec(STRING, allowed_values=("RESOLVED",)),
        },
    ),
    ("agent_task_contract", 1): _contract(
        "agent_task_contract",
        {
            "schema_version": FieldSpec(int),
            "packet_id": FieldSpec(STRING),
            "role": FieldSpec(STRING, allowed_values=ROLES),
            "project_id": FieldSpec(STRING),
            "task_id": FieldSpec(STRING),
            "objective": FieldSpec(STRING),
            "binding_constraints": STRING_LIST,
            "non_goals": STRING_LIST,
            "relevant_paths": STRING_LIST,
            "interfaces_consumed": STRING_LIST,
            "interfaces_produced": STRING_LIST,
            "acceptance_criteria": STRING_LIST,
            "required_skills": STRING_LIST,
            "required_evidence": STRING_LIST,
            "prohibited_actions": STRING_LIST,
            "return_schema": FieldSpec(STRING),
        },
    ),
    ("agent_result", 1): _contract(
        "agent_result",
        {
            "schema_version": FieldSpec(int),
            "packet_id": FieldSpec(STRING),
            "role": FieldSpec(STRING, allowed_values=ROLES),
            "status": FieldSpec(
                STRING,
                allowed_values=(
                    "DONE",
                    "DONE_WITH_CONCERNS",
                    "NEEDS_CONTEXT",
                    "BLOCKED",
                    "FAILED",
                ),
            ),
            "summary": FieldSpec(STRING),
            "changed_files": STRING_LIST,
            "created_files": STRING_LIST,
            "commands_run": STRING_LIST,
            "evidence_paths": STRING_LIST,
            "assumptions": STRING_LIST,
            "concerns": STRING_LIST,
            "blocker": FieldSpec((STRING, NONE)),
            "recommended_next_state": FieldSpec(STRING, allowed_values=TASK_STATES),
        },
    ),
    ("review_finding", 1): _contract(
        "review_finding",
        {
            "schema_version": FieldSpec(int),
            "finding_id": FieldSpec(STRING),
            "review_id": FieldSpec(STRING),
            "severity": FieldSpec(STRING, allowed_values=("P0", "P1", "P2", "P3")),
            "category": FieldSpec(STRING),
            "summary": FieldSpec(STRING),
            "evidence_paths": STRING_LIST,
            "impact": FieldSpec(STRING),
            "recommendation": FieldSpec(STRING),
            "disposition": FieldSpec(
                STRING,
                allowed_values=(
                    "UNTRIAGED",
                    "ACCEPTED",
                    "PARTIAL",
                    "DEFERRED",
                    "ALREADY_FIXED",
                    "NOT_REPRODUCIBLE",
                    "REJECTED",
                    "DUPLICATE",
                    "STALE",
                ),
            ),
            "status": FieldSpec(STRING, allowed_values=("OPEN", "IN_PROGRESS", "VERIFIED", "CLOSED")),
            "rationale": FieldSpec((STRING, NONE)),
            "verification_required": STRING_LIST,
        },
    ),
    ("verification_record", 1): _contract(
        "verification_record",
        {
            "schema_version": FieldSpec(int),
            "verification_id": FieldSpec(STRING),
            "project_id": FieldSpec(STRING),
            "task_id": FieldSpec(STRING),
            "baseline_hash": FieldSpec(STRING),
            "checks": FieldSpec(LIST, item_fields=VERIFICATION_CHECK_FIELDS),
            "requirements_checked": STRING_LIST,
            "failed_requirements": STRING_LIST,
            "verified_at_utc": FieldSpec(STRING),
            "verifier_role": FieldSpec(STRING, allowed_values=("VERIFIER",)),
            "recommendation": FieldSpec(STRING, allowed_values=("VERIFIED", "FIX_REQUIRED", "BLOCKED")),
        },
    ),
    ("audit_event", 1): _contract(
        "audit_event",
        {
            "schema_version": FieldSpec(int),
            "event_id": FieldSpec(STRING),
            "project_id": FieldSpec(STRING),
            "task_id": FieldSpec((STRING, NONE)),
            "event_type": FieldSpec(STRING),
            "actor": FieldSpec(STRING),
            "created_at_utc": FieldSpec(STRING),
            "evidence_paths": STRING_LIST,
            "details": FieldSpec(DICT),
        },
    ),
    ("release_candidate_manifest", 1): _contract(
        "release_candidate_manifest",
        {
            "schema_version": FieldSpec(int),
            "rc_id": FieldSpec(STRING),
            "project_id": FieldSpec(STRING),
            "version": FieldSpec(STRING),
            "created_at_utc": FieldSpec(STRING),
            "source_artifact": FieldSpec(DICT, fields=SOURCE_ARTIFACT_FIELDS),
            "build_artifacts": FieldSpec(LIST, item_fields=SOURCE_ARTIFACT_FIELDS),
            "verification_records": FieldSpec(LIST, item_type=STRING),
            "review_closures": FieldSpec(LIST, item_type=STRING),
            "known_limitations": STRING_LIST,
            "residual_risks": STRING_LIST,
            "rollback_plan_path": FieldSpec(STRING),
            "human_release_authorization": FieldSpec((STRING, NONE)),
            "status": FieldSpec(STRING, allowed_values=("RC_READY", "BLOCKED", "CLOSED")),
        },
    ),
    ("coding_execution_record", 2): ContractSpec(
        name="coding_execution_record",
        version=2,
        fields=CODING_EXECUTION_FIELDS,
    ),
}

_CURRENT_VERSIONS: dict[str, int] = {}
for contract_name, contract_version in _CONTRACTS:
    _CURRENT_VERSIONS[contract_name] = max(
        contract_version,
        _CURRENT_VERSIONS.get(contract_name, 0),
    )


def get_contract(contract_name: str, version: int | None = None) -> ContractSpec:
    if contract_name not in _CURRENT_VERSIONS:
        raise UnknownContractError(f"unknown contract: {contract_name}")
    resolved_version = _CURRENT_VERSIONS[contract_name] if version is None else version
    try:
        return _CONTRACTS[(contract_name, resolved_version)]
    except KeyError as exc:
        raise UnsupportedContractVersionError(
            f"unsupported version for {contract_name}: {resolved_version}"
        ) from exc


def contract_names() -> tuple[str, ...]:
    return tuple(sorted(_CURRENT_VERSIONS))


def supported_versions(contract_name: str) -> tuple[int, ...]:
    if contract_name not in _CURRENT_VERSIONS:
        raise UnknownContractError(f"unknown contract: {contract_name}")
    return tuple(sorted(version for name, version in _CONTRACTS if name == contract_name))


def validate_contract(
    contract_name: str,
    data: Mapping[str, object],
    *,
    mode: str = "runtime",
) -> None:
    if mode not in ("runtime", "template"):
        raise ValueError(f"unknown validation mode: {mode}")
    if not isinstance(data, Mapping):
        spec = get_contract(contract_name)
        raise ContractValidationError(contract_name, [ValidationIssue("$", "expected mapping")])

    raw_version = data.get("schema_version")
    if type(raw_version) is int:
        spec = get_contract(contract_name, raw_version)
    else:
        spec = get_contract(contract_name)
    issues: list[ValidationIssue] = []
    _validate_mapping(spec, data, issues, mode)
    if issues:
        raise ContractValidationError(contract_name, issues)


def _validate_mapping(
    spec: ContractSpec,
    data: Mapping[str, object],
    issues: list[ValidationIssue],
    mode: str,
) -> None:
    version = data.get("schema_version")
    if type(version) is not int:
        issues.append(
            ValidationIssue(
                "schema_version",
                f"expected int, got {type(version).__name__}",
            )
        )
    elif version != spec.version:
        issues.append(
            ValidationIssue(
                "schema_version",
                f"expected {spec.version}, got {version!r}",
            )
        )

    for field_name in data:
        if field_name not in spec.fields:
            issues.append(ValidationIssue(field_name, "unexpected field"))

    for field_name, field in spec.fields.items():
        if field_name not in data:
            if field.required:
                issues.append(ValidationIssue(field_name, "missing required field"))
            continue

        value = data[field_name]
        if not _matches_expected_type(value, field.expected_type):
            issues.append(
                ValidationIssue(
                    field_name,
                    f"expected {_type_name(field.expected_type)}, got {type(value).__name__}",
                )
            )
            continue

        _validate_runtime_semantics(field_name, value, issues, mode)

        if not field.allow_empty and value == "":
            issues.append(ValidationIssue(field_name, "must not be empty"))

        if (
            field.allowed_values is not None
            and value not in field.allowed_values
            and not _is_allowed_template_placeholder(value, mode)
        ):
            issues.append(
                ValidationIssue(
                    field_name,
                    f"expected one of {field.allowed_values!r}, got {value!r}",
                )
            )

        if field.fields is not None and isinstance(value, Mapping):
            _validate_fields(field_name, value, field.fields, issues, mode)

        if field.item_fields is not None and isinstance(value, list):
            for index, item in enumerate(value):
                item_path = f"{field_name}[{index}]"
                if not isinstance(item, Mapping):
                    issues.append(ValidationIssue(item_path, "expected mapping"))
                    continue
                _validate_fields(item_path, item, field.item_fields, issues, mode)

        if field.item_type is not None and isinstance(value, list):
            for index, item in enumerate(value):
                item_path = f"{field_name}[{index}]"
                if not _matches_expected_type(item, field.item_type):
                    issues.append(
                        ValidationIssue(
                            item_path,
                            f"expected {_type_name(field.item_type)}, got {type(item).__name__}",
                        )
                    )
                    continue
                _validate_runtime_semantics(item_path, item, issues, mode)

        if field.map_value_type is not None and isinstance(value, Mapping):
            for key, item in value.items():
                item_path = f"{field_name}.{key}"
                if not _matches_expected_type(item, field.map_value_type):
                    issues.append(
                        ValidationIssue(
                            item_path,
                            f"expected {_type_name(field.map_value_type)}, got {type(item).__name__}",
                        )
                    )
                    continue
                _validate_runtime_semantics(item_path, item, issues, mode)

    if spec.name == "human_decision_request":
        _validate_human_decision_request(data, issues, mode)
    if spec.name == "task_state":
        _validate_task_state(data, issues, mode)
    if spec.name == "verification_record":
        _validate_verification_record(data, issues, mode)
    if spec.name == "agent_result":
        _validate_agent_result(data, issues)
    if spec.name == "review_finding":
        _validate_review_finding(data, issues)
    if spec.name == "release_candidate_manifest":
        _validate_release_candidate_manifest(data, issues, mode)
    if spec.name == "policy_evaluation_result":
        _validate_policy_evaluation_result(data, issues)
    if spec.name == "coding_execution_record":
        _validate_coding_execution_record(data, issues)


def _validate_coding_execution_record(
    data: Mapping[str, object],
    issues: list[ValidationIssue],
) -> None:
    _validate_no_casefold_key_collisions(data, "$", issues)

    for field_name in ("execution_id", "gate_id", "project_id", "task_id"):
        value = data.get(field_name)
        if isinstance(value, str) and not _is_coding_safe_id(value):
            issues.append(ValidationIssue(field_name, "expected uppercase SafeId"))

    created_at = data.get("created_at_utc")
    if isinstance(created_at, str) and not _is_coding_utc(created_at):
        issues.append(ValidationIssue("created_at_utc", "expected UTC timestamp with millisecond precision"))

    packet = data.get("packet")
    baseline = data.get("baseline")
    slot = data.get("slot")
    attempt = data.get("attempt")
    executor = data.get("executor")
    capabilities = data.get("capabilities")
    prelaunch = data.get("prelaunch")
    process = data.get("process")
    events = data.get("events")
    agent_result = data.get("agent_result")
    candidate = data.get("candidate")
    clone_before = data.get("clone_before")
    clone_after = data.get("clone_after")

    def require_git_oid(mapping: object, field_name: str, path: str) -> None:
        if isinstance(mapping, Mapping):
            value = mapping.get(field_name)
            if isinstance(value, str) and not re.fullmatch(r"[0-9a-f]{40}", value):
                issues.append(ValidationIssue(path, "expected 40-character lowercase Git object ID"))

    def require_size(mapping: object, field_name: str, path: str, *, nullable: bool = False) -> None:
        if not isinstance(mapping, Mapping):
            return
        value = mapping.get(field_name)
        if nullable and value is None:
            return
        if type(value) is int and not 0 <= value <= 2**63 - 1:
            issues.append(ValidationIssue(path, "expected Size in 0..2^63-1"))

    def require_count(mapping: object, field_name: str, path: str, *, nullable: bool = False) -> None:
        if not isinstance(mapping, Mapping):
            return
        value = mapping.get(field_name)
        if nullable and value is None:
            return
        if type(value) is int and not 0 <= value <= 2**31 - 1:
            issues.append(ValidationIssue(path, "expected Count in 0..2^31-1"))

    def require_argv(mapping: object, field_name: str, path: str, *, allow_empty: bool = False) -> None:
        if not isinstance(mapping, Mapping):
            return
        value = mapping.get(field_name)
        if not isinstance(value, list):
            return
        if not allow_empty and not value:
            issues.append(ValidationIssue(path, "expected nonempty direct argument vector"))
        if any(not isinstance(item, str) or not item or "\x00" in item for item in value):
            issues.append(ValidationIssue(path, "argv entries must be nonempty strings without NUL"))

    if isinstance(packet, Mapping):
        packet_path = packet.get("path")
        if isinstance(packet_path, str) and not _is_safe_relative_path(packet_path):
            issues.append(ValidationIssue("packet.path", "expected canonical relative path"))
        require_size(packet, "size_bytes", "packet.size_bytes")

    if isinstance(baseline, Mapping):
        repository_path = baseline.get("repository_path")
        if isinstance(repository_path, str) and not _is_windows_absolute_path(repository_path):
            issues.append(ValidationIssue("baseline.repository_path", "expected normalized absolute Windows path"))
        require_git_oid(baseline, "commit", "baseline.commit")
        require_git_oid(baseline, "tree", "baseline.tree")

    if isinstance(executor, Mapping):
        executor_path = executor.get("path")
        if isinstance(executor_path, str) and not _is_windows_absolute_path(executor_path):
            issues.append(ValidationIssue("executor.path", "expected normalized absolute Windows path"))
        require_size(executor, "size_bytes", "executor.size_bytes", nullable=True)
        require_argv(executor, "argv", "executor.argv")

    for clone_name, clone in (("clone_before", clone_before), ("clone_after", clone_after)):
        require_git_oid(clone, "commit", f"{clone_name}.commit")
        require_git_oid(clone, "tree", f"{clone_name}.tree")
    if isinstance(clone_before, Mapping):
        clone_path = clone_before.get("path")
        if isinstance(clone_path, str) and not _is_windows_absolute_path(clone_path):
            issues.append(ValidationIssue("clone_before.path", "expected normalized absolute Windows path"))
        require_count(clone_before, "remote_count", "clone_before.remote_count")

    if isinstance(attempt, Mapping):
        require_count(attempt, "remaining_before", "attempt.remaining_before")
        require_count(attempt, "remaining_after", "attempt.remaining_after")
        require_count(attempt, "process_start_request_count", "attempt.process_start_request_count")
    if isinstance(process, Mapping):
        require_count(process, "pid", "process.pid", nullable=True)
        require_count(process, "descendant_count", "process.descendant_count")
    if isinstance(events, Mapping):
        require_size(events, "size_bytes", "events.size_bytes")
        for field_name in ("parsed_count", "unknown_count", "prohibited_count"):
            require_count(events, field_name, f"events.{field_name}")
    if isinstance(agent_result, Mapping):
        require_size(agent_result, "size_bytes", "agent_result.size_bytes")

    if isinstance(capabilities, Mapping):
        operation_rows = capabilities.get("operation_rows")
        if isinstance(operation_rows, list):
            for index, row in enumerate(operation_rows):
                if not isinstance(row, Mapping):
                    continue
                require_count(row, "sequence", f"capabilities.operation_rows[{index}].sequence")
                process_class = row.get("class") in {"LOCAL_CHECK_PROCESS", "GIT_READ_ONLY_INSPECTION"}
                require_argv(
                    row,
                    "argv",
                    f"capabilities.operation_rows[{index}].argv",
                    allow_empty=not process_class,
                )
                for field_name in ("executable", "cwd"):
                    value = row.get(field_name)
                    if value is not None and isinstance(value, str) and not _is_windows_absolute_path(value):
                        issues.append(
                            ValidationIssue(
                                f"capabilities.operation_rows[{index}].{field_name}",
                                "expected normalized absolute Windows path",
                            )
                        )

    if isinstance(packet, Mapping):
        packet_id = packet.get("packet_id")
        if isinstance(packet_id, str) and not _is_coding_safe_id(packet_id):
            issues.append(ValidationIssue("packet.packet_id", "expected uppercase SafeId"))

    if isinstance(baseline, Mapping):
        before_hash = baseline.get("before_state_sha256")
        after_hash = baseline.get("after_state_sha256")
        expected_unchanged = isinstance(before_hash, str) and before_hash == after_hash
        if baseline.get("unchanged") is not expected_unchanged:
            issues.append(
                ValidationIssue(
                    "baseline.unchanged",
                    "must equal before-state and after-state byte equality",
                )
            )

    if isinstance(capabilities, Mapping):
        if capabilities.get("accepted_operation_classes") != list(CODING_OPERATION_CLASSES):
            issues.append(
                ValidationIssue(
                    "capabilities.accepted_operation_classes",
                    "must equal the exact five-class ASCII-ordered universe",
                )
            )
        if capabilities.get("disabled_surfaces") != list(CODING_DISABLED_SURFACES):
            issues.append(
                ValidationIssue(
                    "capabilities.disabled_surfaces",
                    "must equal the exact disabled-surface universe",
                )
            )
        operation_rows = capabilities.get("operation_rows")
        _validate_sorted_unique_relpaths(
            capabilities.get("authorized_write_paths"),
            "capabilities.authorized_write_paths",
            issues,
        )
        expected_complete = all(
            (
                isinstance(capabilities.get("effective_config_sha256"), str),
                isinstance(capabilities.get("network_policy_sha256"), str),
                capabilities.get("automatic_resume_enabled") is False,
                capabilities.get("hooks_enabled") is False,
                capabilities.get("memories_enabled") is False,
                capabilities.get("accepted_operation_classes") == list(CODING_OPERATION_CLASSES),
                capabilities.get("disabled_surfaces") == list(CODING_DISABLED_SURFACES),
            )
        )
        if capabilities.get("observations_complete") is not expected_complete:
            issues.append(
                ValidationIssue(
                    "capabilities.observations_complete",
                    "must equal the completeness of the recorded capability observations",
                )
            )
        if isinstance(operation_rows, list):
            patch_occurrences: list[str] = []
            for index, row in enumerate(operation_rows):
                if isinstance(row, Mapping) and row.get("sequence") != index:
                    issues.append(
                        ValidationIssue(
                            f"capabilities.operation_rows[{index}].sequence",
                            "must be contiguous from zero",
                        )
                    )
                if isinstance(row, Mapping):
                    _validate_sorted_unique_relpaths(
                        row.get("path_set"),
                        f"capabilities.operation_rows[{index}].path_set",
                        issues,
                    )
                    source = row.get("source")
                    event_id = row.get("event_id")
                    operation_class = row.get("class")
                    process_class = operation_class in {"LOCAL_CHECK_PROCESS", "GIT_READ_ONLY_INSPECTION"}
                    if source in {"CONTROLLER_EVENT", "PROCESS_OBSERVATION"} and event_id is None:
                        issues.append(
                            ValidationIssue(
                                f"capabilities.operation_rows[{index}].event_id",
                                "event and process observations require an event identity",
                            )
                        )
                    if source in {"FILESYSTEM_DIFF", "GIT_DIFF"} and event_id is not None:
                        issues.append(
                            ValidationIssue(
                                f"capabilities.operation_rows[{index}].event_id",
                                "derived diff rows cannot assert an event identity",
                            )
                        )
                    if process_class:
                        if not (
                            isinstance(row.get("executable"), str)
                            and isinstance(row.get("argv"), list)
                            and len(row.get("argv", [])) > 0
                            and isinstance(row.get("cwd"), str)
                        ):
                            issues.append(
                                ValidationIssue(
                                    f"capabilities.operation_rows[{index}]",
                                    "process classes require executable, argv, and cwd",
                                )
                            )
                    elif any((row.get("executable") is not None, row.get("argv") != [], row.get("cwd") is not None)):
                        issues.append(
                            ValidationIssue(
                                f"capabilities.operation_rows[{index}]",
                                "nonprocess classes require null process identity and empty argv",
                            )
                        )
                    if operation_class == "APPROVED_FILE_PATCH" and isinstance(row.get("path_set"), list):
                        patch_occurrences.extend(path for path in row["path_set"] if isinstance(path, str))
            if len(patch_occurrences) != len(set(patch_occurrences)):
                issues.append(
                    ValidationIssue(
                        "capabilities.operation_rows",
                        "approved patch paths must have exact one-row coverage",
                    )
                )

    if isinstance(executor, Mapping):
        expected_complete = all(
            (
                isinstance(executor.get("size_bytes"), int),
                isinstance(executor.get("sha256"), str),
                executor.get("authenticode_status") == "VALID",
                isinstance(executor.get("signer"), str),
                isinstance(executor.get("cli_version"), str),
            )
        )
        if executor.get("identity_complete") is not expected_complete:
            issues.append(
                ValidationIssue(
                    "executor.identity_complete",
                    "must equal completeness of the observed artifact identity",
                )
            )

    if isinstance(prelaunch, Mapping):
        checked_at = prelaunch.get("checked_at_utc")
        if isinstance(checked_at, str) and not _is_coding_utc(checked_at):
            issues.append(
                ValidationIssue(
                    "prelaunch.checked_at_utc",
                    "expected UTC timestamp with millisecond precision",
                )
            )
        gate_rows = prelaunch.get("gate_rows")
        expected_gate_ids = ["P0", "P1", "P2", "P3", "P4", "P5", "P6"]
        if not isinstance(gate_rows, list) or [
            row.get("gate_id") if isinstance(row, Mapping) else None for row in gate_rows
        ] != expected_gate_ids:
            issues.append(
                ValidationIssue(
                    "prelaunch.gate_rows",
                    "must contain exactly P0 through P6 in order",
                )
            )
        elif prelaunch.get("state") == "PASS":
            if any(
                row.get("status") != "PASS" or row.get("blocker_ids") != []
                for row in gate_rows
                if isinstance(row, Mapping)
            ) or prelaunch.get("blocker_ids") != []:
                issues.append(
                    ValidationIssue(
                        "prelaunch.state",
                        "PASS requires seven passing rows and no blockers",
                    )
                )

    if isinstance(attempt, Mapping):
        number = attempt.get("number")
        kind = attempt.get("kind")
        remaining_before = attempt.get("remaining_before")
        remaining_after = attempt.get("remaining_after")
        reserved_at = attempt.get("reserved_at_utc")
        parent_id = attempt.get("parent_candidate_id")
        start_count = attempt.get("process_start_request_count")
        if kind == "PRELAUNCH":
            if number is not None or reserved_at is not None or parent_id is not None:
                issues.append(ValidationIssue("attempt.kind", "PRELAUNCH must not reserve an attempt"))
            if remaining_after != remaining_before:
                issues.append(ValidationIssue("attempt.remaining_after", "PRELAUNCH must not consume budget"))
            if start_count != 0:
                issues.append(ValidationIssue("attempt.process_start_request_count", "PRELAUNCH cannot request a process start"))
        elif number in (1, 2):
            if remaining_after != remaining_before - 1:
                issues.append(
                    ValidationIssue(
                        "attempt.remaining_after",
                        "a reserved attempt must decrement the budget exactly once",
                    )
                )
            if not isinstance(reserved_at, str) or not _is_coding_utc(reserved_at):
                issues.append(
                    ValidationIssue(
                        "attempt.reserved_at_utc",
                        "a reserved attempt requires a millisecond UTC timestamp",
                    )
                )
            if kind == "ORDINARY" and parent_id is not None:
                issues.append(ValidationIssue("attempt.parent_candidate_id", "ORDINARY attempts have no parent"))
            if kind == "REMEDIATION" and (number != 2 or not isinstance(parent_id, str)):
                issues.append(
                    ValidationIssue(
                        "attempt.kind",
                        "REMEDIATION requires Attempt 2 and a parent candidate",
                    )
                )
            if start_count != 1:
                issues.append(
                    ValidationIssue(
                        "attempt.process_start_request_count",
                        "a reserved attempt requires exactly one process-start request",
                    )
                )
        else:
            issues.append(
                ValidationIssue(
                    "attempt.number",
                    "attempt number is null exactly for PRELAUNCH and otherwise one or two",
                )
            )
        if isinstance(start_count, int) and not 0 <= start_count <= 1:
            issues.append(ValidationIssue("attempt.process_start_request_count", "must be zero or one"))

    if isinstance(process, Mapping):
        if process.get("start_requested") is False:
            null_fields = (
                "pid",
                "started_at_utc",
                "ended_at_utc",
                "exit_code",
                "error",
                "stdout_sha256",
                "stderr_sha256",
            )
            for field_name in null_fields:
                if process.get(field_name) is not None:
                    issues.append(
                        ValidationIssue(
                            f"process.{field_name}",
                            "must be null when no process start was requested",
                        )
                    )
        elif isinstance(process.get("pid"), int):
            for field_name in ("started_at_utc", "ended_at_utc", "stdout_sha256", "stderr_sha256"):
                if process.get(field_name) is None:
                    issues.append(
                        ValidationIssue(
                            f"process.{field_name}",
                            "must be present for a created process",
                        )
                    )
            for field_name in ("started_at_utc", "ended_at_utc"):
                value = process.get(field_name)
                if isinstance(value, str) and not _is_coding_utc(value):
                    issues.append(
                        ValidationIssue(
                            f"process.{field_name}",
                            "expected UTC timestamp with millisecond precision",
                        )
                    )
        elif process.get("start_requested") is True:
            if process.get("error") in (None, ""):
                issues.append(
                    ValidationIssue(
                        "process.error",
                        "process creation failure requires a nonempty error",
                    )
                )
            for field_name in ("started_at_utc", "ended_at_utc", "exit_code", "stdout_sha256", "stderr_sha256"):
                if process.get(field_name) is not None:
                    issues.append(
                        ValidationIssue(
                            f"process.{field_name}",
                            "must be null when process creation fails",
                        )
                    )

    if isinstance(clone_before, Mapping) and isinstance(clone_after, Mapping):
        for field_name in ("commit", "tree", "git_control_sha256"):
            if clone_after.get(field_name) != clone_before.get(field_name):
                issues.append(
                    ValidationIssue(
                        f"clone_after.{field_name}",
                        f"must equal clone_before.{field_name}",
                    )
                )

    patch_paths: list[str] = []
    if isinstance(capabilities, Mapping):
        operation_rows = capabilities.get("operation_rows")
        if isinstance(operation_rows, list):
            for row in operation_rows:
                if isinstance(row, Mapping) and row.get("class") == "APPROVED_FILE_PATCH":
                    paths = row.get("path_set")
                    if isinstance(paths, list):
                        patch_paths.extend(path for path in paths if isinstance(path, str))
    patch_paths = sorted(set(patch_paths))
    if isinstance(clone_after, Mapping):
        changed_paths = clone_after.get("changed_paths")
        _validate_sorted_unique_relpaths(changed_paths, "clone_after.changed_paths", issues)
        if changed_paths != patch_paths:
            issues.append(
                ValidationIssue(
                    "clone_after.changed_paths",
                    "must exactly equal paths covered by approved patch rows",
                )
            )

    if isinstance(candidate, Mapping) and isinstance(slot, Mapping):
        candidate_id = candidate.get("candidate_id")
        if candidate.get("status") == "FROZEN_REVIEW" and slot.get("active_candidate_after") != candidate_id:
            issues.append(
                ValidationIssue(
                    "slot.active_candidate_after",
                    "must equal the frozen candidate identity",
                )
            )
        if candidate.get("status") == "FROZEN_REVIEW":
            version = candidate.get("version")
            parent = candidate.get("parent_candidate_id")
            if version == 1 and not all(
                (
                    parent is None,
                    slot.get("state_before") == "EMPTY",
                    slot.get("state_after") == "FROZEN_REVIEW_V1",
                    slot.get("historical_candidate_ids") == [],
                )
            ):
                issues.append(ValidationIssue("candidate.version", "Candidate v1 must derive from the EMPTY slot"))
            if version == 2 and not all(
                (
                    isinstance(parent, str),
                    isinstance(attempt, Mapping),
                    attempt.get("number") == 2,
                    attempt.get("kind") == "REMEDIATION",
                    attempt.get("parent_candidate_id") == parent,
                    slot.get("state_before") == "EMPTY_FOR_REMEDIATION",
                    slot.get("state_after") == "FROZEN_REVIEW_V2",
                    slot.get("historical_candidate_ids") == [parent],
                )
            ):
                issues.append(
                    ValidationIssue(
                        "candidate.version",
                        "Candidate v2 requires the sole authorized remediation transition",
                    )
                )

    if isinstance(prelaunch, Mapping) and prelaunch.get("state") == "HOLD":
        if prelaunch.get("model_request_started") is not False:
            issues.append(
                ValidationIssue(
                    "prelaunch.model_request_started",
                    "must be false when prelaunch state is HOLD",
                )
            )
        if prelaunch.get("process_start_requested") is not False:
            issues.append(
                ValidationIssue(
                    "prelaunch.process_start_requested",
                    "must be false when prelaunch state is HOLD",
                )
            )
        if isinstance(process, Mapping) and process.get("start_requested") is not False:
            issues.append(
                ValidationIssue(
                    "process.start_requested",
                    "must be false when prelaunch state is HOLD",
                )
            )

    if (
        isinstance(candidate, Mapping)
        and candidate.get("status") == "FROZEN_REVIEW"
        and isinstance(clone_after, Mapping)
        and candidate.get("diff_sha256") != clone_after.get("diff_sha256")
    ):
        issues.append(
            ValidationIssue(
                "candidate.diff_sha256",
                "must equal clone_after.diff_sha256",
            )
        )

    promotion_ready = _coding_promotion_ready(
        packet=packet,
        baseline=baseline,
        slot=slot,
        attempt=attempt,
        executor=executor,
        capabilities=capabilities,
        clone_before=clone_before,
        prelaunch=prelaunch,
        process=process,
        events=events,
        agent_result=agent_result,
        clone_after=clone_after,
        candidate=candidate,
    )
    if data.get("outcome") == "CANDIDATE_READY" and not promotion_ready:
        issues.append(
            ValidationIssue(
                "outcome",
                "CANDIDATE_READY requires all promotion predicates",
            )
        )
    expected_outcome = _coding_expected_outcome(
        prelaunch=prelaunch,
        attempt=attempt,
        process=process,
        agent_result=agent_result,
        promotion_ready=promotion_ready,
    )
    if expected_outcome is not None and data.get("outcome") != expected_outcome:
        issues.append(
            ValidationIssue(
                "outcome",
                f"must equal the derived terminal outcome {expected_outcome}",
            )
        )
    if isinstance(candidate, Mapping):
        if candidate.get("promotion_predicates_passed") is not promotion_ready:
            issues.append(
                ValidationIssue(
                    "candidate.promotion_predicates_passed",
                    "must equal the derived promotion predicate",
                )
            )
        if not promotion_ready and any(
            (
                candidate.get("candidate_id") is not None,
                candidate.get("version") is not None,
                candidate.get("status") != "NONE",
                candidate.get("parent_candidate_id") is not None,
                candidate.get("diff_sha256") is not None,
                candidate.get("file_set_sha256") is not None,
                candidate.get("checks_sha256") is not None,
            )
        ):
            issues.append(
                ValidationIssue(
                    "candidate",
                    "non-promotable outcomes require the exact NONE candidate form",
                )
            )


def _validate_no_casefold_key_collisions(
    value: object,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if isinstance(value, Mapping):
        seen: dict[str, str] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                issues.append(ValidationIssue(path, "object keys must be strings"))
                continue
            folded = key.casefold()
            previous = seen.get(folded)
            if previous is not None and previous != key:
                issues.append(
                    ValidationIssue(
                        f"{path}.{key}",
                        f"case-fold-colliding key with {previous!r}",
                    )
                )
            else:
                seen[folded] = key
            _validate_no_casefold_key_collisions(child, f"{path}.{key}", issues)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_no_casefold_key_collisions(child, f"{path}[{index}]", issues)


def _is_coding_safe_id(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,127}", value))


def _is_coding_utc(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError:
        return False
    return True


def _validate_sorted_unique_relpaths(
    value: object,
    path: str,
    issues: list[ValidationIssue],
) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return
    if value != sorted(set(value)):
        issues.append(ValidationIssue(path, "must be ASCII-ordered and unique"))
    folded = [item.casefold() for item in value]
    if len(folded) != len(set(folded)):
        issues.append(ValidationIssue(path, "must not contain case-fold-colliding paths"))
    for item in value:
        if "\x00" in item or not _is_safe_relative_path(item):
            issues.append(ValidationIssue(path, f"unsafe relative path: {item!r}"))


def _coding_promotion_ready(
    *,
    packet: object,
    baseline: object,
    slot: object,
    attempt: object,
    executor: object,
    capabilities: object,
    clone_before: object,
    prelaunch: object,
    process: object,
    events: object,
    agent_result: object,
    clone_after: object,
    candidate: object,
) -> bool:
    mappings = (
        packet,
        baseline,
        slot,
        attempt,
        executor,
        capabilities,
        clone_before,
        prelaunch,
        process,
        events,
        agent_result,
        clone_after,
        candidate,
    )
    if not all(isinstance(item, Mapping) for item in mappings):
        return False
    assert isinstance(packet, Mapping)
    assert isinstance(baseline, Mapping)
    assert isinstance(slot, Mapping)
    assert isinstance(attempt, Mapping)
    assert isinstance(executor, Mapping)
    assert isinstance(capabilities, Mapping)
    assert isinstance(clone_before, Mapping)
    assert isinstance(prelaunch, Mapping)
    assert isinstance(process, Mapping)
    assert isinstance(events, Mapping)
    assert isinstance(agent_result, Mapping)
    assert isinstance(clone_after, Mapping)
    assert isinstance(candidate, Mapping)
    rows = capabilities.get("operation_rows")
    rows_pass = isinstance(rows, list) and all(
        isinstance(row, Mapping) and row.get("status") == "PASS" and row.get("sequence") == index
        for index, row in enumerate(rows)
    )
    changed_paths = clone_after.get("changed_paths")
    patch_paths = sorted(
        {
            path
            for row in rows if isinstance(rows, list) and isinstance(row, Mapping) and row.get("class") == "APPROVED_FILE_PATCH"
            for path in (row.get("path_set") if isinstance(row.get("path_set"), list) else [])
            if isinstance(path, str)
        }
    ) if isinstance(rows, list) else []
    return all(
        (
            packet.get("validation_status") == "PASS",
            baseline.get("unchanged") is True,
            prelaunch.get("state") == "PASS",
            attempt.get("number") in (1, 2),
            attempt.get("process_start_request_count") == 1,
            executor.get("identity_complete") is True,
            capabilities.get("observations_complete") is True,
            rows_pass,
            changed_paths == patch_paths,
            clone_before.get("commit") == clone_after.get("commit"),
            clone_before.get("tree") == clone_after.get("tree"),
            clone_before.get("git_control_sha256") == clone_after.get("git_control_sha256"),
            process.get("start_requested") is True,
            process.get("exit_code") == 0,
            process.get("error") is None,
            process.get("timed_out") is False,
            process.get("cancelled") is False,
            process.get("all_descendants_terminated") is True,
            events.get("unknown_count") == 0,
            events.get("prohibited_count") == 0,
            events.get("output_schema_valid") is True,
            agent_result.get("contract_valid") is True,
            agent_result.get("claims_match") is True,
            agent_result.get("claimed_status") == "DONE",
            candidate.get("status") == "FROZEN_REVIEW",
            candidate.get("candidate_id") == slot.get("active_candidate_after"),
            candidate.get("diff_sha256") == clone_after.get("diff_sha256"),
        )
    )


def _coding_expected_outcome(
    *,
    prelaunch: object,
    attempt: object,
    process: object,
    agent_result: object,
    promotion_ready: bool,
) -> str | None:
    if not all(isinstance(value, Mapping) for value in (prelaunch, attempt, process, agent_result)):
        return None
    assert isinstance(prelaunch, Mapping)
    assert isinstance(attempt, Mapping)
    assert isinstance(process, Mapping)
    assert isinstance(agent_result, Mapping)
    if prelaunch.get("state") == "HOLD":
        return "PRELAUNCH_HOLD"
    if attempt.get("number") not in (1, 2):
        return None
    process_failed = any(
        (
            process.get("start_requested") is not True,
            process.get("pid") is None,
            process.get("error") is not None,
            process.get("timed_out") is True,
            process.get("cancelled") is True,
            process.get("all_descendants_terminated") is not True,
            isinstance(process.get("exit_code"), int) and process.get("exit_code") != 0,
        )
    )
    if process_failed or agent_result.get("claimed_status") == "FAILED":
        return "ATTEMPT_FAILED"
    if promotion_ready:
        return "CANDIDATE_READY"
    return "ATTEMPT_HOLD"


def _validate_human_decision_request(
    data: Mapping[str, object],
    issues: list[ValidationIssue],
    mode: str,
) -> None:
    options = data.get("options")
    recommended_option = data.get("recommended_option")
    if not isinstance(options, list):
        return

    if len(options) < 1:
        issues.append(ValidationIssue("options", "expected at least 1 item"))
        return

    if not isinstance(recommended_option, str):
        return

    option_id_values = [
        item.get("id")
        for item in options
        if isinstance(item, Mapping) and isinstance(item.get("id"), str)
    ]
    option_ids = set(option_id_values)
    if len(option_id_values) != len(option_ids):
        issues.append(ValidationIssue("options", "duplicate option id"))
    if recommended_option not in option_ids:
        issues.append(
            ValidationIssue(
                "recommended_option",
                f"expected one of option ids {tuple(sorted(option_ids))!r}, got {recommended_option!r}",
            )
        )


def _validate_task_state(
    data: Mapping[str, object],
    issues: list[ValidationIssue],
    mode: str,
) -> None:
    if mode != "runtime":
        return
    state = data.get("state")
    pending_decision_id = data.get("pending_decision_id")
    if state == "WAITING_HUMAN" and not (
        isinstance(pending_decision_id, str) and pending_decision_id.strip()
    ):
        issues.append(
            ValidationIssue(
                "pending_decision_id",
                "required when state is WAITING_HUMAN",
            )
        )
    if state != "WAITING_HUMAN" and pending_decision_id not in (None, ""):
        issues.append(
            ValidationIssue(
                "pending_decision_id",
                "must be empty unless state is WAITING_HUMAN",
            )
        )


def _validate_verification_record(
    data: Mapping[str, object],
    issues: list[ValidationIssue],
    mode: str,
) -> None:
    if mode != "runtime" or data.get("recommendation") != "VERIFIED":
        return
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        issues.append(ValidationIssue("checks", "required when recommendation is VERIFIED"))
    requirements_checked = data.get("requirements_checked")
    if not isinstance(requirements_checked, list) or not requirements_checked:
        issues.append(
            ValidationIssue(
                "requirements_checked",
                "required when recommendation is VERIFIED",
            )
        )
    if isinstance(checks, list):
        for index, check in enumerate(checks):
            if isinstance(check, Mapping) and check.get("exit_code") != 0:
                issues.append(
                    ValidationIssue(
                        f"checks[{index}].exit_code",
                        "must be 0 when recommendation is VERIFIED",
                    )
                )
    if data.get("failed_requirements"):
        issues.append(
            ValidationIssue(
                "failed_requirements",
                "must be empty when recommendation is VERIFIED",
            )
        )


def _validate_agent_result(
    data: Mapping[str, object],
    issues: list[ValidationIssue],
) -> None:
    status = data.get("status")
    blocker = data.get("blocker")
    if status == "DONE" and blocker not in (None, ""):
        issues.append(ValidationIssue("blocker", "must be empty when status is DONE"))
    if status == "BLOCKED" and blocker in (None, ""):
        issues.append(ValidationIssue("blocker", "required when status is BLOCKED"))


def _validate_review_finding(
    data: Mapping[str, object],
    issues: list[ValidationIssue],
) -> None:
    if data.get("status") == "CLOSED" and data.get("disposition") == "UNTRIAGED":
        issues.append(
            ValidationIssue(
                "disposition",
                "must not be UNTRIAGED when status is CLOSED",
            )
        )
    if data.get("status") in ("VERIFIED", "CLOSED"):
        if not data.get("evidence_paths"):
            issues.append(
                ValidationIssue(
                    "evidence_paths",
                    "required when status is VERIFIED or CLOSED",
                )
            )
        if not data.get("verification_required"):
            issues.append(
                ValidationIssue(
                    "verification_required",
                    "required when status is VERIFIED or CLOSED",
                )
            )


def _validate_release_candidate_manifest(
    data: Mapping[str, object],
    issues: list[ValidationIssue],
    mode: str,
) -> None:
    if mode != "runtime" or data.get("status") != "RC_READY":
        return
    for field_name in ("verification_records", "review_closures"):
        value = data.get(field_name)
        if not isinstance(value, list) or not value:
            issues.append(ValidationIssue(field_name, "required when status is RC_READY"))


def _validate_policy_evaluation_result(
    data: Mapping[str, object],
    issues: list[ValidationIssue],
) -> None:
    result = data.get("result")
    if not isinstance(result, Mapping):
        return

    policy_bundle_digest = data.get("policy_bundle_digest")
    decision_emitted = result.get("decision_emitted")
    fail_closed = result.get("fail_closed")
    error_code = result.get("error_code")
    issue_items = result.get("issues")
    executable_fields = (
        "required_human_triggers",
        "required_skills",
        "model_roles",
        "mandatory_gates",
        "legal_transitions",
        "authorized_transitions",
        "provenance",
    )

    if policy_bundle_digest is None and fail_closed is not True:
        issues.append(
            ValidationIssue(
                "policy_bundle_digest",
                "required unless evaluation failed before a usable policy bundle existed",
            )
        )

    if fail_closed is True:
        if result.get("risk_level") != "R3":
            issues.append(
                ValidationIssue(
                    "result.risk_level",
                    "must be R3 when fail_closed is true",
                )
            )
        if result.get("human_gate") is not True:
            issues.append(
                ValidationIssue(
                    "result.human_gate",
                    "must be true when fail_closed is true",
                )
            )
        if decision_emitted is not False:
            issues.append(
                ValidationIssue(
                    "result.decision_emitted",
                    "must be false when fail_closed is true",
                )
            )
        for field_name in executable_fields:
            value = result.get(field_name)
            if value not in ({}, []):
                issues.append(
                    ValidationIssue(
                        f"result.{field_name}",
                        "must be empty when fail_closed is true",
                    )
                )
        if not isinstance(error_code, str) or not error_code.strip():
            issues.append(
                ValidationIssue(
                    "result.error_code",
                    "required when fail_closed is true",
                )
            )
        elif error_code not in POLICY_ERROR_CODES:
            issues.append(
                ValidationIssue(
                    "result.error_code",
                    "must be a registered policy error code",
                )
            )
        if not isinstance(issue_items, list) or not issue_items:
            issues.append(
                ValidationIssue(
                    "result.issues",
                    "required when fail_closed is true",
                )
            )
        elif isinstance(error_code, str):
            seen_issue_paths: set[str] = set()
            for index, issue in enumerate(issue_items):
                if not isinstance(issue, Mapping):
                    continue
                if issue.get("code") != error_code:
                    issues.append(
                        ValidationIssue(
                            f"result.issues[{index}].code",
                            "must match result.error_code",
                        )
                    )
                issue_path = issue.get("path")
                if not isinstance(issue_path, str) or not issue_path.strip():
                    issues.append(
                        ValidationIssue(
                            f"result.issues[{index}].path",
                            "must be a non-empty path",
                        )
                    )
                elif issue_path in seen_issue_paths:
                    issues.append(
                        ValidationIssue(
                            f"result.issues[{index}].path",
                            "must not duplicate another issue path",
                        )
                    )
                else:
                    seen_issue_paths.add(issue_path)
    else:
        if decision_emitted is not True:
            issues.append(
                ValidationIssue(
                    "result.decision_emitted",
                    "must be true when fail_closed is false",
                )
            )
        if error_code is not None:
            issues.append(
                ValidationIssue(
                    "result.error_code",
                    "must be null when fail_closed is false",
                )
            )
        if issue_items not in ([], None):
            issues.append(
                ValidationIssue(
                    "result.issues",
                    "must be empty when fail_closed is false",
                )
            )

        if result.get("risk_level") == "R3" and result.get("human_gate") is not True:
            issues.append(
                ValidationIssue(
                    "result.human_gate",
                    "must be true when risk_level is R3",
                )
            )
        required_human_triggers = result.get("required_human_triggers")
        if isinstance(required_human_triggers, list) and required_human_triggers and result.get("human_gate") is not True:
            issues.append(
                ValidationIssue(
                    "result.human_gate",
                    "must be true when required_human_triggers is non-empty",
                )
            )

    _validate_policy_result_list_vocab(
        result,
        "required_human_triggers",
        HUMAN_DECISION_TRIGGERS,
        issues,
    )
    _validate_policy_result_list_vocab(result, "required_skills", POLICY_SKILL_IDS, issues)
    _validate_policy_result_list_vocab(result, "mandatory_gates", POLICY_GATE_IDS, issues)
    _validate_policy_result_list_vocab(result, "legal_transitions", TASK_STATES, issues, enforce_order=False)
    _validate_policy_result_list_vocab(result, "authorized_transitions", TASK_STATES, issues, enforce_order=False)
    _validate_policy_result_provenance(result, issues)

    model_roles = result.get("model_roles")
    if isinstance(model_roles, Mapping):
        for key, role_id in model_roles.items():
            if key not in POLICY_MODEL_ACTORS:
                issues.append(
                    ValidationIssue(
                        f"result.model_roles.{key}",
                        "must reference a declared model actor",
                    )
                )
            if isinstance(role_id, str) and role_id not in POLICY_MODEL_ROLE_IDS:
                issues.append(
                    ValidationIssue(
                        f"result.model_roles.{key}",
                        "must reference a declared model role",
                    )
                )

    legal = result.get("legal_transitions")
    authorized = result.get("authorized_transitions")
    if isinstance(legal, list) and isinstance(authorized, list):
        legal_set = set(item for item in legal if isinstance(item, str))
        for index, target in enumerate(authorized):
            if target not in legal_set:
                issues.append(
                    ValidationIssue(
                        f"result.authorized_transitions[{index}]",
                        "must also be present in legal_transitions",
                    )
                )

    if result.get("human_gate") is True and isinstance(authorized, list):
        for index, target in enumerate(authorized):
            if target not in {"WAITING_HUMAN", "ABANDONED"}:
                issues.append(
                    ValidationIssue(
                        f"result.authorized_transitions[{index}]",
                        "human-gated results may authorize only WAITING_HUMAN or ABANDONED",
                    )
                )


def _validate_policy_result_list_vocab(
    result: Mapping[str, object],
    field_name: str,
    vocabulary: tuple[str, ...],
    issues: list[ValidationIssue],
    *,
    enforce_order: bool = True,
) -> None:
    values = result.get(field_name)
    if not isinstance(values, list):
        return
    seen: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, str):
            continue
        if value in seen:
            issues.append(
                ValidationIssue(
                    f"result.{field_name}[{index}]",
                    "must not duplicate another set-like output value",
                )
            )
        else:
            seen.add(value)
        if value not in vocabulary:
            issues.append(
                ValidationIssue(
                    f"result.{field_name}[{index}]",
                    "must reference a declared policy vocabulary item",
                )
            )
    canonical = [item for item in vocabulary if item in seen]
    if enforce_order and values != canonical:
        issues.append(
            ValidationIssue(
                f"result.{field_name}",
                "must use canonical declaration order",
            )
        )


def _validate_policy_result_provenance(
    result: Mapping[str, object],
    issues: list[ValidationIssue],
) -> None:
    values = result.get("provenance")
    if not isinstance(values, list):
        return
    seen: set[str] = set()
    for index, value in enumerate(values):
        if not isinstance(value, str):
            continue
        if value in seen:
            issues.append(
                ValidationIssue(
                    f"result.provenance[{index}]",
                    "must not duplicate another provenance path",
                )
            )
        else:
            seen.add(value)
        if not PROVENANCE_RE.match(value):
            issues.append(
                ValidationIssue(
                    f"result.provenance[{index}]",
                    "must be a source path followed by a policy field path",
                )
            )
        if index > 0:
            previous_group = _provenance_order_group(values[index - 1])
            current_group = _provenance_order_group(value)
            if current_group < previous_group:
                issues.append(
                    ValidationIssue(
                        "result.provenance",
                        "must use canonical provenance order",
                    )
                )
                break


def _provenance_order_group(value: object) -> int:
    if not isinstance(value, str):
        return 99
    prefixes = (
        (("config/risk_policy.yaml:", "project_profiles/"), 0),
        (("config/human_decision_policy.yaml:",), 1),
        (("config/skill_routing.yaml:",), 2),
        (("config/model_routing.yaml:",), 3),
        (("config/workflow_policy.yaml:",), 4),
    )
    for group_prefixes, group in prefixes:
        if value.startswith(group_prefixes):
            return group
    return 99


def _validate_fields(
    path: str,
    data: Mapping[str, object],
    fields: dict[str, FieldSpec],
    issues: list[ValidationIssue],
    mode: str,
) -> None:
    for field_name in data:
        if field_name not in fields:
            issues.append(ValidationIssue(f"{path}.{field_name}", "unexpected field"))

    for field_name, field in fields.items():
        child_path = f"{path}.{field_name}"
        if field_name not in data:
            if field.required:
                issues.append(ValidationIssue(child_path, "missing required field"))
            continue

        value = data[field_name]
        if not _matches_expected_type(value, field.expected_type):
            issues.append(
                ValidationIssue(
                    child_path,
                    f"expected {_type_name(field.expected_type)}, got {type(value).__name__}",
                )
            )
            continue

        if not field.allow_empty and value == "":
            issues.append(ValidationIssue(child_path, "must not be empty"))

        _validate_runtime_semantics(child_path, value, issues, mode)

        if (
            field.allowed_values is not None
            and value not in field.allowed_values
            and not _is_allowed_template_placeholder(value, mode)
        ):
            issues.append(
                ValidationIssue(
                    child_path,
                    f"expected one of {field.allowed_values!r}, got {value!r}",
                )
            )

        if field.fields is not None and isinstance(value, Mapping):
            _validate_fields(child_path, value, field.fields, issues, mode)

        if field.item_fields is not None and isinstance(value, list):
            for index, item in enumerate(value):
                item_path = f"{child_path}[{index}]"
                if not isinstance(item, Mapping):
                    issues.append(ValidationIssue(item_path, "expected mapping"))
                    continue
                _validate_fields(item_path, item, field.item_fields, issues, mode)

        if field.item_type is not None and isinstance(value, list):
            for index, item in enumerate(value):
                item_path = f"{child_path}[{index}]"
                if not _matches_expected_type(item, field.item_type):
                    issues.append(
                        ValidationIssue(
                            item_path,
                            f"expected {_type_name(field.item_type)}, got {type(item).__name__}",
                        )
                    )
                    continue
                _validate_runtime_semantics(item_path, item, issues, mode)

        if field.map_value_type is not None and isinstance(value, Mapping):
            for key, item in value.items():
                item_path = f"{child_path}.{key}"
                if not _matches_expected_type(item, field.map_value_type):
                    issues.append(
                        ValidationIssue(
                            item_path,
                            f"expected {_type_name(field.map_value_type)}, got {type(item).__name__}",
                        )
                    )
                    continue
                _validate_runtime_semantics(item_path, item, issues, mode)


def _type_name(expected_type: type | tuple[type, ...]) -> str:
    if isinstance(expected_type, tuple):
        return " or ".join(item.__name__ for item in expected_type)
    return expected_type.__name__


def _matches_expected_type(
    value: object,
    expected_type: type | tuple[type, ...],
) -> bool:
    if expected_type is int:
        return type(value) is int
    if isinstance(expected_type, tuple):
        return any(_matches_expected_type(value, item) for item in expected_type)
    return isinstance(value, expected_type)


def _is_allowed_template_placeholder(value: object, mode: str) -> bool:
    return mode == "template" and isinstance(value, str) and value in TEMPLATE_PLACEHOLDERS


def _validate_runtime_semantics(
    path: str,
    value: object,
    issues: list[ValidationIssue],
    mode: str,
) -> None:
    if mode != "runtime" or not isinstance(value, str):
        return

    if value in TEMPLATE_PLACEHOLDERS:
        issues.append(ValidationIssue(path, "template placeholder is not valid at runtime"))

    field_name = _semantic_field_name(path)
    if _is_required_text_field(field_name) and not value.strip():
        issues.append(ValidationIssue(path, "must not be empty"))

    if field_name.endswith("_at_utc") and not _is_rfc3339_utc(value):
        issues.append(ValidationIssue(path, "expected RFC 3339 UTC timestamp"))

    if (
        field_name in ("sha256", "baseline_hash")
        or field_name.endswith("_sha256")
        or field_name.endswith("_digest")
    ) and not _is_sha256(value):
        issues.append(ValidationIssue(path, "expected lowercase SHA-256 hex digest"))

    if _is_absolute_path_semantic_path(path):
        if not _is_windows_absolute_path(value):
            issues.append(ValidationIssue(path, "expected normalized absolute Windows path"))
    elif _is_path_semantic_path(path):
        if not _is_safe_relative_path(value):
            issues.append(ValidationIssue(path, "expected safe relative path"))


def _semantic_field_name(path: str) -> str:
    field_name = path.rsplit(".", 1)[-1]
    return re.sub(r"\[\d+\]$", "", field_name)


def _semantic_path_parts(path: str) -> list[str]:
    return [_semantic_field_name(part) for part in path.split(".")]


def _is_path_semantic_path(path: str) -> bool:
    parts = _semantic_path_parts(path)
    field_name = parts[-1]
    return field_name in PATH_FIELDS or any(part in PATH_COLLECTION_FIELDS for part in parts)


def _is_absolute_path_semantic_path(path: str) -> bool:
    parts = _semantic_path_parts(path)
    return len(parts) >= 2 and parts[-2:] in (
        ["executor", "path"],
        ["clone_before", "path"],
    )


def _is_required_text_field(field_name: str) -> bool:
    return field_name in {
        "actor",
        "assessment_id",
        "baseline_hash",
        "business_context",
        "category",
        "command",
        "created_at_utc",
        "decision_id",
        "description",
        "event_id",
        "event_type",
        "finding_id",
        "impact",
        "name",
        "objective",
        "output_path",
        "packet_id",
        "path",
        "profile_id",
        "project_id",
        "project_name",
        "project_type",
        "question",
        "rationale",
        "rc_id",
        "recommendation",
        "recommendation_rationale",
        "requested_by",
        "requested_outcome",
        "resolved_at_utc",
        "resolved_by",
        "result_summary",
        "review_id",
        "rollback_plan_path",
        "selected_option",
        "sha256",
        "summary",
        "task_id",
        "title",
        "updated_at_utc",
        "verification_id",
        "verified_at_utc",
        "version",
    }


def _is_rfc3339_utc(value: str) -> bool:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{3})?Z", value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ" if "." in value else "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return True


def _is_sha256(value: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", value))


def _is_safe_relative_path(value: str) -> bool:
    if not value or "\\" in value:
        return False
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return False
    parts = value.split("/")
    return all(part not in ("", ".", "..") for part in parts)


def _is_windows_absolute_path(value: str) -> bool:
    if not re.fullmatch(r"[A-Za-z]:\\[^\x00]*", value):
        return False
    parts = value[3:].split("\\") if len(value) > 3 else []
    return all(part not in ("", ".", "..") for part in parts)
