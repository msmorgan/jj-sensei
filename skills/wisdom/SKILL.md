---
name: wisdom
description: The jj-sensei hub. Load before ANY version control command in a Jujutsu repo, including trivial ones. Carries jj's model, the always-binding safety rules, and routing to every reference and to the knowledge, harmony, and boundaries skills. Use for any Git-reflex translation, history-shaping request, or unexplained jj output token.
---

# Jujutsu: the hub

Everything version-control in this repository starts here. Read the model and
the rules below — they bind every command — then use the routing table to
reach the one reference that answers the request.

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
existing description instead of prompting.

## Rules that bind every command

**You cannot drive an editor or terminal UI, so any command that opens one is
unavailable:** interactive `split`/`squash` (`-i`, or `split` with no
fileset), `diffedit`, `resolve` without `--tool`, `arrange`, `config edit`,
and bare `describe`/`commit` without `-m`. Use non-interactive forms instead:
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

**`jj --no-pager bookmark list --all` and `jj --no-pager log` are the ground
truth for refs.** There's no separate git layer underneath to double-check. If
a ref is not in jj's output, it does not exist.

**Mutability is decided by `immutable_heads()`.** jj treats
`::(immutable_heads() | root())` as immutable and refuses to rewrite it; by
default that is `trunk() | tags() | untracked_remote_bookmarks()`. A repo may
extend it, so read the active definition rather than assume: `jj --no-pager
config get "revset-aliases.'immutable_heads()'"`.

**The following operations and escape hatches are always strictly forbidden:**

- **Never perform operation-log surgery:** `jj undo`, `jj redo`, and `jj op
  abandon/integrate/restore/revert` modify shared operation history across all
  workspaces; reserved for the user. *Reading* it is fine: `jj --no-pager op
  log`, `op show <op>`, and `--at-op <op>` with a read-only command are
  allowed diagnostics.
- **Never bypass immutability guards:** a refusal almost always means the
  request *as understood* would rewrite published history — report which
  revision and why in a sentence or two, then ask. Never reinterpret the
  request, search diffs for a resembling revision, or use `--ignore-immutable`
  / `--config`/`--config-file` to get around it. Before rebasing, splitting,
  or placing against a named target, check mutability first: `jj --no-pager
  log -r '<target>' --no-graph -T 'immutable'`, or the `why-immutable` helper
  below for the clause and anchor.
- **Never retarget other workspaces with `-R`/`--repository`:** work from the
  directory of the workspace you are operating in.
- **Never run mutating `git` commands:** in a colocated repository, do version
  control through `jj`, not `git`.
- **Never propose an exception to these rules:** when a rule blocks the
  request, state the limitation and stop. Forbidden includes *offering* it:
  don't present it as an option to authorize, e.g. "option 1, requires your
  approval" — naming it as available is itself the violation.

## Route on what jj printed

Trust the output token over the user's phrasing.

| jj printed | Go to |
|---|---|
| `??` after a bookmark name, or `(conflicted)` in `jj bookmark list` | [Publish and land work](references/shipping.md) |
| `(conflict)` on a revision, `×` in the log graph, `<<<<<<<` in a file | `harmony` skill |
| `Error: The working copy is stale` | `harmony` skill |
| `(divergent)`, or a change ID with a `/0`/`/1` suffix | `harmony` if it is a diverged working copy, else `knowledge` for `rtfd docs/guides/divergence` |
| An immutability refusal | [Undo without operation-log surgery](references/undoing.md), triage section |
| `[updated] untracked` after a fetch | [Publish and land work](references/shipping.md) |
| An unfamiliar revset alias from `config get` | `knowledge` skill |

## Route on what was asked

Common Git reflexes answered inline; anything with a trap is routed.

| The request | Answer or destination |
|---|---|
| status / diff / log | `jj --no-pager st`; `jj --no-pager diff --git`; `jj --no-pager log -r ::@ -n 5 -T builtin_log_oneline` |
| stage a file (`git add`) | Nothing to do — every command snapshots all unignored edits |
| commit everything | `jj --no-pager commit -m "..."` — describes `@`, then creates a fresh empty child |
| commit only some paths | `jj --no-pager commit FILESET -m "..."` — see [Tidy the working copy](references/tidy.md) |
| stash / unstash | Nothing to stash: `jj --no-pager new <base> -m "..."` for the interruption, `jj --no-pager edit <wip>` to return; the WIP change stays put as a sibling |
| switch branches | `jj --no-pager edit <change>` to move onto one; `jj --no-pager new <base> -m "..."` to start work. Neither creates a bookmark |
| who wrote this line (`git blame`) | `jj --no-pager file annotate PATH` — names the change that **last touched** each line, not necessarily the one that introduced a symbol; corroborate with that change's diff |
| stop tracking an ignored file | `jj --no-pager file untrack PATH` — the path must already match an ignore pattern |
| discard uncommitted work | `jj --no-pager restore FILESET` — see [Undo](references/undoing.md) |
| uncommit / amend / reword / move a fix into an earlier commit | [Tidy the working copy](references/tidy.md) and [Undo](references/undoing.md) |
| undo, revert, drop a change, recover lost work | [Undo without operation-log surgery](references/undoing.md) |
| split, reorder, rebase, cherry-pick, merge, insert mid-stack | [Place changes deliberately](references/placement.md) |
| push, fetch, bookmarks, tags, landing work | [Publish and land work](references/shipping.md) |
| check state, select revisions, build a compact view | [Use templates without guessing](references/templates.md) |
| reconstruct an oversized `@` into a series | [Reconstruct work with evolog](references/using-evolog.md) |
| build an intermediate state selection cannot express | [Interpolate a change](references/interpolate.md) |
| conflicts, stale workspace, divergence, recover a file from a snapshot | `harmony` skill |
| add or audit a workspace, multi-workspace immutability | `boundaries` skill |
| anything not covered here, or any uncertain flag or semantics | `knowledge` skill — read the installed version-matched manual before acting; never infer from Git |

## Helpers

Resolve helper paths from this loaded `SKILL.md`, not from the repository
being edited. These are diagnostics to **run**; their output is the evidence.

```bash
"<skill-dir>/scripts/why-immutable" REVSET [REVSET ...]
"<skill-dir>/scripts/interpolate"
```

`why-immutable` reports whether each selected revision is immutable, which
clause of the active `immutable_heads()` definition captures it, and the
bookmark or tag anchoring that clause. It is read-only. Run it before
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
