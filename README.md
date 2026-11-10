# jj-sensei

*Teach your agents Jujutsu.*

jj-sensei is an Antigravity, Claude Code, and Codex plugin that teaches
coding agents to use [Jujutsu (jj)](https://jj-vcs.github.io/jj/) fluently
and safely — giving them working knowledge for everyday jj operations,
direct access to the manual installed on your machine, and guarded tools for
when repositories get difficult.

It does not replace jj or hide it behind a new version-control abstraction.
Agents still use the real `jj` CLI and learn its native model.

## What it does automatically

When a session starts anywhere beneath a `.jj/` directory, jj-sensei injects
a one-line preamble — in Antigravity, only before the first model invocation.
It positively names `jj` as the repository's exclusive version-control tool
and has the agent load the `wisdom` skill once, before its first
version-control command (status included). Context compaction evicts the
skill text even when the summary lists it as loaded, so the preamble has the
agent load it once more after compaction.

Everything else is pulled on demand rather than pushed into every session.
`wisdom` is the hub an agent lands on: jj's model in a paragraph, the rules
that bind every command, and two routing tables — one keyed on what jj printed,
one on what was asked. Common Git reflexes are answered inline there in a
line; anything carrying a trap routes to the smallest sufficient reference
set.

The repository detector only examines parent directories and deliberately
never invokes jj, since even a read-looking jj command can synchronize a
colocated Git repository. Outside a jj repository, the hook emits nothing.

A second hook shows a compact live status line at session start and after
each file-writing or shell tool: workspace and working-copy change, a
description and edit-volume summary, and conflicts, stale workspaces,
bookmarks on `@`, orphaned workspaces, and divergence made hard to miss. When a
shell command starts with `cd <workspace> &&` (or `;`), the line describes that
workspace rather than the tool's reported directory. Post-tool probes eagerly
snapshot agent-authored filesystem edits, suppressing a repeated line until
rendered state changes. Warnings about the workspace's own state — a stale
working copy, a workspace jj cannot read or the hook could not probe, or
divergence under `@` — are the exception and repeat on every call until they
clear. Suppression is tracked per workspace and per agent, so subagents
sharing their parent's session each see the line. Beyond
ambient visibility, these eager snapshots continuously populate jj's evolution
log (`jj evolog`), turning raw tool executions into an addressable patch-level
trace that lets agents reconstruct clean commit series after the fact.

Divergence is watched repo-wide, not just under `@`: the hook remembers the
set of `divergent() & mutable()` commits in the repository's shared `.jj/repo`
directory, so growth caused anywhere — another workspace, another agent, a
background command — is noticed by the next hook call in any workspace. Each
agent is shown such growth once, as a separate line naming the change, the
number of visible copies, and the operation that created them (its workspace
and command line), followed by standing `⚠ @ or its ancestors divergent` and
`⚠ N divergent commits repo-wide` suffixes on the status line until the twins
are resolved. Only the first of those repeats on every call; the repo-wide
count, like the orphaned-workspace notice, is shown once per agent and again
whenever it changes, since one agent usually cannot fix another's commits. Divergence that already exists when jj-sensei first looks at a
repository is reported by the suffix only.

Status and history-repair operations share one short workspace lock. The
divergence probe runs outside it, so a busy workspace still reports
divergence. The hook never repairs, unstales, or changes graph topology, and
always lets the turn continue. Antigravity receives changed status on the next invocation after a
tool call; Claude Code and Codex receive it directly.

A third hook guards shell commands before they run, on Antigravity, Claude
Code, and Codex.
A commit id still resolves after another workspace rewrites and hides that
commit, and `jj new`, `rebase`, `squash`, and the other mutating commands
then resurrect it and its hidden ancestry as divergent copies. The guard
denies a mutating jj command that names a hidden commit id and replies with
that commit's change id and current version. In a stale workspace it denies a
bare `jj workspace update-stale`, which would snapshot on-disk edits at the
old operation and can fork the working-copy change, and points to `harmony`'s
`repair` instead. It warns, without blocking, when a mutating command takes
its revision from a shell variable or command substitution it cannot check,
and when any other jj command is about to run in a stale workspace. Staleness
is read from the working copy's checkout record and the operation heads,
without a snapshot. The guard reads the command text only: chains and
`bash -c '...'` bodies are scanned, but script files are out of its sight,
and for them the status hook's repo-wide divergence alarm is the backstop.
Anything the guard cannot read, or any jj failure, lets the command proceed.
When it does not deny, it never approves either, so the host's own permission
prompts are unchanged. Antigravity shows a hook's message to the model only
with a denial, so there a warning arrives with the status line on the next
model invocation instead. OpenCode does not run the guard.

## Skills

Four skills ship today, forming one lesson: every version control task
begins at the `wisdom` hub, which answers directly or routes onward —
repository trouble to `harmony`, multi-workspace safety to `boundaries`, and
anything still unresolved to `knowledge`.

### knowledge

`knowledge` is the fallback: load it whenever a question about jj usage
survives the hub and its references. It reads documentation matching the
installed jj version — a command, a language topic like revsets or filesets,
a `docs/` manual page, a definition, or a full section. `rtfm` reads executable help; `rtfd`
navigates Markdown pages and referenced YAML tables, including
case-sensitive regular-expression search of the Git or Jujutsu command
field. The Git command table is roughly 60 compact rows and can be loaded
directly, or narrowed by search. Both helpers avoid vendoring a second,
possibly stale copy of jj's documentation.

Command and language help comes from the local executable; manual pages come
from the package when detected, or an explicit `JJ_SENSEI_DOCS_DIR` for
unusual layouts. The helper never fetches missing documentation. Tests
fingerprint both surfaces when available, so jj upgrades expose new commands,
options, language features, and pages for review. Configured manual trees
warn when detectable version metadata drifts from the installed jj;
docs-only copies can carry a `.jj-version` sidecar.

### harmony

`harmony` handles messy states that otherwise become long, fragile runbooks:
stale workspaces, divergent working-copy successors, and file conflicts. A
compact diagnosis router discloses only the affected branch. Its one-stop
repair command updates stale state, converges divergent working-copy
successors through `jj converge`, and walks mutable conflicts oldest to newest.

Repair is locked and crash-resumable: it journals completed transitions,
leaves merging divergent work to jj, automates only the conflict resolutions
it can establish are safe, and pauses with a useful diagnosis when needed. Narrower tools inspect conflict markers,
accept a specifically chosen representation, and run conservative mechanical
resolutions.

A read-only recovery helper reads one file's earlier content out of jj's
operation snapshots, reporting only the operations where that content
actually changed. It loads the repository at an operation and never restores
it.

It never performs operation-log surgery or bypasses immutability. Within a
repair invocation, an internal error preserves the journal and blocks later
transaction steps — but ordinary jj command errors don't trigger a stop for
permission.

### wisdom

`wisdom` is the hub. It carries jj's model, the always-binding rules — the
non-interactive constraint, the ask-first rules, the forbidden operations —
and the routing tables that assign every requested operation and jj output
token to its owner. Publishing is split by push, sync, bookmark, bookmark
conflict, and tag branches so unrelated guidance stays unloaded.

When jj refuses an operation as immutable, a read-only helper reports which
clause of the active `immutable_heads()` definition captures the revision
and which bookmark or tag anchors it, explaining the refusal rather than
working around it.

It also records small, high-leverage idioms easy to miss in the full manual:
choosing whether a selected fileset becomes the earlier or later half of a
split, expressing after/before placement as an idempotent invariant, and
using `-A` with `-B` to name one exact graph edge. It prefers explicit `-r`
revsets — including `ROOT::` for a subtree — and previews nontrivial
selections before mutation, favoring `-A`/`-B` for ordinary insertion and
reordering while reserving `-o` for intentional forks and merges.

For inspection, `wisdom` supplies small, tested template idioms for
identities, state flags, parents, changed paths, stats, and machine-readable
lists. It favors built-in and bounded views before custom templates or full
patches; anything beyond the catalog routes to `knowledge`'s version-matched
template reference rather than being guessed.

Because the live-status hook snapshots after agent tools, `wisdom` can use
`jj evolog` to recover the ordered patches inside an oversized `@` and
rebuild them into a coherent commit series. The snapshots preserve execution
history; the agent still chooses semantic boundaries, not every tool call as
a commit. The same snapshots let it roll a described change back to an earlier
version of itself with one scoped `jj restore --from SNAPSHOT --into CHANGE
PATH`, instead of restoring a whole tree and rebasing onto it.

Its guarded escape hatch is interpolation: turning one mixed change into two
by constructing an intermediate state between them when that isn't a matter
of selecting files and lines — e.g. because generated artifacts must be
recreated at that state. The guarded helper journals every transition and
can finish or abort an interrupted construction. When the intermediate tree
already exists, `interpolate insert --from SNAPSHOT -B TARGET -m DESCRIPTION`
inserts it without switching the working copy or changing descendant trees.
Both modes are intentionally narrow, not general replacements for `jj split`.

### boundaries

`boundaries` installs and audits a repository-level `immutable_heads()`
policy for repositories with multiple live jj workspaces: from a feature
workspace, other live working-copy lines become immutable; from `default`,
the coordinator keeps the flexibility to rewrite those feature stacks.

The setup helper verifies the configuration after installing it and can also
run in read-only check mode. It detects shared mutable ancestry between live
feature workspaces and treats that as a safe stop rather than teaching
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

### OpenCode

```bash
opencode plugin add github:msmorgan/jj-sensei
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
package.json                OpenCode package manifest
index.js                    OpenCode directory entrypoint
.opencode/plugins/          OpenCode plugin implementation
hooks/hooks.json            hook manifest for Claude Code and Codex
hooks/                      startup guidance, live status, and pre-command guard scripts
skills/                     the four skills above, loaded by every host
src/jj_sensei/              shared Python implementation
```

For local package development:

```bash
uv run --extra dev pytest
uv run --extra dev ruff check .
```
