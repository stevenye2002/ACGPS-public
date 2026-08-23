from __future__ import annotations

from pathlib import Path
import configparser
import unittest

from acgps.contracts import (
    ContractValidationError,
    UnknownContractError,
    UnsupportedContractVersionError,
    contract_names,
    validate_contract,
)

try:
    import yaml
except ImportError:  # pragma: no cover - exercised only in minimal environments
    yaml = None


ROOT = Path(__file__).resolve().parents[1]


class ContractCoreTests(unittest.TestCase):
    def test_task_intake_requires_schema_version_one(self) -> None:
        data = {
            "schema_version": 2,
            "task_id": "TASK-1",
            "project_id": "PROJECT",
            "title": "Contract validation",
            "requested_outcome": "Validate task intake",
            "business_context": "WP-1",
            "in_scope": [],
            "out_of_scope": [],
            "acceptance_criteria": [],
            "known_constraints": [],
            "known_risks": [],
            "affected_surfaces": [],
            "source_paths": [],
            "requested_by": "human_owner",
            "created_at_utc": "AUTO",
        }

        with self.assertRaises(UnsupportedContractVersionError) as raised:
            validate_contract("task_intake", data)

        self.assertIn("task_intake", str(raised.exception))
        self.assertIn("2", str(raised.exception))

    def test_task_intake_reports_missing_required_fields(self) -> None:
        with self.assertRaises(ContractValidationError) as raised:
            validate_contract("task_intake", {"schema_version": 1})

        message = str(raised.exception)
        self.assertIn("task_id", message)
        self.assertIn("project_id", message)
        self.assertIn("requested_outcome", message)


class ContractRegistryTests(unittest.TestCase):
    def test_registry_contains_every_wp1_contract(self) -> None:
        self.assertEqual(
            set(contract_names()),
            {
                "project_profile",
                "task_intake",
                "task_state",
                "risk_assessment",
                "routing_decision",
                "policy_evaluation_input",
                "policy_evaluation_result",
                "human_decision_request",
                "human_decision_resolution",
                "agent_task_contract",
                "agent_result",
                "review_finding",
                "verification_record",
                "audit_event",
                "release_candidate_manifest",
            },
        )

    def test_task_state_rejects_unknown_state(self) -> None:
        data = {
            "schema_version": 1,
            "task_id": "TASK-1",
            "project_id": "PROJECT",
            "state": "MADE_UP",
            "updated_at_utc": "2026-07-20T00:00:00Z",
            "evidence": [],
            "pending_decision_id": None,
        }

        with self.assertRaises(ContractValidationError) as raised:
            validate_contract("task_state", data)

        self.assertIn("MADE_UP", str(raised.exception))

    def test_human_decision_resolution_validates_status_and_target_state(self) -> None:
        data = {
            "schema_version": 1,
            "decision_id": "HDR-1",
            "project_id": "PROJECT",
            "task_id": "TASK-1",
            "selected_option": "OPTION-A",
            "resolved_by": "human_owner",
            "resolved_at_utc": "2026-07-20T00:00:00Z",
            "rationale": "Owner accepted the risk.",
            "evidence_paths": [],
            "resume_state": "MADE_UP",
            "status": "RESOLVED",
        }

        with self.assertRaises(ContractValidationError) as raised:
            validate_contract("human_decision_resolution", data)

        self.assertIn("resume_state", str(raised.exception))
        self.assertIn("MADE_UP", str(raised.exception))


