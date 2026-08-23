from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from acgps.contracts import ContractValidationError, validate_contract
from acgps.workflow_store import write_state_atomic


class ReviewEvidenceError(ValueError):
    pass


def _read_mapping(path: Path) -> dict[str, Any]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReviewEvidenceError(f"evidence is unreadable: {path}") from exc
    if not isinstance(record, dict):
        raise ReviewEvidenceError(f"evidence must be a mapping: {path}")
    return record


def _validate_record(contract_name: str, record: dict[str, Any], path: Path) -> None:
    try:
        validate_contract(contract_name, record, mode="runtime")
    except ContractValidationError as exc:
        raise ReviewEvidenceError(f"invalid {contract_name} at {path}: {exc}") from exc


def _relative_regular_file(root: Path, path: Path) -> tuple[str, Path]:
    root_resolved = root.resolve(strict=True)
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise ReviewEvidenceError(f"required evidence file is missing: {path}") from exc
    if path.is_symlink() or not resolved.is_file() or not resolved.is_relative_to(root_resolved):
        raise ReviewEvidenceError(f"evidence file must be a regular file under output_dir: {path}")
    return resolved.relative_to(root_resolved).as_posix(), resolved


def validate_review_findings(paths: Iterable[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        item = Path(path)
        record = _read_mapping(item)
        _validate_record("review_finding", record, item)
        if record["severity"] in {"P0", "P1"} and record["status"] not in {"VERIFIED", "CLOSED"}:
            raise ReviewEvidenceError(f"blocking review finding remains open: {record['finding_id']}")
        records.append(record)
    if not records:
        raise ReviewEvidenceError("at least one review finding is required")
    return records


def build_release_candidate_manifest(
    *,
    output_dir: Path,
    project_id: str,
    rc_id: str,
    version: str,
    source_path: Path,
    verification_paths: Iterable[Path],
    review_paths: Iterable[Path],
    rollback_path: Path,
    created_at_utc: str,
    build_artifact_paths: Iterable[Path] = (),
) -> Path:
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    source_rel, source = _relative_regular_file(root, Path(source_path))
    build_artifacts: list[dict[str, str]] = []
    build_paths: set[str] = set()
    for path in build_artifact_paths:
        rel, resolved = _relative_regular_file(root, Path(path))
        if rel in build_paths or rel == source_rel:
            raise ReviewEvidenceError("release candidate artifact paths must be unique")
        build_paths.add(rel)
        build_artifacts.append(
            {
                "path": rel,
                "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
            }
        )
    verification_rel: list[str] = []
    for path in verification_paths:
        rel, resolved = _relative_regular_file(root, Path(path))
        record = _read_mapping(resolved)
        _validate_record("verification_record", record, resolved)
        if record["recommendation"] != "VERIFIED":
            raise ReviewEvidenceError("release candidate requires VERIFIED evidence")
        if record["project_id"] != project_id:
            raise ReviewEvidenceError("verification evidence project_id does not match the release candidate")
        verification_rel.append(rel)
    review_items = [Path(path) for path in review_paths]
    validate_review_findings(review_items)
    review_rel = [_relative_regular_file(root, path)[0] for path in review_items]
    rollback_rel, _ = _relative_regular_file(root, Path(rollback_path))
    manifest = {
        "schema_version": 1,
        "rc_id": rc_id,
        "project_id": project_id,
        "version": version,
        "created_at_utc": created_at_utc,
        "source_artifact": {
            "path": source_rel,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        },
        "build_artifacts": build_artifacts,
        "verification_records": verification_rel,
        "review_closures": review_rel,
        "known_limitations": [],
        "residual_risks": [],
        "rollback_plan_path": rollback_rel,
        "human_release_authorization": None,
        "status": "RC_READY",
    }
    _validate_record("release_candidate_manifest", manifest, root / "release-candidate.json")
    manifest_path = root / "release-candidate.json"
    write_state_atomic(manifest_path, manifest)
    return manifest_path


def verify_release_candidate_manifest(
    manifest_path: Path,
    *,
    expected_project_id: str | None = None,
    expected_task_id: str | None = None,
    require_build_artifacts: bool = False,
) -> bool:
    path = Path(manifest_path)
    manifest = _read_mapping(path)
    _validate_record("release_candidate_manifest", manifest, path)
    if manifest["status"] != "RC_READY":
        raise ReviewEvidenceError("release candidate manifest status must be RC_READY")
    if manifest["human_release_authorization"] is not None:
        raise ReviewEvidenceError("RC_READY must not claim human release authorization")
    if expected_project_id is not None and manifest["project_id"] != expected_project_id:
        raise ReviewEvidenceError("release candidate project_id does not match the current project")
    if not manifest["verification_records"] or not manifest["review_closures"]:
        raise ReviewEvidenceError("RC_READY requires verification and independent review evidence")
    if require_build_artifacts and not manifest["build_artifacts"]:
        raise ReviewEvidenceError("release candidate requires at least one build artifact")
    root = path.parent
    for artifact in [manifest["source_artifact"], *manifest["build_artifacts"]]:
        _, resolved = _relative_regular_file(root, root / artifact["path"])
        if hashlib.sha256(resolved.read_bytes()).hexdigest() != artifact["sha256"]:
            raise ReviewEvidenceError(f"artifact hash mismatch: {artifact['path']}")
    for rel_path in manifest["verification_records"]:
        _, resolved = _relative_regular_file(root, root / rel_path)
        record = _read_mapping(resolved)
        _validate_record("verification_record", record, resolved)
        if record["recommendation"] != "VERIFIED":
            raise ReviewEvidenceError("verification evidence no longer recommends VERIFIED")
        if record["project_id"] != manifest["project_id"]:
            raise ReviewEvidenceError("verification evidence project_id does not match the manifest")
        if expected_task_id is not None and record["task_id"] != expected_task_id:
            raise ReviewEvidenceError("verification evidence task_id does not match the current task")
    review_paths = [root / rel_path for rel_path in manifest["review_closures"]]
    validate_review_findings(review_paths)
    _relative_regular_file(root, root / manifest["rollback_plan_path"])
    return True
