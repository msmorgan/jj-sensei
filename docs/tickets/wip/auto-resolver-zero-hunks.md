# Find out why `conflicts auto` resolved 0 hunks in 9 conflicts

Source: October 2026 study of 48 jj problem occasions across 30 agent sessions, mostly in deckmaste.rs (a Rust/Lean repo using jj-kata). Episode IDs (epNNN) refer to that study.

Every time the helper's conservative auto-resolution ran on a file conflict
it resolved nothing; agents resolved all of them by hand (mostly with ad hoc
Python edits). Median conflict size was 18 lines.

| Episode | Files | Hunks | Lines |
|---|---|---|---|
| ep005 | lean/Semantics/Phrase.lean (deriving list) | 1 | 3 |
| ep017 | macro_def.rs, declarations.rs | 2 | 17 |
| ep020 | Check/Phrase.lean, amplify.ron | 4 | 25 |
| ep021 | Check/Abilities.lean, Facts.lean, Declared.lean (last two generated) | 8 | ? |
| ep022 | expansions.rs, Facts.lean (generated), Proofs.lean | 4 | ? |
| ep027 | docs/decisions/semantics-v2.md | 1 | 69 |
| ep031 | Check/Abilities.lean | 2 | 8 |
| ep035 | radio.py, types.py, test_radio.py (adjacent-line edits) | 3 | 311* |
| ep047 | semantics-v2.md, two Rust test files | 3 | 85 |

*derived from conflict-header line ranges, not counted.

Several were described as "adjacent-line" clashes (ep008, ep035), which is the
shape most likely to be mechanically mergeable.

Done when:

- Representative hunk shapes are captured as test fixtures under
  `tests/fixtures/` (minimised; no need to keep the original project text).
- Each shape is classified: mechanically safe or not, and why `auto` declined.
- Either `auto` is widened for the safe shapes (with tests), or, if none are
  safe, `references/conflicts.md` demotes `auto` to a passing mention.
- Findings are written into this ticket for `per-hunk-accept` to build on.
