# Manage tags

Create a tag at an explicitly verified revision:

```bash
jj --no-pager tag set v1.0.0 -r main
jj --no-pager tag list
```

If the tag already exists, jj refuses to move it. Treat that as a user choice
about whether the release name should change; after confirmation, the command
is `jj --no-pager tag set v1.0.0 -r main --allow-move`.

## Publish and track

jj publishes tags directly:

```bash
jj --no-pager git push --remote origin -t v1.0.0 --dry-run
jj --no-pager git push --remote origin -t v1.0.0
```

The first push starts tracking an untracked tag. Local creation alone is not a
release; the remote effect occurs only on push. Dry-run output must name only
the intended tag update.

Import or stop following a remote tag with:

```bash
jj --no-pager tag track v1.0.0@origin
jj --no-pager tag untrack v1.0.0@origin
```

Tracking governs visibility and remote deletion. `jj --no-pager tag list`
hides untracked remote tags and usually hides a tracked counterpart already at
the local target; differing local and remote targets render as a conflict.

## Delete

Remote deletion requires a tracked tag, a local delete, and a push:

```bash
jj --no-pager tag delete v1.0.0
jj --no-pager git push --remote origin --deleted --dry-run
jj --no-pager git push --remote origin --deleted
```

`--deleted` covers all tracked bookmark and tag deletions, so the dry-run must
list this deletion and no unrelated one before the real push. Deleting the tag
does not abandon its revision.

Fetch behavior for tags is configured per remote. Load `knowledge` and query
`rtfm git fetch --full` when exact `fetch-tags` or refspec semantics matter;
the installed manual is authoritative.

Tag work is complete when `jj --no-pager tag list NAME` shows the intended
local target and `jj --no-pager tag list --tracked NAME` shows the intended
tracked target. For deletion, both must be empty after the exact dry-run and
successful push.
