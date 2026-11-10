#!/usr/bin/env python3
"""PreToolUse guard: deny jj mutations naming a hidden commit; warn on unchecked ones."""

from __future__ import annotations

import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "src"))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        if isinstance(payload, dict) and payload.get("toolCall") and payload.get("conversationId"):
            _antigravity(payload)
        else:
            _claude(payload)
    # A guard must never break a tool call it cannot judge: any failure allows.
    # On Antigravity a non-zero exit fails the tool call, so exit 0 always.
    except Exception:  # noqa: BLE001
        return 0
    return 0


def _claude(payload: dict) -> None:
    """Claude Code and Codex: snake_case payload, `hookSpecificOutput` reply."""
    from jj_sensei.guard import evaluate

    if payload.get("hook_event_name") != "PreToolUse":
        return
    if payload.get("tool_name") not in {"Bash", None}:
        return
    command = (payload.get("tool_input") or {}).get("command")
    cwd = payload.get("cwd")
    if not isinstance(command, str) or not cwd:
        return
    verdict = evaluate(command, Path(cwd))
    if verdict is None:
        return
    output: dict[str, object] = {"hookEventName": "PreToolUse"}
    if verdict.deny:
        output["permissionDecision"] = "deny"
        output["permissionDecisionReason"] = verdict.message
    else:
        # No permissionDecision: an "allow" would skip the user's permission
        # prompt. Context alone leaves the host's normal flow in charge.
        output["additionalContext"] = verdict.message
    print(json.dumps({"hookSpecificOutput": output}))


def _antigravity(payload: dict) -> None:
    """Antigravity: camelCase payload, `decision` reply.

    Empty stdout is the only neutral reply: it leaves Antigravity's permission
    flow exactly as if no hook ran. `{}` is read as a deny with no reason, and
    the decision values are documented inconsistently ("allow" is described
    both as auto-approving and as deferring), so the guard never prints one
    unless it denies. A reason is shown to the model only with a deny, so a
    warning goes to the status hook's pending queue for the next invocation.
    """
    from jj_sensei.guard import evaluate
    from jj_sensei.hookstate import consumer_token, defer_warning, jj_workspace

    if payload.get("hookEventName", "PreToolUse") != "PreToolUse":
        return
    tool_call = payload["toolCall"]
    if tool_call.get("name") != "run_command":
        return
    arguments = tool_call.get("args") or {}
    command = arguments.get("CommandLine")
    # `cwd` is where the agent's commands run by default; `Cwd` overrides it.
    agent_cwd = payload.get("cwd") or (payload.get("workspacePaths") or [""])[0]
    cwd = arguments.get("Cwd") or agent_cwd
    if not isinstance(command, str) or not cwd:
        return
    verdict = evaluate(command, Path(cwd))
    if verdict is None:
        return
    if verdict.deny:
        print(json.dumps({"decision": "deny", "reason": verdict.message}))
        return
    # Queue under the workspace the next PreInvocation resolves: it sees only
    # the agent's own directory, never this command's.
    workspace = jj_workspace(Path(agent_cwd).resolve()) if agent_cwd else None
    if workspace is not None:
        defer_warning(workspace, consumer_token(payload), verdict.message)


if __name__ == "__main__":
    raise SystemExit(main())
