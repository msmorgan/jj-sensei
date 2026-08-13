from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest


@dataclass
class JjRepo:
    root: Path
    env: dict[str, str]

    def run(
        self,
        cwd: Path,
        *args: str,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["jj", "--no-pager", *args],
            cwd=cwd,
            env=self.env,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode:
            raise AssertionError(
                f"jj command failed ({result.returncode}): {' '.join(args)}\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )
        return result

    def write(self, cwd: Path, relative: str, content: str) -> None:
        path = cwd / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def commit(self, cwd: Path, message: str) -> None:
        self.run(cwd, "commit", "-m", message)

    def add_workspace(self, name: str) -> Path:
        destination = self.root.parent / name
        self.run(
            self.root,
            "workspace",
            "add",
            str(destination),
            "--name",
            name,
            "-m",
            f"{name} workspace",
        )
        return destination


@pytest.fixture
def jj_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JjRepo:
    config_home = tmp_path / "config"
    config_home.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    root = tmp_path / "default"
    root.mkdir()
    env = dict(os.environ)
    repo = JjRepo(root=root, env=env)
    repo.run(root, "git", "init", "--colocate", ".")
    repo.write(root, "f.txt", "base\n")
    repo.commit(root, "base")
    return repo
