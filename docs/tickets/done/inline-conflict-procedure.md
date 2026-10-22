# Put the minimum conflict procedure in harmony's SKILL.md

Source: October 2026 study of 48 jj problem occasions across 30 agent sessions, mostly in deckmaste.rs (a Rust/Lean repo using jj-kata). Episode IDs (epNNN) refer to that study.

Harmony's documented route was followed on 10 occasions and skipped on 31 (7
unclear). The usual pattern: the agent reads SKILL.md's routing table and never
loads `references/conflicts.md`. Typical cases:

- ep008, ep011, ep014: harmony loaded, then every hunk resolved by Python string
  splicing or a heredoc; no conflicts reference, no `repair`/`resolve` helper.
- ep016, ep026: kata's refresh output pointed at harmony and the agent never
  loaded it.
- ep021, ep022: `repair` run straight from the plugin scripts, no skill load.
- 19 of 48 occasions were later rounds in sessions that had loaded harmony
  earlier; agents re-entered mid-procedure rather than re-reading it.

Causes in SKILL.md:

- The route row "One conflict with known intended content" and §3's "several
  conflicts → run `repair`" overlap, so an agent can reasonably skip the
  reference altogether.

Done when:

- SKILL.md carries the minimum conflict procedure inline (where the conflict
  lives, how to edit or accept, verify `conflicts()` empty), and
  `references/conflicts.md` keeps only edge cases.
- §2 and §3 no longer give two competing entry points for conflicts.
- wisdom's output-token row for `(conflict)` / markers lands on that procedure.
