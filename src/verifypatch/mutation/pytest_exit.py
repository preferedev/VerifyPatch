from __future__ import annotations

from typing import Literal

PytestPartitionOutcome = Literal["survived", "killed", "error", "no_tests", "timeout", "interrupted"]

PYTEST_OK = 0
PYTEST_TESTS_FAILED = 1
PYTEST_INTERRUPTED = 2
PYTEST_INTERNAL_ERROR = 3
PYTEST_USAGE_ERROR = 4
PYTEST_NO_TESTS = 5


def classify_pytest_exit(returncode: int | None, timed_out: bool) -> PytestPartitionOutcome:
    """Map pytest's process status to a mutation partition outcome.

    Only an actual test failure (exit 1) is evidence that a mutant was killed.
    """
    if timed_out:
        return "timeout"
    if returncode == PYTEST_OK:
        return "survived"
    if returncode == PYTEST_TESTS_FAILED:
        return "killed"
    if returncode == PYTEST_INTERRUPTED:
        return "interrupted"
    if returncode == PYTEST_NO_TESTS:
        return "no_tests"
    return "error"
