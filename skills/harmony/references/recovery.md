# Recover a file from operation snapshots

Use the read-only helper when content no longer exists in the visible change
graph:

```bash
"<skill-dir>/scripts/recover-file" list PATH
"<skill-dir>/scripts/recover-file" list -n 200 PATH
"<skill-dir>/scripts/recover-file" show OPERATION PATH
```

`list` walks snapshot operations and reports only states where the path's
content changed. `show` prints one state; copy the chosen content forward as an
ordinary edit.

Only snapshotted states exist. Edits overwritten between snapshots cannot be
recovered here. For earlier versions of a change that still exists, use `jj
--no-pager evolog -r CHANGE` instead.

Recovery is complete when the selected snapshot has been identified by
operation, its content has been copied forward, and the resulting diff and
relevant project tests verify the restored file.
