# jj-sensei

*Teach your agents Jujutsu.*

jj-sensei is an Antigravity, Claude Code, and Codex plugin that teaches coding
agents to use [Jujutsu (jj)](https://jj-vcs.github.io/jj/) fluently and safely.
It gives them the working knowledge they need for everyday jj operations,
direct access to the manual installed on your machine, and guarded tools for
the situations where repositories become difficult.

It does not replace jj or hide it behind a new version-control abstraction.
Agents still use the real `jj` CLI and learn its native model.

## What it does automatically

When a session starts anywhere beneath a `.jj/` directory, jj-sensei injects a
practical startup guide. In Antigravity this happens before the first model
invocation; later invocations are left alone. The guide covers the things an
agent needs before its first command:

- jj's working-copy model and the absence of a staging area
- direct Git-to-jj equivalents for common operations
- change IDs, bookmarks, rebasing, workspaces, and colocated Git repositories
- Git-shaped diff output and non-interactive command hygiene
- workspace immutability and the escape hatches an agent must never use
- when to stop guessing and consult the installed jj manual

The repository detector only examines parent directories; it deliberately does
not invoke jj, since even a read-looking jj command can synchronize a colocated
Git repository. Outside a jj repository, the hook emits nothing.

## Skills

Three skills ship today. They are meant to feel like parts of one lesson:
routine work begins with the injected guidance, uncertainty goes to
`knowledge`, repository trouble goes to `harmony`, and multi-workspace safety
comes from `boundaries`.

### knowledge

`knowledge` reads authoritative documentation matching the installed jj
version. An agent can ask for a command, a language topic such as revsets or
filesets, a broader `docs/` manual page, one relevant definition, or the full
section. The included `rtfm` helper keeps ordinary answers compact without
vendoring a second, possibly stale copy of jj's documentation.

Command and language help comes from the local executable. Manual pages come
from the package when available, with a fallback to the matching official
`jj-vcs/jj` release tag for packages such as Nixpkgs that omit them. Tests
fingerprint both surfaces so jj upgrades expose new commands, options, language
features, and pages for deliberate review.

### harmony

`harmony` handles the messy states that otherwise turn into long, fragile
runbooks: stale workspaces, divergent working-copy successors, and file
conflicts. Its one-stop repair command updates stale state, converges only
equivalent divergence, and walks mutable conflicts from oldest to newest.

Repair is locked and crash-resumable. It journals completed transitions,
automates only resolutions it can establish are safe, and pauses with a useful
diagnosis when human judgment is required. Narrower tools are included for
inspecting conflict markers, accepting a specifically chosen representation,
and running conservative mechanical resolutions.

It never performs operation-log surgery, bypasses immutability, or silently
continues after a failed jj command.

### boundaries

`boundaries` installs and audits a repository-level `immutable_heads()` policy
for repositories with multiple live jj workspaces. From a feature workspace,
other live working-copy lines become immutable; from the primary `default`
workspace, the coordinator retains the flexibility to rewrite those feature
stacks.

The setup helper verifies the configuration after installing it and can also
run in read-only check mode. It detects shared mutable ancestry between live
feature workspaces and treats that topology as a safe stop instead of teaching
agents to bypass the guard.

## Install

### Antigravity

```bash
agy plugin install https://github.com/msmorgan/jj-sensei
```

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

## Repository layout

```text
plugin.json, hooks.json   Antigravity plugin and hook manifests
hooks/                    Claude hook manifest and shared startup guidance
skills/knowledge/         version-matched access to installed jj help
skills/harmony/           stale-state, divergence, and conflict repair
skills/boundaries/        multi-workspace immutability setup and audit
src/jj_sensei/            shared Python implementation
```

For local package development:

```bash
python -m pip install -e '.[dev]'
pytest
ruff check .
```
