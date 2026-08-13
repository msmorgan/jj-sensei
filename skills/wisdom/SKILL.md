---
name: wisdom
description: Route a Jujutsu history-shaping request to focused guidance or a guarded technique. Use when asked to move a fix into an earlier commit, split or reorder work, undo or revert something, recover lost content, publish or land work with bookmarks and tags, verify repository state compactly, or when jj refuses an operation as immutable.
---

# Apply Jujutsu Wisdom

Match what the user actually asked for, then read only that reference. Resolve
helper paths from this loaded `SKILL.md`, not from the repository being edited.

## Route by the request

- **“Put this fix in that earlier commit.” “Split this into separate
  commits.” “Clean up the working copy.”** Read
  [Tidy the working copy into the right commits](references/tidy.md) for
  `absorb`, explicit `squash`, the repeated-split recipe, fileset syntax, and
  which rebase flag selects what.
- **“Undo that.” “Take that change back out.” “I lost some work.”** Read
  [Undo without operation-log surgery](references/undoing.md) for the choice
  among `restore`, `abandon`, `revert`, evolog, and the read-only operation
  log — and for what to do when jj refuses a target as immutable.
- **“Push this.” “Land it on main.” “Tag the release.” “Get it up for
  review.”** Read [Publish and land work](references/shipping.md) for
  bookmark placement, pushing and auto-tracking, the fetch-and-track
  lifecycle, and the tag limitation.
- **“Move that commit before this one.” “Reorder these.” “Put it on that
  branch point.” “Move this whole subtree.”** Read
  [Place changes deliberately](references/placement.md) for `-A`/`-B`/`-o`,
  naming one exact graph edge, and choosing which half of a split moves.
- **“Find what introduced this.” “Rebuild all of that into a proper
  series.”** Read [Reconstruct work with evolog](references/using-evolog.md)
  to recover the ordered edits inside an oversized `@` and choose coherent
  commit boundaries. For per-line attribution, `jj --no-pager file annotate
  PATH` answers directly.
- **“Check whether…” “Verify that…” “Which revisions/paths…”** — any moment
  that calls for reading state rather than changing it. Read
  [Use templates without guessing](references/templates.md) for small,
  composable, tested idioms that answer in one line instead of a full patch.
- **“Make the earlier commit contain a state that isn't just a subset of the
  files.”** — for example, generated output must be recreated at that state.
  Read [Interpolate a change](references/interpolate.md) for the guarded
  escape hatch; use ordinary `jj split` whenever selection is sufficient.

## Helpers

```bash
"<skill-dir>/scripts/why-immutable" REVSET [REVSET ...]
```

`why-immutable` reports, for each selected revision, whether it is immutable
and which clause of the active `immutable_heads()` definition captures it,
together with the bookmark or tag anchoring that clause. It is read-only.
Run it before proposing a rebase, split, or placement against a named target,
and run it again when jj refuses one.

```bash
"<skill-dir>/scripts/interpolate"
```

`interpolate` is the guarded escape hatch described above. Read
[Interpolate a change](references/interpolate.md) before running it.

If no listed request matches, do not improvise a multi-step rewrite from this
skill. Use `knowledge` to read the version-matched jj manual, then choose
normal jj commands or pause for the missing judgment.
