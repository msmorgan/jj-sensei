# Converge working-copy successors

`"<skill-dir>/scripts/converge"` handles only divergent successors of this
workspace's own working-copy change. It hands them to `jj converge
--no-interactive`, which merges them from the change's evolution: both sides'
edits and the newer parents survive, and a local bookmark on any successor
moves to the converged change. The helper then requires exactly one successor.

When the sides disagree on content, the converged change records a file
conflict. `repair` continues into its conflict walk; after the narrow helper,
run `repair`.

It stops with status `80`, changing nothing, when another workspace owns a
candidate, when a candidate is immutable, or when jj cannot choose a
description, parents, or author by itself. Present jj's reason and both
commit-ID successors and let the user choose; then apply that choice with
ordinary commands — `jj --no-pager describe`, `abandon`, or `metaedit
--update-change-id` — on commit IDs, because the shared change ID is ambiguous.

On a jj older than 0.45 there is no `jj converge`. The helper then only keeps
the sole nonempty successor, or one of byte-identical successors, and stops
when nonempty trees differ or a bookmark sits on a successor it would drop.

A divergent change elsewhere in the graph is a different branch. Load
`knowledge` and read `rtfd docs/guides/divergence`; inspect both commit-ID
successors first. That guide's `jj converge` prompts by default, so run it
only as `jj --no-pager converge --no-interactive -r REVSET`, with a revset
naming the divergent commits just inspected. Its exit status is not the
verdict: it also exits `0` when its revset left a candidate out.

Convergence is complete when `jj --no-pager log -r 'divergent()' -T
builtin_log_oneline` no longer lists the change, `jj --no-pager log -r
'conflicts()' -T builtin_log_oneline` is empty, and `jj --no-pager op show -p`
shows the converged change carrying the work both successors held.
