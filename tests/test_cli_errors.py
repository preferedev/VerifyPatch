from __future__ import annotations

import os
from pathlib import Path

import pytest

from verifypatch.cli import main
from verifypatch.errors import UnsupportedError
from verifypatch.xdist import reject_xdist
from tests.helpers import materialize_fixture


def test_xdist_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYTEST_ADDOPTS", "-n auto")
    with pytest.raises(UnsupportedError):
        reject_xdist(tmp_path, [])


def test_xdist_from_pytest_ini(tmp_path: Path):
    (tmp_path / "pytest.ini").write_text("[pytest]\naddopts = --numprocesses auto\n", encoding="utf-8")
    with pytest.raises(UnsupportedError):
        reject_xdist(tmp_path, [])


def test_xdist_from_tox_ini(tmp_path: Path):
    (tmp_path / "tox.ini").write_text("[pytest]\naddopts = --dist=load\n", encoding="utf-8")
    with pytest.raises(UnsupportedError):
        reject_xdist(tmp_path, [])


def test_xdist_from_setup_cfg(tmp_path: Path):
    (tmp_path / "setup.cfg").write_text("[tool:pytest]\naddopts = -n8\n", encoding="utf-8")
    with pytest.raises(UnsupportedError):
        reject_xdist(tmp_path, [])


def test_xdist_from_pyproject(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\naddopts = '-nauto'\n",
        encoding="utf-8",
    )
    with pytest.raises(UnsupportedError):
        reject_xdist(tmp_path, [])


def test_disabled_xdist_forms_allowed(tmp_path: Path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n", encoding="utf-8")
    reject_xdist(tmp_path, ["-n", "0"])
    reject_xdist(tmp_path, ["--dist=no"])
    reject_xdist(tmp_path, ["--numprocesses=0"])


def test_cli_invalid_ref_exits_2(tmp_path: Path):
    repo, _base, _head = materialize_fixture("clean_refactor", tmp_path / "repo")
    code = main(
        [
            "check",
            "--base",
            "does-not-exist",
            "--head",
            "HEAD",
            "--root",
            str(repo),
            "--json-out",
            str(tmp_path / "a.json"),
            "--md-out",
            str(tmp_path / "a.md"),
        ]
    )
    assert code == 2


def test_cli_dirty_worktree_exits_2(tmp_path: Path):
    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "dirty")
    (repo / "src" / "mathy.py").write_text("changed = True\n", encoding="utf-8")
    code = main(
        [
            "check",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--json-out",
            str(tmp_path / "d.json"),
            "--md-out",
            str(tmp_path / "d.md"),
        ]
    )
    assert code == 2


def test_cli_head_mismatch_exits_2(tmp_path: Path):
    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "mis")
    code = main(
        [
            "check",
            "--base",
            base,
            "--head",
            base,
            "--root",
            str(repo),
            "--json-out",
            str(tmp_path / "m.json"),
            "--md-out",
            str(tmp_path / "m.md"),
        ]
    )
    assert code == 2


def test_cli_timeout_exits_2(tmp_path: Path):
    repo, base, _head = materialize_fixture("clean_refactor", tmp_path / "slow")
    (repo / "tests" / "test_sleep.py").write_text(
        "import time\n\ndef test_sleep():\n    time.sleep(30)\n",
        encoding="utf-8",
    )
    import subprocess
    from tests.helpers import commit_all

    head = commit_all(repo, "sleep")
    code = main(
        [
            "check",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--timeout",
            "1",
            "--json-out",
            str(tmp_path / "t.json"),
            "--md-out",
            str(tmp_path / "t.md"),
        ]
    )
    assert code == 2


def test_cli_paths_with_spaces(tmp_path: Path):
    repo, base, head = materialize_fixture("clean_refactor", tmp_path / "space repo")
    outdir = tmp_path / "out dir"
    code = main(
        [
            "check",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--json-out",
            str(outdir / "report.json"),
            "--md-out",
            str(outdir / "report.md"),
        ]
    )
    assert code == 0
    assert (outdir / "report.json").is_file()
    assert (outdir / "report.md").is_file()


def test_failing_pytest_does_not_change_verifypatch_exit(tmp_path: Path):
    repo, base, _head = materialize_fixture("clean_refactor", tmp_path / "failci")
    (repo / "tests" / "test_fail.py").write_text("def test_fail():\n    assert False\n", encoding="utf-8")
    from tests.helpers import commit_all

    head = commit_all(repo, "fail")
    json_out = tmp_path / "f.json"
    code = main(
        [
            "check",
            "--base",
            base,
            "--head",
            head,
            "--root",
            str(repo),
            "--json-out",
            str(json_out),
            "--md-out",
            str(tmp_path / "f.md"),
        ]
    )
    assert code == 0
    payload = __import__("json").loads(json_out.read_text(encoding="utf-8"))
    assert payload["tests"]["pytest_exit_code"] != 0
    assert payload["status"] in {"complete", "incomplete"}
