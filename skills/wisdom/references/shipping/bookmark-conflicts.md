# Reconcile a conflicted bookmark

`main??` in `jj log`, or `main (conflicted):` in `jj bookmark list --all`,
means a tracked local bookmark and its remote counterpart both moved from a
common base:

```text
main (conflicted):
  - nuksvuvu e45b3ffa init
  + zktnryzs f315a667 local work on main
  + luzozstn f323a372 remote work on main
```

The `-` line is the base and each `+` line is a side. Clearing the pointer
markers alone does not reconcile their work. First identify the local root and
remote head with `jj --no-pager bookmark list --all main`, then rebase the
complete local subtree:

```bash
jj --no-pager rebase -r 'LOCAL_CHANGE::' -o main@origin
jj --no-pager bookmark list --all
jj --no-pager git push -b main --dry-run
```

The `::` is load-bearing: selecting only `LOCAL_CHANGE` reparents its
descendants onto the old parent and can strand the ordinary empty `@`.
Selecting `LOCAL_CHANGE::` carries everything built on the local root.

The bookmark follows the rewritten local change automatically. The listing
must lose `(conflicted)`, and the push dry-run must report `move forward`:

```text
bookmark: main [move forward from 8ba2aa7bfa8f to 1fb830be0e1f]
```

`move forward` is the checkable completion criterion: the remote target is an
ancestor of the new target, so the update loses nothing. `move sideways`
displaces remote work; stop and obtain the user's explicit decision rather
than treating disappearance of `??` as success.
