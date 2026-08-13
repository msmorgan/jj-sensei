# jj-sensei

*Teach your agents Jujutsu.*

A Claude Code and Codex plugin for working in [Jujutsu (jj)](https://jj-vcs.github.io/jj/) repositories. Three layers:

1. **Eager** — a `SessionStart` hook injects the operational jj model, common Git-to-jj command mappings, and repository safety constraints, only when the session starts beneath a `.jj/` directory. The detector does not run jj, so it cannot trigger colocated Git synchronization. Zero prompt cost elsewhere.
2. **Authoritative** — the `knowledge` skill extracts focused sections from documentation embedded in the installed jj binary. `--full` exposes complete command or language help without vendoring it.
3. **Operational** — Python subskills provide resumable stale/divergence/conflict repair and install the multi-workspace immutability guard. They have no runtime dependencies beyond Python and jj.

The toolkit is standalone: it combines local agent policy with documentation from the jj executable actually present on the machine.

## Knowledge

The skill wrapper normalizes jj's native help interface and keeps routine
queries compact:

```bash
skills/knowledge/scripts/knowledge --list
skills/knowledge/scripts/knowledge revsets
skills/knowledge/scripts/knowledge revsets --search ancestors
skills/knowledge/scripts/knowledge revsets --full
skills/knowledge/scripts/knowledge git push --full
```

Command topics default to short help. Language topics default to essential
grammar plus a section outline; `--search` extracts a matching official
definition or section, and `--full` returns the complete installed topic.

Tests pin a prose-free structural fingerprint for the supported jj version:
command paths, usage shapes, arguments, options, subcommands, keyword heading
trees, and revset/fileset/template definitions. A jj upgrade therefore fails
the drift test until its interface changes have been reviewed deliberately.
After review, `skills/knowledge/scripts/knowledge --manifest-lock` emits the updated
prose-free lock.

## Install

Register the federated `msmorgan` marketplace once:

### Claude Code

```bash
claude plugin marketplace add msmorgan/marketplace
claude plugin install jj-sensei@msmorgan
```

### Codex

```bash
codex plugin marketplace add msmorgan/marketplace
codex plugin add jj-sensei@msmorgan
```

Start a new session after installing or updating the plugin.

## Layout

```
.claude-plugin/plugin.json     Claude Code plugin manifest
.codex-plugin/plugin.json      Codex plugin manifest
hooks/hooks.json               SessionStart registration
hooks/session_start.sh         jj-repo detection
hooks/jj-context.md            the injected blurb
skills/knowledge/              installed-help extractor
skills/harmony/                inspect, converge, resolve, and repair
skills/boundaries/             install and audit workspace isolation
src/jj_sensei/                 Python implementation
pyproject.toml                 package, CLI, test, and lint metadata
```

For local package development:

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```
