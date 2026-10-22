---
needs: [auto-resolver-zero-hunks]
---
# Add per-hunk accept/replace to the conflicts helper

Source: October 2026 study of 48 jj problem occasions across 30 agent sessions, mostly in deckmaste.rs (a Rust/Lean repo using jj-kata). Episode IDs (epNNN) refer to that study.

Agents wrote their own Python edits in 21 resolutions (e.g. ep017, ep020,
ep021, ep022, ep047: "resolved hunks with ad hoc python scripts rather than the
Edit tool"). `conflicts accept FILE SIDE` only works on a whole file, so
agents splice hunks themselves, with errors: ep047 deleted both sides of a hunk
outright and set a count matching neither side.

Done when the helper can pick a side for one hunk, or replace one hunk's
content from a file, with tests; shaped by what `auto-resolver-zero-hunks`
records about the hunks.