class ContractExampleTests(unittest.TestCase):
    def test_repository_examples_validate_against_contracts(self) -> None:
        if yaml is None:
            self.skipTest("PyYAML unavailable; scripts/validate_spec.py reports this separately")

        examples = {
            "templates/TASK_INTAKE.yaml": "task_intake",
            "templates/HUMAN_DECISION_REQUEST.yaml": "human_decision_request",
            "templates/HUMAN_DECISION_RESOLUTION.yaml": "human_decision_resolution",
            "templates/AGENT_TASK_CONTRACT.yaml": "agent_task_contract",
            "templates/AGENT_RESULT.yaml": "agent_result",
            "templates/REVIEW_FINDING.yaml": "review_finding",
            "templates/VERIFICATION_RECORD.yaml": "verification_record",
            "templates/RELEASE_CANDIDATE_MANIFEST.yaml": "release_candidate_manifest",
            "project_profiles/ftic.yaml": "project_profile",
        }

        for rel_path, contract_name in examples.items():
            with self.subTest(rel_path=rel_path, contract_name=contract_name):
                data = yaml.safe_load((ROOT / rel_path).read_text(encoding="utf-8"))
                validate_contract(contract_name, data, mode="template")

    def test_contract_rejects_unexpected_fields(self) -> None:
        data = {
            "schema_version": 1,
            "task_id": "TASK-1",
            "project_id": "PROJECT",
            "title": "Contract validation",
            "requested_outcome": "Validate task intake",
            "business_context": "WP-1",
            "in_scope": [],
            "out_of_scope": [],
            "acceptance_criteria": [],
            "known_constraints": [],
            "known_risks": [],
            "affected_surfaces": [],
            "source_paths": [],
            "requested_by": "human_owner",
            "created_at_utc": "AUTO",
            "surprise": "drift",
        }

        with self.assertRaises(ContractValidationError) as raised:
            validate_contract("task_intake", data)

        self.assertIn("surprise", str(raised.exception))
        self.assertIn("unexpected field", str(raised.exception))

    def test_contract_rejects_boolean_schema_version(self) -> None:
        data = {
            "schema_version": True,
            "task_id": "TASK-1",
            "project_id": "PROJECT",
            "title": "Contract validation",
            "requested_outcome": "Validate task intake",
            "business_context": "WP-1",
            "in_scope": [],
            "out_of_scope": [],
            "acceptance_criteria": [],
            "known_constraints": [],
            "known_risks": [],
            "affected_surfaces": [],
            "source_paths": [],
            "requested_by": "human_owner",
            "created_at_utc": "AUTO",
        }

        with self.assertRaises(ContractValidationError) as raised:
            validate_contract("task_intake", data)

        self.assertIn("schema_version", str(raised.exception))
        self.assertIn("expected int", str(raised.exception))

    def test_release_candidate_requires_source_artifact_keys(self) -> None:
        data = {
            "schema_version": 1,
            "rc_id": "RC-1",
            "project_id": "PROJECT",
            "version": "0.1.0",
            "created_at_utc": "2026-07-20T00:00:00Z",
            "source_artifact": {},
            "build_artifacts": [],
            "verification_records": [],
            "review_closures": [],
            "known_limitations": [],
            "residual_risks": [],
            "rollback_plan_path": "docs/rollback.md",
            "human_release_authorization": None,
            "status": "RC_READY",
        }

        with self.assertRaises(ContractValidationError) as raised:
            validate_contract("release_candidate_manifest", data)

        self.assertIn("source_artifact.path", str(raised.exception))
        self.assertIn("source_artifact.sha256", str(raised.exception))

    def test_human_decision_options_require_required_keys(self) -> None:
        data = {
            "schema_version": 1,
            "decision_id": "HDR-1",
            "project_id": "PROJECT",
            "task_id": "TASK-1",
            "stage": "CLASSIFIED",
            "risk_level": "R2",
            "trigger": "H3_RISK_ACCEPTANCE",
            "question": "Accept known risk?",
            "recommended_option": "accept",
            "recommendation_rationale": "Evidence supports acceptance.",
            "options": [{}],
            "default_without_response": "PAUSE",
            "evidence_paths": [],
            "created_at_utc": "2026-07-20T00:00:00Z",
            "status": "PENDING",
        }

        with self.assertRaises(ContractValidationError) as raised:
            validate_contract("human_decision_request", data)

        self.assertIn("options[0].id", str(raised.exception))
        self.assertIn("options[0].description", str(raised.exception))

    def test_human_decision_options_must_include_recommended_option(self) -> None:
        data = {
            "schema_version": 1,
            "decision_id": "HDR-1",
            "project_id": "PROJECT",
            "task_id": "TASK-1",
            "stage": "CLASSIFIED",
            "risk_level": "R2",
            "trigger": "H3_RISK_ACCEPTANCE",
            "question": "Accept known risk?",
            "recommended_option": "accept",
            "recommendation_rationale": "Evidence supports acceptance.",
            "options": [],
            "default_without_response": "PAUSE",
            "evidence_paths": [],
            "created_at_utc": "2026-07-20T00:00:00Z",
            "status": "PENDING",
        }

        with self.assertRaises(ContractValidationError) as empty_error:
            validate_contract("human_decision_request", data)

        self.assertIn("options", str(empty_error.exception))
        self.assertIn("at least 1", str(empty_error.exception))

        data["options"] = [
            {
                "id": "pause",
                "description": "Pause for now",
                "benefits": [],
                "costs": [],
                "risks": [],
                "reversible": True,
            }
        ]

        with self.assertRaises(ContractValidationError) as mismatch_error:
            validate_contract("human_decision_request", data)

        self.assertIn("recommended_option", str(mismatch_error.exception))
        self.assertIn("accept", str(mismatch_error.exception))

    def test_verification_checks_require_required_keys(self) -> None:
        data = {
            "schema_version": 1,
            "verification_id": "VER-1",
            "project_id": "PROJECT",
            "task_id": "TASK-1",
            "baseline_hash": "HASH",
            "checks": [{}],
            "requirements_checked": [],
            "failed_requirements": [],
            "verified_at_utc": "2026-07-20T00:00:00Z",
            "verifier_role": "VERIFIER",
            "recommendation": "VERIFIED",
        }

        with self.assertRaises(ContractValidationError) as raised:
            validate_contract("verification_record", data)

        self.assertIn("checks[0].name", str(raised.exception))
        self.assertIn("checks[0].exit_code", str(raised.exception))

    def test_human_decision_risk_and_agent_result_role_are_enums(self) -> None:
        request = {
            "schema_version": 1,
            "decision_id": "HDR-1",
            "project_id": "PROJECT",
            "task_id": "TASK-1",
            "stage": "CLASSIFIED",
            "risk_level": "MADE_UP",
            "trigger": "H3_RISK_ACCEPTANCE",
            "question": "Accept known risk?",
            "recommended_option": "accept",
            "recommendation_rationale": "Evidence supports acceptance.",
            "options": [],
            "default_without_response": "PAUSE",
            "evidence_paths": [],
            "created_at_utc": "2026-07-20T00:00:00Z",
            "status": "PENDING",
        }
        result = {
            "schema_version": 1,
            "packet_id": "PACKET-1",
            "role": "MADE_UP",
            "status": "DONE",
            "summary": "completed",
            "changed_files": [],
            "created_files": [],
            "commands_run": [],
            "evidence_paths": [],
            "assumptions": [],
            "concerns": [],
            "blocker": None,
            "recommended_next_state": "TASK_REVIEW",
        }

        with self.assertRaises(ContractValidationError) as request_error:
            validate_contract("human_decision_request", request)
        with self.assertRaises(ContractValidationError) as result_error:
            validate_contract("agent_result", result)

        self.assertIn("risk_level", str(request_error.exception))
        self.assertIn("role", str(result_error.exception))


