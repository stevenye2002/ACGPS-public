from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import re
import shutil
import tempfile
from pathlib import Path
from collections.abc import Mapping
from typing import Any

import yaml

from acgps.contracts import (
    HUMAN_DECISION_TRIGGERS,
    POLICY_GATE_IDS,
    POLICY_MODEL_ACTORS,
    POLICY_MODEL_ROLE_IDS,
    POLICY_SKILL_IDS,
    TASK_STATES,
    ContractValidationError,
    validate_contract,
)
from acgps.policy_errors import POLICY_ERROR_CODES
from acgps.yaml_loader import (
    DuplicateYamlKeyError,
    StrictYamlError,
    UniqueKeyLoader,
    contains_yaml_anchor_or_alias,
    load_yaml_strict,
)


ROOT = Path(__file__).resolve().parents[1]
RISK_ORDER = {"R0": 0, "R1": 1, "R2": 2, "R3": 3}
POLICY_FILES = {
    "workflow": "config/workflow_policy.yaml",
    "risk": "config/risk_policy.yaml",
    "human": "config/human_decision_policy.yaml",
    "skills": "config/skill_routing.yaml",
    "models": "config/model_routing.yaml",
    "routing_features": "config/policy_routing_features.yaml",
}
POLICY_IDS = {
    "config/workflow_policy.yaml": "global-workflow-v1",
    "config/risk_policy.yaml": "global-risk-v1",
    "config/human_decision_policy.yaml": "human-decision-v1",
    "config/skill_routing.yaml": "skill-routing-v1",
    "config/model_routing.yaml": "model-routing-v1",
    "config/policy_routing_features.yaml": "policy-routing-features-v1",
}
POLICY_ROUTING_FEATURE_IDS = {
    "approved_plan",
    "before_integration",
    "behavior_change",
    "bug_fix",
    "critical_browser_flow",
    "critical_user_flow",
    "design_system_change",
    "failing_test",
    "formal_feature",
    "formal_milestone",
    "high_fidelity_experience",
    "integration",
    "isolated_review_work",
    "multi_file",
    "multi_step",
    "new_ui",
    "parallel_tasks",
    "public_contract_change",
    "rc_candidate",
    "regression",
    "responsive_layout",
    "risk_R2",
    "risk_R3",
    "two_or_more_independent_tasks",
    "unclear_runtime_behavior",
    "unexpected_failure",
    "web_ui_change",
}
INPUT_FIELDS = {
    "current_state",
    "risk_triggers",
    "human_triggers",
    "task_attributes",
    "project_profile_id",
}
WRAPPER_FIELDS = {"schema_version", "input"}
PUBLIC_INPUT_WRAPPER_FIELDS = {"schema_version", "evaluation_id", "project_id", "task_id", "input", "created_at_utc"}
PROFILE_REQUIRED_FIELDS = {
    "schema_version": int,
    "profile_id": str,
    "project_name": str,
    "project_type": str,
    "required_files": dict,
    "critical_surfaces": list,
    "risk_overrides": dict,
    "pilot_restrictions": list,
    "commands": dict,
}
PROFILE_ALLOWED_FIELDS = set(PROFILE_REQUIRED_FIELDS)
FIXTURE_REFERENCE_PHASES = (
    "schema",
    "skill_routing",
    "risk_conflict",
    "duplicate_profiles",
    "profile_validation",
)


@dataclass(frozen=True)
class PolicyEvaluationError(ValueError):
    code: str
    path: str
    message: str
    mark: object | None = None

    def __post_init__(self) -> None:
        if self.code not in POLICY_ERROR_CODES:
            raise ValueError(f"unregistered policy error code: {self.code}")
        ValueError.__init__(self, f"{self.code} {self.path}: {self.message}")


@dataclass(frozen=True)
class PolicyBundle:
    root: Path
    workflow: dict[str, Any]
    risk: dict[str, Any]
    human: dict[str, Any]
    skills: dict[str, Any]
    models: dict[str, Any]
    routing_features: dict[str, Any]
    project_profiles: dict[str, dict[str, Any]]
    policy_bundle_digest: str


def load_policy_bundle(root: str | Path = ROOT) -> PolicyBundle:
    resolved = Path(root)
    policies = {
        key: _load_yaml_mapping(resolved, logical_path, required=True)
        for key, logical_path in POLICY_FILES.items()
    }
    _validate_policy_schemas(policies)
    profiles = _load_project_profiles(resolved, policies["risk"])
    _validate_cross_file_references(policies)
    return PolicyBundle(
        root=resolved,
        project_profiles=profiles,
        policy_bundle_digest=_policy_bundle_digest(policies, profiles),
        **policies,
    )


def validate_project_registration(
    project_root: str | Path,
    profile: Mapping[str, Any],
) -> dict[str, Path]:
    """Resolve a validated profile's required files under one managed root."""
    try:
        validate_contract("project_profile", profile)
    except ContractValidationError as exc:
        issue = exc.issues[0]
        raise PolicyEvaluationError(
            "POLICY_PROFILE_REQUIRED_FILE_INVALID",
            issue.path,
            issue.message,
        ) from exc

    root = Path(project_root)
    if root.is_symlink():
        raise PolicyEvaluationError(
            "POLICY_PROFILE_REQUIRED_FILE_INVALID",
            "project_root",
            "managed project root must not be a symlink",
        )
    try:
        resolved_root = root.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise PolicyEvaluationError(
            "POLICY_PROFILE_REQUIRED_FILE_INVALID",
            "project_root",
            "managed project root is missing",
        ) from exc
    if not resolved_root.is_dir():
        raise PolicyEvaluationError(
            "POLICY_PROFILE_REQUIRED_FILE_INVALID",
            "project_root",
            "managed project root must be a directory",
        )

    resolved_files: dict[str, Path] = {}
    required_files = profile.get("required_files", {})
    assert isinstance(required_files, Mapping)
    for key, value in required_files.items():
        field_path = f"required_files.{key}"
        if not isinstance(key, str) or not isinstance(value, str) or not _is_safe_relative_path(value):
            raise PolicyEvaluationError(
                "POLICY_PROFILE_REQUIRED_FILE_INVALID",
                field_path,
                "profile required_files entry must be a safe relative path",
            )
        candidate = root.joinpath(*value.split("/"))
        cursor = root
        for part in value.split("/"):
            cursor = cursor / part
            if cursor.is_symlink():
                raise PolicyEvaluationError(
                    "POLICY_PROFILE_REQUIRED_FILE_INVALID",
                    field_path,
                    "managed required-file path must not contain symlinks",
                )
        try:
            resolved = candidate.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise PolicyEvaluationError(
                "POLICY_PROFILE_REQUIRED_FILE_INVALID",
                field_path,
                "managed required file is missing",
            ) from exc
        if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
            raise PolicyEvaluationError(
                "POLICY_PROFILE_REQUIRED_FILE_INVALID",
                field_path,
                "managed required file must be a regular file contained by project_root",
            )
        resolved_files[key] = resolved
    return resolved_files


def evaluate_policy(
    record: object,
    *,
    root: str | Path = ROOT,
    bundle: PolicyBundle | None = None,
) -> dict[str, Any]:
    public_context = _public_input_context(record)
    policy_bundle_digest: str | None = None
    try:
        active_bundle = bundle if bundle is not None else load_policy_bundle(root)
        policy_bundle_digest = active_bundle.policy_bundle_digest
        normalized = _prevalidate_input(record, active_bundle)
        result = _evaluate_normalized(normalized, active_bundle)
        _validate_policy_result_contract(result, active_bundle)
    except PolicyEvaluationError as exc:
        result = fail_closed_result(exc.code, exc.path, exc.message)
    except Exception as exc:
        result = fail_closed_result("POLICY_MALFORMED", "policy", f"policy evaluation failed closed: {type(exc).__name__}")
    if public_context is not None:
        return _wrap_public_result(public_context, result, policy_bundle_digest)
    return result


