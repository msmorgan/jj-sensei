# Put the minimum conflict procedure in harmony's SKILL.md

Conflict-occasion study (48 occasions, mostly deckmaste.rs): harmony's
documented route was followed 10 times and skipped 31. Agents read the
routing table and never load `references/conflicts.md`, and later rounds
re-enter with harmony already loaded and go straight to editing.

- The routing row "One conflict with known intended content" and §3's
  "several conflicts → repair" overlap, so an agent can skip the reference.
- Inline ~5 lines in SKILL.md: locate the conflicted change, edit or accept,
  generated-file branch, verify `conflicts()` is empty. Keep conflicts.md
  for edge cases.
- Check wisdom's output-token routing sends `(conflict)` / markers straight
  to that procedure.

Evidence: /tmp/claude-1000/-home-msmorgan-Projects-resume/ec810bb7-3850-4b45-9515-43e60d12bd21/scratchpad/occasions.json
