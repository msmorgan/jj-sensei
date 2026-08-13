"""Insert a constructed intermediate commit into a specific revision edge.

`jj split` divides a commit's existing diff: every byte of both halves already
appears in the original. That is the wrong tool when the intermediate state has
to be *derived* rather than selected -- a repository with generated artifacts
cannot express "the catalog before this entry, with its manifests regenerated"
as a subset of any diff, because the regenerated manifests appear neither in the
original commit nor in its parent.

Interpolation constructs that state instead. `begin -A AFTER -B BEFORE` inserts
an empty commit into that exact edge and pulls BEFORE's full content down into
it, leaving BEFORE empty. The caller then edits the working copy freely --
deleting, adding, rerunning generators -- until it holds the intermediate state.
`finish` restores BEFORE's original content on top, so its diff becomes exactly
the delta between the constructed state and where history already was.

The original content is recovered from the target's pre-rebase commit id, which
`begin` records. Rewriting a commit leaves the old one in the store, hidden but
still addressable, so no duplicate commit is needed and nothing has to be
cleaned up afterwards.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from .jj import Commit, Jj, JjError, safe_revision
from .repair import (
    EXIT_CLEAN,
    EXIT_EDIT_REQUIRED,
    EXIT_LOCK_TIMEOUT,
    EXIT_PAUSED,
    HumanRequired,
    LockTimeout,
    WorkspaceLock,
)

STATE_VERSION = 2

_BEGIN_PHASES = {"pin_pending", "insert_pending", "restore_pending"}
_FINISH_PHASES = {"finish_restore_pending", "finish_return_pending"}
_ABORT_PHASES = {"abort_restore_pending", "abort_abandon_pending", "abort_return_pending"}


@dataclass
class InterpolateState:
    version: int
    run_id: str
    workspace_name: str
    workspace_root: str
    phase: str
    after_change_id: str
    target_change_id: str
    target_commit_id: str
    target_description: str
    base_description: str
    return_change_id: str
    return_original_description: str
    return_requires_pin: bool
    return_pinned: bool = False
    base_change_id: str | None = None


class StateStore:
    """Persist the in-progress interpolation beside jj-sensei's other state."""

    def __init__(self, workspace_root: Path):
        self.directory = workspace_root / ".jj" / "jj-sensei"
        self.path = self.directory / "interpolate.json"

    def load(self) -> InterpolateState | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        state = InterpolateState(**data)
        if state.version != STATE_VERSION:
            raise HumanRequired(
                f"interpolate state version {state.version} is not supported; "
                f"ask a human to inspect {self.path}"
            )
        return state

    def save(self, state: InterpolateState) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="interpolate.", suffix=".tmp", dir=self.directory)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(asdict(state), stream, indent=2, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, self.path)
        finally:
            temporary_path.unlink(missing_ok=True)

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)


def run_begin(
    cwd: Path | str | None = None,
    after: str | None = None,
    before: str | None = None,
    message: str | None = None,
) -> int:
    return _run_locked(
        "interpolate begin",
        cwd,
        lambda jj, store: _begin(jj, store, after, before, message),
    )


def run_finish(cwd: Path | str | None = None) -> int:
    return _run_locked("interpolate finish", cwd, _finish)


def run_abort(cwd: Path | str | None = None) -> int:
    return _run_locked("interpolate abort", cwd, _abort)


