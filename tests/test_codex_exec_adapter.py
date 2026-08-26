from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from acgps.codex_exec_adapter import (
    create_disposable_clone,
    inspect_clone_after,
    observe_executor_identity,
    run_bounded_process,
)


def _run_git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _create_source_repository(root: Path) -> tuple[Path, str, str]:
    repo = root / "source"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    _run_git(repo, "config", "user.email", "test@example.invalid")
    _run_git(repo, "config", "user.name", "ACGPS Test")
    (repo / "example.txt").write_text("baseline\n", encoding="utf-8")
    _run_git(repo, "add", "example.txt")
    _run_git(repo, "commit", "-m", "baseline")
    return repo, _run_git(repo, "rev-parse", "HEAD"), _run_git(repo, "rev-parse", "HEAD^{tree}")


class CodexExecAdapterTests(unittest.TestCase):
    def test_observe_executor_identity_binds_artifact_bytes_and_fixed_launch_contract(self) -> None:
        observation = observe_executor_identity(
            Path(sys.executable),
            argv=[sys.executable, "exec", "--json"],
            platform_profile="WINDOWS_11_X64_NTFS_PYTHON_3_13_ELEVATED_PRIVATE_DESKTOP",
        )

        executable_bytes = Path(sys.executable).read_bytes()
        self.assertEqual(observation["path"], str(Path(sys.executable).resolve()))
        self.assertEqual(observation["size_bytes"], len(executable_bytes))
        self.assertEqual(observation["sha256"], hashlib.sha256(executable_bytes).hexdigest())
        self.assertEqual(observation["argv"], [sys.executable, "exec", "--json"])
        self.assertEqual(observation["model"], "gpt-5.6-sol")
        self.assertEqual(observation["reasoning_effort"], "high")
        self.assertIn(observation["authenticode_status"], {"VALID", "INVALID", "MISSING"})

    def test_observe_executor_identity_accepts_explicit_windows_server_2022_profile(self) -> None:
        platform = "WINDOWS_SERVER_2022_X64_NTFS_PYTHON_3_13_ELEVATED_PRIVATE_DESKTOP"

        observation = observe_executor_identity(
            Path(sys.executable),
            argv=[sys.executable, "exec", "--json"],
            platform_profile=platform,
        )

        self.assertEqual(observation["platform"], platform)

    def test_observe_executor_identity_rejects_unqualified_platform_profile(self) -> None:
        with self.assertRaisesRegex(ValueError, "unsupported executor platform profile"):
            observe_executor_identity(
                Path(sys.executable),
                argv=[sys.executable, "exec", "--json"],
                platform_profile="WINDOWS_SERVER_2025_UNQUALIFIED",
            )

    def test_inspect_clone_after_derives_stable_changed_paths_and_diff_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, commit, tree = _create_source_repository(root)
            clone = root / "clone"
            before = create_disposable_clone(source, commit, clone)
            (clone / "example.txt").write_text("changed\n", encoding="utf-8")
            (clone / "new.txt").write_text("new\n", encoding="utf-8")

            after = inspect_clone_after(clone)

            self.assertEqual(after.commit, commit)
            self.assertEqual(after.tree, tree)
            self.assertEqual(after.git_control_sha256, before.git_control_sha256)
            self.assertEqual(after.changed_paths, ("example.txt", "new.txt"))
            self.assertRegex(after.diff_sha256, r"^[0-9a-f]{64}$")
            self.assertEqual(after, inspect_clone_after(clone))

    def test_create_disposable_clone_is_detached_clean_and_has_no_remotes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, commit, tree = _create_source_repository(root)
            clone = root / "clone"

            observation = create_disposable_clone(source, commit, clone)

            self.assertEqual(observation.path, clone.resolve())
            self.assertEqual(observation.commit, commit)
            self.assertEqual(observation.tree, tree)
            self.assertEqual(observation.remote_count, 0)
            self.assertTrue(observation.independent_git)
            self.assertTrue(observation.detached)
            self.assertTrue(observation.clean)
            self.assertTrue((clone / ".git").is_dir())
            self.assertEqual(_run_git(clone, "remote"), "")
            self.assertEqual(_run_git(clone, "status", "--porcelain"), "")

    def test_run_bounded_process_uses_exact_environment_and_hashes_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            program = (
                "import json, os; "
                "print(json.dumps({'visible': os.environ.get('ACGPS_VISIBLE'), "
                "'secret': os.environ.get('ACGPS_TEST_SECRET')}, sort_keys=True))"
            )
            result = run_bounded_process(
                [sys.executable, "-c", program],
                cwd=root,
                environment={"ACGPS_VISIBLE": "yes"},
                timeout_seconds=10.0,
            )

            expected_stdout = b'{"secret": null, "visible": "yes"}\r\n'
            self.assertEqual(result.exit_code, 0)
            self.assertFalse(result.timed_out)
            self.assertFalse(result.cancelled)
            self.assertIsNone(result.error)
            self.assertTrue(result.all_descendants_terminated)
            self.assertEqual(result.stdout, expected_stdout)
            self.assertEqual(result.stderr, b"")
            self.assertEqual(result.stdout_sha256, hashlib.sha256(expected_stdout).hexdigest())
            self.assertEqual(result.stderr_sha256, hashlib.sha256(b"").hexdigest())

    def test_run_bounded_process_times_out_and_terminates_process_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_bounded_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                cwd=Path(tmp),
                environment={},
                timeout_seconds=0.2,
            )

            self.assertTrue(result.timed_out)
            self.assertTrue(result.all_descendants_terminated)
            self.assertIsNotNone(result.started_at_utc)
            self.assertIsNotNone(result.ended_at_utc)
            self.assertEqual(result.stdout_sha256, hashlib.sha256(b"").hexdigest())
            self.assertEqual(result.stderr_sha256, hashlib.sha256(b"").hexdigest())

    def test_run_bounded_process_records_creation_failure_without_output_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_bounded_process(
                [str(Path(tmp) / "missing-executable.exe")],
                cwd=Path(tmp),
                environment={},
                timeout_seconds=1.0,
            )

            self.assertTrue(result.start_requested)
            self.assertIsNone(result.pid)
            self.assertIsNotNone(result.error)
            self.assertIsNone(result.stdout_sha256)
            self.assertIsNone(result.stderr_sha256)
            self.assertTrue(result.all_descendants_terminated)


if __name__ == "__main__":
    unittest.main()
