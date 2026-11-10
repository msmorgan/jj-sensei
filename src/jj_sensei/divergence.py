"""Repo-wide alarm for newly created divergent commits.

Divergence is rarely made in the workspace that later suffers from it: one
agent resurrects a hidden commit with `jj new <old commit id>`, and the stale
copies surface under other agents' stacks minutes later. A per-`@` check sees
none of that. This probe therefore watches the whole repository's
`divergent() & mutable()` set and remembers it in the repository's shared
directory, so the next hook call from *any* workspace, session, or agent sees
growth made by anyone, including a background command.

The probe is read-only and lock-free. In the steady state it costs one
`jj op log -n1`; the divergent set is queried again only after the operation
changes, and the operation log is walked with `--at-op` only when that set
actually grew. Every failure degrades to "no information", never to an error.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from .jj import Jj

STATE_VERSION = 1
# Immutable twins (an old remote bookmark imported by a clone, say) are a
# different, slower-moving problem and not this alarm's business.
DIVERGENT_REVSET = "divergent() & mutable()"
_DIVERGENT_TEMPLATE = 'change_id ++ " " ++ commit_id ++ "\\n"'
# How far back the attribution walk goes. One hook call normally sees a
# handful of new operations; a burst from many parallel agents can reach a few
# dozen. Anything older than this stays unattributed rather than slow.
WALK_LIMIT = 40
# A NEW alarm is delivered once to every consumer (agent or session, per
# workspace) that has not seen it, while the divergence it reports persists,
# but only for this long: after that it is old news, and the standing
# `⚠ N divergent commits repo-wide` suffix carries the message.
ALARM_TTL_SECONDS = 2 * 60 * 60
MAX_ALARMS = 50
_LISTED_CHANGES = 3
_LONG_HEX = re.compile(r"\b([0-9a-f]{8})[0-9a-f]{5,}\b")


@dataclass(frozen=True)
class Alarm:
    """One burst of new divergence, attributed to the operation that made it."""

    id: str
    line: str
    created: float


@dataclass(frozen=True)
class Divergence:
    """The repo-wide divergent set at one operation, plus any live alarms."""

    op_id: str
    changes: dict[str, list[str]]
    alarms: tuple[Alarm, ...] = ()

    @property
    def count(self) -> int:
        return sum(len(commits) for commits in self.changes.values())

    @property
    def suffix(self) -> str:
        return f" | ⚠ {self.count} divergent commits repo-wide" if self.count else ""


def shared_repo_dir(workspace_root: Path) -> Path:
    """The repository directory every workspace of this repo shares.

    The default workspace holds it at `.jj/repo`; every other workspace has a
    file there naming it, relative to that workspace's `.jj` directory.
    """
    pointer = workspace_root / ".jj" / "repo"
    if pointer.is_dir():
        return pointer.resolve()
    target = pointer.read_text(encoding="utf-8").strip()
    if not target:
        raise ValueError(f"{pointer} is empty")
    return (pointer.parent / target).resolve()


def state_path(workspace_root: Path) -> Path:
    return shared_repo_dir(workspace_root) / "jj-sensei" / "divergence.json"


def probe(jj: Jj, workspace_root: Path) -> Divergence | None:
    """Read the repo-wide divergent set, recording growth as alarms.

    Returns None when jj cannot answer (including a jj too old for the
    revset); callers treat that as silence.
    """
    try:
        op_id = _current_op(jj)
        path = state_path(workspace_root)
    except Exception:  # noqa: BLE001 - a probe never fails its caller
        return None
    saved = _load(path)
    if saved is not None and saved.op_id == op_id:
        return _with_live_alarms(saved)

    try:
        changes = divergent_at(jj, op_id)
    except Exception:  # noqa: BLE001
        return None

    if saved is None:
        # First sight of this repository: whatever is divergent now is the
        # baseline. It is reported by the standing suffix, never as NEW.
        current = Divergence(op_id, changes)
    else:
        grown = {
            change: len(commits)
            for change, commits in changes.items()
            if len(commits) > len(saved.changes.get(change, ()))
        }
        alarms = list(saved.alarms)
        if grown:
            try:
                alarms.extend(_attribute(jj, saved, op_id, grown))
            except Exception:  # noqa: BLE001
                alarms.append(_alarm(None, list(grown.items())))
        current = Divergence(op_id, changes, _prune(alarms, changes))

    # A read-only sandbox can still be warned; it just cannot remember.
    with contextlib.suppress(OSError):
        _store(path, current)
    return _with_live_alarms(current)


def divergent_at(jj: Jj, op_id: str) -> dict[str, list[str]]:
    """Map change id to its visible divergent mutable commits at `op_id`."""
    output = jj.run(
        "--at-op",
        op_id,
        "log",
        "--no-graph",
        "-r",
        DIVERGENT_REVSET,
        "-T",
        _DIVERGENT_TEMPLATE,
        ignore_working_copy=True,
    ).stdout
    changes: dict[str, list[str]] = {}
    for row in output.splitlines():
        parts = row.split()
        if len(parts) == 2:
            changes.setdefault(parts[0], []).append(parts[1])
    return changes


def _current_op(jj: Jj) -> str:
    op_id = jj.run(
        "op", "log", "--no-graph", "-n", "1", "-T", 'id ++ "\\n"', ignore_working_copy=True
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]+", op_id):
        raise ValueError(f"unexpected operation id {op_id!r}")
    return op_id


@dataclass(frozen=True)
class _Operation:
    id: str
    workspace: str
    args: str
    description: str = ""


def _attribute(jj: Jj, saved: Divergence, head: str, grown: dict[str, int]) -> list[Alarm]:
    """Find, for each grown change, the first new operation after which it grew."""
    window, complete = _operations_since(jj, saved.op_id)
    pending = dict(grown)
    blame: dict[str | None, list[tuple[str, int]]] = {}
    operations = {operation.id: operation for operation in window}
    # Oldest first: the culprit is the first op whose result shows the growth.
    # The op log is flattened newest-first, so a concurrent branch and the
    # "reconcile divergent operations" merge that joins it both fall inside
    # the window; growth first visible at the merge is blamed on the merge.
    for index, operation in enumerate(reversed(window)):
        if not pending:
            break
        at = (
            {change: len(commits) for change, commits in divergent_at(jj, operation.id).items()}
            if operation.id != head
            else pending
        )
        for change in list(pending):
            if at.get(change, 0) > len(saved.changes.get(change, ())):
                # When the walk never reached the last-seen op, growth already
                # visible at the oldest op examined happened somewhere earlier.
                culprit = operation.id if complete or index else None
                blame.setdefault(culprit, []).append((change, pending.pop(change)))
    if pending:
        blame.setdefault(None, []).extend(pending.items())
    return [
        _alarm(operations[op] if op is not None else None, changes) for op, changes in blame.items()
    ]


def _operations_since(jj: Jj, last_seen: str) -> tuple[list[_Operation], bool]:
    """Operations newer than `last_seen`, newest first, at most WALK_LIMIT.

    The flag says whether `last_seen` was reached, i.e. the window is whole.
    """
    output = jj.run(
        "op",
        "log",
        "--no-graph",
        "-n",
        str(WALK_LIMIT + 1),
        "-T",
        'json(self) ++ "\\n"',
        ignore_working_copy=True,
    ).stdout
    operations = []
    for row in output.splitlines():
        if not row.strip():
            continue
        item = json.loads(row)
        if item.get("id") == last_seen:
            return operations[:WALK_LIMIT], len(operations) <= WALK_LIMIT
        attributes = item.get("attributes") or item.get("tags") or {}
        operations.append(
            _Operation(
                id=str(item["id"]),
                workspace=str(item.get("workspace_name") or ""),
                args=str(attributes.get("args") or ""),
                description=str(item.get("description") or "").split("\n", 1)[0],
            )
        )
    return operations[:WALK_LIMIT], False


def _alarm(operation: _Operation | None, changes: list[tuple[str, int]]) -> Alarm:
    changes = sorted(changes, key=lambda item: (-item[1], item[0]))
    if len(changes) == 1:
        change, copies = changes[0]
        what = f"{change[:12]} now has {copies} visible copies"
        pronoun = "it"
    else:
        listed = ", ".join(
            f"{change[:12]} ×{copies}" for change, copies in changes[:_LISTED_CHANGES]
        )
        if len(changes) > _LISTED_CHANGES:
            listed += f", +{len(changes) - _LISTED_CHANGES} more"
        what = f"{len(changes)} changes gained visible copies ({listed})"
        pronoun = "them"
    if operation is None:
        origin = "by an operation jj-sensei could not identify"
        op_key = "unknown"
    else:
        origin = f"by op {operation.id[:12]}"
        if operation.description:
            # "reconcile divergent operations" says more than its args do.
            origin += f" ({_shorten_args(operation.description, 48)})"
        if operation.workspace:
            origin += f" in {operation.workspace}"
        if operation.args:
            origin += f": {_shorten_args(operation.args)}"
        op_key = operation.id[:12]
    line = (
        f"jj: ⚠ NEW DIVERGENCE — {what}; created {origin} — "
        f"load jj-sensei harmony; do not build on {pronoun}"
    )
    key = ",".join(f"{change}:{copies}" for change, copies in changes)
    return Alarm(id=f"{op_key}/{key}", line=line, created=time.time())


def _shorten_args(args: str, limit: int = 80) -> str:
    args = _LONG_HEX.sub(r"\1…", args.strip().replace("jj --no-pager ", "jj ", 1))
    args = " ".join(args.split())
    return args if len(args) <= limit else f"{args[: limit - 1]}…"


def _prune(alarms: list[Alarm], changes: dict[str, list[str]]) -> tuple[Alarm, ...]:
    """Keep alarms whose divergence still stands, newest last, bounded."""
    now = time.time()
    kept: dict[str, Alarm] = {}
    for alarm in alarms:
        if now - alarm.created > ALARM_TTL_SECONDS:
            continue
        try:
            # The id is `<op>/<change>:<copies>,...`; see `_alarm`.
            standing = all(
                len(changes.get(change, ())) >= int(copies)
                for change, copies in (
                    part.rsplit(":", 1) for part in alarm.id.split("/", 1)[1].split(",")
                )
            )
        except (IndexError, ValueError):
            standing = False  # written by someone else; drop it
        if standing:
            kept.setdefault(alarm.id, alarm)
    return tuple(list(kept.values())[-MAX_ALARMS:])


def _with_live_alarms(divergence: Divergence) -> Divergence:
    now = time.time()
    live = tuple(alarm for alarm in divergence.alarms if now - alarm.created <= ALARM_TTL_SECONDS)
    return Divergence(divergence.op_id, divergence.changes, live)


def _load(path: Path) -> Divergence | None:
    """Read saved state; anything missing, corrupt, or foreign is no state."""
    try:
        item = json.loads(path.read_text(encoding="utf-8"))
        if item.get("version") != STATE_VERSION:
            return None
        return Divergence(
            op_id=str(item["op_id"]),
            changes={
                str(change): [str(commit) for commit in commits]
                for change, commits in item["changes"].items()
            },
            alarms=tuple(
                Alarm(id=str(alarm["id"]), line=str(alarm["line"]), created=float(alarm["created"]))
                for alarm in item.get("alarms", [])
            ),
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _store(path: Path, divergence: Divergence) -> None:
    """Replace the shared state atomically; concurrent hooks may race here."""
    payload = {
        "version": STATE_VERSION,
        "op_id": divergence.op_id,
        "changes": divergence.changes,
        "alarms": [
            {"id": alarm.id, "line": alarm.line, "created": alarm.created}
            for alarm in divergence.alarms
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f"{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=1, sort_keys=True)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)
