# Read jj conflict markers

jj materializes a recorded conflict into the working copy as marker blocks.
The default `ui.conflict-marker-style` is `diff`, and the `conflicts` helper
supports that style. Read the grammar before editing a block by hand.

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
  revision it runs from and the revision it runs to.
- `\\\\\\\` carries nothing semantic. It exists only so the `to:` half of the
  diff label can occupy its own line.

Resolving means producing the content that results from applying every diff to
the snapshot, then deleting the whole block including its markers. In the
example, the diff changes `grape` to `grapefruit` and the snapshot is the
uppercased side, so the resolution is `APPLE` / `GRAPEFRUIT` / `ORANGE`.

Order inside the block is not fixed: a diff section may precede the snapshot.
Read the marker that opens each section rather than assuming a position.

## More than two sides

Conflicts are usually two-sided, but jj records conflicts with arbitrarily
many sides, which arises when three or more commits are merged at once. Such a
block still holds exactly one snapshot section and gains one `%%%%%%%` diff
section per additional side. Apply each diff to the snapshot in turn.

## Long markers

When file content could itself be mistaken for a marker — a line beginning
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

Match markers by their leading run of repeated characters, never by an exact
seven-character literal, and preserve the length when editing a block.

## Missing terminating newline

Markers must occupy their own line, so a conflict term whose content lacks a
final newline is annotated `(no terminating newline)` on its section label and
given one extra newline. To compensate, the closing `>>>>>>>` marker itself is
written without a terminating newline:

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

The trailing blank line inside the diff is the newline being added, not
content. Decide deliberately whether the resolution ends with a newline.

## Modify/delete conflicts

When one side deletes a file and the other edits it, `jj resolve --list`
reports `2-sided conflict including 1 deletion` and the block renders the
deletion as a diff that removes every line:

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

Keeping the file is ordinary: write the content you want and the conflict
clears. **Deleting it is the case that misleads**, and all three plausible
moves were tested:

| Move | Verified result |
|---|---|
| Empty the marker block (leave a zero-byte file) | Conflict clears, but the path stays **tracked as an empty file** — `jj diff --summary` still shows `A doomed.txt` |
| `conflicts accept PATH diff` | Reports `accepted diff side`, and produces the **same zero-byte tracked file** — not a deletion, despite `diff` being the deleting side |
| `rm PATH` | The only one that resolves it **as a deletion**: the path leaves the tree and the change becomes empty against its parent |

So delete the file from the working copy with `rm` when the deletion is the
intended resolution, then let the next jj command snapshot it. Confirm with
`jj --no-pager diff --summary` — an unexpected `A <path>` means an empty file
was committed instead of a removal. `conflicts accept PATH snapshot` keeps the
edited content, which is the other genuine option.

## Alternative marker styles

`ui.conflict-marker-style` also accepts `snapshot`, which reproduces every side
and the base in full using `+++++++` and `-------` labels and no diffs, and
`git`, which emits Git's diff3 markers (`<<<<<<<`, `|||||||`, `=======`,
`>>>>>>>`). The `git` style supports two sides only and falls back to
`snapshot` markers for a conflict with more. A merge tool can override the
style for itself through `merge-tools.TOOL.conflict-marker-style`.

The `conflicts` helper reads the default `diff` style. If a repository has
configured another style, inspect the markers directly and do not assume the
helper's section names apply.
