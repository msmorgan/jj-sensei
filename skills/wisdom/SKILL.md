---
name: wisdom
description: Load before every version-control command in a Jujutsu repository, including status and inspection. Applies the jj model and hard guardrails, then routes by request or output token.
metadata:
  kind: reference
---

# Jujutsu: the hub

Everything version-control in this repository starts here:

1. Ground the task in the model and command conventions below.
2. Scan **what jj printed** before **what was asked**; output tokens beat the
   user's phrasing.
3. Load every matched destination and no unrelated reference. Routing is
   complete when each relevant output token and requested operation has an
   owner. If no row owns one, load `knowledge`.
4. Apply the guardrail details before acting. A mutating plan is ready only
   when its referents exist, its target is mutable, and its postconditions are
   explicit.

## The model, in short

The working copy **is** a commit, `@`. There is no staging area and no `git
add`: every jj command snapshots all unignored edits into `@` first, so file
edits auto-amend it continuously. Refer to changes by **change ID**, which is
stable across rewrites, not by commit hash. Descendants rebase automatically
when you rewrite something, and conflicts are recorded in commits rather than
pausing a command. `.jj/` and `.git/` share one working copy in a colocated
repo; jj owns the refs and keeps git in sync with them.

Conventions for every invocation: put `--no-pager` immediately after `jj`;
request `--git` when output will be diff-shaped; pass `-m` whenever a command
could open a description editor (`describe`/`commit`/`squash`/`split`). On
`jj squash`, `-u` (`--use-destination-message`) keeps the destination's
existing description instead of prompting. `jj new` never opens an editor, so
its `-m` is a convenience for describing the change up front, not an
editor-avoidance requirement.

## Route on what jj printed

