"""Extract focused jj reference material for jj-sensei."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import use_utf8_output

_COMMAND_HEADING = re.compile(r"^## `jj(?: (?P<path>[^`]+))?`$")
_HEADING = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$")
_LEADING_DEFINITION = re.compile(r"^\* `(?P<term>[^`]+)`")
_OPTION_CODE = re.compile(r"`(?P<option>--?[a-zA-Z0-9][^`]*)`")
_ARGUMENT_CODE = re.compile(r"`(?P<argument><[^`]+>)`")
_KEYWORD = re.compile(r"^\s*-\s+(?P<name>[a-z][a-z-]+):(?:\s|$)")
_VERSION = re.compile(r"\b(?P<version>\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?)\b")
_LANGUAGE_ESSENTIALS = {
    "revsets": {"Hidden revisions", "Symbols", "Priority", "Operators"},
    "filesets": {"Quoting file names", "File patterns", "Operators", "Functions"},
    "templates": {"Keywords", "Commit keywords", "Operation keywords", "Operators"},
}


class HelpError(RuntimeError):
    """The installed jj help could not satisfy a request."""


@dataclass(frozen=True)
class CommandSection:
    path: str
    text: str


class HelpSource:
    """Read help and version-matched manual pages for one jj executable."""

    def __init__(self, executable: str = "jj", docs_dir: Path | None = None):
        self.executable = executable
        self._markdown: str | None = None
        self._configured_docs_dir = docs_dir
        self._docs: dict[str, str] | None = None
        self._local_docs_dir: Path | None = None

    def run(self, *args: str) -> str:
        command = [self.executable, "--no-pager", "--color", "never", *args]
        try:
            result = subprocess.run(command, capture_output=True, text=True, check=False)
        except FileNotFoundError as error:
            raise HelpError(f"cannot run {self.executable!r}: executable not found") from error
        if result.returncode:
            detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic"
            raise HelpError(f"{' '.join(command)} failed ({result.returncode}): {detail}")
        return result.stdout

    def version(self) -> str:
        return self.run("version").strip()

    def help_help(self) -> str:
        return self.run("help", "--help")

    def keyword(self, topic: str) -> str:
        return self.run("help", "-k", topic)

    def command(self, path: Sequence[str], *, full: bool) -> str:
        if full:
            return self.run("help", *path)
        return self.run(*path, "-h")

    def markdown_help(self) -> str:
        if self._markdown is None:
            self._markdown = self.run("util", "markdown-help")
        return self._markdown

    def doc_topics(self) -> list[str]:
        self._load_docs_index()
        assert self._docs is not None
        return sorted(self._docs)

    def doc(self, topic: str) -> str:
        self._load_docs_index()
        assert self._docs is not None
        try:
            relative = self._docs[topic]
        except KeyError as error:
            raise HelpError(f"no installed manual page {topic!r}") from error
        if self._local_docs_dir is not None:
            return (self._local_docs_dir / relative).read_text(encoding="utf-8")
        return self._remote_text(relative)

    def _load_docs_index(self) -> None:
        if self._docs is not None:
            return
        docs_dir = self._find_docs_dir()
        if docs_dir is not None:
            self._local_docs_dir = docs_dir
            paths = [path.relative_to(docs_dir).as_posix() for path in docs_dir.rglob("*.md")]
        else:
            paths = self._remote_doc_paths()
        docs: dict[str, str] = {}
        for path in paths:
            topic = _doc_topic(path)
            if previous := docs.get(topic):
                raise HelpError(
                    f"manual pages {previous!r} and {path!r} both normalize to {topic!r}"
                )
            docs[topic] = path
        self._docs = docs

    def _find_docs_dir(self) -> Path | None:
        configured = self._configured_docs_dir or _docs_override()
        if configured is not None:
            resolved = configured.expanduser().resolve()
            if not resolved.is_dir():
                raise HelpError(f"configured jj docs directory does not exist: {resolved}")
            return resolved

        executable = shutil.which(self.executable)
        if executable is None:
            return None
        prefix = Path(executable).resolve().parent.parent
        version = self._version_number()
        candidates = [
            prefix / "share" / "doc" / package / "docs"
            for package in ("jujutsu", "jj", "jj-vcs", f"jujutsu-{version}")
        ]
        candidates.extend(
            [prefix / "share" / package / "docs" for package in ("jujutsu", "jj", "jj-vcs")]
        )
        return next((path for path in candidates if path.is_dir()), None)

    def _version_number(self) -> str:
        match = _VERSION.search(self.version())
        if match is None:
            raise HelpError("could not determine a release version for the installed jj")
        return match.group("version")

    def _remote_doc_paths(self) -> list[str]:
        tag = f"v{self._version_number()}"
        url = f"https://api.github.com/repos/jj-vcs/jj/git/trees/{tag}?recursive=1"
        try:
            payload = json.loads(self._request(url))
        except (json.JSONDecodeError, KeyError, TypeError) as error:
            raise HelpError(f"could not read the official docs index for {tag}") from error
        if payload.get("truncated"):
            raise HelpError(f"official docs index for {tag} was truncated")
        paths = [
            item["path"].removeprefix("docs/")
            for item in payload.get("tree", [])
            if item.get("type") == "blob"
            and item.get("path", "").startswith("docs/")
            and item.get("path", "").endswith(".md")
        ]
        if not paths:
            raise HelpError(f"official tag {tag} has no Markdown documentation")
        return paths

    def _remote_text(self, relative: str) -> str:
        tag = f"v{self._version_number()}"
        path = urllib.parse.quote(relative, safe="/")
        return self._request(f"https://raw.githubusercontent.com/jj-vcs/jj/{tag}/docs/{path}")

    @staticmethod
    def _request(url: str) -> str:
        request = urllib.request.Request(url, headers={"User-Agent": "jj-sensei-rtfm"})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.read().decode("utf-8")
        except (OSError, UnicodeError, urllib.error.URLError) as error:
            raise HelpError(
                f"packaged jj docs were not found and the version-matched official source "
                f"could not be read: {error}"
            ) from error


def _docs_override() -> Path | None:
    value = os.environ.get("JJ_SENSEI_DOCS_DIR")
    return Path(value) if value else None


def _doc_topic(relative: str) -> str:
    path = Path(relative)
    without_suffix = path.with_suffix("").as_posix()
    return "docs/" + without_suffix.replace("_", "-").lower()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="rtfm",
        description="Read help and manual pages matching the installed jj version.",
    )
    result.add_argument("topic", nargs="*", help="help keyword or canonical command path")
    result.add_argument(
        "--full",
        action="store_true",
        help="print the complete command help, keyword help, or manual page",
    )
    result.add_argument(
        "--search",
        metavar="TERM",
        help="extract matching definitions or sections from long help",
    )
    result.add_argument(
        "--list",
        action="store_true",
        help="list help keywords, manual pages, and canonical command paths",
    )
    result.add_argument(
        "--manifest",
        action="store_true",
        help="print the normalized structural help manifest as JSON",
    )
    result.add_argument(
        "--manifest-lock",
        action="store_true",
        help="print compact per-topic fingerprints for drift tests",
    )
    result.add_argument(
        "--check-manifest",
        metavar="PATH",
        type=Path,
        help="compare installed jj help with a normalized manifest",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    use_utf8_output()
    return run_help(argv, HelpSource())


def run_help(argv: list[str] | None, source: HelpSource) -> int:
    args = parser().parse_args(argv)
    try:
        if args.manifest:
            _require_standalone(args, "manifest")
            print(json.dumps(build_manifest(source), indent=2, sort_keys=True))
            return 0
        if args.manifest_lock:
            _require_standalone(args, "manifest_lock")
            print(json.dumps(manifest_lock(build_manifest(source)), indent=2, sort_keys=True))
            return 0
        if args.check_manifest:
            _require_standalone(args, "check_manifest")
            return check_manifest(source, args.check_manifest)
        if args.list:
            _require_standalone(args, "list")
            print(render_topic_list(source), end="")
            return 0
        if not args.topic:
            parser().print_usage(sys.stderr)
            print("rtfm: supply a topic or use --list", file=sys.stderr)
            return 2

        requested = " ".join(args.topic)
        if requested.startswith("docs/"):
            if len(args.topic) != 1:
                print("rtfm: manual page topics cannot contain spaces", file=sys.stderr)
                return 2
            topics = set(source.doc_topics())
            if requested not in topics:
                print(f"rtfm: no installed manual page {requested!r}", file=sys.stderr)
                return 2
            output = source.doc(requested)
            if args.search:
                selected = extract_relevant(output, args.search)
                if selected is None:
                    print(
                        f"rtfm: no {args.search!r} section or definition in {requested!r}",
                        file=sys.stderr,
                    )
                    return 2
                print(selected, end="")
                return 0
            if args.full:
                print(output, end="")
                return 0
            compact = compact_keyword(requested, output)
            if compact is None:
                print(
                    "rtfm: installed jj manual page has an unfamiliar structure; showing it in full",
                    file=sys.stderr,
                )
                print(output, end="")
            else:
                print(compact, end="")
            return 0

        keywords = available_keywords(source)
        if len(args.topic) == 1 and args.topic[0] in keywords:
            output = source.keyword(args.topic[0])
            if args.search:
                selected = extract_relevant(output, args.search)
                if selected is None:
                    print(
                        f"rtfm: no {args.search!r} section or definition in {args.topic[0]!r}",
                        file=sys.stderr,
                    )
                    return 2
                print(selected, end="")
                return 0
            if args.full:
                print(output, end="")
                return 0
            compact = compact_keyword(args.topic[0], output)
            if compact is None:
                print(
                    "rtfm: installed jj help has an unfamiliar structure; showing full topic",
                    file=sys.stderr,
                )
                print(output, end="")
            else:
                print(compact, end="")
            return 0

        command_paths = set(parse_command_sections(source.markdown_help()))
        requested_path = "" if requested == "jj" else requested
        if requested_path not in command_paths:
            print(
                f"rtfm: no help keyword, docs/ page, or canonical command path {requested!r}",
                file=sys.stderr,
            )
            return 2
        command_args = [] if requested_path == "" else args.topic
        output = source.command(command_args, full=args.full or bool(args.search))
        if args.search:
            selected = extract_relevant(output, args.search)
            if selected is None:
                print(
                    f"rtfm: no {args.search!r} section or definition in {requested!r}",
                    file=sys.stderr,
                )
                return 2
            output = selected
        print(output, end="")
        return 0
    except (HelpError, OSError, json.JSONDecodeError) as error:
        print(f"rtfm: {error}", file=sys.stderr)
        return 2


def _require_standalone(args: argparse.Namespace, selected: str) -> None:
    controls = {
        "manifest": args.manifest,
        "manifest_lock": args.manifest_lock,
        "check_manifest": args.check_manifest is not None,
        "list": args.list,
    }
    conflicting_control = any(enabled for name, enabled in controls.items() if name != selected)
    if args.topic or args.full or args.search or conflicting_control:
        option = f"--{selected.replace('_', '-')}"
        raise HelpError(f"{option} must be used by itself")


def available_keywords(source: HelpSource) -> list[str]:
    names = [
        match.group("name")
        for line in source.help_help().splitlines()
        if (match := _KEYWORD.match(line))
    ]
    if not names:
        raise HelpError("could not discover help keywords from `jj help --help`")
    return sorted(set(names))


def parse_command_sections(markdown: str) -> dict[str, CommandSection]:
    lines = markdown.splitlines()
    starts: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        match = _COMMAND_HEADING.match(line)
        if match:
            starts.append((index, match.group("path") or ""))
    if not starts:
        raise HelpError("could not discover commands from `jj util markdown-help`")
    sections: dict[str, CommandSection] = {}
    for position, (start, path) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        sections[path] = CommandSection(
            path=path,
            text="\n".join(lines[start:end]).rstrip() + "\n",
        )
    return sections


def render_topic_list(source: HelpSource) -> str:
    keywords = available_keywords(source)
    commands = parse_command_sections(source.markdown_help())
    rendered_commands = ["jj" if not path else f"jj {path}" for path in commands]
    try:
        docs = source.doc_topics()
        rendered_docs = "\n  ".join(docs)
    except HelpError as error:
        rendered_docs = f"[unavailable: {error}]"
    return (
        "Help keywords:\n  "
        + "\n  ".join(keywords)
        + "\n\nManual pages:\n  "
        + rendered_docs
        + "\n\nCanonical command paths:\n  "
        + "\n  ".join(rendered_commands)
        + "\n"
    )


def compact_keyword(topic: str, full: str) -> str | None:
    lines = full.splitlines()
    if not lines or not lines[0].startswith("# "):
        return None
    first_section = next(
        (index for index, line in enumerate(lines) if line.startswith("## ")),
        len(lines),
    )
    intro = _trim_blank(lines[:first_section])
    headings = [
        match.group("title")
        for line in lines
        if (match := _HEADING.match(line)) and len(match.group("marks")) >= 2
    ]
    if not headings:
        return None

    output = [*intro]
    essentials = _LANGUAGE_ESSENTIALS.get(topic)
    if essentials:
        for _, section in _top_level_sections(lines):
            selected = _select_essential_section(section, essentials)
            if selected:
                output.extend(["", *selected])
    output.extend(["", "## Available sections", ""])
    output.extend(f"- {title}" for title in headings)
    output.extend(
        [
            "",
            "Use `--search TERM` for one official definition or section, or `--full` for the complete installed help.",
            "",
        ]
    )
    return "\n".join(output)


def _top_level_sections(lines: list[str]) -> list[tuple[str, list[str]]]:
    starts = [index for index, line in enumerate(lines) if line.startswith("## ")]
    sections = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        sections.append((lines[start][3:].strip(), lines[start:end]))
    return sections


def _select_essential_section(section: list[str], essentials: set[str]) -> list[str]:
    title = section[0][3:].strip()
    if title not in essentials:
        return []
    selected: list[str] = []
    skip_level: int | None = None
    in_comment = False
    for line in section:
        if in_comment:
            if "-->" in line:
                in_comment = False
            continue
        if "<!--" in line:
            in_comment = "-->" not in line
            continue
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group("marks"))
            heading_title = heading.group("title")
            if skip_level is not None and level <= skip_level:
                skip_level = None
            if level >= 3 and heading_title not in essentials:
                skip_level = level
                continue
        if skip_level is not None:
            continue
        if line.startswith("??? "):
            break
        selected.append(line)
    return _trim_blank(selected)


def extract_relevant(full: str, query: str) -> str | None:
    needle = query.casefold()
    lines = full.splitlines()

    definitions: list[list[str]] = []
    exact_definitions: list[list[str]] = []
    for start, line in enumerate(lines):
        match = _LEADING_DEFINITION.match(line)
        if not match or needle not in match.group("term").casefold():
            continue
        end = start + 1
        while (
            end < len(lines)
            and not lines[end].startswith("* ")
            and not lines[end].startswith("## ")
        ):
            end += 1
        definition = _trim_blank(lines[start:end])
        definitions.append(definition)
        name = re.split(r"[(:]", match.group("term"), maxsplit=1)[0].lstrip(".")
        if name.casefold() == needle:
            exact_definitions.append(definition)
    if exact_definitions:
        return _join_matches(exact_definitions)
    if definitions:
        return _join_matches(definitions)

    sections: list[list[str]] = []
    for start, line in enumerate(lines):
        match = _HEADING.match(line)
        if not match or needle not in _plain_heading(match.group("title")).casefold():
            continue
        level = len(match.group("marks"))
        end = start + 1
        while end < len(lines):
            next_heading = _HEADING.match(lines[end])
            if next_heading and len(next_heading.group("marks")) <= level:
                break
            end += 1
        sections.append(_trim_blank(lines[start:end]))
    if sections:
        return _join_matches(sections)

    blocks = _paragraph_blocks(lines)
    matches = [block for block in blocks if needle in "\n".join(block).casefold()]
    if matches:
        return _join_matches(matches[:8], truncated=len(matches) > 8)
    return None


def _join_matches(matches: list[list[str]], *, truncated: bool = False) -> str:
    output: list[str] = []
    for index, match in enumerate(matches):
        if index:
            output.extend(["", "---", ""])
        output.extend(match)
    if truncated:
        output.extend(["", "[additional matches omitted; use --full]", ""])
    else:
        output.append("")
    return "\n".join(output)


def _paragraph_blocks(lines: list[str]) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in lines:
        if line.strip():
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _plain_heading(title: str) -> str:
    return re.sub(r"[`*_#]", "", title)


def _trim_blank(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def build_manifest(source: HelpSource) -> dict:
    command_sections = parse_command_sections(source.markdown_help())
    commands = {
        path or "jj": _command_contract(section.text) for path, section in command_sections.items()
    }
    keywords = {}
    for topic in available_keywords(source):
        text = source.keyword(topic)
        keywords[topic] = {
            "headings": _keyword_headings(text),
            "definitions": _keyword_definitions(text) if topic in _LANGUAGE_ESSENTIALS else [],
        }
    docs = {
        topic: {"headings": _keyword_headings(source.doc(topic))} for topic in source.doc_topics()
    }
    return {
        "schema": 2,
        "jj_version": source.version(),
        "commands": commands,
        "keywords": keywords,
        "docs": docs,
    }


def manifest_lock(manifest: dict) -> dict:
    return {
        "schema": manifest["schema"],
        "lock": 1,
        "jj_version": manifest["jj_version"],
        "commands": {
            path: _fingerprint(contract) for path, contract in manifest["commands"].items()
        },
        "keywords": {
            topic: _fingerprint(contract) for topic, contract in manifest["keywords"].items()
        },
        "docs": {
            topic: _fingerprint(contract) for topic, contract in manifest.get("docs", {}).items()
        },
    }


def _fingerprint(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(canonical).hexdigest()}"


def _command_contract(section: str) -> dict:
    usage_match = re.search(r"^\*\*Usage:\*\* `(?P<usage>[^`]+)`", section, re.MULTILINE)
    usage = usage_match.group("usage") if usage_match else ""
    options = set()
    arguments = set()
    subcommands = set()
    mode: str | None = None
    for line in section.splitlines():
        if line == "###### **Arguments:**":
            mode = "arguments"
            continue
        if line == "###### **Subcommands:**":
            mode = "subcommands"
            continue
        if line == "###### **Options:**":
            mode = "options"
            continue
        if line.startswith("## ") or (line.startswith("###### ") and line.endswith(":**")):
            mode = None
        if mode == "options" and line.startswith("* "):
            for match in _OPTION_CODE.finditer(line):
                options.add(match.group("option").split(maxsplit=1)[0].split("=", 1)[0])
        elif mode == "arguments" and line.startswith("* "):
            arguments.update(match.group("argument") for match in _ARGUMENT_CODE.finditer(line))
        elif mode == "subcommands" and (match := _LEADING_DEFINITION.match(line)):
            subcommands.add(match.group("term"))
    return {
        "usage": usage,
        "arguments": sorted(arguments),
        "options": sorted(options),
        "subcommands": sorted(subcommands),
    }


def _keyword_headings(text: str) -> list[str]:
    return [
        f"{'#' * len(match.group('marks'))} {_plain_heading(match.group('title'))}"
        for line in text.splitlines()
        if (match := _HEADING.match(line))
    ]


def _keyword_definitions(text: str) -> list[str]:
    return sorted(
        {
            match.group("term")
            for line in text.splitlines()
            if (match := _LEADING_DEFINITION.match(line))
        }
    )


def check_manifest(source: HelpSource, path: Path) -> int:
    expected = json.loads(path.read_text(encoding="utf-8"))
    actual_manifest = build_manifest(source)
    actual = manifest_lock(actual_manifest) if "lock" in expected else actual_manifest
    differences = manifest_differences(expected, actual)
    if not differences:
        print(f"jj help contract matches {path}")
        return 0
    print(f"jj help contract drifted from {path}:", file=sys.stderr)
    for difference in differences:
        print(f"- {difference}", file=sys.stderr)
    print(
        "Review the installed jj changes, then regenerate with `rtfm --manifest-lock`.",
        file=sys.stderr,
    )
    return 1


def manifest_differences(expected: dict, actual: dict) -> list[str]:
    differences: list[str] = []
    if expected.get("schema") != actual.get("schema"):
        differences.append(f"schema: {expected.get('schema')!r} -> {actual.get('schema')!r}")
    if expected.get("jj_version") != actual.get("jj_version"):
        differences.append(
            f"jj version: {expected.get('jj_version')!r} -> {actual.get('jj_version')!r}"
        )
    _mapping_differences(
        "command", expected.get("commands", {}), actual.get("commands", {}), differences
    )
    _mapping_differences(
        "keyword", expected.get("keywords", {}), actual.get("keywords", {}), differences
    )
    _mapping_differences(
        "manual page", expected.get("docs", {}), actual.get("docs", {}), differences
    )
    return differences


def _mapping_differences(
    label: str,
    expected: dict,
    actual: dict,
    differences: list[str],
) -> None:
    expected_keys = set(expected)
    actual_keys = set(actual)
    if added := sorted(actual_keys - expected_keys):
        differences.append(f"added {label}s: {', '.join(added)}")
    if removed := sorted(expected_keys - actual_keys):
        differences.append(f"removed {label}s: {', '.join(removed)}")
    for key in sorted(expected_keys & actual_keys):
        if expected[key] != actual[key]:
            differences.append(f"changed {label}: {key}")


if __name__ == "__main__":
    raise SystemExit(main())
