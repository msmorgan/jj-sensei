from __future__ import annotations

import json
from pathlib import Path

import pytest

from jj_sensei import cli
from jj_sensei.knowledge import (
    HelpError,
    HelpSource,
    build_manifest,
    compact_keyword,
    extract_relevant,
    manifest_differences,
    manifest_lock,
    parse_command_sections,
    run_help,
)

HELP_HELP = """\
Usage: jj help [OPTIONS] [COMMAND]...

          Possible values:
          - bookmarks: Named pointers
          - filesets: A language for selecting files
          - revsets: A language for selecting revisions
"""

MARKDOWN_HELP = """\
# Command-Line Help for `jj`

## `jj`

**Usage:** `jj [OPTIONS] [COMMAND]`

###### **Subcommands:**

* `log` — Show revision history

###### **Options:**

* `--no-pager` — Disable the pager

## `jj log`

**Usage:** `jj log [OPTIONS]`

###### **Options:**

* `-r`, `--revisions <REVSETS>` — Which revisions to show
"""

REVSETS = """\
# Revsets

Select revisions.

## Symbols

`@` is the working copy.

## Operators

* `x | y`: Union.

??? examples

    Lots of examples.

## Functions

* `ancestors(x, [depth])`: Return ancestors of x.

* `descendants(x, [depth])`: Return descendants of x.

## Examples

An example.
"""

FILESETS = """\
# Filesets

Select files.

## Operators

* `x | y`: Union.
"""

BOOKMARKS = """\
# Bookmarks keyword

Embedded bookmark help.

## Remotes

Remote bookmark behavior.
"""

GIT_EXPERTS = """\
# Jujutsu for Git experts

Why Git experts may prefer Jujutsu.

## The Git index/staging area

Jujutsu uses commits instead of an index.

## The evolution log

Use `jj evolog` to inspect a change's earlier versions.
"""


class FakeSource:
    def __init__(self, *, malformed_keyword: bool = False):
        self.malformed_keyword = malformed_keyword
        self.command_calls: list[tuple[tuple[str, ...], bool]] = []

    def version(self):
        return "jj 9.9.9"

    def help_help(self):
        return HELP_HELP

    def keyword(self, topic):
        if self.malformed_keyword:
            return "unstructured official output\n"
        return {"revsets": REVSETS, "filesets": FILESETS, "bookmarks": BOOKMARKS}[topic]

    def command(self, path, *, full):
        self.command_calls.append((tuple(path), full))
        return f"{'long' if full else 'short'} help for {' '.join(path)}\n"

    def markdown_help(self):
        return MARKDOWN_HELP

    def doc_topics(self):
        return ["docs/bookmarks", "docs/git-experts"]

    def doc(self, topic):
        return {
            "docs/bookmarks": "# Bookmarks manual\n\n## Tracking\n\nTrack remote bookmarks.\n",
            "docs/git-experts": GIT_EXPERTS,
        }[topic]


def test_command_sections_capture_canonical_paths():
    assert list(parse_command_sections(MARKDOWN_HELP)) == ["", "log"]


def test_compact_language_help_keeps_grammar_but_not_function_catalog():
    compact = compact_keyword("revsets", REVSETS)
    assert compact is not None
    assert "## Operators" in compact
    assert "Lots of examples" not in compact
    assert "Return ancestors" not in compact
    assert "- Functions" in compact


def test_search_prefers_matching_official_definition():
    selected = extract_relevant(REVSETS, "ancestors")
    assert selected == "* `ancestors(x, [depth])`: Return ancestors of x.\n"


def test_full_keyword_is_returned_verbatim(capsys):
    source = FakeSource()
    assert run_help(["revsets", "--full"], source) == 0
    assert capsys.readouterr().out == REVSETS


def test_malformed_compact_help_falls_back_to_full(capsys):
    source = FakeSource(malformed_keyword=True)
    assert run_help(["revsets"], source) == 0
    captured = capsys.readouterr()
    assert captured.out == "unstructured official output\n"
    assert "showing full topic" in captured.err


def test_command_defaults_short_and_full_is_explicit(capsys):
    source = FakeSource()
    assert run_help(["log"], source) == 0
    assert run_help(["log", "--full"], source) == 0
    assert source.command_calls == [(("log",), False), (("log",), True)]
    assert capsys.readouterr().out == "short help for log\nlong help for log\n"


def test_list_discovers_topics_without_hard_coding(capsys):
    assert run_help(["--list"], FakeSource()) == 0
    output = capsys.readouterr().out
    assert "filesets" in output
    assert "docs/git-experts" in output
    assert "jj log" in output


def test_manual_pages_use_an_explicit_docs_namespace(capsys):
    source = FakeSource()

    assert run_help(["docs/git-experts"], source) == 0
    compact = capsys.readouterr().out
    assert "Why Git experts may prefer Jujutsu" in compact
    assert "Available sections" in compact
    assert "Use `jj evolog`" not in compact

    assert run_help(["docs/git-experts", "--search", "evolution"], source) == 0
    assert "Use `jj evolog`" in capsys.readouterr().out


