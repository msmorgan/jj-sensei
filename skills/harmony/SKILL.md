---
name: harmony
description: Harmonize stale workspace state, divergent working-copy successors, and file conflicts in Jujutsu. Use on jj's own output - `Error: The working copy is stale`, `(conflict)` on a revision, `×` in the log graph, `<<<<<<<` markers in a file, or `(divergent)` working copies - when revision state needs a safe oldest-first repair or jj's diff+snapshot markers need inspection. Never perform operation-log surgery.
---

# Harmonize a jj Workspace

This skill updates stale workspaces, converges safe divergent successors, and
walks mutable conflicts oldest-first — never through operation-log surgery: no
undo, redo, operation restore, or ignored immutability checks.

Every `scripts/` helper here is a diagnostic to **run**. Its output is the
evidence about this repository; its source says nothing about this repository,
so reading the script instead of executing it answers nothing.

Resolve every helper path from this loaded `SKILL.md`, not from the repository
being repaired. If command or marker semantics are uncertain, load `knowledge`
and query `resolve --full` or `config --search "Conflict marker style"` before
choosing conflict content.

Before running any fix, state the diagnosed root cause in one plain sentence —
which revision is stale, divergent, or conflicted, and what produced that
state. A repair chosen before naming the diagnosis is a guess.

## Choose the narrow fix or the repair walk

One conflict, already fully diagnosed, whose intended content is known: edit
the marker block or run `conflicts accept`, then stop. Several conflicts, a
stale workspace, or divergence in play: run `repair`, whose oldest-first order
avoids re-resolving content already fixed and refuses the parts that need
judgment.

An orphaned workspace registration is neither: the status line flags it, but
`repair` does not clear it. Load `boundaries` for the diagnosis, and leave the
`jj workspace forget` decision to the user.

If the conflicted revision is already `@`, no choreography is needed — it's
materialized in the files on disk, so resolve it by editing those files or
running `conflicts accept`, then let the next jj command snapshot the result.
No `edit`, `new`, or `squash` involved.

## Fixing a conflict that lives in an ancestor

A conflict recorded in an ancestor is materialized in `@` too — a trap:
editing the markers there resolves them **in `@` only**. The ancestor stays
conflicted, `jj --no-pager log -r 'conflicts()'` still lists it, and every
future rebase across it carries the conflict along.

Fix it where it lives instead — the verified sequence:

```bash
jj --no-pager log -r 'conflicts()' -T builtin_log_oneline   # find the oldest
jj --no-pager edit CONFLICTED_CHANGE_ID                     # @ becomes it
# edit the marker block in the file to the intended content
jj --no-pager st                                            # snapshots; rebases descendants
jj --no-pager log -r 'conflicts()' -T builtin_log_oneline   # must be empty
jj --no-pager edit ORIGINAL_TIP_CHANGE_ID                   # go back
```

jj reports `Rebased 1 descendant commits onto updated working copy` as the fix
propagates. Return by **change ID**, captured before moving: the tip is real
described work, so `jj edit` finds it again, and `@` means the conflicted
revision for the duration — never the tip.

## Unstaling a workspace is not lossless

A stale workspace refuses every jj command — `st`, `log`, `op log`,
`bookmark list` alike — with `Error: The working copy is stale`; inspect it
without changing anything via `--ignore-working-copy` on a read command.

`jj workspace update-stale`, which `repair` runs first, realigns the
workspace — state that cost before running it. If another workspace abandoned
this one's working-copy commit, update-stale moves this workspace to a fresh
**empty** commit and rewrites disk to match: tracked edits are reverted and
files that existed only in the abandoned change are **deleted**. jj reports
the damage in passing — `Added 0 files, modified 1 files, removed 1 files` —
easy to mistake for a harmless realignment.

Name the recovery route in the same breath: the abandoned content is still
readable, via `recover-file` (below) or directly, and reading it needs no
operation-log mutation:

