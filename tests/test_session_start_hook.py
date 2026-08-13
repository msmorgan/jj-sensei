import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "session_start.sh"


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
