**This is a jj (Jujutsu) repo — use `jj`, never `git`.** Refer to changes by change ID (stable across rewrites), not commit hash. No staging area: the working copy is itself a commit (`@`) and file edits auto-amend it whenever jj snapshots. Always put global `--no-pager` immediately after `jj`, always request Git format with `--git` when output will be diff-shaped, and always pass `-m` when a command could open a description editor (`describe/commit/squash/split`).

| One Git happy path | One jj happy path | Caveat |
|---|---|---|
| `git status` | `jj --no-pager st` | Shows `@`, parents, changed paths, and conflicts. |
| `git diff HEAD` | `jj --no-pager diff --git` | Diffs `@` against its merged parent tree. |
| `git log --oneline --graph -5` | `jj --no-pager log -r ::@ -n 5 -T builtin_log_oneline` | Revset ancestry; change IDs survive rewrites. |
| `git show HEAD` | `jj --no-pager show --git qpvuntsm` | `qpvuntsm` is an example change ID, not a commit hash. |
| `git add -A` | `jj --no-pager st` | **No exact equivalent:** ordinary commands snapshot all unignored edits. |
| `git add -A && git commit -m "Fix parser"` | `jj --no-pager commit -m "Fix parser"` | Describes `@`, then creates a fresh empty child. |
| `git commit --amend -m "Fix parser"` | `jj --no-pager squash -m "Fix parser"` | Single-parent `@`; folds into `@-` and leaves a fresh `@`. |
| `git restore --source=HEAD -- src/parser.rs` | `jj --no-pager restore src/parser.rs` | Restores from the merged parent tree; no index. |
| `git switch -c fix-parser main` | `jj --no-pager new main -m "Fix parser"` | Creates and edits a child; creates no bookmark. |
| `git switch fix-parser` | `jj --no-pager edit qpvuntsm` | Edits a change, not a checked-out branch; descendants rebase. |
| `git rebase main` | `jj --no-pager rebase -s qpvuntsm -o main` | Moves that change and descendants; conflicts stay recorded. |
| `git fetch origin` | `jj --no-pager git fetch --remote origin` | Updates remote bookmarks; does not perform an active-branch pull. |

**Bookmarks are named pointers to revisions.** They remain attached when the revision they point to is rewritten, but they do not advance when a new child is created. There is no active or checked-out bookmark. Do not infer that a bookmark should move merely because work began from it. Create, move, or delete bookmarks only when the user, task, or repository workflow calls for it.

**Empty, undescribed working-copy changes are normal.** These changes are usually auto-pruned when you switch away. Ignore them; to tidy only mutable anonymous heads that belong to no workspace: `jj --no-pager abandon -r '(empty() & description(exact:"") & mutable() & visible_heads()) ~ working_copies() ~ bookmarks()'`.

**Rebasing is surgical, predictable, and does not pause at conflicts.** Rebasing never pauses for merge conflicts; conflicts are recorded directly in the resulting commits. Use `-d <dest>` (or `-o <dest>`) to relocate the fork point of revisions specified by `-r <revset>` (or `-s <root>` for a full subtree). Use `-B <target>` (`--before`) and/or `-A <target>` (`--after`) to insert a change before or after a target revision (this is a no-op if the change is already positioned appropriately relative to the target). When used together, `-A` and `-B` can locate a specific edge for inserting revisions.

**Git interop and colocation.** In a colocated repository, `.jj/` and `.git/` share the same working copy, and `jj` automatically synchronizes commits and refs with Git. Bookmarks correspond directly to local and remote Git branches (e.g. `main@origin`). Git can represent empty commits, but `jj git push` rejects empty descriptions by default. Describe changes before pushing; abandon temporary empty WIP litter with `jj --no-pager abandon`.

**Workspaces are live pointers to a mutable change in one shared repo.** Workspaces are not independent Git worktrees; all working copies share the underlying revision graph, bookmarks, and operation log. Active workspaces can be inspected using the `working_copies()` revset or `jj --no-pager workspace list`, and each workspace is addressable in revsets via its `<workspace_name>@` alias (e.g. `default@`).

**Mutability and workspace isolation are handled by `immutable_heads()`.** Jujutsu treats `::(immutable_heads() | root())` as immutable. By default, `immutable_heads()` is `trunk() | tags() | untracked_remote_bookmarks()`; `trunk()` is a repository-specific alias commonly initialized from a `main`, `master`, or `trunk` bookmark on the default remote, `upstream`, or `origin`. A repository may extend it with readable conditional aliases:

```toml
[revset-aliases]
"other_workspaces()" = "working_copies() ~ @"
"not_default()" = "@ ~ default@"
"only_if(condition, revisions)" = "revisions & descendants(ancestors(condition))"
"immutable_heads()" = "builtin_immutable_heads() | only_if(not_default(), other_workspaces())"
```

The ancestors of any nonempty `condition` include `root()`, whose descendants are `all()`, so `only_if` returns `revisions` when its condition is nonempty and `none()` otherwise. In `default`, `not_default()` is empty and only built-in immutable heads remain, leaving the coordinator able to rewrite feature stacks. Elsewhere, every other working-copy commit becomes an immutable head, protecting it and its ancestors. This is a guardrail rather than complete isolation: unrelated mutable changes outside another working copy's ancestry remain writable. Inspect the active definition with `jj --no-pager config get "revset-aliases.'immutable_heads()'"` or all aliases with `jj --no-pager config get revset-aliases`.

**Keep live non-default workspaces independent.** Do not run `jj new <other-live-feature>@`, or base a workspace on mutable feature-only ancestry shared with another live workspace. The guard fails safely: shared history becomes immutable from both workspaces; if one working-copy head is an ancestor of another, the ancestor workspace's own `@` becomes immutable through ancestor closure. Base independent work on default-owned history. If this topology produces an immutability error, stop and report it—never reach for an escape hatch.

**The following operations and escape hatches are always strictly forbidden:**
- **Never perform operation-log surgery:** Commands like `jj --no-pager undo`, `jj --no-pager redo`, or `jj --no-pager op abandon/integrate/restore/revert` modify shared operation history across all workspaces and are strictly reserved for the user.
- **Never bypass immutability guards:** If `jj` reports that a commit is immutable, you are targeting the wrong revision. Never use `--ignore-immutable` or bypass guards using `--config` / `--config-file` flags.
- **Never retarget other workspaces with `-R`:** Do not pass `-R <path>` or `--repository <path>` to target another workspace's directory. Always ensure you are in the correct directory for the workspace you are operating in.
- **Never run mutating `git` commands:** In a colocated repository, run all version control operations through `jj`, never `git`.

**If an operation you need is not explicitly covered above, or its correct form is uncertain, load the `knowledge` skill and query the installed jj documentation before acting. Do not infer jj behavior from Git.**