def _begin(
    jj: Jj,
    store: StateStore,
    after_revision: str | None,
    before_revision: str | None,
    message: str | None,
) -> int:
    existing = store.load()
    if existing is not None:
        state = _require_state(jj, store)
        if state.phase in _BEGIN_PHASES:
            if message is not None and message != state.base_description:
                raise HumanRequired(
                    "the requested description differs from the in-progress interpolation; "
                    "rerun with the original `-m` value or abort"
                )
            return _advance_begin(jj, store, state)
        raise HumanRequired(
            f"an interpolation beneath {existing.target_change_id} is already in progress; "
            "run `interpolate finish` to complete it or `interpolate abort` to discard it"
        )

    if message is None or not message.strip():
        raise HumanRequired(
            "the interpolated commit needs a description; rerun `interpolate begin -m DESCRIPTION`"
        )
    if after_revision is None or before_revision is None:
        raise HumanRequired(
            "name the edge to interpolate with both `-A AFTER` and `-B BEFORE`; "
            "the usual current-change edge is `-A '@-' -B '@'`"
        )

    target = jj.one_commit(before_revision, snapshot=True)
    _refuse_unsuitable_target(target)
    after = jj.one_commit(after_revision)
    parents = jj.commits(f"parents({safe_revision(target.change_id)})")
    parent_ids = {parent.change_id for parent in parents}
    if after.change_id not in parent_ids:
        found = ", ".join(parent.change_id[:12] for parent in parents) or "nothing"
        raise HumanRequired(
            f"{after.change_id[:12]} is not a parent of {target.change_id[:12]}; "
            f"its parent(s) are {found}, so the requested edge does not exist"
        )

    workspace = jj.current_workspace()
    return_commit = jj.one_commit("@")

    # Recorded before any rewrite: `jj new -B` rebases the target onto the new
    # commit, giving it a fresh commit id. The id captured here keeps pointing at
    # the original content, which is what `finish` restores.
    target_commit_id = safe_revision(target.commit_id)
    target_change_id = safe_revision(target.change_id)
    state = InterpolateState(
        version=STATE_VERSION,
        run_id=uuid.uuid4().hex,
        workspace_name=workspace.name,
        workspace_root=str(workspace.root),
        phase="pin_pending",
        after_change_id=safe_revision(after.change_id),
        target_change_id=target_change_id,
        target_commit_id=target_commit_id,
        target_description=target.description,
        base_description=message,
        return_change_id=safe_revision(return_commit.change_id),
        return_original_description=return_commit.description,
        return_requires_pin=return_commit.empty and not return_commit.description,
    )
    # Save intent before the first mutation. Every later phase can recognize
    # both the pre-command and post-command graph after an interrupted process.
    store.save(state)
    return _advance_begin(jj, store, state)


def _advance_begin(jj: Jj, store: StateStore, state: InterpolateState) -> int:
    if state.phase == "pin_pending":
        _pin_return_commit(jj, state)
        state.phase = "insert_pending"
        store.save(state)

    if state.phase == "insert_pending":
        base = _find_or_insert_base(jj, state)
        state.base_change_id = safe_revision(base.change_id)
        state.phase = "restore_pending"
        store.save(state)

    if state.phase == "restore_pending":
        _pull_target_content_down(jj, state)
        state.phase = "editing"
        store.save(state)

    if state.phase != "editing" or state.base_change_id is None:
        raise HumanRequired(f"unknown interpolate begin phase {state.phase!r}")

    print(
        f"interpolate: inserted {state.base_change_id[:12]} into edge "
        f"{state.after_change_id[:12]} -> {state.target_change_id[:12]}."
    )
    print(f"  intermediate: {state.base_description}")
    print(f"  target: {state.target_description or '(no description set)'}")
    print()
    print("The working copy now holds the target's full content and the target is empty.")
    print("Edit the working copy until it holds the intermediate state -- delete what")
    print("belongs above, rerun any generators, keep every file consistent.")
    print()
    print("Then run `interpolate finish` to restore the target's content on top.")
    return EXIT_EDIT_REQUIRED


def _pin_return_commit(jj: Jj, state: InterpolateState) -> None:
    current = jj.one_commit("@", snapshot=True)
    if current.change_id != state.return_change_id:
        raise HumanRequired(
            "the working copy moved before interpolation could start; state is preserved"
        )
    if not state.return_requires_pin:
        return

    marker = _pin_description(state)
    if current.description == marker:
        state.return_pinned = True
        return
    if current.description != state.return_original_description:
        raise HumanRequired(
            "the working-copy description changed before it could be pinned; state is preserved"
        )
    jj.run("describe", "-m", marker)
    state.return_pinned = True