```bash
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

`repair` runs the three steps above, using a short per-workspace lock and a
resumable journal under that workspace's `.jj/`, releasing the lock whenever
it asks for an edit.

Its exit status is load-bearing — run it bare, never piped into another
command:

- `0` — clean; rerun the operation that originally exposed the problem.
- `1` — stopped on the oldest remaining conflict. Edit every listed marker,
  then rerun the same `repair` command.
- `70` — internal error. Transaction state is preserved; present the
  diagnosis and do not improvise a recovery command.
- `75` — another repair holds the workspace lock. Rerun after it finishes.
- `80` — human judgment is required. Present the reported state and ask before
  continuing.

These statuses belong to this helper alone, not to an ordinary jj invocation
rejected for invalid syntax or options. Every successful state transition is
journaled; after an internal error the helper takes no further transaction
step, performs no operation-log rollback, preserves its journal, and reports
what to inspect. Never use `undo`, `redo`, `op restore`, `--ignore-immutable`,
`--config`, or `--config-file` as recovery.

The resolver temporarily describes an empty undescribed tip while it descends,
then restores the original description, and never creates, moves, or deletes
bookmarks.

## Narrow commands

Use these only once the narrower diagnosis is certain:

```bash
"<skill-dir>/scripts/converge"  # divergence only
"<skill-dir>/scripts/resolve"   # conflict walk only
```

Convergence covers only divergent **working-copy successors** — this
workspace's own `@` rewritten twice. A change divergent elsewhere in the graph
(jj prints `(divergent)` with `/0`/`/1` suffixes on one change ID) is outside
this helper; load `knowledge` and read `rtfd docs/guides/divergence` for its
four remedies — abandon the unwanted commit (by *commit* ID; the change ID is
ambiguous), `jj metaedit --update-change-id <commit-id>` to keep both under
separate identities, squash them together, or leave it alone. Inspect both
sides and let the user pick when both hold real work.

Convergence keeps the sole nonempty successor, or any one of byte-identical
successors, leaving a bookmark on the chosen keeper intact. If abandoning a
losing candidate would affect a bookmark, convergence pauses rather than
assume whether that bookmark should move, remain, or be deleted — and it
refuses genuinely different nonempty trees or candidates owned by another
workspace.

## Recovering a file from an operation snapshot

When content is lost rather than conflicted, read it out of the operation log
instead of restoring the repository to an earlier operation:

```bash
"<skill-dir>/scripts/recover-file" list PATH
"<skill-dir>/scripts/recover-file" list -n 200 PATH
"<skill-dir>/scripts/recover-file" show OPERATION PATH
```

`list` walks `jj op log`'s snapshot operations, reads `PATH` at each, and
reports only the ones where its content changed. `show` prints one of those
states; redirect or copy it forward as an ordinary edit.

Both subcommands are read-only: they load the repository at an operation
without restoring it. Only snapshotted states exist — jj snapshots on
ordinary commands and after agent tool calls — so edits made and overwritten
between two snapshots were never recorded and can't be recovered here. For
earlier versions of a change that still exists, `jj --no-pager evolog` is the
better tool.

## Inspecting and resolving marker content

The `conflicts` helper supports jj's default `diff+snapshot` marker style:

```bash
"<skill-dir>/scripts/conflicts" list
"<skill-dir>/scripts/conflicts" show [--json] [FILE ...]
```

Resolve semantically complex conflicts by editing the complete marker block.
Read [Read jj conflict markers](references/markers.md) before hand-editing
one: it covers the section grammar, lengthened markers, missing-newline
annotations, N-way conflicts, and alternative marker styles.

Use a mechanical strategy only after its result is understood:

```bash
"<skill-dir>/scripts/conflicts" accept FILE snapshot
"<skill-dir>/scripts/conflicts" accept FILE diff
"<skill-dir>/scripts/conflicts" accept FILE base
"<skill-dir>/scripts/conflicts" accept FILE stack
"<skill-dir>/scripts/conflicts" accept FILE stack-snap-first
```

A conflict reported as `including 1 deletion` needs care: resolving it as a
deletion means `rm`-ing the path — emptying the marker block and `conflicts
accept PATH diff` both leave a tracked zero-byte file instead. See
[Read jj conflict markers](references/markers.md).

`stack` variants are allowed only for two pure-add sides reported
`stackable: true`. The repair helper tries the conservative sorted-list
resolver automatically; preview or run it directly:

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
non-interactive session, and never choose a side merely from labels like
`snapshot`, `diff`, `ours`, or `theirs`.
