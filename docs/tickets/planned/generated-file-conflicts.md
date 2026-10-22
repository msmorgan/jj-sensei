# Route conflicts in generated files to "take a side, regenerate"

The slowest clears were generated files: ep014 (25m), ep016 (45m), ep026 (12m)
on `Facts.lean` / `Declared.lean`. conflicts.md only says `auto` leaves
generated files untouched, and gives no next step.

- Add a branch: take one side (`jj resolve --tool :ours PATH`), rerun the
  generator (background or long timeout; generators ran ~10m and hit the tool
  timeout), never hand-merge markers.
- Which files are generated and how to rebuild them belongs in the consuming
  repo's CLAUDE.md; say so.

Evidence: /tmp/claude-1000/-home-msmorgan-Projects-resume/ec810bb7-3850-4b45-9515-43e60d12bd21/scratchpad/ep_results/
