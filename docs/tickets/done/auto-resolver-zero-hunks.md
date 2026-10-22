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

## Findings

### Why `auto` resolved nothing

`auto` had one strategy: merge two pure additions into a sorted run of three or
more lines. It declined every hunk in which either side changed or deleted a
line ("removal present", or "removal present (snapshot side)"), which is almost
every real conflict. It declined appends to unsorted text with "no sorted run
at insertion point" or "sorted run too short". Each reason named the guard that
failed, not the shape of the hunk, so agents learned nothing from it.

### Hunks and shapes

17 hunks were recoverable from the excerpts. The generated `Facts.lean` and
`Declared.lean` hunks (ep021, ep022) were not shown, and ep035 `radio.py` was
cut off partway. Each shape is minimised in `tests/fixtures/conflict-shapes/`
as `NAME.conflict`. A `NAME.resolved` file beside it means `auto` must produce
exactly that file; without one, `auto` must leave the file untouched.

| Shape (fixture) | Hunks | Old verdict | Safe to merge mechanically? | `auto` now |
|---|---|---|---|---|
| `adjacent-line-edits`: one side edits line N, the other line N+1, line for line | ep020 Phrase 1/3 and 3/3, ep031 2/2 | removal present | Yes. Each base line is changed by one side, nothing is inserted, and base order fixes the result | resolved |
| `adjacent-deletions`: each side deletes different, touching lines | ep035 `test_radio.py` | removal present | Yes (result is empty) | resolved |
| `adjacent-block-replacements`: each side replaces its own neighbouring line with several | ep021 Abilities 1/3, ep035 `radio.py` (shape only) | removal present | No: each side's extra lines are insertions beside the other's change | left |
| `insertion-beside-edited-line`: one side inserts a line, the other edits the neighbouring line | ep017 `macro_def.rs`, ep021 Abilities 2/3, ep031 1/2 | removal present (snapshot side) / removal present | No. Each agent's result was the plain composition, but no textual test separates these from the failures below | left |
| `edit-then-append`: one side edits a line, the other appends after it | ep017 `declarations.rs` | removal present | No, for the same reason | left |
| `insertion-beside-replaced-line`: one side appends after a line the other replaced with unrelated text | ep022 `expansions.rs` | not shown | No. The insertion's neighbour is gone (the other side moved it) | left |
| `replace-and-insert-beside-deletion`, `inverted-condition-beside-insertion`, `same-line-added-twice` (from review, not episodes) | — | — | No. They merge to a log line about a call that is gone, a privileged call under a negated condition, and a double `release()` | left |
| `same-line-edits`: both sides edit one line | ep005, ep021 Abilities 3/3 | removal present | No. This needs a merge within the line | left |
| `reflow-overlap`: looks adjacent, but one side reflowed both lines | ep020 Phrase 2/3 | removal present | No | left |
| `competing-rewrites`: both sides rewrote the same prose | ep020 `amplify.ron` | removal present | No | left |
| `competing-values`: both sides changed one number | ep047 `spelling_templates.rs` | removal present | No. The agent's `66 + 208` adds both deltas to the base (201 +6 +1); it is not an error | left |
| `modify-delete`: one side edits lines the other deleted | ep047 `keyword_abilities.rs` | removal present | No. The ruling retired the function, so the agent kept the deletion | left |
| `same-point-additions`: both sides append at one point of unsorted text | ep027, ep047 decisions doc, ep022 `Proofs.lean`, ep035 `types.py` | no sorted run / sorted run too short | No; the order is a choice. `stack-snap-first` would have produced the agents' result in ep027, ep047 and ep022 (upstream side first). ep035 used `stack` plus two blank separator lines | left, with an `accept stack` hint |
| `generated-header`, `generated-header-below-conflict` | ep021/ep022 `Facts.lean`, `Declared.lean` | not shown | Never merge them; regenerate | left |
| `three-sided`, `no-newline` (real jj output) | — | — | No: a three-way merge, and a merge that would add a final newline neither side has | left |

