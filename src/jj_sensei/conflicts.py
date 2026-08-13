#!/usr/bin/env python3
"""
jj-sensei conflict helper for jj repos using the default diff+snapshot marker format.

  scripts/conflicts list
      List conflicted files (via jj resolve --list).

  scripts/conflicts show [FILE ...]
      Print only the conflict hunks with line numbers — not the whole file.
      Omit FILE to show all conflicted files.

  scripts/conflicts show --json [FILE ...]
      Same but as a JSON array — each element has: file, hunk, total,
      start_line, end_line, diff_header, diff_side, diff_base,
      snap_header, snapshot.

  scripts/conflicts accept FILE snapshot|diff|base|stack|stack-snap-first|sort
      Resolve every supported hunk in FILE by choosing a side, composing pure
      additions, or conservatively merging additions to a sorted list.
"""

import argparse
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

from . import use_utf8_output
from .jj import Jj, JjError

_START = re.compile(r"^(<{7,}) conflict (\d+) of (\d+)$")
_GENERIC_START = re.compile(r"^<{7,}", re.MULTILINE)
_LINE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+")


def workspace_root(start=None):
    """Find the workspace containing `start`, or None.

    Derived from the path in hand rather than cached at import time, so the
    answer cannot go stale when the process changes directory — and so a file
    outside any workspace is reported as such instead of being described
    relative to wherever the process happened to start.
    """
    directory = Path(start or Path.cwd()).resolve()
    while True:
        if (directory / ".jj").exists():
            return directory
        if directory == directory.parent:
            return None
        directory = directory.parent


# ---------------------------------------------------------------------------
# Work-tree IO
# ---------------------------------------------------------------------------


def _read_source(path):
    """Read a work-tree file byte-faithfully.

    `newline=""` disables universal-newline translation, so a CRLF file stays
    CRLF instead of being silently rewritten to LF by the resolution round-trip.
    """
    return path.read_text(encoding="utf-8", newline="")


def _write_source(path, text):
    return path.write_text(text, encoding="utf-8", newline="")


def _split_line(line):
    """Split a raw line into its text and its exact terminator."""
    for terminator in ("\r\n", "\n"):
        if line.endswith(terminator):
            return line[: -len(terminator)], terminator
    return line, ""


def _split_lines(text):
    """Split into terminator-keeping lines, breaking only on CR, LF, and CRLF.

    `str.splitlines` also breaks on form feed and the Unicode separators, which
    would silently reflow source files that use them.
    """
    return _LINE.findall(text)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def parse_file(path):
    """Return (hunks, lines) — hunks is a list of dicts, lines is the raw file."""
    text = _read_source(path)
    lines = _split_lines(text)
    hunks = []
    i = 0
    while i < len(lines):
        m = _START.match(_split_line(lines[i])[0])
        if m:
            n = len(m.group(1))
            end_pfx = ">" * n
            j = i + 1
            while j < len(lines) and not lines[j].startswith(end_pfx + " conflict"):
                j += 1
            sides = _parse_sides(lines[i + 1 : j], n)
            root = workspace_root(path.parent)
            try:
                file_str = str(path.resolve().relative_to(root)) if root else str(path)
            except ValueError:
                file_str = str(path)
            hunks.append(
                {
                    "file": file_str,
                    "hunk": int(m.group(2)),
                    "total": int(m.group(3)),
                    "start_line": i + 1,  # 1-indexed
                    "end_line": j + 1,  # 1-indexed
                    "_start": i,  # 0-indexed for splicing
                    "_end": j,
                    "raw": lines[i : j + 1],
                    **sides,
                }
            )
            i = j + 1
        else:
            i += 1
    return hunks, lines


def _has_unparsed_conflict(path, hunks):
    """Return true when markers exist but are not default diff+snapshot hunks."""
    return not hunks and bool(_GENERIC_START.search(_read_source(path)))


