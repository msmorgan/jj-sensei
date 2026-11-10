---
name: harmony
description: Load for jj-reported stale workspaces, file conflicts, divergent working-copy successors, or file recovery from operation snapshots. Diagnoses first, then routes the narrow repair.
metadata:
  kind: reference
---

# Repair a jj workspace

Keep the operation log read-only and respect Wisdom's immutability and
workspace guardrails throughout repair. Every `scripts/` helper here is a
diagnostic to run: repository-specific evidence comes from its output, not its
source. Resolve helper paths from this loaded `SKILL.md`.

## 1. Diagnose

Before any fix, state one plain sentence naming the stale, divergent,
conflicted, or lost revision, the workspace that owns it, and what produced the
state. Diagnosis is complete when the affected revision, its owner, and the
mechanism are known; otherwise gather read-only evidence or load `knowledge`
before choosing a repair.

Repair only from the workspace that owns the affected change. When another
workspace's problem blocks you, report it to that workspace's owner and wait;
don't repair it yourself.

## 2. Route

| State or request | Procedure |
|---|---|
| `(conflict)` on a revision, `×` in the log graph, `<<<<<<<` in a file | [Resolve conflicts](#3-resolve-conflicts), below |
| `Error: The working copy is stale` | [Realign a stale workspace](references/stale.md), then `repair`, never a bare `jj workspace update-stale` |
| Divergent successors of this workspace's working copy | [Converge working-copy successors](references/divergence.md) |
| Divergence elsewhere in the graph | `knowledge`: `rtfd docs/guides/divergence` |
| `⚠ NEW DIVERGENCE` or a divergent-count suffix in the status line | Diagnose whose copies they are; converge only this workspace's own working copy or ancestry, and report other workspaces' copies to their owner without abandoning them |
| Recover one path from operation snapshots | [Recover a file](references/recovery.md) |
| Orphaned workspace registration | `boundaries`; the user decides whether to forget it |

Load every matched branch and no unrelated branch. If command or marker
semantics remain uncertain, load `knowledge` and query the installed manual.

## 3. Resolve conflicts

A conflict lives in the oldest conflicted revision. Its descendants show the
same markers, but editing them at `@` resolves only `@`. `repair` walks the
conflicted revisions oldest-first, so it is the entry point for one conflict or
many, at `@` or in an ancestor:

1. Find where it lives: the oldest change in `jj --no-pager log -r
   'conflicts()' -T builtin_log_oneline`.
2. Run `"<skill-dir>/scripts/repair"` from the affected workspace. It moves
   onto the oldest mutable conflicted change, applies proven-safe hunks, and
   exits `1` listing each remaining marker as `file:line` with its hunk.
3. Settle every listed hunk, by one of:
   - Replace each whole marker block, markers included, with the intended
     content using the file-editing tool. [Read jj conflict markers](references/markers.md)
     says which section is which side.
   - Settle one hunk at a time, taking a side or writing its content, with
     `conflicts accept --hunk` or `conflicts replace`; see
     [Resolve one hunk](references/conflicts.md#resolve-one-hunk).
   - Take one side for the whole file: `"<skill-dir>/scripts/conflicts" accept
     FILE SIDE`, naming `SIDE` by role (`destination`, `rebased`) or change ID
     rather than `snapshot`/`diff`, which can swap between hunks.
   - A generated file: take one side with `accept`, then rerun its generator
     instead of merging markers. [Generated files](references/conflicts.md#generated-files)
     has the procedure.
4. Rerun `repair` after each round; it resumes from its journal. Exit `0` means
   every resolution is folded into its conflicted change and `@` is back on the
   original tip. Continue to [Verify](#5-verify).

Load [conflict edge cases](references/conflicts.md) for a deletion conflict,
two pure additions to stack, generated files, the automatic resolver run
directly, or a conflicted change outside `::@`.

## 4. Run the repair helper

For a stale workspace or working-copy divergence, run `repair` after its
reference; it realigns and converges before its conflict walk. Run it bare so
its exit status remains visible:

```bash
"<skill-dir>/scripts/repair"
```

- `0` — clean; rerun the operation that exposed the problem.
- `1` — edit every marker the helper listed, then rerun `repair`.
- `70` — internal error; preserve the journal and present the diagnosis.
- `75` — another repair holds the workspace lock; retry after it finishes.
- `80` — human judgment is required; present the reported state and ask.

These statuses belong only to the helper. It uses a short per-workspace lock
and a resumable journal under that workspace's `.jj/`, releasing the lock when
an edit is required. It preserves transaction state after an internal error
and leaves bookmarks untouched, except that converging moves a bookmark on a
divergent successor to the converged change.

Use narrower helpers only after diagnosis establishes their exact scope:

```bash
"<skill-dir>/scripts/converge"  # working-copy divergence only
"<skill-dir>/scripts/resolve"   # conflict walk only
```

## 5. Verify

Repair is complete only when the original operation succeeds, `jj --no-pager
log -r 'conflicts()' -T builtin_log_oneline` is empty, and, after content
changed, each resolved change's `jj --no-pager diff --git -r CHANGE` expresses
the intended content and the relevant project tests pass. Report any
remaining stale, divergent, conflicted, or judgment-required state rather than
treating a partial repair as success.