def _find_or_insert_base(jj: Jj, state: InterpolateState) -> Commit:
    current = jj.one_commit("@", snapshot=True)
    if current.change_id == state.return_change_id:
        jj.run(
            "new",
            "-A",
            safe_revision(state.after_change_id),
            "-B",
            safe_revision(state.target_change_id),
            "-m",
            state.base_description,
        )
        current = jj.one_commit("@", snapshot=True)

    if current.change_id in {state.return_change_id, state.target_change_id}:
        raise HumanRequired(
            "jj did not leave the working copy on a distinct interpolated commit; inspect the graph"
        )
    if current.description != state.base_description:
        raise HumanRequired(
            "the candidate interpolated commit has an unexpected description; state is preserved"
        )
    _refuse_changed_edge(jj, state, base_change_id=current.change_id)
    return current


def _pull_target_content_down(jj: Jj, state: InterpolateState) -> None:
    base = _base_commit(jj, state)
    target = _one_by_change_id(jj, state.target_change_id, "target commit")
    _refuse_changed_edge(jj, state)

    if _same_tree(jj, state.target_commit_id, base.commit_id):
        if not target.empty:
            raise HumanRequired(
                "the intermediate tree was restored but the target is not empty; state is ambiguous"
            )
        return
    if not base.empty or not _same_tree(jj, state.target_commit_id, target.commit_id):
        raise HumanRequired(
            "history changed while insertion was pending; refusing to overwrite either commit"
        )

    jj.run(
        "restore",
        "--from",
        safe_revision(state.target_change_id),
        "--into",
        safe_revision(base.change_id),
    )
    base = _base_commit(jj, state)
    target = _one_by_change_id(jj, state.target_change_id, "target commit")
    if not _same_tree(jj, state.target_commit_id, base.commit_id) or not target.empty:
        raise HumanRequired("jj restore completed with an unexpected interpolation graph")


def _finish(jj: Jj, store: StateStore) -> int:
    state = _require_state(jj, store)
    if state.phase in _BEGIN_PHASES:
        raise HumanRequired(
            "interpolation setup was interrupted; rerun `interpolate begin` before finishing"
        )
    if state.phase in _ABORT_PHASES:
        raise HumanRequired("an abort is in progress; rerun `interpolate abort`")

    if state.phase == "editing":
        _require_editing_position(jj, state)
        state.phase = "finish_restore_pending"
        store.save(state)

    if state.phase == "finish_restore_pending":
        _restore_target(jj, state)
        state.phase = "finish_return_pending"
        store.save(state)

    if state.phase != "finish_return_pending":
        raise HumanRequired(f"unknown interpolate finish phase {state.phase!r}")

    _return_to_original(jj, store, state)
    base = _base_commit(jj, state)
    target = _one_by_change_id(jj, state.target_change_id, "target commit")
    store.clear()

    print(f"interpolate: split {state.target_change_id[:12]} into two commits.")
    print(f"  {base.change_id[:12]}  {_describe(base)}")
    print(f"  {target.change_id[:12]}  {_describe(target)}")
    if base.empty or target.empty:
        # stderr is unbuffered while a piped stdout is not; flush so the warning
        # follows the summary it refers to instead of racing ahead of it.
        sys.stdout.flush()
    if base.empty:
        print(
            "\nwarning: the interpolated commit is empty -- the working copy was never edited, "
            "so nothing moved down.",
            file=sys.stderr,
        )
    if target.empty:
        print(
            "\nwarning: the target is now empty -- the intermediate state matches the original, "
            "so nothing remains above.",
            file=sys.stderr,
        )
    return EXIT_CLEAN


