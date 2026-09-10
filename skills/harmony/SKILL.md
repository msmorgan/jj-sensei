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
conflicted, or lost revision and what produced the state. Diagnosis is complete
when both the affected revision and the mechanism are known; otherwise gather
read-only evidence or load `knowledge` before choosing a repair.

## 2. Route

| State or request | Reference |
|---|---|
| One conflict with known intended content, or any conflict-marker work | [Resolve file conflicts](references/conflicts.md) |
| `Error: The working copy is stale` | [Realign a stale workspace](references/stale.md) |
| Divergent successors of this workspace's working copy | [Converge working-copy successors](references/divergence.md) |
| Divergence elsewhere in the graph | `knowledge`: `rtfd docs/guides/divergence` |
| Recover one path from operation snapshots | [Recover a file](references/recovery.md) |
| Orphaned workspace registration | `boundaries`; the user decides whether to forget it |

Load every matched branch and no unrelated branch. If command or marker
semantics remain uncertain, load `knowledge` and query the installed manual.

## 3. Apply the narrow repair

For one diagnosed conflict whose intended content is known, follow the
conflict reference and stop after its verification gate. For several
conflicts, a stale workspace, or working-copy divergence, run the resumable
repair helper from the affected workspace:

```bash
"<skill-dir>/scripts/repair"
```

Run it bare so its exit status remains visible:

- `0` — clean; rerun the operation that exposed the problem.
- `1` — edit every marker the helper listed, then rerun `repair`.
- `70` — internal error; preserve the journal and present the diagnosis.
- `75` — another repair holds the workspace lock; retry after it finishes.
- `80` — human judgment is required; present the reported state and ask.

These statuses belong only to the helper. It uses a short per-workspace lock
and a resumable journal under that workspace's `.jj/`, releasing the lock when
an edit is required. It preserves transaction state after an internal error
and leaves bookmarks untouched.

Use narrower helpers only after diagnosis establishes their exact scope:

```bash
"<skill-dir>/scripts/converge"  # working-copy divergence only
"<skill-dir>/scripts/resolve"   # conflict walk only
```

## 4. Verify

Repair is complete only when the original operation succeeds, `jj --no-pager
log -r 'conflicts()' -T builtin_log_oneline` is empty, and the relevant project
tests pass after content changed. Report any remaining stale, divergent,
conflicted, or judgment-required state rather than treating a partial repair
as success.
