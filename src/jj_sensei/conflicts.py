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
      start_line, end_line, fingerprint, sides, diff_header, diff_side,
      diff_base, snap_header, snapshot.

  scripts/conflicts accept FILE SIDE [--hunk N --expect FINGERPRINT]
      Resolve every supported hunk in FILE, or only hunk N, by choosing a side
      (snapshot|diff|base, a role such as `destination`/`rebased`, or a change
      ID from the hunk's labels), composing pure additions (stack,
      stack-snap-first), or conservatively merging a sorted list (sort).

  scripts/conflicts replace FILE N --expect FINGERPRINT [--from PATH]
      Replace hunk N, markers included, with content from PATH or stdin.

  scripts/conflicts auto [--dry-run] [FILE ...]
      Resolve only hunks whose line merge is provably safe: two additions to a
      sorted list, or two sides whose edits touch but never overlap.
"""

import argparse
import hashlib
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
# A side label as jj writes it after the marker run, e.g.
#   diff from: prxwxlkq 7abd6bba "base" (parents of rebased revision)
#          to: wxtpllkt a2dfdd18 "one" (rebase destination)
#   psxzqytx a3c804b9 "two" (rebased revision) (no terminating newline)
_LABEL = re.compile(
    r'^\s*(?:diff from:|to:)?\s*(?P<change>[a-z]+) (?P<commit>[0-9a-f]+) "(?P<desc>.*)"'
    r"(?P<tail>(?: \([^()]*\))*)\s*$"
)
_NO_NEWLINE = "no terminating newline"
_MARKER_LINE = re.compile(r"^(?:<{7,}|>{7,}) conflict \d+ of \d+", re.MULTILINE)


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
    with path.open(encoding="utf-8", newline="") as handle:
        return handle.read()


def _write_source(path, text):
    with path.open("w", encoding="utf-8", newline="") as handle:
        return handle.write(text)


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
            inner = "".join(lines[i + 1 : j])
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
                    # Hash only what lies between the markers, so a hunk keeps
                    # its fingerprint while other hunks are resolved around it.
                    "fingerprint": hashlib.sha256(inner.encode("utf-8")).hexdigest()[:8],
                    "_terminated": j < len(lines),
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
        "sides": [],
    }
    has_removal = False

    for kind, sec in sections:
        if kind == "diff":
            result["diff_header"] = sec[0]
            labels = [sec[0][n:]] + [line[n:] for line in sec[1:] if line.startswith(cont_m)]
            from_label = labels[0].strip().removeprefix("diff from:")
            to_label = next((label for label in labels[1:] if "to:" in label), "")
            result["sides"].append(_side_label("base", from_label))
            result["sides"].append(_side_label("diff", to_label.strip().removeprefix("to:")))
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
            result["sides"].append(_side_label("snapshot", sec[0][n:]))

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
    # jj gives every term a final newline when any lacks one, annotates the
    # label of each term that lacked it, and drops the closing marker's own.
    result["no_newline"] = any(side["no_newline"] for side in result["sides"])
    return result


def _side_label(name, text):
    """Describe one side from the label jj wrote after its marker."""
    text = text.strip()
    side = {
        "name": name,
        "change_id": None,
        "commit_id": None,
        "description": None,
        "role": None,
        "label": text,
        "no_newline": f"({_NO_NEWLINE})" in text,
    }
    match = _LABEL.match(text)
    if match:
        notes = re.findall(r"\(([^()]*)\)", match.group("tail"))
        roles = [note for note in notes if note != _NO_NEWLINE]
        side.update(
            change_id=match.group("change"),
            commit_id=match.group("commit"),
            description=match.group("desc"),
            role=" ".join(roles) or None,
        )
    return side


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

    # 4. Merge run + new adds, re-sort. Dropping an added line that already
    #    appears elsewhere is only sound if identical lines are interchangeable.
    #    That holds for a sorted list — a repeated import or allowlist entry is
    #    genuinely redundant — and fails for record-structured text, where
    #    `[[package]]` occurs once per record and `version = "0.0.0"` once per
    #    unversioned crate. A run being sorted is evidence of a list, not proof,
    #    so decline instead of deduping. Nothing is lost on a genuine list: there
    #    a colliding add is a no-op, so the declined resolution was a no-op too.
    #    The one dedup that stays is both sides making the *same* addition.
    kept = x_adds if Counter(x_adds) == Counter(y_adds) else adds
    if len(set(kept)) != len(kept):
        return None, "sides add overlapping lines (not a sorted list)"
    if set(kept) & set(run):
        return None, "addition already present in the run (not a sorted list)"

    merged = sorted(run + kept)
    new_virtual = virtual[:lo] + merged + virtual[hi:]
    return new_virtual, len(merged) - len(run)


# An edit replaces base[start:end] with `lines`; start == end is an insertion.
# jj reports edits that merely *touch* as a conflict, the shape agents met most
# often: one side edits line N, the other line N+1. Two sides' edits compose
# without a choice when no base line is changed by both and no point receives
# insertions from both. That is necessary but not sufficient: a line inserted
# beside the other side's change was written next to a line that is gone or
# different, and no textual measure can tell whether it still belongs there
# (a comment beside a call whose arguments flipped, a body line under a negated
# condition). So two touching edits compose only when neither inserts lines:
# both replace n lines with n, or one is a pure deletion.


def _side_edits(base, side):
    matcher = SequenceMatcher(a=base, b=side, autojunk=False)
    return [
        (i1, i2, tuple(side[j1:j2]))
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


def _inserts_lines(edit):
    """Whether an edit adds lines beyond a line-for-line rewrite of its range.

    A replace of n lines by m > n hides an insertion whose position inside the
    range is unknown, so it counts as one.
    """
    start, end, lines = edit
    return len(lines) > end - start


def _line_for_line_or_deletion(edit):
    start, end, lines = edit
    return len(lines) in (0, end - start)


def _inside(insertion, change):
    return insertion[0] == insertion[1] and change[0] < insertion[0] < change[1]


def _clash(ours, theirs):
    """Why two edits from different sides cannot both apply, or None."""
    our_start, our_end, _ = ours
    their_start, their_end, _ = theirs
    if our_start == our_end == their_start == their_end:
        return "both sides insert at the same point"
    if _inside(ours, theirs) or _inside(theirs, ours):
        return "an insertion lands inside the other side's change"
    if our_start < their_end and their_start < our_end:
        return "both sides change the same line"
    if our_end != their_start and their_end != our_start:
        return None  # an unchanged base line separates them
    if _inserts_lines(ours) or _inserts_lines(theirs):
        return "a side inserts lines beside the other side's change"
    if not (_line_for_line_or_deletion(ours) and _line_for_line_or_deletion(theirs)):
        return "a side shortens lines beside the other side's change"
    return None


def _disjoint_resolution(hunk):
    """Compose two sides whose edits touch but never overlap or insert.

    Return (resolution_lines, info) on success, else (None, reason).
    """
    if not hunk.get("supported"):
        reason = "many-sided conflict" if hunk.get("many_sided") else "unsupported marker style"
        return None, reason
    if any("(no terminating newline)" in line for line in hunk["raw"]):
        return None, "no-newline at EOF"

    base = hunk["diff_base"]
    # Each side is re-diffed against the base. That alignment is unique only if
    # every base line is distinct and no side adds a copy of one; otherwise a
    # change could be read at more than one position.
    if len(set(base)) != len(base):
        return None, "base region repeats a line"
    edits = []
    for side in (hunk["diff_side"], hunk["snapshot"]):
        side_edits = _side_edits(base, side)
        if not side_edits:
            return None, "one side leaves the region unchanged"
        if any(set(lines) & set(base) for _, _, lines in side_edits):
            return None, "a side adds a line the base region already has"
        edits.append(side_edits)

    # The same edit made on both sides is made once.
    shared = set(edits[0]) & set(edits[1])
    ours = [edit for edit in edits[0] if edit not in shared]
    theirs = [edit for edit in edits[1] if edit not in shared]

    for our_edit in ours:
        for their_edit in theirs:
            reason = _clash(our_edit, their_edit)
            if reason:
                return None, reason
    # A line both sides write, other than through one shared edit, would appear
    # twice: a double `release()`, or the same fix made in two places.
    our_lines = {line for _, _, lines in ours for line in lines}
    if any(line in our_lines for _, _, lines in theirs for line in lines):
        return None, "both sides add the same line"

    resolution, position = [], 0
    for start, end, lines in sorted(ours + theirs + list(shared), key=lambda e: (e[0], e[1])):
        resolution.extend(base[position:start])
        resolution.extend(lines)
        position = end
    resolution.extend(base[position:])
    changed = len(ours) + len(theirs) + len(shared)
    return resolution, f"{changed} non-overlapping edit(s)"


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


# Merging is never the right resolution for a file derived from a manifest: the
# answer is to regenerate it. Names, not contents, because a half-merged lockfile
# is indistinguishable from a hand-written sorted list.
_GENERATED_NAMES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "pnpm-lock.yaml",
        "bun.lockb",
        "go.sum",
        "go.work.sum",
        ".terraform.lock.hcl",
        "gradle.lockfile",
        "packages.lock.json",
        "Package.resolved",
    }
)
_BUILT_SUFFIXES = (".min.js", ".min.css")


# Generators conventionally say so near the top of the file. Repo-specific
# generated files with no such header cannot be recognised here.
_GENERATED_HEADER = re.compile(
    r"@generated|\bdo not edit\b|\bauto-?generated\b|\bautomatically generated\b",
    re.IGNORECASE,
)
_GENERATED_HEADER_LINES = 10


def _is_generated(path):
    name = Path(path).name
    return name.endswith(".lock") or name in _GENERATED_NAMES


def _side_texts(path):
    """The conflicted file as it reads on each side, markers removed."""
    hunks, lines = parse_file(path)
    texts = []
    for key in ("diff_base", "diff_side", "snapshot"):
        text, position = [], 0
        for hunk in hunks:
            text.extend(lines[position : hunk["_start"]])
            text.extend(hunk[key])
            position = hunk["_end"] + 1
        text.extend(lines[position:])
        texts.append(text)
    return texts


def _generated_reason(path):
    """Why `path` must be regenerated rather than merged, or None."""
    if _is_generated(path):
        return "generated file — regenerate it from its manifest"
    if Path(path).name.endswith(_BUILT_SUFFIXES):
        return "built file — rebuild it from its source"
    try:
        # A conflict near the top pushes the header down the raw file, so read
        # it as each side has it.
        texts = _side_texts(Path(path))
    except (OSError, UnicodeError):
        return None
    for text in texts:
        if any(_GENERATED_HEADER.search(line) for line in text[:_GENERATED_HEADER_LINES]):
            return "generated file, its header says so — regenerate it"
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
            f"File: {h['file']}  |  hunk {h['hunk']}/{h['total']}  |  "
            f"lines {h['start_line']}–{h['end_line']}  |  fingerprint {h['fingerprint']}"
        )
        for side in h["sides"]:
            print(f"  {side['name']:<8} : {side['label'] or '(unlabelled)'}")
        print()
        sys.stdout.writelines(h["raw"])
        print()
    for filepath in unsupported:
        print(
            f"Unsupported conflict marker style in {filepath}; inspect it manually.",
            file=sys.stderr,
        )
    return 1 if unsupported else 0


_SIDE_KEYS = {"snapshot": "snapshot", "diff": "diff_side", "base": "diff_base"}
# Shorthands for the roles jj appends to rebase labels.
_ROLE_ALIASES = {"destination": "rebase destination", "rebased": "rebased revision"}


def _side_by_name(hunk, name):
    """The side of `hunk` that `name` selects: a section name (snapshot, diff,
    base), a role from its label, or a change or commit ID prefix.

    Raises ValueError, naming the hunk's sides, when none or several match.
    """
    for side in hunk["sides"]:
        if side["name"] == name:
            return side
    role = _ROLE_ALIASES.get(name, name)
    matches = [
        side
        for side in hunk["sides"]
        if side["role"] == role
        or (side["change_id"] or "").startswith(name)
        or (side["commit_id"] or "").startswith(name)
    ]
    if len(matches) == 1:
        return matches[0]
    problem = "matches more than one side" if matches else "names no side"
    sides = "; ".join(
        f"{side['name']} = {side['label'] or '(unlabelled)'}" for side in hunk["sides"]
    )
    raise ValueError(f"'{name}' {problem} of hunk {hunk['hunk']}/{hunk['total']} ({sides})")


def _take_side(hunk, side):
    """The lines a hunk resolves to when one side is taken whole."""
    lines = list(hunk[_SIDE_KEYS[side["name"]]])
    if hunk["no_newline"] and lines:
        # Undo the newline jj added to every term to keep markers on their own
        # line; the side's own text decides whether the file ends with one.
        last = lines[-1]
        lines[-1] = last[:-1] if last.endswith("\n") else last
        if not lines[-1]:
            lines.pop()
    return lines


def _describe_side(side):
    return side["name"] + (f" = {side['label']}" if side["label"] else "")


def _resolution(hunk, strategy):
    """Return (lines, description) for one supported hunk, or raise ValueError."""
    if strategy in ("stack", "stack-snap-first"):
        if not hunk["stackable"]:
            raise ValueError("not two pure additions — resolve by hand")
        return _stack_resolution(hunk, snapshot_first=strategy == "stack-snap-first"), strategy
    side = _side_by_name(hunk, strategy)
    return _take_side(hunk, side), _describe_side(side)


def _unsupported_reason(hunk):
    if not hunk["_terminated"]:
        return "no closing marker"
    if not hunk["supported"]:
        return "many-sided conflict" if hunk["many_sided"] else "unsupported marker style"
    return None


def cmd_accept(args):
    filepath, strategy = args.file, args.strategy
    single = args.hunk is not None
    if single != (args.expect is not None):
        print("accept: --hunk and --expect go together.", file=sys.stderr)
        return 1
    path = _resolve_path(filepath)
    if path is None:
        print(f"Not found: {filepath}", file=sys.stderr)
        return 1
    if strategy == "sort":
        if single:
            print("accept: sort applies to the whole file; drop --hunk.", file=sys.stderr)
            return 1
        merged = []
        resolved, left = _auto_resolve_file(
            path, filepath, dry=False, disjoint=False, merged=merged
        )
        _auto_summary(resolved, left, dry=False, merged=merged)
        return 0
    if single:
        return _accept_one(path, filepath, strategy, args.hunk, args.expect)

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

    # Choose for every hunk before writing any: a side named by role or change
    # ID may be the snapshot in one hunk and the diff in the next, and a name
    # that one hunk lacks must not leave the file half-resolved.
    plans, skipped, refused = [], 0, []
    for h in hunks:
        reason = _unsupported_reason(h)
        if reason:
            print(f"  {filepath} hunk {h['hunk']}/{h['total']}: left ({reason} — resolve by hand)")
            skipped += 1
            continue
        try:
            plans.append((h, *_resolution(h, strategy)))
        except ValueError as error:
            if strategy in ("stack", "stack-snap-first"):
                print(f"  {filepath} hunk {h['hunk']}/{h['total']}: left ({error})")
                skipped += 1
            else:
                refused.append(str(error))
    if refused:
        for message in refused:
            print(f"accept: {message}", file=sys.stderr)
        print(f"Nothing written to {filepath}.", file=sys.stderr)
        return 1

    for h, resolution, _ in reversed(plans):
        lines[h["_start"] : h["_end"] + 1] = resolution
    if plans:
        _write_source(path, "".join(lines))
    left = f", {skipped} unsupported hunk(s) left" if skipped else ""
    print(f"Resolved {len(plans)} hunk(s) in {filepath} (accepted {strategy} side){left}.")
    if strategy not in _SIDE_KEYS and strategy not in ("stack", "stack-snap-first"):
        for h, _, taken in plans:
            print(f"  hunk {h['hunk']}/{h['total']}: {taken}")
    return 1 if skipped else 0


def _find_hunk(path, filepath, number, expect):
    """Return (hunk, lines) for hunk `number` if it still has fingerprint
    `expect`; otherwise print why and return (None, None)."""
    hunks, lines = parse_file(path)
    if not hunks and _has_unparsed_conflict(path, hunks):
        print(
            f"Unsupported conflict marker style in {filepath}; resolve it by hand.",
            file=sys.stderr,
        )
        return None, None
    found = [h for h in hunks if h["hunk"] == number]
    if not found:
        remaining = ", ".join(str(h["hunk"]) for h in hunks) or "none"
        print(
            f"{filepath} has no conflict {number} (conflicts remaining: {remaining}).",
            file=sys.stderr,
        )
        return None, None
    if len(found) > 1:
        print(
            f"{filepath} has {len(found)} conflicts numbered {number}; resolve by hand.",
            file=sys.stderr,
        )
        return None, None
    hunk = found[0]
    if hunk["fingerprint"] != expect.lower():
        print(
            f"{filepath} conflict {number} no longer matches fingerprint {expect} "
            f"(it is now {hunk['fingerprint']}). Rerun `conflicts show {filepath}` "
            "and choose again from what it prints.",
            file=sys.stderr,
        )
        return None, None
    if not hunk["_terminated"]:
        print(
            f"{filepath} conflict {number} has no closing marker; resolve it by hand.",
            file=sys.stderr,
        )
        return None, None
    return hunk, lines


def _splice(path, filepath, hunk, lines, resolution, how):
    lines[hunk["_start"] : hunk["_end"] + 1] = resolution
    _write_source(path, "".join(lines))
    remaining, _ = parse_file(path)
    if remaining:
        numbers = ", ".join(str(h["hunk"]) for h in remaining)
        after = f"conflicts still open: {numbers}"
    elif _GENERIC_START.search("".join(lines)):
        after = "other conflict markers remain; inspect the file"
    else:
        after = "no conflict markers remain"
    print(f"Resolved conflict {hunk['hunk']}/{hunk['total']} in {filepath} ({how}); {after}.")


def _accept_one(path, filepath, strategy, number, expect):
    hunk, lines = _find_hunk(path, filepath, number, expect)
    if hunk is None:
        return 1
    reason = _unsupported_reason(hunk)
    if reason:
        print(
            f"accept: {filepath} conflict {number}: {reason}; use `replace` instead.",
            file=sys.stderr,
        )
        return 1
    try:
        resolution, how = _resolution(hunk, strategy)
    except ValueError as error:
        print(f"accept: {error}", file=sys.stderr)
        return 1
    _splice(path, filepath, hunk, lines, resolution, f"took {how}")
    return 0


def _hunk_line_ending(hunk):
    """CRLF when every content line of the hunk ends with it, else LF."""
    content = hunk["snapshot"] + hunk["diff_base"] + hunk["diff_side"]
    ended = [line for line in content if line.endswith(("\n", "\r"))]
    if ended and all(line.endswith("\r\n") for line in ended):
        return "\r\n"
    return "\n"


def cmd_replace(args):
    filepath = args.file
    if args.source in (None, "-"):
        if sys.stdin is None or sys.stdin.isatty():
            print("replace: pipe the replacement on stdin or pass --from PATH.", file=sys.stderr)
            return 1
        content = sys.stdin.buffer.read().decode("utf-8")
    else:
        content = _read_source(Path(args.source))
    if not content and not args.allow_empty:
        print(
            "replace: the replacement is empty; pass --allow-empty to delete the hunk's lines.",
            file=sys.stderr,
        )
        return 1
    if _MARKER_LINE.search(content):
        print("replace: the replacement still contains conflict markers.", file=sys.stderr)
        return 1
    path = _resolve_path(filepath)
    if path is None:
        print(f"Not found: {filepath}", file=sys.stderr)
        return 1
    hunk, lines = _find_hunk(path, filepath, args.hunk, args.expect)
    if hunk is None:
        return 1
    ending = _hunk_line_ending(hunk)
    if ending == "\r\n" and "\r" not in content:
        content = content.replace("\n", "\r\n")
    # Without a final newline the next line would join the last replaced one.
    # jj's missing-newline case is the exception: there the hunk ends the file
    # and the replacement says whether the file ends with a newline.
    if content and not content.endswith(("\n", "\r")) and not hunk["no_newline"]:
        content += ending
    _splice(path, filepath, hunk, lines, _split_lines(content), "replaced")
    return 0


def _auto_summary(resolved, left, dry, merged=()):
    print("  ---")
    suffix = " (dry-run, nothing written)" if dry else ""
    print(f"  resolved {resolved} hunk(s), {left} left for review{suffix}")
    if resolved:
        # The guards prove the lines merge, not that the merge means anything.
        print("  A ✓ means the lines merged safely, not that the result is right — read the diff.")
    print_merged(merged, dry=dry)


def print_merged(merged, *, dry=False, stream=None):
    """List every auto-merged hunk so none is folded in unseen."""
    if not merged:
        return
    heading = "would be auto-merged" if dry else "auto-merged; inspect each before continuing"
    print(f"  Hunks {heading}:", file=stream)
    for entry in merged:
        print(f"    {entry}", file=stream)


def _merged_entry(filepath, old_lines, new_lines, strategy):
    """Name where a merge landed in the rewritten file, as FILE:FIRST-LAST."""
    prefix = 0
    limit = min(len(old_lines), len(new_lines))
    while prefix < limit and old_lines[prefix] == new_lines[prefix]:
        prefix += 1
    suffix = 0
    while suffix < limit - prefix and old_lines[-1 - suffix] == new_lines[-1 - suffix]:
        suffix += 1
    first, last = prefix + 1, len(new_lines) - suffix
    if last < first:
        return f"{filepath}:{first} ({strategy}; the hunk resolved to no lines)"
    return f"{filepath}:{first}-{last} ({strategy})"


def _report(filepath, hunk, label, msg):
    print(f"  {filepath} hunk {hunk['hunk']}/{hunk['total']}: {label} ({msg})")


def _qualifying_resolution(hunk, lines, disjoint):
    """Try each conservative strategy. Returns (new_lines, label, info)."""
    new_lines, sorted_info = _sorted_merge_resolution(hunk, lines)
    if new_lines is not None:
        return new_lines, "sorted-merge ✓", f"{sorted_info} adds"
    if not disjoint:
        return None, "left", sorted_info
    resolution, disjoint_info = _disjoint_resolution(hunk)
    if resolution is not None:
        new_lines = lines[: hunk["_start"]] + resolution + lines[hunk["_end"] + 1 :]
        return new_lines, "disjoint-merge ✓", disjoint_info
    reason = disjoint_info
    if sorted_info != disjoint_info:
        reason = f"{disjoint_info}; sorted-merge: {sorted_info}"
    if hunk.get("stackable"):
        reason += "; if the order is known, accept stack or stack-snap-first"
    return None, "left", reason


def _auto_resolve_file(path, filepath, dry, disjoint=True, merged=None):
    """Resolve every qualifying hunk in one file. Returns (resolved, left).

    `disjoint=False` restricts it to sorted-list additions (`accept FILE sort`).
    Each merged hunk's location is appended to `merged` when it is given.
    """
    if merged is None:
        merged = []
    generated = _generated_reason(path)
    if generated:
        print(f"  {filepath}: left ({generated})")
        return 0, 1
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
            new_lines, label, info = _qualifying_resolution(h, lines, disjoint)
            if new_lines is None:
                _report(filepath, h, label, info)
                declined.add("".join(h["raw"]))
                left += 1
                continue
            _report(filepath, h, label, info)
            resolved += 1
            strategy = label.removesuffix(" ✓")
            if dry:
                # Don't rewrite; mark resolved so we don't loop on it forever.
                declined.add("".join(h["raw"]))
                merged.append(f"{filepath}:{h['start_line']}-{h['end_line']} ({strategy})")
            else:
                merged.append(_merged_entry(filepath, lines, new_lines, strategy))
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
    merged = []
    for filepath, path in targets:
        resolved, left = _auto_resolve_file(path, filepath, dry, merged=merged)
        total_resolved += resolved
        total_left += left
    _auto_summary(total_resolved, total_left, dry, merged)
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
            "Resolve every supported hunk in one file, or one hunk with --hunk, using an "
            "explicitly selected strategy. Unsupported hunks are left untouched."
        ),
    )
    accept.add_argument("file", metavar="FILE", help="conflicted file to resolve")
    accept.add_argument(
        "strategy",
        metavar="SIDE",
        help=(
            "snapshot, diff or base selects that section; a role from the labels "
            "(destination, rebased, or its full text) or a change/commit ID prefix selects "
            "that side in every hunk, whichever section it is; stack or stack-snap-first "
            "combines two pure additions; sort conservatively merges a sorted list"
        ),
    )
    accept.add_argument(
        "--hunk", type=int, metavar="N", help="resolve only conflict N as `show` numbers it"
    )
    accept.add_argument(
        "--expect",
        metavar="FINGERPRINT",
        help="the hunk's fingerprint from `show`; required with --hunk",
    )

    replace = commands.add_parser(
        "replace",
        help="replace one hunk with given content",
        description=(
            "Replace conflict N, markers included, with content read from --from PATH or "
            "stdin, if the hunk still has the fingerprint `show` printed."
        ),
    )
    replace.add_argument("file", metavar="FILE", help="conflicted file")
    replace.add_argument("hunk", type=int, metavar="N", help="conflict number as `show` prints it")
    replace.add_argument(
        "--expect", required=True, metavar="FINGERPRINT", help="the hunk's fingerprint from `show`"
    )
    replace.add_argument(
        "--from",
        dest="source",
        metavar="PATH",
        help="read the replacement from PATH (default: stdin)",
    )
    replace.add_argument(
        "--allow-empty", action="store_true", help="accept an empty replacement (delete the lines)"
    )

    auto = commands.add_parser(
        "auto",
        help="merge provably safe hunks: sorted-list additions or non-overlapping edits",
        description=(
            "Conservatively merge two pure additions into an existing sorted run of at least "
            "three lines, or two sides whose line edits touch but never overlap. Leave every "
            "unproven hunk untouched, and never merge a generated file such as *.lock, "
            "package-lock.json, go.sum or one whose header marks it generated."
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
            return cmd_accept(args)
        if args.command == "replace":
            return cmd_replace(args)
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
