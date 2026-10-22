# Route conflicts in generated files to "take a side, regenerate"

Source: October 2026 study of 48 jj problem occasions across 30 agent sessions, mostly in deckmaste.rs (a Rust/Lean repo using jj-kata). Episode IDs (epNNN) refer to that study.

The slowest clears were generated files:

- ep014 (25m): `Facts.lean` and `Declared.lean` cleared only by rerunning the
  generators, which ran past the 600s tool timeout and took ~20 min of polling.
- ep016 (45m): `Facts.lean` regeneration hit the timeout (exit 143) and was
  rerun in the background; `Declared.lean` was then stale too.
- ep026 (12m): both regenerated; full verification ~40 min.
- ep047: after clearing, `Declared.lean` was stale and failed the macros check.

`references/conflicts.md` only says `auto` "leaves generated files untouched",
with no next step.

Done when harmony has a generated-file branch: take one side for the path
(`jj resolve --tool :ours PATH` or equivalent), rerun the generator in the
background or with a long timeout, never hand-merge its markers; and it says
that which files are generated, and how to rebuild them, belongs in the
consuming repo's CLAUDE.md/AGENTS.md.
