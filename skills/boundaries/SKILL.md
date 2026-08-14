---
name: boundaries
description: Install or audit jj-sensei's repository-level immutable_heads configuration for safe multi-workspace isolation. Use when asked to set up, initialize, upgrade, verify, or troubleshoot jj-sensei workspace protection.
---

# Set Up jj Workspace Isolation

Run this skill from the repository's `default` workspace. Resolve the helper
path from this loaded `SKILL.md`, not from the target repository:

```bash
"<skill-dir>/scripts/setup-immutability"
```

The helper exits `0` on successful verification, `70` after an internal
error, `75` when another transaction holds the lock, and `80` when the
workspace or topology needs human judgment. Present a `70` or `80` diagnosis
rather than improvising a recovery command — these statuses are the
helper's own; ordinary jj syntax and option errors do not invoke this
protocol.

The helper installs four readable repository revset aliases:

```toml
[revset-aliases]
"other_workspaces()" = "working_copies() ~ @"
"not_default()" = "@ ~ default@"
"only_if(condition, revisions)" = "revisions & descendants(ancestors(condition))"
"immutable_heads()" = "builtin_immutable_heads() | only_if(not_default(), other_workspaces())"
```

`only_if` exploits that the ancestors of any nonempty revset include
`root()`, whose descendants are `all()` — so it returns `revisions` when
`condition` is nonempty and `none()` otherwise. `not_default()` is nonempty
only outside the `default` workspace.

In `default`, the custom term collapses to `none()`, leaving only jj's
built-in immutable heads and letting the coordinator rewrite feature stacks.
Elsewhere, every other live working-copy commit becomes an immutable head,
protecting it and its ancestors — a guardrail, not complete isolation:
unrelated mutable changes outside another working copy's ancestry stay
writable.

jj treats `::(immutable_heads() | root())` as immutable. Read the active
definition and every alias behind it:

```bash
jj --no-pager config get "revset-aliases.'immutable_heads()'"
jj --no-pager config get revset-aliases
```

To find out why one particular revision is protected — which clause captures
it and which bookmark or tag anchors that clause — use the `wisdom` skill's
read-only `why-immutable` helper.

The helper verifies that the custom term collapses in `default`, then audits
active workspaces for shared feature-only ancestry. Treat an overlap report
as a safe stop — the guard is working, but later rewrites can be
unexpectedly blocked. Never bypass the guard; ask the user how the live
stacks should be restructured.

A workspace listing that cannot resolve one workspace's root means an
orphaned registration — the workspace is still recorded but its directory
is gone. The helper reports the name and jj's own diagnosis and stops for
human judgment. `jj workspace forget <name>` clears it, but that's the
user's call: a missing directory can equally be an unmounted volume, and
workspace lifecycle is not an agent decision. Report it and ask.

To audit without changing configuration:

```bash
"<skill-dir>/scripts/setup-immutability" --check
```

## Workspace lifecycle

```bash
jj --no-pager workspace list
jj --no-pager workspace root
jj --no-pager workspace add ../feature-x --name feature-x -r main -m "feature-x workspace"
jj --no-pager workspace forget feature-x
```

Workspaces are live pointers to a mutable change in one shared repo, unlike
Git worktrees: every working copy shares the revision graph, bookmarks, and
operation log. Each is addressable in revsets as `<name>@` (e.g. `default@`).

`workspace add` creates the directory and gives it a working-copy commit;
`-r` names that commit's parents, and with no `-r` the new workspace shares
the current workspace's parents. Base new workspaces on default-owned
history — `main`, `trunk()`, or another revision the `default` workspace
owns — never on another live workspace's `@` or on mutable feature-only
ancestry shared with it. That choice decides whether the two can later
rewrite their own stacks, and it cannot be fixed afterwards without moving
work. If one workspace head becomes an ancestor of another anyway, the
ancestor workspace's own `@` becomes immutable through ancestor closure, even
though it is not itself returned by `immutable_heads()`.

`workspace forget` unregisters a workspace without touching its directory,
which can be deleted before or after — it is the resolution for the
orphaned registrations this helper reports, and as above it stays a
human-confirmed step, not an agent's call.
