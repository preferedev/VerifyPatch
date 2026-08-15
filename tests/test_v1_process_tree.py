from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from verifypatch.coverage_run import run_pytest_coverage
from verifypatch.errors import AnalysisError
from verifypatch.limits import MAX_OUTPUT_BYTES, PROCESS_KILL_GRACE_SECONDS
from tests.helpers import commit_all, materialize_fixture, run_git


def _alive(pid: int) -> bool:
    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "pid="],
        capture_output=True,
        text=True,
    )
    return str(pid) in (completed.stdout or "")


def _write_sleep_tree(repo: Path, pid_dir: Path, ignore_term: bool) -> None:
    ignore_line = "signal.signal(signal.SIGTERM, signal.SIG_IGN)" if ignore_term else "pass"
    (repo / "tests" / "test_spawn_tree.py").write_text(
        "\n".join(
            [
                "import os",
                "import signal",
                "import subprocess",
                "import sys",
                "import time",
                "from pathlib import Path",
                "",
                "def test_spawn_tree():",
                "    pid_dir = Path(os.environ['VERIFYPATCH_PID_DIR'])",
                "    child_code = (",
                "        'import os, signal, time\\n'",
                "        'from pathlib import Path\\n'",
                f"        {ignore_line!r} + '\\n'",
                "        'Path(os.environ[\"VERIFYPATCH_PID_DIR\"], \"grandchild.pid\").write_text(str(os.getpid()), encoding=\"utf-8\")\\n'",
                "        'time.sleep(60)\\n'",
                "    )",
                "    child = subprocess.Popen([sys.executable, '-c', child_code], env=os.environ.copy())",
                "    (pid_dir / 'child.pid').write_text(str(child.pid), encoding='utf-8')",
                "    time.sleep(60)",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _read_pids(pid_dir: Path) -> tuple[int, int]:
    child = int((pid_dir / "child.pid").read_text(encoding="utf-8").strip())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not (pid_dir / "grandchild.pid").is_file():
        time.sleep(0.05)
    grandchild = int((pid_dir / "grandchild.pid").read_text(encoding="utf-8").strip())
    return child, grandchild


def test_timeout_kills_child_and_grandchild(tmp_path: Path):
    repo, base, _head = materialize_fixture("clean_refactor", tmp_path / "repo")
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    _write_sleep_tree(repo, pid_dir, ignore_term=False)
    head = commit_all(repo, "spawn tree")
    assert run_git(repo, "rev-parse", "HEAD") == head
    env_pid = os.environ.get("VERIFYPATCH_PID_DIR")
    os.environ["VERIFYPATCH_PID_DIR"] = str(pid_dir)
    before = run_git(repo, "status", "--porcelain", "-uno")
    work = tmp_path / "work"
    try:
        with pytest.raises(AnalysisError, match="timeout"):
            run_pytest_coverage(repo, ["-k", "test_spawn_tree"], timeout=1, work_dir=work)
        time.sleep(PROCESS_KILL_GRACE_SECONDS + 0.3)
        child, grandchild = _read_pids(pid_dir)
        assert not _alive(child)
        assert not _alive(grandchild)
    finally:
        if env_pid is None:
            os.environ.pop("VERIFYPATCH_PID_DIR", None)
        else:
            os.environ["VERIFYPATCH_PID_DIR"] = env_pid
    after = run_git(repo, "status", "--porcelain", "-uno")
    assert after == before


def test_timeout_kills_sigterm_ignoring_grandchild(tmp_path: Path):
    repo, base, _head = materialize_fixture("clean_refactor", tmp_path / "repo")
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    _write_sleep_tree(repo, pid_dir, ignore_term=True)
    commit_all(repo, "ignore term")
    os.environ["VERIFYPATCH_PID_DIR"] = str(pid_dir)
    work = tmp_path / "work"
    try:
        with pytest.raises(AnalysisError, match="timeout"):
            run_pytest_coverage(repo, ["-k", "test_spawn_tree"], timeout=1, work_dir=work)
        time.sleep(0.2)
        child, grandchild = _read_pids(pid_dir)
        assert not _alive(child)
        assert not _alive(grandchild)
    finally:
        os.environ.pop("VERIFYPATCH_PID_DIR", None)


def test_output_beyond_limit_is_truncated(tmp_path: Path):
    from verifypatch.deadlines import python_argv, run_bounded

    huge = MAX_OUTPUT_BYTES + 50_000
    result = run_bounded(
        python_argv("-c", f"print('A' * {huge})"),
        cwd=tmp_path,
        timeout=10,
    )
    assert result.truncated is True
    assert len(result.stdout.encode("utf-8")) <= MAX_OUTPUT_BYTES


def test_sigterm_of_verifypatch_kills_descendants_without_success_report(tmp_path: Path):
    repo, base, _head = materialize_fixture("clean_refactor", tmp_path / "repo")
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    _write_sleep_tree(repo, pid_dir, ignore_term=True)
    head = commit_all(repo, "sigterm tree")
    json_out = tmp_path / "out.json"
    md_out = tmp_path / "out.md"
    env = os.environ.copy()
    env["VERIFYPATCH_PID_DIR"] = str(pid_dir)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src") + os.pathsep + env.get(
        "PYTHONPATH", ""
    )
    before = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "-uno"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "verifypatch",
            "check",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--timeout",
            "30",
            "--json-out",
            str(json_out),
            "--md-out",
            str(md_out),
        ],
        cwd=str(repo),
        env=env,
        start_new_session=True,
    )
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline and not (pid_dir / "grandchild.pid").is_file():
        if proc.poll() is not None:
            break
        time.sleep(0.05)
    assert proc.poll() is None
    os.kill(proc.pid, signal.SIGTERM)
    try:
        proc.wait(timeout=PROCESS_KILL_GRACE_SECONDS + 8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
        raise AssertionError("VerifyPatch did not exit after SIGTERM")
    time.sleep(0.3)
    if (pid_dir / "child.pid").is_file():
        child, grandchild = _read_pids(pid_dir)
        assert not _alive(child)
        assert not _alive(grandchild)
    after = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "-uno"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert after == before
    if json_out.is_file():
        payload = json_out.read_text(encoding="utf-8")
        assert '"status": "complete"' not in payload
    assert proc.returncode not in {0}
