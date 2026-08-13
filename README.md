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

A second hook provides a compact live status line at session start and after
each file-writing or shell tool. It identifies the workspace and working-copy
change, summarizes descriptions and edit volume, and makes conflicts, stale
workspaces, and bookmarks on `@` difficult to miss. Post-tool probes eagerly
snapshot agent-authored filesystem edits, but repeated context is suppressed
until the rendered state changes.

Status and history-repair operations share one short workspace lock. The hook
never repairs, unstales, or changes graph topology, and it always allows the
turn to continue. Antigravity receives changed status on the invocation after a
tool call; Claude Code and Codex receive it directly.

## Skills

Four skills ship today. They are meant to feel like parts of one lesson:
routine work begins with the injected guidance, uncertainty goes to
`knowledge`, uncommon history shaping goes to `wisdom`, repository trouble goes
to `harmony`, and multi-workspace safety comes from `boundaries`.

### knowledge

`knowledge` reads authoritative documentation matching the installed jj
version. An agent can ask for a command, a language topic such as revsets or
filesets, a broader `docs/` manual page, one relevant definition, or the full
section. The included `rtfm` helper reads executable help, while `rtfd`
navigates Markdown pages and referenced YAML tables, including field-aware,
case-sensitive regular-expression search of either the Git or Jujutsu command
field. The complete Git command table is roughly 60 compact rows and can be
loaded directly; when the complete inventory is unnecessary, search narrows it
in one call. Both helpers avoid vendoring a second, possibly stale copy of jj's
documentation.

Command and language help comes from the local executable. Manual pages come
from the package when detected, or from an explicit `JJ_SENSEI_DOCS_DIR` for
unusual layouts. The helper does not fetch missing documentation. Tests
fingerprint both surfaces when available so jj upgrades expose new commands,
options, language features, and pages for deliberate review. Configured manual
trees also warn when detectable version metadata has drifted from the installed
jj; docs-only copies can provide a `.jj-version` sidecar.

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

A read-only recovery helper reads one file's earlier content out of jj's
operation snapshots, reporting only the operations where that content actually
changed. It loads the repository at an operation and never restores it.

It never performs operation-log surgery or bypasses immutability. Within a
repair invocation, an internal error preserves the journal and prevents later
transaction steps; it does not turn ordinary jj command errors into a reason to
stop and ask for permission.

### wisdom

`wisdom` recognizes history-shaping situations and routes each one to a
focused technique. Its entry point is a compact index keyed on what a user
actually asked for—move this fix into that commit, undo this, publish this,
reorder these—rather than a general tutorial or a long sequence of commands.

When jj refuses an operation as immutable, a read-only helper reports which
clause of the active `immutable_heads()` definition captures the revision and
which bookmark or tag anchors that clause, so the refusal can be explained
rather than worked around.

It also records small, high-leverage idioms that are easy to miss in the full
manual: choosing whether a selected fileset becomes the earlier or later half
of a split, expressing after/before placement as an idempotent invariant, and
using `-A` with `-B` to name one exact graph edge. It prefers explicit `-r`
revsets—including `ROOT::` for a subtree—and previews nontrivial selections
before mutation. For ordinary insertion and reordering it prefers `-A`/`-B`;
`-o` is reserved for intentional forks and merges.

For inspection, `wisdom` supplies small, tested template idioms for identities,
state flags, parents, changed paths, stats, and machine-readable lists. It
prefers built-in and bounded views before custom templates or full patches;
anything beyond the catalog routes to `knowledge`'s installed, version-matched
template reference instead of being guessed.

Because the live-status hook snapshots after agent tools, `wisdom` can also use
`jj evolog` to recover the ordered patches inside an oversized `@` and rebuild
them as a coherent series of commits. The snapshots preserve execution history;
the agent still chooses semantic boundaries rather than treating every tool call
as a commit.

Its guarded escape hatch is interpolation: turning one mixed change into two
by constructing an intermediate state between two commits when doing so is not
a matter of selecting files and lines—for example, because generated artifacts
must be recreated at that state. jj has no index separate from its working-copy
commit, so the helper temporarily rehomes the upper revision's tree while
constructing the lower one. It inserts the change into an explicitly named
`-A`/`-B` edge, journals every transition, supports merge edges, and can finish
or abort after an interrupted process without operation-log recovery. It is
intentionally narrow, not a general replacement for `jj split`.

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

Each host discovers the plugin through its own manifest, and none of them is
referenced by any code in this repository. The hooks, skills, and Python behind
them are shared.

```text
plugin.json                 Antigravity plugin manifest
hooks.json                  Antigravity hook manifest
.claude-plugin/plugin.json  Claude Code plugin manifest
.codex-plugin/plugin.json   Codex plugin manifest
hooks/hooks.json            hook manifest for Claude Code and Codex
hooks/                      startup guidance and live status hook scripts
skills/                     the four skills above, loaded by every host
src/jj_sensei/              shared Python implementation
```

For local package development:

```bash
uv run --extra dev pytest
uv run --extra dev ruff check .
```
