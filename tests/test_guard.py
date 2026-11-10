"""The PreToolUse guard against hidden commit ids and stale-workspace snapshots."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from jj_sensei.guard import candidates, find_invocations

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "jj_guard.py"


def run_guard(cwd: Path, command: str, **overrides) -> dict | None:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(cwd),
        "tool_input": {"command": command},
        **overrides,
    }
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else None


def one(command: str, cwd: Path = Path("/work")):
    invocations = find_invocations(command, cwd)
    assert len(invocations) == 1, invocations
    return invocations[0]


# --- tokenizer ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "subcommand", "revisions"),
    [
        ("jj new abc12345", "new", ["abc12345"]),
        ("jj --no-pager new abc12345 -m 'base'", "new", ["abc12345"]),
        ("jj --color=never --no-pager rebase -r @ -o abc12345", "rebase", ["@", "abc12345"]),
        ("jj rebase -r=abc12345 -d main", "rebase", ["abc12345", "main"]),
        ("jj rebase -rabc12345 --onto=main", "rebase", ["abc12345", "main"]),
        ("jj squash --from abc12345 --into @ src/file.rs", "squash", ["abc12345", "@"]),
        ("jj bookmark set feature -r abc12345", "bookmark set", ["abc12345"]),
        ("jj b m feature --to abc12345", "bookmark m", ["abc12345"]),
        ("jj workspace add ../ws -r abc12345", "workspace add", ["abc12345"]),
        ("jj new 'abc12345::|def67890'", "new", ["abc12345::|def67890"]),
        ("jj new abc12345 >/dev/null 2>&1", "new", ["abc12345"]),
        ("jj new abc12345 | tail -1", "new", ["abc12345"]),
        ("FOO=1 timeout 30 jj new abc12345", "new", ["abc12345"]),
        ("/usr/bin/jj new -- abc12345", "new", ["abc12345"]),
    ],
)
def test_revision_arguments_are_found_in_every_spelling(command, subcommand, revisions):
    invocation = one(command)

    assert invocation.subcommand == subcommand
    assert invocation.mutating
    assert invocation.revisions == revisions


def test_messages_paths_and_templates_are_not_revisions():
    invocation = one('jj describe -m "fix deadbeef1234 handling" -r @ && echo done')
    assert invocation.revisions == ["@"]

    # squash/restore positionals are filesets, not revisions.
    assert one("jj restore --from @- deadbeef1234/file.rs").revisions == ["@-"]
    assert one("jj squash -m 'deadbeef1234' cafebabe1234.txt").revisions == []


def test_read_only_subcommands_are_not_mutating():
    for command in (
        "jj log -r abc12345",
        "jj show abc12345",
        "jj diff --git -r abc12345",
        "jj evolog -r abc12345",
        "jj file show -r abc12345 a.txt",
        "jj bookmark list",
    ):
        assert not one(command).mutating, command


def test_every_invocation_in_a_chain_is_found_with_its_directory(tmp_path):
    invocations = find_invocations(
        f"cd {tmp_path}/ws && jj st; cargo test\njj new abc12345 && jj -R ../other abandon def67890",
        tmp_path,
    )

    assert [i.subcommand for i in invocations] == ["st", "new", "abandon"]
    assert invocations[1].directory == tmp_path / "ws"
    assert invocations[2].directory == tmp_path / "ws" / ".." / "other"
    assert invocations[2].revisions == ["def67890"]


def test_shell_c_bodies_are_scanned_but_script_files_are_not():
    assert one("bash -c 'cd /x && jj new abc12345'").revisions == ["abc12345"]
    assert find_invocations("bash ./rebuild-baseline.sh", Path("/work")) == []


def test_variables_are_unexpanded_unless_assigned_literally_in_the_same_command():
    assert one('jj new "$B1"').unexpanded == ["$B1"]
    assert one("jj rebase -r @ -o ${BASE}").unexpanded == ["${BASE}"]
    assert one("jj new $(jj log -r @- -T commit_id)").unexpanded == ["$(jj"]
    assert one("OLD=abc12345; jj new $OLD").revisions == ["abc12345"]
    assert one("OLD=$(jj log -T commit_id); jj new $OLD").unexpanded == ["$OLD"]


@pytest.mark.parametrize(
    ("revision", "expected"),
    [
        ("abc12345", ["abc12345"]),
        ("abc12345::", ["abc12345"]),
        ("abc12345|def67890", ["abc12345", "def67890"]),
        ("heads(::@ & ::abc12345)", ["abc12345"]),
        ("abc1234", []),  # below the 8-character floor
        ("zwpzqlsk", []),  # change ids use k-z
        ("feature_abc12345", []),
        ("onztrtnm/2", ["onztrtnm/2"]),
        ("a" * 41, []),
    ],
)
def test_hex_atoms_are_extracted_from_revsets(revision, expected):
    assert candidates(revision) == expected


def test_unreadable_commands_yield_nothing():
    assert find_invocations("jj new 'unterminated", Path("/work")) == []
    assert find_invocations("cargo test --workspace", Path("/work")) == []


# --- hidden commits (the `resurrect` reproduction) ----------------------------


@pytest.fixture
def resurrect(jj_repo):
    """A captured commit id, then another workspace rewrites the line under it."""
    root = jj_repo.root
    for name in ("a", "b", "c"):
        jj_repo.write(root, name, f"{name}\n")
        jj_repo.commit(root, name.upper())
    old = jj_repo.run(root, "log", "--no-graph", "-r", "@-", "-T", "commit_id").stdout
    change = jj_repo.run(root, "log", "--no-graph", "-r", "@-", "-T", "change_id").stdout
    jj_repo.run(root, "describe", "-r", 'description(exact:"A\n")', "-m", "A2")
    current = jj_repo.run(
        root, "log", "--no-graph", "-r", change, "-T", "commit_id.shortest(12)"
    ).stdout
    return root, old, change, current


def test_guard_denies_a_literal_hidden_commit_id(resurrect):
    root, old, change, current = resurrect

    output = run_guard(root, f"jj --no-pager new {old}")

    assert output["permissionDecision"] == "deny"
    reason = output["permissionDecisionReason"]
    assert f"{old[:12]} is a hidden (rewritten) commit" in reason
    assert f"Its change is {change[:8]}" in reason
    assert f"current version: {current}" in reason


def test_guard_denies_a_hidden_short_id_inside_a_chain_and_revset(resurrect):
    root, old, _, _ = resurrect

    output = run_guard(
        root.parent, f"cd {root} && jj --no-pager rebase -r @ -o '{old[:8]}::' | tail -1"
    )

    assert output["permissionDecision"] == "deny"


def test_guard_allows_the_change_id(resurrect):
    root, _, change, _ = resurrect

    assert run_guard(root, f"jj --no-pager new {change[:8]}") is None


def test_guard_allows_reading_a_hidden_commit(resurrect):
    root, old, _, _ = resurrect

    assert run_guard(root, f"jj --no-pager log -r {old}") is None
    assert run_guard(root, f"jj --no-pager evolog -r {old[:12]}") is None


def test_guard_warns_without_deciding_on_a_shell_variable(resurrect):
    root, _, _, _ = resurrect

    output = run_guard(root, 'jj --no-pager new "$OLD"')

    assert "permissionDecision" not in output
    assert "$OLD" in output["additionalContext"]
    assert "Write the change id or revset inline" in output["additionalContext"]


def test_guard_ignores_visible_and_unknown_hex(resurrect, jj_repo):
    root, _, _, _ = resurrect
    visible = jj_repo.run(root, "log", "--no-graph", "-r", "@-", "-T", "commit_id").stdout

    assert run_guard(root, f"jj --no-pager new {visible}") is None
    assert run_guard(root, "jj --no-pager new deadbeefdeadbeef") is None


# --- stale working copy (the `update-stale fork` reproduction) ----------------


@pytest.fixture
def stale(jj_repo):
    """ws2's `@` is rewritten from the default workspace while ws2 has edits on disk."""
    root = jj_repo.root
    ws2 = root.parent / "ws2"
    jj_repo.run(root, "workspace", "add", str(ws2), "--name", "ws2", "-r", "@-")
    jj_repo.write(ws2, "w", "w\n")
    jj_repo.run(ws2, "describe", "-m", "W")
    jj_repo.write(ws2, "w", "w\nw2\n")
    jj_repo.run(root, "rebase", "-r", "ws2@", "-d", "root()")
    # jj itself agrees: the workspace is stale, and a stale `jj st` refuses
    # rather than snapshotting.
    assert "stale" in jj_repo.run(ws2, "st", check=False).stderr
    return root, ws2


