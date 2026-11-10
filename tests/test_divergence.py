"""The repo-wide NEW-divergence alarm, warning delivery, and workspace resolution."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from jj_sensei import divergence
from jj_sensei.jj import Jj
from jj_sensei.repair import WorkspaceLock
from jj_sensei.status import render_status

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "jj_status.py"


def _hook(
    cwd: Path,
    *,
    session: str = "session",
    event: str = "PostToolUse",
    env: dict[str, str] | None = None,
    **extra: object,
) -> str:
    """Run the status hook and return the context it injected ("" if none)."""
    payload = {"hook_event_name": event, "cwd": str(cwd), "session_id": session, **extra}
    result = subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    if not result.stdout or event == "SessionStart":
        return result.stdout
    return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]


def _head_op(repo, cwd: Path) -> str:
    return repo.run(
        cwd, "--ignore-working-copy", "op", "log", "--no-graph", "-n1", "-T", "id"
    ).stdout.strip()


def _change(repo, cwd: Path, revset: str) -> str:
    return repo.run(
        cwd, "--ignore-working-copy", "log", "--no-graph", "-r", revset, "-T", "change_id"
    ).stdout.strip()


def _resurrect(repo) -> tuple[str, str]:
    """The baton's `resurrect` reproduction, from an agent's point of view.

    An agent records its base *commit* id, another workspace rewrites the
    line beneath it, and `jj new <old commit id>` brings the hidden commit and
    every hidden ancestor back as divergent twins. Returns the resurrected
    tip's change id and the operation that resurrected it.
    """
    root = repo.root
    for name in ("A", "B", "C"):
        repo.write(root, f"{name.lower()}.txt", f"{name}\n")
        repo.commit(root, name)
    old = repo.run(root, "log", "--no-graph", "-r", "@-", "-T", "commit_id").stdout.strip()
    tip = _change(repo, root, "@-")
    repo.run(root, "describe", "-r", 'description(exact:"A\n")', "-m", "A2")
    repo.run(root, "new", old)
    return tip, _head_op(repo, root)


def _divergent_count(repo) -> int:
    return len(Jj(repo.root).commits(divergence.DIVERGENT_REVSET))


def test_resurrected_hidden_commit_raises_new_divergence_once(jj_repo):
    baseline = _hook(jj_repo.root)
    assert "DIVERGENCE" not in baseline

    tip, op = _resurrect(jj_repo)
    assert _divergent_count(jj_repo) == 6

    alarm = _hook(jj_repo.root)
    first, status = alarm.splitlines()
    assert first.startswith("jj: ⚠ NEW DIVERGENCE — 3 changes gained visible copies (")
    assert f"{tip[:12]} ×2" in first
    assert f"created by op {op[:12]} (new empty commit) in default: jj new " in first
    assert "load jj-sensei harmony; do not build on them" in first
    assert status.startswith("jj: default | @ ")
    assert status.endswith("| ⚠ @ or its ancestors divergent | ⚠ 6 divergent commits repo-wide")

    repeated = _hook(jj_repo.root)
    assert "NEW DIVERGENCE" not in repeated
    # Warnings are never deduplicated: the standing suffix repeats until fixed.
    assert repeated == status


def test_new_divergence_reaches_another_workspace_of_the_same_repo(jj_repo):
    feature = jj_repo.add_workspace("feature")
    _hook(jj_repo.root)
    assert "DIVERGENCE" not in _hook(feature)

    tip, op = _resurrect(jj_repo)
    assert "NEW DIVERGENCE" in _hook(jj_repo.root)

    elsewhere = _hook(feature)
    assert "NEW DIVERGENCE" in elsewhere
    assert tip[:12] in elsewhere
    assert op[:12] in elsewhere
    status = elsewhere.splitlines()[-1]
    assert status.startswith("jj: feature | @ ")
    # feature@ is not built on the twins, so only the repo-wide suffix shows.
    assert "@ or its ancestors divergent" not in status
    assert status.endswith("| ⚠ 6 divergent commits repo-wide")
    assert "NEW DIVERGENCE" not in _hook(feature)


def test_new_divergence_reaches_every_agent_of_one_session(jj_repo):
    _hook(jj_repo.root, agent_id="parent")
    _resurrect(jj_repo)

    for agent in ("agent-a", "agent-b"):
        assert "NEW DIVERGENCE" in _hook(jj_repo.root, agent_id=agent)
        assert "NEW DIVERGENCE" not in _hook(jj_repo.root, agent_id=agent)
    # Without an agent id the session itself is one more consumer.
    assert "NEW DIVERGENCE" in _hook(jj_repo.root)


def test_plain_status_is_delivered_to_each_subagent_of_one_session(jj_repo):
    lines = [_hook(jj_repo.root, agent_id=agent) for agent in ("agent-a", "agent-b")]

    assert lines[0] == lines[1]
    assert lines[0].startswith("jj: default | @ ")
    assert _hook(jj_repo.root, agent_id="agent-a") == ""


def test_first_sight_of_standing_divergence_is_a_baseline_not_new(jj_repo):
    _resurrect(jj_repo)

    first = _hook(jj_repo.root)

    assert "NEW DIVERGENCE" not in first
    assert first.endswith("| ⚠ 6 divergent commits repo-wide")
    shared = jj_repo.root / ".jj" / "repo" / "jj-sensei" / "divergence.json"
    assert json.loads(shared.read_text())["op_id"]


def test_secondary_workspace_state_lives_in_the_shared_repo_dir(jj_repo):
    feature = jj_repo.add_workspace("feature")

    _hook(feature)

    assert (feature / ".jj" / "repo").is_file()
    assert divergence.state_path(feature) == divergence.state_path(jj_repo.root)
    assert divergence.state_path(feature).is_file()


@pytest.mark.parametrize("content", ["", "{not json", '{"version": 1}', '{"version": 99}'])
def test_corrupt_shared_state_is_a_fresh_baseline(jj_repo, content):
    _hook(jj_repo.root)
    shared = divergence.state_path(jj_repo.root)
    shared.write_text(content)
    _resurrect(jj_repo)

    line = _hook(jj_repo.root)

    assert "NEW DIVERGENCE" not in line
    assert line.endswith("| ⚠ 6 divergent commits repo-wide")
    assert json.loads(shared.read_text())["version"] == divergence.STATE_VERSION


def test_divergence_clears_once_the_twins_are_abandoned(jj_repo):
    _hook(jj_repo.root)
    _resurrect(jj_repo)
    _hook(jj_repo.root)

    # The resurrected chain is exactly the divergent part of @'s ancestry.
    jj_repo.run(jj_repo.root, "abandon", "-r", "::@ & divergent()")

    assert _divergent_count(jj_repo) == 0
    assert "⚠" not in _hook(jj_repo.root)


def test_held_workspace_lock_still_reports_divergence(jj_repo):
    _hook(jj_repo.root)
    tip, op = _resurrect(jj_repo)

    with WorkspaceLock(jj_repo.root, timeout=1):
        busy = _hook(jj_repo.root)
        again = _hook(jj_repo.root)

    alarm, status = busy.splitlines()
    assert again == status  # the degraded line repeats; the alarm does not
    assert "NEW DIVERGENCE" in alarm
    assert op[:12] in alarm
    assert status == "jj: default | @ not probed (workspace busy) | ⚠ 6 divergent commits repo-wide"


def test_held_workspace_lock_without_divergence_stays_silent(jj_repo):
    with WorkspaceLock(jj_repo.root, timeout=1):
        assert render_status(jj_repo.root) is None
        assert _hook(jj_repo.root) == ""


def test_update_stale_fork_is_reported_from_both_workspaces(jj_repo):
    """The baton's `update-stale fork`: a stale workspace with on-disk edits.

    `jj workspace update-stale` snapshots the edits at the workspace's old
    operation, and the "reconcile divergent operations" merge then leaves a
    second visible commit of the working-copy change.
    """
    ws2 = jj_repo.root.parent / "ws2"
    jj_repo.run(jj_repo.root, "workspace", "add", str(ws2), "--name", "ws2", "-r", "@-")
    jj_repo.write(ws2, "w.txt", "w\n")
    jj_repo.run(ws2, "describe", "-m", "W")
    change = _change(jj_repo, ws2, "@")
    _hook(jj_repo.root)
    jj_repo.write(ws2, "w.txt", "w\nw2\n")  # never snapshotted
    jj_repo.run(jj_repo.root, "rebase", "-r", "ws2@", "-d", "root()")

    updated = jj_repo.run(ws2, "workspace", "update-stale")
    assert "Concurrent modification" in updated.stderr
    merge = jj_repo.run(
        ws2,
        "--ignore-working-copy",
        "op",
        "log",
        "--no-graph",
        "-T",
        'if(parents.len() > 1, id ++ "\n")',
    ).stdout.split()[0]

    for workspace, name in ((ws2, "ws2"), (jj_repo.root, "default")):
        context = _hook(workspace)
        alarm, status = context.splitlines()
        assert alarm.startswith(f"jj: ⚠ NEW DIVERGENCE — {change[:12]} now has 2 visible copies")
        assert (
            f"created by op {merge[:12]} (reconcile divergent operations) in ws2: "
            "jj workspace update-stale" in alarm
        )
        assert status.startswith(f"jj: {name} | @ ")
        assert status.endswith("⚠ 2 divergent commits repo-wide")
    assert "@ or its ancestors divergent" in _hook(ws2)


def test_stale_warning_repeats_on_every_call(jj_repo):
    feature = jj_repo.add_workspace("feature")
    jj_repo.write(jj_repo.root, "trunk.txt", "moved\n")
    jj_repo.commit(jj_repo.root, "move trunk")
    jj_repo.run(jj_repo.root, "rebase", "-r", "feature@", "-d", "default@-")

    stale = "jj: feature | ⚠ STALE working copy — use harmony before trusting anything here"
    assert _hook(feature) == stale
    assert _hook(feature) == stale
    assert _hook(feature, agent_id="subagent") == stale


def test_alarm_walk_that_misses_the_last_seen_op_blames_nobody(jj_repo, monkeypatch):
    _hook(jj_repo.root)
    _resurrect(jj_repo)
    monkeypatch.setattr(divergence, "WALK_LIMIT", 1)
    jj_repo.run(jj_repo.root, "describe", "-m", "later")

    status = divergence.probe(Jj(jj_repo.root), jj_repo.root)

    assert status is not None
    (alarm,) = status.alarms
    assert "created by an operation jj-sensei could not identify" in alarm.line


def test_probe_is_silent_when_jj_cannot_answer(tmp_path):
    workspace = tmp_path / "fake"
    (workspace / ".jj" / "repo").mkdir(parents=True)

    assert divergence.probe(Jj(workspace), workspace) is None


@pytest.fixture
def two_workspaces(jj_repo):
    feature = jj_repo.add_workspace("feature")
    return jj_repo, feature


@pytest.mark.parametrize(
    "command",
    [
        "cd {feature} && jj st",
        "cd {feature}; jj st",
        "cd {feature}&&jj st",
        "cd '{feature}' && jj st",
        'cd "{feature}" && jj st',
        "  cd ../feature && jj st",
        "cd ~/feature && jj st",
    ],
)
def test_leading_cd_selects_the_workspace_the_command_ran_in(two_workspaces, command):
    repo, feature = two_workspaces
    env = {**repo.env, "HOME": str(feature.parent)}

    context = _hook(
        repo.root,
        tool_name="Bash",
        tool_input={"command": command.format(feature=feature)},
        env=env,
    )

    assert context.startswith("jj: feature | @ ")


@pytest.mark.parametrize(
    "command",
    [
        "cd {outside} && ls",
        "cd {feature}",
        "cd $FEATURE && jj st",
        "cd '~/feature' && jj st",
        "echo cd {feature} && jj st",
        "cd {missing} && jj st",
        'cd "{feature} && jj st',
    ],
)
def test_other_commands_fall_back_to_the_payload_cwd(two_workspaces, tmp_path, command):
    repo, feature = two_workspaces
    outside = tmp_path / "outside"
    outside.mkdir()
    env = {**repo.env, "HOME": str(feature.parent), "FEATURE": str(feature)}

    context = _hook(
        repo.root,
        tool_name="Bash",
        tool_input={
            "command": command.format(
                feature=feature, outside=outside, missing=tmp_path / "missing"
            )
        },
        env=env,
    )

    assert context.startswith("jj: default | @ ")


def test_antigravity_command_line_cd_is_resolved_too(two_workspaces):
    repo, feature = two_workspaces
    payload = {
        "conversationId": "agy",
        "workspacePaths": [str(repo.root)],
        "toolCall": {
            "name": "run_command",
            "args": {"Cwd": str(repo.root), "CommandLine": f"cd {feature} && jj st"},
        },
    }
    subprocess.run(
        [str(HOOK)], input=json.dumps(payload), capture_output=True, text=True, check=True
    )
    delivered = subprocess.run(
        [str(HOOK)],
        input=json.dumps(
            {"conversationId": "agy", "workspacePaths": [str(feature)], "invocationNum": 1}
        ),
        capture_output=True,
        text=True,
        check=True,
    )

    message = json.loads(delivered.stdout)["injectSteps"][0]["ephemeralMessage"]
    assert message.startswith("jj: feature | @ ")


def test_malformed_saved_alarms_are_dropped(jj_repo):
    _hook(jj_repo.root)
    shared = divergence.state_path(jj_repo.root)
    state = json.loads(shared.read_text())
    state["alarms"] = [{"id": "garbage", "line": "x", "created": 4e9}]
    shared.write_text(json.dumps(state))
    _resurrect(jj_repo)

    line = _hook(jj_repo.root)

    assert "NEW DIVERGENCE" in line
    assert "garbage" not in shared.read_text()


def test_repo_wide_divergence_alone_is_deduplicated_per_consumer(jj_repo):
    """A standing count the agent did not cause is news once, not every call."""
    feature = jj_repo.add_workspace("feature")
    _resurrect(jj_repo)
    first = _hook(feature, agent_id="agent-a")
    assert "NEW DIVERGENCE" not in first  # first sight: a baseline
    assert first.endswith("| ⚠ 6 divergent commits repo-wide")

    assert _hook(feature, agent_id="agent-a") == ""
    assert _hook(feature, agent_id="agent-b") == first
    assert _hook(feature, agent_id="agent-b") == ""

    # The tip of the resurrected chain stops being divergent: the line changes.
    jj_repo.run(jj_repo.root, "abandon", "-r", "heads(::@ & divergent())")
    changed = _hook(feature, agent_id="agent-a")
    assert changed.endswith("| ⚠ 4 divergent commits repo-wide")
    assert _hook(feature, agent_id="agent-a") == ""


def test_divergence_under_this_workspace_repeats_every_call(jj_repo):
    _resurrect(jj_repo)

    first = _hook(jj_repo.root)
    assert "⚠ @ or its ancestors divergent" in first
    assert _hook(jj_repo.root) == first


def test_orphaned_workspace_notice_is_deduplicated(jj_repo):
    jj_repo.orphan_workspace("dead")

    first = _hook(jj_repo.root)
    assert "⚠ orphaned workspace 'dead'" in first
    assert _hook(jj_repo.root) == ""


def test_render_status_marks_only_workspace_warnings_for_repetition(jj_repo):
    plain = render_status(jj_repo.root)
    assert plain is not None and not plain.repeat

    jj_repo.run(jj_repo.root, "bookmark", "create", "shared", "-r", "@")
    bookmarked = render_status(jj_repo.root)
    assert bookmarked is not None and "⚠ bookmark" in bookmarked.line
    assert not bookmarked.repeat

    _resurrect(jj_repo)
    divergent = render_status(jj_repo.root)
    assert divergent is not None and divergent.repeat
