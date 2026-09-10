# Reconstruct work with evolog

Use the evolution log when `@` has accumulated work that should have been a
series of commits. jj-sensei's live-status hook snapshots after file-writing
and shell tools, so the change retains a chronological, patch-level trace of
what the agent did even without intermediate commits.

If subagents are available, delegate the trace analysis to a fresh subagent
of the appropriate tier immediately, before loading the full evolog into the
coordinating agent's context — this task is semi-mechanical and well-bounded.
Keep it read-only: it should run the evolog queries itself and return only a
compact reconstruction plan containing:

- the original current change ID and commit ID;
- proposed commits in oldest-to-newest order;
- the checkpoint commit ID, rationale, and likely reconstruction method for
  each boundary; and
- ambiguities that still require the coordinating agent's judgment.

Do not ask it to paste the complete evolog or mutate history; inspect only the
proposed checkpoints, validate the plan, and perform the graph mutations
yourself. Load the full trace directly only when no subagent is available or
the compact plan leaves a material ambiguity.

To analyze the trace directly, inspect it from oldest version to newest:

```bash
jj --no-pager evolog -r @ --reversed -p --git
```

`-p` shows each version's patch against the previous one. If parents changed,
jj temporarily rebases the older version onto the newer version's parents so
unrelated rebase changes don't contaminate the patch. Start with `--stat`
instead of `--git` when the trace is too large, then rerun with `--git` once
its scope is understood.

The hook snapshots execution history, not intent — don't turn every evolution
entry into a commit. Ignore empty metadata-only versions, reversals, failed
experiments, and mechanical follow-up edits; group the ordered patches into
the smallest coherent changes that build and make sense independently.

Each entry names a commit ID for that historical version; inspect it in
context when a patch alone is insufficient:

```bash
jj --no-pager show --git COMMIT_ID
```

Before rewriting, record the current change ID as the insertion target and
its commit ID so the final tree remains independently checkable:

```bash
jj --no-pager log -r @ --no-graph -T 'change_id ++ " " ++ commit_id ++ "\n"'
```

Reconstruct the series from oldest boundary to newest. Use ordinary `jj split`
with an explicit fileset for a files-only boundary. For a single-parent `@`
whose selected checkpoints have compatible parent content, insert each earlier
checkpoint directly before the original change with the
[interpolation helper](interpolate.md#insert-an-existing-snapshot):

```bash
"<skill-dir>/scripts/interpolate" insert --from SNAPSHOT -B ORIGINAL_CHANGE_ID -m 'earlier change'
jj --no-pager diff --git -r 'ORIGINAL_CHANGE_ID-'
```

Repeat with later checkpoints, keeping `ORIGINAL_CHANGE_ID` fixed. Its parent
is the newly inserted change each time. Leave the final state in the original
change; its diff becomes the work remaining after the last checkpoint.
The helper uses `--no-edit` and `--restore-descendants` to keep the working
copy on the original change and preserve descendant trees while filling the
lower change. It checks parent compatibility and journals the insertion for
resumption or abort. No final rebase is needed.

The whole-tree restore is deliberate here: each lower change should have
exactly its selected snapshot's tree. If a snapshot contains unrelated work
or was based on different parent content, use the normalized evolog patches
as evidence and construct only the intended checkpoint content with
[interpolation's `begin` / `finish` mode](interpolate.md#construct-a-state-in-the-working-copy),
for example by running generators.

`duplicate SNAPSHOT -d PARENT` does not materialize this sequence of trees:
it reapplies each snapshot's cumulative diff against its original parents.
Successive edits to the same lines can therefore conflict even though the
snapshots came from one change.

After reconstruction, compare the final tree with the original recorded commit
ID; the diff must be empty:

```bash
jj --no-pager diff --git --from ORIGINAL_COMMIT_ID --to ORIGINAL_CHANGE_ID
```

Review every resulting change and run the relevant tests: evolog supplies the
evidence, but semantic commit boundaries still require judgment. This workflow
reads historical versions and performs ordinary history rewrites — it never
requires operation-log surgery.

## Restore a change to one of its own snapshots

Use this when a described change has been amended with content it should not
carry — a refactor that got snapshotted into it, an experiment that stayed —
and the goal is "put `CHANGE` back the way it was at an earlier point". The
evolog holds every earlier version of the change; restore the affected paths
from one of them **into the change itself**.

```bash
jj --no-pager evolog -r CHANGE --no-graph \
  -T 'commit.commit_id().short() ++ " " ++ operation.time().start().format("%H:%M") ++ "\n"'
jj --no-pager file list -r SNAPSHOT            # confirm the snapshot has what you want
jj --no-pager file show -r SNAPSHOT PATH        # or read it
jj --no-pager restore --from SNAPSHOT --into CHANGE PATH...
jj --no-pager diff -r CHANGE --stat             # the change now carries the old content
```

`SNAPSHOT` is a commit ID from the evolog listing (in an evolog template the
commit is reached as `commit.commit_id()`; bare `commit_id` is not a keyword
there). `--into CHANGE` is the correct direction for this case: it rewrites
that change's tree for the named paths only, its description and change ID
survive, and descendants rebase. The [undo table](undoing.md) row for the
same command points here.

Two things this recipe never does:

- **Restore without a `FILESET`.** `restore --from SNAPSHOT` with no paths
  copies the snapshot's entire tree into the destination, so every path that
  differs — including work from other lines that happened to be in the tree
  at the time — changes with it.
- **Restore the old tree somewhere else and rebase `CHANGE` onto it.**
  `jj new BASE && jj restore --from SNAPSHOT && jj rebase -r CHANGE -d @`
  looks like a rollback but is not: rebasing `CHANGE` re-applies `CHANGE`'s
  own diff on top of the copy, so the unwanted content comes straight back,
  usually with conflicts and the whole-tree leak from the first point on top.
  One scoped `restore --from SNAPSHOT --into CHANGE PATH` is the entire
  operation.

The parent caveat above still applies: a snapshot taken on a different parent
can carry that parent's content in the restored paths, so check `file show`
output before restoring rather than trusting the timestamp alone.
