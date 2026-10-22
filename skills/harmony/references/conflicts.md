# Conflict edge cases

Harmony's Resolve conflicts procedure covers the ordinary case. This page
covers the files and conflicts that procedure leaves out; return to it, and to
its verification, once the edge case is settled.

## Inspect hunks before choosing

The helper supports jj's default diff+snapshot marker style:

```bash
"<skill-dir>/scripts/conflicts" list
"<skill-dir>/scripts/conflicts" show [--json] [FILE ...]
```

[Read jj conflict markers](markers.md) owns section grammar, long markers,
missing newlines, N-way conflicts, and alternative styles.

## Deletion conflicts

A conflict “including 1 deletion” resolves as a deletion only when the path is
removed; empty marker content and `accept FILE diff` leave a tracked zero-byte
file. The marker reference is authoritative for this case.

## Two pure additions

When both sides only add lines and `show` reports `stackable: true`, keep both
additions in either order:

```bash
"<skill-dir>/scripts/conflicts" accept FILE stack
"<skill-dir>/scripts/conflicts" accept FILE stack-snap-first
```

## Preview the automatic resolver

`repair` already applies the conservative resolver. To preview or apply it
directly:

```bash
"<skill-dir>/scripts/conflicts" auto --dry-run [FILE ...]
"<skill-dir>/scripts/conflicts" auto [FILE ...]
```

It leaves generated files and uncertain hunks untouched. A `✓` establishes
only that the line merge was mechanically safe; inspect the result semantically.

## Resolve without `repair`

`repair` walks only conflicts in `::@`. For a conflicted change outside that
ancestry, fix it where it lives and return:

```bash
jj --no-pager log -r 'conflicts()' -T builtin_log_oneline
jj --no-pager edit CONFLICTED_CHANGE_ID
# edit the complete marker block to the intended content
jj --no-pager st
jj --no-pager log -r 'conflicts()' -T builtin_log_oneline
jj --no-pager edit ORIGINAL_TIP_CHANGE_ID
```

Capture the original tip's change ID before moving. Start from the oldest
conflicted change in the first listing; the second listing must no longer show
it before returning. Descendants rebase as the ancestor is fixed.