def test_embedded_keyword_wins_while_docs_collision_stays_addressable(capsys):
    source = FakeSource()

    assert run_help(["bookmarks", "--full"], source) == 0
    assert capsys.readouterr().out.startswith("# Bookmarks keyword")
    assert run_help(["docs/bookmarks", "--full"], source) == 0
    assert capsys.readouterr().out.startswith("# Bookmarks manual")


def test_explicit_docs_directory_is_read_without_platform_assumptions(tmp_path):
    docs = tmp_path / "odd-package-layout" / "manual"
    (docs / "guides").mkdir(parents=True)
    (docs / "git-experts.md").write_text(GIT_EXPERTS, encoding="utf-8")
    (docs / "guides" / "multiple_remotes.md").write_text("# Multiple remotes\n", encoding="utf-8")
    source = HelpSource(docs_dir=docs)

    assert source.doc_topics() == ["docs/git-experts", "docs/guides/multiple-remotes"]
    assert source.doc("docs/git-experts") == GIT_EXPERTS


def test_missing_packaged_docs_explain_how_to_configure_them(monkeypatch):
    source = HelpSource(executable="jj-without-docs")
    monkeypatch.setattr(source, "_find_docs_dir", lambda: None)

    with pytest.raises(
        HelpError,
        match=(
            r"jj docs directory not detected\. Set "
            r"JJ_SENSEI_DOCS_DIR=/path/to/jj/docs to use this feature\."
        ),
    ):
        source.doc_topics()


def test_manifest_lock_cli_is_prose_free(capsys):
    assert run_help(["--manifest-lock"], FakeSource()) == 0
    lock = json.loads(capsys.readouterr().out)
    assert lock["jj_version"] == "jj 9.9.9"
    assert set(lock["commands"]) == {"jj", "log"}
    assert all(value.startswith("sha256:") for value in lock["keywords"].values())


def test_manifest_modes_are_mutually_exclusive(capsys):
    assert run_help(["--manifest", "--list"], FakeSource()) == 2
    assert "must be used by itself" in capsys.readouterr().err


def test_package_cli_forwards_rtfm_options(monkeypatch):
    received = None

    def fake_main(args):
        nonlocal received
        received = args
        return 17

    monkeypatch.setattr(cli.knowledge, "main", fake_main)
    assert cli.main(["rtfm", "--list"]) == 17
    assert received == ["--list"]


def test_manifest_records_commands_options_and_language_definitions():
    manifest = build_manifest(FakeSource())
    assert manifest["commands"]["log"]["options"] == ["--revisions", "-r"]
    assert manifest["commands"]["jj"]["subcommands"] == ["log"]
    assert manifest["keywords"]["revsets"]["definitions"] == [
        "ancestors(x, [depth])",
        "descendants(x, [depth])",
        "x | y",
    ]
    assert manifest["docs"]["docs/git-experts"]["headings"] == [
        "# Jujutsu for Git experts",
        "## The Git index/staging area",
        "## The evolution log",
    ]


def test_manifest_lock_detects_structural_drift():
    original = {
        "schema": 2,
        "jj_version": "jj 1",
        "commands": {},
        "keywords": {},
        "docs": {},
    }
    changed = {**original, "commands": {"new": {}}}
    assert manifest_lock(original)["commands"] != manifest_lock(changed)["commands"]
    assert manifest_differences(original, changed) == ["added commands: new"]
    assert manifest_differences(manifest_lock(original), manifest_lock(changed)) == [
        "added commands: new"
    ]

    before = {**original, "commands": {"rebase": {"options": ["--onto"]}}}
    after = {
        **original,
        "commands": {"rebase": {"options": ["--insert-after", "--onto"]}},
    }
    assert manifest_differences(manifest_lock(before), manifest_lock(after)) == [
        "changed command: rebase"
    ]


@pytest.mark.contract
def test_installed_jj_help_contract_has_not_drifted():
    """Pin the shape of the installed jj's help so an upgrade surfaces changes.

    The fingerprint is version-specific by construction, so this can only assert
    against the jj it was recorded for. Skip loudly on any other version rather
    than turning every contributor's suite red — `pytest -ra` prints the reason,
    and `pytest -m contract` selects this check on its own.
    """
    from jj_sensei.knowledge import HelpError, HelpSource

    expected = json.loads(
        (Path(__file__).parent / "fixtures" / "knowledge-contract.json").read_text(encoding="utf-8")
    )
    source = HelpSource()
    try:
        installed = source.version()
    except HelpError as error:
        pytest.skip(f"no usable jj on PATH: {error}")
    if installed != expected["jj_version"]:
        pytest.skip(
            f"contract was recorded for {expected['jj_version']!r} but {installed!r} is installed; "
            "review the differences, then re-record with `jj-sensei rtfm --manifest-lock`"
        )

    actual = manifest_lock(build_manifest(source))
    assert actual == expected, (
        "The installed jj help contract changed. Review command/option/language changes, "
        "then regenerate the structural fingerprint deliberately."
    )
