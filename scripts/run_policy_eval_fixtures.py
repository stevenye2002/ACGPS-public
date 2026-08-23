from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml

from acgps import policy


def main() -> int:
    errors: list[str] = []
    cases_doc = yaml.safe_load((ROOT / "config" / "policy_eval_cases.yaml").read_text(encoding="utf-8"))
    for case in cases_doc.get("cases", []):
        fixture_id = case.get("fixture_id")
        if fixture_id is None:
            continue
        result = policy.evaluate_policy_fixture(str(fixture_id), case.get("input"), root=ROOT)
        expected = case.get("expected")
        if result != expected:
            errors.append(f"{fixture_id}: production fixture result did not match expected catalog output")
            continue
        if not result.get("fail_closed") or not result.get("error_code") or not result.get("issues"):
            errors.append(f"{fixture_id}: expected stable fail-closed error code, path, and message")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"POLICY_EVAL_FIXTURES_FAILED count={len(errors)}")
        return 1

    print("POLICY_EVAL_FIXTURES_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
