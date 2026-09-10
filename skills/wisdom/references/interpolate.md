# Interpolate a change

Interpolation inserts an intermediate state while preserving the upper
change's content. Prefer ordinary `jj split` whenever selection is sufficient.
Use `insert` when the intermediate tree exists in a snapshot, or `begin` /
`finish` when it must be constructed through working-copy edits.

## Insert an existing snapshot

```bash
"<skill-dir>/scripts/interpolate" insert --from SNAPSHOT -B TARGET -m 'earlier change'
```

`SNAPSHOT` is a historical commit ID; `TARGET` is the change to insert before.
The command completes in one invocation and prints the inserted change ID.
It uses `new --no-edit` and `restore --into --restore-descendants`, leaving the
working copy on the same change and preserving the target and descendant
trees throughout. No `finish` or final rebase is needed.

This mode requires single-parent snapshots and targets. The target's parent
tree must match the snapshot's parent tree, or an earlier version of the
snapshot on that same base. This admits successive checkpoints from one
evolution log while refusing incompatible historical base content. The
whole-tree copy is intentional; choose a snapshot whose entire state belongs
at this boundary. The helper verifies tree preservation, not semantic commit
boundaries.

For a series, call `insert` with the selected snapshots oldest first, keeping
the target change ID fixed. Leave the final state in the original target.
See [Reconstruct work with evolog](using-evolog.md) for checkpoint selection.

After interruption, rerun the same `insert` command with the same arguments,
or use `abort` to discard the unfinished insertion. The journal records the
source commit ID, so resuming uses the originally selected tree. External
content or graph changes can require judgment rather than an automatic retry.

## Construct a state in the working copy

Use this mode when generated manifests, lockfiles, snapshots, or migrations
must be recreated at the intermediate state.

This is not a native jj idiom: jj's working copy is a real commit, so the
helper works around that by temporarily moving the upper revision's complete
tree into a newly inserted lower revision, journaling that graph state, then
restoring the exact original upper tree. Do not reproduce its graph
choreography by hand.

Interpolation names the exact graph edge using jj's `--after`/`--before`
style: the endpoints must be distinct, and `AFTER` must be a parent of
`BEFORE`. `BEFORE` may be a merge — only the named edge changes.

Start the guarded transaction with a description for the new lower change:

```bash
"<skill-dir>/scripts/interpolate" begin -A '@-' -B '@' -m 'lower change description'
```

Exit `1` means the working copy now contains `BEFORE`'s complete original
tree — construct the intermediate state there: remove the content belonging
above it, run generators at that state, and verify every dependent artifact
agrees. Then finish:

```bash
"<skill-dir>/scripts/interpolate" finish
```

`finish` restores `BEFORE`'s exact original tree above the constructed state and
returns to the change that was the working copy when `begin` started. The new
lower change already has the description supplied with `-m`.

## Abort and recovery

To discard an unfinished interpolation and restore the original graph and content:

```bash
"<skill-dir>/scripts/interpolate" abort
```

The helper journals intent before mutating and reconciles any completed jj
commands after an interruption. Its exit status is load-bearing — run it
bare, never through a pipe.

- `0` — finished or aborted cleanly.
- `1` — edit the constructed intermediate state, then run `finish`.
- `70` — an internal error occurred; transaction state is preserved. Present
  the diagnosis, and do not improvise a recovery command.
- `75` — another jj-sensei history transaction holds the workspace lock;
  retry after it finishes.
- `80` — human judgment is required; present the reported state and ask
  before continuing.

This exit-code list applies only to the helper itself, not to an ordinary jj
invocation rejected for invalid syntax or options.

Do not edit or delete `.jj/jj-sensei/interpolate.json`. Do not use operation-log
recovery, immutability bypasses, or a manual abandon as recovery. If `begin` or
`insert` was interrupted, rerun that same command; otherwise rerun the phase
named by the diagnosis.
