# Use templates without guessing

Use jj's template language to request the smallest view that answers the
question. Templates format objects; revsets and filesets still select the
revisions and paths.

Do not invent template syntax. If an idiom below is insufficient, load
`knowledge` and query the installed reference with `rtfm templates --search
TERM` or `rtfd docs/templates --section HEADING`. Use `--full` only when the
complete reference is genuinely needed.

## Select before you format

A template cannot narrow *which* revisions are shown; `-r` does that. Most
"which change …" questions are answered by the revset alone, with
`builtin_log_oneline` as the whole format:

| Predicate | Selects |
|---|---|
| `author(pattern)`, `mine()` | by author name or email; `mine()` is the current user |
| `description(pattern)` | by description text |
| `files(fileset)` | commits that modified matching paths |
| `conflicts()` | commits with files in a conflicted state |
| `empty()` | commits modifying no files |
| `merges()` | merge commits |
| `divergent()` | commits sharing a change ID with another |
| `::x` / `x::` | ancestors / descendants of `x`, `x` included |
| `x..y` | ancestors of `y` that are not ancestors of `x` |
| `x::y` | descendants of `x` that are also ancestors of `y` |
| `x & y`, `x ~ y`, `x \| y` | and, minus, or — `&` and `~` bind equally and parse left to right, `\|` weaker |

String patterns default to **`glob:`**, which is why `description("timeout")`
matches nothing: there are no wildcards in it. Say what is meant —
`substring:"timeout"`, `glob:"*timeout*"`, `exact:"…"`, or `regex:"…"`, each
with an optional `-i` suffix for case-insensitivity.

A compound example, verified: which of my nonempty changes touched a path and
mention a term?

```bash
jj --no-pager log -r 'mine() & ~empty() & files("src/parser.rs") & description(substring:"timeout")' -T builtin_log_oneline
```

Build these up one clause at a time and check the count as you go; a revset
that silently selects nothing looks identical to one that found nothing. For
a predicate not listed above, use the same lookup with `rtfm revsets --search
TERM` rather than guessing at a function name.

## Prefer the simplest sufficient view

Use `builtin_log_oneline` for ordinary graph inspection, and `jj diff
--summary` or `jj diff --stat` to learn a change's scope before requesting
its patch. A template earns its keep when several facts belong on each log
row, a list needs transforming, or output must be machine-readable. An
unscoped `jj show --git` is not a discovery tool for an unknown or
potentially large change.

Start a custom template against one revision, then widen the revset after its
shape is correct:

```bash
jj --no-pager log -r CHANGE --no-graph \
  -T 'change_id.short() ++ " " ++ description.first_line() ++ "\n"'
```

## Compose known idioms

Zero-argument `Commit` methods are available as keywords. Use `self` when an
explicit receiver makes a method chain clearer.

Show useful state without printing a patch:

```bash
jj --no-pager log -r REVSET --no-graph \
  -T 'change_id.short() ++ if(empty, " empty") ++ if(conflict, " conflict") ++ if(immutable, " immutable") ++ "\n"'
```

Show changed paths or a bounded stat for each selected change:

```bash
jj --no-pager log -r CHANGE --no-graph -T 'self.diff().summary()'
jj --no-pager log -r CHANGE --no-graph -T 'self.diff().stat()'
```

`diff()` alone is parsed as a global function call and fails. Use the explicit
method `self.diff()` or the zero-argument keyword `diff`.

Transform a list with `map`, then join the results:

```bash
jj --no-pager log -r REVSET --no-graph \
  -T 'parents.map(|p| p.change_id().short()).join(", ") ++ "\n"'
```

The same pattern exposes exactly which paths changed:

```bash
jj --no-pager log -r CHANGE --no-graph \
  -T 'self.diff().files().map(|e| e.status_char() ++ " " ++ e.display_diff_path()).join("\n") ++ "\n"'
```

Serialize values instead of hand-escaping machine-readable output:

```bash
jj --no-pager log -r CHANGE --no-graph \
  -T 'json(self.diff().files().map(|e| e.display_diff_path())) ++ "\n"'
```

Useful building blocks: `if`, `coalesce`, `++`, `.map()`, `.filter()`,
`.join()`, `json()`. Names describe intent, but accepted types and exact
method forms are version-specific — consult the installed reference rather
than extrapolating from an example.
