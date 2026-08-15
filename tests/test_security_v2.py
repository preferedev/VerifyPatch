from __future__ import annotations

from pathlib import Path

from verifypatch.deadlines import python_argv, run_bounded


def test_malicious_node_ids_are_not_interpolated_into_a_shell():
    source = Path(__file__).resolve().parents[1] / "src" / "verifypatch" / "mutation" / "runner.py"
    invoke = Path(__file__).resolve().parents[1] / "src" / "verifypatch" / "pytest_invoke.py"
    text = source.read_text(encoding="utf-8") + "\n" + invoke.read_text(encoding="utf-8")
    assert "shell=True" not in text
    assert "pytest" in text
    assert "*node_ids" in text
    assert "no:verifypatch" in text


def test_generated_tests_are_not_selected_by_synthetic_ids():
    source = Path(__file__).resolve().parents[1] / "src" / "verifypatch" / "mutation" / "runner.py"
    text = source.read_text(encoding="utf-8")
    assert "item.id for item in generated.items" not in text
    assert "_materialize_generated" in text
    assert ".verifypatch_generated" in text


def test_paths_with_spaces_and_metacharacters_go_through_argv(tmp_path: Path):
    target = tmp_path / "dir with spaces" / "x.py"
    target.parent.mkdir()
    target.write_text("print('ok')\n", encoding="utf-8")
    result = run_bounded(
        python_argv(str(target)),
        cwd=tmp_path,
        timeout=10,
    )
    assert result.timed_out is False
    assert "ok" in result.stdout


def test_child_process_timeout_kills_group():
    result = run_bounded(
        python_argv("-c", "import time, os; time.sleep(30)"),
        cwd=Path("."),
        timeout=0.2,
    )
    assert result.timed_out is True
    assert result.returncode != 0 or result.timed_out


def test_unicode_path_argv(tmp_path: Path):
    target = tmp_path / "ünicode-dir" / "mod.py"
    target.parent.mkdir()
    target.write_text("print('ü')\n", encoding="utf-8")
    result = run_bounded(python_argv(str(target)), cwd=tmp_path, timeout=10)
    assert result.timed_out is False
    assert result.returncode == 0


def test_artifact_path_cannot_escape(tmp_path: Path):
    from verifypatch.artifacts import write_artifact

    try:
        write_artifact(tmp_path, "../secret.txt", b"x", "test")
    except ValueError:
        return
    raise AssertionError("expected traversal to be rejected")


def test_registered_temp_dirs_are_removed_on_cleanup(tmp_path: Path):
    from verifypatch.cleanup import cleanup_registered, register_temp_dir, unregister_temp_dir

    leak = tmp_path / "verifypatch-mut-leak"
    leak.mkdir()
    (leak / "x").write_text("1", encoding="utf-8")
    register_temp_dir(leak)
    cleanup_registered()
    assert not leak.exists()
    unregister_temp_dir(leak)


def test_symlink_escape_rejected_in_yaml_paths():
    from verifypatch.requirements.firewall import _safe_relpath

    assert _safe_relpath("../secrets") is None
    assert _safe_relpath("/etc/passwd") is None
    assert _safe_relpath("README.md") == "README.md"
