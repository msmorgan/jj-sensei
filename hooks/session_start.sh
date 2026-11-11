#!/usr/bin/env bash
# PreInvocation / SessionStart hook: inject jj guidance only inside a jj repo.
# Detect the workspace marker without running jj. Even a read-looking jj command
# can synchronize a colocated Git repository and need write access to .git.

payload=""
if [ ! -t 0 ]; then
    payload=$(cat)
fi

# AGY calls PreInvocation before every model invocation, and invocationNum
# restarts at zero on every user prompt, while injected steps persist in the
# conversation. At invocation zero the guide is therefore injected only when the
# conversation transcript (transcriptPath) shows no copy of it since the last
# compaction: the newest CHECKPOINT or preamble EPHEMERAL_MESSAGE decides, so
# copies do not accumulate across turns, and a compaction (whose checkpoint
# replaces the history the model sees) brings the guide back. The transcript
# format is undocumented, so any doubt about it falls back to injecting. Later
# invocations in a turn, and invocations outside a jj workspace, return an empty
# response. Claude's SessionStart payload has no invocationNum.
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
                printf '%s' "$payload" | python3 -c '
import json
from pathlib import Path
import sys


def already_injected(opening):
    # Newest decisive step wins: a preamble copy suppresses, a checkpoint does not.
    try:
        path = json.load(sys.stdin).get("transcriptPath")
        with open(path, encoding="utf-8") as transcript:
            lines = transcript.readlines()
        for line in reversed(lines):
            try:
                step = json.loads(line)
            except ValueError:
                continue
            if not isinstance(step, dict):
                continue
            if step.get("type") == "CHECKPOINT":
                return False
            content = step.get("content")
            if (
                step.get("type") == "EPHEMERAL_MESSAGE"
                and isinstance(content, str)
                and content.lstrip().startswith(opening)
            ):
                return True
    except Exception:
        pass
    return False


context = Path(sys.argv[1]).read_text()
opening = context.lstrip()[:40]
if opening and already_injected(opening):
    print("{}")
else:
    print(json.dumps({"injectSteps": [{"ephemeralMessage": context}]}))
' "$context_file"
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
