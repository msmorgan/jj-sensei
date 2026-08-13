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
    assert result.stdout.startswith("**This is a jj (Jujutsu) repo")


def test_agy_first_invocation_injects_ephemeral_context(tmp_path):
    workspace = jj_workspace(tmp_path)

    result = run_hook({"invocationNum": 0, "workspacePaths": [str(workspace)]})

    assert result.returncode == 0
    response = json.loads(result.stdout)
    assert response["injectSteps"][0]["ephemeralMessage"].startswith(
        "**This is a jj (Jujutsu) repo"
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
    assert result.stdout.startswith("**This is a jj (Jujutsu) repo")


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
    assert result.stdout.startswith("**This is a jj (Jujutsu) repo")


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
