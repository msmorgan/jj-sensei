---
name: harmony
description: Harmonize stale workspace state, divergent working-copy successors, and file conflicts in Jujutsu; use when revision state needs a safe oldest-first repair or jj's default diff+snapshot markers need inspection. Never perform operation-log surgery.
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

If the conflicted revision is already `@`, there is no choreography to
perform. The conflict is materialized in the files on disk, so resolving it is
editing those files — or running `conflicts accept` — and letting the next jj
command snapshot the result. No `edit`, no `new`, no `squash` is involved.

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

Convergence keeps the sole nonempty successor, or any one of byte-identical
successors. A bookmark on the chosen keeper is left intact. If abandoning a
losing candidate would affect a bookmark, convergence pauses rather than
assuming whether that bookmark should move, remain, or be deleted. It also
refuses genuinely different nonempty trees and candidates owned by another
workspace.

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
