---
name: wisdom
description: Recognize useful Jujutsu history-shaping idioms and uncommon scenarios, then route to focused guidance or guarded techniques. Use when splitting mixed work, placing or reordering changes with split/rebase, naming an exact graph edge, or constructing an intermediate content state that ordinary diff selection cannot express.
---

# Apply Jujutsu Wisdom

Match the situation below, then read only its linked reference. Resolve helper
paths from this loaded `SKILL.md`, not from the repository being edited.

- **“I wish I’d made this change as two different changes, but the content is
  all mixed together and/or relies on the output of a tool at a different
  state.”** Read [Interpolate a change](references/interpolate.md).
- **“I want these selected files to become the later change, not the earlier
  one.”** Read [Place changes deliberately](references/placement.md).
- **“I know what this change should be after or before—or exactly which graph
  edge it belongs in.”** Read [Place changes deliberately](references/placement.md).

If no listed scenario matches, do not improvise a multi-step rewrite from this
skill. Use `knowledge` to read the version-matched jj manual, then choose normal
jj commands or pause for the missing judgment.
