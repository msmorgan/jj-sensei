"""Explain which clause of `immutable_heads()` makes a revision immutable."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from . import use_utf8_output
from .jj import Jj, JjError, safe_revision

_ALIAS_KEY = "revset-aliases.'immutable_heads()'"
_BUILTIN = "builtin_immutable_heads()"
_BUILTIN_CLAUSES = ("trunk()", "tags()", "untracked_remote_bookmarks()")
_ANCHOR_TEMPLATE = (
    "concat("
    "'{\"change_id\":', json(change_id), "
    "',\"bookmarks\":', json(stringify(bookmarks)), "
    "',\"tags\":', json(stringify(tags)), "
    "'}', \"\\n\")"
)


@dataclass(frozen=True)
class Clause:
    """One top-level term of the active `immutable_heads()` definition."""

    text: str
    origin: str | None = None

    @property
    def label(self) -> str:
        return self.text if self.origin is None else f"{self.text} (via {self.origin})"


@dataclass(frozen=True)
class Anchor:
    change_id: str
    bookmarks: str
    tags: str

    @property
    def label(self) -> str:
        names = ", ".join(name for name in (self.bookmarks, self.tags) if name)
        return f"{self.change_id[:12]} {names}" if names else self.change_id[:12]


@dataclass(frozen=True)
class Capture:
    clause: Clause
    anchors: tuple[Anchor, ...]


@dataclass(frozen=True)
class Verdict:
    change_id: str
    description: str
    immutable: bool
    captures: tuple[Capture, ...]
    unevaluated: tuple[str, ...]


def split_union(expression: str) -> list[str]:
    """Split a revset on its top-level `|` operators only.

    Nested unions inside a function call are that function's business; only
    the outermost terms are separately attributable to a revision.
    """
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    quote = ""
    previous = ""
    for character in expression:
        if quote:
            current.append(character)
            if character == quote and previous != "\\":
                quote = ""
            previous = "" if previous == "\\" else character
            continue
        if character in "'\"":
            quote = character
        elif character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        elif character == "|" and depth == 0:
            parts.append("".join(current))
            current = []
            previous = character
            continue
        current.append(character)
        previous = character
    parts.append("".join(current))
    return [stripped for part in parts if (stripped := part.strip())]


def unwrap(expression: str) -> str:
    """Drop parentheses that wrap the whole expression.

    `(a) & (b)` also starts and ends with a parenthesis, so matching the two
    ends is not enough; the opening one has to be the one the final character
    closes.
    """
    text = expression.strip()
    while text.startswith("(") and text.endswith(")") and _is_one_group(text):
        inner = text[1:-1].strip()
        if not inner:
            break
        text = inner
    return text


def _is_one_group(text: str) -> bool:
    depth = 0
    quote = ""
    previous = ""
    for index, character in enumerate(text):
        if quote:
            if character == quote and previous != "\\":
                quote = ""
            previous = "" if previous == "\\" else character
            continue
        if character in "'\"":
            quote = character
        elif character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
            if depth == 0 and index != len(text) - 1:
                return False
        previous = character
    return depth == 0


def active_definition(jj: Jj) -> str:
    """Read the repository's `immutable_heads()`, or jj's built-in default."""
    result = jj.run("config", "get", _ALIAS_KEY, check=False, ignore_working_copy=True)
    if result.returncode or not result.stdout.strip():
        return _BUILTIN
    return " ".join(result.stdout.split())


def clauses(definition: str) -> list[Clause]:
    """Break a definition into separately testable terms.

    `builtin_immutable_heads()` is expanded so a report can name `trunk()`
    rather than the umbrella alias that contains it.
    """
    result: list[Clause] = []
    for term in split_union(definition):
        text = unwrap(term)
        if text == _BUILTIN:
            result.extend(Clause(builtin, _BUILTIN) for builtin in _BUILTIN_CLAUSES)
        else:
            result.append(Clause(text))
    return result


def _anchors(jj: Jj, clause: Clause, change_id: str) -> tuple[Anchor, ...] | None:
    """Revisions in `clause` that `change_id` is an ancestor of, or None.

    A revision is immutable through a clause exactly when the clause contains
    one of its descendants, so this one query answers both whether the clause
    captures the revision and what anchors it there. None means the clause
    could not be evaluated at all.
    """
    revset = f"({clause.text}) & {safe_revision(change_id)}::"
    result = jj.run(
        "log",
        "--no-graph",
        "-r",
        revset,
        "-T",
        _ANCHOR_TEMPLATE,
        check=False,
        ignore_working_copy=True,
    )
    if result.returncode:
        return None
    return tuple(
        Anchor(
            change_id=item["change_id"],
            bookmarks=item["bookmarks"],
            tags=item["tags"],
        )
        for item in (json.loads(line) for line in result.stdout.splitlines() if line.strip())
    )


def explain(jj: Jj, revset: str, definition: str | None = None) -> list[Verdict]:
    """Report every revision selected by `revset` and why it is immutable."""
    terms = clauses(definition if definition is not None else active_definition(jj))
    verdicts: list[Verdict] = []
    for commit in jj.commits(revset):
        captures: list[Capture] = []
        unevaluated: list[str] = []
        for clause in terms:
            anchors = _anchors(jj, clause, commit.change_id)
            if anchors is None:
                unevaluated.append(clause.label)
            elif anchors:
                captures.append(Capture(clause, anchors))
        verdicts.append(
            Verdict(
                change_id=commit.change_id,
                description=commit.description.splitlines()[0] if commit.description else "",
                immutable=commit.immutable,
                captures=tuple(captures),
                unevaluated=tuple(unevaluated),
            )
        )
    return verdicts


def render(definition: str, verdicts: list[Verdict]) -> str:
    lines = [f"immutable_heads() = {definition}", ""]
    for verdict in verdicts:
        state = "immutable" if verdict.immutable else "mutable"
        summary = f"{verdict.change_id[:12]}  {state}"
        if verdict.description:
            summary += f'  "{verdict.description}"'
        lines.append(summary)
        for capture in verdict.captures:
            lines.append(f"    captured by {capture.clause.label}")
            for anchor in capture.anchors:
                lines.append(f"        anchored at {anchor.label}")
        if verdict.immutable and not verdict.captures:
            lines.append("    captured by no named clause; the root commit is always immutable")
        for clause in verdict.unevaluated:
            lines.append(f"    could not evaluate {clause}")
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="why-immutable",
        description=(
            "Report whether each selected revision is immutable and which clause of the "
            "active immutable_heads() definition captures it."
        ),
    )
    result.add_argument("revsets", nargs="+", metavar="REVSET", help="revisions to explain")
    return result


def run_why_immutable(revsets: list[str], cwd: Path | str | None = None) -> int:
    jj = Jj(cwd)
    try:
        definition = active_definition(jj)
        verdicts: list[Verdict] = []
        for revset in revsets:
            verdicts.extend(explain(jj, revset, definition))
    except JjError as error:
        # jj's own diagnosis of a bad revset is far more useful than the
        # rendered command, which carries the whole JSON template.
        print(f"why-immutable: {error.stderr.strip() or error}", file=sys.stderr)
        return 2
    except (RuntimeError, ValueError) as error:
        print(f"why-immutable: {error}", file=sys.stderr)
        return 2
    print(render(definition, verdicts))
    return 0


def main(argv: list[str] | None = None) -> int:
    use_utf8_output()
    args = parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    return run_why_immutable(args.revsets)


if __name__ == "__main__":
    raise SystemExit(main())