def evaluate_policy_fixture(
    fixture_id: str,
    record: object,
    *,
    root: str | Path = ROOT,
) -> dict[str, Any]:
    try:
        with _fixture_overlay_root(Path(root), fixture_id) as overlay_root:
            return evaluate_policy(record, root=overlay_root)
    except PolicyEvaluationError as exc:
        return fail_closed_result(exc.code, exc.path, exc.message)
    except Exception as exc:
        return fail_closed_result("POLICY_MALFORMED", "fixture_id", str(exc))


def run_policy_eval_suite(root: str | Path = ROOT) -> dict[str, Any]:
    resolved = Path(root)
    cases_doc = _load_yaml_mapping(resolved, "config/policy_eval_cases.yaml", required=True)
    failures: list[dict[str, str]] = []
    case_results: list[dict[str, Any]] = []
    bundle: PolicyBundle | None = None
    for case in cases_doc.get("cases", []):
        case_id = str(case.get("case_id", "<missing>"))
        fixture_id = case.get("fixture_id")
        expected = case.get("expected")
        if fixture_id is None and bundle is None:
            try:
                bundle = load_policy_bundle(resolved)
            except PolicyEvaluationError as exc:
                result = fail_closed_result(exc.code, exc.path, exc.message)
            else:
                result = evaluate_policy(case.get("input"), bundle=bundle)
        elif fixture_id is None:
            result = evaluate_policy(case.get("input"), bundle=bundle)
        else:
            result = evaluate_policy_fixture(str(fixture_id), case.get("input"), root=resolved)

        comparable_expected = {
            key: value
            for key, value in dict(expected).items()
            if key != "replay_deterministic"
        } if isinstance(expected, dict) else {}
        passed = result == comparable_expected
        case_results.append({"case_id": case_id, "passed": passed, "result": result})
        if not passed:
            failures.append(
                {
                    "case_id": case_id,
                    "message": "policy result did not match expected eval catalog output",
                }
            )

    return {
        "schema_version": 1,
        "case_set_id": cases_doc.get("case_set_id"),
        "case_count": len(cases_doc.get("cases", [])),
        "passed": not failures,
        "failures": failures,
        "results_digest": _stable_digest(case_results),
    }


def fail_closed_result(error_code: str, path: str, message: str) -> dict[str, Any]:
    if error_code not in POLICY_ERROR_CODES:
        error_code = "POLICY_MALFORMED"
    return {
        "decision_emitted": False,
        "risk_level": "R3",
        "human_gate": True,
        "required_human_triggers": [],
        "required_skills": [],
        "model_roles": {},
        "mandatory_gates": [],
        "legal_transitions": [],
        "authorized_transitions": [],
        "provenance": [],
        "fail_closed": True,
        "error_code": error_code,
        "issues": [{"code": error_code, "path": path, "message": message}],
    }


def derive_policy_fixture_error(
    fixture_id: str,
    *,
    fixtures_root: Path | None = None,
) -> tuple[str, str, str]:
    fixture_base = (fixtures_root if fixtures_root is not None else ROOT / "tests" / "fixtures" / "policy_eval").resolve()
    fixture_dir = _fixture_child_dir(fixture_base, fixture_id, "fixture_id")
    fixture = _load_fixture_yaml(fixture_dir / "fixture.yaml", "fixture.yaml")
    policy_root_name = fixture.get("policy_root", "policy_root")
    if not isinstance(policy_root_name, str) or not policy_root_name:
        raise ValueError("fixture.yaml policy_root must be a non-empty string when present")
    policy_root = _fixture_child_dir(fixture_dir, policy_root_name, "fixture.policy_root")
    loaded, load_error = _fixture_load_policy_root(policy_root)
    if load_error is not None:
        return load_error
    for phase in FIXTURE_REFERENCE_PHASES:
        result = _run_fixture_phase(phase, loaded, policy_root)
        if result is not None:
            return result
    raise ValueError(f"policy eval fixture produced no fail-closed error: {fixture_id}")


def _load_yaml_mapping(root: Path, logical_path: str, *, required: bool) -> dict[str, Any]:
    path = root / logical_path
    if required and not path.is_file():
        raise PolicyEvaluationError("POLICY_FILE_MISSING", logical_path, "required policy file is missing")
    _assert_safe_file(root, path, logical_path)
    try:
        text = path.read_text(encoding="utf-8")
        data = load_yaml_strict(text, logical_path=logical_path)
    except DuplicateYamlKeyError as exc:
        key = str(exc.key) if exc.key is not None else "<unknown>"
        raise PolicyEvaluationError("POLICY_DUPLICATE_YAML_KEY", f"{logical_path}:{key}", "duplicate YAML key detected", mark=exc.mark) from exc
    except StrictYamlError as exc:
        raise PolicyEvaluationError("POLICY_MALFORMED", logical_path, "policy fixture cannot be parsed") from exc
    except UnicodeDecodeError as exc:
        raise PolicyEvaluationError("POLICY_MALFORMED", logical_path, "policy fixture cannot be parsed") from exc
    if not isinstance(data, dict):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", logical_path, "policy file must be a mapping")
    return data


def _validate_policy_schemas(policies: dict[str, dict[str, Any]]) -> None:
    for key, policy_doc in policies.items():
        logical_path = POLICY_FILES[key]
        if policy_doc.get("schema_version") != 1:
            raise PolicyEvaluationError(
                "POLICY_UNSUPPORTED_VERSION",
                f"{logical_path}:schema_version",
                "unsupported policy schema version",
            )
    if policies["risk"].get("default_level") not in policies["risk"].get("levels", {}):
        raise PolicyEvaluationError("POLICY_UNKNOWN_ID", "config/risk_policy.yaml:default_level", "default risk level is undeclared")
    if policies["risk"].get("unknown_trigger_behavior") != "fail_closed":
        raise PolicyEvaluationError(
            "POLICY_CONFLICT",
            "config/risk_policy.yaml:unknown_trigger_behavior",
            "unknown trigger behavior must be fail_closed",
        )
    _validate_workflow_policy(policies["workflow"])
    _validate_risk_policy(policies["risk"])
    _validate_human_policy(policies["human"])
    _validate_skill_policy(policies["skills"])
    _validate_model_policy(policies["models"])
    _validate_routing_features_policy(policies["routing_features"])


def _validate_workflow_policy(workflow: dict[str, Any]) -> None:
    logical_path = "config/workflow_policy.yaml"
    _require_exact_fields(
        workflow,
        {"schema_version", "policy_id", "task_states", "transitions", "mandatory_rules"},
        logical_path,
    )
    _require_policy_id(workflow, logical_path)
    states = _require_string_list(workflow.get("task_states"), f"{logical_path}:task_states")
    for index, state in enumerate(states):
        if state not in TASK_STATES:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:task_states[{index}]", "unknown workflow state")
    transitions = workflow.get("transitions")
    if not isinstance(transitions, dict):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:transitions", "workflow transitions must be a mapping")
    if set(transitions) != set(states):
        missing = sorted(set(states) - set(transitions))
        extra = sorted(set(transitions) - set(states))
        if missing:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:transitions.{missing[0]}", "workflow state is missing a transition row")
        raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:transitions.{extra[0]}", "unknown transition source state")
    for source, targets in transitions.items():
        if source not in states:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:transitions.{source}", "unknown transition source state")
        target_list = _require_string_list(targets, f"{logical_path}:transitions.{source}")
        for index, target in enumerate(target_list):
            if target not in states:
                raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:transitions.{source}[{index}]", "unknown workflow transition target")
    _require_string_list(workflow.get("mandatory_rules"), f"{logical_path}:mandatory_rules")


