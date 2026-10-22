# Find out why `conflicts auto` resolved 0 hunks in 9 conflicts

Across all 9 conflicts where the helper ran, it auto-resolved 0 hunks; agents
resolved every one (21 with ad-hoc Python edits, 9 by hand). Median conflict
size was 18 lines.

- Pull the hunks from those 9 runs and classify: was any mechanically safe?
- If none, demote `auto` in conflicts.md to a passing mention.
- If some, widen the resolver for those shapes, with tests.

Evidence: /tmp/claude-1000/-home-msmorgan-Projects-resume/ec810bb7-3850-4b45-9515-43e60d12bd21/scratchpad/ep_results/, /tmp/claude-1000/-home-msmorgan-Projects-resume/ec810bb7-3850-4b45-9515-43e60d12bd21/scratchpad/occasions.json
