"""Per-consumer hook state kept inside a workspace's `.jj/jj-sensei/`.

Antigravity cannot add model-visible context from `PreToolUse` without denying,
nor from `PostToolUse` at all. Both hooks therefore leave text in pending files
that the next `PreInvocation` of the status hook delivers. The status line and
the guard's warnings use separate files, so the status hook rewriting its line
never clobbers a warning the guard deferred a moment earlier.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

STATUS_PENDING = "status-pending"
WARNINGS_PENDING = "warnings-pending"


def consumer_token(payload: dict) -> str:
    """Key dedupe state by agent when the host names one, else by session.

    Claude Code subagents share their parent's `session_id`; keying by session
    alone let the parent's cached line silence every subagent.
    """
    session = str(payload.get("session_id") or payload.get("conversationId") or "nosession")
    agent = payload.get("agent_id")
    key = f"{session}\0agent:{agent}" if agent else session
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def is_antigravity(payload: dict) -> bool:
    return bool(
        payload.get("conversationId") and (payload.get("toolCall") or "invocationNum" in payload)
    )


def jj_workspace(start: Path) -> Path | None:
    for candidate in (start, *start.parents):
        if (candidate / ".jj").is_dir():
            return candidate
    return None


def state_directory(workspace: Path) -> Path:
    return workspace / ".jj" / "jj-sensei"


def pending_path(workspace: Path, kind: str, token: str) -> Path:
    return state_directory(workspace) / f"{kind}.{token}"


def defer_warning(workspace: Path, token: str, text: str) -> None:
    """Queue `text` for the next PreInvocation, keeping anything already queued."""
    path = pending_path(workspace, WARNINGS_PENDING, token)
    queued = read(path) or ""
    if text in queued.split("\n\n"):
        return
    atomic_write(path, f"{queued}\n\n{text}" if queued else text)


def take_pending(workspace: Path, token: str) -> str | None:
    """Remove and return everything queued for this consumer, warnings first."""
    parts = []
    for kind in (WARNINGS_PENDING, STATUS_PENDING):
        path = pending_path(workspace, kind, token)
        value = read(path)
        if value is not None:
            path.unlink(missing_ok=True)
            if value:
                parts.append(value)
    return "\n\n".join(parts) if parts else None


def read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def atomic_write(path: Path, value: str) -> None:
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
