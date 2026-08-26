from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Mapping, Sequence

from acgps.contracts import CODING_EXECUTOR_PLATFORM_PROFILES


@dataclass(frozen=True)
class CloneObservation:
    path: Path
    commit: str
    tree: str
    index_sha256: str
    status_sha256: str
    git_control_sha256: str
    file_inventory_sha256: str
    remote_count: int
    independent_git: bool
    detached: bool
    clean: bool

    def to_record(self) -> dict[str, object]:
        return {
            "path": str(self.path),
            "commit": self.commit,
            "tree": self.tree,
            "index_sha256": self.index_sha256,
            "status_sha256": self.status_sha256,
            "git_control_sha256": self.git_control_sha256,
            "file_inventory_sha256": self.file_inventory_sha256,
            "remote_count": self.remote_count,
            "independent_git": self.independent_git,
            "detached": self.detached,
            "clean": self.clean,
        }


@dataclass(frozen=True)
class CloneAfterObservation:
    commit: str
    tree: str
    index_sha256: str
    status_sha256: str
    git_control_sha256: str
    file_inventory_sha256: str
    changed_paths: tuple[str, ...]
    diff_sha256: str

    def to_record(self) -> dict[str, object]:
        return {
            "commit": self.commit,
            "tree": self.tree,
            "index_sha256": self.index_sha256,
            "status_sha256": self.status_sha256,
            "git_control_sha256": self.git_control_sha256,
            "file_inventory_sha256": self.file_inventory_sha256,
            "changed_paths": list(self.changed_paths),
            "diff_sha256": self.diff_sha256,
        }


@dataclass(frozen=True)
class ProcessObservation:
    start_requested: bool
    pid: int | None
    started_at_utc: str | None
    ended_at_utc: str | None
    exit_code: int | None
    timed_out: bool
    cancelled: bool
    error: str | None
    descendant_count: int
    all_descendants_terminated: bool
    stdout: bytes
    stderr: bytes
    stdout_sha256: str | None
    stderr_sha256: str | None

    def to_record(self) -> dict[str, object]:
        return {
            "start_requested": self.start_requested,
            "pid": self.pid,
            "started_at_utc": self.started_at_utc,
            "ended_at_utc": self.ended_at_utc,
            "exit_code": self.exit_code,
            "timed_out": self.timed_out,
            "cancelled": self.cancelled,
            "error": self.error,
            "descendant_count": self.descendant_count,
            "all_descendants_terminated": self.all_descendants_terminated,
            "stdout_sha256": self.stdout_sha256,
            "stderr_sha256": self.stderr_sha256,
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
        shell=False,
    )