def _abort(jj: Jj, store: StateStore) -> int:
    state = _require_state(jj, store)
    if (
        state.phase in _FINISH_PHASES
        or state.phase == "editing"
        or state.phase == "restore_pending"
    ):
        state.phase = "abort_restore_pending"
        store.save(state)
    elif state.phase == "pin_pending":
        state.phase = "abort_return_pending"
        store.save(state)
    elif state.phase == "insert_pending":
        base = _find_inserted_base(jj, state)
        if base is None:
            state.phase = "abort_return_pending"
        else:
            state.base_change_id = safe_revision(base.change_id)
            state.phase = "abort_restore_pending"
        store.save(state)

    if state.phase == "abort_restore_pending":
        if _base_is_visible(jj, state):
            _restore_target(jj, state)
            state.phase = "abort_abandon_pending"
        elif _same_tree(jj, state.target_commit_id, _target_commit(jj, state).commit_id):
            state.phase = "abort_return_pending"
        else:
            raise HumanRequired(
                "the interpolated commit disappeared before the target was restored; inspect history"
            )
        store.save(state)

    if state.phase == "abort_abandon_pending":
        if _base_is_visible(jj, state):
            _refuse_changed_edge(jj, state)
            _refuse_bookmarked_or_foreign_base(jj, state)
            # Preserving descendant content is required: the target's current
            # diff is based on the edited intermediate tree.
            jj.run(
                "abandon",
                "--restore-descendants",
                safe_revision(_base_change_id(state)),
            )
        if _base_is_visible(jj, state):
            raise HumanRequired("jj abandon completed but the interpolated commit is still visible")
        target = _target_commit(jj, state)
        if not _same_tree(jj, state.target_commit_id, target.commit_id):
            raise HumanRequired("the target no longer has its original content after abort")
        state.phase = "abort_return_pending"
        store.save(state)

    if state.phase != "abort_return_pending":
        raise HumanRequired(f"unknown interpolate abort phase {state.phase!r}")

    _return_to_original(jj, store, state)
    store.clear()

    print(
        f"interpolate: discarded the interpolated commit; "
        f"{state.target_change_id[:12]} holds its original content again."
    )
    return EXIT_CLEAN


def _refuse_unsuitable_target(target: Commit) -> None:
    if target.immutable:
        raise HumanRequired(
            f"{target.change_id} is immutable; interpolating beneath it would rewrite "
            "protected history"
        )
    if target.conflict:
        raise HumanRequired(
            f"{target.change_id} has conflicts; resolve them before interpolating so the "
            "recorded content is unambiguous"
        )
    if target.empty:
        raise HumanRequired(
            f"{target.change_id} is empty; there is no content to interpolate beneath"
        )


def _refuse_changed_edge(
    jj: Jj,
    state: InterpolateState,
    *,
    base_change_id: str | None = None,
) -> None:
    """Refuse when the recorded after -> intermediate -> before edge changed."""
    base_id = safe_revision(base_change_id or _base_change_id(state))
    children = jj.commits(f"{base_id}+")
    child_ids = {commit.change_id for commit in children}
    parents = jj.commits(f"parents({base_id})")
    parent_ids = {commit.change_id for commit in parents}
    if child_ids != {state.target_change_id} or parent_ids != {state.after_change_id}:
        found_parents = ", ".join(sorted(parent[:12] for parent in parent_ids)) or "nothing"
        found_children = ", ".join(sorted(child[:12] for child in child_ids)) or "nothing"
        raise HumanRequired(
            f"expected edge {state.after_change_id[:12]} -> {base_id[:12]} -> "
            f"{state.target_change_id[:12]}, found parents {found_parents} and children "
            f"{found_children}; the history moved underneath this interpolation, so no jj "
            "command was run"
        )


def _require_state(jj: Jj, store: StateStore) -> InterpolateState:
    state = store.load()
    if state is None:
        raise HumanRequired("no interpolation is in progress; run `interpolate begin` first")
    workspace = jj.current_workspace()
    if workspace.name != state.workspace_name or workspace.root != Path(state.workspace_root):
        raise HumanRequired(
            f"this interpolation belongs to {state.workspace_name!r} at {state.workspace_root}, "
            f"not {workspace.name!r} at {workspace.root}"
        )
    return state


def _require_editing_position(jj: Jj, state: InterpolateState) -> None:
    base = _base_commit(jj, state)
    current = jj.one_commit("@", snapshot=True)
    if current.change_id != base.change_id:
        raise HumanRequired(
            "@ no longer names the interpolated commit; return to it or abort before finishing"
        )
    _refuse_changed_edge(jj, state)


