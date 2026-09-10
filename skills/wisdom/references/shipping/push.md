# Push work

`jj git push` moves bookmarks and tags, not an anonymous working-copy line.
Confirm that the named pointer targets the intended described change before
pushing; [Manage bookmarks](bookmarks.md) owns creating or advancing one.

```bash
jj --no-pager git push -b feature --dry-run
jj --no-pager git push -b feature
```

The dry-run is the gate: it must list only the intended remote changes. A
first push of an untracked bookmark creates and starts tracking it. The push
covers commits through that bookmark's target and nothing beyond it.

An empty description is a failed precondition:

```text
Error: Won't push commit d42cf91d5be4 since it has no description
```

Describe the change and retry. Treat the rejection as correct; publishing an
unreadable change is not the completion criterion.

## Choose the remote explicitly

Tracking does not choose the push remote. With more than one remote, or when
the user names one, inspect and pass it explicitly:

```bash
jj --no-pager git remote list
jj --no-pager git push --remote upstream -b feature --dry-run
jj --no-pager git push --remote upstream -b feature
```

Without `--remote`, jj uses `git.push` and then a remote named `origin`. A push
targets one remote at a time.

After a conflicted bookmark, the preflight must report `move forward`; read
[Reconcile a conflicted bookmark](bookmark-conflicts.md). A sideways or
backwards move changes what the remote name means and requires the user's
explicit choice about the work being displaced.

The push is complete when the dry-run was exact, the real push succeeds, and a
targeted `jj --no-pager bookmark list --tracked NAME` or `jj --no-pager tag
list --tracked NAME` shows the intended tracked target without conflict.
