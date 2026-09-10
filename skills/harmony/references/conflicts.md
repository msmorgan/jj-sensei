# Resolve file conflicts

## Conflict at `@`

A conflict recorded at `@` is materialized in the working-copy files. Edit the
complete marker block or run a specifically chosen `conflicts accept`; the
next jj command snapshots the resolution.

## Conflict in an ancestor

An ancestor's conflict is also materialized at `@`, but editing it there
resolves only `@`. Fix the revision where the conflict lives:

```bash
jj --no-pager log -r 'conflicts()' -T builtin_log_oneline
jj --no-pager edit CONFLICTED_CHANGE_ID
# edit the complete marker block to the intended content
jj --no-pager st
jj --no-pager log -r 'conflicts()' -T builtin_log_oneline
jj --no-pager edit ORIGINAL_TIP_CHANGE_ID
```

Capture the original tip's change ID before moving. The first conflict listing
must identify the oldest conflicted change; the second must be empty before
returning. Descendants rebase as the ancestor is fixed.

## Inspect and accept marker content

The helper supports jj's default diff+snapshot marker style:

```bash
"<skill-dir>/scripts/conflicts" list
"<skill-dir>/scripts/conflicts" show [--json] [FILE ...]
```

Read [Read jj conflict markers](markers.md) before hand-editing a block; it
owns section grammar, long markers, missing newlines, N-way conflicts, and
alternative styles.

Use a mechanical representation only after its meaning is understood:

```bash
"<skill-dir>/scripts/conflicts" accept FILE snapshot
"<skill-dir>/scripts/conflicts" accept FILE diff
"<skill-dir>/scripts/conflicts" accept FILE base
"<skill-dir>/scripts/conflicts" accept FILE stack
"<skill-dir>/scripts/conflicts" accept FILE stack-snap-first
```

A conflict “including 1 deletion” resolves as a deletion only when the path is
removed; empty marker content and `accept FILE diff` leave a tracked zero-byte
file. The marker reference is authoritative for this case.

`stack` variants apply only to two pure-add sides reported as `stackable:
true`. The conservative automatic resolver can preview or apply proven-safe
hunks:

```bash
"<skill-dir>/scripts/conflicts" auto --dry-run [FILE ...]
"<skill-dir>/scripts/conflicts" auto [FILE ...]
```

It leaves generated files and uncertain hunks untouched. A `✓` establishes
only that the line merge was mechanically safe; inspect the result semantically.

```bash
jj --no-pager diff --git
jj --no-pager st
"<skill-dir>/scripts/conflicts" list
```

Conflict resolution is complete when the final helper listing and
`conflicts()` revset are empty, the diff expresses the intended content, and
the relevant project tests pass.