class ProjectChecksTests(unittest.TestCase):
    def test_implementation_checks_run_unittest_suite(self) -> None:
        parser = configparser.ConfigParser()
        parser.read(ROOT / "project_checks.ini", encoding="utf-8")
        expected = "python -m unittest discover -s tests -v"

        for check_name in ("affected", "full"):
            with self.subTest(check_name=check_name):
                self.assertIn(expected, parser.get("checks", check_name))

    def test_release_check_fails_closed_until_release_gate_exists(self) -> None:
        parser = configparser.ConfigParser()
        parser.read(ROOT / "project_checks.ini", encoding="utf-8")

        self.assertEqual(
            parser.get("checks", "release"),
            "python scripts/release_readiness.py",
        )


class RuntimeFixtureCoverageTests(unittest.TestCase):
    def test_every_contract_has_valid_runtime_fixture(self) -> None:
        if yaml is None:
            self.skipTest("PyYAML unavailable; scripts/validate_spec.py reports this separately")

        fixture_dir = ROOT / "tests" / "fixtures" / "contracts" / "runtime"
        fixture_names = {path.stem for path in fixture_dir.glob("*.yaml")}
        self.assertEqual(fixture_names, set(contract_names()))

        for contract_name in contract_names():
            with self.subTest(contract_name=contract_name):
                data = yaml.safe_load((fixture_dir / f"{contract_name}.yaml").read_text(encoding="utf-8"))
                validate_contract(contract_name, data)


