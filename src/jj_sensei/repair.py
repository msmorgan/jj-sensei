"""Resumable, fail-closed recovery for stale, divergent, and conflicted workspaces."""

from __future__ import annotations

import errno
import json
import os
import re
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from . import conflicts
from .jj import Commit, Jj, JjError, safe_revision, union

if os.name == "nt":  # pragma: no cover - exercised on Windows
    import msvcrt
else:  # pragma: no cover - the lock behavior is tested, not the platform import
    import fcntl

EXIT_CLEAN = 0
EXIT_EDIT_REQUIRED = 1
EXIT_PAUSED = 2
EXIT_LOCK_TIMEOUT = 75
_MARKER = re.compile(r"^(<{7,}|>{7,}) conflict [0-9]+ of [0-9]+")


class HumanRequired(RuntimeError):
    """The helper cannot choose safely; no more jj commands should run."""


class LockTimeout(RuntimeError):
    pass


@dataclass
class ResolutionState:
    version: int
    run_id: str
    workspace_name: str
    workspace_root: str
    tip_change_id: str
    phase: str
    target_change_id: str
    before_change_id: str
    resolution_change_id: str | None = None
    destination_description: str | None = None
    tip_original_description: str = ""
    tip_requires_pin: bool = False
    tip_pinned: bool = False


class StateStore:
    def __init__(self, workspace_root: Path):
        self.directory = workspace_root / ".jj" / "jj-sensei"
        self.path = self.directory / "repair.json"

    def load(self) -> ResolutionState | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        state = ResolutionState(**data)
        if state.version != 2:
            raise HumanRequired(
                f"repair state version {state.version} is not supported; ask a human to inspect {self.path}"
            )
        return state

    def save(self, state: ResolutionState) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix="repair.", suffix=".tmp", dir=self.directory)
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


class WorkspaceLock:
    def __init__(self, workspace_root: Path, timeout: float = 5.0):
        self.path = workspace_root / ".jj" / "jj-sensei" / "repair.lock"
        self.timeout = timeout
        self._stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("a+b")
        if os.name == "nt" and self.path.stat().st_size == 0:
            self._stream.write(b"\0")
            self._stream.flush()
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                _try_lock(self._stream)
                return self
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    self._stream.close()
                    self._stream = None
                    raise LockTimeout(f"timed out waiting for {self.path}") from None
                time.sleep(0.05)

    def __exit__(self, exc_type, exc, traceback):
        if self._stream is not None:
            _unlock(self._stream)
            self._stream.close()
        return False


def _try_lock(stream) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on Windows
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EDEADLK}:
                raise BlockingIOError from error
            raise
    else:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(stream) -> None:
    if os.name == "nt":  # pragma: no cover - exercised on Windows
        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def converge(jj: Jj, *, announce: bool = True) -> bool:
    """Converge equivalent divergent successors, returning whether work was done."""
    current = jj.one_commit("@")
    safe_revision(current.change_id)
    candidates = jj.commits(f"change_id({current.change_id})")
    if len(candidates) <= 1:
        if announce:
            print("converge: @ is not divergent — nothing to do.")
        return False

    _refuse_owned_candidates(jj, candidates, current)
    nonempty = [candidate for candidate in candidates if not candidate.empty]
    if not nonempty:
        keep = current
    elif len(nonempty) == 1:
        keep = nonempty[0]
    else:
        keep = current if not current.empty else nonempty[0]
        for candidate in nonempty:
            if candidate.commit_id == keep.commit_id:
                continue
            if jj.diff_between(keep.commit_id, candidate.commit_id):
                raise HumanRequired(
                    "converge: divergent successors hold different nonempty work; "
                    "inspect the candidates and choose the keeper manually"
                )

    if current.commit_id != keep.commit_id:
        jj.run("edit", keep.commit_id)

    survivors = jj.commits(f"change_id({current.change_id})")
    drop = [candidate for candidate in survivors if candidate.commit_id != keep.commit_id]
    if drop:
        _refuse_owned_candidates(jj, [keep, *drop], keep)
        jj.run("abandon", *[candidate.commit_id for candidate in drop])

    if announce:
        dropped = ", ".join(candidate.commit_id[:12] for candidate in drop) or "none (auto-hidden)"
        print(f"converge: kept {keep.commit_id[:12]}; dropped {dropped}.")
    return True


