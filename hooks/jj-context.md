**This is a jj (Jujutsu) repo — use `jj`, never `git`.** Refer to changes by change ID (stable across rewrites), not commit hash. No staging area: the working copy is itself a commit (`@`) and file edits auto-amend it whenever jj snapshots. Always put global `--no-pager` immediately after `jj`, always request Git format with `--git` when output will be diff-shaped, and always pass `-m` when a command could open a description editor (`describe/commit/squash/split`). On `jj squash`, `-u` (`--use-destination-message`) is the non-interactive alternative when the destination's existing description should be kept.

| One Git happy path | One jj happy path | Caveat |
|---|---|---|
| `git status` | `jj --no-pager st` | Shows `@`, parents, changed paths, and conflicts. There is no `git add`: any command snapshots all unignored edits. |
| `git diff HEAD` | `jj --no-pager diff --git` | Diffs `@` against its merged parent tree. |
| `git log --oneline --graph -5` | `jj --no-pager log -r ::@ -n 5 -T builtin_log_oneline` | Revset ancestry; change IDs survive rewrites. |
| `git blame src/parser.rs` | `jj --no-pager file annotate src/parser.rs` | Names the source change of each line. `qpvuntsm` below is an example change ID, not a hash. |
| `git rm --cached src/generated.rs` | `jj --no-pager file untrack src/generated.rs` | The path must already match an ignore pattern. |
| `git add -A && git commit -m "Fix parser"` | `jj --no-pager commit -m "Fix parser"` | Describes `@`, then creates a fresh empty child. |
| `git commit --amend -m "Fix parser"` | `jj --no-pager squash -m "Fix parser"` | Folds `@` into `@-`; `-m` sets the **destination's** description. The emptied `@` becomes a fresh empty change with a new ID. |
| `git commit --fixup && git rebase --autosquash` | `jj --no-pager absorb` | Moves each working-copy hunk into the mutable ancestor that last touched those lines; ambiguous hunks stay put. `jj --no-pager squash --from @ --into qpvuntsm FILESET` for explicit control. |
| `git stash` / `git stash pop` | `jj --no-pager new main -m "urgent fix"`, later `jj --no-pager edit qpvuntsm` | **Nothing to stash:** the WIP change stays put as a sibling; return by editing it. |
| `git restore --source=HEAD -- src/parser.rs` | `jj --no-pager restore src/parser.rs` | Restores from the merged parent tree; no index. |
| `git revert abc123` | `jj --no-pager revert -r abc123 -A @` | Requires one of `-o`/`-A`/`-B`; no default placement. A conflict from later edits to adjacent lines is recorded and normal, not a failure. |
| `git switch -c fix-parser main` | `jj --no-pager new main -m "Fix parser"` | Creates and edits a child; creates no bookmark. |
| `git switch fix-parser` | `jj --no-pager edit qpvuntsm` | Edits a change, not a checked-out branch; descendants rebase. |
| `git rebase main` | `jj --no-pager rebase -r 'main..@' -A main` | Preview the revset first; the selection depends on the intended stack. |
| `git fetch origin` | `jj --no-pager git fetch --remote origin` | Updates remote bookmarks; no active-branch pull. `[updated] untracked` means the local bookmark did **not** move — run `jj --no-pager bookmark track <name>@<remote>` before rebasing onto it. |
| `git push -u origin feature` | `jj --no-pager bookmark create feature -r @-` then `jj --no-pager git push -b feature` | Point the bookmark at the last **described** change, not an empty `@`. Pushing a new bookmark auto-tracks its remote counterpart. |
| `git tag v1.0.0` | `jj --no-pager tag set v1.0.0 -r main` | **This jj cannot push tags:** `jj git push` is bookmark-only. Publishing a tag is an external step to surface, never to work around. |

**Bookmarks are named pointers to revisions.** They stay attached when their revision is rewritten, do not advance when a child is created, and are never checked out. Do not infer that a bookmark should move because work began from it; create, move, or delete one only when the user, task, or workflow calls for it.

