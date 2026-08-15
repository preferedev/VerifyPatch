from __future__ import annotations

from pathlib import Path

from verifypatch.engine import run_check
from tests.helpers import commit_all, materialize_fixture


def _prep(tmp_path: Path, name: str) -> tuple[Path, str]:
    repo, _base, mid = materialize_fixture("clean_refactor", tmp_path / name)
    return repo, mid


def _add_extra_line(repo: Path) -> None:
    path = repo / "src" / "mathy.py"
    path.write_text(path.read_text(encoding="utf-8") + "\nEXTRA = 9\n", encoding="utf-8")


def _mathy_lines(report) -> list:
    return [row for row in report.line_evidence if row.path == "src/mathy.py"]


def test_source_dot_does_not_drop_src_files(tmp_path: Path):
    repo, mid = _prep(tmp_path, "srcdot")
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + '\n[tool.coverage.run]\nsource = ["."]\n',
        encoding="utf-8",
    )
    _add_extra_line(repo)
    head = commit_all(repo, "source dot")
    report = run_check(repo, mid, head, pytest_args=[])
    assert _mathy_lines(report)
    assert report.coverage.changed_executable_lines >= 1


def test_source_src_directory(tmp_path: Path):
    repo, mid = _prep(tmp_path, "srcdir")
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + '\n[tool.coverage.run]\nsource = ["src"]\n',
        encoding="utf-8",
    )
    _add_extra_line(repo)
    head = commit_all(repo, "source src")
    report = run_check(repo, mid, head, pytest_args=[])
    assert _mathy_lines(report)
    assert report.coverage.changed_executable_lines >= 1


def test_source_importable_module(tmp_path: Path):
    repo, mid = _prep(tmp_path, "srcmod")
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + '\n[tool.coverage.run]\nsource = ["src.mathy"]\n',
        encoding="utf-8",
    )
    _add_extra_line(repo)
    head = commit_all(repo, "source module")
    report = run_check(repo, mid, head, pytest_args=[])
    assert _mathy_lines(report)
    assert report.coverage.changed_executable_lines >= 1


def test_source_pkgs(tmp_path: Path):
    repo, mid = _prep(tmp_path, "srcpkgs")
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + '\n[tool.coverage.run]\nsource_pkgs = ["src"]\n',
        encoding="utf-8",
    )
    _add_extra_line(repo)
    head = commit_all(repo, "source pkgs")
    report = run_check(repo, mid, head, pytest_args=[])
    assert _mathy_lines(report)
    assert report.coverage.changed_executable_lines >= 1


def test_include_without_source(tmp_path: Path):
    repo, mid = _prep(tmp_path, "include")
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + '\n[tool.coverage.run]\ninclude = ["src/*"]\n',
        encoding="utf-8",
    )
    _add_extra_line(repo)
    head = commit_all(repo, "include only")
    report = run_check(repo, mid, head, pytest_args=[])
    assert _mathy_lines(report)


def test_source_wins_over_include(tmp_path: Path):
    repo, mid = _prep(tmp_path, "srcinc")
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8")
        + '\n[tool.coverage.run]\nsource = ["src"]\ninclude = ["does-not-match/*"]\n',
        encoding="utf-8",
    )
    _add_extra_line(repo)
    head = commit_all(repo, "source plus include")
    report = run_check(repo, mid, head, pytest_args=[])
    assert _mathy_lines(report)
    assert report.coverage.changed_executable_lines >= 1


def test_relative_and_wildcard_omit(tmp_path: Path):
    repo, mid = _prep(tmp_path, "omitwild")
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8") + '\n[tool.coverage.run]\nomit = ["*/skipped.py"]\n',
        encoding="utf-8",
    )
    (repo / "src" / "skipped.py").write_text("VALUE = 1\n", encoding="utf-8")
    _add_extra_line(repo)
    head = commit_all(repo, "omit wild")
    report = run_check(repo, mid, head, pytest_args=[])
    assert all(row.path != "src/skipped.py" for row in report.line_evidence)
    assert _mathy_lines(report)


def test_absolute_omit(tmp_path: Path):
    repo, mid = _prep(tmp_path, "omitabs")
    skipped = repo / "src" / "skipped.py"
    skipped.write_text("VALUE = 1\n", encoding="utf-8")
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8")
        + f'\n[tool.coverage.run]\nomit = ["{skipped.resolve().as_posix()}"]\n',
        encoding="utf-8",
    )
    _add_extra_line(repo)
    head = commit_all(repo, "omit abs")
    report = run_check(repo, mid, head, pytest_args=[])
    assert all(row.path != "src/skipped.py" for row in report.line_evidence)
    assert _mathy_lines(report)


def test_coveragerc_source(tmp_path: Path):
    repo, mid = _prep(tmp_path, "rcfile")
    (repo / ".coveragerc").write_text("[run]\nsource = src\n", encoding="utf-8")
    _add_extra_line(repo)
    head = commit_all(repo, "coveragerc")
    report = run_check(repo, mid, head, pytest_args=[])
    assert _mathy_lines(report)


def test_setup_cfg_coverage(tmp_path: Path):
    repo, mid = _prep(tmp_path, "setupcfg")
    (repo / "setup.cfg").write_text("[coverage:run]\nsource = src\n", encoding="utf-8")
    _add_extra_line(repo)
    head = commit_all(repo, "setup.cfg")
    report = run_check(repo, mid, head, pytest_args=[])
    assert _mathy_lines(report)


def test_custom_exclude_lines(tmp_path: Path):
    repo, mid = _prep(tmp_path, "excludelines")
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8")
        + "\n[tool.coverage.report]\nexclude_lines = [\"pragma: no cover\", \"TYPE_CHECKING\"]\n",
        encoding="utf-8",
    )
    path = repo / "src" / "mathy.py"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nKEEP = 1\nSKIP = 2  # TYPE_CHECKING\n",
        encoding="utf-8",
    )
    head = commit_all(repo, "exclude_lines")
    report = run_check(repo, mid, head, pytest_args=[])
    lines = {row.line for row in _mathy_lines(report)}
    keep = skip = None
    for index, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if text.startswith("KEEP"):
            keep = index
        if text.startswith("SKIP"):
            skip = index
    assert keep in lines
    assert skip not in lines


def test_exclude_also_and_custom_exclude_lines(tmp_path: Path):
    repo, mid = _prep(tmp_path, "exclude")
    pyproject = repo / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8")
        + "\n[tool.coverage.report]\nexclude_also = [\"omit_me\"]\n",
        encoding="utf-8",
    )
    path = repo / "src" / "mathy.py"
    path.write_text(
        path.read_text(encoding="utf-8") + "\nKEEP = 1\nomit_me = 2  # omit_me\n",
        encoding="utf-8",
    )
    head = commit_all(repo, "exclude_also")
    report = run_check(repo, mid, head, pytest_args=[])
    lines = {row.line: row for row in _mathy_lines(report)}
    keep = None
    for index, text in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if text.startswith("KEEP"):
            keep = index
        if "omit_me = 2" in text:
            assert index not in lines
    assert keep in lines
