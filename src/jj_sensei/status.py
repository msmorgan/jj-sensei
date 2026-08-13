"""Compact, agent-oriented status for one Jujutsu workspace."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from .jj import Jj, JjError
from .repair import LockTimeout, WorkspaceLock

_INSERTIONS = re.compile(r"(\d+) insertion")
_DELETIONS = re.compile(r"(\d+) deletion")
_BOOKMARKS_TEMPLATE = 'bookmarks.map(|bookmark| bookmark.name()).join(",")'


@dataclass(frozen=True)
class Status:
    root: Path
    line: str


def render_status(cwd: Path | str | None = None) -> Status | None:
    """Snapshot and render a workspace, or stay silent if it cannot be probed safely."""
    jj = Jj(cwd)
    try:
        root = jj.workspace_root()
        with WorkspaceLock(root, timeout=0.25):
            return _render_locked(jj, root)
    except (JjError, LockTimeout, OSError, RuntimeError, ValueError):
        return None


def _render_locked(jj: Jj, root: Path) -> Status:
    workspace = jj.current_workspace()

    # This is the intentional write: status hooks run after mutating tools so
    # their filesystem edits become a jj snapshot promptly. Every later query
    # ignores the working copy and reads that one coherent snapshot.
    snapshot = jj.run("st", check=False)
    if snapshot.returncode:
        diagnostic = f"{snapshot.stdout}\n{snapshot.stderr}".lower()
        if "stale" in diagnostic:
            return Status(
                root,
                f"jj: {workspace.name} | ⚠ STALE working copy — use harmony before "
                "trusting anything here",
            )
        return Status(root, f"jj: {workspace.name} | ⚠ jj could not read this workspace")

    current = jj.one_commit("@")
    bookmarks = jj.run(
        "log",
        "--no-graph",
        "-r",
        "@",
        "-T",
        _BOOKMARKS_TEMPLATE,
        ignore_working_copy=True,
    ).stdout.strip()

    if current.empty:
        state = "(empty)"
    else:
        description = (
            current.description.splitlines()[0].replace("\t", " ") if current.description else ""
        )
        state = f'"{_shorten(description)}"' if description else "(no desc)"
        insertions, deletions, added, modified, removed = _diff_counts(jj)
        state += f" +{insertions}/-{deletions} (+{added}/~{modified}/-{removed})"

    line = f"jj: {workspace.name} | @ {current.change_id[:12]} {state}"
    conflicted = len(jj.commits("::@ & conflicts()"))
    if conflicted:
        line += f" | ⚠ {conflicted} conflicted"
    if bookmarks:
        line += f" | ⚠ bookmark '{bookmarks}' on @"
    orphaned = [other.name for other in jj.workspaces() if other.orphaned]
    if orphaned:
        line += f" | ⚠ orphaned workspace '{','.join(orphaned)}' — needs `jj workspace forget`"
    return Status(root, line)


def _diff_counts(jj: Jj) -> tuple[int, int, int, int, int]:
    added = modified = removed = 0
    summary = jj.run(
        "diff",
        "--summary",
        "-r",
        "@",
        ignore_working_copy=True,
    ).stdout
    for row in summary.splitlines():
        kind = row[:1]
        if kind == "A":
            added += 1
        elif kind == "D":
            removed += 1
        elif row:
            modified += 1

    stat = jj.run(
        "diff",
        "--stat",
        "-r",
        "@",
        ignore_working_copy=True,
    ).stdout
    tail = stat.splitlines()[-1] if stat.splitlines() else ""
    insertions = _match_count(_INSERTIONS, tail)
    deletions = _match_count(_DELETIONS, tail)
    return insertions, deletions, added, modified, removed


def _match_count(pattern: re.Pattern[str], value: str) -> int:
    match = pattern.search(value)
    return int(match.group(1)) if match else 0


def _shorten(value: str, limit: int = 48) -> str:
    return value if len(value) <= limit else f"{value[: limit - 1]}…"


def run_status(cwd: Path | str | None = None, *, porcelain: bool = False) -> int:
    status = render_status(cwd)
    if status is None:
        return 1
    if porcelain:
        print(f"{status.line}\t{status.line}")
    else:
        print(status.line)
    return 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="jj-sensei status",
        description="Snapshot and print compact agent-oriented Jujutsu workspace status.",
    )
    parser.add_argument(
        "--porcelain",
        action="store_true",
        help="print KEY<TAB>LINE for hook suppression",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    return run_status(porcelain=args.porcelain)


if __name__ == "__main__":
    raise SystemExit(main())
