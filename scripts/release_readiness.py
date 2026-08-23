from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from acgps.review_adapter import ReviewEvidenceError, verify_release_candidate_manifest
from scripts.build_mvp_source_archive import SourceArchiveError, build_source_archive, verify_source_archive


class ReleaseReadinessError(ValueError):
    pass


def validate_supported_environment(platform_name: str, version_info: tuple[int, int, int]) -> dict[str, str]:
    major, minor, patch = version_info
    if platform_name != "win32" or (major, minor) != (3, 13):
        raise ReleaseReadinessError("ACGPS v0.1 release readiness supports only Windows with Python 3.13")
    return {"platform": platform_name, "python": f"{major}.{minor}.{patch}"}


def evaluate_release_readiness(
    repo_root: Path,
    *,
    archive_path: Path | None = None,
    manifest_path: Path | None = None,
    platform_name: str | None = None,
    version_info: tuple[int, int, int] | None = None,
) -> dict[str, object]:
    environment = validate_supported_environment(
        sys.platform if platform_name is None else platform_name,
        tuple(sys.version_info[:3]) if version_info is None else version_info,
    )
    root = Path(repo_root).resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="acgps-release-readiness-") as temporary:
        temporary_root = Path(temporary)
        first = temporary_root / "candidate-a.zip"
        second = temporary_root / "candidate-b.zip"
        first_result = build_source_archive(root, first)
        second_result = build_source_archive(root, second)
        if first.read_bytes() != second.read_bytes() or first_result != second_result:
            raise ReleaseReadinessError("source archive generation is not deterministic")
        verify_source_archive(root, first)
        if archive_path is not None:
            supplied = Path(archive_path).resolve(strict=True)
            supplied_result = verify_source_archive(root, supplied)
            if supplied.read_bytes() != first.read_bytes() or supplied_result != first_result:
                raise ReleaseReadinessError("supplied source archive does not match the deterministic candidate")
    if manifest_path is not None:
        verify_release_candidate_manifest(Path(manifest_path), require_build_artifacts=True)
    return {
        "archive": first_result,
        "environment": environment,
        "scope": "WINDOWS_PYTHON_3_13",
        "status": "RELEASE_READY",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate bounded ACGPS v0.1 release readiness.")
    parser.add_argument("--repo-root", default=str(ROOT))
    parser.add_argument("--archive")
    parser.add_argument("--manifest")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = evaluate_release_readiness(
            Path(args.repo_root),
            archive_path=Path(args.archive) if args.archive else None,
            manifest_path=Path(args.manifest) if args.manifest else None,
        )
    except (OSError, ReleaseReadinessError, ReviewEvidenceError, SourceArchiveError) as exc:
        print(json.dumps({"error": str(exc), "status": "HOLD"}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
