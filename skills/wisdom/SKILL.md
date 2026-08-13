---
name: wisdom
description: Recognize useful Jujutsu history-shaping idioms and uncommon scenarios, then route to focused guidance or guarded techniques. Use when splitting mixed work, reconstructing an oversized working-copy change from its evolution log, selecting precise revisions with revsets, placing or reordering changes with split/rebase, naming an exact graph edge, or constructing an intermediate state between commits when doing so is not a matter of selecting files and lines.
---

# Apply Jujutsu Wisdom

Match the situation below, then read only its linked reference. Resolve helper
paths from this loaded `SKILL.md`, not from the repository being edited.

- **“I need to construct an intermediate state between two commits, and doing
  so is not a matter of selecting files and lines—for example, generated output
  must be recreated at that state.”** Read
  [Interpolate a change](references/interpolate.md) for the guarded escape
  hatch; use ordinary `jj split` whenever selection is sufficient.
- **“I made far too many changes in `@`, and they should have been a series of
  commits.”** Not all hope is lost. Read
  [Reconstruct work with evolog](references/using-evolog.md) to recover the
  agent's ordered edits and choose coherent commit boundaries.
- **“I want these selected files to become the later change, not the earlier
  one.”** Read [Place changes deliberately](references/placement.md).
- **“I know what this change should be after or before—or exactly which graph
  edge it belongs in—without accidentally creating a fork.”** Read
  [Place changes deliberately](references/placement.md).
- **“I need to move a precise set of revisions or a whole subtree.”** Read
  [Place changes deliberately](references/placement.md).

If no listed scenario matches, do not improvise a multi-step rewrite from this
skill. Use `knowledge` to read the version-matched jj manual, then choose normal
jj commands or pause for the missing judgment.
