# Manage bookmarks

Bookmarks are named pointers to revisions. They follow a revision when it is
rewritten, never advance merely because work started from them, and are not
created by `jj new` or `jj commit`. Create, move, or delete one only when the
user, task, or workflow calls for that named-pointer change.

## Point a bookmark at real work

`jj bookmark create NAME -r REV` defaults `-r` to `@`, commonly a fresh empty
undescribed child after `jj commit`. Inspect the described tip and name the
intended target explicitly:

```bash
jj --no-pager log -r '::@' -n 3 -T builtin_log_oneline
jj --no-pager bookmark create feature -r @-
```

Confirm the target from the listing rather than assuming `@-`; after several
commits or `jj new`, the described tip may be further back. Use `jj --no-pager
bookmark set NAME -r REV` to move an existing bookmark. In `jj log`, `main*`
means the local and remote bookmark targets differ, usually because a push is
outstanding.

## Advance after landing work

Advancing a bookmark is implied when new work sits on top of the line it
already names—that is what “land this on `feature`” asks for. Ask when the
move would go sideways or backwards, rewrite a remote target, or the work was
merely started from the bookmark rather than built on it. Once decided, name
the target explicitly:

```bash
jj --no-pager bookmark set main -r @-
jj --no-pager bookmark move main --to @-
```

`jj --no-pager bookmark advance --to REV` moves the closest bookmarks at or
below the target. With several candidates it may move an unintended one, so
name bookmarks positionally: `jj --no-pager bookmark advance main --to @-`.

## Rename, forget, or delete

Deleting and forgetting have different remote effects:

```bash
jj --no-pager bookmark delete feature
jj --no-pager git push -b feature --dry-run
jj --no-pager git push -b feature
```

Deletion marks the remote name for removal on the next push; it does not
abandon the revisions. Deleting a bookmark at `@` leaves the change,
description, and working copy intact.

`jj --no-pager bookmark forget NAME` only unregisters the name locally. The
remote branch remains and becomes untracked. Use forget to stop tracking, not
to delete remotely.

Renaming is local, so a remote rename needs both halves:

```bash
jj --no-pager bookmark rename old-name new-name
jj --no-pager git push -b new-name -b old-name --dry-run
jj --no-pager git push -b new-name -b old-name
```

If the old name was never pushed, publish only the new name.

Bookmark work is complete when `jj --no-pager bookmark list NAME` shows the
intended local target and `jj --no-pager bookmark list --tracked NAME` shows
the intended tracked target. For a remote effect, the dry-run must name exactly
the move, creation, or deletion intended before the real push.
