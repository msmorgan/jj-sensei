---
needs: [auto-resolver-zero-hunks]
---
# Add per-hunk accept/replace to the conflicts helper

Agents wrote their own Python edits in 21 resolutions, which suggests
`conflicts accept FILE SIDE` (whole-file only) is missing a primitive.
Add hunk-level selection: pick a side for one hunk, or write replacement text
for one hunk from a file. Shape it with what the zero-hunk investigation finds.