def _restore_target(jj: Jj, state: InterpolateState) -> None:
    _base_commit(jj, state)
    target = _target_commit(jj, state)
    _refuse_changed_edge(jj, state)
    if target.immutable:
        raise HumanRequired(
            f"target {state.target_change_id} became immutable during the interpolation; "
            "no jj command was run"
        )
    if not _same_tree(jj, state.target_commit_id, target.commit_id) and not target.empty:
        raise HumanRequired(
            "the target changed while interpolation was in progress; refusing to overwrite it"
        )
    jj.run(
        "restore",
        "--from",
        safe_revision(state.target_commit_id),
        "--into",
        safe_revision(state.target_change_id),
    )
    target = _target_commit(jj, state)
    if not _same_tree(jj, state.target_commit_id, target.commit_id):
        raise HumanRequired("jj restore completed but the target tree is not the recorded original")


def _return_to_original(jj: Jj, store: StateStore, state: InterpolateState) -> None:
    return_commit = _one_by_change_id(jj, state.return_change_id, "original working-copy commit")
    current = jj.one_commit("@", snapshot=True)
    if current.change_id != return_commit.change_id:
        jj.run("edit", safe_revision(state.return_change_id))
        return_commit = _one_by_change_id(
            jj, state.return_change_id, "original working-copy commit"
        )

    marker = _pin_description(state)
    # A crash after `describe` but before the journal update leaves the marker
    # in the graph while return_pinned is still false. The graph is the durable
    # postcondition, so reconcile it here rather than leaking the cursor.
    if return_commit.description == marker:
        state.return_pinned = True
    if not state.return_pinned:
        return
    if return_commit.description == state.return_original_description:
        state.return_pinned = False
        store.save(state)
        return
    if return_commit.description != marker:
        raise HumanRequired(
            "the pinned working-copy description was edited externally; ask which description to keep"
        )
    jj.run("describe", "-m", state.return_original_description)
    state.return_pinned = False
    store.save(state)


def _find_inserted_base(jj: Jj, state: InterpolateState) -> Commit | None:
    if state.base_change_id is not None:
        commits = jj.commits(f"change_id({safe_revision(state.base_change_id)})")
        if len(commits) > 1:
            raise HumanRequired(
                "the interpolated commit became divergent; inspect it before aborting"
            )
        return commits[0] if commits else None

    current = jj.one_commit("@", snapshot=True)
    if current.change_id == state.return_change_id:
        return None
    if current.description != state.base_description:
        raise HumanRequired(
            "the working copy moved while insertion was pending; state is preserved"
        )
    _refuse_changed_edge(jj, state, base_change_id=current.change_id)
    return current


def _refuse_bookmarked_or_foreign_base(jj: Jj, state: InterpolateState) -> None:
    base = _base_commit(jj, state)
    if jj.commits(f"{safe_revision(base.commit_id)} & bookmarks()"):
        raise HumanRequired(
            "aborting would abandon a bookmarked interpolated commit; bookmark intent must come "
            "from the user, task, or repository workflow"
        )
    foreign = [
        workspace.name
        for workspace in jj.workspaces()
        if workspace.commit_id == base.commit_id and workspace.name != state.workspace_name
    ]
    if foreign:
        raise HumanRequired(
            "the interpolated commit is another workspace's working copy "
            f"({', '.join(foreign)}); refusing to abandon it"
        )


def _base_change_id(state: InterpolateState) -> str:
    if state.base_change_id is None:
        raise HumanRequired("interpolation state does not yet identify an inserted commit")
    return state.base_change_id


def _base_commit(jj: Jj, state: InterpolateState) -> Commit:
    return _one_by_change_id(jj, _base_change_id(state), "interpolated commit")


def _target_commit(jj: Jj, state: InterpolateState) -> Commit:
    return _one_by_change_id(jj, state.target_change_id, "target commit")