**Empty, undescribed working-copy changes are normal.** They are usually auto-pruned when you switch away. Ignore them.

**Rebasing is surgical and never pauses at conflicts;** they are recorded in the resulting commits. Prefer `-r <revset>`, previewing a nontrivial one first. For insertion or reordering use `-A <target>` (`--after`) and/or `-B <target>` (`--before`): each alone anchors the opposite endpoint to the target's current neighbors, both are no-ops when the relationship already holds, and together they name one exact edge. `-o <dest>` (`--onto`; `-d` is its alias) makes the selection a direct child while the destination's descendants stay put—an intentional fork—or, repeated, a merge. `-s <root>` has distinct source semantics; with no `-b`/`-s`/`-r`, a bare `jj rebase` defaults to `-b @`.

**Inspect in widening steps; stop at the one that answers the question.** Identity and shape: `jj --no-pager log -r '<revset>' -T builtin_log_oneline`. Volume: `diff --stat`, or `--summary` for changed paths. Content, scoped: `diff --git <paths>`. Read a full `show --git <rev>` only when the complete patch is required; unscoped, it is not a discovery tool.

**Git interop and colocation.** `.jj/` and `.git/` share one working copy; jj synchronizes commits and refs automatically, and bookmarks correspond to local and remote Git branches (e.g. `main@origin`). `jj git push` rejects empty descriptions, so describe first, and preflight a nonobvious push with `--dry-run`.

**Workspaces are live pointers to a mutable change in one shared repo,** not independent Git worktrees: every working copy shares the revision graph, bookmarks, and operation log. List them with `jj --no-pager workspace list`; each is addressable in revsets as `<name>@` (e.g. `default@`).

**Mutability is decided by `immutable_heads()`.** jj treats `::(immutable_heads() | root())` as immutable and refuses to rewrite it; by default that is `trunk() | tags() | untracked_remote_bookmarks()`. A repository may extend it—for example to protect other live workspaces' heads—so read the active definition rather than assuming: `jj --no-pager config get "revset-aliases.'immutable_heads()'"`. Load `boundaries` for the alias mechanics and workspace topology.

**The following operations and escape hatches are always strictly forbidden:**
- **Never perform operation-log surgery:** `jj undo`, `jj redo`, and `jj op abandon/integrate/restore/revert` modify shared operation history across all workspaces and are reserved for the user. *Reading* it is permitted and often useful: `jj --no-pager op log`, `op show <op>`, and `--at-op <op>` with a read-only command are allowed diagnostics.
- **Never bypass immutability guards:** A refusal almost always means the request *as understood* would rewrite published history. Report which revision was refused and why in one or two sentences, then ask. Do not reinterpret the request, do not search diffs for another revision resembling the target, and never use `--ignore-immutable` or `--config`/`--config-file` to get around the guard. Before proposing a rebase, split, or placement against a named target, check its mutability first: `jj --no-pager log -r '<target>' --no-graph -T 'immutable'`, or `wisdom`'s `why-immutable` helper for the clause and anchor.
- **Never retarget other workspaces with `-R`:** Do not pass `-R <path>` or `--repository <path>` to target another workspace's directory. Work from the directory of the workspace you are operating in.
- **Never run mutating `git` commands:** In a colocated repository, run all version control operations through `jj`, never `git`.
- **Never propose an exception to these rules:** when a rule blocks the request, state the limitation and stop.

**Four skills are available; load the one that matches.** `knowledge` — any jj command or behavior not covered above, or whose correct form is uncertain: read the installed version-matched manual before acting; never infer from Git. `wisdom` — a history-shaping request: move a fix into an earlier commit, split, reorder, place at an exact edge, undo, revert, publish, land, or check state compactly. `harmony` — conflicts, stale workspaces, divergent successors, or content to recover from a snapshot. `boundaries` — multi-workspace immutability setup and audit.
