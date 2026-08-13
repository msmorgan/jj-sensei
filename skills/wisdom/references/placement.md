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
revisions.

Prefer `-A` and `-B` for ordinary insertion and reordering. They express where
the selection belongs in the surrounding history and move the affected
descendants with that relationship. By contrast, `-d DESTINATION` (also
spelled `-o DESTINATION`) makes the selection a direct child of `DESTINATION`
without moving the destination's existing descendants. Use it when that
parallel fork is intentional, or repeat it when intentionally creating a
merge:

```bash
jj --no-pager rebase -r CHANGE -o FORK_POINT
jj --no-pager rebase -r CHANGE -o LEFT_PARENT -o RIGHT_PARENT
```

## Select revisions explicitly

Prefer `-r` whenever a command accepts it. Construct a revset that names the
complete set you intend to move instead of relying on a source flag to expand
it implicitly:

```bash
jj --no-pager rebase -r CHANGE -A LOWER
jj --no-pager rebase -r 'ROOT::' -A LOWER
```

For a nontrivial revset, inspect exactly what it selects before using the same
quoted expression in a mutating command:

```bash
jj --no-pager log -r 'REVSET' -T builtin_log_oneline
```

Check both identities and graph extent. `-r` preserves dependencies among all
selected revisions, which makes the command’s scope visible in the expression
and independently testable. Use `-s` only when its distinct source semantics
are specifically required; do not reach for it merely as shorthand for
descendants that can be written as `ROOT::`.

These flags encode placement, not permission. Immutability, workspace
ownership, and bookmark intent still apply; never bypass a refusal to make the
relationship fit.