@pytest.mark.parametrize(
    "command",
    [
        "jj workspace update-stale",
        "jj --no-pager workspace update-stale 2>&1 | tail -1",
        "cd {ws2} && jj --no-pager workspace update-stale",
        "bash -c 'cd {ws2} && jj workspace update-stale'",
    ],
)
def test_guard_refuses_update_stale_in_a_stale_workspace(stale, command):
    _, ws2 = stale

    output = run_guard(ws2 if "{ws2}" not in command else ws2.parent, command.format(ws2=ws2))

    assert output["permissionDecision"] == "deny"
    reason = output["permissionDecisionReason"]
    assert "workspace ws2 is STALE" in reason
    assert "bare `jj workspace update-stale` is refused" in reason
    assert "Realign a stale workspace" in reason
    assert "`repair` helper" in reason


def test_guard_only_warns_for_other_jj_commands_in_a_stale_workspace(stale):
    _, ws2 = stale

    output = run_guard(ws2, "jj --no-pager commit -m x")

    assert "permissionDecision" not in output
    context = output["additionalContext"]
    assert "workspace ws2 is STALE" in context
    assert "harmony" in context
    assert "never a bare `jj workspace update-stale`" in context


def test_guard_is_silent_for_inspection_and_healthy_workspaces(stale):
    root, ws2 = stale

    assert run_guard(ws2, "jj --no-pager --ignore-working-copy log") is None
    assert run_guard(root, "jj --no-pager commit -m x") is None
    assert run_guard(root, "jj --no-pager workspace update-stale") is None


# --- fail open ----------------------------------------------------------------


def test_guard_fails_open(tmp_path, resurrect):
    root, old, _, _ = resurrect

    assert run_guard(tmp_path, f"jj new {old}") is None  # not a jj workspace
    assert run_guard(root, f"jj new {old}", tool_name="Edit") is None
    assert run_guard(root, f"jj new {old}", hook_event_name="PostToolUse") is None
    assert run_guard(root, f"jj new '{old}") is None  # unbalanced quote

    result = subprocess.run(
        [sys.executable, str(HOOK)], input="not json", capture_output=True, text=True
    )
    assert (result.returncode, result.stdout) == (0, "")

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": str(root),
        "tool_input": {"command": f"jj new {old}"},
    }
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"PATH": str(tmp_path)},  # jj cannot be found
    )
    assert (result.returncode, result.stdout) == (0, "")


def test_guard_is_registered_for_bash_before_tool_use():
    manifest = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    entries = manifest["hooks"]["PreToolUse"]

    assert [entry["matcher"] for entry in entries] == ["Bash"]
    command = entries[0]["hooks"][0]["command"]
    assert command.endswith('/hooks/jj_guard.py"')