def _validate_risk_policy(risk: dict[str, Any]) -> None:
    logical_path = "config/risk_policy.yaml"
    allowed = {
        "schema_version",
        "policy_id",
        "default_level",
        "unknown_trigger_behavior",
        "levels",
        "triggers",
        "highest_applicable_level_wins",
        "project_profile_may_lower_risk",
        "rules",
    }
    _require_exact_fields(risk, allowed, logical_path, allow_missing={"rules"})
    _require_policy_id(risk, logical_path)
    levels = risk.get("levels")
    if not isinstance(levels, dict):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:levels", "risk levels must be a mapping")
    if set(levels) != set(RISK_ORDER):
        missing = sorted(set(RISK_ORDER) - set(levels))
        extra = sorted(set(levels) - set(RISK_ORDER))
        if missing:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:levels.{missing[0]}", "required risk level is undeclared")
        raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:levels.{extra[0]}", "unknown risk level")
    for level, config in levels.items():
        if level not in RISK_ORDER:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:levels.{level}", "unknown risk level")
        if not isinstance(config, dict):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:levels.{level}", "risk level must be a mapping")
        _require_exact_fields(config, {"description", "required_gates"}, f"{logical_path}:levels.{level}")
        if not isinstance(config.get("description"), str) or not config.get("description"):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:levels.{level}.description", "risk level description must be a non-empty string")
        gates = _require_string_list(config.get("required_gates"), f"{logical_path}:levels.{level}.required_gates")
        if not gates:
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:levels.{level}.required_gates", "risk level must declare at least one mandatory gate")
        for gate_index, gate in enumerate(gates):
            if gate not in POLICY_GATE_IDS:
                raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:levels.{level}.required_gates[{gate_index}]", "unknown gate id")
    triggers = risk.get("triggers")
    if not isinstance(triggers, dict):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:triggers", "risk triggers must be a mapping")
    for trigger, level in triggers.items():
        if not isinstance(trigger, str) or not isinstance(level, str):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:triggers", "risk trigger ids and levels must be strings")
        if level not in levels:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:triggers.{trigger}", "unknown risk level")
    if type(risk.get("highest_applicable_level_wins")) is not bool:
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:highest_applicable_level_wins", "must be a boolean")
    if type(risk.get("project_profile_may_lower_risk")) is not bool:
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:project_profile_may_lower_risk", "must be a boolean")
    _validate_risk_rule_conflicts(risk)


def _validate_human_policy(human: dict[str, Any]) -> None:
    logical_path = "config/human_decision_policy.yaml"
    _require_exact_fields(
        human,
        {"schema_version", "policy_id", "default_without_response", "triggers", "do_not_escalate"},
        logical_path,
    )
    _require_policy_id(human, logical_path)
    if human.get("default_without_response") != "PAUSE":
        raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:default_without_response", "unknown default behavior")
    triggers = human.get("triggers")
    if not isinstance(triggers, dict):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:triggers", "human triggers must be a mapping")
    for trigger in triggers:
        if trigger not in HUMAN_DECISION_TRIGGERS:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:triggers.{trigger}", "unknown human trigger")
        config = triggers[trigger]
        if not isinstance(config, dict):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:triggers.{trigger}", "human trigger config must be a mapping")
        _require_exact_fields(config, {"examples"}, f"{logical_path}:triggers.{trigger}")
        _require_string_list(config.get("examples"), f"{logical_path}:triggers.{trigger}.examples")
    _require_string_list(human.get("do_not_escalate"), f"{logical_path}:do_not_escalate")


def _validate_skill_policy(skills: dict[str, Any]) -> None:
    logical_path = "config/skill_routing.yaml"
    _require_exact_fields(
        skills,
        {"schema_version", "policy_id", "primary_discovery", "skills", "exception_requires_record"},
        logical_path,
    )
    _require_policy_id(skills, logical_path)
    primary = _require_mapping(skills.get("primary_discovery"), f"{logical_path}:primary_discovery")
    _require_exact_fields(primary, {"exclusive", "routes"}, f"{logical_path}:primary_discovery")
    if type(primary.get("exclusive")) is not bool:
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:primary_discovery.exclusive", "exclusive must be a boolean")
    routes_value = primary.get("routes")
    if isinstance(routes_value, list):
        _validate_primary_routes(skills, logical_path)
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:primary_discovery.routes", "expected mapping")
    routes = _require_mapping(routes_value, f"{logical_path}:primary_discovery.routes")
    for route, target in routes.items():
        if not isinstance(route, str) or not isinstance(target, str):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:primary_discovery.routes", "routes must map strings to strings")
        if target not in POLICY_SKILL_IDS and target not in {"grill_with_docs", "concise_spec", "superpowers_brainstorming"}:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:primary_discovery.routes.{route}", "unknown primary discovery target")
    skill_rules = _require_mapping(skills.get("skills"), f"{logical_path}:skills")
    for skill_id, rule in skill_rules.items():
        if skill_id not in POLICY_SKILL_IDS and skill_id not in {
            "superpowers_tdd",
            "superpowers_systematic_debugging",
            "superpowers_git_worktrees",
            "superpowers_subagent_driven",
            "browser_qa",
        }:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:skills.{skill_id}", "unknown policy skill id")
        if not isinstance(rule, dict):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:skills.{skill_id}", "skill rule must be a mapping")
        _require_exact_fields(rule, {"always", "when_any", "when_all"}, f"{logical_path}:skills.{skill_id}", allow_missing={"always", "when_any", "when_all"})
        if "always" in rule and type(rule["always"]) is not bool:
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:skills.{skill_id}.always", "always must be a boolean")
        if "when_any" in rule:
            _require_known_feature_list(rule["when_any"], f"{logical_path}:skills.{skill_id}.when_any")
        if "when_all" in rule:
            _require_known_feature_list(rule["when_all"], f"{logical_path}:skills.{skill_id}.when_all")
    if type(skills.get("exception_requires_record")) is not bool:
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:exception_requires_record", "exception_requires_record must be a boolean")


def _validate_model_policy(models: dict[str, Any]) -> None:
    logical_path = "config/model_routing.yaml"
    _require_exact_fields(
        models,
        {"schema_version", "policy_id", "roles", "escalate_when"},
        logical_path,
    )
    _require_policy_id(models, logical_path)
    roles = _require_mapping(models.get("roles"), f"{logical_path}:roles")
    for role_id, config in roles.items():
        if role_id not in POLICY_MODEL_ROLE_IDS and role_id not in {"deep_research", "coder_mechanical", "coder_integration"}:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:roles.{role_id}", "unknown model role")
        if not isinstance(config, dict):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:roles.{role_id}", "model role config must be a mapping")
        _require_exact_fields(config, {"capability", "independent_context", "model_role"}, f"{logical_path}:roles.{role_id}", allow_missing={"independent_context", "model_role"})
        if not isinstance(config.get("capability"), str) or not config.get("capability"):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:roles.{role_id}.capability", "capability must be a non-empty string")
        if "independent_context" in config and type(config["independent_context"]) is not bool:
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:roles.{role_id}.independent_context", "independent_context must be a boolean")
        if "model_role" in config and (not isinstance(config["model_role"], str) or not config["model_role"]):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:roles.{role_id}.model_role", "model_role must be a non-empty string")
    _require_string_list(models.get("escalate_when"), f"{logical_path}:escalate_when")


