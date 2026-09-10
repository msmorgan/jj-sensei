# Realign a stale workspace

A stale workspace rejects ordinary working-copy commands. Inspect it without
changing working-copy state by adding `--ignore-working-copy` to a read-only jj
command.

`jj workspace update-stale`, which `repair` runs first, is not necessarily
lossless. If another workspace abandoned this one's working-copy commit, it
moves this workspace to a fresh empty commit and rewrites disk to match:
tracked edits revert and files existing only in the abandoned change are
removed.

State that cost before running the repair and name the read-only recovery
route in the same breath:

```bash
jj --no-pager --ignore-working-copy op log
jj --no-pager --at-op OPERATION file show -r ABANDONED_CHANGE PATH
```

Recover important content before realignment or copy it forward afterward;
operation snapshots survive either order. [Recover a file](recovery.md)
automates the lookup for one path.

The stale branch is complete when the user has heard the possible disk effect,
recoverable content has been accounted for, `repair` exits `0`, and the
operation that exposed the stale state succeeds on retry.
