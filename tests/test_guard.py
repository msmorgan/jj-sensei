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


# --- Antigravity --------------------------------------------------------------

STATUS_HOOK = ROOT / "hooks" / "jj_status.py"


def _agy_payload(cwd: Path, command: str, **overrides) -> dict:
    """The shape of a real Antigravity `PreToolUse` payload for `run_command`."""
    payload = {
        "conversationId": "2cd1403b-68c4-45a1-8df1-8834350f2023",
        "cwd": str(cwd),
        "workspacePaths": [str(cwd)],
        "hookEventName": "PreToolUse",
        "lastUserInput": "do the thing",
        "modelName": "gemini-4-argon-low",
        "stepIdx": 3,
        "toolCall": {
            "id": "call_1",
            "name": "run_command",
            "args": {"CommandLine": command, "WaitMsBeforeAsync": 5000},
        },
    }
    payload.update(overrides)
    return payload


def run_agy_guard(cwd: Path, command: str, **overrides) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(_agy_payload(cwd, command, **overrides)),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def run_status(payload: dict) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [sys.executable, str(STATUS_HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def _pending(workspace: Path) -> list[Path]:
    return list((workspace / ".jj" / "jj-sensei").glob("warnings-pending.*"))


def test_antigravity_guard_denies_a_hidden_commit_id(resurrect):
    root, old, change, _ = resurrect

    result = run_agy_guard(root, f"jj --no-pager new {old}")

    output = json.loads(result.stdout)
    assert set(output) == {"decision", "reason"}
    assert output["decision"] == "deny"
    assert f"{old[:12]} is a hidden (rewritten) commit" in output["reason"]
    assert f"Its change is {change[:8]}" in output["reason"]


def test_antigravity_guard_reads_the_command_cwd_argument(resurrect):
    root, old, _, _ = resurrect

    result = run_agy_guard(root.parent, f"jj --no-pager new {old}")
    assert result.stdout == ""

    tool_call = {"name": "run_command", "args": {"CommandLine": f"jj new {old}", "Cwd": str(root)}}
    result = run_agy_guard(root.parent, "", toolCall=tool_call)
    assert json.loads(result.stdout)["decision"] == "deny"


def test_antigravity_guard_prints_nothing_when_it_has_no_objection(resurrect):
    root, old, change, _ = resurrect

    # Empty stdout leaves Antigravity's permission flow untouched; `{}` would deny.
    assert run_agy_guard(root, f"jj --no-pager new {change[:8]}").stdout == ""
    assert run_agy_guard(root, f"jj --no-pager log -r {old}").stdout == ""
    assert run_agy_guard(root, "cargo test").stdout == ""
    other_tool = {"name": "view_file", "args": {"CommandLine": f"jj new {old}"}}
    assert run_agy_guard(root, "", toolCall=other_tool).stdout == ""
    assert run_agy_guard(root, f"jj new {old}", hookEventName="PostToolUse").stdout == ""
    assert _pending(root) == []


def test_antigravity_guard_defers_a_warning_to_the_next_invocation(resurrect):
    root, _, _, _ = resurrect

    warned = run_agy_guard(root, 'jj --no-pager new "$OLD"')
    assert warned.stdout == ""
    assert len(_pending(root)) == 1

    # The status hook's PostToolUse for the same call queues its own line;
    # it must not overwrite the warning.
    root.joinpath("new.txt").write_text("one\n")
    post = run_status(
        {
            "conversationId": _agy_payload(root, "")["conversationId"],
            "workspacePaths": [str(root)],
            "cwd": str(root),
            "toolCall": {"name": "run_command", "args": {"CommandLine": 'jj new "$OLD"'}},
        }
    )
    assert json.loads(post.stdout) == {}

    invocation = {
        "conversationId": _agy_payload(root, "")["conversationId"],
        "workspacePaths": [str(root)],
        "invocationNum": 1,
    }
    delivered = run_status(invocation)
    message = json.loads(delivered.stdout)["injectSteps"][0]["ephemeralMessage"]
    warning, _, status = message.partition("\n\n")
    assert "$OLD" in warning
    assert "Write the change id or revset inline" in warning
    assert status.startswith("jj: default | @ ")
    assert _pending(root) == []

    assert json.loads(run_status(invocation).stdout) == {}


def test_antigravity_guard_queues_a_stale_workspace_warning_once(stale):
    _, ws2 = stale

    for _ in range(2):
        assert run_agy_guard(ws2, "jj --no-pager commit -m x").stdout == ""

    delivered = run_status(
        {
            "conversationId": _agy_payload(ws2, "")["conversationId"],
            "workspacePaths": [str(ws2)],
            "invocationNum": 2,
        }
    )
    message = json.loads(delivered.stdout)["injectSteps"][0]["ephemeralMessage"]
    assert message.count("workspace ws2 is STALE") == 1
    assert "harmony" in message


def test_antigravity_guard_fails_open(tmp_path, resurrect):
    root, old, _, _ = resurrect

    assert run_agy_guard(tmp_path, f"jj new {old}").stdout == ""  # not a jj workspace
    assert run_agy_guard(root, f"jj new '{old}").stdout == ""  # unbalanced quote
    assert run_agy_guard(root, "", toolCall={"name": "run_command"}).stdout == ""

    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(_agy_payload(root, f"jj new {old}")),
        capture_output=True,
        text=True,
        env={"PATH": str(tmp_path)},  # jj cannot be found
    )
    assert (result.returncode, result.stdout) == (0, "")


def test_guard_is_registered_for_antigravity_run_command():
    manifest = json.loads((ROOT / "hooks.json").read_text())

    assert manifest["jj-sensei-guard"] == {
        "PreToolUse": [
            {
                "matcher": "run_command",
                "hooks": [
                    {
                        "type": "command",
                        "command": "python3 ./hooks/jj_guard.py",
                        "timeout": 10,
                    }
                ],
            }
        ]
    }