def _refuse_owned_candidates(jj: Jj, candidates: list[Commit], keep: Commit) -> None:
    candidate_ids = {candidate.commit_id for candidate in candidates}
    referenced = jj.commits(f"({union(candidate_ids)}) & bookmarks()")
    if referenced:
        ids = ", ".join(commit.commit_id[:12] for commit in referenced)
        raise HumanRequired(
            f"converge: candidate(s) {ids} have bookmarks; bookmark ownership is user-only"
        )

    current_name = jj.current_workspace().name
    foreign = [
        workspace
        for workspace in jj.workspaces()
        if workspace.commit_id in candidate_ids and workspace.name != current_name
    ]
    if foreign:
        names = ", ".join(workspace.name for workspace in foreign)
        raise HumanRequired(
            f"converge: candidate commits are working copies of other workspaces ({names}); refusing"
        )


def resolve_conflicts(jj: Jj, store: StateStore) -> int:
    """Resume or start an oldest-first conflict descent."""
    state = store.load()
    workspace = jj.current_workspace()
    if state is not None and (
        state.workspace_name != workspace.name or Path(state.workspace_root) != workspace.root
    ):
        raise HumanRequired(
            f"repair state belongs to {state.workspace_name} at {state.workspace_root}, "
            f"not {workspace.name} at {workspace.root}"
        )

    for _ in range(100):
        if state is None:
            state = _start_next_conflict(jj, store, workspace.name, workspace.root, None)
            if state is None:
                store.clear()
                print("repair: workspace is clean.")
                return EXIT_CLEAN

        if state.phase == "unpin_pending":
            _unpin_tip(jj, store, state)
            store.clear()
            print("repair: all conflicts resolved; workspace is clean.")
            return EXIT_CLEAN

        if state.phase == "start_pending":
            state = _enter_resolution(jj, store, state)

        if state.phase == "editing":
            outcome, state = _finish_edit(jj, store, state)
            if outcome is not None:
                return outcome

        if state.phase == "fold_pending":
            state = _fold_resolution(jj, store, state)

        if state.phase == "return_pending":
            state = _return_to_tip(jj, store, state)

        if state.phase == "scan":
            previous = state
            state = _start_next_conflict(
                jj,
                store,
                state.workspace_name,
                Path(state.workspace_root),
                state,
            )
            if state is None:
                previous.phase = "unpin_pending"
                store.save(previous)
                state = previous

    raise HumanRequired("repair exceeded 100 state transitions; refusing a possible loop")


def _start_next_conflict(
    jj: Jj,
    store: StateStore,
    workspace_name: str,
    workspace_root: Path,
    previous: ResolutionState | None,
) -> ResolutionState | None:
    current = jj.one_commit("@")
    if current.immutable:
        raise HumanRequired(
            "repair: this workspace's @ is immutable. This usually means one live non-default "
            "workspace was based on another's feature-only ancestry. Do not bypass the guard; "
            "report the workspace topology and restructure it from the default workspace."
        )

    conflicted = jj.commits("::@ & conflicts()")
    if not conflicted:
        return None
    mutable_conflicted = jj.commits("::@ & conflicts() & mutable()")
    if not mutable_conflicted:
        raise HumanRequired(
            "repair: the remaining conflict is in immutable ancestry. Stop here; do not use "
            "--ignore-immutable. Report which workspace owns that ancestry."
        )
    roots = jj.commits("roots(::@ & conflicts() & mutable())")
    if not roots:
        raise HumanRequired("repair: could not identify the oldest mutable conflicted commit")
    target = roots[0]
    tip_change_id = previous.tip_change_id if previous is not None else current.change_id
    state = ResolutionState(
        version=2,
        run_id=previous.run_id if previous is not None else uuid.uuid4().hex,
        workspace_name=workspace_name,
        workspace_root=str(workspace_root),
        tip_change_id=tip_change_id,
        phase="start_pending",
        target_change_id=target.change_id,
        before_change_id=current.change_id,
        tip_original_description=(
            previous.tip_original_description if previous is not None else current.description
        ),
        tip_requires_pin=(
            previous.tip_requires_pin
            if previous is not None
            else current.empty and not current.description
        ),
        tip_pinned=previous.tip_pinned if previous is not None else False,
    )
    store.save(state)
    return state


def _enter_resolution(jj: Jj, store: StateStore, state: ResolutionState) -> ResolutionState:
    current = jj.one_commit("@")
    if state.tip_requires_pin and not state.tip_pinned:
        pin = _pin_description(state)
        if current.change_id != state.tip_change_id:
            raise HumanRequired(
                "repair: the tip moved before it could be pinned. State is preserved; inspect "
                "the graph before continuing."
            )
        if current.description == pin:
            state.tip_pinned = True
            store.save(state)
        elif current.description != state.tip_original_description:
            raise HumanRequired(
                "repair: the tip description changed before it could be pinned. State is "
                "preserved; inspect the tip before continuing."
            )
        else:
            jj.run("describe", "-m", pin)
            state.tip_pinned = True
            store.save(state)

    if current.change_id == state.before_change_id:
        jj.run("new", state.target_change_id)
        current = jj.one_commit("@", snapshot=True)
    elif not _is_direct_child(jj, state.target_change_id):
        raise HumanRequired(
            "repair: @ moved while a resolution step was pending. State is preserved; inspect "
            "the current graph and ask before continuing."
        )

    if not _is_direct_child(jj, state.target_change_id):
        raise HumanRequired(
            "repair: jj created an unexpected resolution position. State is preserved; inspect "
            "the graph before continuing."
        )
    state.resolution_change_id = current.change_id
    state.phase = "editing"
    store.save(state)
    print(f"repair: editing oldest conflicted change {state.target_change_id[:12]}.")
    return state


