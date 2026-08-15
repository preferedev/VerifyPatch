from __future__ import annotations

import posixpath
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from verifypatch.errors import AnalysisError


@dataclass
class FileDiff:
    path: str
    status: str
    old_path: str | None = None
    added_lines: set[int] = field(default_factory=set)
    deleted_line_count: int = 0


@dataclass
class GitDiff:
    merge_base: str
    head: str
    files: list[FileDiff]

    def by_path(self) -> dict[str, FileDiff]:
        return {item.path: item for item in self.files}


def run_git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise AnalysisError(f"git {' '.join(args)} failed: {message}")
    return result.stdout


def resolve_sha(root: Path, ref: str) -> str:
    sha = run_git(root, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    if len(sha) != 40:
        raise AnalysisError(f"could not resolve {ref!r} to an immutable commit SHA")
    return sha


def worktree_head(root: Path) -> str:
    return resolve_sha(root, "HEAD")


def merge_base_sha(root: Path, base: str, head: str) -> str:
    return run_git(root, "merge-base", base, head).strip()


def tracked_dirty(root: Path) -> bool:
    output = run_git(root, "status", "--porcelain")
    for line in output.splitlines():
        if not line:
            continue
        code = line[:2]
        if code.strip() and not code.startswith("?"):
            return True
    return False


def posix_relpath(path: str) -> str:
    return posixpath.normpath(path.replace("\\", "/"))


def parse_numstat_and_diff(root: Path, merge_base: str, head: str) -> list[FileDiff]:
    name_status = run_git(
        root,
        "diff",
        "--find-renames",
        "--name-status",
        f"{merge_base}...{head}",
    )
    unified = run_git(
        root,
        "diff",
        "--find-renames",
        "-U0",
        "--no-ext-diff",
        f"{merge_base}...{head}",
    )
    files: dict[str, FileDiff] = {}
    for line in name_status.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0][0]
        if status == "R":
            old_path = posix_relpath(parts[1])
            new_path = posix_relpath(parts[2])
            files[new_path] = FileDiff(path=new_path, status="renamed", old_path=old_path)
        elif status == "A":
            path = posix_relpath(parts[1])
            files[path] = FileDiff(path=path, status="added")
        elif status == "D":
            path = posix_relpath(parts[1])
            files[path] = FileDiff(path=path, status="deleted")
        else:
            path = posix_relpath(parts[1])
            files[path] = FileDiff(path=path, status="modified")

    _apply_added_line_numbers(unified, files)
    _apply_deleted_counts(unified, files)
    return list(files.values())


def _apply_added_line_numbers(unified: str, files: dict[str, FileDiff]) -> None:
    current: FileDiff | None = None
    next_line = 0
    for line in unified.splitlines():
        if line.startswith("+++ "):
            raw = line[4:]
            current = None
            if raw == "/dev/null":
                continue
            if raw.startswith("b/"):
                raw = raw[2:]
            current = files.get(posix_relpath(raw))
            continue
        if current is None:
            continue
        if line.startswith("@@"):
            plus = line.split(" ")[2]
            start = plus[1:]
            start_n, _, _count = start.partition(",")
            next_line = int(start_n)
            if next_line == 0:
                next_line = 1
            continue
        if line.startswith("+"):
            current.added_lines.add(next_line)
            next_line += 1
        elif line.startswith("-"):
            continue
        else:
            next_line += 1


def _apply_deleted_counts(unified: str, files: dict[str, FileDiff]) -> None:
    current: FileDiff | None = None
    for line in unified.splitlines():
        if line.startswith("--- "):
            raw = line[4:]
            current = None
            if raw == "/dev/null":
                continue
            if raw.startswith("a/"):
                raw = raw[2:]
            path = posix_relpath(raw)
            current = files.get(path)
            if current is None:
                for item in files.values():
                    if item.old_path == path:
                        current = item
                        break
            continue
        if current is None:
            continue
        if line.startswith("-") and not line.startswith("---"):
            current.deleted_line_count += 1


def collect_diff(root: Path, merge_base: str, head: str) -> GitDiff:
    files = parse_numstat_and_diff(root, merge_base, head)
    return GitDiff(merge_base=merge_base, head=head, files=files)


def git_show(root: Path, sha: str, path: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{sha}:{path}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout


def git_ls_tree(root: Path, sha: str) -> list[str]:
    output = run_git(root, "ls-tree", "-r", "--name-only", sha)
    return [posix_relpath(line) for line in output.splitlines() if line.strip()]


def add_worktree(root: Path, dest: Path, sha: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run_git(root, "worktree", "add", "--detach", str(dest), sha)
    return dest


def remove_worktree(root: Path, dest: Path) -> None:
    if dest.exists():
        try:
            run_git(root, "worktree", "remove", "--force", str(dest))
        except AnalysisError:
            shutil.rmtree(dest, ignore_errors=True)
            try:
                run_git(root, "worktree", "prune")
            except AnalysisError:
                pass
