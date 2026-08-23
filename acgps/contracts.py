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

    if _is_path_semantic_path(path):
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
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
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
