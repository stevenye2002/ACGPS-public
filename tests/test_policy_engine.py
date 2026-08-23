from __future__ import annotations

import json
import hashlib
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from acgps import policy
from acgps.contracts import validate_contract


ROOT = Path(__file__).resolve().parents[1]
MVP_FTIC_ROOT = ROOT / "tests" / "fixtures" / "mvp_ftic"


def load_cases() -> list[dict[str, object]]:
    with (ROOT / "config" / "policy_eval_cases.yaml").open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)["cases"]


def case_by_id(case_id: str) -> dict[str, object]:
    for case in load_cases():
        if case["case_id"] == case_id:
            return case
    raise AssertionError(f"missing policy eval case {case_id}")


def write_yaml(path: Path, data: object) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")


def canonical_json_digest(record: object) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def copied_policy_root(temp_dir: str) -> Path:
    temp_root = Path(temp_dir)
    shutil.copytree(ROOT / "config", temp_root / "config")
    shutil.copytree(ROOT / "project_profiles", temp_root / "project_profiles")
    public_sources = {
        "docs/PROJECT_GOAL.md": ROOT / "docs" / "PROJECT_GOAL.md",
        "docs/PROJECT_STATE.md": MVP_FTIC_ROOT / "docs" / "PROJECT_STATE.md",
        "AGENTS.md": MVP_FTIC_ROOT / "AGENTS.md",
        "reviews/CURRENT_REVIEW.md": MVP_FTIC_ROOT / "reviews" / "CURRENT_REVIEW.md",
    }
    for rel_path, source in public_sources.items():
        target = temp_root / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return temp_root


