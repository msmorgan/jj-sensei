---
name: knowledge
description: Read authoritative command help and manual pages matching the installed Jujutsu version. Use before any jj operation not covered by injected repository guidance; when command flags or semantics are uncertain; or when revsets, filesets, templates, configuration, bookmarks, glossary terms, workspaces, Git interop, or other jj behavior needs authoritative version-matched clarification.
---

# Read the Installed jj Manual

Resolve the helper from this loaded skill, not from the target repository:

```bash
"<skill-dir>/scripts/rtfm" --list
"<skill-dir>/scripts/rtfm" revsets
"<skill-dir>/scripts/rtfm" revsets --search ancestors
"<skill-dir>/scripts/rtfm" revsets --search Aliases
"<skill-dir>/scripts/rtfm" config --search immutable_heads
"<skill-dir>/scripts/rtfm" revsets --full
"<skill-dir>/scripts/rtfm" rebase
"<skill-dir>/scripts/rtfm" git push --full
"<skill-dir>/scripts/rtfd" --list
"<skill-dir>/scripts/rtfd" docs/git-experts --toc
"<skill-dir>/scripts/rtfd" docs/operation-log --section evolog
"<skill-dir>/scripts/rtfd" --yaml-table docs/git-command-table.yml
"<skill-dir>/scripts/rtfd" --yaml-table docs/git-command-table.yml --search-git '(rebase|merge)'
"<skill-dir>/scripts/rtfd" --yaml-table docs/git-command-table.yml --search-jj '(rebase|arrange)'
```

A repository's own configuration is a common reason to reach for this skill:
when a `jj config get` result is an unfamiliar revset alias, `rtfm revsets
--search Aliases` gives the `[revset-aliases]` syntax it's written in, and
`rtfm config --search immutable_heads` gives that alias's documented meaning.
Decode definitions from these rather than inferring them from names.

Use a help keyword for a language or conceptual topic — the installed jj
lists available keywords; common ones include `revsets`, `filesets`,
`templates`, `config`, `bookmarks`, `glossary`, and `tutorial`. Use a
canonical command path for command help. Short help is the default; `--full`
gives complete long help. For keyword topics the default keeps the
introduction, essential grammar, and a section outline; `--search TERM`
extracts matching definitions or sections, and `--full` returns the complete
topic — use it only when the complete topic is needed.

`--search` belongs to `rtfm` alone — passing it to `rtfd` is a usage error,
since the two helpers select depth differently.

A `--search` hit is an extract, not a section: `rtfm config --search TERM`
often returns a stub that opens mid-section and trails into a neighboring
option's prose. Treat an incomplete-looking result as a pointer, and re-read
the whole section with `rtfd docs/config --section HEADING`.

Route links from executable help back through the installed manual. For a
link under `https://docs.jj-vcs.dev/latest/PAGE`, strip that prefix and any
trailing slash, then run `rtfd docs/PAGE`; e.g. links from `rtfm git --full`
map to `rtfd docs/git-comparison` and `rtfd docs/git-command-table`. If the
installed manual has no matching page, report that it is unavailable; do not
fetch documentation for another jj version from the web.

Use `rtfd` with the explicit `docs/` prefix for broader manual pages.
`--list` discovers page names, including nested ones like
`docs/guides/divergence`; `--toc`, `--section HEADING`, and `--full` select
how much to read and are mutually exclusive — `--toc` first, then `--section`
on a printed heading, is the cheapest route into a long page. Use
`--yaml-table docs/PAGE.yml` for a page's official YAML table asset. The Git
command table is only about 60 compact rows, so loading it whole is
reasonable; otherwise add `--search-git 'regex'` or `--search-jj 'regex'` to
filter that field with a case-sensitive regular expression (combine commands
via alternation). These two filters apply only to `--yaml-table`; use
`--section` for Markdown pages. The namespace deliberately distinguishes
embedded `bookmarks` help from the packaged `docs/bookmarks` page.

The helper first looks for docs shipped beside the resolved jj executable;
set `JJ_SENSEI_DOCS_DIR=/path/to/jj/docs` for unusual layouts. If none is
detected, it reports that and does not fetch documentation from the network.
It also warns when configured docs' version metadata does not match the
installed jj — add a `.jj-version` file with the release number when keeping
only `docs/`.

Treat all output as authoritative for the installed jj version — though
repository and startup safety policy still governs which otherwise-valid jj
operations an agent may perform. If a required command or behavior is
absent, do not guess from Git or another jj version's documentation.
