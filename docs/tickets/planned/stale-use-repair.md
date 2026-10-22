# Steer stale workspaces to `repair`, not manual `update-stale`

Source: October 2026 study of 48 jj problem occasions across 30 agent sessions, mostly in deckmaste.rs (a Rust/Lean repo using jj-kata). Episode IDs (epNNN) refer to that study.

ep032: a stale-working-copy error hit a script before harmony was loaded; the
agent ran `jj workspace update-stale` directly, which triggered a
concurrent-modification rebase and left the working copy divergent
(`vqvxsort/0` and `vqvxsort/2`). Harmony was loaded only after that. By
contrast ep033, which followed harmony's route, cleared cleanly.

ep007 is related and also self-inflicted: the agent's own `jj squash --into`
put a conflict into a ticket file, the command chain did not stop on the
conflict notice, and `kata integrate` then folded the conflicted commit onto
the default line.

Done when harmony's stale route (SKILL.md and `references/stale.md`) makes
`repair` the path and says a bare `update-stale` is not; and wisdom has a rule
not to chain further commands after one that can introduce a conflict
(squash, rebase) without checking its output, if no such rule exists.