class PolicyEngineTests(unittest.TestCase):
    def test_profile_loading_validates_required_file_syntax_not_acgps_root_existence(self) -> None:
        bundle = policy.load_policy_bundle(ROOT)

        self.assertEqual(
            bundle.project_profiles["ftic-v1"]["profile"]["required_files"]["goal"],
            "docs/FTIC_PROJECT_REPLAN.md",
        )

    def test_project_registration_resolves_required_files_under_managed_root(self) -> None:
        profile = policy.load_policy_bundle(ROOT).project_profiles["ftic-v1"]["profile"]

        resolved = policy.validate_project_registration(MVP_FTIC_ROOT, profile)

        self.assertEqual(resolved["goal"], MVP_FTIC_ROOT / "docs" / "FTIC_PROJECT_REPLAN.md")
        self.assertEqual(resolved["state"], MVP_FTIC_ROOT / "docs" / "PROJECT_STATE.md")
        self.assertEqual(resolved["agents"], MVP_FTIC_ROOT / "AGENTS.md")
        self.assertEqual(resolved["active_review"], MVP_FTIC_ROOT / "reviews" / "CURRENT_REVIEW.md")

    def test_project_registration_rejects_missing_managed_file(self) -> None:
        profile = policy.load_policy_bundle(ROOT).project_profiles["ftic-v1"]["profile"]
        with tempfile.TemporaryDirectory() as tmp:
            managed_root = Path(tmp) / "managed"
            shutil.copytree(MVP_FTIC_ROOT, managed_root)
            (managed_root / "docs" / "FTIC_PROJECT_REPLAN.md").unlink()

            with self.assertRaises(policy.PolicyEvaluationError) as missing:
                policy.validate_project_registration(managed_root, profile)

        self.assertEqual(missing.exception.code, "POLICY_PROFILE_REQUIRED_FILE_INVALID")
        self.assertEqual(missing.exception.path, "required_files.goal")

    def test_valid_policy_bundle_loads_profiles_with_source_paths(self) -> None:
        bundle = policy.load_policy_bundle(ROOT)

        self.assertIn("ftic-v1", bundle.project_profiles)
        self.assertEqual(
            "project_profiles/ftic.yaml",
            bundle.project_profiles["ftic-v1"]["source_path"],
        )

    def test_positive_eval_case_matches_catalog_and_contract(self) -> None:
        case = case_by_id("TEST-POLICY-003")
        result = policy.evaluate_policy(case["input"], root=ROOT)

        self.assertEqual(case["expected"], result)
        validate_contract(
            "policy_evaluation_result",
            {
                "schema_version": 1,
                "evaluation_id": "TEST-POLICY-003",
                "project_id": "ACGPS",
                "task_id": "TEST-POLICY-003",
                "policy_bundle_digest": policy.load_policy_bundle(ROOT).policy_bundle_digest,
                "result": result,
                "created_at_utc": "2026-07-26T00:00:00Z",
            },
        )

    def test_public_evaluator_accepts_full_contract_input_and_returns_full_contract_result(self) -> None:
        case = case_by_id("TEST-POLICY-003")
        public_input = {
            "schema_version": 1,
            "evaluation_id": "TEST-POLICY-003",
            "project_id": "ACGPS",
            "task_id": "TEST-POLICY-003",
            "input": case["input"],
            "created_at_utc": "2026-07-26T00:00:00Z",
        }

        result = policy.evaluate_policy(public_input, root=ROOT)

        self.assertEqual(
            {
                "schema_version": 1,
                "evaluation_id": "TEST-POLICY-003",
                "project_id": "ACGPS",
                "task_id": "TEST-POLICY-003",
                "policy_bundle_digest": policy.load_policy_bundle(ROOT).policy_bundle_digest,
                "result": case["expected"],
                "created_at_utc": "2026-07-26T00:00:00Z",
            },
            result,
        )
        validate_contract("policy_evaluation_result", result)

    def test_public_evaluator_returns_policy_bundle_digest_distinct_from_result_hash(self) -> None:
        case = case_by_id("TEST-POLICY-003")
        public_input = {
            "schema_version": 1,
            "evaluation_id": "TEST-POLICY-003",
            "project_id": "ACGPS",
            "task_id": "TEST-POLICY-003",
            "input": case["input"],
            "created_at_utc": "2026-07-26T00:00:00Z",
        }

        result = policy.evaluate_policy(public_input, root=ROOT)

        self.assertEqual(policy.load_policy_bundle(ROOT).policy_bundle_digest, result["policy_bundle_digest"])
        self.assertNotEqual(canonical_json_digest(result), result["policy_bundle_digest"])
        validate_contract("policy_evaluation_result", result)

    def test_policy_result_contract_requires_policy_bundle_digest_for_success(self) -> None:
        case = case_by_id("TEST-POLICY-003")
        record = {
            "schema_version": 1,
            "evaluation_id": "TEST-POLICY-003",
            "project_id": "ACGPS",
            "task_id": "TEST-POLICY-003",
            "policy_bundle_digest": None,
            "result": case["expected"],
            "created_at_utc": "2026-07-26T00:00:00Z",
        }

        with self.assertRaisesRegex(Exception, "policy_bundle_digest"):
            validate_contract("policy_evaluation_result", record)

    def test_public_evaluator_invalid_wrapper_fails_closed_with_valid_result_envelope(self) -> None:
        case = case_by_id("TEST-POLICY-003")
        public_input = {
            "schema_version": "1",
            "evaluation_id": "TEST-POLICY-003",
            "project_id": "ACGPS",
            "task_id": "TEST-POLICY-003",
            "input": case["input"],
            "created_at_utc": "not-a-time",
        }

        result = policy.evaluate_policy(public_input, root=ROOT)

        validate_contract("policy_evaluation_result", result)
        self.assertTrue(result["result"]["fail_closed"])
        self.assertEqual("POLICY_TYPE_ERROR", result["result"]["error_code"])

    def test_public_evaluator_round_trips_every_valid_catalog_case(self) -> None:
        for case in load_cases():
            expected = case["expected"]
            if case.get("fixture_id") is not None or expected["fail_closed"] is True:
                continue
            with self.subTest(case_id=case["case_id"]):
                public_input = {
                    "schema_version": 1,
                    "evaluation_id": case["case_id"],
                    "project_id": "ACGPS",
                    "task_id": case["case_id"],
                    "input": case["input"],
                    "created_at_utc": "2026-07-26T00:00:00Z",
                }

                result = policy.evaluate_policy(public_input, root=ROOT)

                comparable_expected = {
                    key: value
                    for key, value in expected.items()
                    if key != "replay_deterministic"
                }
                validate_contract("policy_evaluation_result", result)
                self.assertEqual(comparable_expected, result["result"])

    def test_human_gate_restricts_authorized_transitions(self) -> None:
        case = case_by_id("TEST-POLICY-002")
        result = policy.evaluate_policy(case["input"], root=ROOT)

        self.assertTrue(result["human_gate"])
        self.assertEqual(["WAITING_HUMAN", "ABANDONED"], result["authorized_transitions"])
        self.assertEqual(case["expected"], result)

    def test_profile_raise_and_order_perturbation_are_deterministic(self) -> None:
        case = case_by_id("TEST-POLICY-017")
        reversed_input = dict(case["input"])
        reversed_input["risk_triggers"] = list(reversed(case["input"]["risk_triggers"]))

        first = policy.evaluate_policy(case["input"], root=ROOT)
        second = policy.evaluate_policy(reversed_input, root=ROOT)

        self.assertEqual(case["expected"], first)
        self.assertEqual(first, second)
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )

    def test_unknown_attribute_and_duplicate_set_inputs_fail_closed(self) -> None:
        unknown_attribute = policy.evaluate_policy(
            {
                "current_state": "DRAFT",
                "risk_triggers": [],
                "human_triggers": [],
                "task_attributes": {"fixture_id": "not_public_input"},
                "project_profile_id": None,
            },
            root=ROOT,
        )
        duplicate_trigger = policy.evaluate_policy(
            {
                "current_state": "DRAFT",
                "risk_triggers": ["ui_ux_change", "ui_ux_change"],
                "human_triggers": [],
                "task_attributes": {},
                "project_profile_id": None,
            },
            root=ROOT,
        )

        self.assertEqual("POLICY_UNKNOWN_ATTRIBUTE", unknown_attribute["error_code"])
        self.assertTrue(unknown_attribute["fail_closed"])
        self.assertEqual("POLICY_DUPLICATE_SET_MEMBER", duplicate_trigger["error_code"])
        self.assertTrue(duplicate_trigger["fail_closed"])

    def test_invalid_policy_roots_fail_closed_without_partial_output(self) -> None:
        for case_id in (
            "TEST-POLICY-008",
            "TEST-POLICY-009",
            "TEST-POLICY-010",
            "TEST-POLICY-011",
            "TEST-POLICY-012",
            "TEST-POLICY-013",
            "TEST-POLICY-014",
            "TEST-POLICY-015",
            "TEST-POLICY-016",
        ):
            case = case_by_id(case_id)
            result = policy.evaluate_policy_fixture(case["fixture_id"], case["input"], root=ROOT)

            self.assertEqual(case["expected"], result)
            self.assertFalse(result["decision_emitted"])
            self.assertEqual([], result["authorized_transitions"])

    def test_profile_discovery_is_order_independent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            shutil.copytree(ROOT / "config", temp_root / "config")
            (temp_root / "project_profiles").mkdir()
            shutil.copy2(ROOT / "project_profiles" / "ftic.yaml", temp_root / "project_profiles" / "z.yaml")
            primary = yaml.safe_load((temp_root / "project_profiles" / "z.yaml").read_text(encoding="utf-8"))
            primary["required_files"] = {}
            (temp_root / "project_profiles" / "z.yaml").write_text(
                yaml.safe_dump(primary, sort_keys=False),
                encoding="utf-8",
            )
            shutil.copy2(ROOT / "project_profiles" / "ftic.yaml", temp_root / "project_profiles" / "a.yaml")
            second = yaml.safe_load((temp_root / "project_profiles" / "a.yaml").read_text(encoding="utf-8"))
            second["profile_id"] = "alpha-v1"
            second["required_files"] = {}
            (temp_root / "project_profiles" / "a.yaml").write_text(
                yaml.safe_dump(second, sort_keys=False),
                encoding="utf-8",
            )

            result = policy.evaluate_policy(case_by_id("TEST-POLICY-006")["input"], root=temp_root)

            self.assertFalse(result["fail_closed"])
            self.assertEqual("R1", result["risk_level"])
            self.assertIn("project_profiles/z.yaml:risk_overrides.report_copy_only", result["provenance"])

    def test_eval_suite_runner_matches_all_shipped_cases_and_is_stable(self) -> None:
        first = policy.run_policy_eval_suite(ROOT)
        second = policy.run_policy_eval_suite(ROOT)

        self.assertTrue(first["passed"], first)
        self.assertEqual(18, first["case_count"])
        self.assertEqual([], first["failures"])
        self.assertEqual(
            json.dumps(first, sort_keys=True, separators=(",", ":")),
            json.dumps(second, sort_keys=True, separators=(",", ":")),
        )

    def test_eval_suite_runner_uses_production_path_for_invalid_fixture_roots(self) -> None:
        with patch.object(policy, "derive_policy_fixture_error", side_effect=AssertionError("reference path bypass")):
            result = policy.run_policy_eval_suite(ROOT)

        self.assertTrue(result["passed"], result)

    def test_policy_loader_rejects_yaml_aliases_and_anchors_before_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            shutil.copytree(ROOT / "config", temp_root / "config")
            shutil.copytree(ROOT / "project_profiles", temp_root / "project_profiles")
            profile_path = temp_root / "project_profiles" / "ftic.yaml"
            profile = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
            profile["required_files"] = {}
            profile_path.write_text(yaml.safe_dump(profile, sort_keys=False), encoding="utf-8")
            risk = (temp_root / "config" / "risk_policy.yaml").read_text(encoding="utf-8")
            (temp_root / "config" / "risk_policy.yaml").write_text(
                risk.replace("schema_version: 1", "schema_version: &risk_schema 1", 1),
                encoding="utf-8",
            )

            result = policy.evaluate_policy(case_by_id("TEST-POLICY-001")["input"], root=temp_root)

        self.assertTrue(result["fail_closed"])
        self.assertEqual("POLICY_MALFORMED", result["error_code"])
        self.assertIn("config/risk_policy.yaml", result["issues"][0]["path"])

    def test_profile_required_files_symlinks_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            managed_root = Path(temp_dir) / "managed"
            managed_root.mkdir()
            target = managed_root / "README.md"
            target.write_text("controlled target\n", encoding="utf-8")
            link = managed_root / "linked-required-file.md"
            try:
                os.symlink(target, link)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            profile = dict(policy.load_policy_bundle(ROOT).project_profiles["ftic-v1"]["profile"])
            profile["required_files"] = {"linked": "linked-required-file.md"}

            with self.assertRaises(policy.PolicyEvaluationError) as symlinked:
                policy.validate_project_registration(managed_root, profile)

        self.assertEqual("POLICY_PROFILE_REQUIRED_FILE_INVALID", symlinked.exception.code)
        self.assertEqual("required_files.linked", symlinked.exception.path)

    def test_policy_document_held_out_mutations_fail_closed_before_decision(self) -> None:
        mutations = []

        def mutate_skill_unknown_field(root: Path) -> None:
            path = root / "config" / "skill_routing.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["unexpected"] = True
            write_yaml(path, data)

        mutations.append(("skill_unknown_field", mutate_skill_unknown_field, "POLICY_UNKNOWN_FIELD"))

        def mutate_skill_bad_route_target(root: Path) -> None:
            path = root / "config" / "skill_routing.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["primary_discovery"]["routes"]["new_ui"] = "unknown_skill"
            write_yaml(path, data)

        mutations.append(("skill_unknown_route_target", mutate_skill_bad_route_target, "POLICY_UNKNOWN_ID"))

        def mutate_model_bad_nested(root: Path) -> None:
            path = root / "config" / "model_routing.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["escalate_when"] = "not-a-list"
            write_yaml(path, data)

        mutations.append(("model_bad_nested", mutate_model_bad_nested, "POLICY_TYPE_ERROR"))

        def mutate_human_bad_examples(root: Path) -> None:
            path = root / "config" / "human_decision_policy.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["triggers"]["H2_IRREVERSIBLE_OR_COSTLY"]["examples"] = "not-a-list"
            write_yaml(path, data)

        mutations.append(("human_bad_examples", mutate_human_bad_examples, "POLICY_TYPE_ERROR"))

        def mutate_routing_bad_canonical(root: Path) -> None:
            path = root / "config" / "policy_routing_features.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["canonical_order"] = "not-a-mapping"
            write_yaml(path, data)

        mutations.append(("routing_bad_canonical_order", mutate_routing_bad_canonical, "POLICY_TYPE_ERROR"))

        def mutate_workflow_missing_transition(root: Path) -> None:
            path = root / "config" / "workflow_policy.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            del data["transitions"]["CLASSIFIED"]
            write_yaml(path, data)

        mutations.append(("workflow_missing_transition", mutate_workflow_missing_transition, "POLICY_UNKNOWN_ID"))

        def mutate_missing_r2_level(root: Path) -> None:
            path = root / "config" / "risk_policy.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            del data["levels"]["R2"]
            write_yaml(path, data)

        mutations.append(("risk_missing_selected_level", mutate_missing_r2_level, "POLICY_UNKNOWN_ID"))

        def mutate_unknown_risk_level_field(root: Path) -> None:
            path = root / "config" / "risk_policy.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["levels"]["R2"]["unexpected"] = True
            write_yaml(path, data)

        mutations.append(("risk_level_unknown_field", mutate_unknown_risk_level_field, "POLICY_UNKNOWN_FIELD"))

        def mutate_bad_risk_level_description(root: Path) -> None:
            path = root / "config" / "risk_policy.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["levels"]["R2"]["description"] = 12
            write_yaml(path, data)

        mutations.append(("risk_level_bad_description", mutate_bad_risk_level_description, "POLICY_TYPE_ERROR"))

        def mutate_bad_policy_id(root: Path) -> None:
            path = root / "config" / "model_routing.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["policy_id"] = 12
            write_yaml(path, data)

        mutations.append(("policy_id_bad_type", mutate_bad_policy_id, "POLICY_TYPE_ERROR"))

        def mutate_malformed_risk_rule(root: Path) -> None:
            path = root / "config" / "risk_policy.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["rules"] = [{"foo": "bar"}]
            write_yaml(path, data)

        mutations.append(("risk_rule_unknown_field", mutate_malformed_risk_rule, "POLICY_UNKNOWN_FIELD"))

        def mutate_empty_model_capability(root: Path) -> None:
            path = root / "config" / "model_routing.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["roles"]["planner_architect"]["capability"] = ""
            write_yaml(path, data)

        mutations.append(("model_empty_capability", mutate_empty_model_capability, "POLICY_TYPE_ERROR"))

        def mutate_unknown_feature_reference(root: Path) -> None:
            path = root / "config" / "policy_routing_features.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            data["skill_rule_features"]["superpowers_writing_plans"]["when_any"].append("undeclared_feature")
            write_yaml(path, data)

        mutations.append(("routing_unknown_feature_reference", mutate_unknown_feature_reference, "POLICY_UNKNOWN_ID"))

        for name, mutate, expected_code in mutations:
            with self.subTest(name=name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    temp_root = copied_policy_root(temp_dir)
                    mutate(temp_root)

                    result = policy.evaluate_policy(case_by_id("TEST-POLICY-002")["input"], root=temp_root)

                self.assertFalse(result["decision_emitted"], result)
                self.assertTrue(result["fail_closed"], result)
                self.assertEqual(expected_code, result["error_code"], result)

    def test_missing_risk_level_cannot_emit_public_executable_decision(self) -> None:
        case = case_by_id("TEST-POLICY-007")
        public_input = {
            "schema_version": 1,
            "evaluation_id": "held-out-missing-r2",
            "project_id": "ACGPS",
            "task_id": "held-out-missing-r2",
            "input": case["input"],
            "created_at_utc": "2026-07-26T00:00:00Z",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = copied_policy_root(temp_dir)
            path = temp_root / "config" / "risk_policy.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            del data["levels"]["R2"]
            write_yaml(path, data)

            result = policy.evaluate_policy(public_input, root=temp_root)

        self.assertFalse(result["result"]["decision_emitted"], result)
        self.assertTrue(result["result"]["fail_closed"], result)
        self.assertEqual([], result["result"]["authorized_transitions"])
        self.assertEqual("POLICY_UNKNOWN_ID", result["result"]["error_code"])

    def test_fixture_roots_are_canonically_contained_under_fixture_base(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = copied_policy_root(temp_dir)
            outside = Path(temp_dir) / "outside_fixture"
            shutil.copytree(ROOT / "tests" / "fixtures" / "policy_eval" / "unknown_schema_version", outside)

            absolute = policy.evaluate_policy_fixture(str(outside), case_by_id("TEST-POLICY-010")["input"], root=temp_root)
            traversal = policy.evaluate_policy_fixture("../outside_fixture", case_by_id("TEST-POLICY-010")["input"], root=temp_root)

        self.assertTrue(absolute["fail_closed"])
        self.assertNotEqual("POLICY_UNSUPPORTED_VERSION", absolute["error_code"])
        self.assertTrue(traversal["fail_closed"])
        self.assertNotEqual("POLICY_UNSUPPORTED_VERSION", traversal["error_code"])

    def test_fixture_policy_root_symlink_escape_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = copied_policy_root(temp_dir)
            fixtures = temp_root / "tests" / "fixtures" / "policy_eval"
            fixtures.mkdir(parents=True)
            external = Path(temp_dir) / "external_policy_root"
            shutil.copytree(ROOT / "tests" / "fixtures" / "policy_eval" / "unknown_schema_version" / "policy_root", external)
            fixture = fixtures / "symlink_policy_root"
            fixture.mkdir()
            try:
                os.symlink(external, fixture / "policy_root", target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            write_yaml(fixture / "fixture.yaml", {"schema_version": 1, "policy_root": "policy_root"})

            result = policy.evaluate_policy_fixture("symlink_policy_root", case_by_id("TEST-POLICY-010")["input"], root=temp_root)

        self.assertTrue(result["fail_closed"])
        self.assertNotEqual("POLICY_UNSUPPORTED_VERSION", result["error_code"])

    def test_fixture_descendant_symlink_files_do_not_escape_policy_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = copied_policy_root(temp_dir)
            fixtures = temp_root / "tests" / "fixtures" / "policy_eval"
            fixtures.mkdir(parents=True)
            external = Path(temp_dir) / "external-risk.yaml"
            external.write_text("schema_version: 99\n", encoding="utf-8")
            fixture = fixtures / "symlink_descendant_file"
            (fixture / "policy_root" / "config").mkdir(parents=True)
            (fixture / "policy_root" / "project_profiles").mkdir(parents=True)
            shutil.copy2(ROOT / "config" / "skill_routing.yaml", fixture / "policy_root" / "config" / "skill_routing.yaml")
            try:
                os.symlink(external, fixture / "policy_root" / "config" / "risk_policy.yaml")
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlink creation unavailable: {exc}")
            write_yaml(fixture / "fixture.yaml", {"schema_version": 1, "policy_root": "policy_root"})

            result = policy.evaluate_policy_fixture("symlink_descendant_file", case_by_id("TEST-POLICY-010")["input"], root=temp_root)

        self.assertTrue(result["fail_closed"])
        self.assertNotEqual("POLICY_UNSUPPORTED_VERSION", result["error_code"])


if __name__ == "__main__":
    unittest.main()
