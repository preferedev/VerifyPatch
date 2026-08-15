from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from verifypatch.errors import AnalysisError
from verifypatch.limits import MAX_OUTPUT_BYTES


def monotonic_now() -> float:
    return time.monotonic()


@dataclass
class Deadline:
    """Monotonic wall-clock budget shared by optional v2 stages."""

    started: float
    total_seconds: float

    def remaining(self) -> float:
        left = self.total_seconds - (monotonic_now() - self.started)
        return left if left > 0 else 0.0

    def expired(self) -> bool:
        return self.remaining() <= 0

    def clamp(self, stage_seconds: int) -> float:
        return min(float(stage_seconds), self.remaining())


def start_deadline(total_seconds: int) -> Deadline:
    return Deadline(started=monotonic_now(), total_seconds=float(total_seconds))


@dataclass
class BoundedProcessResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    truncated: bool = False
    duration_seconds: float = 0.0


def _kill_process_group(proc: subprocess.Popen) -> None:
    from verifypatch.cleanup import terminate_process_group

    terminate_process_group(proc.pid)
    if proc.poll() is None:
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except (ProcessLookupError, OSError):
                return


def _preexec() -> None:
    if os.name == "posix":
        os.setsid()


def _clip(text: str, limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="replace"), True


def run_bounded(
    argv: list[str],
    *,
    cwd: Path,
    timeout: float,
    env: Mapping[str, str] | None = None,
    input_text: str | None = None,
    output_limit: int = MAX_OUTPUT_BYTES,
) -> BoundedProcessResult:
    """Run argv with shell=False, a process-group timeout, and bounded output."""
    from verifypatch.cleanup import register_process_group, unregister_process_group

    if timeout <= 0:
        raise AnalysisError("subprocess timeout is exhausted")
    started = monotonic_now()
    popen_kwargs: dict = {
        "cwd": str(cwd),
        "env": dict(env) if env is not None else None,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "start_new_session": os.name == "posix",
    }
    if input_text is not None:
        popen_kwargs["stdin"] = subprocess.PIPE
    proc = subprocess.Popen(argv, **popen_kwargs)
    register_process_group(proc.pid)
    timed_out = False
    try:
        try:
            stdout, stderr = proc.communicate(input=input_text, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_group(proc)
            stdout, stderr = proc.communicate()
        except (KeyboardInterrupt, SystemExit):
            _kill_process_group(proc)
            raise
    finally:
        unregister_process_group(proc.pid)
    stdout, trunc_out = _clip(stdout or "", output_limit)
    stderr, trunc_err = _clip(stderr or "", output_limit)
    return BoundedProcessResult(
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        truncated=trunc_out or trunc_err,
        duration_seconds=monotonic_now() - started,
    )


def python_argv(*args: str) -> list[str]:
    return [sys.executable, *args]
