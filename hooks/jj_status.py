#!/usr/bin/env python3
"""Inject compact jj status at session orientation and after mutating tools."""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import sys
import tempfile
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

from jj_sensei.status import render_status  # noqa: E402


def _consumer_token(payload: dict) -> str:
    """Key dedupe state by agent when the host names one, else by session.

    Claude Code subagents share their parent's `session_id`; keying by session
    alone let the parent's cached line silence every subagent.
    """
    session = str(payload.get("session_id") or payload.get("conversationId") or "nosession")
    agent = payload.get("agent_id")
    key = f"{session}\0agent:{agent}" if agent else session
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def main() -> int:
    antigravity = False
    try:
        payload = json.load(sys.stdin)
        antigravity = bool(
            payload.get("conversationId")
            and (payload.get("toolCall") or "invocationNum" in payload)
        )
        event = _event(payload)
        if event not in {"SessionStart", "PostToolUse", "PreInvocation"}:
            return _empty(antigravity)

        cwd = _cwd(payload)
        if cwd is None or _jj_workspace(cwd) is None:
            return _empty(antigravity)

        token = _consumer_token(payload)
        at_start = event == "SessionStart"

        # Antigravity cannot inject context from PostToolUse. Deliver the line
        # saved by that event on the following PreInvocation instead.
        if event == "PreInvocation":
            pending = _find_pending(cwd, token)
            if pending is not None:
                line = pending.read_text(encoding="utf-8")
                pending.unlink(missing_ok=True)
                return _emit_antigravity(line)
            if payload.get("invocationNum") != 0:
                return _empty(True)
            at_start = True

        status = render_status(cwd)
        if status is None:
            return _empty(antigravity)

        # Every file here lives in this workspace's `.jj`, so the consumer key
        # is (workspace, agent-or-session).
        directory = status.root / ".jj" / "jj-sensei"
        cache = directory / f"status.{token}"
        pending = directory / f"status-pending.{token}"
        seen = directory / f"alarms.{token}"

        # A NEW-divergence alarm is shown once to each consumer that has not
        # seen it, whoever's hook call first detected it.
        acknowledged = _read_lines(seen)
        unseen = [alarm for alarm in status.alarms if alarm.id not in acknowledged]
        live = {alarm.id for alarm in status.alarms}
        if set(acknowledged) != live:
            _atomic_write(seen, "".join(f"{alarm}\n" for alarm in sorted(live)))

        # A warning about this workspace's own state repeats until it clears;
        # everything else, standing repo-wide warnings included, is shown once
        # per consumer and again whenever the line changes.
        if not at_start and not unseen and not status.repeat and _read(cache) == status.line:
            return _empty(antigravity)
        _atomic_write(cache, status.line)
        text = "\n".join([*(alarm.line for alarm in unseen), status.line])

        if at_start:
            _sweep(directory)

        if event == "SessionStart":
            print(text)
        elif antigravity:
            if event == "PreInvocation":
                return _emit_antigravity(text)
            _atomic_write(pending, text)
            print("{}")
        else:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                            "additionalContext": text,
                        }
                    }
                )
            )
    # A context probe must never block a turn or session start. The renderer's
    # known operational failures are already normalized; this final boundary
    # also contains programmer errors until tests can expose and fix them.
    except Exception:  # noqa: BLE001
        return _empty(antigravity)
    return 0


def _event(payload: dict) -> str:
    if payload.get("hook_event_name"):
        return str(payload["hook_event_name"])
    if payload.get("toolCall"):
        return "PostToolUse"
    if "invocationNum" in payload:
        return "PreInvocation"
    return ""


def _cwd(payload: dict) -> Path | None:
    tool_call = payload.get("toolCall") or {}
    arguments = tool_call.get("args") or {}
    mounted = (payload.get("workspacePaths") or [""])[0]
    value = payload.get("cwd") or arguments.get("Cwd")
    if not value:
        target = arguments.get("TargetFile")
        if target:
            path = Path(target)
            if not path.is_absolute():
                path = Path(mounted) / path
            value = path.parent
        else:
            value = mounted
    if not value:
        return None
    path = Path(value).resolve()
    if not path.is_dir():
        return None
    command = (payload.get("tool_input") or {}).get("command") or arguments.get("CommandLine")
    moved = _leading_cd(command, path) if isinstance(command, str) else None
    return moved or path


def _leading_cd(command: str, base: Path) -> Path | None:
    """The directory a leading `cd DIR &&` or `cd DIR;` moved the command into.

    Agents whose shell resets to the project root prefix every command with
    `cd <workspace> && ...`; the payload's cwd then names the wrong workspace.
    Only a jj workspace counts, and only a literal path: anything the shell
    would still have to expand, other than a leading `~`, is ignored.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = [next(lexer, None) for _ in range(3)]
    except ValueError:
        return None
    if tokens[0] != "cd" or tokens[1] is None or tokens[2] not in {"&&", ";"}:
        return None
    target = tokens[1]
    if not target or target.startswith("-") or any(c in target for c in "$`*?["):
        return None
    if target.startswith("~") and command.lstrip()[2:].lstrip().startswith("~"):
        target = os.path.expanduser(target)
    path = (base / target).resolve()
    if not path.is_dir() or _jj_workspace(path) is None:
        return None
    return path


def _jj_workspace(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".jj").is_dir():
            return candidate
    return None


def _find_pending(cwd: Path, token: str) -> Path | None:
    workspace = _jj_workspace(cwd)
    if workspace is None:
        return None
    candidate = workspace / ".jj" / "jj-sensei" / f"status-pending.{token}"
    return candidate if candidate.is_file() else None


def _read_lines(path: Path) -> list[str]:
    value = _read(path)
    return value.splitlines() if value else []


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f"{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _sweep(directory: Path) -> None:
    cutoff = time.time() - 7 * 24 * 60 * 60
    for pattern in ("status.*", "status-pending.*", "alarms.*"):
        for path in directory.glob(pattern):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except FileNotFoundError:
                pass


def _empty(antigravity: bool) -> int:
    if antigravity:
        print("{}")
    return 0


def _emit_antigravity(line: str) -> int:
    print(json.dumps({"injectSteps": [{"ephemeralMessage": line}]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