def _parse_sides(inner, n):
    diff_m, snap_m, cont_m = "%" * n, "+" * n, "\\" * n
    sections, cur_kind, cur = [], None, []

    for line in inner:
        s = _split_line(line)[0]
        if s.startswith(diff_m):
            if cur_kind:
                sections.append((cur_kind, cur))
            cur_kind, cur = "diff", [s]
        elif s.startswith(snap_m):
            if cur_kind:
                sections.append((cur_kind, cur))
            cur_kind, cur = "snapshot", [s]
        elif s.startswith(cont_m):
            if cur:
                cur.append(s)
        elif cur_kind is not None:
            cur.append(line)

    if cur_kind:
        sections.append((cur_kind, cur))

    result = {
        "diff_header": None,
        "diff_side": [],
        "diff_base": [],
        "snap_header": None,
        "snapshot": [],
    }
    has_removal = False

    for kind, sec in sections:
        if kind == "diff":
            result["diff_header"] = sec[0]
            for line in sec[1:]:
                # Rebuild each side with the terminator the file actually used,
                # so a CRLF work tree survives the round-trip.
                s, terminator = _split_line(line)
                if s.startswith(" "):
                    result["diff_base"].append(s[1:] + terminator)
                    result["diff_side"].append(s[1:] + terminator)
                elif s.startswith("-"):
                    has_removal = True
                    result["diff_base"].append(s[1:] + terminator)
                elif s.startswith("+"):
                    result["diff_side"].append(s[1:] + terminator)
        elif kind == "snapshot":
            result["snap_header"] = sec[0]
            result["snapshot"] = list(sec[1:])

    diff_sections = sum(1 for kind, _ in sections if kind == "diff")
    snapshot_sections = sum(1 for kind, _ in sections if kind == "snapshot")

    # jj materializes an N-sided conflict as N-1 %%% diff sections (or several
    # +++ ones). The loop above CONCATENATES them into one diff_side/diff_base,
    # so any per-side resolution built from those lists would be garbage — flag
    # the hunk so accept/auto decline it instead of silently corrupting the file.
    result["many_sided"] = diff_sections > 1 or snapshot_sections > 1
    # Mechanical resolution is defined only for a two-sided conflict in jj's
    # default diff+snapshot marker style. In particular, accepting an empty
    # parsed side from `git`-style markers would silently delete the hunk.
    result["supported"] = diff_sections == 1 and snapshot_sections == 1

    diff_insertions = _insertions_by_gap(result["diff_base"], result["diff_side"])
    snapshot_insertions = _insertions_by_gap(result["diff_base"], result["snapshot"])
    result["_diff_insertions"] = diff_insertions
    result["_snapshot_insertions"] = snapshot_insertions

    # Both sides are purely additive relative to the base when they can each be
    # represented only as insertions at gaps between unchanged base lines.
    result["stackable"] = (
        not has_removal
        and result["supported"]
        and diff_insertions is not None
        and snapshot_insertions is not None
        and any(diff_insertions)
        and any(snapshot_insertions)
    )
    result["has_removal"] = has_removal
    return result


def _multiset_diff(super_lines, sub_lines):
    """Lines in super_lines not accounted for by sub_lines (multiset difference)."""
    remaining = Counter(sub_lines)
    extra = []
    for line in super_lines:
        if remaining.get(line, 0) > 0:
            remaining[line] -= 1
        else:
            extra.append(line)
    return extra


def _insertions_by_gap(base, side):
    """Map a pure-add edit to insertion lists before/between/after base lines."""
    gaps = [[] for _ in range(len(base) + 1)]
    matcher = SequenceMatcher(a=base, b=side, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag != "insert" or i1 != i2:
            return None
        gaps[i1].extend(side[j1:j2])
    return gaps


def _stack_resolution(hunk, snapshot_first=False):
    """Compose two pure-add sides while preserving each base line exactly once."""
    first_key, second_key = (
        ("_snapshot_insertions", "_diff_insertions")
        if snapshot_first
        else ("_diff_insertions", "_snapshot_insertions")
    )
    first, second = hunk[first_key], hunk[second_key]
    result = []
    for gap in range(len(hunk["diff_base"]) + 1):
        result.extend(first[gap])
        result.extend(second[gap])
        if gap < len(hunk["diff_base"]):
            result.append(hunk["diff_base"][gap])
    return result


def _is_sorted(seq):
    return all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1))