| jj printed | Go to |
|---|---|
| `??` after a bookmark name, or `(conflicted)` in `jj bookmark list` | [Reconcile a conflicted bookmark](references/shipping/bookmark-conflicts.md) |
| `(conflict)` on a revision, `×` in the log graph, `<<<<<<<` in a file | `harmony` skill |
| `Error: The working copy is stale` | `harmony` skill |
| `(divergent)`, or a change ID with a `/0`/`/1` suffix | `harmony` for this workspace's divergent working copy; otherwise `knowledge` for `rtfd docs/guides/divergence` |
| An immutability refusal | [Immutable-target triage](references/undoing.md#immutable-target-triage) |
| `[updated] untracked` after a fetch | [Fetch and track upstream](references/shipping/sync.md) |
| `Refused to snapshot some files`, or a `?` path under `Untracked paths:` | The path exceeds `snapshot.max-new-file-size` or is excluded by `snapshot.auto-track`; use `jj --no-pager file track --include-ignored PATH` when it belongs in history, otherwise leave or ignore it |
| An unfamiliar revset alias from `config get` | `knowledge` skill |

## Route on what was asked

| The request | Answer or destination |
|---|---|
| status / diff / log | `jj --no-pager st`; `jj --no-pager diff --git`; `jj --no-pager log -r ::@ -n 5 -T builtin_log_oneline` |
| stage a file (`git add`) | Nothing to do — every command snapshots all unignored edits under the size limit |
| force-add an ignored or oversized file (`git add -f`) | `jj --no-pager file track --include-ignored PATH` |
| commit everything | `jj --no-pager commit -m "..."` — describes `@`, then creates a fresh empty child |
| commit selected paths / amend / reword / move a fix into an earlier change | [Tidy the working copy](references/tidy.md) |
| stash / unstash | `jj --no-pager new <base> -m "..."` for the interruption; `jj --no-pager edit <wip>` to return |
| switch lines of work | `jj --no-pager edit <change>` to move onto one; `jj --no-pager new <base> -m "..."` to start one |
| who wrote this line (`git blame`) | `jj --no-pager file annotate PATH`; corroborate the last-touch result with that change's diff |
| stop tracking an ignored file | `jj --no-pager file untrack PATH` |
| uncommit / discard / revert / drop / recover lost work | [Undo without operation-log surgery](references/undoing.md) |
| split / reorder / rebase / cherry-pick / merge / insert mid-stack | [Place changes deliberately](references/placement.md) |
| push or publish work | [Push work](references/shipping/push.md) |
| fetch / track / rebase onto upstream / choose among remotes | [Fetch and track upstream](references/shipping/sync.md) |
| create / advance / rename / delete a bookmark | [Manage bookmarks](references/shipping/bookmarks.md) |
| resolve a conflicted bookmark | [Reconcile a conflicted bookmark](references/shipping/bookmark-conflicts.md) |
| create / move / track / publish / delete a tag | [Manage tags](references/shipping/tags.md) |
| check state / select revisions / build a compact view | [Use templates without guessing](references/templates.md) |
| reconstruct an oversized `@` into a series | [Reconstruct work with evolog](references/using-evolog.md) |
| restore a described change to one of its own snapshots | [Restore a change to one of its own snapshots](references/using-evolog.md#restore-a-change-to-one-of-its-own-snapshots) |
| build an intermediate state selection cannot express | [Interpolate a change](references/interpolate.md) |
| conflicts / stale workspace / divergence / recover a file from a snapshot | `harmony` skill |
| add or audit a workspace / multi-workspace immutability | `boundaries` skill |
| uncertain flag or semantics / no matching row | `knowledge` skill |

## Guardrail details

**Use non-interactive forms exclusively.** Commands that require an editor or
terminal UI are unavailable: interactive `split`/`squash`/`absorb` (`-i`, or
`split` with no fileset), `diffedit`, `resolve` without `--tool`, `arrange`,
`config edit`, and bare `describe`/`commit` without `-m`. Use these forms:
a `FILESET` argument to `split`/`squash`, `-m`/`-u` for descriptions,
hand-edited conflict markers for `resolve`, and `jj --no-pager config set
--repo KEY VALUE` (or `--user`) for `config edit`. A fileset selects whole
paths, so it cannot separate two hunks *within* one file; when a split runs
mid-file, say so, then propose a semantic boundary or use
[Interpolate a change](references/interpolate.md). If the user names an
interactive method, say in one sentence that this session can't open one and
name the substitute — never plan the editor, and never substitute silently.

**Ask before acting on an ambiguous or unverified referent — asking is
correct, not a failure.**

- *More than one change matches what the user said:* ask which one, naming
  candidates (change ID + description) from a single `jj --no-pager log -T
  builtin_log_oneline`. Ask **before** reading any diffs — guessing from them
  costs more than asking and still guesses.
- *The request names a bookmark, branch, or revision:* confirm it exists
  first, cheaply — `jj --no-pager bookmark list --all` or `jj --no-pager log
  -r '<name>'`. If not, say so and ask what was meant — don't invent it,
  substitute a similar name, or dig through history for something that
  resembles it.
- *The user says "the branch" but the repo has no such bookmark — or no
  bookmarks at all:* this is normal in jj, where lines of work are usually
  anonymous. Resolve it by matching the description across `jj --no-pager log
  -T builtin_log_oneline`, then **confirm the match with the user before
  acting on it**. A description match is a hypothesis, not a referent.

**`jj --no-pager bookmark list --all` and `jj --no-pager log` are the ground
truth for refs.** There's no separate git layer underneath to double-check. If
a ref is not in jj's output, it does not exist.

**Mutability is decided by `immutable_heads()`.** jj treats
`::(immutable_heads() | root())` as immutable and refuses to rewrite it; by
default that is `trunk() | tags() | untracked_remote_bookmarks()`. A repo may
extend it, so read the active definition rather than assume: `jj --no-pager
config get "revset-aliases.'immutable_heads()'"`. A repo that has never
configured this still answers — `builtin_immutable_heads()` **is** the
unmodified default, not a sign that something is missing. Only a definition
naming something else has been customized.

**Apply these hard guardrails:**

- **Keep operation history read-only.** `jj undo`, `jj redo`, and `jj op
  abandon/integrate/restore/revert` modify shared operation history across all
  workspaces; reserved for the user. *Reading* it is fine: `jj --no-pager op
  log`, `op show <op>`, and `--at-op <op>` with a read-only command are
  allowed diagnostics.
- **Honor immutability refusals.** A refusal almost always means the
  request *as understood* would rewrite published history — report which
  revision and why in a sentence or two, then ask. Never reinterpret the
  request, search diffs for a resembling revision, or use `--ignore-immutable`
  / `--config`/`--config-file` to get around it. Before rebasing, splitting,
  or placing against a named target, check mutability first: `jj --no-pager
  log -r '<target>' --no-graph -T 'immutable'`, or the `why-immutable` helper
  below for the clause and anchor.
- **Stay in the current workspace directory.** Operate there instead of
  retargeting another workspace with `-R`/`--repository`.
- **Use jj exclusively for version control.** In a colocated repository, jj
  owns version-control mutations and Git synchronization.
- **Stop at a guardrail.** State the limitation without proposing an
  exception. Forbidden includes *offering* one:
  don't present it as an option to authorize, e.g. "option 1, requires your
  approval" — naming it as available is itself the violation.

## Helpers

Resolve helper paths from this loaded `SKILL.md`, not from the repository
being edited. These are diagnostics to **run**; their output is the evidence.

```bash
"<skill-dir>/scripts/why-immutable" REVSET [REVSET ...]
"<skill-dir>/scripts/interpolate"
```

`why-immutable` reports whether each selected revision is immutable, which
clause of the active `immutable_heads()` definition captures it, and the
bookmark or tag anchoring that clause. It is read-only, and it names the
repository it is describing on the first line — check that line, since the
helper reads the working directory and a report from the wrong repo looks
exactly like a surprising one. More than one clause can capture the same
revision (an untracked remote bookmark on trunk is captured by both), and the
report says so: every capturing clause has to stop matching before the
revision becomes mutable. Run it before
proposing a rebase, split, or placement against a named target, and again when
jj refuses one. When the capturing clause is a repository alias rather than a
jj builtin, the report says so and points at `knowledge`'s `rtfm revsets
--search Aliases` and `rtfm config --search immutable_heads`. Read those
before reporting what the guard protects — an alias name is not its
definition.

`interpolate` is the guarded escape hatch; read
[Interpolate a change](references/interpolate.md) before running it.

If nothing above matches, do not improvise a multi-step rewrite from this
skill. Use `knowledge` to read the version-matched jj manual, then choose
normal jj commands or pause for the missing judgment.
