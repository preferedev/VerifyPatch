from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tests_helpers_is_importable_as_package():
    import tests.helpers as helpers

    assert callable(helpers.materialize_fixture)
    assert callable(helpers.normalize_report)
    assert callable(helpers.commit_all)


def test_tests_helpers_importable_without_cwd_on_sys_path():
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "sys.path[:] = [p for p in sys.path if p not in ('', '.')]; "
            f"sys.path.insert(0, {str(ROOT)!r}); "
            f"sys.path.insert(0, {str(ROOT / 'src')!r}); "
            "from tests.helpers import materialize_fixture; "
            "assert callable(materialize_fixture)",
        ],
        cwd="/",
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
