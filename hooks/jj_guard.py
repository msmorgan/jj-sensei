#!/usr/bin/env python3
"""PreToolUse guard: deny jj mutations naming a hidden commit; warn on unchecked ones."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

from jj_sensei.guard import evaluate  # noqa: E402


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if payload.get("hook_event_name") != "PreToolUse":
            return 0
        if payload.get("tool_name") not in {"Bash", None}:
            return 0
        command = (payload.get("tool_input") or {}).get("command")
        cwd = payload.get("cwd")
        if not isinstance(command, str) or not cwd:
            return 0
        verdict = evaluate(command, Path(cwd))
        if verdict is None:
            return 0
        output: dict[str, object] = {"hookEventName": "PreToolUse"}
        if verdict.deny:
            output["permissionDecision"] = "deny"
            output["permissionDecisionReason"] = verdict.message
        else:
            # No permissionDecision: an "allow" would skip the user's permission
            # prompt. Context alone leaves the host's normal flow in charge.
            output["additionalContext"] = verdict.message
        print(json.dumps({"hookSpecificOutput": output}))
    # A guard must never break a tool call it cannot judge: any failure allows.
    except Exception:  # noqa: BLE001
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