def _sorted_merge_resolution(hunk, lines):
    """
    Resolve `hunk` iff it is two pure-add edits into an already-sorted run of >=3
    lines. Return (new_file_lines, n_adds) on success, else (None, reason).
    """
    if not hunk.get("supported"):
        reason = "many-sided conflict" if hunk.get("many_sided") else "unsupported marker style"
        return None, reason
    # A many-sided hunk's parsed sides are concatenations of several sides —
    # nothing built from them is a valid resolution.
    if hunk.get("many_sided"):
        return None, "many-sided conflict"
    # 1. Both sides must be pure adds.
    if hunk.get("has_removal"):
        return None, "removal present"
    # Ordinary diff+snapshot labels use `\\\\\\\` continuation lines for the
    # "to:" commit. Decline only jj's explicit missing-newline annotation.
    if any("(no terminating newline)" in line for line in hunk["raw"]):
        return None, "no-newline at EOF"

    base = hunk["diff_base"]
    # The snapshot (+++) side is taken literally, so its deletions aren't in
    # has_removal (which only sees the %%% diff side). If any base line is missing
    # from the snapshot, that side removed it — decline (not a pure-add conflict).
    if _multiset_diff(base, hunk["snapshot"]):
        return None, "removal present (snapshot side)"
    if not _is_sorted(base):
        return None, "base region not sorted"

    x_adds = _multiset_diff(hunk["diff_side"], base)
    y_adds = _multiset_diff(hunk["snapshot"], base)
    adds = x_adds + y_adds
    if not adds:
        return None, "no additions"

    # 2. Virtual base file: this hunk's markers replaced by its base lines; any
    #    other hunk's markers remain as ordinary boundary lines.
    before = lines[: hunk["_start"]]
    after = lines[hunk["_end"] + 1 :]
    virtual = before + base + after
    p = len(before)
    q = p + len(base)

    # 3. Maximal non-decreasing run covering the base region.
    if p == q:  # empty base region: run must straddle the junction at p
        if p == 0 or p >= len(virtual) or virtual[p - 1] > virtual[p]:
            return None, "no sorted run at insertion point"
        lo, hi = p - 1, p + 1
    else:
        lo, hi = p, q
    while lo > 0 and virtual[lo - 1] <= virtual[lo]:
        lo -= 1
    while hi < len(virtual) and virtual[hi - 1] <= virtual[hi]:
        hi += 1

    run = virtual[lo:hi]
    if len(run) < 3:
        return None, f"sorted run too short ({len(run)} < 3)"

    # 4. Merge run + new adds (dedup new lines only), re-sort. Existing run lines
    #    are preserved as-is; an add equal to an existing/other-side line is kept once.
    merged = list(run)
    seen = set(run)
    for a in adds:
        if a not in seen:
            merged.append(a)
            seen.add(a)
    merged.sort()

    new_virtual = virtual[:lo] + merged + virtual[hi:]
    return new_virtual, len(merged) - len(run)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def _conflicted_files():
    return Jj().conflict_files()


def _resolve_path(filepath):
    root = workspace_root()
    candidates = [Path(filepath)] if root is None else [root / filepath, Path(filepath)]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _resolve_targets(files):
    """Default to every conflicted file. Returns (filepath, path) pairs, warning
    about and skipping paths that don't resolve — or None when there was nothing
    to target at all (already reported to the user)."""
    if not files:
        files = _conflicted_files()
        if not files:
            print("No conflicts found.")
            return None
    out = []
    for filepath in files:
        path = _resolve_path(filepath)
        if path is None:
            print(f"Not found: {filepath}", file=sys.stderr)
            continue
        out.append((filepath, path))
    return out


def cmd_list(_args):
    result = Jj().resolve_list()
    sys.stdout.write(result.stdout)
    if result.returncode:
        sys.stderr.write(result.stderr)
    return result.returncode


