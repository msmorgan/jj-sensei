# Reconstruct work with evolog

Use the evolution log when `@` has accumulated work that should have been a
series of commits. jj-sensei's live-status hook snapshots after file-writing
and shell tools, so under normal hook operation the change retains a
chronological, patch-level trace of what the agent did even when it never
created intermediate commits.

If subagents are available, delegate the trace analysis immediately, before
loading the full evolog into the coordinating agent's context. Use a fresh
subagent of the appropriate tier for this semi-mechanical, well-bounded task.
Tell it to remain read-only, run the evolog queries itself, and return only a
compact reconstruction plan containing:

- the original current commit ID;
- proposed commits in oldest-to-newest order;
- the checkpoint commit ID, rationale, and likely reconstruction method for
  each boundary; and
- ambiguities that still require the coordinating agent's judgment.

Do not ask it to paste the complete evolog or mutate history. The coordinating
agent should inspect only the proposed checkpoints, validate the plan, and
perform the graph mutations. Load the full trace itself only when no subagent is
available or the compact plan leaves a material ambiguity.

To analyze the trace directly, inspect it from oldest version to newest:

```bash
jj --no-pager evolog -r @ --reversed -p --git
```

`-p` shows each version's patch against the previous version. If its parents
changed, jj temporarily rebases the older version onto the newer version's
parents so unrelated rebase changes do not contaminate the patch. Start with
`--stat` instead of `--git` when the full trace is too large, then rerun with
`--git` once its scope is understood.

The hook snapshots execution history, not intent. Do not turn every evolution
entry into a commit. Ignore empty metadata-only versions, reversals, failed
experiments, and mechanical follow-up edits; group the ordered patches into the
smallest coherent changes that build and make sense independently.

Each entry names a commit ID for that historical version. Inspect that version
in context when an evolution patch alone is insufficient:

```bash
jj --no-pager show --git COMMIT_ID
```

Before rewriting, record the current commit ID so the final tree remains
independently checkable:

```bash
jj --no-pager log -r @ --no-graph -T 'commit_id ++ "\n"'
```

Reconstruct the intended series from oldest boundary to newest. Use ordinary
`jj split` with an explicit fileset when the boundary is a selection of files.
When a boundary is best represented by one historical tree—and its parent
context is still compatible—use [interpolation](interpolate.md) to insert the
lower commit, then restore that evolog snapshot while the helper is waiting for
the intermediate state:

```bash
"<skill-dir>/scripts/interpolate" begin -A '@-' -B '@' -m 'earlier change'
jj --no-pager restore --from EVOLUTION_COMMIT_ID
jj --no-pager diff --git
"<skill-dir>/scripts/interpolate" finish
```

Repeat with later checkpoints. If the historical version was based on
different parent content, restoring its whole tree may reintroduce unrelated
base changes. In that case, use the normalized evolog patches as evidence and
construct only the intended content instead of restoring the snapshot
wholesale.

After reconstruction, compare the final tree with the original recorded commit
ID; the diff must be empty:

```bash
jj --no-pager diff --git --from ORIGINAL_COMMIT_ID --to @
```

Review every resulting change and run the relevant tests. Evolog provides the
evidence needed to recover the work; semantic commit boundaries still require
judgment. This workflow reads historical versions and performs ordinary history
rewrites—it never requires operation-log surgery.
