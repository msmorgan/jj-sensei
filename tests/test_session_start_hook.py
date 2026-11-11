import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "session_start.sh"
PLUGIN_ROOT_VARIABLES = ("PLUGIN_ROOT", "CLAUDE_PLUGIN_ROOT")


def run_hook(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def jj_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "repo"
    (workspace / ".jj").mkdir(parents=True)
    return workspace


def test_claude_session_start_emits_plain_context(tmp_path):
    workspace = jj_workspace(tmp_path)

    result = run_hook({"hook_event_name": "SessionStart", "cwd": str(workspace)})

    assert result.returncode == 0
    assert result.stdout.startswith("Use Jujutsu (`jj`) exclusively")


def test_context_keeps_load_once_but_reloads_after_compaction():
    """`once` and `stays in context` stop agents re-reading the skill before every
    jj command; the compaction clause stops them trusting a summary that merely
    lists wisdom as loaded after the skill text itself was evicted."""
    context = (ROOT / "hooks" / "jj-context.md").read_text()

    assert "skill once, before your first version-control command" in context
    assert "from then on it stays in context" in context
    assert "Context compaction evicts it" in context
    assert "even when the summary lists it as loaded" in context
    assert "load it once more after compaction" in context


def test_agy_first_invocation_injects_ephemeral_context(tmp_path):
    workspace = jj_workspace(tmp_path)

    result = run_hook({"invocationNum": 0, "workspacePaths": [str(workspace)]})

    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["injectSteps"][0]["ephemeralMessage"].startswith(
        "Use Jujutsu (`jj`) exclusively"
    )


def test_agy_later_invocation_does_not_repeat_context(tmp_path):
    workspace = jj_workspace(tmp_path)

    result = run_hook({"invocationNum": 1, "workspacePaths": [str(workspace)]})

    assert result.returncode == 0
    assert json.loads(result.stdout) == {}


def test_agy_outside_jj_workspace_does_not_inject(tmp_path):
    result = run_hook({"invocationNum": 0, "workspacePaths": [str(tmp_path)]})

    assert result.returncode == 0
    assert json.loads(result.stdout) == {}


PREAMBLE = (ROOT / "hooks" / "jj-context.md").read_text()


def step(index: int, step_type: str, content: str, **extra: object) -> dict:
    source = {"EPHEMERAL_MESSAGE": "SYSTEM_SDK", "CHECKPOINT": "SYSTEM"}.get(
        step_type, "USER_EXPLICIT"
    )
    return {
        "step_index": str(index),
        "source": source,
        "type": step_type,
        "status": "DONE",
        "created_at": "2026-11-11T00:00:00Z",
        "content": content,
        **extra,
    }


def write_transcript(tmp_path: Path, *steps: dict) -> Path:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("".join(json.dumps(s) + "\n" for s in steps))
    return transcript


def run_agy_first_invocation(workspace: Path, transcript: Path, invocation: int = 0) -> object:
    result = run_hook(
        {
            "invocationNum": invocation,
            "workspacePaths": [str(workspace)],
            "transcriptPath": str(transcript),
        }
    )
    assert result.returncode == 0
    return json.loads(result.stdout)


def injects(response: object) -> bool:
    return response == {"injectSteps": [{"ephemeralMessage": PREAMBLE}]}


def test_agy_injects_on_a_transcript_with_only_user_input(tmp_path):
    transcript = write_transcript(tmp_path, step(0, "USER_INPUT", "hello"))

    assert injects(run_agy_first_invocation(jj_workspace(tmp_path), transcript))


def test_agy_does_not_repeat_a_preamble_already_in_the_transcript(tmp_path):
    transcript = write_transcript(
        tmp_path,
        step(0, "USER_INPUT", "hello"),
        step(1, "EPHEMERAL_MESSAGE", PREAMBLE),
        step(2, "PLANNER_RESPONSE", "hi"),
        step(3, "USER_INPUT", "again"),
    )

    assert run_agy_first_invocation(jj_workspace(tmp_path), transcript) == {}


def test_agy_reinjects_after_a_compaction_checkpoint(tmp_path):
    transcript = write_transcript(
        tmp_path,
        step(1, "EPHEMERAL_MESSAGE", PREAMBLE),
        step(2, "PLANNER_RESPONSE", "hi"),
        step(3, "CHECKPOINT", "# Resuming from a compaction\n\nsummary"),
        step(4, "USER_INPUT", "continue"),
    )

    assert injects(run_agy_first_invocation(jj_workspace(tmp_path), transcript))


def test_agy_does_not_repeat_a_preamble_reinjected_after_compaction(tmp_path):
    transcript = write_transcript(
        tmp_path,
        step(1, "EPHEMERAL_MESSAGE", PREAMBLE),
        step(2, "CHECKPOINT", "# Resuming from a compaction\n\nsummary"),
        step(3, "EPHEMERAL_MESSAGE", PREAMBLE),
        step(4, "PLANNER_RESPONSE", "hi"),
        step(5, "USER_INPUT", "continue"),
    )

    assert run_agy_first_invocation(jj_workspace(tmp_path), transcript) == {}


def test_agy_ignores_the_preamble_quoted_outside_an_ephemeral_message(tmp_path):
    transcript = write_transcript(
        tmp_path,
        step(0, "USER_INPUT", PREAMBLE),
        step(1, "PLANNER_RESPONSE", PREAMBLE),
    )

    assert injects(run_agy_first_invocation(jj_workspace(tmp_path), transcript))


def test_agy_ignores_another_plugins_ephemeral_message(tmp_path):
    transcript = write_transcript(
        tmp_path, step(1, "EPHEMERAL_MESSAGE", "Some other plugin's guidance.")
    )

    assert injects(run_agy_first_invocation(jj_workspace(tmp_path), transcript))


def test_agy_recognises_a_truncated_preamble(tmp_path):
    transcript = write_transcript(
        tmp_path,
        step(1, "EPHEMERAL_MESSAGE", PREAMBLE[:60], truncated_fields=["content"]),
    )

    assert run_agy_first_invocation(jj_workspace(tmp_path), transcript) == {}


def test_agy_injects_when_the_transcript_is_missing(tmp_path):
    transcript = tmp_path / "missing.jsonl"

    assert injects(run_agy_first_invocation(jj_workspace(tmp_path), transcript))


@pytest.mark.parametrize(("ephemeral", "expected_inject"), [(PREAMBLE, False), ("other", True)])
def test_agy_skips_garbage_transcript_lines(tmp_path, ephemeral, expected_inject):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(step(1, "EPHEMERAL_MESSAGE", ephemeral))
        + "\nnot json {\n[1, 2]\n"
        + json.dumps(step(2, "USER_INPUT", "hello"))
        + "\n"
    )

    response = run_agy_first_invocation(jj_workspace(tmp_path), transcript)

    assert injects(response) is expected_inject
    if not expected_inject:
        assert response == {}


