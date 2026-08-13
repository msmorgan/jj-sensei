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
"<skill-dir>/scripts/rtfm" docs/git-experts
"<skill-dir>/scripts/rtfm" docs/operation-log --search evolog
```

Use a help keyword for a language or conceptual topic. The installed jj lists
the available keywords; common topics include `revsets`, `filesets`,
`templates`, `config`, `bookmarks`, `glossary`, and `tutorial`.

Use a canonical command path for command help. The default is jj's short help;
`--full` requests its complete long help. For keyword topics, the default keeps
the introduction, essential grammar where applicable, and a section outline.
Use `--search TERM` to extract matching official definitions or sections and
`--full` only when the complete topic is needed.

Use the explicit `docs/` prefix for broader manual pages. `--list` discovers
their names, including nested pages such as `docs/guides/divergence`. This
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
