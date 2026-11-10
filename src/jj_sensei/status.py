"""Compact, agent-oriented status for one Jujutsu workspace."""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import divergence as divergence_probe
from .divergence import Alarm, Divergence
from .jj import Jj, JjError
from .repair import LockTimeout, WorkspaceLock

_INSERTIONS = re.compile(r"(\d+) insertion")
_DELETIONS = re.compile(r"(\d+) deletion")
_BOOKMARKS_TEMPLATE = 'bookmarks.map(|bookmark| bookmark.name()).join(",")'


@dataclass(frozen=True)
class Status:
    root: Path
    line: str
    # NEW-divergence alarms still standing repo-wide. Which of them a given
    # agent has already been shown is the caller's bookkeeping.
    alarms: tuple[Alarm, ...] = ()
    # Whether hooks must repeat this line on every call instead of
    # deduplicating it. Only warnings about this workspace's own state, which
    # its agent should act on, repeat; standing repo-wide notices (the
    # divergent count, an orphaned workspace) and the bookmark and conflict
    # warnings are shown once per consumer and again whenever the line changes.
    repeat: bool = False


def render_status(cwd: Path | str | None = None) -> Status | None:
    """Snapshot and render a workspace, or stay silent if it cannot be probed safely.

    The repo-wide divergence probe runs first, outside the workspace lock, so
    a busy or unreadable workspace still reports divergence made anywhere.
    """
    jj = Jj(cwd)
    try:
        root = jj.workspace_root()
    except (JjError, OSError, RuntimeError, ValueError):
        return None
    divergence = divergence_probe.probe(jj, root)
    try:
        with WorkspaceLock(root, timeout=0.25):
            status = _render_locked(jj, root, divergence)
    except LockTimeout:
        status = _render_unlocked(jj, root, divergence, "@ not probed (workspace busy)")
    except (JjError, OSError, RuntimeError, ValueError):
        status = _render_unlocked(jj, root, divergence, "@ not probed (jj error)")
    if status is None:
        return None
    alarms = divergence.alarms if divergence is not None else ()
    return Status(status.root, status.line, alarms, status.repeat)


def _render_unlocked(
    jj: Jj, root: Path, divergence: Divergence | None, reason: str
) -> Status | None:
    """A degraded line that still carries repo-wide warnings, or silence."""
    if divergence is None or not (divergence.count or divergence.alarms):
        return None
    try:
        name = jj.current_workspace().name
    except (JjError, OSError, RuntimeError, ValueError):
        name = root.name
    return Status(root, f"jj: {name} | {reason}{divergence.suffix}", repeat=True)


def _render_locked(jj: Jj, root: Path, divergence: Divergence | None = None) -> Status:
    workspace = jj.current_workspace()
    suffix = divergence.suffix if divergence is not None else ""

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
                "trusting anything here" + suffix,
                repeat=True,
            )
        return Status(
            root,
            f"jj: {workspace.name} | ⚠ jj could not read this workspace{suffix}",
            repeat=True,
        )

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
    # Only paid for when something is divergent at all: the repo-wide set is
    # already known, and `@`'s ancestry can only intersect a non-empty set.
    repeat = False
    if divergence is not None and divergence.count:
        if jj.commits(f"::@ & ({divergence_probe.DIVERGENT_REVSET})"):
            line += " | ⚠ @ or its ancestors divergent"
            repeat = True
        line += divergence.suffix
    return Status(root, line, repeat=repeat)


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
