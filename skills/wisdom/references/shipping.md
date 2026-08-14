# Publish and land work

Bookmarks are the only thing `jj git push` moves. Nothing about a bookmark is
implicit: none is checked out, none advances because work started from it,
and none is created by `jj new` or `jj commit`.

## Point a bookmark at real work

`jj bookmark create NAME -r REV` defaults `-r` to `@` — normally the wrong
revision, since after `jj commit`, `@` is a fresh empty undescribed child and
naming it produces a bookmark that cannot be pushed. Name the last
*described* change instead:

```bash
jj --no-pager log -r '::@' -n 3 -T builtin_log_oneline
jj --no-pager bookmark create feature -r @-
```

Confirm the target from that listing rather than assuming `@-` is right; after
several commits or a `jj new`, the described tip may be further back.

Use `jj bookmark set NAME -r REV` to move an existing bookmark. In `jj log`,
`main*` means the local bookmark and its remote counterpart point at different
revisions — a reminder that a push is outstanding, not an error.

## Push

```bash
jj --no-pager git push -b feature --dry-run
jj --no-pager git push -b feature
```

`--dry-run` prints the intended remote changes without touching anything —
cheap insurance before any push whose effect isn't obvious.

Pushing an untracked bookmark creates the remote bookmark and starts tracking
it automatically — no separate track step is needed. The push covers every
commit from the remote's current position up to the bookmark's target, and
nothing beyond it.

Empty descriptions are rejected:

```text
Error: Won't push commit d42cf91d5be4 since it has no description
```

Describe the change and push again. `--allow-empty-description` exists but
publishes a commit no reviewer can read; treat the rejection as correct.

## Fetch, tracking, and rebasing onto upstream

`jj git fetch` updates remote bookmarks, moving a *local* bookmark only when
it is tracked. An untracked update is reported plainly:

```text
bookmark: main@origin [updated] untracked
```

That line means the local `main` did **not** move — rebasing onto `main`
after seeing it rebases onto stale history. The full lifecycle:

```bash
jj --no-pager git fetch --remote origin
jj --no-pager bookmark track main@origin     # only if fetch said untracked
jj --no-pager rebase -r 'main..@' -A main
```

`jj git clone` tracks the default branch and leaves other remote bookmarks
untracked, so a colleague's branch fetched later always needs `bookmark
track` before it is usable as a local name.

Fetching also prunes: commits no longer reachable from any branch on the
remote are treated as abandoned there and abandoned locally to match, unless
`git.abandon-unreachable-commits` is set to `false`. A force-push by someone
else can therefore remove local commits on the next fetch.

## More than one remote

jj does **not** infer the remote from tracking — `jj help git push` states it
outright: "Unlike in Git, the remote to push to is not derived from the
tracked remote bookmarks. […] There is no option to push to multiple
remotes." Without `--remote` it falls back to the `git.push` setting, then to
a remote literally named `origin`.

Pass `--remote NAME` whenever the repository has more than one remote or the
user named one, and push each separately:

```bash
jj --no-pager git remote list
jj --no-pager git push --remote upstream -b feature
```

## When a bookmark shows `??`

`main??` in `jj log`, and `main (conflicted):` in `jj bookmark list --all`,
mean the bookmark is *tracked* and both ends moved from a common base — local
`main` advanced to one commit, `main@origin` to another, and the fetch could
not reconcile them:

```text
main (conflicted):
  - nuksvuvu e45b3ffa init
  + zktnryzs f315a667 local work on main
  + luzozstn f323a372 remote work on main
```

The `-` line is the base; each `+` line is a side. jj's hint (`jj bookmark
set <name> -r <rev>`) clears the markers, but only resolves the *bookmark*,
not the *work* — naming the local side discards the remote commit, as the
push preflight reports plainly:

```text
bookmark: main [move sideways from 8ba2aa7bfa8f to 7aa879ce03bc]
```

`move sideways` means the remote is being moved off a commit that is not an
ancestor of the new target — a force push that drops whatever was there.

The safe resolution reconciles the content instead: rebase the local commit
onto the remote head. The bookmark follows the rewritten commit on its own —
no second `bookmark set` needed — and the two sides stop diverging once one is
an ancestor of the other:

```bash
jj --no-pager rebase -r LOCAL_CHANGE -o main@origin
jj --no-pager bookmark list --all          # no longer conflicted
jj --no-pager git push -b main --dry-run
```

That dry-run must report `move forward`:

```text
bookmark: main [move forward from 8ba2aa7bfa8f to 1fb830be0e1f]
```

Check the vocabulary before every push that follows a conflict. `move forward`
is a fast-forward and loses nothing; `move sideways` needs the user's explicit
agreement about what is being dropped, and is never something to run because
it made the `??` go away.

## Advancing a bookmark after landing work

Advancing a bookmark is implied when new work sits on top of the line it
already names — that is what "land this on `feature`" asks for. It needs
asking when the move would go sideways or backwards, rewrite what a remote
already has, or when the work was merely *started* from the bookmark rather
than built on it. Once decided, name the target explicitly:

```bash
jj --no-pager bookmark set main -r @-        # to one named revision
jj --no-pager bookmark move main --to @-     # same effect, refuses to create
```

`jj bookmark advance --to REV` is the shorthand: it moves the *closest*
bookmarks at or below the target — by default `heads(::to & bookmarks())` —
so with one bookmark below `@` it does the obvious thing, but with several it
may move one you did not intend. Name bookmarks positionally (`jj bookmark
advance main --to @-`) to restrict it. Check the result with `jj --no-pager
bookmark list` before pushing.

## Renaming and deleting

Deleting and forgetting a bookmark are different operations — only one
reaches the remote:

```bash
jj --no-pager bookmark delete feature      # then push to propagate
jj --no-pager git push -b feature          # sends `[delete from <hash>]`
```

`jj bookmark delete` marks the deletion to be pushed; the remote bookmark
survives until that push runs. Verify with `jj --no-pager git push -b feature
--dry-run`, reporting `bookmark: feature [delete from <hash>]`. Deleting a
bookmark does **not** abandon the revisions it pointed at.

`jj bookmark forget NAME` only unregisters the name locally and never
propagates — remote bookmarks simply become untracked, so the branch stays on
the remote. Use it to stop tracking, never to delete.

Renaming is local in the same way, so the remote needs both halves:

```bash
jj --no-pager bookmark rename old-name new-name
jj --no-pager git push -b new-name -b old-name
```

The old name has to be pushed too, or the remote keeps a branch under it
forever — unless it was never pushed, in which case pushing the new name is
enough.

Tags delete locally with `jj --no-pager tag delete NAME`, which likewise does
not abandon the tagged revisions (see Tags below on why it never reaches the
remote).

## Tags

```bash
jj --no-pager tag set v1.0.0 -r main
jj --no-pager tag set v1.0.0 -r main --allow-move   # to repoint an existing tag
jj --no-pager tag list
```

This jj publishes no tags: `jj git push` has no tag option at all, pushing
bookmarks only, so creating a tag locally never releases it and there is no
jj-side workaround. Surface that limitation and let the user push the tag
through whatever mechanism the project uses; do not invent one.
