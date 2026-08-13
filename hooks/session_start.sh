#!/usr/bin/env bash
# PreInvocation / SessionStart hook: inject jj guidance only inside a jj repo.
# Detect the workspace marker without running jj. Even a read-looking jj command
# can synchronize a colocated Git repository and need write access to .git.

payload=""
if [ ! -t 0 ]; then
    payload=$(cat)
fi

# AGY calls PreInvocation before every model invocation. Its first invocation is
# zero, so later invocations must return an empty response rather than repeatedly
# injecting the startup guide. Claude's SessionStart payload has no invocationNum.
agy_invocation=""
if [ -n "$payload" ]; then
    agy_invocation=$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    value = json.load(sys.stdin).get("invocationNum", "")
    print(value if isinstance(value, int) else "")
except (OSError, ValueError):
    pass
' 2>/dev/null)
fi
if [ -n "$agy_invocation" ] && [ "$agy_invocation" != 0 ]; then
    printf '{}\n'
    exit 0
fi

# Detect the workspace directory from the host payload or PWD.
search_dir=""
if [ -n "$payload" ]; then
    search_dir=$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    paths = data.get("workspacePaths") or []
    print(paths[0] if paths else data.get("cwd", ""))
except (OSError, ValueError):
    pass
' 2>/dev/null)
fi
if [ -z "$search_dir" ] || [ "$search_dir" = "null" ]; then
    search_dir=$(pwd -P) || exit 0
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
context_file="$script_dir/jj-context.md"

while :; do
    if [ -d "$search_dir/.jj" ]; then
        if [ -f "$context_file" ]; then
            if [ -n "$agy_invocation" ]; then
                python3 - "$context_file" <<'PY'
import json
from pathlib import Path
import sys

print(json.dumps({
    "injectSteps": [{"ephemeralMessage": Path(sys.argv[1]).read_text()}]
}))
PY
            else
                cat "$context_file"
            fi
            exit 0
        fi
    fi
    [ "$search_dir" = / ] && break
    search_dir=${search_dir%/*}
    [ -n "$search_dir" ] || search_dir=/
done

if [ -n "$agy_invocation" ]; then
    printf '{}\n'
fi
exit 0
