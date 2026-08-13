"""Read one file's earlier content out of jj's operation snapshots."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from . import use_utf8_output
from .jj import Jj, JjError

_OPERATION_ID = re.compile(r"^[0-9a-f]{4,}$")
_OPERATION_TEMPLATE = (
    "concat("
    "'{\"id\":', json(self.id().short(12)), "
    "',\"snapshot\":', json(self.snapshot()), "
    "',\"time\":', json(self.time().end().format(\"%Y-%m-%d %H:%M:%S\")), "
    "'}', \"\\n\")"
)


@dataclass(frozen=True)
class Snapshot:
    """One operation that snapshotted the working copy."""

    operation_id: str
    time: str


@dataclass(frozen=True)
class Recovered:
    """A file state found at one snapshot operation."""

    snapshot: Snapshot
    digest: str
    size: int


def safe_operation(value: str) -> str:
    """Validate an operation ID before passing it to `--at-op`."""
    if not _OPERATION_ID.fullmatch(value):
        raise ValueError(f"unsafe operation identifier: {value!r}")
    return value


def snapshots(jj: Jj, limit: int | None = None) -> list[Snapshot]:
    """List the snapshot operations, newest first."""
    arguments = ["op", "log", "--no-graph", "-T", _OPERATION_TEMPLATE]
    if limit is not None:
        arguments.extend(["-n", str(limit)])
    result = jj.run(*arguments, ignore_working_copy=True)
    return [
        Snapshot(operation_id=item["id"], time=item["time"])
        for item in (json.loads(line) for line in result.stdout.splitlines() if line.strip())
        if item["snapshot"]
    ]


def content_at(jj: Jj, operation_id: str, path: str) -> str | None:
    """Read `path` from the working-copy commit as of one operation."""
    result = jj.run(
        f"--at-op={safe_operation(operation_id)}",
        "file",
        "show",
        "-r",
        "@",
        path,
        check=False,
    )
    return None if result.returncode else result.stdout


def distinct_states(jj: Jj, path: str, limit: int | None = None) -> list[Recovered]:
    """Find the snapshots holding `path`, keeping only content transitions.

    Consecutive snapshots usually hold identical content, so reporting every
    one of them buries the states worth looking at.
    """
    found: list[Recovered] = []
    previous: str | None = None
    for snapshot in snapshots(jj, limit=limit):
        content = content_at(jj, snapshot.operation_id, path)
        if content is None:
            previous = None
            continue
        digest = hashlib.sha256(content.encode("utf-8", "surrogateescape")).hexdigest()
        if digest != previous:
            found.append(Recovered(snapshot=snapshot, digest=digest, size=len(content)))
        previous = digest
    return found


def render(path: str, states: list[Recovered]) -> str:
    if not states:
        return (
            f"no operation snapshot contains {path}\n"
            "Only snapshotted states are recoverable; edits between snapshots were never recorded."
        )
    lines = [f"{len(states)} distinct recorded states of {path}, newest first:"]
    for state in states:
        lines.append(
            f"  {state.snapshot.operation_id}  {state.snapshot.time}  "
            f"{state.size} bytes  {state.digest[:12]}"
        )
    lines.append(f"Read one with: recover-file show OPERATION {path}")
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="recover-file",
        description=(
            "Read a file's earlier content out of jj operation snapshots. Strictly read-only: "
            "it never restores the repository to an earlier operation."
        ),
    )
    commands = result.add_subparsers(dest="command", required=True)
    listing = commands.add_parser(
        "list",
        help="show the snapshot operations holding distinct content for a path",
    )
    listing.add_argument("path", metavar="PATH", help="workspace path to look for")
    listing.add_argument(
        "-n",
        "--limit",
        type=int,
        default=None,
        help="examine only this many of the most recent operations",
    )
    show = commands.add_parser("show", help="print a path's content at one operation")
    show.add_argument("operation", metavar="OPERATION", help="operation ID from `list`")
    show.add_argument("path", metavar="PATH", help="workspace path to print")
    return result


def run_list(path: str, limit: int | None = None, cwd: Path | str | None = None) -> int:
    jj = Jj(cwd)
    try:
        states = distinct_states(jj, path, limit=limit)
    except JjError as error:
        print(f"recover-file: {error.stderr.strip() or error}", file=sys.stderr)
        return 2
    except (RuntimeError, ValueError) as error:
        print(f"recover-file: {error}", file=sys.stderr)
        return 2
    print(render(path, states))
    return 0


def run_show(operation: str, path: str, cwd: Path | str | None = None) -> int:
    jj = Jj(cwd)
    try:
        content = content_at(jj, operation, path)
    except JjError as error:
        print(f"recover-file: {error.stderr.strip() or error}", file=sys.stderr)
        return 2
    except (RuntimeError, ValueError) as error:
        print(f"recover-file: {error}", file=sys.stderr)
        return 2
    if content is None:
        print(f"recover-file: no {path} at operation {operation}", file=sys.stderr)
        return 1
    print(content, end="")
    return 0


def main(argv: list[str] | None = None) -> int:
    use_utf8_output()
    args = parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    if args.command == "list":
        return run_list(args.path, limit=args.limit)
    if args.command == "show":
        return run_show(args.operation, args.path)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
