# Fetch and track upstream

`jj git fetch` updates remote bookmarks. A tracked local bookmark follows a
non-divergent remote update; an untracked one does not:

```text
bookmark: main@origin [updated] untracked
```

That output means local `main` stayed on stale history. `[updated] tracked`
means the local bookmark already advanced. Ask the tracking question directly:

```bash
jj --no-pager bookmark list --tracked main
```

An empty result means no tracked remote bookmark matched. `jj --no-pager
bookmark list --all` displays both kinds and is not a tracking test.

`jj git init --colocate` leaves existing remote bookmarks untracked. `jj git
clone` auto-tracks only the default branch. A complete fetch-to-rebase path is:

```bash
jj --no-pager git fetch --remote origin
jj --no-pager bookmark track main@origin
jj --no-pager rebase -r 'main..@' -A main
```

Run `bookmark track` only when the fetch or tracked listing established that
the remote bookmark is untracked. Before rebasing, preview the same revset and
apply Wisdom's mutability gate.

Fetching can abandon local commits no longer reachable from any remote branch
when `git.abandon-unreachable-commits` permits it. A force-push by someone else
can therefore remove local commits on the next fetch; inspect unexpected
abandonment through the read-only recovery routes.

## More than one remote

Fetch and push do not infer a remote from bookmark tracking. Inspect the
configured remotes, then name the intended source or sweep deliberately:

```bash
jj --no-pager git remote list
jj --no-pager git fetch --remote upstream
jj --no-pager git fetch --all-remotes
```

Without an explicit remote, fetch uses `git.fetch`, then `origin` when several
remotes exist. “Nothing changed” says nothing about a remote that was not
queried. `--remote` accepts a pattern and can be repeated; consult `knowledge`
and `rtfm git fetch` for the installed version's exact selection syntax.

Sync is complete when every intended remote was fetched, tracking state was
queried directly, the rebase selection matched the intended stack, and the
resulting parent chain and `@` position satisfy Placement's postconditions.
