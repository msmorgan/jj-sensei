from __future__ import annotations

import pytest

from jj_sensei.documentation import (
    parse_yaml_table,
    render_toc,
    render_yaml_table,
    run_docs,
)
from jj_sensei.knowledge import HelpError, HelpSource

YAML_TABLE = """\
- Use case: Compare A | B
  Git command: >
    `git diff A B`
  Jujutsu command: >
    `jj diff --from A --to B`
  Notes:

- Use case: >
    Fold a long
    description
  Git command: Not supported
  Jujutsu command: >
    `jj new`
  Notes: Safe <example>
"""


def _source(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "# Guide\n\nIntroduction.\n\n## First\n\nFirst body.\n\n### Detail\n\nDetail body.\n",
        encoding="utf-8",
    )
    (docs / "git-command-table.yml").write_text(YAML_TABLE, encoding="utf-8")
    return HelpSource(docs_dir=docs)


def test_yaml_table_parser_folds_blocks_and_preserves_empty_cells():
    rows = parse_yaml_table(YAML_TABLE)

    assert len(rows) == 2
    assert rows[0].use_case == "Compare A | B"
    assert rows[0].notes == ""
    assert rows[1].use_case == "Fold a long description"


def test_yaml_table_renderer_escapes_markdown_table_hazards():
    rendered = render_yaml_table(YAML_TABLE)

    assert rendered.startswith("| Use case | Git command | Jujutsu command | Notes |\n")
    assert r"Compare A \| B" in rendered
    assert "Safe &lt;example&gt;" in rendered


def test_rtfd_renders_a_canonical_yaml_table_asset(tmp_path, capsys):
    source = _source(tmp_path)

    assert run_docs(["--yaml-table", "docs/git-command-table.yml"], source) == 0
    assert "`jj diff --from A --to B`" in capsys.readouterr().out


def test_rtfd_searches_only_the_git_command_column(tmp_path, capsys):
    source = _source(tmp_path)

    assert (
        run_docs(["--yaml-table", "docs/git-command-table.yml", "--search", "GIT DIFF"], source)
        == 0
    )
    output = capsys.readouterr().out
    assert "Compare A" in output
    assert "Fold a long description" not in output

    assert (
        run_docs(["--yaml-table", "docs/git-command-table.yml", "--search", "jj new"], source) == 2
    )
    assert "no Git command matching" in capsys.readouterr().err


def test_rtfd_rejects_yaml_asset_path_traversal(tmp_path, capsys):
    source = _source(tmp_path)

    assert run_docs(["--yaml-table", "docs/../outside.yml"], source) == 2
    assert "canonical docs/ path" in capsys.readouterr().err


def test_rtfd_lists_pages_and_navigates_headings(tmp_path, capsys):
    source = _source(tmp_path)

    assert run_docs(["--list"], source) == 0
    assert capsys.readouterr().out == "docs/guide\n"

    assert run_docs(["docs/guide"], source) == 0
    compact = capsys.readouterr().out
    assert "Introduction." in compact
    assert "## Available sections" in compact
    assert "First body." not in compact

    assert run_docs(["docs/guide", "--toc"], source) == 0
    assert capsys.readouterr().out == "- Guide\n  - First\n    - Detail\n"

    assert run_docs(["docs/guide", "--section", "First"], source) == 0
    section = capsys.readouterr().out
    assert "## First" in section
    assert "### Detail" in section


def test_render_toc_requires_markdown_headings():
    with pytest.raises(HelpError, match="no Markdown headings"):
        render_toc("plain text\n")
