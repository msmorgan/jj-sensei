# Interpolate a change

Interpolation constructs an intermediate state between two commits when doing
so is not a matter of selecting files and lines. Prefer ordinary `jj split`
whenever selection is sufficient; use this guarded escape hatch when, for
example, generated manifests, lockfiles, snapshots, or migrations must be
recreated at the intermediate state.

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

To discard the interpolation and restore the original graph and content:

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
recovery, immutability bypasses, or a manual abandon as recovery. If `begin` was
interrupted, rerun the same `begin` command; otherwise rerun the phase named by
the diagnosis.
