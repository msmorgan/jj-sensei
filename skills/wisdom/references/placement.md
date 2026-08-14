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

Which side ends up as `@` depends on whether `REV` was `@`. Splitting the
working copy leaves `@` on the **remainder** — a new change ID carrying `REV`'s
original description, sitting on top of the selected half, which kept `REV`'s
change ID. Splitting any other revision leaves `@` where it already was and
rebases it along with the rest of the descendants. Say which of these the plan
produces; the two differ in what the next command operates on.

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

Either flag alone already names a complete insertion. `-A LOWER` rebases the
selection onto `LOWER` and rebases `LOWER`'s descendants onto the result, so
the opposite endpoint is `LOWER`'s current children. `-B UPPER` rebases the
selection onto `UPPER`'s parents and rebases `UPPER` and its descendants onto
the result, so the opposite endpoint is `UPPER`'s current parents. Neither
form needs the other to be well defined.

Combine them only to name one specific existing edge:

```bash
jj --no-pager rebase -r CHANGE -A LOWER -B UPPER
```

This is surgical around merges: `UPPER` may have several parents, while
`LOWER` identifies the one edge being split. The endpoints are distinct
revisions.

Prefer `-A` and `-B` for ordinary insertion and reordering. They express where
the selection belongs in the surrounding history and move the affected
descendants with that relationship. By contrast, `-o DESTINATION` (`--onto`,
with `-d`/`--destination` as its alias) makes the selection a direct child of
`DESTINATION` without moving the destination's existing descendants. Use it
when that parallel fork is intentional, or repeat it when intentionally
creating a merge:

```bash
jj --no-pager rebase -r CHANGE -o FORK_POINT
jj --no-pager rebase -r CHANGE -o LEFT_PARENT -o RIGHT_PARENT
```

`jj new` belongs to this family too: `-A`/`--insert-after` and
`-B`/`--insert-before` create the new change at that position and rebase the
displaced descendants onto it, which is how new work is inserted into the
middle of a stack in one command:

```bash
jj --no-pager new -B LATER_CHANGE -m 'work that belongs underneath it'
```

Its positional arguments are the new change's **parents**, and `-r`/`-o` are
aliases for those positionals — not the `--onto` of `rebase`. `jj new -o main`
therefore means "parent is main", not "onto main".

## The same placement model elsewhere

`jj split`, `jj revert`, and `jj duplicate` take the same `-o`/`-A`/`-B`
triple with the same meanings, so a placement decision transfers between them
unchanged:

```bash
jj --no-pager revert -r LANDED -A TIP
jj --no-pager duplicate -r CHANGE -A TIP
```

`jj revert` is stricter than the others: it *requires* one of the three and
refuses to run without a placement, since there is no sensible default
location for a reversal.

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

## State the postconditions

A placement plan is not finished until it says what the graph looks like
afterwards. Three things are worth stating explicitly, because each is a place
plans routinely go wrong:

1. **The resulting parent chain** — the affected revisions in order, as
   `jj --no-pager log -r '<range>' -T builtin_log_oneline` would print them.
   Descendants rebase automatically; say which ones did.
2. **Which change is `@` afterwards.** Placement commands move the working
   copy in ways that are easy to miss: `jj new -A`/`-B` puts `@` on the newly
   created change, splitting `@` puts `@` on the remainder, and rebasing a
   revision that `@` descends from leaves `@` in place with a new commit hash.
3. **Whether an empty working-copy tip survives.** An empty, undescribed `@`
   is auto-pruned the moment the working copy moves off it, so a plan that
   ends "then go back to where I was" cannot use `jj edit <old-tip-id>` — that
   fails with `Revision ... doesn't exist`. Return with
   `jj --no-pager new <rebased-neighbor>` instead, which produces an
   equivalent fresh tip.

These flags encode placement, not permission. Immutability, workspace
ownership, and bookmark intent still apply; never bypass a refusal to make the
relationship fit.
