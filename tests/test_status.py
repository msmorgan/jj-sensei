from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from jj_sensei.jj import Jj
from jj_sensei.status import render_status

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "jj_status.py"


def _run_hook(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def test_status_reports_empty_and_dirty_working_copy(jj_repo):
    clean = render_status(jj_repo.root)
    assert clean is not None
    assert clean.line.startswith("jj: default | @ ")
    assert clean.line.endswith("(empty)")

    jj_repo.write(jj_repo.root, "new.txt", "one\ntwo\nthree\n")
    dirty = render_status(jj_repo.root)
    assert dirty is not None
    assert "(no desc) +3/-0 (+1/~0/-0)" in dirty.line

    jj_repo.run(jj_repo.root, "describe", "-m", "add new.txt")
    described = render_status(jj_repo.root)
    assert described is not None
    assert '"add new.txt"' in described.line


def test_status_warns_when_a_bookmark_points_at_the_working_copy(jj_repo):
    jj_repo.run(jj_repo.root, "bookmark", "create", "shared", "-r", "@")

    status = render_status(jj_repo.root)

    assert status is not None
    assert "⚠ bookmark 'shared' on @" in status.line


def test_status_reports_conflicted_ancestry(jj_repo):
    jj_repo.write(jj_repo.root, "f.txt", "left\n")
    jj_repo.commit(jj_repo.root, "left")
    left_change_id = Jj(jj_repo.root).one_commit("@-").change_id

    jj_repo.run(jj_repo.root, "new", "@--", "-m", "right")
    jj_repo.write(jj_repo.root, "f.txt", "right\n")
    jj_repo.run(jj_repo.root, "st")
    jj_repo.run(jj_repo.root, "rebase", "-r", left_change_id, "-d", "@")
    jj_repo.run(jj_repo.root, "edit", left_change_id)

    status = render_status(jj_repo.root)

    assert status is not None
    assert "⚠ 1 conflicted" in status.line


def test_status_reports_stale_workspace_without_repairing_it(jj_repo):
    feature = jj_repo.add_workspace("feature")
    jj_repo.write(jj_repo.root, "trunk.txt", "moved\n")
    jj_repo.commit(jj_repo.root, "move trunk")
    jj_repo.run(jj_repo.root, "rebase", "-r", "feature@", "-d", "default@-")
    jj_repo.write(feature, "precious.txt", "keep me\n")

    status = render_status(feature)

    assert status is not None
    assert status.line == (
        "jj: feature | ⚠ STALE working copy — use harmony before trusting anything here"
    )
    still_stale = jj_repo.run(feature, "st", check=False)
    assert still_stale.returncode != 0
    assert "stale" in still_stale.stderr.lower()


def test_post_tool_hook_snapshots_and_suppresses_identical_context(jj_repo):
    jj_repo.write(jj_repo.root, "new.txt", "one\n")
    payload = {
        "hook_event_name": "PostToolUse",
        "cwd": str(jj_repo.root),
        "session_id": "session-one",
        "tool_name": "Write",
    }

    first = _run_hook(payload)
    assert first.returncode == 0
    context = json.loads(first.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "(no desc) +1/-0" in context

    repeated = _run_hook(payload)
    assert repeated.returncode == 0
    assert repeated.stdout == ""

    jj_repo.write(jj_repo.root, "new.txt", "one\ntwo\n")
    changed = _run_hook(payload)
    context = json.loads(changed.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "(no desc) +2/-0" in context


def test_session_start_always_emits_a_bare_status_line(jj_repo):
    payload = {
        "hook_event_name": "SessionStart",
        "cwd": str(jj_repo.root),
        "session_id": "resumed",
    }

    first = _run_hook(payload)
    second = _run_hook(payload)

    assert first.returncode == second.returncode == 0
    assert first.stdout.startswith("jj: default | @ ")
    assert second.stdout == first.stdout
    assert "hookSpecificOutput" not in first.stdout


def test_session_start_sweeps_only_old_status_caches(jj_repo):
    directory = jj_repo.root / ".jj" / "jj-sensei"
    directory.mkdir(parents=True, exist_ok=True)
    ancient = directory / "status.ancient"
    ancient.write_text("old")
    old = time.time() - 30 * 24 * 60 * 60
    os.utime(ancient, (old, old))

    result = _run_hook(
        {
            "hook_event_name": "SessionStart",
            "cwd": str(jj_repo.root),
            "session_id": "live",
        }
    )

    assert result.returncode == 0
    assert not ancient.exists()
    assert list(directory.glob("status.*"))


def test_antigravity_defers_post_tool_context_until_pre_invocation(jj_repo):
    jj_repo.write(jj_repo.root, "new.txt", "one\n")
    post = {
        "conversationId": "agy-session",
        "workspacePaths": [str(jj_repo.root)],
        "toolCall": {
            "name": "write_to_file",
            "args": {"TargetFile": str(jj_repo.root / "new.txt")},
        },
    }

    acknowledged = _run_hook(post)
    assert acknowledged.returncode == 0
    assert json.loads(acknowledged.stdout) == {}

    invocation = {
        "conversationId": "agy-session",
        "workspacePaths": [str(jj_repo.root)],
        "invocationNum": 1,
    }
    delivered = _run_hook(invocation)
    message = json.loads(delivered.stdout)["injectSteps"][0]["ephemeralMessage"]
    assert message.startswith("jj: default | @ ")


def test_status_hook_is_silent_and_successful_outside_jj(tmp_path):
    claude = _run_hook(
        {
            "hook_event_name": "PostToolUse",
            "cwd": str(tmp_path),
            "session_id": "outside",
        }
    )
    antigravity = _run_hook(
        {
            "conversationId": "outside",
            "workspacePaths": [str(tmp_path)],
            "toolCall": {"name": "run_command", "args": {"Cwd": str(tmp_path)}},
        }
    )

    assert claude.returncode == antigravity.returncode == 0
    assert claude.stdout == ""
    assert json.loads(antigravity.stdout) == {}


def test_status_hook_never_blocks_on_invalid_input():
    result = subprocess.run(
        [str(HOOK)],
        input="not json",
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_status_cache_is_inside_dot_jj_and_hook_is_executable(jj_repo):
    result = _run_hook(
        {
            "hook_event_name": "PostToolUse",
            "cwd": str(jj_repo.root),
            "session_id": "cache-location",
        }
    )

    assert result.returncode == 0
    assert list((jj_repo.root / ".jj" / "jj-sensei").glob("status.*"))
    assert os.access(HOOK, os.X_OK)


def test_status_hook_manifest_registration():
    shared = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    expected = 'python3 "${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}/hooks/jj_status.py"'

    assert [hook["command"] for group in shared["PostToolUse"] for hook in group["hooks"]] == [
        expected
    ]
    assert shared["PostToolUse"][0]["matcher"].split("|") == [
        "Bash",
        "Edit",
        "Write",
        "run_command",
        "write_to_file",
        "replace_file_content",
        "multi_replace_file_content",
    ]
    assert expected in [
        hook["command"] for group in shared["SessionStart"] for hook in group["hooks"]
    ]

    antigravity = json.loads((ROOT / "hooks.json").read_text())["jj-sensei-status"]
    assert set(antigravity) == {"PostToolUse", "PreInvocation"}
    assert all(
        entry["command"] == "python3 ./hooks/jj_status.py"
        for event in antigravity.values()
        for group in event
        for entry in group.get("hooks", [group])
    )


def test_status_hook_manifest_handles_plugin_root_with_spaces(jj_repo, tmp_path):
    installed = tmp_path / "plugin cache" / "jj-sensei"
    (installed / "hooks").mkdir(parents=True)
    shutil.copy2(HOOK, installed / "hooks" / HOOK.name)
    shutil.copytree(ROOT / "src", installed / "src")
    manifest = json.loads((ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    command = manifest["PostToolUse"][0]["hooks"][0]["command"]
    environment = {
        name: value
        for name, value in os.environ.items()
        if name not in {"PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT"}
    }
    environment["CLAUDE_PLUGIN_ROOT"] = str(installed)

    result = subprocess.run(
        ["bash", "-c", command],
        input=json.dumps(
            {
                "hook_event_name": "PostToolUse",
                "cwd": str(jj_repo.root),
                "session_id": "spaced-plugin-root",
            }
        ),
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"].startswith(
        "jj: default | @ "
    )
