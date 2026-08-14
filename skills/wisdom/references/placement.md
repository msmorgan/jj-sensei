# Place changes deliberately

Placement flags state the graph relationship you want — clearer than
calculating destination parents or special-casing whether a move is needed.

## Choose which half of a split moves

With the default form, the selected `FILESET` remains in the original change;
the unselected remainder becomes a new child:

```bash
jj --no-pager split -r REV -m 'selected change description' FILESET
```

Use `-A REV` to make the selected files the new later change instead: the
remainder keeps `REV`, its position, and its original description, while the
selected files land in a new child after it:

```bash
jj --no-pager split -r REV -A REV -m 'selected change description' FILESET
```

Choose the form whose selected side is the change you intend to describe and
place. Always give a `FILESET` (skips the diff editor) and `-m` (skips the
description editor).

`-m` labels **only the selected half**. The other half keeps `REV`'s original
description verbatim, which usually leaves it mislabelled — a second
`jj --no-pager describe` on that half is part of the recipe, not an
afterthought.

Which side ends up as `@` depends on whether `REV` was `@`. Splitting the
working copy leaves `@` on the **remainder** — a new change ID carrying `REV`'s
original description, on top of the selected half, which kept `REV`'s change
ID. Splitting any other revision leaves `@` where it already was and rebases
it along with the rest of the descendants. Say which of these the plan
produces; the two differ in what the next command operates on.

## State placement as an invariant

Rebasing is surgical and never pauses at conflicts — they land in the
resulting commits. `-A` and `-B` each anchor the opposite endpoint to the
target's current neighbors, are no-ops when the relationship already holds,
and together name one exact edge. So issue the command that states the
relationship you want rather than first checking whether a move is needed:

```bash
jj --no-pager rebase -r CHANGE -A LOWER
jj --no-pager rebase -r CHANGE -B UPPER
jj --no-pager rebase -r CHANGE -A LOWER -B UPPER   # one specific edge
```

Combining them is what makes this surgical around merges: `UPPER` may have
several parents, and `LOWER` identifies the single edge being split. The two
endpoints must be distinct revisions.

### Swapping two adjacent commits

Given `base → FIRST → SECOND`, to make `SECOND` come first, either form works
and both are one command:

```bash
jj --no-pager rebase -r SECOND -B FIRST     # put SECOND before FIRST
jj --no-pager rebase -r FIRST -A SECOND     # equivalently, FIRST after SECOND
```

Both leave `base → SECOND → FIRST` with descendants and `@` riding along.
Pick whichever names the commit the user talked about — "move the docs commit
earlier" is `-r DOCS -B <the one it should precede>`.

Preview the revset before a nontrivial rebase — `jj --no-pager rebase -r
'main..@' -A main` is the usual "rebase my stack onto main", but the exact
selection depends on the intended stack.

Prefer `-A` and `-B` for ordinary insertion and reordering — they express
where the selection belongs and move the affected descendants with it. By
contrast, `-o DESTINATION` (`--onto`, aliased `-d`/`--destination`) makes the
selection a direct child of `DESTINATION` without moving its existing
descendants. Use it for an intentional parallel fork, or repeat it to create
a merge deliberately:

```bash
jj --no-pager rebase -r CHANGE -o FORK_POINT
jj --no-pager rebase -r CHANGE -o LEFT_PARENT -o RIGHT_PARENT
```

`jj new` belongs to this family too: `-A`/`--insert-after` and
`-B`/`--insert-before` create the new change at that position and rebase
displaced descendants onto it — how new work gets inserted mid-stack in one
command:

```bash
jj --no-pager new -B LATER_CHANGE -m 'work that belongs underneath it'
```

Its positional arguments are the new change's **parents**, and `-r`/`-o` are
aliases for those positionals — not the `--onto` of `rebase`. `jj new -o main`
therefore means "parent is main", not "onto main".

## The same placement model elsewhere

`jj split`, `jj revert`, and `jj duplicate` take the same `-o`/`-A`/`-B`
triple, so a placement decision transfers between them unchanged:

```bash
jj --no-pager revert -r LANDED -A TIP
jj --no-pager duplicate -r CHANGE -A TIP
```

`jj revert` is stricter than the others: it *requires* one of the three and
refuses to run without a placement, since there is no sensible default
location for a reversal.

`jj duplicate` is the cherry-pick: it **copies**, leaving the original where
it is. Placement is what reaches your line — bare `jj duplicate -r REV` lands
the copy beside the original, onto its **own** parents.

Decide from what you want `@`'s tree to contain, not from the flag names:

- Want the fix **in** `@`'s tree → `-B @`. The copy becomes `@`'s parent, so
  `@` builds on it and contains it.
- Want the copy **stacked on top of** `@` → `-A @`. The copy becomes `@`'s
  child, and **`@` will not contain it**.

`-B` reads as "before" in graph order, which is *underneath* in stack order.
When in doubt, run the command and check with `jj --no-pager diff --summary`.

A merge is just a new change with two parents — **`jj merge` does not
exist**:

```bash
jj --no-pager new main feature -m 'merge feature into main'
```

Neither bookmark advances on its own; whether `main` should then move onto the
merge is a decision to surface, not assume. See
[Publish and land work](shipping.md).

## Select revisions explicitly

Prefer `-r` whenever a command accepts it. Construct a revset naming the
complete set you intend to move, instead of relying on a source flag to
expand it implicitly:

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
selected revisions, keeping the command's scope visible in the expression and
independently testable. Use `-s` only when its distinct source semantics are
specifically required, not merely as shorthand for descendants that can be
written as `ROOT::`.

## State the postconditions

A placement plan isn't finished until it states what the graph looks like
afterward. Three things are worth stating explicitly — each is a place plans
routinely go wrong:

1. **The resulting parent chain** — the affected revisions in order, as
   `jj --no-pager log -r '<range>' -T builtin_log_oneline` would print them.
   Descendants rebase automatically; say which ones did.
2. **Which change is `@` afterward.** Placement commands move the working
   copy in easy-to-miss ways: `jj new -A`/`-B` puts `@` on the new change,
   splitting `@` puts it on the remainder (above), and rebasing a revision
   `@` descends from leaves `@` in place with a new commit hash.
3. **Whether an empty working-copy tip survives.** An empty, undescribed `@`
   is auto-pruned the moment the working copy moves off it, so a plan that
   ends "then go back to where I was" cannot use `jj edit <old-tip-id>` — that
   fails with `Revision ... doesn't exist`. Return with
   `jj --no-pager new <rebased-neighbor>` instead, which produces an
   equivalent fresh tip.

These flags encode placement, not permission. Immutability, workspace
ownership, and bookmark intent still apply; never bypass a refusal to make the
relationship fit.
