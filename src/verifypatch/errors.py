from __future__ import annotations


class VerifyPatchError(Exception):
    """Base error."""


class AnalysisError(VerifyPatchError):
    """Fatal analysis failure; CLI exits 2."""


class UnsupportedError(VerifyPatchError):
    """Unsupported required condition; CLI exits 2."""
