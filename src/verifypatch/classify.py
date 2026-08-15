from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from verifypatch.config import VerifyPatchConfig
from verifypatch.gitops import FileDiff, posix_relpath


TEST_FILE_PREFIX = "test_"
TEST_FILE_SUFFIX = "_test.py"


@dataclass
class PathClass:
    path: str
    kind: str  # production | test_file | conftest | shared_test_helper | other


def path_parts(path: str) -> list[str]:
    return [part for part in posix_relpath(path).split("/") if part and part != "."]


def under_directory(path: str, directory: str) -> bool:
    norm = posix_relpath(path)
    root = posix_relpath(directory).rstrip("/")
    if root in {".", ""}:
        return True
    return norm == root or norm.startswith(root + "/")


def is_python_file(path: str) -> bool:
    return posix_relpath(path).endswith(".py")


def is_conftest(path: str) -> bool:
    return Path(posix_relpath(path)).name == "conftest.py"


def matches_test_filename(path: str) -> bool:
    name = Path(posix_relpath(path)).name
    return name.startswith(TEST_FILE_PREFIX) and name.endswith(".py") or name.endswith(
        TEST_FILE_SUFFIX
    )


def under_tests_dir(path: str) -> bool:
    return "tests" in path_parts(path)[:-1]


def under_configured_test_root(path: str, config: VerifyPatchConfig) -> bool:
    return any(under_directory(path, root) for root in config.test_paths)


def matches_test_glob(path: str, config: VerifyPatchConfig) -> bool:
    return any(fnmatch.fnmatch(posix_relpath(path), pattern) for pattern in config.test_globs)


def is_test_infrastructure(path: str, config: VerifyPatchConfig) -> bool:
    if not is_python_file(path):
        return False
    return (
        is_conftest(path)
        or matches_test_filename(path)
        or under_tests_dir(path)
        or under_configured_test_root(path, config)
        or matches_test_glob(path, config)
    )


def classify_path(path: str, config: VerifyPatchConfig) -> PathClass:
    path = posix_relpath(path)
    if not is_python_file(path):
        return PathClass(path=path, kind="other")
    if is_conftest(path):
        return PathClass(path=path, kind="conftest")
    if matches_test_filename(path) or matches_test_glob(path, config):
        return PathClass(path=path, kind="test_file")
    if under_tests_dir(path) or under_configured_test_root(path, config):
        if matches_test_filename(path):
            return PathClass(path=path, kind="test_file")
        return PathClass(path=path, kind="shared_test_helper")
    return PathClass(path=path, kind="production")


def classify_diffs(files: list[FileDiff], config: VerifyPatchConfig) -> dict[str, PathClass]:
    return {item.path: classify_path(item.path, config) for item in files}


def ancestor_conftest_paths(test_file: str, pytest_root: str = ".") -> list[str]:
    """conftest.py files that apply to a test file by directory scope."""
    path = posix_relpath(test_file)
    parts = path_parts(path)
    directories = []
    acc: list[str] = []
    for part in parts[:-1]:
        acc.append(part)
        directories.append("/".join(acc))
    if pytest_root not in {".", ""}:
        directories = [d for d in directories if under_directory(d, pytest_root)]
    return [f"{directory}/conftest.py" for directory in directories] + (
        ["conftest.py"] if pytest_root in {".", ""} and "conftest.py" not in [
            f"{d}/conftest.py" for d in directories
        ]
        else []
    )
