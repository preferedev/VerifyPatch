import atexit
import os
import shutil
import signal
import time
from pathlib import Path

from verifypatch.limits import PROCESS_KILL_GRACE_SECONDS

_TEMP_DIRS: list[Path] = []
_WORKTREES: list[tuple[Path, Path]] = []
_PROCESS_GROUPS: list[int] = []
_INSTALLED = False


def register_temp_dir(path: Path) -> Path:
    _TEMP_DIRS.append(path)
    return path


def unregister_temp_dir(path: Path) -> None:
    try:
        _TEMP_DIRS.remove(path)
    except ValueError:
        return


def register_worktree(root: Path, dest: Path) -> Path:
    _WORKTREES.append((root, dest))
    return dest


def unregister_worktree(dest: Path) -> None:
    _WORKTREES[:] = [(root, path) for root, path in _WORKTREES if path != dest]


def register_process_group(pid: int) -> int:
    _PROCESS_GROUPS.append(pid)
    return pid


def unregister_process_group(pid: int) -> None:
    try:
        _PROCESS_GROUPS.remove(pid)
    except ValueError:
        return


def terminate_process_group(pid: int) -> None:
    """SIGTERM the process group, wait the grace period, then SIGKILL remaining members.

    Always escalate after the grace period so descendants that ignore SIGTERM are removed
    even if the session leader has already exited.
    """
    def _send(sig: int) -> None:
        try:
            if os.name == "posix":
                os.killpg(pid, sig)
            else:
                os.kill(pid, sig)
        except (ProcessLookupError, OSError, PermissionError):
            if os.name == "posix":
                try:
                    os.kill(pid, sig)
                except (ProcessLookupError, OSError, PermissionError):
                    return

    term = getattr(signal, "SIGTERM", signal.SIGTERM)
    kill = getattr(signal, "SIGKILL", getattr(signal, "SIGTERM", signal.SIGTERM))
    _send(term)
    deadline = time.monotonic() + PROCESS_KILL_GRACE_SECONDS
    while time.monotonic() < deadline:
        time.sleep(0.05)
    _send(kill)


def kill_registered_process_groups() -> None:
    for pid in list(_PROCESS_GROUPS):
        terminate_process_group(pid)
    _PROCESS_GROUPS.clear()


def cleanup_registered() -> None:
    from verifypatch.gitops import remove_worktree

    kill_registered_process_groups()
    for root, dest in list(_WORKTREES):
        try:
            remove_worktree(root, dest)
        except Exception:
            shutil.rmtree(dest, ignore_errors=True)
    _WORKTREES.clear()
    for path in list(_TEMP_DIRS):
        shutil.rmtree(path, ignore_errors=True)
    _TEMP_DIRS.clear()


def install_cleanup_handlers() -> None:
    """Ensure SIGTERM and interpreter exit remove child processes and temp worktrees."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True
    atexit.register(cleanup_registered)

    def _handle(signum: int, _frame: object) -> None:
        cleanup_registered()
        raise SystemExit(128 + int(signum))

    if os.name == "posix":
        signal.signal(signal.SIGTERM, _handle)