def cmd_show(args):
    as_json = "--json" in args
    targets = _resolve_targets([a for a in args if a != "--json"])
    if targets is None:
        return 0

    all_hunks = []
    unsupported = []
    for filepath, path in targets:
        hunks, _ = parse_file(path)
        all_hunks.extend(hunks)
        if _has_unparsed_conflict(path, hunks):
            unsupported.append(filepath)

    if as_json:
        out = []
        for h in all_hunks:
            out.append({k: v for k, v in h.items() if not k.startswith("_") and k != "raw"})
        print(json.dumps(out, indent=2))
        for filepath in unsupported:
            print(
                f"Unsupported conflict marker style in {filepath}; inspect it manually.",
                file=sys.stderr,
            )
        return 1 if unsupported else 0

    if not all_hunks and not unsupported:
        print("No conflict hunks found.")
        return 0

    for h in all_hunks:
        print("─" * 64)
        print(
            f"File: {h['file']}  |  hunk {h['hunk']}/{h['total']}  |  lines {h['start_line']}–{h['end_line']}"
        )
        if h["diff_header"]:
            print(f"  diff-side : {h['diff_header']}")
        if h["snap_header"]:
            print(f"  snapshot  : {h['snap_header']}")
        print()
        sys.stdout.writelines(h["raw"])
        print()
    for filepath in unsupported:
        print(
            f"Unsupported conflict marker style in {filepath}; inspect it manually.",
            file=sys.stderr,
        )
    return 1 if unsupported else 0


def cmd_accept(args):
    if len(args) < 2:
        print(
            "Usage: scripts/conflicts accept FILE snapshot|diff|base|stack|stack-snap-first|sort",
            file=sys.stderr,
        )
        return 1
    filepath, side = args[0], args[1]
    valid = ("snapshot", "diff", "base", "stack", "stack-snap-first", "sort")
    if side not in valid:
        print(f"Unknown side '{side}'. Choose: {', '.join(valid)}", file=sys.stderr)
        return 1
    path = _resolve_path(filepath)
    if path is None:
        print(f"Not found: {filepath}", file=sys.stderr)
        return 1
    if side == "sort":
        resolved, left = _auto_resolve_file(path, filepath, dry=False)
        print(f"  ---\n  resolved {resolved} hunk(s), {left} left for review")
        return 0
    hunks, lines = parse_file(path)
    if not hunks:
        if _has_unparsed_conflict(path, hunks):
            print(
                f"Unsupported conflict marker style in {filepath}; resolve it by hand.",
                file=sys.stderr,
            )
            return 1
        print(f"No conflicts in {filepath}")
        return 0

    key_map = {"snapshot": "snapshot", "diff": "diff_side", "base": "diff_base"}
    resolved = skipped = 0
    for h in reversed(hunks):
        # Parsed sides are safe to apply only for a two-sided default-style hunk.
        if not h["supported"]:
            reason = "many-sided conflict" if h["many_sided"] else "unsupported marker style"
            print(f"  {filepath} hunk {h['hunk']}/{h['total']}: left ({reason} — resolve by hand)")
            skipped += 1
            continue
        if side in key_map:
            resolution = h[key_map[side]]
        elif side == "stack":
            if not h["stackable"]:
                print(
                    f"  {filepath} hunk {h['hunk']}/{h['total']}: left (not two pure additions — resolve by hand)"
                )
                skipped += 1
                continue
            resolution = _stack_resolution(h)
        else:  # stack-snap-first
            if not h["stackable"]:
                print(
                    f"  {filepath} hunk {h['hunk']}/{h['total']}: left (not two pure additions — resolve by hand)"
                )
                skipped += 1
                continue
            resolution = _stack_resolution(h, snapshot_first=True)
        lines[h["_start"] : h["_end"] + 1] = resolution
        resolved += 1

    if resolved:
        _write_source(path, "".join(lines))
    left = f", {skipped} unsupported hunk(s) left" if skipped else ""
    print(f"Resolved {resolved} hunk(s) in {filepath} (accepted {side} side){left}.")
    return 1 if skipped else 0


def _report(filepath, hunk, status, msg):
    label = "sorted-merge ✓" if status == "ok" else "left"
    print(f"  {filepath} hunk {hunk['hunk']}/{hunk['total']}: {label} ({msg})")


