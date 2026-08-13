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

Use a help keyword for a language or conceptual topic. The installed jj lists
the available keywords; common topics include `revsets`, `filesets`,
`templates`, `config`, `bookmarks`, `glossary`, and `tutorial`.

Use a canonical command path for command help. The default is jj's short help;
`--full` requests its complete long help. For keyword topics, the default keeps
the introduction, essential grammar where applicable, and a section outline.
Use `--search TERM` to extract matching official definitions or sections and
`--full` only when the complete topic is needed.

`--search` belongs to `rtfm` alone. Passing it to `rtfd` is a usage error; the
two helpers select depth differently, so read the paragraph below before
composing an `rtfd` call.

A `--search` hit is an extract, not a section. `rtfm config --search TERM`
often returns a stub that opens mid-section and trails off into a neighboring
option's prose. Treat a result that does not read as a complete definition as a
pointer, and re-read the whole section with `rtfd docs/config --section
HEADING`.

Route links from executable help back through the installed manual. For a link
under `https://docs.jj-vcs.dev/latest/PAGE`, strip that prefix and any trailing
slash, then run `rtfd docs/PAGE`; for example, links from `rtfm git --full` map
to `rtfd docs/git-comparison` and `rtfd docs/git-command-table`. If the
installed manual has no matching page, report that it is unavailable; do not
fetch documentation for another jj version from the web.

Use `rtfd` and the explicit `docs/` prefix for broader manual pages. `--list`
discovers their names, including nested pages such as
`docs/guides/divergence`; `--toc`, `--section HEADING`, and `--full` select how
much to read, and they are mutually exclusive. `--toc` first, then `--section`
on a heading it printed, is the cheapest route into a long page. Use
`--yaml-table docs/PAGE.yml` when a page references an
official YAML table asset. The Git command table is only about 60 compact
rows, so loading it whole is reasonable when the complete inventory is useful.
If you will not need all roughly 60 rows, add `--search-git 'regex'` or
`--search-jj 'regex'` to filter only that command field with a case-sensitive
regular expression; combine several commands with regex alternation. Those two
filters apply only to `--yaml-table`; use `--section` on a Markdown page. The
namespace intentionally distinguishes embedded `bookmarks` help from the
packaged `docs/bookmarks` page.

The helper first looks for docs shipped beside the resolved jj executable. Set
`JJ_SENSEI_DOCS_DIR=/path/to/jj/docs` when a package uses an unusual layout. If
no docs directory is detected, the helper reports that configuration and does
not fetch documentation from the network. For configured docs, it warns when
version metadata beside the directory does not match the installed jj. Add a
`.jj-version` file containing the release number when keeping only `docs/`.

Treat all output as authoritative for the installed jj version. Repository and
startup safety policy remains authoritative about which otherwise-valid jj
operations an agent may perform. If a required command or behavior is absent,
do not guess from Git or documentation for another jj version.
