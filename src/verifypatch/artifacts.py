from __future__ import annotations

import hashlib
import json
from pathlib import Path

from verifypatch.stage import ArtifactRef


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_artifact(directory: Path, relative: str, data: bytes, kind: str) -> ArtifactRef:
    normalized = relative.replace("\\", "/")
    if Path(normalized).is_absolute() or ".." in Path(normalized).parts:
        raise ValueError("artifact path escapes the artifacts directory")
    path = directory / normalized
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    digest = sha256_bytes(data)
    return ArtifactRef(
        path=relative.replace("\\", "/"),
        sha256=digest,
        kind=kind,
        bytes=len(data),
    )


def write_json_artifact(directory: Path, relative: str, payload: dict, kind: str) -> ArtifactRef:
    encoded = (json.dumps(payload, indent=2) + "\n").encode("utf-8")
    return write_artifact(directory, relative, encoded, kind)


def artifact_manifest(directory: str, items: list[ArtifactRef]) -> dict:
    return {
        "directory": directory,
        "items": [
            {
                "path": item.path,
                "sha256": item.sha256,
                "kind": item.kind,
                "bytes": item.bytes,
            }
            for item in items
        ],
    }
