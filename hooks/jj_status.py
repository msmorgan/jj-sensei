#!/usr/bin/env python3
"""Inject compact jj status at session orientation and after mutating tools."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

from jj_sensei.status import render_status  # noqa: E402


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

        session = str(payload.get("session_id") or payload.get("conversationId") or "nosession")
        token = hashlib.sha256(session.encode()).hexdigest()[:24]
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

        directory = status.root / ".jj" / "jj-sensei"
        cache = directory / f"status.{token}"
        pending = directory / f"status-pending.{token}"
        if not at_start and _read(cache) == status.line:
            return _empty(antigravity)
        _atomic_write(cache, status.line)

        if at_start:
            _sweep(directory)

        if event == "SessionStart":
            print(status.line)
        elif antigravity:
            if event == "PreInvocation":
                return _emit_antigravity(status.line)
            _atomic_write(pending, status.line)
            print("{}")
        else:
            print(
                json.dumps(
                    {
                        "hookSpecificOutput": {
                            "hookEventName": "PostToolUse",
                            "additionalContext": status.line,
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
    return path if path.is_dir() else None


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
    for pattern in ("status.*", "status-pending.*"):
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