def _finish_edit(
    jj: Jj,
    store: StateStore,
    state: ResolutionState,
) -> tuple[int | None, ResolutionState]:
    current = jj.one_commit("@", snapshot=True)
    if current.change_id != state.resolution_change_id:
        raise HumanRequired(
            "repair: @ no longer names the recorded resolution change. State is preserved; "
            "inspect the graph before continuing."
        )

    files = jj.conflict_files()
    if files:
        resolved, _left = _auto_resolve(jj.workspace_root(), files)
        if resolved:
            files = jj.conflict_files()
    if files:
        print("repair: stopped for manual conflict resolution.", file=sys.stderr)
        _print_marker_locations(jj.workspace_root(), files)
        _print_conflict_hunks(jj.workspace_root(), files)
        print(
            "Resolve every marker in the listed files, then rerun this repair command. "
            "No lock is held while you edit.",
            file=sys.stderr,
        )
        return EXIT_EDIT_REQUIRED, state

    target = _one_by_change_id(jj, state.target_change_id)
    if not target.conflict:
        if not current.empty:
            raise HumanRequired(
                "repair: the target is already conflict-free but the resolution change still "
                "contains work. Refusing to guess whether it was already folded."
            )
        state.phase = "return_pending"
        store.save(state)
        return None, state

    state.destination_description = target.description
    state.phase = "fold_pending"
    store.save(state)
    return None, state


def _fold_resolution(jj: Jj, store: StateStore, state: ResolutionState) -> ResolutionState:
    target = _one_by_change_id(jj, state.target_change_id)
    current = jj.one_commit("@", snapshot=True)
    if not target.conflict:
        # `jj squash` replaces the resolution child with a fresh empty
        # working-copy change. After a crash between squash and journal update,
        # recognize the graph postcondition rather than the vanished identity.
        if current.empty and _is_direct_child(jj, state.target_change_id):
            state.phase = "return_pending"
            store.save(state)
            return state
        raise HumanRequired(
            "repair: fold state is ambiguous after an external rewrite. State is preserved; "
            "inspect the target and resolution changes before continuing."
        )
    if current.change_id != state.resolution_change_id or jj.conflict_files():
        raise HumanRequired(
            "repair: the recorded resolution is no longer ready to fold. State is preserved; "
            "inspect @ and the conflict files before continuing."
        )

    description = state.destination_description
    if description is None:
        description = target.description
        state.destination_description = description
        store.save(state)
    jj.run("squash", "-m", description)
    target = _one_by_change_id(jj, state.target_change_id)
    if target.conflict:
        raise HumanRequired(
            "repair: squash completed but the target is still conflicted. Stop and inspect it."
        )
    state.phase = "return_pending"
    store.save(state)
    return state


def _return_to_tip(jj: Jj, store: StateStore, state: ResolutionState) -> ResolutionState:
    current = jj.one_commit("@")
    if current.change_id != state.tip_change_id:
        tips = jj.commits(state.tip_change_id)
        if len(tips) != 1:
            raise HumanRequired(
                "repair: the recorded tip is missing or divergent. State is preserved; run "
                "convergence or ask a human to choose the correct successor."
            )
        jj.run("edit", state.tip_change_id)
    state.phase = "scan"
    state.target_change_id = ""
    state.before_change_id = state.tip_change_id
    state.resolution_change_id = None
    state.destination_description = None
    store.save(state)
    return state


def _unpin_tip(jj: Jj, store: StateStore, state: ResolutionState) -> None:
    if not state.tip_pinned:
        return
    current = jj.one_commit("@", snapshot=True)
    if current.change_id != state.tip_change_id:
        raise HumanRequired(
            "repair: cannot restore the tip description because @ moved. State is preserved."
        )
    if current.description == state.tip_original_description:
        state.tip_pinned = False
        store.save(state)
        return
    if current.description != _pin_description(state):
        raise HumanRequired(
            "repair: the pinned tip description was edited externally. State is preserved; "
            "ask which description should be kept."
        )
    jj.run("describe", "-m", state.tip_original_description)
    state.tip_pinned = False
    store.save(state)


