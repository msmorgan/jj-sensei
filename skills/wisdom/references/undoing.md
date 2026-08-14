# Undo without operation-log surgery

`jj undo`, `jj redo`, and every `jj op` mutation are reserved for the user.
Nothing below needs them. Pick the tool from what is actually unwanted.

## Decision table

| What is unwanted | Tool | Notes |
|---|---|---|
| Uncommitted content in `@` | `jj --no-pager restore FILESET` | Restores those paths from the parent tree; the change and its description survive. Bare `jj restore` empties `@` entirely. |
| A whole mutable change | `jj --no-pager abandon -r REV` | Descendants rebase onto its parents. Bookmarks on it are deleted unless `--retain-bookmarks` moves them to the parents. |
| A landed or otherwise immutable change | `jj --no-pager revert -r REV -A TIP` | Adds a new commit that reverses `REV`; the original stays. |
| Content that no longer exists anywhere | `jj --no-pager evolog -r REV`, or read-only operation log | See below. |
| A squash that folded work into the wrong commit | `jj --no-pager split -r WRONG_TARGET FILESET -m '...'` | Take the work back out by ordinary rewrite; see [Tidy the working copy](tidy.md) and [Place changes deliberately](placement.md). **Not** `jj undo`. |

`jj restore` restores whole files, and `jj diffedit` — which would take only
part of one — opens a diff editor and is therefore unavailable here; split by
fileset instead.

A squash that landed in the wrong commit is the most common reason agents
reach for `jj undo`, and it is never the right tool. The squash is an ordinary
rewrite and comes back out as one: `jj --no-pager split -r WRONG_TARGET
FILESET -m '<description for the extracted work>'` separates it again, and the
op log — read-only — shows exactly what the squash did if the target is
unclear:

```bash
jj --no-pager op log
jj --no-pager op show OP_ID
```

Read [Tidy the working copy into the right commits](tidy.md) for which half of
the split keeps the change ID and where the extracted work lands.

## Reverting immutable work

`jj revert` refuses to run without a placement flag — one of `-o`, `-A`, or
`-B` is required, exactly as for `rebase` and `duplicate`:

```bash
jj --no-pager revert -r REV -A TIP
```

Placing the reversal after the current tip is the usual intent. Reverting a
change whose lines were edited again later records a conflict in the new
commit; jj reports it and completes:

```text
Reverted 1 commits as follows:
  lyykzpxu 8eb49939 (conflict) Revert "change two"
```

That is the expected outcome, not a failure. Resolve the conflict in place —
it is materialized in the working copy — and continue. Adjacent-line edits are
enough to produce one.

## Recovering content that is gone

`jj evolog -r REV` shows a change's own earlier versions, including the
per-snapshot states an agent's edits produced. It is the first stop when work
was overwritten inside one change.

When the content belonged to a change that no longer exists, read the
operation log. Reading it is permitted; mutating it is not:

```bash
jj --no-pager op log
jj --no-pager op show OP_ID
jj --no-pager --at-op OP_ID file show -r @ PATH
jj --no-pager --at-op OP_ID log -r 'all()' -T builtin_log_oneline
```

`--at-op` with a read command reconstructs what the repository looked like
then. Copy the recovered content forward as an ordinary edit. Never use `op
restore` or `op revert` to move the repository back.

The `harmony` skill's `recover-file` helper automates that walk for one path:
it finds the snapshot operations whose content differs and prints any one of
them. States that were never snapshotted are not recoverable by any route.

## Immutable-target triage

An immutability refusal is information about the request, not an obstacle to
route around.

1. **Detect.** `jj log` draws immutable commits with `◆` rather than `○`. The
   `immutable` template keyword answers directly:

   ```bash
   jj --no-pager log -r REV --no-graph -T 'change_id.short() ++ " " ++ immutable ++ "\n"'
   ```

   `scripts/why-immutable REV` names which clause of the active
   `immutable_heads()` definition captures it and what anchors that clause.

2. **Stop.** Do not retarget. Do not search diffs for a similar change that
   happens to be mutable. The refusal means the request as understood would
   rewrite published history.

3. **Report** in one sentence: which revision, and which clause makes it
   immutable.

4. **Present the real options** and let the user choose:
   - Move or advance the anchoring bookmark or tag, and say plainly that
     rewriting what a remote already has requires a force push and disrupts
     anyone who fetched it.
   - `jj duplicate -r REV -A TIP` to copy the content somewhere mutable and
     work on the copy.
   - Confirm which revision was actually intended, if the named target may
     have been a misunderstanding.

5. **Never bypass.** `--ignore-immutable`, `--config`, and `--config-file`
   are not options here, and they are not to be offered as options either.