class RuntimeSemanticAdversarialTests(unittest.TestCase):
    def test_runtime_rejects_invalid_nested_semantics_reported_by_design_review(self) -> None:
        if yaml is None:
            self.skipTest("PyYAML unavailable; scripts/validate_spec.py reports this separately")

        fixture_dir = ROOT / "tests" / "fixtures" / "contracts" / "runtime"
        cases = []

        task_intake = yaml.safe_load((fixture_dir / "task_intake.yaml").read_text(encoding="utf-8"))
        task_intake["created_at_utc"] = "2026-99-99T99:99:99Z"
        cases.append(("task_intake", task_intake, "created_at_utc"))

        task_intake_path = yaml.safe_load((fixture_dir / "task_intake.yaml").read_text(encoding="utf-8"))
        task_intake_path["source_paths"] = ["../escape"]
        cases.append(("task_intake", task_intake_path, "source_paths[0]"))

        task_intake_item = yaml.safe_load((fixture_dir / "task_intake.yaml").read_text(encoding="utf-8"))
        task_intake_item["acceptance_criteria"] = [123]
        cases.append(("task_intake", task_intake_item, "acceptance_criteria[0]"))

        project_profile = yaml.safe_load((fixture_dir / "project_profile.yaml").read_text(encoding="utf-8"))
        project_profile["required_files"] = {"bad": 123}
        project_profile["commands"] = {"quick": ["python", "-m", "unittest"]}
        cases.append(("project_profile", project_profile, "required_files.bad"))

        routing = yaml.safe_load((fixture_dir / "routing_decision.yaml").read_text(encoding="utf-8"))
        routing["model_roles"] = {"CODER": 123}
        routing["required_skills"] = [123]
        cases.append(("routing_decision", routing, "model_roles.CODER"))

        waiting = yaml.safe_load((fixture_dir / "task_state.yaml").read_text(encoding="utf-8"))
        waiting["state"] = "WAITING_HUMAN"
        waiting["pending_decision_id"] = None
        cases.append(("task_state", waiting, "pending_decision_id"))

        non_waiting = yaml.safe_load((fixture_dir / "task_state.yaml").read_text(encoding="utf-8"))
        non_waiting["state"] = "PLAN_READY"
        non_waiting["pending_decision_id"] = "HDR-1"
        cases.append(("task_state", non_waiting, "pending_decision_id"))

        verified = yaml.safe_load((fixture_dir / "verification_record.yaml").read_text(encoding="utf-8"))
        verified["recommendation"] = "VERIFIED"
        verified["checks"] = []
        verified["requirements_checked"] = []
        cases.append(("verification_record", verified, "checks"))

        finding = yaml.safe_load((fixture_dir / "review_finding.yaml").read_text(encoding="utf-8"))
        finding["status"] = "CLOSED"
        finding["disposition"] = "ACCEPTED"
        finding["evidence_paths"] = []
        finding["verification_required"] = []
        cases.append(("review_finding", finding, "evidence_paths"))

        rc = yaml.safe_load((fixture_dir / "release_candidate_manifest.yaml").read_text(encoding="utf-8"))
        rc["status"] = "RC_READY"
        rc["verification_records"] = ["../escape"]
        rc["review_closures"] = ["reviews/findings/F-1.yaml"]
        cases.append(("release_candidate_manifest", rc, "verification_records[0]"))

        for contract_name, data, expected_path in cases:
            with self.subTest(contract_name=contract_name, expected_path=expected_path):
                with self.assertRaises(ContractValidationError) as raised:
                    validate_contract(contract_name, data)
                self.assertIn(expected_path, str(raised.exception))

    def test_status_vocabulary_accepts_review_loop_statuses(self) -> None:
        agent_result = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/agent_result.yaml").read_text(encoding="utf-8")
        )
        review_finding = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/review_finding.yaml").read_text(encoding="utf-8")
        )

        agent_result["status"] = "DONE_WITH_CONCERNS"
        review_finding["status"] = "VERIFIED"
        review_finding["disposition"] = "ALREADY_FIXED"

        validate_contract("agent_result", agent_result)
        validate_contract("review_finding", review_finding)

    def test_policy_evaluation_result_rejects_cross_field_invariant_violations(self) -> None:
        if yaml is None:
            self.skipTest("PyYAML unavailable; scripts/validate_spec.py reports this separately")

        base = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )

        cases = []

        fail_closed_with_output = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        fail_closed_with_output["result"].update(
            {
                "decision_emitted": True,
                "fail_closed": True,
                "error_code": None,
                "issues": [],
                "required_skills": ["superpowers_verification_before_completion"],
                "authorized_transitions": ["SPEC_READY"],
            }
        )
        cases.append((fail_closed_with_output, "result.decision_emitted"))

        human_gate_bypass = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        human_gate_bypass["result"]["human_gate"] = True
        human_gate_bypass["result"]["authorized_transitions"] = ["SPEC_READY"]
        cases.append((human_gate_bypass, "result.authorized_transitions[0]"))

        illegal_authorized_transition = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        illegal_authorized_transition["result"]["authorized_transitions"] = ["CLOSED"]
        illegal_authorized_transition["result"]["legal_transitions"] = ["SPEC_READY"]
        cases.append((illegal_authorized_transition, "result.authorized_transitions[0]"))

        fail_closed_missing_issue = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        fail_closed_missing_issue["result"].update(
            {
                "decision_emitted": False,
                "fail_closed": True,
                "required_skills": [],
                "model_roles": {},
                "mandatory_gates": [],
                "legal_transitions": [],
                "authorized_transitions": [],
                "provenance": [],
                "error_code": "POLICY_UNKNOWN_ID",
                "issues": [],
            }
        )
        cases.append((fail_closed_missing_issue, "result.issues"))

        fail_closed_low_risk_unknown_code = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        fail_closed_low_risk_unknown_code["result"].update(
            {
                "decision_emitted": False,
                "fail_closed": True,
                "risk_level": "R0",
                "human_gate": False,
                "required_human_triggers": [],
                "required_skills": [],
                "model_roles": {},
                "mandatory_gates": [],
                "legal_transitions": [],
                "authorized_transitions": [],
                "provenance": [],
                "error_code": "POLICY_BOGUS_UNREGISTERED",
                "issues": [{"code": "POLICY_BOGUS_UNREGISTERED", "path": "x", "message": "bogus"}],
            }
        )
        cases.append((fail_closed_low_risk_unknown_code, "result.error_code"))

        fail_closed_mismatched_issue_code = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        fail_closed_mismatched_issue_code["result"].update(
            {
                "decision_emitted": False,
                "fail_closed": True,
                "risk_level": "R3",
                "human_gate": True,
                "required_human_triggers": [],
                "required_skills": [],
                "model_roles": {},
                "mandatory_gates": [],
                "legal_transitions": [],
                "authorized_transitions": [],
                "provenance": [],
                "error_code": "POLICY_UNKNOWN_ID",
                "issues": [{"code": "POLICY_TYPE_ERROR", "path": "x", "message": "mismatch"}],
            }
        )
        cases.append((fail_closed_mismatched_issue_code, "result.issues[0].code"))

        r3_without_human_gate = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        r3_without_human_gate["result"]["risk_level"] = "R3"
        r3_without_human_gate["result"]["human_gate"] = False
        cases.append((r3_without_human_gate, "result.human_gate"))

        human_trigger_without_gate = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        human_trigger_without_gate["result"]["required_human_triggers"] = ["H2_IRREVERSIBLE_OR_COSTLY"]
        human_trigger_without_gate["result"]["human_gate"] = False
        cases.append((human_trigger_without_gate, "result.human_gate"))

        duplicate_skill = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        duplicate_skill["result"]["required_skills"] = [
            "superpowers_verification_before_completion",
            "superpowers_verification_before_completion",
        ]
        cases.append((duplicate_skill, "result.required_skills[1]"))

        unknown_vocab = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        unknown_vocab["result"]["required_skills"] = ["unknown_skill"]
        unknown_vocab["result"]["model_roles"] = {"reviewer": "unknown_role"}
        unknown_vocab["result"]["mandatory_gates"] = ["unknown_gate"]
        unknown_vocab["result"]["legal_transitions"] = ["MADE_UP"]
        cases.append((unknown_vocab, "result.required_skills[0]"))

        unknown_model_actor = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        unknown_model_actor["result"]["model_roles"] = {"attacker": "planner_architect"}
        cases.append((unknown_model_actor, "result.model_roles.attacker"))

        duplicate_provenance = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        duplicate_provenance["result"]["provenance"] = [
            "config/risk_policy.yaml:triggers.evidence_or_audit_chain",
            "config/risk_policy.yaml:triggers.evidence_or_audit_chain",
        ]
        cases.append((duplicate_provenance, "result.provenance[1]"))

        invalid_provenance_path = yaml.safe_load(
            (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
        )
        invalid_provenance_path["result"]["provenance"] = ["not-a-policy-source"]
        cases.append((invalid_provenance_path, "result.provenance[0]"))

        for field_name in (
            "required_skills",
            "mandatory_gates",
            "provenance",
        ):
            reordered = yaml.safe_load(
                (ROOT / "tests/fixtures/contracts/runtime/policy_evaluation_result.yaml").read_text(encoding="utf-8")
            )
            reordered["result"][field_name] = list(reversed(reordered["result"][field_name]))
            cases.append((reordered, f"result.{field_name}"))

        validate_contract("policy_evaluation_result", base)
        for data, expected_path in cases:
            with self.subTest(expected_path=expected_path):
                with self.assertRaises(ContractValidationError) as raised:
                    validate_contract("policy_evaluation_result", data)
                self.assertIn(expected_path, str(raised.exception))


class RuntimeSemanticValidationTests(unittest.TestCase):
    def test_runtime_rejects_template_placeholders_empty_required_strings_and_bad_time(self) -> None:
        data = {
            "schema_version": 1,
            "task_id": "",
            "project_id": "PROJECT_ID",
            "title": "",
            "requested_outcome": "Validate task intake",
            "business_context": "WP-1",
            "in_scope": [],
            "out_of_scope": [],
            "acceptance_criteria": [],
            "known_constraints": [],
            "known_risks": [],
            "affected_surfaces": [],
            "source_paths": [],
            "requested_by": "human_owner",
            "created_at_utc": "not-a-time",
        }

        with self.assertRaises(ContractValidationError) as raised:
            validate_contract("task_intake", data)

        message = str(raised.exception)
        self.assertIn("task_id", message)
        self.assertIn("project_id", message)
        self.assertIn("title", message)
        self.assertIn("created_at_utc", message)

    def test_runtime_rejects_duplicate_options_invalid_stage_and_trigger(self) -> None:
        data = {
            "schema_version": 1,
            "decision_id": "HDR-0001",
            "project_id": "PROJECT",
            "task_id": "TASK-1",
            "stage": "BANANA",
            "risk_level": "R2",
            "trigger": "NOT_A_TRIGGER",
            "question": "Accept known risk?",
            "recommended_option": "accept",
            "recommendation_rationale": "Evidence supports acceptance.",
            "options": [
                {
                    "id": "accept",
                    "description": "Accept risk",
                    "benefits": [],
                    "costs": [],
                    "risks": [],
                    "reversible": True,
                },
                {
                    "id": "accept",
                    "description": "Duplicate accept",
                    "benefits": [],
                    "costs": [],
                    "risks": [],
                    "reversible": True,
                },
            ],
            "default_without_response": "PAUSE",
            "evidence_paths": [],
            "created_at_utc": "2026-07-20T00:00:00Z",
            "status": "PENDING",
        }

        with self.assertRaises(ContractValidationError) as raised:
            validate_contract("human_decision_request", data)

        message = str(raised.exception)
        self.assertIn("stage", message)
        self.assertIn("trigger", message)
        self.assertIn("options", message)
        self.assertIn("duplicate", message)

    def test_runtime_rejects_malformed_rc_hash_and_artifacts(self) -> None:
        data = {
            "schema_version": 1,
            "rc_id": "RC-0001",
            "project_id": "PROJECT",
            "version": "0.1.0",
            "created_at_utc": "2026-07-20T00:00:00Z",
            "source_artifact": {"path": "PATH", "sha256": "x"},
            "build_artifacts": [123, {"anything": "goes"}],
            "verification_records": [],
            "review_closures": [],
            "known_limitations": [],
            "residual_risks": [],
            "rollback_plan_path": "../escape.md",
            "human_release_authorization": None,
            "status": "RC_READY",
        }

        with self.assertRaises(ContractValidationError) as raised:
            validate_contract("release_candidate_manifest", data)

        message = str(raised.exception)
        self.assertIn("source_artifact.path", message)
        self.assertIn("source_artifact.sha256", message)
        self.assertIn("build_artifacts[0]", message)
        self.assertIn("rollback_plan_path", message)
        self.assertIn("verification_records", message)

    def test_runtime_rejects_contradictory_verification_agent_and_review_records(self) -> None:
        verification = {
            "schema_version": 1,
            "verification_id": "VER-0001",
            "project_id": "PROJECT",
            "task_id": "TASK-1",
            "baseline_hash": "a" * 64,
            "checks": [
                {
                    "name": "focused",
                    "command": "python -m unittest",
                    "exit_code": 1,
                    "result_summary": "failed",
                    "output_path": "artifacts/focused.txt",
                }
            ],
            "requirements_checked": [],
            "failed_requirements": [],
            "verified_at_utc": "2026-07-20T00:00:00Z",
            "verifier_role": "VERIFIER",
            "recommendation": "VERIFIED",
        }
        agent_result = {
            "schema_version": 1,
            "packet_id": "PACKET-1",
            "role": "CODER",
            "status": "DONE",
            "summary": "completed",
            "changed_files": [],
            "created_files": [],
            "commands_run": [],
            "evidence_paths": [],
            "assumptions": [],
            "concerns": [],
            "blocker": "fatal blocker",
            "recommended_next_state": "TASK_REVIEW",
        }
        review = {
            "schema_version": 1,
            "finding_id": "F-1",
            "review_id": "R-1",
            "severity": "P1",
            "category": "correctness",
            "summary": "finding",
            "evidence_paths": [],
            "impact": "impact",
            "recommendation": "fix",
            "disposition": "UNTRIAGED",
            "status": "CLOSED",
            "rationale": None,
            "verification_required": [],
        }

        for contract_name, data, expected in (
            ("verification_record", verification, "checks[0].exit_code"),
            ("agent_result", agent_result, "blocker"),
            ("review_finding", review, "disposition"),
        ):
            with self.subTest(contract_name=contract_name):
                with self.assertRaises(ContractValidationError) as raised:
                    validate_contract(contract_name, data)
                self.assertIn(expected, str(raised.exception))

    def test_template_mode_accepts_repository_templates_but_runtime_rejects_them(self) -> None:
        if yaml is None:
            self.skipTest("PyYAML unavailable; scripts/validate_spec.py reports this separately")
        data = yaml.safe_load((ROOT / "templates/TASK_INTAKE.yaml").read_text(encoding="utf-8"))

        validate_contract("task_intake", data, mode="template")
        with self.assertRaises(ContractValidationError):
            validate_contract("task_intake", data)

    def test_unknown_contract_and_unsupported_version_use_stable_errors(self) -> None:
        with self.assertRaises(UnknownContractError):
            validate_contract("missing_contract", {"schema_version": 1})
        with self.assertRaises(UnsupportedContractVersionError):
            validate_contract("task_intake", {"schema_version": 99})


if __name__ == "__main__":
    unittest.main()