def test_agy_injects_when_the_transcript_is_not_utf8(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_bytes(
        json.dumps(step(1, "EPHEMERAL_MESSAGE", PREAMBLE)).encode() + b"\n\xff\xfe\n"
    )

    assert injects(run_agy_first_invocation(jj_workspace(tmp_path), transcript))


def test_agy_later_invocation_stays_silent_with_a_transcript(tmp_path):
    transcript = write_transcript(tmp_path, step(0, "USER_INPUT", "hello"))

    response = run_agy_first_invocation(jj_workspace(tmp_path), transcript, 1)

    assert response == {}


def hook_manifest_commands() -> list[str]:
    """Every distinct command the manifest runs, across all of its events."""
    manifest = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    commands = [
        hook["command"]
        for entries in manifest["hooks"].values()
        for entry in entries
        for hook in entry["hooks"]
    ]
    assert commands, manifest
    return sorted(set(commands))


def session_start_command() -> str:
    matches = [
        command
        for command in hook_manifest_commands()
        if command.endswith('/hooks/session_start.sh"')
    ]
    assert len(matches) == 1, matches
    return matches[0]


@pytest.mark.parametrize(
    "command", hook_manifest_commands(), ids=lambda c: c.rsplit("/", 1)[-1].rstrip('"')
)
@pytest.mark.parametrize("plugin_root", PLUGIN_ROOT_VARIABLES)
def test_every_manifest_command_resolves_for_every_host(tmp_path, plugin_root, command):
    """Codex exports PLUGIN_ROOT and Claude exports CLAUDE_PLUGIN_ROOT. A command
    naming only one of them silently expands to an absolute path under `/`, and the
    hook never runs. Every command in the manifest carries that risk, not just the
    one whose output this module asserts on."""
    workspace = jj_workspace(tmp_path)
    environment = {
        name: value for name, value in os.environ.items() if name not in PLUGIN_ROOT_VARIABLES
    }
    environment[plugin_root] = str(ROOT)

    result = subprocess.run(
        ["bash", "-c", command],
        input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(workspace)}),
        capture_output=True,
        text=True,
        env=environment,
    )

    # An unresolved root exits non-zero from the interpreter, before the hook's own
    # logic runs. What each hook then decides to emit is asserted elsewhere.
    assert result.returncode == 0, result.stderr


def test_session_start_manifest_command_injects_guidance(tmp_path):
    workspace = jj_workspace(tmp_path)

    result = subprocess.run(
        ["bash", "-c", session_start_command()],
        input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(workspace)}),
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(ROOT)},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Use Jujutsu (`jj`) exclusively")


def test_hook_manifest_command_survives_a_plugin_root_containing_spaces(tmp_path):
    installed = tmp_path / "plugin cache" / "jj-sensei"
    (installed / "hooks").mkdir(parents=True)
    for name in ("session_start.sh", "jj-context.md"):
        target = installed / "hooks" / name
        target.write_bytes((ROOT / "hooks" / name).read_bytes())
        target.chmod(0o755)
    workspace = jj_workspace(tmp_path)

    result = subprocess.run(
        ["bash", "-c", session_start_command()],
        input=json.dumps({"hook_event_name": "SessionStart", "cwd": str(workspace)}),
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PLUGIN_ROOT": str(installed)},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Use Jujutsu (`jj`) exclusively")


def test_antigravity_manifest_targets_the_shared_hook_script():
    manifest = json.loads((ROOT / "hooks.json").read_text())
    entries = manifest["jj-sensei-context"]["PreInvocation"]

    assert [entry["type"] for entry in entries] == ["command"]
    # Antigravity runs hook commands from the plugin root, so the path is relative.
    relative = entries[0]["command"].removeprefix("bash ./")
    assert relative != entries[0]["command"]
    assert (ROOT / relative).resolve() == HOOK.resolve()


def test_hook_script_is_executable():
    assert os.access(HOOK, os.X_OK)
