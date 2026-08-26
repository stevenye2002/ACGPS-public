from __future__ import annotations

import subprocess
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.build_mvp_source_archive import (
    SourceArchiveError,
    build_source_archive,
    verify_source_archive,
)
from scripts.release_readiness import ReleaseReadinessError, validate_supported_environment


class DeterministicSourceArchiveTests(unittest.TestCase):
    def test_archive_is_deterministic_and_matches_git_candidate_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            subprocess.run(
                ["git", "init", "--initial-branch=main"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "config", "core.autocrlf", "false"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            (root / ".gitignore").write_text("ignored/\n", encoding="utf-8", newline="\n")
            (root / "tracked.txt").write_text("tracked\n", encoding="utf-8", newline="\n")
            subprocess.run(
                ["git", "add", ".gitignore", "tracked.txt"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.email=test@example.invalid",
                    "-c",
                    "user.name=ACGPS Test",
                    "commit",
                    "-m",
                    "baseline",
                ],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            (root / "candidate.txt").write_text("candidate\n", encoding="utf-8", newline="\n")
            ignored = root / "ignored"
            ignored.mkdir()
            (ignored / "cache.txt").write_text("ignored\n", encoding="utf-8", newline="\n")

            first = Path(tmp) / "first.zip"
            second = Path(tmp) / "second.zip"
            first_result = build_source_archive(root, first)
            second_result = build_source_archive(root, second)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_result, second_result)
            self.assertEqual(first_result["file_count"], 3)
            with zipfile.ZipFile(first) as archive:
                self.assertEqual(
                    archive.namelist(),
                    [".gitignore", "candidate.txt", "tracked.txt"],
                )
                self.assertEqual(archive.read("candidate.txt"), b"candidate\n")
                for item in archive.infolist():
                    self.assertEqual(item.date_time, (1980, 1, 1, 0, 0, 0))

            self.assertEqual(verify_source_archive(root, first), first_result)

            (root / "candidate.txt").write_text("changed\n", encoding="utf-8", newline="\n")
            with self.assertRaises(SourceArchiveError):
                verify_source_archive(root, first)

            (root / "candidate.txt").write_text("candidate\n", encoding="utf-8", newline="\n")
            subprocess.run(
                ["git", "update-index", "--skip-worktree", "tracked.txt"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            (root / "tracked.txt").unlink()
            index_backed = Path(tmp) / "index-backed.zip"

            build_source_archive(root, index_backed)

            with zipfile.ZipFile(index_backed) as archive:
                self.assertEqual(archive.read("tracked.txt"), b"tracked\n")
            verify_source_archive(root, index_backed)

            subprocess.run(
                ["git", "update-index", "--no-skip-worktree", "tracked.txt"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            with self.assertRaises(SourceArchiveError):
                build_source_archive(root, Path(tmp) / "deleted.zip")

            subprocess.run(
                ["git", "add", "-u", "tracked.txt"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            )
            with self.assertRaises(SourceArchiveError):
                build_source_archive(root, Path(tmp) / "staged-deletion.zip")

    def test_supported_environment_is_exactly_windows_server_2022_python_3_13(self) -> None:
        self.assertEqual(
            validate_supported_environment("win32", (3, 13, 13), "2022Server"),
            {
                "platform": "win32",
                "profile": "WINDOWS_SERVER_2022",
                "python": "3.13.13",
                "windows_release": "2022Server",
            },
        )
        for platform_name, version_info, windows_release in (
            ("linux", (3, 13, 13), "2022Server"),
            ("darwin", (3, 13, 13), "2022Server"),
            ("win32", (3, 12, 9), "2022Server"),
            ("win32", (3, 14, 0), "2022Server"),
            ("win32", (3, 13, 13), "11"),
            ("win32", (3, 13, 13), "2019Server"),
        ):
            with self.subTest(
                platform_name=platform_name,
                version_info=version_info,
                windows_release=windows_release,
            ):
                with self.assertRaises(ReleaseReadinessError):
                    validate_supported_environment(platform_name, version_info, windows_release)


if __name__ == "__main__":
    unittest.main()