def _pin_description(state: ResolutionState) -> str:
    return f"jj-sensei: repair cursor {state.run_id}"


def _is_direct_child(jj: Jj, parent_change_id: str) -> bool:
    safe_revision(parent_change_id)
    return bool(jj.commits(f"parents(@) & {parent_change_id}"))


def _one_by_change_id(jj: Jj, change_id: str) -> Commit:
    safe_revision(change_id)
    commits = jj.commits(change_id)
    if len(commits) != 1:
        raise HumanRequired(
            f"repair: change {change_id[:12]} has {len(commits)} visible successors; converge first"
        )
    return commits[0]


def _auto_resolve(root: Path, files: list[str]) -> tuple[int, int]:
    total_resolved = total_left = 0
    print("repair: trying conservative sorted-addition resolution:")
    for filename in files:
        path = root / filename
        resolved, left = conflicts._auto_resolve_file(path, filename, dry=False)
        total_resolved += resolved
        total_left += left
    print(f"  resolved {total_resolved} hunk(s), {total_left} left for review")
    return total_resolved, total_left


def _print_marker_locations(root: Path, files: list[str]) -> None:
    print("Conflict markers to inspect (file:line):", file=sys.stderr)
    for filename in files:
        path = root / filename
        try:
            lines = conflicts._split_lines(conflicts._read_source(path))
        except (OSError, UnicodeError) as error:
            print(f"  {path}: could not read markers: {error}", file=sys.stderr)
            continue
        for number, line in enumerate(lines, 1):
            text = conflicts._split_line(line)[0]
            if _MARKER.match(text):
                print(f"  {path}:{number}:{text}", file=sys.stderr)


def _print_conflict_hunks(root: Path, files: list[str]) -> None:
    print("Conflict hunks:", file=sys.stderr)
    for filename in files:
        path = root / filename
        try:
            hunks, _lines = conflicts.parse_file(path)
        except (OSError, UnicodeError) as error:
            print(f"  {path}: could not read conflict: {error}", file=sys.stderr)
            continue
        if not hunks:
            print(
                f"  {path}: unsupported marker style; inspect the file manually.",
                file=sys.stderr,
            )
            continue
        for hunk in hunks:
            print("─" * 64, file=sys.stderr)
            print(
                f"{path} | hunk {hunk['hunk']}/{hunk['total']} | "
                f"lines {hunk['start_line']}–{hunk['end_line']}",
                file=sys.stderr,
            )
            sys.stderr.writelines(hunk["raw"])


def run_repair(cwd: Path | str | None = None) -> int:
    return _run_locked("repair", cwd, _repair)


def run_resolve(cwd: Path | str | None = None) -> int:
    return _run_locked("resolve", cwd, _resolve_only)


def run_converge(cwd: Path | str | None = None) -> int:
    return _run_locked("converge", cwd, _converge_only)


def _repair(jj: Jj, store: StateStore) -> int:
    jj.run("workspace", "update-stale")
    converge(jj, announce=False)
    return resolve_conflicts(jj, store)


def _resolve_only(jj: Jj, store: StateStore) -> int:
    return resolve_conflicts(jj, store)


def _converge_only(jj: Jj, _store: StateStore) -> int:
    converge(jj)
    return EXIT_CLEAN


def _run_locked(name: str, cwd: Path | str | None, operation) -> int:
    jj = Jj(cwd)
    try:
        root = jj.workspace_root()
        store = StateStore(root)
        with WorkspaceLock(root):
            return operation(jj, store)
    except LockTimeout as error:
        print(f"{name}: {error}; rerun after the other repair finishes.", file=sys.stderr)
        return EXIT_LOCK_TIMEOUT
    except JjError as error:
        _print_failed_step(name, error)
        return EXIT_PAUSED
    except HumanRequired as error:
        print(str(error), file=sys.stderr)
        print(
            f"{name}: paused without running another jj command. Inspect the reported state and "
            f"ask before continuing; when it is understood, rerun {name}.",
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


def _print_failed_step(name: str, error: JjError) -> None:
    print(f"{name}: jj step failed; no subsequent jj command was run.", file=sys.stderr)
    print(f"  command: {error.rendered_command}", file=sys.stderr)
    if error.stdout.strip():
        print(error.stdout.rstrip(), file=sys.stderr)
    if error.stderr.strip():
        print(error.stderr.rstrip(), file=sys.stderr)
    print(
        "State is preserved. Do not use an immutability bypass or operation-log recovery. "
        "Pause, inspect `jj --no-pager st`, and suggest rerunning this command once the "
        "workspace is stable; if the error says immutable, report the live workspace ancestry.",
        file=sys.stderr,
    )