def _base_is_visible(jj: Jj, state: InterpolateState) -> bool:
    if state.base_change_id is None:
        return False
    commits = jj.commits(f"change_id({safe_revision(state.base_change_id)})")
    if len(commits) > 1:
        raise HumanRequired(
            "the interpolated commit became divergent; inspect it before continuing"
        )
    return bool(commits)


def _same_tree(jj: Jj, left_commit_id: str, right_commit_id: str) -> bool:
    return not jj.diff_between(safe_revision(left_commit_id), safe_revision(right_commit_id))


def _pin_description(state: InterpolateState) -> str:
    return f"jj-sensei: interpolate cursor {state.run_id}"


def _one_by_change_id(jj: Jj, change_id: str, label: str) -> Commit:
    commits = jj.commits(safe_revision(change_id))
    if len(commits) != 1:
        raise HumanRequired(
            f"expected exactly one {label} for {change_id}, found {len(commits)}; "
            "no jj command was run"
        )
    return commits[0]


def _describe(commit: Commit) -> str:
    description = commit.description or "(no description set)"
    return f"{'(empty) ' if commit.empty else ''}{description}"


def _run_locked(name: str, cwd: Path | str | None, operation) -> int:
    jj = Jj(cwd)
    try:
        root = jj.workspace_root()
        store = StateStore(root)
        # Shares repair's lock: both rewrite history in this workspace.
        with WorkspaceLock(root):
            return operation(jj, store)
    except LockTimeout as error:
        print(f"{name}: {error}; rerun after the other command finishes.", file=sys.stderr)
        return EXIT_LOCK_TIMEOUT
    except JjError as error:
        print(f"{name}: jj step failed; no subsequent jj command was run.", file=sys.stderr)
        print(f"  command: {error.rendered_command}", file=sys.stderr)
        if error.stdout.strip():
            print(error.stdout.rstrip(), file=sys.stderr)
        if error.stderr.strip():
            print(error.stderr.rstrip(), file=sys.stderr)
        print(
            "State is preserved. Do not use an immutability bypass or operation-log recovery. "
            "Pause, inspect `jj --no-pager st`, and ask before continuing.",
            file=sys.stderr,
        )
        return EXIT_PAUSED
    except HumanRequired as error:
        print(str(error), file=sys.stderr)
        print(
            f"{name}: paused without running another jj command. Inspect the reported state "
            "and ask before continuing.",
            file=sys.stderr,
        )
        return EXIT_PAUSED
    except (OSError, RuntimeError, ValueError) as error:
        print(f"{name}: paused: {error}", file=sys.stderr)
        print(
            f"{name}: no further recovery command was attempted. Inspect the workspace and ask "
            "before continuing.",
            file=sys.stderr,
        )
        return EXIT_PAUSED


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="jj-sensei interpolate",
        description=(
            "Insert a constructed intermediate commit into a named revision edge. Unlike "
            "`jj split`, the intermediate state may contain content that appears in neither "
            "the upper commit nor the lower endpoint."
        ),
        epilog=(
            "Exit 0 when clean; 1 when the working copy awaits your edits; "
            "2 on safe refusal; 75 if locked."
        ),
    )
    commands = parser.add_subparsers(dest="phase", required=True)
    begin = commands.add_parser(
        "begin",
        help="insert a commit into an edge and pull the upper endpoint's content into it",
    )
    begin.add_argument("-A", "--after", required=True, help="lower endpoint of the edge")
    begin.add_argument("-B", "--before", required=True, help="upper endpoint of the edge")
    begin.add_argument(
        "-m",
        "--message",
        required=True,
        help="description for the constructed intermediate commit",
    )
    commands.add_parser(
        "finish",
        help="restore the target's original content on top of the edited intermediate state",
    )
    commands.add_parser(
        "abort",
        help="discard the intermediate commit and restore the target's original content",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))

    if args.phase == "begin":
        return run_begin(after=args.after, before=args.before, message=args.message)
    if args.phase == "finish":
        return run_finish()
    if args.phase == "abort":
        return run_abort()
    raise AssertionError(args.phase)


if __name__ == "__main__":
    sys.exit(main())
