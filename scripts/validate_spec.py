from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMPLATE_CONTRACTS = (
    ("templates/TASK_INTAKE.yaml", "task_intake"),
    ("templates/HUMAN_DECISION_REQUEST.yaml", "human_decision_request"),
    ("templates/HUMAN_DECISION_RESOLUTION.yaml", "human_decision_resolution"),
    ("templates/AGENT_TASK_CONTRACT.yaml", "agent_task_contract"),
    ("templates/AGENT_RESULT.yaml", "agent_result"),
    ("templates/REVIEW_FINDING.yaml", "review_finding"),
    ("templates/VERIFICATION_RECORD.yaml", "verification_record"),
    ("templates/RELEASE_CANDIDATE_MANIFEST.yaml", "release_candidate_manifest"),
)


class SpecValidationError(ValueError):
    pass


def validate_repository(root: Path) -> tuple[int, int, int]:
    from acgps import policy
    from acgps.contracts import (
        ContractValidationError,
        UnsupportedContractVersionError,
        validate_contract,
    )
    from acgps.yaml_loader import load_yaml_strict

    bundle = policy.load_policy_bundle(root)
    for relative_path, contract_name in TEMPLATE_CONTRACTS:
        template_path = root / relative_path
        template = load_yaml_strict(
            template_path.read_text(encoding="utf-8"),
            logical_path=relative_path,
        )
        try:
            validate_contract(contract_name, template, mode="template")
        except (ContractValidationError, UnsupportedContractVersionError) as exc:
            raise SpecValidationError(f"{relative_path}: {exc}") from exc

    return len(policy.POLICY_FILES), len(bundle.project_profiles), len(TEMPLATE_CONTRACTS)


def main(root: Path = ROOT) -> int:
    try:
        policy_count, profile_count, template_count = validate_repository(root)
    except Exception as exc:
        print(f"SPEC_VALIDATION_FAILED {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        "SPEC_VALIDATION_OK "
        f"policies={policy_count} profiles={profile_count} templates={template_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
