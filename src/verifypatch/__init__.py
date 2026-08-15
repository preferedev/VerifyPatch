"""VerifyPatch: evidence provenance for Python/pytest pull requests.

PYTEST_DONT_REWRITE
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("verifypatch")
except PackageNotFoundError:
    __version__ = "0.2.0"

SCHEMA_VERSION = "1"

__all__ = ["SCHEMA_VERSION", "__version__"]