def _validate_routing_features_policy(routing: dict[str, Any]) -> None:
    logical_path = "config/policy_routing_features.yaml"
    _require_exact_fields(
        routing,
        {"schema_version", "policy_id", "task_attributes", "risk_conditions", "skill_rule_features", "model_role_rules", "canonical_order"},
        logical_path,
    )
    _require_policy_id(routing, logical_path)
    task_attrs = routing.get("task_attributes")
    if not isinstance(task_attrs, dict):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:task_attributes", "task attributes must be a mapping")
    for attr, config in task_attrs.items():
        if not isinstance(attr, str) or not isinstance(config, dict):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:task_attributes.{attr}", "task attribute config must be a mapping")
        _require_exact_fields(config, {"allowed_values", "maps_to_features"}, f"{logical_path}:task_attributes.{attr}")
        allowed_values = _require_string_list(config.get("allowed_values"), f"{logical_path}:task_attributes.{attr}.allowed_values")
        maps_to_features = config.get("maps_to_features", {})
        if not isinstance(maps_to_features, dict):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:task_attributes.{attr}.maps_to_features", "maps_to_features must be a mapping")
        for value, features in maps_to_features.items():
            if value not in allowed_values:
                raise PolicyEvaluationError("POLICY_UNKNOWN_ATTRIBUTE_VALUE", f"{logical_path}:task_attributes.{attr}.maps_to_features.{value}", "unknown task attribute value")
            _require_known_feature_list(features, f"{logical_path}:task_attributes.{attr}.maps_to_features.{value}")
    for level, features in _require_mapping(routing.get("risk_conditions"), f"{logical_path}:risk_conditions").items():
        if level not in RISK_ORDER:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:risk_conditions.{level}", "unknown risk level")
        _require_known_feature_list(features, f"{logical_path}:risk_conditions.{level}")
    for skill_id, rule in _require_mapping(routing.get("skill_rule_features"), f"{logical_path}:skill_rule_features").items():
        if skill_id not in POLICY_SKILL_IDS:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:skill_rule_features.{skill_id}", "unknown policy skill id")
        if not isinstance(rule, dict):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:skill_rule_features.{skill_id}", "skill rule must be a mapping")
        _require_exact_fields(rule, {"always", "when_any"}, f"{logical_path}:skill_rule_features.{skill_id}", allow_missing={"always", "when_any"})
        if "always" in rule and type(rule["always"]) is not bool:
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:skill_rule_features.{skill_id}.always", "always must be a boolean")
        if "when_any" in rule:
            _require_known_feature_list(rule["when_any"], f"{logical_path}:skill_rule_features.{skill_id}.when_any")
    for actor, rule in _require_mapping(routing.get("model_role_rules"), f"{logical_path}:model_role_rules").items():
        if actor not in POLICY_MODEL_ACTORS:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:model_role_rules.{actor}", "unknown model actor")
        if not isinstance(rule, dict):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:model_role_rules.{actor}", "model role rule must be a mapping")
        for selector, role_id in rule.items():
            if selector != "always" and selector not in RISK_ORDER:
                raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:model_role_rules.{actor}.{selector}", "unknown model role selector")
            if role_id not in POLICY_MODEL_ROLE_IDS:
                raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:model_role_rules.{actor}.{selector}", "unknown model role")
    canonical = _require_mapping(routing.get("canonical_order"), f"{logical_path}:canonical_order")
    _require_exact_fields(canonical, {"set_like_inputs", "order_source"}, f"{logical_path}:canonical_order")
    for field_name in _require_string_list(canonical.get("set_like_inputs"), f"{logical_path}:canonical_order.set_like_inputs"):
        if field_name not in {"risk_triggers", "human_triggers"}:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:canonical_order.set_like_inputs", "unknown canonical input field")
    if canonical.get("order_source") != "policy_declaration_order":
        raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:canonical_order.order_source", "unknown canonical order source")


def _validate_risk_rule_conflicts(risk: dict[str, Any]) -> None:
    seen: dict[tuple[object, object], object] = {}
    for index, rule in enumerate(risk.get("rules", [])):
        if not isinstance(rule, dict):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"config/risk_policy.yaml:rules[{index}]", "risk rule must be a mapping")
        unexpected = sorted(set(rule) - {"trigger", "priority", "risk_level"})
        if unexpected:
            raise PolicyEvaluationError(
                "POLICY_UNKNOWN_FIELD",
                f"config/risk_policy.yaml:rules[{index}]:{unexpected[0]}",
                f"unexpected policy field {unexpected[0]}",
            )
        _require_exact_fields(rule, {"trigger", "priority", "risk_level"}, f"config/risk_policy.yaml:rules[{index}]")
        if not isinstance(rule.get("trigger"), str) or not rule.get("trigger"):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"config/risk_policy.yaml:rules[{index}].trigger", "risk rule trigger must be a non-empty string")
        if type(rule.get("priority")) is not int:
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"config/risk_policy.yaml:rules[{index}].priority", "risk rule priority must be an integer")
        if rule.get("risk_level") not in risk.get("levels", {}):
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"config/risk_policy.yaml:rules[{index}].risk_level", "risk rule must reference a declared risk level")
        key = (rule.get("trigger"), rule.get("priority"))
        previous = seen.get(key)
        if previous is not None and previous != rule.get("risk_level"):
            raise PolicyEvaluationError("POLICY_CONFLICT", f"config/risk_policy.yaml:rules[{index}]", "conflicting equal-priority policy rules")
        seen[key] = rule.get("risk_level")


def _require_policy_id(doc: dict[str, Any], logical_path: str) -> None:
    policy_id = doc.get("policy_id")
    if not isinstance(policy_id, str) or not policy_id:
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:policy_id", "policy_id must be a non-empty string")
    if policy_id != POLICY_IDS[logical_path]:
        raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{logical_path}:policy_id", "unknown policy_id")


def _require_known_feature_list(value: object, path: str) -> list[str]:
    features = _require_string_list(value, path)
    for index, feature in enumerate(features):
        if feature not in POLICY_ROUTING_FEATURE_IDS:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"{path}[{index}]", "unknown routing feature")
    return features


def _require_exact_fields(doc: dict[str, Any], allowed: set[str], logical_path: str, *, allow_missing: set[str] | None = None) -> None:
    allow_missing = allow_missing or set()
    missing = sorted((allowed - allow_missing) - set(doc))
    if missing:
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:{missing[0]}", f"{missing[0]} missing required field")
    unexpected = sorted(set(doc) - allowed)
    if unexpected:
        raise PolicyEvaluationError("POLICY_UNKNOWN_FIELD", f"{logical_path}:{unexpected[0]}", f"unexpected policy field {unexpected[0]}")


def _require_string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", path, "expected list of strings")
    duplicate = _duplicate_item(value)
    if duplicate is not None:
        raise PolicyEvaluationError("POLICY_DUPLICATE_SET_MEMBER", f"{path}[{duplicate[0]}]", "duplicate set-like policy value")
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item:
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{path}[{index}]", "expected non-empty string")
    return value


def _require_mapping(value: object, path: str) -> dict[Any, Any]:
    if not isinstance(value, dict):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", path, "expected mapping")
    return value


def _validate_cross_file_references(policies: dict[str, dict[str, Any]]) -> None:
    skills = policies["skills"].get("skills", {})
    models = policies["models"].get("roles", {})
    routing = policies["routing_features"]
    if not isinstance(skills, dict) or not isinstance(models, dict):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", "config/skill_routing.yaml", "skill and model policies must be mappings")
    _validate_primary_routes(policies["skills"], "config/skill_routing.yaml")
    for skill_id in routing.get("skill_rule_features", {}):
        if skill_id not in skills:
            raise PolicyEvaluationError(
                "POLICY_UNKNOWN_ID",
                f"config/policy_routing_features.yaml:skill_rule_features.{skill_id}",
                f"unknown skill rule {skill_id}",
            )
    for actor, rule in routing.get("model_role_rules", {}).items():
        if not isinstance(rule, dict):
            raise PolicyEvaluationError(
                "POLICY_TYPE_ERROR",
                f"config/policy_routing_features.yaml:model_role_rules.{actor}",
                "model role rule must be a mapping",
            )
        for role_id in rule.values():
            if role_id not in models:
                raise PolicyEvaluationError(
                    "POLICY_UNKNOWN_ID",
                    f"config/policy_routing_features.yaml:model_role_rules.{actor}",
                    f"unknown model role {role_id}",
                )


