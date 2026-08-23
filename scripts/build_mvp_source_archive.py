from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile
import zipfile


class SourceArchiveError(ValueError):
    pass


def _candidate_paths(repo_root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "-c", "core.quotepath=false", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise SourceArchiveError(f"cannot enumerate candidate files: {message}")
    try:
        paths = [item.decode("utf-8") for item in completed.stdout.split(b"\0") if item]
    except UnicodeDecodeError as exc:
        raise SourceArchiveError("candidate paths must be valid UTF-8") from exc
    if not paths:
        raise SourceArchiveError("candidate file set is empty")
    ordered = sorted(paths, key=lambda item: item.encode("utf-8"))
    if len(ordered) != len(set(ordered)):
        raise SourceArchiveError("candidate paths must be unique")
    return ordered


def _tracked_index(repo_root: Path) -> dict[str, str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--stage"],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SourceArchiveError("cannot read the Git index")
    result: dict[str, str] = {}
    try:
        rows = [row.decode("utf-8") for row in completed.stdout.split(b"\0") if row]
    except UnicodeDecodeError as exc:
        raise SourceArchiveError("Git index paths must be valid UTF-8") from exc
    for row in rows:
        metadata, separator, relative_path = row.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3 or fields[2] != "0":
            raise SourceArchiveError("Git index must contain only stage-zero paths")
        result[relative_path] = fields[1]
    return result


def _index_blob(repo_root: Path, object_id: str, relative_path: str) -> bytes:
    completed = subprocess.run(
        ["git", "cat-file", "blob", object_id],
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SourceArchiveError(f"cannot read index-backed candidate file: {relative_path}")
    return completed.stdout


def _deleted_paths(repo_root: Path, *, cached: bool) -> set[str]:
    arguments = ["git", "diff"]
    if cached:
        arguments.append("--cached")
    arguments.extend(["--name-only", "--no-renames", "--diff-filter=D", "-z", "--"])
    completed = subprocess.run(
        arguments,
        cwd=repo_root,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise SourceArchiveError("cannot inspect candidate deletions")
    try:
        return {item.decode("utf-8") for item in completed.stdout.split(b"\0") if item}
    except UnicodeDecodeError as exc:
        raise SourceArchiveError("deleted candidate paths must be valid UTF-8") from exc


def _regular_candidate_bytes(
    repo_root: Path,
    relative_path: str,
    tracked: dict[str, str],
    deleted: set[str],
) -> bytes:
    logical = PurePosixPath(relative_path)
    if logical.is_absolute() or not logical.parts or any(part in {"", ".", ".."} for part in logical.parts):
        raise SourceArchiveError(f"unsafe candidate path: {relative_path}")
    path = repo_root.joinpath(*logical.parts)
    try:
        status = path.lstat()
    except FileNotFoundError as exc:
        object_id = tracked.get(relative_path)
        if object_id is None or relative_path in deleted:
            raise SourceArchiveError(f"candidate file is missing: {relative_path}") from exc
        return _index_blob(repo_root, object_id, relative_path)
    except OSError as exc:
        raise SourceArchiveError(f"candidate file is unreadable: {relative_path}") from exc
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    file_attributes = getattr(status, "st_file_attributes", 0)
    if path.is_symlink() or (reparse_flag and file_attributes & reparse_flag) or not stat.S_ISREG(status.st_mode):
        raise SourceArchiveError(f"candidate entry must be a regular non-reparse file: {relative_path}")
    try:
        path.resolve(strict=True).relative_to(repo_root)
    except (OSError, ValueError) as exc:
        raise SourceArchiveError(f"candidate path escapes the repository: {relative_path}") from exc
    return path.read_bytes()


def _candidate_files(repo_root: Path) -> list[tuple[str, bytes]]:
    root = Path(repo_root).resolve(strict=True)
    tracked = _tracked_index(root)
    staged_deleted = _deleted_paths(root, cached=True)
    if staged_deleted:
        raise SourceArchiveError(f"staged candidate deletions are not supported: {sorted(staged_deleted)!r}")
    deleted = _deleted_paths(root, cached=False)
    return [
        (relative, _regular_candidate_bytes(root, relative, tracked, deleted))
        for relative in _candidate_paths(root)
    ]


def _archive_result(archive_path: Path, file_count: int) -> dict[str, object]:
    content = archive_path.read_bytes()
    return {
        "file_count": file_count,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
    }


def build_source_archive(repo_root: Path, output_path: Path) -> dict[str, object]:
    root = Path(repo_root).resolve(strict=True)
    output = Path(output_path).resolve(strict=False)
    files = _candidate_files(root)
    try:
        output_relative = output.relative_to(root).as_posix()
    except ValueError:
        output_relative = None
    if output_relative is not None and output_relative in {relative for relative, _ in files}:
        raise SourceArchiveError("archive output must not be part of the candidate file set")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent, delete=False) as handle:
            temporary_path = Path(handle.name)
        with zipfile.ZipFile(temporary_path, mode="w", compression=zipfile.ZIP_STORED, strict_timestamps=True) as archive:
            for relative_path, source_bytes in files:
                entry = zipfile.ZipInfo(relative_path, date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_STORED
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, source_bytes)
        temporary_path.replace(output)
        temporary_path = None
    except (OSError, zipfile.BadZipFile) as exc:
        raise SourceArchiveError(f"cannot build source archive: {exc}") from exc
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return _archive_result(output, len(files))


def verify_source_archive(repo_root: Path, archive_path: Path) -> dict[str, object]:
    root = Path(repo_root).resolve(strict=True)
    archive_source = Path(archive_path).resolve(strict=True)
    files = _candidate_files(root)
    expected_names = [relative for relative, _ in files]
    try:
        with zipfile.ZipFile(archive_source, mode="r") as archive:
            items = archive.infolist()
            if [item.filename for item in items] != expected_names:
                raise SourceArchiveError("archive file set or ordering does not match the candidate")
            for item, (relative_path, source_bytes) in zip(items, files, strict=True):
                if item.is_dir() or item.date_time != (1980, 1, 1, 0, 0, 0):
                    raise SourceArchiveError(f"archive metadata mismatch: {relative_path}")
                if item.compress_type != zipfile.ZIP_STORED or item.create_system != 3:
                    raise SourceArchiveError(f"archive storage metadata mismatch: {relative_path}")
                if archive.read(item) != source_bytes:
                    raise SourceArchiveError(f"archive content mismatch: {relative_path}")
    except (OSError, zipfile.BadZipFile) as exc:
        raise SourceArchiveError(f"cannot verify source archive: {exc}") from exc
    return _archive_result(archive_source, len(files))


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        print("usage: python scripts/build_mvp_source_archive.py REPO_ROOT OUTPUT_ZIP")
        return 2
    try:
        result = build_source_archive(Path(arguments[0]), Path(arguments[1]))
    except (OSError, SourceArchiveError) as exc:
        print(json.dumps({"error": str(exc), "status": "HOLD"}, sort_keys=True))
        return 1
    print(json.dumps({**result, "status": "ARCHIVE_READY"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
