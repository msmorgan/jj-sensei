# Read jj conflict markers

jj materializes a recorded conflict into the working copy as marker blocks.
The default `ui.conflict-marker-style` is `diff`, which the `conflicts`
helper supports. Read the grammar before hand-editing a block.

## The diff+snapshot grammar

```text
<<<<<<< conflict 1 of 1
%%%%%%% diff from: vpxusssl 38d49363 "merge base"
\\\\\\\        to: rtsqusxu 2768b0b9 "commit A"
 apple
-grape
+grapefruit
 orange
+++++++ ysrnknol 7a20f389 "commit B"
APPLE
GRAPE
ORANGE
>>>>>>> conflict 1 of 1 ends
```

- `<<<<<<<` opens a conflict and `>>>>>>>` closes it. Both are numbered, so a
  file with several conflicts is unambiguous.
- `+++++++` opens the *snapshot*: one side reproduced in full.
- `%%%%%%%` opens a *diff* to apply to that snapshot, labelled with the
  from/to revisions it runs between.
- `\\\\\\\` is purely cosmetic: it exists only so the diff label's `to:` half
  can occupy its own line.

Resolving means applying every diff to the snapshot, then deleting the whole
block including its markers. Here the diff changes `grape` to `grapefruit`
against the uppercased snapshot, giving `APPLE` / `GRAPEFRUIT` / `ORANGE`.

Order inside the block isn't fixed: a diff section may precede the snapshot.
Read the marker that opens each section rather than assume its position.

## More than two sides

Conflicts are usually two-sided, but jj can record arbitrarily many sides —
from merging three or more commits at once. Such a block still holds exactly
one snapshot section, gaining one `%%%%%%%` diff section per additional side;
apply each diff to the snapshot in turn.

## Long markers

When file content could be mistaken for a marker — a line beginning
`=======`, for example — jj lengthens every marker in that file's blocks past
the ambiguous run:

```text
<<<<<<<<<<<<<<< conflict 1 of 1
%%%%%%%%%%%%%%% diff from: wqvuxsty cb9217d5 "merge base"
\\\\\\\\\\\\\\\        to: kwntsput 0e15b770 "commit A"
-Heading
+HEADING
 =======
+++++++++++++++ mpnwrytz 52020ed6 "commit B"
New Heading
===========
>>>>>>>>>>>>>>> conflict 1 of 1 ends
```

Match markers by their leading run of repeated characters, not an exact
seven-character literal, and preserve the length when editing a block.

## Missing terminating newline

Markers must occupy their own line, so a conflict term lacking a final
newline is annotated `(no terminating newline)` on its section label and
given one extra newline; the closing `>>>>>>>` marker compensates by omitting
its own terminating newline:

```text
<<<<<<< conflict 1 of 1
+++++++ tlwwkqxk d121763d "commit A" (no terminating newline)
grapefruit
%%%%%%% diff from: qwpqssno fe561d93 "merge base" (no terminating newline)
\\\\\\\        to: poxkmrxy c735fe02 "commit B"
 grape
+
>>>>>>> conflict 1 of 1 ends
```

The trailing blank line inside the diff is the added newline, not content.
Decide deliberately whether the resolution should end with one.

## Modify/delete conflicts

When one side deletes a file and the other edits it, `jj resolve --list`
reports `2-sided conflict including 1 deletion`; the block renders the
deletion as a diff removing every line:

```text
<<<<<<< conflict 1 of 1
%%%%%%% diff from: ytmvmyyy ee23e74e "init" (parents of rebased revision)
\\\\\\\        to: orulktnq 8207e393 "delete doomed" (rebase destination)
-line one
-line two
+++++++ pkxqrpwv 8ebe4d35 "edit doomed" (rebased revision)
line one
line two EDITED
>>>>>>> conflict 1 of 1 ends
```

Keeping the file is ordinary: write the wanted content and the conflict
clears. **Deleting it is the case that misleads** — all three plausible moves
were tested:

| Move | Verified result |
|---|---|
| Empty the marker block (leave a zero-byte file) | Conflict clears, but the path stays **tracked as an empty file** — `jj diff --summary` still shows `A doomed.txt` |
| `conflicts accept PATH diff` | Reports `accepted diff side`, and produces the **same zero-byte tracked file** — not a deletion, despite `diff` being the deleting side |
| `rm PATH` | The only one that resolves it **as a deletion**: the path leaves the tree and the change becomes empty against its parent |

So delete the file with `rm` for the intended deletion, then let the next jj
command snapshot it. Confirm via `jj --no-pager diff --summary` — an
unexpected `A <path>` means an empty file was committed, not a removal.
`conflicts accept PATH snapshot` keeps the edited content instead, the other
genuine option.

## Alternative marker styles

`ui.conflict-marker-style` also accepts `snapshot` — every side and the base
reproduced in full via `+++++++`/`-------` labels, no diffs — and `git`,
which emits Git's diff3 markers (`<<<<<<<`, `|||||||`, `=======`, `>>>>>>>`).
`git` supports only two sides, falling back to `snapshot` markers for more. A
merge tool can override the style for itself via
`merge-tools.TOOL.conflict-marker-style`.

The `conflicts` helper reads the default `diff` style. If a repository has
configured another style, inspect the markers directly and don't assume the
helper's section names apply.
