import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARMONY = ROOT / "skills" / "harmony" / "scripts"
WISDOM = ROOT / "skills" / "wisdom" / "scripts"

PACKAGED_COMMANDS = [
    [],
    ["repair"],
    ["resolve"],
    ["converge"],
    ["setup"],
    ["rtfm"],
    ["conflicts"],
    ["conflicts", "list"],
    ["conflicts", "show"],
    ["conflicts", "accept"],
    ["conflicts", "auto"],
    ["interpolate"],
    ["interpolate", "begin"],
    ["interpolate", "finish"],
    ["interpolate", "abort"],
]

SKILL_COMMANDS = [
    [str(HARMONY / "repair")],
    [str(HARMONY / "resolve")],
    [str(HARMONY / "converge")],
    [str(HARMONY / "conflicts")],
    [str(HARMONY / "conflicts"), "list"],
    [str(HARMONY / "conflicts"), "show"],
    [str(HARMONY / "conflicts"), "accept"],
    [str(HARMONY / "conflicts"), "auto"],
    [str(ROOT / "skills" / "boundaries" / "scripts" / "setup-immutability")],
    [str(ROOT / "skills" / "knowledge" / "scripts" / "rtfm")],
    [str(WISDOM / "interpolate")],
    [str(WISDOM / "interpolate"), "begin"],
    [str(WISDOM / "interpolate"), "finish"],
    [str(WISDOM / "interpolate"), "abort"],
]


@pytest.mark.parametrize("command", PACKAGED_COMMANDS)
@pytest.mark.parametrize("help_flag", ["-h", "--help"])
def test_packaged_commands_expose_side_effect_free_help(tmp_path, command, help_flag):
    environment = os.environ | {"PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [sys.executable, "-m", "jj_sensei.cli", *command, help_flag],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
    assert result.stderr == ""


@pytest.mark.parametrize("command", SKILL_COMMANDS)
@pytest.mark.parametrize("help_flag", ["-h", "--help"])
def test_skill_commands_expose_side_effect_free_help(tmp_path, command, help_flag):
    result = subprocess.run(
        [*command, help_flag],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout.lower()
    assert result.stderr == ""