def _validate_primary_routes(skills: dict[str, Any], logical_path: str) -> None:
    routes = skills.get("primary_discovery", {}).get("routes", {})
    if isinstance(routes, dict):
        return
    if not isinstance(routes, list):
        raise PolicyEvaluationError(
            "POLICY_TYPE_ERROR",
            f"{logical_path}:primary_discovery.routes",
            "primary discovery routes must be a mapping or list",
        )
    route_ids = [item.get("route_id") for item in routes if isinstance(item, dict)]
    duplicate = _duplicate_item(route_ids)
    if duplicate is not None:
        raise PolicyEvaluationError(
            "POLICY_DUPLICATE_DISCOVERY_ROUTE",
            f"{logical_path}:primary_discovery.routes[{duplicate[0]}].route_id",
            "duplicate primary discovery route detected",
        )


def _load_project_profiles(root: Path, risk: dict[str, Any]) -> dict[str, dict[str, Any]]:
    profiles_dir = root / "project_profiles"
    if not profiles_dir.exists():
        return {}
    registry: dict[str, dict[str, Any]] = {}
    for profile_path in sorted(profiles_dir.glob("*.yaml"), key=lambda path: path.as_posix()):
        logical_path = profile_path.relative_to(root).as_posix()
        profile = _load_yaml_mapping(root, logical_path, required=True)
        _validate_project_profile(root, logical_path, profile, risk)
        profile_id = profile["profile_id"]
        if profile_id in registry:
            raise PolicyEvaluationError(
                "POLICY_DUPLICATE_PROFILE_ID",
                f"{logical_path}:profile_id",
                "duplicate profile_id detected",
            )
        registry[profile_id] = {"source_path": logical_path, "profile": profile}
    return registry


def _validate_project_profile(root: Path, logical_path: str, profile: dict[str, Any], risk: dict[str, Any]) -> None:
    try:
        validate_contract("project_profile", profile)
    except ContractValidationError as exc:
        issue = exc.issues[0]
        if issue.path.startswith("required_files"):
            raise PolicyEvaluationError(
                "POLICY_PROFILE_REQUIRED_FILE_INVALID",
                f"{logical_path}:{issue.path}",
                "profile required_files entry is unsafe or missing",
            ) from exc
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:{issue.path}", issue.message) from exc
    unexpected = sorted(set(profile) - PROFILE_ALLOWED_FIELDS)
    if unexpected:
        raise PolicyEvaluationError(
            "POLICY_UNKNOWN_FIELD",
            f"{logical_path}:{unexpected[0]}",
            f"unexpected profile field {unexpected[0]}",
        )
    for field, expected_type in PROFILE_REQUIRED_FIELDS.items():
        if field not in profile:
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:{field}", f"{field} missing required field")
        value = profile[field]
        if expected_type is int:
            valid_type = type(value) is int
        else:
            valid_type = isinstance(value, expected_type)
        if not valid_type:
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:{field}", f"{field} has invalid type")
    if profile.get("schema_version") != 1:
        raise PolicyEvaluationError("POLICY_UNSUPPORTED_VERSION", f"{logical_path}:schema_version", "unsupported profile schema version")
    for field in ("critical_surfaces", "pilot_restrictions"):
        for index, value in enumerate(profile.get(field, [])):
            if not isinstance(value, str) or not value:
                raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:{field}[{index}]", f"{field} entries must be non-empty strings")
    for key, level in profile.get("risk_overrides", {}).items():
        if not isinstance(key, str) or not key:
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"{logical_path}:risk_overrides", "risk_overrides keys must be non-empty strings")
        if level not in RISK_ORDER:
            raise PolicyEvaluationError(
                "POLICY_UNKNOWN_ID",
                f"{logical_path}:risk_overrides.{key}",
                "risk override must reference a declared risk level",
            )
        global_level = risk.get("triggers", {}).get(key)
        if (
            risk.get("project_profile_may_lower_risk") is False
            and global_level in RISK_ORDER
            and RISK_ORDER[level] < RISK_ORDER[global_level]
        ):
            raise PolicyEvaluationError(
                "POLICY_PROFILE_DOWNGRADE_FORBIDDEN",
                f"{logical_path}:risk_overrides.{key}",
                "project profile may not lower global risk level",
            )
    for key, value in profile.get("required_files", {}).items():
        if not isinstance(key, str) or not isinstance(value, str) or not _is_safe_relative_path(value):
            raise PolicyEvaluationError(
                "POLICY_PROFILE_REQUIRED_FILE_INVALID",
                f"{logical_path}:required_files.{key}",
                "profile required_files entry is unsafe or missing",
            )


def _prevalidate_input(record: object, bundle: PolicyBundle) -> dict[str, Any]:
    input_data = _normalize_input(record)
    for field_name in input_data:
        if field_name not in INPUT_FIELDS:
            raise PolicyEvaluationError("POLICY_UNKNOWN_FIELD", f"input.{field_name}", f"unknown PolicyEvaluationInput field {field_name}")
    for field_name in INPUT_FIELDS:
        if field_name not in input_data:
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"input.{field_name}", f"{field_name} is required")
    current_state = input_data.get("current_state")
    if not isinstance(current_state, str):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", "input.current_state", "current_state must be a string")
    if current_state not in set(bundle.workflow.get("task_states", [])):
        raise PolicyEvaluationError("POLICY_UNKNOWN_ID", "input.current_state", f"unknown current_state {current_state}")
    for field_name in ("risk_triggers", "human_triggers"):
        values = input_data.get(field_name)
        if not isinstance(values, list):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"input.{field_name}", f"{field_name} must be a list")
        for index, value in enumerate(values):
            if not isinstance(value, str):
                singular = field_name[:-1]
                raise PolicyEvaluationError("POLICY_TYPE_ERROR", f"input.{field_name}[{index}]", f"{singular} must be a string")
        duplicate = _duplicate_item(values)
        if duplicate is not None:
            singular = field_name[:-1]
            raise PolicyEvaluationError(
                "POLICY_DUPLICATE_SET_MEMBER",
                f"input.{field_name}[{duplicate[0]}]",
                f"duplicate {singular} {duplicate[1]}",
            )
    _validate_task_attributes(input_data.get("task_attributes"), bundle.routing_features)
    for index, trigger in enumerate(input_data.get("human_triggers", [])):
        if trigger not in bundle.human.get("triggers", {}):
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"input.human_triggers[{index}]", f"unknown human trigger {trigger}")
    profile_id = input_data.get("project_profile_id")
    if profile_id is not None and not isinstance(profile_id, str):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", "input.project_profile_id", "project_profile_id must be a string or null")
    if isinstance(profile_id, str) and profile_id not in bundle.project_profiles:
        raise PolicyEvaluationError("POLICY_UNKNOWN_ID", "input.project_profile_id", f"unknown project_profile_id {profile_id}")
    return dict(input_data)


def _normalize_input(record: object) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", "input", "PolicyEvaluationInput must be a mapping")
    if _looks_like_public_input(record):
        try:
            validate_contract("policy_evaluation_input", record)
        except ContractValidationError as exc:
            issue = exc.issues[0]
            if issue.message == "unexpected field":
                raise PolicyEvaluationError("POLICY_UNKNOWN_FIELD", issue.path, f"unknown PolicyEvaluationInput field {issue.path}") from exc
            if issue.message.startswith("expected"):
                raise PolicyEvaluationError("POLICY_TYPE_ERROR", issue.path, issue.message) from exc
            raise PolicyEvaluationError("POLICY_MALFORMED", issue.path, issue.message) from exc
        return dict(record["input"])
    if "schema_version" in record or "input" in record:
        for field_name in record:
            if field_name not in WRAPPER_FIELDS:
                raise PolicyEvaluationError("POLICY_UNKNOWN_FIELD", field_name, f"unknown PolicyEvaluationInput wrapper field {field_name}")
        schema_version = record.get("schema_version")
        if type(schema_version) is not int:
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", "schema_version", "schema_version must be an integer")
        if schema_version != 1:
            raise PolicyEvaluationError("POLICY_UNSUPPORTED_VERSION", "schema_version", "unsupported PolicyEvaluationInput schema version")
        input_data = record.get("input")
        if not isinstance(input_data, dict):
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", "input", "input must be a mapping")
        return input_data
    return record


