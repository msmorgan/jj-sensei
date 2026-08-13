---
name: knowledge
description: Read authoritative documentation embedded in the installed Jujutsu binary. Use before any jj operation not covered by injected repository guidance; when command flags or semantics are uncertain; or when revsets, filesets, templates, configuration, bookmarks, glossary terms, workspaces, Git interop, or other jj behavior needs authoritative version-matched clarification.
---

# Read the Installed jj Manual

Resolve the helper from this loaded skill, not from the target repository:

```bash
"<skill-dir>/scripts/knowledge" --list
"<skill-dir>/scripts/knowledge" revsets
"<skill-dir>/scripts/knowledge" revsets --search ancestors
"<skill-dir>/scripts/knowledge" revsets --full
"<skill-dir>/scripts/knowledge" rebase
"<skill-dir>/scripts/knowledge" git push --full
```

Use a help keyword for a language or conceptual topic. The installed jj lists
the available keywords; common topics include `revsets`, `filesets`,
`templates`, `config`, `bookmarks`, `glossary`, and `tutorial`.

Use a canonical command path for command help. The default is jj's short help;
`--full` requests its complete long help. For keyword topics, the default keeps
the introduction, essential grammar where applicable, and a section outline.
Use `--search TERM` to extract matching official definitions or sections and
`--full` only when the complete topic is needed.

Treat the output as the authority for the installed jj version. Repository and
startup safety policy remains authoritative about which otherwise-valid jj
operations an agent may perform. If a required command or behavior is absent,
do not guess from Git or documentation for another jj version.