The episode hunks were replayed through the final `auto`. 4 of the 17 now
resolve (ep020 Phrase 1/3 and 3/3, ep031 2/2, ep035 `test_radio.py`), each
matching what the agent wrote by hand. No episode clears without a manual
edit. A first version also merged an insertion beside an in-place edit (9 of
17), guarded by token similarity. Review found it merged the inverted
condition and the comment beside flipped arguments, and the replace-plus-insert
and double-`release()` cases bypassed the guard altogether, so that version was
dropped.

### What changed

- `conflicts auto` and `repair` try a second strategy, `disjoint-merge`, after
  `sorted-merge`. Each side is re-diffed against the base. The two sides
  compose only when all of these hold:
  - No base line is changed by both sides; an identical edit on both sides is
    made once.
  - No point receives insertions from both sides, and no insertion lands
    inside the other side's change.
  - Two edits that touch are both line-for-line rewrites (n lines become n)
    or pure deletions. A replace that grows (n lines become more) hides an
    insertion and is treated as one; a replace that shrinks is also declined.
  - Neither side writes a line the other also writes, except through one
    shared identical edit.
  - The alignment is unique: the base region repeats no line, and no side adds
    a copy of a base line.
  - The conflict is two-sided, in jj's diff+snapshot style, and does not end
    in a missing final newline.
- Every merged hunk is listed as `FILE:FIRST-LAST (strategy)` with an
  instruction to inspect it. `repair` records each one with its change ID and
  repeats the list when it stops for manual resolution and when it finishes.
- Decline messages give the disjoint reason, then the sorted-merge reason,
  then an `accept stack`/`stack-snap-first` hint when both sides are pure
  additions.
- Generated files are refused by name (now also `go.work.sum`,
  `.terraform.lock.hcl`, `gradle.lockfile`, `packages.lock.json`,
  `Package.resolved`, `*.min.js`, `*.min.css`). They are also refused when the
  first 10 lines of the base or either side, read without markers, contain
  `@generated`, `DO NOT EDIT`, `auto-generated` or `automatically generated`.
  deckmaste.rs's `Facts.lean`/`Declared.lean` probably carry no such header,
  so the `generated-file-conflicts` ticket should let a repo declare its
  generated paths.
- `accept FILE sort` still applies only the sorted-list merge.
- `references/conflicts.md`: the resolver paragraph names the two shapes and
  says merged hunks are listed for review.

### For `per-hunk-accept`

- Every visible manual resolution was an inline `python3 - <<EOF` script. Each
  one found `<<<<<<< conflict N of M` … `>>>>>>> conflict N of M ends` by
  `str.index` or regex and spliced a literal string into the file. Four
  patterns appeared:
  1. Take one side for one hunk: ep047 `keyword_abilities.rs`, and the
     generated files. ep021 wrote a reusable `takeplus.py` for these.
  2. Concatenate both sides in a chosen order (`stack`/`stack-snap-first`):
     ep027, ep047, ep022 `Proofs.lean`, and ep035 `types.py` with a separator.
  3. A hand-written replacement for each hunk, applied in hunk order from a
     `res=[...]` list, asserting the count: ep020, ep021, ep005.
  4. One side plus a one-token edit: ep017 `declarations.rs`.
- Agents re-implemented `accept` by stripping `+`/` ` prefixes from the `%%%`
  section (ep027, ep035, ep047). Single-hunk files (ep027) could already have
  used whole-file `accept`. The decline message never pointed to it.
- "snapshot" and "diff" are not stable roles. In ep017 the `+++` side was the
  rebase destination in one file and the rebased revision in the other. A
  per-hunk command should accept the header roles (`destination` /
  `rebased`) or print them beside each hunk number. Otherwise "take mine"
  silently picks different sides in different hunks.
- Address hunks by the `N` in `conflict N of M`. The remaining markers keep
  their numbers after a splice, but a stale `show` can still point at the
  wrong text. Let `replace` take content from a file or stdin, and check that
  the hunk's text matches what `show` printed (for example, a short hash).
- The decision agents most often had to make by hand is which side's
  additions come first. They chose the upstream side (the rebase destination)
  first.
