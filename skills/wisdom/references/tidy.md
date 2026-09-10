# Tidy the working copy into the right commits

The common request — "this fix belongs in that earlier commit" — has a
one-command answer before any manual choreography.

## Absorb first

```bash
jj --no-pager absorb
jj --no-pager absorb FILESET
```

`absorb` splits the changes in `@` and moves each hunk into the closest
*mutable* ancestor that last modified those lines. A hunk with an ambiguous
destination stays behind in the source, so it's safe to run and inspect
after. If everything is absorbed and the source has no description, the
source revision is abandoned.

`-f REVSET` chooses a source other than `@`; `-t REVSETS` narrows the
candidate destinations, which default to `mutable()`. Review the result with
`jj --no-pager op show -p` or an ordinary `jj --no-pager log`/`jj --no-pager
diff`.

Reach past `absorb` only when the destination isn't the commit that last
touched those lines — a new file, or a hunk `absorb` wouldn't choose.

## Squash explicitly

```bash
jj --no-pager squash --from @ --into CHANGE FILESET -m 'combined description'
jj --no-pager squash --from @ --into CHANGE FILESET -u
```

Either `--from` or `--into` defaults to `@` when omitted. Always give `-m` or
`-u`: when both source and destination have nonempty descriptions and the
source is emptied, jj otherwise opens an editor to combine them. `-m` sets the
destination's description; `-u`/`--use-destination-message` keeps the
destination's and discards the source's — usually what's wanted when
squashing a fix into an already-well-described commit.

Reword without folding anything: `jj --no-pager describe -r @- -m '...'`
touches the description and nothing else, so unrelated work in `@` stays in
`@`. Reach for `squash` only when the working-copy diff really belongs in the
parent.

Squashing everything out of `@` empties it. jj then abandons that revision and
gives the working copy a new, empty commit with a new change ID.

## Commit only part of the working copy

```bash
jj --no-pager commit FILESET -m 'what those paths do'
```

The named paths stay in the committed change; everything else moves to a new
working-copy commit on top. Unlike `jj split`, this never moves bookmarks
forward.

## Repeated splitting

Turning one mixed change into N commits takes exactly N−1 two-way splits. Each
split leaves two revisions and the next split targets one of them. Read
[Choose which half of a split moves](placement.md#choose-which-half-of-a-split-moves)
before the first split; it is the single source for change IDs, descriptions,
bookmark movement, and `@` placement. Splitting is complete only when every
resulting change has the intended content and description and the final graph
and bookmark targets match the stated postconditions.

## Fileset syntax

Literal paths need no lookup. For operators, patterns, functions, quoting, or
precedence, load `knowledge` and run `rtfm filesets`; the installed manual is
the source of truth. For rebase selection and placement, read [Place changes
deliberately](placement.md).

## Anonymous-head litter

Empty undescribed changes are normal and usually auto-pruned. To sweep only
the mutable anonymous heads no workspace or bookmark holds:

```bash
jj --no-pager abandon -r '(empty() & description(exact:"") & mutable() & visible_heads()) ~ working_copies() ~ bookmarks()'
```

Preview it with `jj --no-pager log -r '<the same expression>'` first. This is
housekeeping, not a step in any other recipe; run it only when the litter is
in the way.
