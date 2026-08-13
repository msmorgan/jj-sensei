"""Command-line entry point for the packaged jj-sensei helpers."""

from __future__ import annotations

import argparse
import sys

from . import conflicts, documentation, interpolate, knowledge, use_utf8_output
from .repair import run_converge, run_repair, run_resolve
from .setup import run_setup
from .status import run_status


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="jj-sensei")
    commands = result.add_subparsers(dest="command", required=True)
    repair = commands.add_parser(
        "repair",
        help="update stale state, converge divergence, and resolve conflicts",
        description=(
            "Run the resumable one-stop harmony workflow: update a stale workspace, converge "
            "safe divergent successors, then resolve mutable conflicts oldest-first."
        ),
    )
    repair.epilog = (
        "Exit 0 when clean; 1 for a requested edit; 70 on internal error; "
        "75 if locked; 80 when human judgment is required."
    )
    resolve = commands.add_parser(
        "resolve",
        help="walk mutable conflicts oldest-first",
        description="Run only the resumable oldest-first mutable-conflict walk.",
    )
    resolve.epilog = (
        "Exit 0 when clean; 1 for a requested edit; 70 on internal error; "
        "75 if locked; 80 when human judgment is required."
    )
    converge = commands.add_parser(
        "converge",
        help="converge equivalent divergent working-copy successors",
        description=(
            "Keep the sole nonempty or one of the byte-identical divergent working-copy "
            "successors; refuse ambiguous work."
        ),
    )
    converge.epilog = (
        "Exit 0 on success; 70 on internal error; 75 if locked; 80 when human judgment is required."
    )
    setup = commands.add_parser(
        "setup",
        help="install the workspace immutability aliases",
        description=("Install and audit jj-sensei's repository-level workspace-isolation aliases."),
    )
    setup.add_argument(
        "--check", action="store_true", help="audit config context and topology only"
    )
    setup.epilog = (
        "Exit 0 when verified; 70 on internal error; 75 if locked; "
        "80 when human judgment is required."
    )
    status = commands.add_parser(
        "status",
        help="snapshot and print compact agent-oriented workspace status",
    )
    status.add_argument(
        "--porcelain",
        action="store_true",
        help="print KEY<TAB>LINE for hook suppression",
    )
    conflict_parser = commands.add_parser(
        "conflicts",
        help="inspect or resolve materialized conflicts",
        description="Inspect or conservatively resolve jj diff+snapshot conflict markers.",
    )
    conflict_parser.add_argument("args", nargs=argparse.REMAINDER)
    rtfm_parser = commands.add_parser("rtfm", help="read the installed jj documentation")
    rtfm_parser.add_argument("args", nargs=argparse.REMAINDER)
    rtfd_parser = commands.add_parser("rtfd", help="read Markdown docs shipped with jj")
    rtfd_parser.add_argument("args", nargs=argparse.REMAINDER)
    interpolate_parser = commands.add_parser(
        "interpolate",
        help="construct a state that files-and-lines selection cannot express",
    )
    interpolate_parser.add_argument("args", nargs=argparse.REMAINDER)
    return result


def main(argv: list[str] | None = None) -> int:
    use_utf8_output()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    if raw_argv[:1] == ["rtfm"]:
        return knowledge.main(raw_argv[1:])
    if raw_argv[:1] == ["rtfd"]:
        return documentation.main(raw_argv[1:])
    if raw_argv[:1] == ["conflicts"]:
        return conflicts.main(raw_argv[1:])
    if raw_argv[:1] == ["interpolate"]:
        return interpolate.main(raw_argv[1:])
    args = parser().parse_args(raw_argv)
    if args.command == "repair":
        return run_repair()
    if args.command == "resolve":
        return run_resolve()
    if args.command == "converge":
        return run_converge()
    if args.command == "setup":
        return run_setup(check_only=args.check)
    if args.command == "status":
        return run_status(porcelain=args.porcelain)
    if args.command == "conflicts":
        return conflicts.main(args.args)
    if args.command == "rtfm":
        return knowledge.main(args.args)
    if args.command == "rtfd":
        return documentation.main(args.args)
    if args.command == "interpolate":
        return interpolate.main(args.args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