def _auto_resolve_file(path, filepath, dry):
    """Resolve every qualifying hunk in one file. Returns (resolved, left)."""
    resolved = left = 0
    declined = set()  # raw-text signatures of hunks we've already left
    while True:
        hunks, lines = parse_file(path)
        if _has_unparsed_conflict(path, hunks):
            print(f"  {filepath}: left (unsupported marker style)")
            left += 1
            break
        pending = [h for h in hunks if "".join(h["raw"]) not in declined]
        if not pending:
            break
        progressed = False
        for h in pending:
            new_lines, info = _sorted_merge_resolution(h, lines)
            if new_lines is None:
                _report(filepath, h, "left", info)
                declined.add("".join(h["raw"]))
                left += 1
                continue
            _report(filepath, h, "ok", f"{info} adds")
            resolved += 1
            if dry:
                # Don't rewrite; mark resolved so we don't loop on it forever.
                declined.add("".join(h["raw"]))
            else:
                _write_source(path, "".join(new_lines))
                progressed = True
                break  # re-parse the rewritten file
        if not progressed:
            break
    return resolved, left


def cmd_auto(args):
    dry = "--dry-run" in args
    targets = _resolve_targets([a for a in args if not a.startswith("--")])
    if targets is None:
        return 0
    total_resolved = total_left = 0
    for filepath, path in targets:
        resolved, left = _auto_resolve_file(path, filepath, dry)
        total_resolved += resolved
        total_left += left
    print("  ---")
    suffix = " (dry-run, nothing written)" if dry else ""
    print(f"  resolved {total_resolved} hunk(s), {total_left} left for review{suffix}")
    # Hunks left for review are the conservative outcome, not a failure.
    return 0


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------


def parser():
    result = argparse.ArgumentParser(
        prog="conflicts",
        description="Inspect or conservatively resolve jj diff+snapshot conflict markers.",
    )
    commands = result.add_subparsers(dest="command", required=True)

    commands.add_parser(
        "list",
        help="list conflicted files",
        description="List files with conflicts recorded in the current jj revision.",
    )

    show = commands.add_parser(
        "show",
        help="show conflict hunks",
        description="Print conflict hunks rather than entire files.",
    )
    show.add_argument(
        "--json",
        action="store_true",
        help="emit structured hunk data, including whether each hunk is stackable",
    )
    show.add_argument("files", metavar="FILE", nargs="*", help="files to inspect (default: all)")

    accept = commands.add_parser(
        "accept",
        help="apply one understood resolution strategy",
        description=(
            "Resolve every supported hunk in one file using an explicitly selected strategy. "
            "Unsupported hunks are left untouched."
        ),
    )
    accept.add_argument("file", metavar="FILE", help="conflicted file to resolve")
    accept.add_argument(
        "strategy",
        choices=("snapshot", "diff", "base", "stack", "stack-snap-first", "sort"),
        help=(
            "snapshot/diff/base selects one side; stack variants combine two pure additions; "
            "sort conservatively merges additions to a sorted list"
        ),
    )

    auto = commands.add_parser(
        "auto",
        help="merge provably safe sorted-list additions",
        description=(
            "Conservatively merge two pure additions into an existing sorted run of at least "
            "three lines. Leave every unproven hunk untouched."
        ),
    )
    auto.add_argument(
        "--dry-run",
        action="store_true",
        help="report qualifying resolutions without writing files",
    )
    auto.add_argument("files", metavar="FILE", nargs="*", help="files to inspect (default: all)")
    return result


def main(argv=None):
    use_utf8_output()
    if argv is None:
        argv = sys.argv[1:]
    command_parser = parser()
    if not argv:
        command_parser.print_help()
        return 1
    args = command_parser.parse_args(argv)
    try:
        if args.command == "list":
            return cmd_list([])
        if args.command == "show":
            return cmd_show((["--json"] if args.json else []) + args.files)
        if args.command == "accept":
            return cmd_accept([args.file, args.strategy])
        if args.command == "auto":
            return cmd_auto((["--dry-run"] if args.dry_run else []) + args.files)
    except JjError as error:
        print(f"conflicts: {error}", file=sys.stderr)
        if error.stderr.strip():
            print(error.stderr.rstrip(), file=sys.stderr)
        return 2
    except (OSError, RuntimeError) as error:
        print(f"conflicts: {error}", file=sys.stderr)
        return 2
    raise AssertionError(args.command)


if __name__ == "__main__":
    sys.exit(main())
