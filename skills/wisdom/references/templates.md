# Use templates without guessing

Use jj's template language to request the smallest view that answers the
question. Templates format objects; revsets and filesets still select the
revisions and paths.

Do not invent template syntax. If an idiom below is insufficient, load the
`knowledge` skill and query the installed reference with `rtfm templates
--search TERM` or `rtfd docs/templates --section HEADING`. Use `--full` only
when the complete language reference is genuinely needed.

## Prefer the simplest sufficient view

Use `builtin_log_oneline` for ordinary graph inspection. Use `jj diff
--summary` or `jj diff --stat` to learn a change's scope before requesting its
patch. A template is useful when several facts belong on each log row, a list
needs transforming, or output must be machine-readable. An unscoped `jj show
--git` is not a discovery tool for an unknown or potentially large change.

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

Useful building blocks include `if`, `coalesce`, `++`, `.map()`, `.filter()`,
`.join()`, and `json()`. Their names describe intent, but their accepted types
and exact method forms remain version-specific; consult the installed template
reference rather than extrapolating from an example.
