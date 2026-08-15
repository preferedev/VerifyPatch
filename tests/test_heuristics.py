from __future__ import annotations

from verifypatch.heuristics import analyze_test_file
from verifypatch.model import WarningRecord


BASE = '''
def test_ok():
    assert value() == 5

def test_skip_me():
    assert True

def test_broad():
    assert True

def test_gone():
    assert True
'''

HEAD = '''
import pytest

@pytest.mark.skip("nope")
def test_ok():
    assert value()

@pytest.mark.xfail
def test_skip_me():
    assert True

def test_broad():
    try:
        boom()
    except Exception:
        pass
'''


def test_finding_codes():
    warnings: list[WarningRecord] = []
    findings = analyze_test_file("tests/test_mod.py", BASE, HEAD, warnings)
    codes = {item.id for item in findings}
    assert "TEST_SKIP_ADDED" in codes
    assert "TEST_XFAIL_ADDED" in codes
    assert "BROAD_EXCEPT_ADDED" in codes
    assert "ASSERT_TO_TRUTHY" in codes
    assert "TEST_REMOVED" in codes
    assert "ASSERT_COUNT_DROP" in codes
    review = [item for item in findings if item.severity == "review"]
    notice = [item for item in findings if item.severity == "notice"]
    assert review
    assert notice
    assert not warnings


def test_syntax_error_warns_without_findings():
    warnings: list[WarningRecord] = []
    findings = analyze_test_file("tests/bad.py", "def test_ok(:\n", "def test_ok():\n    assert True\n", warnings)
    assert findings == []
    assert warnings
