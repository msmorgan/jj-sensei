"""Navigate Markdown documentation shipped with the installed jj release."""

from __future__ import annotations

import argparse
import html
import re
import sys
from dataclasses import dataclass

from . import use_utf8_output
from .knowledge import (
    HelpError,
    HelpSource,
    compact_keyword,
    extract_relevant,
    warn_about_docs_version,
)

_HEADING = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
_RECORD = re.compile(r"^- (?P<key>[A-Za-z][A-Za-z ]*):(?:\s(?P<value>.*))?$")
_FIELD = re.compile(r"^  (?P<key>[A-Za-z][A-Za-z ]*):(?:\s(?P<value>.*))?$")
_TABLE_FIELDS = ("Use case", "Git command", "Jujutsu command", "Notes")


@dataclass(frozen=True)
class TableRow:
    use_case: str
    git_command: str
    jujutsu_command: str
    notes: str


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="rtfd",
        description="Read Markdown documentation shipped with the installed jj release.",
    )
    result.add_argument("topic", nargs="?", help="canonical docs/ Markdown page")
    result.add_argument("--list", action="store_true", help="list installed Markdown pages")
    result.add_argument("--toc", action="store_true", help="print only the page heading tree")
    result.add_argument("--section", metavar="HEADING", help="extract one matching section")
    result.add_argument("--full", action="store_true", help="print the complete Markdown page")
    result.add_argument(
        "--yaml-table",
        metavar="DOCS/YAML",
        help="render an installed YAML table asset as Markdown",
    )
    result.add_argument(
        "--search",
        metavar="GIT-COMMAND",
        help="filter a YAML table by its Git command column",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    use_utf8_output()
    return run_docs(argv, HelpSource())


def run_docs(argv: list[str] | None, source: HelpSource) -> int:
    args = parser().parse_args(argv)
    try:
        if args.yaml_table is not None:
            _require_yaml_table_alone(args)
            source_text = source.doc_asset(args.yaml_table, suffixes={".yaml", ".yml"})
            warn_about_docs_version(source, program="rtfd")
            print(render_yaml_table(source_text, search=args.search), end="")
            return 0

        if args.list:
            _require_list_alone(args)
            topics = source.doc_topics()
            warn_about_docs_version(source, program="rtfd")
            print("\n".join(topics))
            return 0

        if args.topic is None:
            parser().print_usage(sys.stderr)
            print("rtfd: supply a docs/ topic, --list, or --yaml-table", file=sys.stderr)
            return 2
        if args.search is not None:
            raise HelpError("--search requires --yaml-table; use --section for Markdown pages")
        if sum((args.toc, args.section is not None, args.full)) > 1:
            raise HelpError("--toc, --section, and --full are mutually exclusive")

        topics = set(source.doc_topics())
        warn_about_docs_version(source, program="rtfd")
        if args.topic not in topics:
            raise HelpError(f"no installed manual page {args.topic!r}")
        output = source.doc(args.topic)
        if args.toc:
            print(render_toc(output), end="")
        elif args.section is not None:
            selected = extract_relevant(output, args.section)
            if selected is None:
                raise HelpError(f"no {args.section!r} section in {args.topic!r}")
            print(selected, end="")
        elif args.full:
            print(output, end="")
        else:
            compact = compact_keyword(args.topic, output)
            print(compact if compact is not None else output, end="")
        return 0
    except (HelpError, OSError, UnicodeError) as error:
        print(f"rtfd: {error}", file=sys.stderr)
        return 2


def _require_yaml_table_alone(args: argparse.Namespace) -> None:
    if args.topic or args.list or args.toc or args.section or args.full:
        raise HelpError("--yaml-table cannot be combined with another topic or view option")


def _require_list_alone(args: argparse.Namespace) -> None:
    if args.topic or args.toc or args.section or args.full or args.search:
        raise HelpError("--list must be used by itself")


def render_toc(markdown: str) -> str:
    headings = [
        (len(match.group("marks")), match.group("title"))
        for line in markdown.splitlines()
        if (match := _HEADING.match(line))
    ]
    if not headings:
        raise HelpError("installed jj manual page has no Markdown headings")
    base = min(level for level, _title in headings)
    return "\n".join(f"{'  ' * (level - base)}- {title}" for level, title in headings) + "\n"


def render_yaml_table(source: str, *, search: str | None = None) -> str:
    rows = parse_yaml_table(source)
    if search is not None:
        needle = search.casefold()
        rows = [row for row in rows if needle in row.git_command.casefold()]
        if not rows:
            raise HelpError(f"YAML table has no Git command matching {search!r}")
    output = [
        "| Use case | Git command | Jujutsu command | Notes |",
        "|---|---|---|---|",
    ]
    for row in rows:
        output.append(
            "| "
            + " | ".join(
                _table_cell(value)
                for value in (row.use_case, row.git_command, row.jujutsu_command, row.notes)
            )
            + " |"
        )
    return "\n".join(output) + "\n"


def parse_yaml_table(source: str) -> list[TableRow]:
    """Parse jj's deliberately simple list-of-mappings documentation schema."""
    lines = source.splitlines()
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip() or line.startswith("#"):
            index += 1
            continue
        match = _RECORD.match(line)
        if match is not None:
            if current is not None:
                records.append(current)
            current = {}
        else:
            match = _FIELD.match(line)
            if match is None or current is None:
                raise HelpError(f"unsupported YAML table structure at line {index + 1}")
        key = match.group("key")
        if key not in _TABLE_FIELDS or key in current:
            raise HelpError(f"unsupported YAML table field {key!r} at line {index + 1}")
        value, index = _yaml_scalar(lines, index, match.group("value") or "")
        current[key] = value
    if current is not None:
        records.append(current)
    if not records:
        raise HelpError("YAML table contains no rows")

    rows: list[TableRow] = []
    for number, record in enumerate(records, start=1):
        missing = [field for field in _TABLE_FIELDS if field not in record]
        if missing:
            raise HelpError(f"YAML table row {number} is missing {', '.join(missing)}")
        rows.append(
            TableRow(
                use_case=record["Use case"],
                git_command=record["Git command"],
                jujutsu_command=record["Jujutsu command"],
                notes=record["Notes"],
            )
        )
    return rows


def _yaml_scalar(lines: list[str], key_index: int, indicator: str) -> tuple[str, int]:
    if indicator and indicator not in {">", "|"}:
        return indicator, key_index + 1

    content: list[str] = []
    index = key_index + 1
    while index < len(lines):
        line = lines[index]
        if line.startswith("    "):
            content.append(line[4:])
            index += 1
            continue
        if not line.strip() and content:
            content.append("")
            index += 1
            continue
        break
    while content and not content[-1]:
        content.pop()
    if indicator == "|":
        return "\n".join(content), index
    return _fold_yaml_lines(content), index


def _fold_yaml_lines(lines: list[str]) -> str:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in lines:
        if line:
            current.append(line.strip())
        elif current:
            paragraphs.append(" ".join(current))
            current = []
    if current:
        paragraphs.append(" ".join(current))
    return "\n\n".join(paragraphs)


def _table_cell(value: str) -> str:
    escaped = html.escape(value, quote=False).replace("|", r"\|")
    return escaped.replace("\n", "<br>")


if __name__ == "__main__":
    raise SystemExit(main())