def _git_stdout(repo: Path, *args: str) -> bytes:
    return _run_git(repo, *args).stdout


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def observe_executor_identity(
    path: Path,
    *,
    argv: Sequence[str],
    platform_profile: str,
) -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("executor identity observation currently supports Windows only")
    if platform_profile not in CODING_EXECUTOR_PLATFORM_PROFILES:
        raise ValueError(f"unsupported executor platform profile: {platform_profile!r}")
    executable = path.resolve(strict=True)
    if not executable.is_file() or executable.is_symlink():
        raise ValueError("executor must be an ordinary local file")
    if not argv or not all(isinstance(item, str) and item and "\x00" not in item for item in argv):
        raise ValueError("executor argv must be a nonempty direct argument vector")

    inspection_environment: dict[str, str] = {"ACGPS_EXECUTOR_PATH": str(executable)}
    for wanted in ("SystemRoot", "WINDIR", "PATH", "PATHEXT"):
        for key, value in os.environ.items():
            if key.casefold() == wanted.casefold():
                inspection_environment[wanted] = value
                break
    signature_script = (
        "$s=Get-AuthenticodeSignature -LiteralPath $env:ACGPS_EXECUTOR_PATH;"
        "$o=[ordered]@{status=[string]$s.Status;signer=$null};"
        "if($null -ne $s.SignerCertificate){$o.signer=[string]$s.SignerCertificate.Subject};"
        "$o|ConvertTo-Json -Compress"
    )
    signature = subprocess.run(
        ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", signature_script],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=inspection_environment,
        shell=False,
        check=False,
    )
    raw_status = ""
    signer: str | None = None
    if signature.returncode == 0:
        try:
            signature_record = json.loads(signature.stdout.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            signature_record = None
        if isinstance(signature_record, dict):
            raw_status = str(signature_record.get("status", ""))
            raw_signer = signature_record.get("signer")
            signer = raw_signer if isinstance(raw_signer, str) and raw_signer else None
    authenticode_status = (
        "VALID"
        if raw_status.casefold() == "valid"
        else "MISSING"
        if raw_status.casefold() in ("", "notsigned")
        else "INVALID"
    )

    version_probe = subprocess.run(
        [str(executable), "--version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=inspection_environment,
        shell=False,
        check=False,
    )
    version_text = (version_probe.stdout or version_probe.stderr).decode("utf-8", errors="strict").strip()
    cli_version = version_text if version_probe.returncode == 0 and version_text else None
    size_bytes = executable.stat().st_size
    sha256 = _hash_file(executable)
    identity_complete = all(
        (
            authenticode_status == "VALID",
            signer is not None,
            cli_version is not None,
        )
    )
    return {
        "path": str(executable),
        "size_bytes": size_bytes,
        "sha256": sha256,
        "authenticode_status": authenticode_status,
        "signer": signer,
        "cli_version": cli_version,
        "identity_complete": identity_complete,
        "argv": list(argv),
        "model": "gpt-5.6-sol",
        "reasoning_effort": "high",
        "auth_mode": "CHATGPT_SUBSCRIPTION",
        "sandbox": "ISOLATED_CLONE",
        "approval_policy": "NEVER",
        "platform": platform_profile,
    }


def _file_inventory_sha256(root: Path) -> str:
    rows: list[bytes] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if relative.parts and relative.parts[0] == ".git":
            continue
        if path.is_symlink():
            raise ValueError(f"clone contains a symbolic link: {relative.as_posix()}")
        if path.is_file():
            content = path.read_bytes()
            rows.append(
                relative.as_posix().encode("utf-8")
                + b"\0"
                + str(len(content)).encode("ascii")
                + b"\0"
                + hashlib.sha256(content).hexdigest().encode("ascii")
                + b"\n"
            )
    return _sha256_bytes(b"".join(rows))


def inspect_clone(path: Path) -> CloneObservation:
    clone = path.resolve(strict=True)
    git_dir = clone / ".git"
    if not git_dir.is_dir() or git_dir.is_symlink():
        raise ValueError("clone must have independent Git control data")
    commit = _git_stdout(clone, "rev-parse", "HEAD").decode("ascii").strip()
    tree = _git_stdout(clone, "rev-parse", "HEAD^{tree}").decode("ascii").strip()
    status = _git_stdout(clone, "status", "--porcelain=v2", "-z", "--untracked-files=all")
    remotes = [line for line in _git_stdout(clone, "remote").decode("utf-8").splitlines() if line]
    detached_probe = _run_git(clone, "symbolic-ref", "-q", "HEAD", check=False)
    index_path = git_dir / "index"
    if not index_path.is_file() or index_path.is_symlink():
        raise ValueError("clone index is missing or redirected")
    git_control_rows = []
    for relative in ("HEAD", "config", "index", "packed-refs"):
        candidate = git_dir / relative
        if candidate.exists():
            if not candidate.is_file() or candidate.is_symlink():
                raise ValueError(f"invalid Git control member: {relative}")
            content = candidate.read_bytes()
            git_control_rows.append(relative.encode("ascii") + b"\0" + _sha256_bytes(content).encode("ascii") + b"\n")
    return CloneObservation(
        path=clone,
        commit=commit,
        tree=tree,
        index_sha256=_hash_file(index_path),
        status_sha256=_sha256_bytes(status),
        git_control_sha256=_sha256_bytes(b"".join(git_control_rows)),
        file_inventory_sha256=_file_inventory_sha256(clone),
        remote_count=len(remotes),
        independent_git=True,
        detached=detached_probe.returncode != 0,
        clean=status == b"",
    )


def create_disposable_clone(source_repository: Path, commit: str, target: Path) -> CloneObservation:
    source = source_repository.resolve(strict=True)
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("baseline commit must be a 40-character Git object ID")
    if target.exists() or target.is_symlink():
        raise ValueError("clone target must not already exist")
    subprocess.run(
        ["git", "clone", "--no-local", "--no-hardlinks", "--no-checkout", str(source), str(target)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
        shell=False,
    )
    _run_git(target, "checkout", "--detach", commit)
    if _run_git(target, "remote", "get-url", "origin", check=False).returncode == 0:
        _run_git(target, "remote", "remove", "origin")
    observation = inspect_clone(target)
    if observation.commit != commit or not observation.detached or not observation.clean or observation.remote_count != 0:
        raise ValueError("fresh clone does not match the fixed baseline boundary")
    return observation


def _changed_paths(repo: Path) -> tuple[str, ...]:
    tracked = _git_stdout(repo, "diff", "--name-only", "-z", "HEAD", "--")
    untracked = _git_stdout(repo, "ls-files", "--others", "--exclude-standard", "-z")
    try:
        names = [item.decode("utf-8") for item in (tracked + untracked).split(b"\0") if item]
    except UnicodeDecodeError as exc:
        raise ValueError("Git reported a non-UTF-8 candidate path") from exc
    if any(
        not name
        or "\\" in name
        or name.startswith("/")
        or any(part in ("", ".", "..") for part in name.split("/"))
        for name in names
    ):
        raise ValueError("Git reported an unsafe candidate path")
    if len({name.casefold() for name in names}) != len(set(names)):
        raise ValueError("candidate paths collide under case folding")
    return tuple(sorted(set(names)))


def _blob_identity(content: bytes | None) -> dict[str, int | str | None]:
    return {
        "sha256": _sha256_bytes(content) if content is not None else None,
        "size_bytes": len(content) if content is not None else None,
    }


def inspect_clone_after(path: Path) -> CloneAfterObservation:
    clone = path.resolve(strict=True)
    observation = inspect_clone(clone)
    changed_paths = _changed_paths(clone)
    diff_rows: list[dict[str, object]] = []
    for relative in changed_paths:
        before_result = _run_git(clone, "show", f"HEAD:{relative}", check=False)
        before = before_result.stdout if before_result.returncode == 0 else None
        candidate = clone / Path(*relative.split("/"))
        if candidate.is_symlink():
            raise ValueError(f"candidate path is a symbolic link: {relative}")
        if candidate.exists() and not candidate.is_file():
            raise ValueError(f"candidate path is not a regular file: {relative}")
        after = candidate.read_bytes() if candidate.is_file() else None
        diff_rows.append(
            {
                "after": _blob_identity(after),
                "before": _blob_identity(before),
                "path": relative,
            }
        )
    diff_bytes = (json.dumps(diff_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    return CloneAfterObservation(
        commit=observation.commit,
        tree=observation.tree,
        index_sha256=observation.index_sha256,
        status_sha256=observation.status_sha256,
        git_control_sha256=observation.git_control_sha256,
        file_inventory_sha256=observation.file_inventory_sha256,
        changed_paths=changed_paths,
        diff_sha256=_sha256_bytes(diff_bytes),
    )


class _WindowsJob:
    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("the bounded executor currently supports Windows only")
        import ctypes
        from ctypes import wintypes

        class _BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [
                ("ReadOperationCount", ctypes.c_ulonglong),
                ("WriteOperationCount", ctypes.c_ulonglong),
                ("OtherOperationCount", ctypes.c_ulonglong),
                ("ReadTransferCount", ctypes.c_ulonglong),
                ("WriteTransferCount", ctypes.c_ulonglong),
                ("OtherTransferCount", ctypes.c_ulonglong),
            ]

        class _ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimit),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class _BasicAccounting(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_longlong),
                ("TotalKernelTime", ctypes.c_longlong),
                ("ThisPeriodTotalUserTime", ctypes.c_longlong),
                ("ThisPeriodTotalKernelTime", ctypes.c_longlong),
                ("TotalPageFaultCount", wintypes.DWORD),
                ("TotalProcesses", wintypes.DWORD),
                ("ActiveProcesses", wintypes.DWORD),
                ("TotalTerminatedProcesses", wintypes.DWORD),
            ]

        self._ctypes = ctypes
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self._kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        self._kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self._kernel32.SetInformationJobObject.restype = wintypes.BOOL
        self._kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self._kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
        self._kernel32.QueryInformationJobObject.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            ctypes.c_void_p,
            wintypes.DWORD,
            ctypes.c_void_p,
        ]
        self._kernel32.QueryInformationJobObject.restype = wintypes.BOOL
        self._kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self._kernel32.TerminateJobObject.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._accounting_type = _BasicAccounting
        self._handle = self._kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        limits = _ExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = 0x00002000
        if not self._kernel32.SetInformationJobObject(
            self._handle,
            9,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            error = ctypes.get_last_error()
            self.close()
            raise OSError(error, "SetInformationJobObject failed")

    def assign(self, process: subprocess.Popen[bytes]) -> None:
        if not self._kernel32.AssignProcessToJobObject(self._handle, int(process._handle)):
            raise OSError(self._ctypes.get_last_error(), "AssignProcessToJobObject failed")

    def counts(self) -> tuple[int, int]:
        accounting = self._accounting_type()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            1,
            self._ctypes.byref(accounting),
            self._ctypes.sizeof(accounting),
            None,
        ):
            raise OSError(self._ctypes.get_last_error(), "QueryInformationJobObject failed")
        return int(accounting.TotalProcesses), int(accounting.ActiveProcesses)

    def terminate(self) -> None:
        if self._handle and not self._kernel32.TerminateJobObject(self._handle, 1):
            raise OSError(self._ctypes.get_last_error(), "TerminateJobObject failed")

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def _resume_suspended_process(process: subprocess.Popen[bytes]) -> None:
    import ctypes
    from ctypes import wintypes

    resume = ctypes.WinDLL("ntdll", use_last_error=True).NtResumeProcess
    resume.argtypes = [wintypes.HANDLE]
    resume.restype = ctypes.c_long
    status = int(resume(wintypes.HANDLE(process._handle)))  # type: ignore[attr-defined]
    if status != 0:
        raise OSError(status, "NtResumeProcess failed")


def run_bounded_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: float,
) -> ProcessObservation:
    if not argv or not all(isinstance(item, str) and item and "\x00" not in item for item in argv):
        raise ValueError("argv must be a nonempty direct argument vector")
    working_directory = cwd.resolve(strict=True)
    if not working_directory.is_dir():
        raise ValueError("cwd must be an existing directory")
    if not isinstance(timeout_seconds, (int, float)) or isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    process_environment: dict[str, str] = {}
    for key, value in environment.items():
        if not isinstance(key, str) or not key or "\x00" in key or "=" in key:
            raise ValueError("environment contains an invalid key")
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("environment contains an invalid value")
        process_environment[key] = value

    if os.name != "nt":
        raise RuntimeError("the bounded executor currently supports Windows only")
    creationflags = (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.CREATE_NO_WINDOW
        | getattr(subprocess, "CREATE_SUSPENDED", 0x00000004)
    )
    job = _WindowsJob()
    started_at = _utc_now()
    try:
        process = subprocess.Popen(
            list(argv),
            cwd=working_directory,
            env=process_environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            creationflags=creationflags,
        )
    except OSError as exc:
        job.close()
        return ProcessObservation(
            start_requested=True,
            pid=None,
            started_at_utc=None,
            ended_at_utc=None,
            exit_code=None,
            timed_out=False,
            cancelled=False,
            error=str(exc),
            descendant_count=0,
            all_descendants_terminated=True,
            stdout=b"",
            stderr=b"",
            stdout_sha256=None,
            stderr_sha256=None,
        )

    timed_out = False
    error: str | None = None
    try:
        job.assign(process)
        _resume_suspended_process(process)
        try:
            stdout, stderr = process.communicate(timeout=float(timeout_seconds))
        except subprocess.TimeoutExpired:
            timed_out = True
            job.terminate()
            stdout, stderr = process.communicate(timeout=10.0)
        total_processes, active_processes = job.counts()
        accounting_deadline = time.monotonic() + 1.0
        while active_processes and process.poll() is not None and time.monotonic() < accounting_deadline:
            time.sleep(0.01)
            total_processes, active_processes = job.counts()
        if active_processes:
            error = "background descendants survived the root process"
            job.terminate()
            process.wait(timeout=10.0)
            _, active_processes = job.counts()
        all_terminated = active_processes == 0
    except Exception:
        try:
            job.terminate()
        finally:
            process.kill()
            process.wait(timeout=10.0)
            job.close()
        raise
    finally:
        job.close()

    return ProcessObservation(
        start_requested=True,
        pid=process.pid,
        started_at_utc=started_at,
        ended_at_utc=_utc_now(),
        exit_code=process.returncode,
        timed_out=timed_out,
        cancelled=False,
        error=error,
        descendant_count=max(0, total_processes - 1),
        all_descendants_terminated=all_terminated,
        stdout=stdout,
        stderr=stderr,
        stdout_sha256=_sha256_bytes(stdout),
        stderr_sha256=_sha256_bytes(stderr),
    )
