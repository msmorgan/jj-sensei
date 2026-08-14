---
name: harmony
description: Harmonize stale workspace state, divergent working-copy successors, and file conflicts in Jujutsu. Use on jj's own output - `Error: The working copy is stale`, `(conflict)` on a revision, `×` in the log graph, `<<<<<<<` markers in a file, or `(divergent)` working copies - when revision state needs a safe oldest-first repair or jj's diff+snapshot markers need inspection. Never perform operation-log surgery.
---

# Harmonize a jj Workspace

This skill harmonizes workspace and revision state: it updates stale workspaces,
converges safe divergent successors, and walks mutable conflicts oldest-first.
It never performs operation-log surgery or rewrites history through undo, redo,
operation restore, or ignored immutability checks.

Resolve every helper path from this loaded `SKILL.md`, not from the repository
being repaired. If command or marker semantics are uncertain, load `knowledge`
and query `resolve --full` or `config --search "Conflict marker style"` before
choosing conflict content.

Before running any fix, state the diagnosed root cause in one plain sentence —
which revision is stale, divergent, or conflicted, and what produced that
state. A repair chosen before the diagnosis is named is a guess.

## Choose the narrow fix or the repair walk

One conflict, already fully diagnosed, whose intended content is known: edit
the marker block or run `conflicts accept`, and stop there. Several conflicts,
a stale workspace, or divergence in play: run `repair`, which orders the work
and refuses the parts that need judgment.

An orphaned workspace registration is neither: the status line flags it, but
`repair` does not clear it. Load `boundaries` for the diagnosis, and leave the
`jj workspace forget` decision to the user.

If the conflicted revision is already `@`, there is no choreography to
perform. The conflict is materialized in the files on disk, so resolving it is
editing those files — or running `conflicts accept` — and letting the next jj
command snapshot the result. No `edit`, no `new`, no `squash` is involved.

## Fixing a conflict that lives in an ancestor

A conflict recorded in an ancestor is materialized in `@` too, which makes an
inviting trap: editing the markers where they appear resolves them **in `@`
only**, and the ancestor stays conflicted. `jj --no-pager log -r 'conflicts()'`
after the edit still lists it, and every future rebase across it carries the
conflict along.

Fix it where it lives. Verified sequence, for a single conflict whose intended
content is known:

```bash
jj --no-pager log -r 'conflicts()' -T builtin_log_oneline   # find the oldest
jj --no-pager edit CONFLICTED_CHANGE_ID                     # @ becomes it
# edit the marker block in the file to the intended content
jj --no-pager st                                            # snapshots; rebases descendants
jj --no-pager log -r 'conflicts()' -T builtin_log_oneline   # must be empty
jj --no-pager edit ORIGINAL_TIP_CHANGE_ID                   # go back
```

jj reports `Rebased 1 descendant commits onto updated working copy` as the fix
propagates. Return by **change ID**: the tip is real described work, so it
survives the excursion and `jj edit` finds it again. Capture that ID before
moving, and do not use `@` to mean it — `@` is the conflicted revision for the
duration.

Prefer full `repair` instead whenever more than one conflict is recorded, the
workspace is stale, or divergence is in play: it walks conflicts oldest-first,
which is the order that avoids re-resolving the same content, and it stops on
the parts that need judgment.

## Unstaling a workspace is not lossless

A stale workspace refuses every jj command — `st`, `log`, `op log`,
`bookmark list` alike — with `Error: The working copy is stale`. Inspect it
without changing anything by adding `--ignore-working-copy` to a read command.

`jj workspace update-stale`, which `repair` runs first, realigns the workspace.
Say plainly what that costs before running it. When the staleness came from
another workspace abandoning this one's working-copy commit, update-stale moves
this workspace to a fresh **empty** commit and rewrites the files on disk to
match it: edits to tracked files are reverted, and files that existed only in
the abandoned change are **deleted**. jj reports the damage in passing —
`Added 0 files, modified 1 files, removed 1 files` — and it is easy to promise
a realignment that quietly discards work.

So state the loss first, and name the recovery route in the same breath. The
abandoned content is still readable, and reading it needs no operation-log
mutation:

```bash
"<skill-dir>/scripts/recover-file" list PATH
"<skill-dir>/scripts/recover-file" show OPERATION PATH
jj --no-pager op log
jj --no-pager --at-op OPERATION file show -r ABANDONED_CHANGE PATH
```

Recover what matters, then unstale — or unstale and recover afterwards, since
the snapshots survive either way. Never reach for `jj op restore` or `jj undo`
to bring the work back.

## Fast path

Run the one-stop repair helper from the affected workspace:

```bash
"<skill-dir>/scripts/repair"
```

`repair` performs `workspace update-stale`, converges equivalent divergent
working-copy successors, then walks mutable conflicts oldest-first. It uses a
short per-workspace lock and a resumable journal under that workspace's `.jj/`.
The lock is released whenever the helper asks for an edit.

