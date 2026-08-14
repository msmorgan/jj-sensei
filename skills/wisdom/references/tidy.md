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
`jj --no-pager op show -p` or an ordinary `jj log`/`diff`.

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
split leaves two revisions and the next split targets one of them.

```bash
jj --no-pager split -r REV -m 'first commit' FILESET
```

Four things follow from a default split, all of them easy to get wrong:

- The **selected** half keeps `REV`'s change ID and becomes the parent. The
  **remainder** becomes its child under a *new* change ID.
- `-m` describes the selected half only. The remainder keeps `REV`'s original
  description verbatim, so it's now mislabelled — a final `jj --no-pager
  describe -r REV+ -m '...'` is part of the recipe, not an afterthought.
- Address the remainder as `REV+` — the child of the change ID that stayed
  with the selected half. Don't parse the split's output for its ID.
- A **bookmark on `REV` follows the remainder**, not the half that kept the
  change ID. Check with `jj --no-pager log -r 'REV::' -T builtin_log_oneline`
  before pushing anything.

`-A`, `-B`, and `-o` change the shape: they extract the selected changes into
a new commit at the named location and leave the remainder in place. `-p`
makes the two halves siblings instead of parent and child. See
[Place changes deliberately](placement.md).

## Fileset syntax

Every `FILESET` above is an expression, not a plain path list.

| Form | Matches |
|---|---|
| `src/parser.rs` | cwd-relative path prefix — file, or directory recursively |
| `file:"src/parser.rs"` | that exact cwd-relative path |
| `glob:"*.rs"` | cwd-relative glob, non-recursive |
| `prefix-glob:"*.d"` | like `glob:`, and everything under a match |
| `root:"docs"` | workspace-relative prefix; `root-file:`, `root-glob:` follow |
| `glob-i:"*.TXT"` | any glob pattern name plus `-i` matches case-insensitively |
| `~x` | everything except `x` |
| `x & y`, `x ~ y` | intersection and difference — **equal** binding power, parsed left to right, so `x ~ y & z` means `(x ~ y) & z` |
| `x \| y` | union — binds more weakly than both of the above |
| `all()`, `none()` | everything, nothing |

Parenthesize whenever `&` and `~` appear together — the left-to-right reading
above is rarely the one intended: write `x ~ (y & z)` or `(x ~ y) & z`
explicitly.

Quotes inside the expression can be omitted only when it has no operators and
no function calls — `jj diff 'Foo Bar'` is fine, but `jj diff '~"Foo Bar"'`
needs both shell and inner quotes. Glob characters aren't meta characters for
this rule, but shell quoting is still required.

## Which rebase flag

- `-r REVSETS` rebases exactly those revisions; their descendants are rebased
  onto the revisions' parents, so the rest of the stack stays where it is.
- `-s ROOTS` rebases each named revision *together with its whole tree of
  descendants*, making each named revision a direct child of the destination.
- `-b REVSETS` rebases the whole branch relative to the destination's
  ancestors: `jj rebase -b BR -o DST` is defined as
  `jj rebase -s 'roots(DST..BR)' -o DST`.
- With none of `-b`, `-s`, or `-r`, the default is `-b @`. A bare `jj rebase`
  therefore moves considerably more than the working copy.

Prefer `-r` with an explicit revset — see [Place changes
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