def _public_input_context(record: object) -> dict[str, Any] | None:
    if not isinstance(record, dict) or not _looks_like_public_input(record):
        return None
    timestamp = record.get("created_at_utc")
    return {
        "schema_version": 1,
        "evaluation_id": record.get("evaluation_id") if isinstance(record.get("evaluation_id"), str) else "UNKNOWN",
        "project_id": record.get("project_id") if isinstance(record.get("project_id"), str) else "UNKNOWN",
        "task_id": record.get("task_id") if isinstance(record.get("task_id"), str) else "UNKNOWN",
        "created_at_utc": timestamp if isinstance(timestamp, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", timestamp) else "1970-01-01T00:00:00Z",
    }


def _validate_policy_result_contract(result: dict[str, Any], bundle: PolicyBundle | None = None) -> None:
    envelope = {
        "schema_version": 1,
        "evaluation_id": "INTERNAL",
        "project_id": "ACGPS",
        "task_id": "POLICY_EVALUATION",
        "policy_bundle_digest": None if bundle is None else bundle.policy_bundle_digest,
        "result": result,
        "created_at_utc": "1970-01-01T00:00:00Z",
    }
    try:
        validate_contract("policy_evaluation_result", envelope)
    except ContractValidationError as exc:
        issue = exc.issues[0]
        raise PolicyEvaluationError("POLICY_MALFORMED", issue.path, issue.message) from exc
    if result.get("fail_closed") is True or result.get("decision_emitted") is False or bundle is None:
        return
    risk_level = result.get("risk_level")
    levels = bundle.risk.get("levels", {})
    if risk_level not in levels:
        raise PolicyEvaluationError("POLICY_UNKNOWN_ID", "result.risk_level", "result risk level is undeclared")
    expected_gates = levels[risk_level].get("required_gates")
    if result.get("mandatory_gates") != expected_gates:
        raise PolicyEvaluationError(
            "POLICY_CONFLICT",
            "result.mandatory_gates",
            "mandatory gates must match the selected risk level declaration",
        )


def _looks_like_public_input(record: dict[str, Any]) -> bool:
    return any(field in record for field in PUBLIC_INPUT_WRAPPER_FIELDS - WRAPPER_FIELDS)


def _wrap_public_result(context: dict[str, Any], result: dict[str, Any], policy_bundle_digest: str | None) -> dict[str, Any]:
    wrapped = {
        "schema_version": context["schema_version"],
        "evaluation_id": str(context["evaluation_id"]),
        "project_id": str(context["project_id"]),
        "task_id": str(context["task_id"]),
        "policy_bundle_digest": policy_bundle_digest,
        "result": result,
        "created_at_utc": str(context["created_at_utc"]),
    }
    try:
        validate_contract("policy_evaluation_result", wrapped)
    except ContractValidationError as exc:
        issue = exc.issues[0]
        wrapped["result"] = fail_closed_result("POLICY_MALFORMED", issue.path, issue.message)
    return wrapped


def _evaluate_normalized(input_data: dict[str, Any], bundle: PolicyBundle) -> dict[str, Any]:
    risk_triggers = list(input_data.get("risk_triggers", []))
    profile_source, profile = _profile_record(bundle, input_data.get("project_profile_id"))
    profile_triggers = profile.get("risk_overrides", {}) if profile is not None else {}
    for index, trigger in enumerate(risk_triggers):
        if trigger not in bundle.risk.get("triggers", {}) and trigger not in profile_triggers:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", f"input.risk_triggers[{index}]", f"unknown risk trigger {trigger}")
    risk_triggers = _canonical_order(
        risk_triggers,
        list(bundle.risk.get("triggers", {})) + sorted(set(profile_triggers) - set(bundle.risk.get("triggers", {}))),
    )

    risk_level = bundle.risk.get("default_level", "R0")
    provenance: list[str] = []
    if not risk_triggers:
        provenance.append("config/risk_policy.yaml:default_level")
    for trigger in risk_triggers:
        candidate_level = bundle.risk.get("triggers", {}).get(trigger)
        if candidate_level is not None:
            provenance.append(f"config/risk_policy.yaml:triggers.{trigger}")
        if profile is not None and trigger in profile_triggers:
            profile_level = profile_triggers[trigger]
            profile_path = profile_source or f"project_profiles/{input_data.get('project_profile_id')}.yaml"
            provenance.append(f"{profile_path}:risk_overrides.{trigger}")
            if candidate_level is not None and RISK_ORDER[profile_level] < RISK_ORDER[candidate_level]:
                raise PolicyEvaluationError(
                    "POLICY_PROFILE_DOWNGRADE_FORBIDDEN",
                    f"{profile_path}:risk_overrides.{trigger}",
                    "project profile may not lower global risk level",
                )
            candidate_level = profile_level
        if candidate_level is None:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ID", "input.risk_triggers", f"unknown risk trigger {trigger}")
        if RISK_ORDER[candidate_level] > RISK_ORDER[risk_level]:
            risk_level = candidate_level

    human_triggers = _canonical_order(list(input_data.get("human_triggers", [])), list(bundle.human.get("triggers", {})))
    human_gate = bool(human_triggers) or risk_level == "R3"
    current_state = input_data["current_state"]
    legal_transitions = list(bundle.workflow.get("transitions", {}).get(current_state, []))
    authorized_transitions = [
        state for state in legal_transitions if state in {"WAITING_HUMAN", "ABANDONED"}
    ] if human_gate else legal_transitions

    features = _derive_routing_features(input_data.get("task_attributes", {}), risk_level, bundle.routing_features)
    required_skills = _derive_required_skills(features, bundle.routing_features)
    model_roles = _derive_model_roles(risk_level, bundle.routing_features)

    for trigger in human_triggers:
        provenance.append(f"config/human_decision_policy.yaml:triggers.{trigger}")
    for skill in required_skills:
        provenance.append(f"config/skill_routing.yaml:skills.{skill}")
    for role in model_roles.values():
        provenance.append(f"config/model_routing.yaml:roles.{role}")
    provenance.append(f"config/workflow_policy.yaml:transitions.{current_state}")
    provenance = _canonical_provenance(provenance)

    return {
        "decision_emitted": True,
        "risk_level": risk_level,
        "human_gate": human_gate,
        "required_human_triggers": human_triggers,
        "required_skills": required_skills,
        "model_roles": model_roles,
        "mandatory_gates": list(bundle.risk.get("levels", {}).get(risk_level, {}).get("required_gates", [])),
        "legal_transitions": legal_transitions,
        "authorized_transitions": authorized_transitions,
        "provenance": provenance,
        "fail_closed": False,
        "error_code": None,
        "issues": [],
    }


def _validate_task_attributes(attrs: object, routing_features: dict[str, Any]) -> None:
    if not isinstance(attrs, dict):
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", "input.task_attributes", "task_attributes must be a mapping")
    attr_vocab = routing_features.get("task_attributes", {})
    for key, value in attrs.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise PolicyEvaluationError(
                "POLICY_TYPE_ERROR",
                f"input.task_attributes.{key}",
                "task attribute keys and values must be strings",
            )
        if key not in attr_vocab:
            raise PolicyEvaluationError("POLICY_UNKNOWN_ATTRIBUTE", f"input.task_attributes.{key}", f"unknown task attribute {key}")
        allowed_values = attr_vocab[key].get("allowed_values", [])
        if value not in allowed_values:
            raise PolicyEvaluationError(
                "POLICY_UNKNOWN_ATTRIBUTE_VALUE",
                f"input.task_attributes.{key}",
                f"unknown value {value} for task attribute {key}",
            )


def _derive_routing_features(attrs: dict[str, str], risk_level: str, routing_features: dict[str, Any]) -> set[str]:
    features = set(routing_features.get("risk_conditions", {}).get(risk_level, []))
    attr_vocab = routing_features.get("task_attributes", {})
    for key, value in attrs.items():
        features.update(attr_vocab.get(key, {}).get("maps_to_features", {}).get(value, []))
    return features


def _derive_required_skills(features: set[str], routing_features: dict[str, Any]) -> list[str]:
    required: list[str] = []
    for skill_id, rule in routing_features.get("skill_rule_features", {}).items():
        if rule.get("always") is True:
            required.append(skill_id)
            continue
        if any(feature in features for feature in rule.get("when_any", [])):
            required.append(skill_id)
    return required


def _derive_model_roles(risk_level: str, routing_features: dict[str, Any]) -> dict[str, str]:
    roles: dict[str, str] = {}
    for actor, rule in routing_features.get("model_role_rules", {}).items():
        if "always" in rule:
            roles[actor] = rule["always"]
        elif risk_level in rule:
            roles[actor] = rule[risk_level]
    return roles


def _profile_record(bundle: PolicyBundle, profile_id: str | None) -> tuple[str | None, dict[str, Any] | None]:
    if profile_id is None:
        return None, None
    record = bundle.project_profiles.get(profile_id)
    if not isinstance(record, dict):
        return None, None
    profile = record.get("profile")
    source_path = record.get("source_path")
    return (
        source_path if isinstance(source_path, str) else None,
        profile if isinstance(profile, dict) else None,
    )


def _canonical_order(values: list[str], declaration_order: list[str]) -> list[str]:
    present = set(values)
    return [item for item in declaration_order if item in present]


def _canonical_provenance(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return ordered


def _provenance_order_key(value: str, stable_index: int = 0) -> tuple[int, int]:
    prefixes = (
        "config/risk_policy.yaml:",
        "project_profiles/",
        "config/human_decision_policy.yaml:",
        "config/skill_routing.yaml:",
        "config/model_routing.yaml:",
        "config/workflow_policy.yaml:",
    )
    for index, prefix in enumerate(prefixes):
        if value.startswith(prefix):
            return index, stable_index
    return len(prefixes), stable_index


def _duplicate_item(items: list[object]) -> tuple[int, object] | None:
    seen: set[object] = set()
    for index, item in enumerate(items):
        if item in seen:
            return index, item
        seen.add(item)
    return None


def _is_safe_relative_path(value: str) -> bool:
    if not value or "\\" in value or value.startswith("/") or re.match(r"^[A-Za-z]:", value):
        return False
    return all(part not in ("", ".", "..") for part in value.split("/"))


def _assert_safe_file(root: Path, path: Path, logical_path: str) -> None:
    root_resolved = root.resolve()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        raise PolicyEvaluationError("POLICY_FILE_MISSING", logical_path, "required policy file is missing") from None
    if path.is_symlink():
        raise PolicyEvaluationError("POLICY_PROFILE_REQUIRED_FILE_INVALID", logical_path, "symlink policy paths are not allowed")
    if not resolved.is_relative_to(root_resolved):
        raise PolicyEvaluationError("POLICY_PROFILE_REQUIRED_FILE_INVALID", logical_path, "policy path escapes repository root")
    if not resolved.is_file():
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", logical_path, "policy path must be a regular file")


def _contains_yaml_anchor_or_alias(text: str) -> bool:
    return contains_yaml_anchor_or_alias(text)


@contextmanager
def _fixture_overlay_root(root: Path, fixture_id: str):
    fixture_base = (root / "tests" / "fixtures" / "policy_eval").resolve()
    fixture_dir = _fixture_child_dir(fixture_base, fixture_id, "fixture_id")
    fixture = _load_fixture_yaml(fixture_dir / "fixture.yaml", "fixture.yaml")
    policy_root_name = fixture.get("policy_root", "policy_root")
    if not isinstance(policy_root_name, str) or not policy_root_name:
        raise PolicyEvaluationError("POLICY_MALFORMED", "fixture.policy_root", "fixture.yaml policy_root must be a non-empty string when present")
    policy_root = _fixture_child_dir(fixture_dir, policy_root_name, "fixture.policy_root")
    with tempfile.TemporaryDirectory() as temp_dir:
        overlay = Path(temp_dir)
        shutil.copytree(root / "config", overlay / "config")
        if (root / "project_profiles").exists():
            shutil.copytree(root / "project_profiles", overlay / "project_profiles")
        _apply_fixture_overlay(policy_root, overlay)
        _copy_declared_required_files(root, overlay)
        yield overlay


def _fixture_child_dir(base: Path, child: str, path: str) -> Path:
    if not isinstance(child, str) or not _is_safe_relative_path(child):
        raise PolicyEvaluationError("POLICY_MALFORMED", path, "fixture paths must be safe relative paths")
    candidate = base / child
    if candidate.is_symlink():
        raise PolicyEvaluationError("POLICY_PROFILE_REQUIRED_FILE_INVALID", path, "symlink fixture paths are not allowed")
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError:
        raise PolicyEvaluationError("POLICY_FILE_MISSING", path, "required fixture directory is missing") from None
    base_resolved = base.resolve()
    if not resolved.is_relative_to(base_resolved):
        raise PolicyEvaluationError("POLICY_PROFILE_REQUIRED_FILE_INVALID", path, "fixture path escapes approved fixture root")
    if not resolved.is_dir():
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", path, "fixture path must be a directory")
    return resolved


def _apply_fixture_overlay(policy_root: Path, overlay: Path) -> None:
    config_root = policy_root / "config"
    if config_root.exists():
        _assert_fixture_descendant(policy_root, config_root, "fixture.policy_root.config", expect_dir=True)
        for source_file in sorted(config_root.glob("*.yaml"), key=lambda path: path.as_posix()):
            logical_path = source_file.relative_to(policy_root).as_posix()
            _assert_fixture_descendant(policy_root, source_file, logical_path, expect_dir=False)
            target = overlay / "config" / source_file.name
            _apply_yaml_overlay_file(source_file, target)
        for required in ("config/risk_policy.yaml", "config/skill_routing.yaml"):
            fixture_policy = policy_root / required
            if not fixture_policy.exists():
                (overlay / required).unlink(missing_ok=True)
    profiles_root = policy_root / "project_profiles"
    if profiles_root.exists():
        _assert_fixture_descendant(policy_root, profiles_root, "fixture.policy_root.project_profiles", expect_dir=True)
        target_profiles = overlay / "project_profiles"
        if target_profiles.exists():
            shutil.rmtree(target_profiles)
        _copy_fixture_tree(policy_root, profiles_root, target_profiles)


def _apply_yaml_overlay_file(source_file: Path, target_file: Path) -> None:
    if source_file.is_symlink():
        raise PolicyEvaluationError("POLICY_PROFILE_REQUIRED_FILE_INVALID", source_file.name, "symlink fixture files are not allowed")
    try:
        source_text = source_file.read_text(encoding="utf-8")
        if _contains_yaml_anchor_or_alias(source_text):
            shutil.copy2(source_file, target_file)
            return
        source = yaml.load(source_text, Loader=UniqueKeyLoader)
    except Exception:
        shutil.copy2(source_file, target_file)
        return
    if not isinstance(source, dict) or source.get("schema_version") != 1:
        shutil.copy2(source_file, target_file)
        return
    try:
        target = yaml.load(target_file.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except Exception:
        shutil.copy2(source_file, target_file)
        return
    if not isinstance(target, dict):
        shutil.copy2(source_file, target_file)
        return
    merged = _deep_merge_mapping(target, source)
    target_file.write_text(yaml.safe_dump(merged, sort_keys=False), encoding="utf-8")


def _deep_merge_mapping(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge_mapping(merged[key], value)
        else:
            merged[key] = value
    return merged


def _assert_fixture_descendant(policy_root: Path, path: Path, logical_path: str, *, expect_dir: bool) -> Path:
    policy_root_resolved = policy_root.resolve()
    relative_parts = path.relative_to(policy_root).parts
    cursor = policy_root
    for part in relative_parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise PolicyEvaluationError("POLICY_PROFILE_REQUIRED_FILE_INVALID", logical_path, "symlink fixture paths are not allowed")
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError:
        raise PolicyEvaluationError("POLICY_FILE_MISSING", logical_path, "required fixture path is missing") from None
    if not resolved.is_relative_to(policy_root_resolved):
        raise PolicyEvaluationError("POLICY_PROFILE_REQUIRED_FILE_INVALID", logical_path, "fixture path escapes policy root")
    if expect_dir and not resolved.is_dir():
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", logical_path, "fixture path must be a directory")
    if not expect_dir and not resolved.is_file():
        raise PolicyEvaluationError("POLICY_TYPE_ERROR", logical_path, "fixture path must be a regular file")
    return resolved


def _copy_fixture_tree(policy_root: Path, source_dir: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for source_path in sorted(source_dir.rglob("*"), key=lambda path: path.as_posix()):
        logical_path = source_path.relative_to(policy_root).as_posix()
        if source_path.is_symlink():
            raise PolicyEvaluationError("POLICY_PROFILE_REQUIRED_FILE_INVALID", logical_path, "symlink fixture paths are not allowed")
        relative = source_path.relative_to(source_dir)
        target_path = target_dir / relative
        if source_path.is_dir():
            _assert_fixture_descendant(policy_root, source_path, logical_path, expect_dir=True)
            target_path.mkdir(parents=True, exist_ok=True)
        elif source_path.is_file():
            _assert_fixture_descendant(policy_root, source_path, logical_path, expect_dir=False)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
        else:
            raise PolicyEvaluationError("POLICY_TYPE_ERROR", logical_path, "fixture path must be a regular file or directory")


def _copy_declared_required_files(source_root: Path, overlay: Path) -> None:
    profiles_dir = overlay / "project_profiles"
    if not profiles_dir.exists():
        return
    for profile_path in sorted(profiles_dir.glob("*.yaml"), key=lambda path: path.as_posix()):
        try:
            profile = yaml.load(profile_path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
        except Exception:
            continue
        required_files = profile.get("required_files") if isinstance(profile, dict) else None
        if not isinstance(required_files, dict):
            continue
        for rel_path in required_files.values():
            if not isinstance(rel_path, str) or not _is_safe_relative_path(rel_path):
                continue
            source = source_root / rel_path
            target = overlay / rel_path
            if source.is_file() and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)


def _stable_digest(data: object) -> str:
    import hashlib

    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _policy_bundle_digest(policies: dict[str, dict[str, Any]], profiles: dict[str, dict[str, Any]]) -> str:
    return _stable_digest(
        {
            "policy_files": {
                logical_path: policies[key]
                for key, logical_path in sorted(POLICY_FILES.items(), key=lambda item: item[1])
            },
            "project_profiles": profiles,
        }
    )


def _load_fixture_yaml(path: Path, logical_path: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"missing policy eval fixture file: {path.as_posix()}")
    try:
        data = load_yaml_strict(path.read_text(encoding="utf-8"), logical_path=logical_path)
    except DuplicateYamlKeyError as exc:
        key = str(exc.key) if exc.key is not None else "<unknown>"
        raise PolicyEvaluationError("POLICY_DUPLICATE_YAML_KEY", f"{logical_path}:{key}", "duplicate YAML key detected", mark=exc.mark) from exc
    except (StrictYamlError, UnicodeDecodeError) as exc:
        raise PolicyEvaluationError("POLICY_MALFORMED", logical_path, "policy fixture cannot be parsed") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.as_posix()} must be a mapping")
    return data


def _fixture_load_policy_root(policy_root: Path) -> tuple[dict[str, dict[str, Any]], tuple[str, str, str] | None]:
    for required in _fixture_required_policy_files(policy_root):
        if not (policy_root / required).exists():
            return {}, ("POLICY_FILE_MISSING", required, "required policy file is missing")
    loaded: dict[str, dict[str, Any]] = {}
    for logical_path in ("config/risk_policy.yaml", "config/skill_routing.yaml"):
        try:
            loaded[logical_path] = _load_fixture_yaml(policy_root / logical_path, logical_path)
        except PolicyEvaluationError as exc:
            return {}, (exc.code, exc.path, exc.message)
    profiles_dir = policy_root / "project_profiles"
    if profiles_dir.exists():
        for profile_path in sorted(profiles_dir.glob("*.yaml"), key=lambda path: path.as_posix()):
            logical_path = profile_path.relative_to(policy_root).as_posix()
            try:
                loaded[logical_path] = _load_fixture_yaml(profile_path, logical_path)
            except PolicyEvaluationError as exc:
                return {}, (exc.code, exc.path, exc.message)
    return loaded, None


def _fixture_required_policy_files(policy_root: Path) -> tuple[str, ...]:
    required = ["config/risk_policy.yaml", "config/skill_routing.yaml"]
    if (policy_root / "project_profiles").exists():
        required.append("project_profiles")
    return tuple(required)


def _run_fixture_phase(
    phase: str,
    loaded: dict[str, dict[str, Any]],
    policy_root: Path,
) -> tuple[str, str, str] | None:
    if phase == "schema":
        for logical_path, data in loaded.items():
            if "schema_version" in data and data.get("schema_version") != 1:
                return "POLICY_UNSUPPORTED_VERSION", f"{logical_path}:schema_version", "unsupported policy schema version"
    if phase == "skill_routing":
        try:
            _validate_primary_routes(loaded.get("config/skill_routing.yaml", {}), "config/skill_routing.yaml")
        except PolicyEvaluationError as exc:
            return exc.code, exc.path, exc.message
    if phase == "risk_conflict":
        conflict = _fixture_risk_policy_conflict(loaded.get("config/risk_policy.yaml", {}))
        if conflict is not None:
            return conflict
    if phase == "duplicate_profiles":
        return _fixture_duplicate_profiles(loaded, policy_root)
    if phase == "profile_validation":
        return _fixture_profile_validation(loaded, policy_root)
    return None


def _fixture_risk_policy_conflict(risk: dict[str, Any]) -> tuple[str, str, str] | None:
    seen: dict[tuple[object, object], object] = {}
    for index, rule in enumerate(risk.get("rules", [])):
        if not isinstance(rule, dict):
            continue
        key = (rule.get("trigger"), rule.get("priority"))
        previous = seen.get(key)
        if previous is not None and previous != rule.get("risk_level"):
            return "POLICY_CONFLICT", f"config/risk_policy.yaml:rules[{index}]", "conflicting equal-priority policy rules"
        seen[key] = rule.get("risk_level")
    return None


def _fixture_profiles(loaded: dict[str, dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    return [(path, data) for path, data in loaded.items() if path.startswith("project_profiles/")]


def _fixture_duplicate_profiles(
    loaded: dict[str, dict[str, Any]],
    policy_root: Path,
) -> tuple[str, str, str] | None:
    seen: set[str] = set()
    for logical_path, profile in _fixture_profiles(loaded):
        profile_id = profile.get("profile_id")
        if profile_id in seen:
            return "POLICY_DUPLICATE_PROFILE_ID", f"{logical_path}:profile_id", "duplicate profile_id detected"
        if isinstance(profile_id, str):
            seen.add(profile_id)
    return None


def _fixture_profile_validation(
    loaded: dict[str, dict[str, Any]],
    policy_root: Path,
) -> tuple[str, str, str] | None:
    risk = loaded.get("config/risk_policy.yaml", {})
    for logical_path, profile in _fixture_profiles(loaded):
        try:
            _validate_project_profile(policy_root, logical_path, profile, risk)
        except PolicyEvaluationError as exc:
            if exc.code in {"POLICY_PROFILE_REQUIRED_FILE_INVALID", "POLICY_PROFILE_DOWNGRADE_FORBIDDEN"}:
                return exc.code, exc.path, exc.message
            return exc.code, exc.path, exc.message
    return None
