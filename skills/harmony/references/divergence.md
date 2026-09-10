# Converge working-copy successors

`"<skill-dir>/scripts/converge"` handles only divergent successors of this
workspace's own working-copy change. It keeps the sole nonempty successor, or
one of byte-identical successors, and leaves a bookmark on the keeper intact.

It stops when losing a candidate would affect a bookmark, when nonempty trees
differ, or when another workspace owns a candidate. Present that state and let
the user choose; equivalence has not been established.

A divergent change elsewhere in the graph is a different branch. Load
`knowledge` and read `rtfd docs/guides/divergence`; inspect both commit-ID
successors because their shared change ID is ambiguous.

Convergence is complete when `jj --no-pager log -r 'divergent()' -T
builtin_log_oneline` no longer lists this workspace's working-copy change and
the surviving tree and bookmark target match the diagnosed keeper.