Its exit status is load-bearing. Run it bare; never pipe it into another
command.

- `0` — clean; rerun the operation that originally exposed the problem.
- `1` — stopped on the oldest remaining conflict. Edit every listed marker,
  then rerun the same `repair` command.
- `70` — an internal error occurred. Transaction state is preserved; present
  the diagnosis and do not improvise a recovery command.
- `75` — another repair holds the workspace lock. Rerun after it finishes.
- `80` — human judgment is required. Present the reported state and ask before
  continuing.

These actions apply only to this helper's exit status, not to an ordinary jj
invocation rejected for invalid syntax or options. Every successful state
transition is journaled. After an internal error, the helper runs no later
transaction step, performs no operation-log rollback, preserves its journal,
and tells the caller what to inspect. Never use `undo`, `redo`, `op restore`,
`--ignore-immutable`, `--config`, or `--config-file` as recovery.

The resolver temporarily pins an empty undescribed tip with a description while
it descends, then restores the original description. It never creates, moves,
or deletes bookmarks.

## Narrow commands

Use these only when the narrower diagnosis is already certain:

```bash
"<skill-dir>/scripts/converge"  # divergence only
"<skill-dir>/scripts/resolve"   # conflict walk only
```

Convergence is scoped to divergent **working-copy successors** — the case
where this workspace's own `@` was rewritten twice. A change that is divergent
anywhere else in the graph, which jj prints as `(divergent)` with `/0` and `/1`
suffixes on one change ID, is outside this helper. For those, load `knowledge`
and read `rtfd docs/guides/divergence`; it documents four remedies — abandon
the unwanted commit (addressing it by *commit* ID, since the change ID is
ambiguous), `jj metaedit --update-change-id <commit-id>` to keep both versions
under separate identities, squashing the two together, or leaving the
divergence alone. Inspect both sides before choosing, and let the user pick
when both hold real work.

Convergence keeps the sole nonempty successor, or any one of byte-identical
successors. A bookmark on the chosen keeper is left intact. If abandoning a
losing candidate would affect a bookmark, convergence pauses rather than
assuming whether that bookmark should move, remain, or be deleted. It also
refuses genuinely different nonempty trees and candidates owned by another
workspace.

## Recovering a file from an operation snapshot

When content was lost rather than conflicted, read it back out of the
operation log instead of restoring the repository to an earlier operation:

```bash
"<skill-dir>/scripts/recover-file" list PATH
"<skill-dir>/scripts/recover-file" list -n 200 PATH
"<skill-dir>/scripts/recover-file" show OPERATION PATH
```

`list` walks `jj op log` for operations that snapshotted the working copy,
reads `PATH` at each, and reports only the operations where its content
changed. `show` prints one of those states; redirect or copy it forward as an
ordinary edit.

Both subcommands are strictly read-only — they load the repository at an
operation and never restore it. Only snapshotted states exist: jj snapshots on
ordinary commands and after agent tool calls, so edits made and overwritten
between two snapshots were never recorded and cannot be recovered here. For
earlier versions of a change that still exists, `jj --no-pager evolog` is the
better tool.

## Inspecting and resolving marker content

The `conflicts` helper supports jj's default `diff+snapshot` marker style:

```bash
"<skill-dir>/scripts/conflicts" list
"<skill-dir>/scripts/conflicts" show [--json] [FILE ...]
```

Resolve semantically complex conflicts by editing the complete marker block.
Read [Read jj conflict markers](references/markers.md) before hand-editing one:
it gives the section grammar, lengthened markers, the `(no terminating
newline)` annotation, conflicts with more than two sides, and the alternative
marker styles.

Use a mechanical strategy only after its result is clearly understood:

```bash
"<skill-dir>/scripts/conflicts" accept FILE snapshot
"<skill-dir>/scripts/conflicts" accept FILE diff
"<skill-dir>/scripts/conflicts" accept FILE base
"<skill-dir>/scripts/conflicts" accept FILE stack
"<skill-dir>/scripts/conflicts" accept FILE stack-snap-first
```

`stack` variants are allowed only for two pure-add sides reported as
`stackable: true`. The repair helper automatically tries the conservative
sorted-list resolver; it can also be previewed or run directly:

```bash
"<skill-dir>/scripts/conflicts" auto --dry-run [FILE ...]
"<skill-dir>/scripts/conflicts" auto [FILE ...]
```

`auto` leaves everything it cannot prove safe untouched. Read its summary;
remaining conflicts are not an execution failure.

After resolving, inspect the Git-shaped diff and run project tests:

```bash
jj --no-pager diff --git
jj --no-pager st
"<skill-dir>/scripts/conflicts" list
```

The final helper listing must be empty. Do not run bare `jj resolve` in a
non-interactive session, and never choose a side merely from labels such as
`snapshot`, `diff`, `ours`, or `theirs`.
