"""jj-sensei's strict subprocess boundary for Jujutsu commands."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

_SAFE_REVISION = re.compile(r"^[a-z0-9]+$")
# A non-greedy path plus a padding run lets the engine backtrack past any double
# space inside the path itself until the description actually matches.
_CONFLICT_ROW = re.compile(r"^(?P<path>.+?) {2,}\d+-sided conflict\b.*$")
_COMMIT_TEMPLATE = (
    "concat("
    "'{\"change_id\":', json(change_id), "
    "',\"commit_id\":', json(commit_id), "
    "',\"empty\":', json(empty), "
    "',\"description\":', json(description), "
    "',\"immutable\":', json(immutable), "
    "',\"conflict\":', json(conflict), "
    "'}', \"\\n\")"
)
# `root` is rendered last on purpose. A workspace whose directory is gone
# stays registered, and jj renders its root as an inline `<Error: ...>`
# placeholder instead of a value, which makes the row invalid JSON. `name` and
# `target.commit_id()` cannot fail, so putting `root` last keeps every other
# field recoverable by truncating the row at the property that failed.
_WORKSPACE_TEMPLATE = (
    "concat("
    "'{\"name\":', json(name), "
    "',\"commit_id\":', json(target.commit_id()), "
    "',\"root\":', json(stringify(root)), "
    "'}', \"\\n\")"
)
_ROOT_PROPERTY = ',"root":'


@dataclass(frozen=True)
class Commit:
    change_id: str
    commit_id: str
    empty: bool
    description: str
    immutable: bool
    conflict: bool


@dataclass(frozen=True)
class Workspace:
    name: str
    commit_id: str
    root: Path | None
    root_error: str | None = None

    @property
    def orphaned(self) -> bool:
        """Registered in the repo, but its working-copy directory is gone."""
        return self.root is None


class JjError(RuntimeError):
    """A checked jj invocation failed."""

    def __init__(self, command: list[str], result: subprocess.CompletedProcess[str]):
        self.command = command
        self.returncode = result.returncode
        self.stdout = result.stdout
        self.stderr = result.stderr
        super().__init__(f"{shlex.join(command)} exited {result.returncode}")

    @property
    def rendered_command(self) -> str:
        return shlex.join(self.command)


class Jj:
    """Run jj in one workspace without repository-retargeting escape hatches."""

    def __init__(self, cwd: Path | str | None = None):
        self.cwd = Path(cwd or Path.cwd()).resolve()

    def run(
        self,
        *args: str,
        check: bool = True,
        ignore_working_copy: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        command = ["jj", "--no-pager"]
        if ignore_working_copy:
            command.append("--ignore-working-copy")
        command.extend(args)
        result = subprocess.run(
            command,
            cwd=self.cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode:
            raise JjError(command, result)
        return result

    def workspace_root(self) -> Path:
        return Path(
            self.run("workspace", "root", ignore_working_copy=True).stdout.strip()
        ).resolve()

    def workspaces(self) -> list[Workspace]:
        """List every registered workspace, including orphaned registrations.

        One workspace whose root cannot be resolved must not hide the others:
        the status hook, boundaries setup, and repair all enumerate from here,
        and a single dead registration used to take all of them down at once.
        """
        result = self.run(
            "workspace",
            "list",
            "-T",
            _WORKSPACE_TEMPLATE,
            ignore_working_copy=True,
        )
        return [
            parse_workspace(line) for line in result.stdout.splitlines() if line.strip()
        ]

    def current_workspace(self) -> Workspace:
        root = self.workspace_root()
        # An orphaned registration has no resolvable root, so it can never be
        # the workspace this process is running in.
        matches = [
            workspace
            for workspace in self.workspaces()
            if not workspace.orphaned and workspace.root == root
        ]
        if len(matches) != 1:
            raise RuntimeError(f"could not identify the current workspace at {root}")
        return matches[0]

    def commits(self, revset: str, *, snapshot: bool = False) -> list[Commit]:
        result = self.run(
            "log",
            "--no-graph",
            "-r",
            revset,
            "-T",
            _COMMIT_TEMPLATE,
            ignore_working_copy=not snapshot,
        )
        commits = []
        for item in _json_lines(result.stdout):
            # jj stores descriptions with one terminating newline. Command-line
            # `-m` accepts the human text without it and restores that canonical
            # terminator, so keep the in-process representation newline-free.
            item["description"] = item["description"].removesuffix("\n")
            commits.append(Commit(**item))
        return commits

    def one_commit(self, revset: str, *, snapshot: bool = False) -> Commit:
        commits = self.commits(revset, snapshot=snapshot)
        if len(commits) != 1:
            raise RuntimeError(f"expected one commit for {revset!r}, found {len(commits)}")
        return commits[0]

    def resolve_list(self) -> subprocess.CompletedProcess[str]:
        """Run `jj resolve --list`, normalizing "no conflicts" to empty success."""
        result = self.run("resolve", "--list", check=False)
        if result.returncode and not result.stdout and "No conflicts found" in result.stderr:
            return subprocess.CompletedProcess(result.args, 0, "", "")
        return result

    def conflict_files(self) -> list[str]:
        result = self.resolve_list()
        if result.returncode:
            raise JjError(["jj", "--no-pager", "resolve", "--list"], result)
        return [parse_conflict_path(line) for line in result.stdout.splitlines() if line.strip()]

    def diff_between(self, left: str, right: str) -> str:
        safe_revision(left)
        safe_revision(right)
        return self.run(
            "diff",
            "--git",
            "--from",
            left,
            "--to",
            right,
            ignore_working_copy=True,
        ).stdout


def parse_conflict_path(line: str) -> str:
    """Read the path out of one `jj resolve --list` row.

    Rows are `PATH<padding>DESCRIPTION`, and the description is not a fixed
    number of words — a delete/modify conflict reads "2-sided conflict
    including 1 deletion". Splitting off a fixed word count silently produces a
    path that does not exist, so anchor on the description and refuse anything
    that does not match rather than guessing.
    """
    match = _CONFLICT_ROW.match(line)
    if match is None:
        raise RuntimeError(f"could not read a path from `jj resolve --list` row: {line!r}")
    return match.group("path")


def parse_workspace(line: str) -> Workspace:
    """Read one `jj workspace list` row, tolerating an unresolvable root.

    jj renders a missing workspace root as an inline `<Error: ...>` placeholder
    and still exits 0, so the row parses as JSON only up to that property. The
    name and commit ID before it are still trustworthy; recover them and
    report the workspace as orphaned rather than losing the whole listing.
    """
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        cut = line.rfind(_ROOT_PROPERTY)
        if cut < 0:
            raise RuntimeError(f"could not read a `jj workspace list` row: {line!r}") from None
        try:
            item = json.loads(f"{line[:cut]}}}")
        except json.JSONDecodeError:
            raise RuntimeError(f"could not read a `jj workspace list` row: {line!r}") from None
        return Workspace(
            name=item["name"],
            commit_id=item["commit_id"],
            root=None,
            root_error=line[cut + len(_ROOT_PROPERTY) :].removesuffix("}").strip(),
        )
    return Workspace(
        name=item["name"],
        commit_id=item["commit_id"],
        root=Path(item["root"]).resolve(),
    )


def safe_revision(value: str) -> str:
    """Validate IDs before interpolating them into revset expressions."""
    if not _SAFE_REVISION.fullmatch(value):
        raise ValueError(f"unsafe revision identifier: {value!r}")
    return value


def union(revisions: Iterable[str]) -> str:
    values = [safe_revision(value) for value in revisions]
    return " | ".join(values) if values else "none()"


def _json_lines(output: str) -> list[dict]:
    return [json.loads(line) for line in output.splitlines() if line.strip()]
