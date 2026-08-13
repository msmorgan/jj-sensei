"""Install and audit jj-sensei's workspace immutability aliases."""

from __future__ import annotations

import itertools
import sys
from dataclasses import dataclass
from pathlib import Path

from .jj import Jj, JjError, Workspace, safe_revision
from .repair import EXIT_CLEAN, EXIT_LOCK_TIMEOUT, EXIT_PAUSED, LockTimeout, WorkspaceLock

ALIASES = {
    'revset-aliases."other_workspaces()"': "working_copies() ~ @",
    'revset-aliases."not_default()"': "@ ~ default@",
    'revset-aliases."only_if(condition, revisions)"': (
        "revisions & descendants(ancestors(condition))"
    ),
    'revset-aliases."immutable_heads()"': (
        "builtin_immutable_heads() | only_if(not_default(), other_workspaces())"
    ),
}


@dataclass(frozen=True)
class Overlap:
    left: Workspace
    right: Workspace
    fork_change_id: str
    fork_description: str


def workspace_overlaps(jj: Jj) -> list[Overlap]:
    """Find pairs sharing feature-only ancestry outside the default line."""
    workspaces = [workspace for workspace in jj.workspaces() if workspace.name != "default"]
    overlaps = []
    for left, right in itertools.combinations(workspaces, 2):
        safe_revision(left.commit_id)
        safe_revision(right.commit_id)
        fork = jj.commits(f"fork_point({left.commit_id} | {right.commit_id}) ~ ancestors(default@)")
        if fork:
            overlaps.append(
                Overlap(
                    left=left,
                    right=right,
                    fork_change_id=fork[0].change_id,
                    fork_description=fork[0].description,
                )
            )
    return overlaps


def run_setup(cwd: Path | str | None = None, *, check_only: bool = False) -> int:
    jj = Jj(cwd)
    try:
        root = jj.workspace_root()
        current = jj.current_workspace()
        if current.name != "default":
            print(
                f"setup: run from the default workspace, not {current.name!r}; no config changed.",
                file=sys.stderr,
            )
            return EXIT_PAUSED
        with WorkspaceLock(root):
            if not check_only:
                for key, value in ALIASES.items():
                    jj.run("config", "set", "--repo", key, value)
                print("setup: installed the workspace immutability aliases.")
            _verify_aliases(jj)
            _verify_default_context(jj)
            overlaps = workspace_overlaps(jj)
            _report_overlaps(overlaps)
            return EXIT_PAUSED if overlaps else EXIT_CLEAN
    except LockTimeout as error:
        print(f"setup: {error}; rerun after the other operation finishes.", file=sys.stderr)
        return EXIT_LOCK_TIMEOUT
    except JjError as error:
        print("setup: jj step failed; no subsequent jj command was run.", file=sys.stderr)
        print(f"  command: {error.rendered_command}", file=sys.stderr)
        if error.stderr.strip():
            print(error.stderr.rstrip(), file=sys.stderr)
        return EXIT_PAUSED
    except (OSError, RuntimeError, ValueError) as error:
        print(f"setup: paused: {error}", file=sys.stderr)
        return EXIT_PAUSED


def _verify_default_context(jj: Jj) -> None:
    protected = jj.commits("working_copies() & immutable_heads()")
    if protected:
        raise RuntimeError(
            "the alias does not collapse in default: default sees a working copy as an immutable head"
        )
    print("setup: verified that default keeps coordinator rewrite authority.")


def _verify_aliases(jj: Jj) -> None:
    for key, expected in ALIASES.items():
        result = jj.run("config", "get", key, check=False)
        actual = result.stdout.strip() if result.returncode == 0 else None
        if actual != expected:
            raise RuntimeError(
                f"alias {key} is missing or differs; expected {expected!r}, found {actual!r}"
            )
    print("setup: verified all four alias definitions.")


def _report_overlaps(overlaps: list[Overlap]) -> None:
    if not overlaps:
        print("setup: active non-default workspaces have independent ancestry.")
        return
    print(
        "setup: discouraged live-workspace topology detected. The guard remains safe, but shared "
        "feature ancestry becomes immutable from both workspaces:",
        file=sys.stderr,
    )
    for overlap in overlaps:
        description = (
            overlap.fork_description.splitlines()[0]
            if overlap.fork_description
            else "(no description)"
        )
        print(
            f"  {overlap.left.name} <-> {overlap.right.name}: shared feature fork "
            f"{overlap.fork_change_id[:12]} {description}",
            file=sys.stderr,
        )
    print(
        "Do not bypass immutability. Base independent workspaces on default-owned history, or ask "
        "the user to choose how these live stacks should be restructured.",
        file=sys.stderr,
    )
