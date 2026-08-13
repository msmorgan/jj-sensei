# Place changes deliberately

Use placement flags to state the graph relationship you want. This is usually
clearer than calculating destination parents or special-casing whether a move
is already necessary.

## Choose which half of a split moves

With the default form, the selected `FILESET` remains in the original change;
the unselected remainder becomes a new child:

```bash
jj --no-pager split -r REV -m 'selected change description' FILESET
```

Use `-A REV` when the selected files should instead become the new later
change. The unselected remainder keeps `REV`, its position, and its original
description; the selected files are extracted into a new child after it:

```bash
jj --no-pager split -r REV -A REV -m 'selected change description' FILESET
```

Choose the form whose selected side is the change you intend to describe and
place. Always provide a `FILESET` to avoid the interactive diff editor and `-m`
to avoid the description editor.

## State placement as an invariant

`-A LOWER` means the selected revision belongs after `LOWER`; `-B UPPER` means
it belongs before `UPPER`. These placement forms are idempotent when the
requested ancestry relationship is already satisfied, so issue the command
that states the desired relationship instead of first branching on whether a
move appears necessary:

```bash
jj --no-pager rebase -r CHANGE -A LOWER
jj --no-pager rebase -r CHANGE -B UPPER
```

Combine them to name both endpoints of a specific edge:

```bash
jj --no-pager rebase -r CHANGE -A LOWER -B UPPER
```

This is surgical around merges: `UPPER` may have several parents, while
`LOWER` identifies the one edge being split. The endpoints are distinct
revisions. Use `-r` for only the selected revisions; use `-s` instead when the
whole descendant subtree is intentionally moving.

These flags encode placement, not permission. Immutability, workspace
ownership, and bookmark intent still apply; never bypass a refusal to make the
relationship fit.
