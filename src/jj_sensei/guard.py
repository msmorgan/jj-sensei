"""Pre-tool guard: refuse jj mutations that name a hidden commit.

A commit id resolves in jj even after the commit has been rewritten and hidden.
Passing such an id to `jj new`, `jj rebase`, and the like makes that commit,
and every hidden ancestor down to the visible line, visible again as divergent
copies of their live successors. Agents hit this by capturing a commit id,
running a long job while another workspace rewrites the line, and then
mutating on the stale id. A change id cannot go stale that way, so the guard
names the change id to use instead.

The guard also warns, without blocking, when a jj command is about to run in a
stale workspace: `jj workspace update-stale` (or any jj command, when
`snapshot.auto-update-stale` is set) snapshots on-disk edits at the old
operation and can fork the working-copy change.

Everything here fails open. A command this module cannot read, a directory
that is not a jj workspace, or a jj call that fails or times out yields no
verdict, and the tool call proceeds through the host's normal flow.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

# Cheap pre-filter: nothing below runs unless the text names jj at all.
_MENTIONS_JJ = re.compile(r"(?<![\w.-])jj(?![\w.-])")

# A commit-id candidate: a run of lowercase hex, 8 to 40 characters, not glued
# to other word characters. jj prints commit ids at 8 (`shortest(8)` in the
# default log) or 12 characters, so 8 covers every id an agent copies from
# output, while shorter runs ("beef", "2024") are mostly words and numbers.
# Change ids use only the letters k-z, so they never match.
_HEX_ATOM = re.compile(r"(?<![0-9A-Za-z_])[0-9a-f]{8,40}(?![0-9A-Za-z_])")
# A change id with a `/N` offset (jj 0.37+) can select a hidden version.
_CHANGE_OFFSET = re.compile(r"(?<![0-9A-Za-z_])[k-z]+/[0-9]+(?![0-9A-Za-z_])")
_ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", re.DOTALL)
_VARIABLE = re.compile(r"^\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\})$")
_REDIRECT_ALONE = re.compile(r"^[0-9]*(?:>>?|<<?|>\||&>>?)$")
_REDIRECT_ATTACHED = re.compile(r"^[0-9]*(?:>>?|<<?|&>>?)\S")
_SEPARATOR_CHARS = frozenset("|&;\n")

_PREFIX_WORDS = frozenset(
    {
        "command",
        "exec",
        "nohup",
        "time",
        "then",
        "do",
        "else",
        "elif",
        "if",
        "while",
        "until",
        "!",
        "{",
        "(",
        "env",
        "timeout",
        "nice",
    }
)
_SHELLS = frozenset({"bash", "sh", "zsh", "dash"})

_GLOBAL_VALUE_OPTIONS = frozenset(
    {
        "-R",
        "--repository",
        "--at-op",
        "--at-operation",
        "--color",
        "--config",
        "--config-toml",
        "--config-file",
    }
)
_NESTED = {
    "bookmark": "bookmark",
    "b": "bookmark",
    "tag": "tag",
    "workspace": "workspace",
}
_MUTATING = frozenset(
    {
        "new",
        "edit",
        "rebase",
        "squash",
        "duplicate",
        "restore",
        "abandon",
        "describe",
        "desc",
        "split",
        "absorb",
        "backout",
        "revert",
        "parallelize",
        "simplify-parents",
        "fix",
        "metaedit",
        "commit",
        "ci",
        "diffedit",
        "sign",
        "unsign",
        "arrange",
        "converge",
        "bookmark set",
        "bookmark s",
        "bookmark move",
        "bookmark m",
        "bookmark create",
        "bookmark c",
        "tag set",
        "tag s",
        "workspace add",
        "workspace update-stale",
    }
)
# Subcommands whose positional arguments are revisions rather than filesets,
# bookmark names, or paths.
_POSITIONAL_REVISIONS = frozenset(
    {
        "new",
        "edit",
        "abandon",
        "describe",
        "desc",
        "duplicate",
        "parallelize",
        "metaedit",
        "sign",
        "unsign",
    }
)
_REVISION_OPTIONS = frozenset(
    {
        "-r",
        "--revision",
        "--revisions",
        "-s",
        "--source",
        "-b",
        "--branch",
        "-d",
        "--destination",
        "-o",
        "--onto",
        "-A",
        "--insert-after",
        "--after",
        "-B",
        "--insert-before",
        "--before",
        "-f",
        "--from",
        "-t",
        "--into",
        "--to",
        "-c",
        "--changes-in",
    }
)
_VALUE_OPTIONS = frozenset(
    {
        "-m",
        "--message",
        "-T",
        "--template",
        "--tool",
        "--name",
        "--sparse-patterns",
        "--remote",
        "--color",
        "--config",
        "--config-file",
        "-R",
        "--repository",
        "--at-op",
        "--at-operation",
    }
)
# Commands that never load the working copy, so staleness is irrelevant.
_NO_WORKING_COPY = frozenset({"help", "config", "util", "version"})

JJ_TIMEOUT = 5.0
_HIDDEN_TEMPLATE = 'commit_id ++ " " ++ change_id.shortest(8) ++ " " ++ hidden ++ "\\n"'
_INLINE_EXAMPLE = "jj --no-pager new 'heads(::@ & ::default@)'"


@dataclass
class Invocation:
    """One `jj ...` call found in a shell command."""

    directory: Path
    subcommand: str
    ignore_working_copy: bool
    revisions: list[str] = field(default_factory=list)
    unexpanded: list[str] = field(default_factory=list)

    @property
    def mutating(self) -> bool:
        return self.subcommand in _MUTATING

    @property
    def label(self) -> str:
        return f"jj {self.subcommand}".strip()


@dataclass(frozen=True)
class Verdict:
    deny: bool
    message: str


# --- tokenizing ---------------------------------------------------------------


def find_invocations(command: str, cwd: Path, *, depth: int = 0) -> list[Invocation]:
    """Every jj invocation in `command`, with the directory it will run in.

    Segments are split on `&&`, `||`, `;`, `|`, `&`, and newlines. A `cd DIR`
    segment changes the directory for the segments after it, which covers the
    leading `cd <workspace> &&` agent shells need. `bash -c '...'` bodies are
    scanned the same way; script files are not read.
    """
    if depth > 2 or not _MENTIONS_JJ.search(command):
        return []
    try:
        lexer = shlex.shlex(command.replace("\\\n", " "), posix=True, punctuation_chars="|&;\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return []

    invocations: list[Invocation] = []
    assignments: dict[str, str] = {}
    directory = cwd
    for segment in _segments(tokens):
        index = _command_index(segment, assignments)
        if index is None:
            continue
        word = segment[index].lstrip("({")
        arguments = segment[index + 1 :]
        if arguments:
            arguments[-1] = _close_group(arguments[-1])
        name = word.rsplit("/", 1)[-1]
        if name in {"cd", "pushd"}:
            target = next((value for value in arguments if not value.startswith("-")), None)
            directory = _resolve(directory, target or os.path.expanduser("~"))
        elif name in _SHELLS:
            body = _shell_body(arguments)
            if body is not None:
                invocations.extend(find_invocations(body, directory, depth=depth + 1))
        elif name == "jj":
            invocation = _parse_jj(arguments, directory, assignments)
            if invocation is not None:
                invocations.append(invocation)
    return invocations


def _segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and set(token) <= _SEPARATOR_CHARS:
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def _command_index(segment: list[str], assignments: dict[str, str]) -> int | None:
    after_prefix = False
    for index, token in enumerate(segment):
        bare = token.lstrip("({")
        if not bare:
            continue
        match = _ASSIGNMENT.match(bare)
        if match:
            name, value = match.groups()
            if "$" in value or "`" in value:
                assignments.pop(name, None)
            else:
                assignments[name] = value
            continue
        if bare in _PREFIX_WORDS:
            after_prefix = True
            continue
        if after_prefix and (bare.startswith("-") or re.fullmatch(r"[0-9.]+[smhd]?", bare)):
            continue
        return index
    return None


def _close_group(token: str) -> str:
    """Drop a subshell's or group's closing `)`/`}` glued to the last word."""
    for opening, closing in ("()", "{}"):
        while token.endswith(closing) and token.count(closing) > token.count(opening):
            token = token[:-1]
    return token


def _shell_body(arguments: list[str]) -> str | None:
    for index, token in enumerate(arguments):
        if token.startswith("-") and not token.startswith("--") and "c" in token[1:]:
            return arguments[index + 1] if index + 1 < len(arguments) else None
        if not token.startswith("-"):
            return None
    return None


def _resolve(base: Path, value: str) -> Path:
    path = Path(os.path.expanduser(value))
    return path if path.is_absolute() else base / path


def _option(token: str, names: frozenset[str]) -> tuple[str, str | None] | None:
    """Match `--name`, `--name=VALUE`, `-x`, `-x=VALUE`, or `-xVALUE`."""
    if token.startswith("--"):
        name, equals, value = token.partition("=")
        return (name, value if equals else None) if name in names else None
    if token.startswith("-") and len(token) >= 2:
        name = token[:2]
        if name not in names:
            return None
        rest = token[2:]
        if not rest:
            return name, None
        return name, rest.removeprefix("=")
    return None


def _parse_jj(
    arguments: list[str], directory: Path, assignments: dict[str, str]
) -> Invocation | None:
    ignore_working_copy = False
    position = 0
    while position < len(arguments) and arguments[position].startswith("-"):
        token = arguments[position]
        if token == "--ignore-working-copy":
            ignore_working_copy = True
        elif token in {"--help", "-h", "--version", "-V"}:
            return None
        matched = _option(token, _GLOBAL_VALUE_OPTIONS)
        if matched is not None:
            name, value = matched
            if value is None:
                position += 1
                value = arguments[position] if position < len(arguments) else ""
            if name in {"-R", "--repository"} and value:
                directory = _resolve(directory, value)
        position += 1

    words: list[str] = []
    if position < len(arguments):
        words.append(arguments[position])
        position += 1
        group = _NESTED.get(words[0])
        if group is not None:
            words[0] = group
            while position < len(arguments) and arguments[position].startswith("-"):
                position += 1
            if position < len(arguments):
                words.append(arguments[position])
                position += 1
    subcommand = " ".join(words)
    if words and words[0] in _NO_WORKING_COPY:
        return None

    invocation = Invocation(directory, subcommand, ignore_working_copy)
    if not invocation.mutating:
        return invocation

    positional_revisions = subcommand in _POSITIONAL_REVISIONS
    options_done = False
    rest = arguments[position:]
    index = 0
    while index < len(rest):
        token = rest[index]
        index += 1
        if _REDIRECT_ALONE.match(token):
            index += 1
            continue
        if _REDIRECT_ATTACHED.match(token):
            continue
        if not options_done and token == "--":
            options_done = True
            continue
        if not options_done and token.startswith("-") and len(token) > 1:
            revision = _option(token, _REVISION_OPTIONS)
            if revision is not None:
                value = revision[1]
                if value is None and index < len(rest):
                    value = rest[index]
                    index += 1
                if value is not None:
                    _record(invocation, value, assignments)
                continue
            other = _option(token, _VALUE_OPTIONS)
            if other is not None and other[1] is None:
                index += 1
            continue
        if positional_revisions:
            _record(invocation, token, assignments)
    return invocation


def _record(invocation: Invocation, value: str, assignments: dict[str, str]) -> None:
    if "$" in value or "`" in value:
        match = _VARIABLE.match(value)
        name = match and (match.group(1) or match.group(2))
        if name and name in assignments:
            invocation.revisions.append(assignments[name])
        else:
            invocation.unexpanded.append(value)
        return
    invocation.revisions.append(value)


def candidates(revision: str) -> list[str]:
    """Hex commit-id atoms and `change/N` offsets inside one revset argument."""
    return [*_HEX_ATOM.findall(revision), *_CHANGE_OFFSET.findall(revision)]


# --- jj queries ---------------------------------------------------------------


def _jj(directory: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["jj", "--no-pager", "--ignore-working-copy", "--color", "never", *args],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=JJ_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def workspace_root(directory: Path) -> Path | None:
    try:
        directory = directory.resolve()
    except OSError:
        return None
    for candidate in (directory, *directory.parents):
        if (candidate / ".jj").is_dir():
            return candidate
    return None


@dataclass(frozen=True)
class Hidden:
    token: str
    commit_id: str
    change_id: str


def hidden_commits(directory: Path, tokens: list[str]) -> list[Hidden]:
    """Which of `tokens` resolve to hidden commits, in one jj call when possible."""
    unique = list(dict.fromkeys(tokens))
    if not unique:
        return []
    rows = _resolve_tokens(directory, unique)
    if rows is None:
        # One unresolvable token (ambiguous prefix, `/N` on an older jj) fails
        # the whole union; fall back to asking about each token alone.
        rows = {}
        for token in unique:
            single = _resolve_tokens(directory, [token])
            if single:
                rows.update(single)
    return [Hidden(token, *rows[token]) for token in unique if token in rows]


def _resolve_tokens(directory: Path, tokens: list[str]) -> dict[str, tuple[str, str]] | None:
    revset = " | ".join(f"present({token})" for token in tokens)
    output = _jj(directory, "log", "--no-graph", "-r", revset, "-T", _HIDDEN_TEMPLATE)
    if output is None:
        return None
    lines = [line.split() for line in output.splitlines() if line.strip()]
    found: dict[str, tuple[str, str]] = {}
    offsets = [token for token in tokens if "/" in token]
    for token in tokens:
        if "/" in token:
            continue
        for commit_id, change_id, hidden in lines:
            if commit_id.startswith(token) and hidden == "true":
                found[token] = (commit_id, change_id)
    if offsets:
        if len(tokens) != 1:
            return None  # offsets cannot be matched to rows; ask one at a time
        if len(lines) == 1 and lines[0][2] == "true":
            found[offsets[0]] = (lines[0][0], lines[0][1])
    return found


def visible_versions(directory: Path, change_id: str) -> list[str] | None:
    template = 'commit_id.shortest(12) ++ "\\n"'
    for revset in (f"change_id({change_id})", change_id):
        output = _jj(directory, "log", "--no-graph", "-r", f"present({revset})", "-T", template)
        if output is not None:
            return [line.strip() for line in output.splitlines() if line.strip()]
    return None


def stale_workspace(directory: Path) -> tuple[str, str] | None:
    """`(workspace name, working-copy operation)` when the workspace is stale.

    jj calls a working copy stale when the operation it last checked out
    recorded a different working-copy commit for this workspace than the
    current operation does. Read the checked-out operation from
    `.jj/working_copy/checkout` instead of running a jj command that would
    snapshot. When that operation is the only operation head, nothing can
    have moved, and no jj process runs at all.
    """
    root = workspace_root(directory)
    if root is None:
        return None
    try:
        operation, name = _read_checkout(root / ".jj" / "working_copy" / "checkout")
        repo = root / ".jj" / "repo"
        if repo.is_file():
            repo = (root / ".jj" / repo.read_text(encoding="utf-8").strip()).resolve()
        heads = os.listdir(repo / "op_heads" / "heads")
    except (OSError, ValueError, UnicodeDecodeError):
        return None
    if not operation or not name or heads == [operation]:
        return None
    template = 'name ++ " " ++ target.commit_id() ++ "\\n"'
    current = _jj(root, "workspace", "list", "-T", template)
    checked_out = _jj(root, "--at-op", operation, "workspace", "list", "-T", template)
    if current is None or checked_out is None:
        return None
    now = _workspace_commit(current, name)
    then = _workspace_commit(checked_out, name)
    if now is None or then is None or now == then:
        return None
    return name, operation[:12]


def _workspace_commit(output: str, name: str) -> str | None:
    for line in output.splitlines():
        workspace, _, commit = line.rpartition(" ")
        if workspace == name:
            return commit
    return None


def _read_checkout(path: Path) -> tuple[str, str]:
    """Decode jj's `Checkout` protobuf: field 2 operation id, field 3 workspace name."""
    data = path.read_bytes()
    operation = name = ""
    position = 0
    while position < len(data):
        key, position = _varint(data, position)
        number, wire = key >> 3, key & 7
        if wire == 0:
            _, position = _varint(data, position)
        elif wire == 2:
            length, position = _varint(data, position)
            value = data[position : position + length]
            position += length
            if number == 2:
                operation = value.hex()
            elif number == 3:
                name = value.decode("utf-8")
        elif wire == 1:
            position += 8
        elif wire == 5:
            position += 4
        else:
            raise ValueError(f"unexpected protobuf wire type {wire}")
    return operation, name


def _varint(data: bytes, position: int) -> tuple[int, int]:
    result = shift = 0
    while True:
        if position >= len(data):
            raise ValueError("truncated varint")
        byte = data[position]
        position += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, position
        shift += 7


# --- verdict ------------------------------------------------------------------


def evaluate(command: str, cwd: Path) -> Verdict | None:
    invocations = find_invocations(command, cwd)
    if not invocations:
        return None

    denials: list[str] = []
    warnings: list[str] = []

    by_root: dict[Path, list[Invocation]] = {}
    for invocation in invocations:
        root = workspace_root(invocation.directory)
        if root is not None:
            by_root.setdefault(root, []).append(invocation)

    for root, group in by_root.items():
        if any(not invocation.ignore_working_copy for invocation in group):
            stale = stale_workspace(root)
            if stale is not None:
                # Refuse only the command that performs the fork. A false stale
                # reading must never lock an agent out of jj, and update-stale in
                # a healthy workspace would have been a no-op anyway.
                if any(i.subcommand == "workspace update-stale" for i in group):
                    denials.append(_stale_message(*stale, group, refused=True))
                else:
                    warnings.append(_stale_message(*stale, group))

        mutating = [invocation for invocation in group if invocation.mutating]
        tokens = {
            token: invocation
            for invocation in mutating
            for revision in invocation.revisions
            for token in candidates(revision)
        }
        for hidden in hidden_commits(root, list(tokens)):
            denials.append(_hidden_message(hidden, tokens[hidden.token], root))
        for invocation in mutating:
            if invocation.unexpanded:
                warnings.append(_unexpanded_message(invocation))

    if denials:
        return Verdict(True, "\n\n".join(denials + warnings))
    if warnings:
        return Verdict(False, "\n\n".join(warnings))
    return None


def _hidden_message(hidden: Hidden, invocation: Invocation, root: Path) -> str:
    shown = hidden.token if "/" in hidden.token else hidden.token[:12]
    versions = visible_versions(root, hidden.change_id)
    if versions is None:
        current = "use the change id"
    elif not versions:
        current = (
            "it has no visible version (it was abandoned), so do not resurrect it; "
            "report this and ask"
        )
    elif len(versions) == 1:
        current = f"use the change id (current version: {versions[0]})"
    else:
        current = (
            f"it is already divergent (visible versions: {', '.join(versions)}); "
            "stop and load the jj-sensei harmony skill"
        )
    return (
        f"jj-sensei: {shown} is a hidden (rewritten) commit; {invocation.label} on it "
        "resurrects it and its whole hidden ancestry as divergent copies of their live "
        f"versions. Its change is {hidden.change_id} — {current}. Write the change id or "
        "a revset in the command itself so it is evaluated at that moment, and run the "
        "mutation as its own call."
    )


def _unexpanded_message(invocation: Invocation) -> str:
    values = ", ".join(invocation.unexpanded)
    return (
        f"jj-sensei: {invocation.label} takes its revision from {values}, a shell variable "
        "or command substitution this guard cannot check. A commit id captured earlier may "
        "have been rewritten by another workspace since, and a mutation on that hidden "
        "commit resurrects its hidden ancestry as divergent copies. Write the change id or "
        f"revset inline so it is evaluated at that moment (e.g. `{_INLINE_EXAMPLE}`), and "
        "run the mutation as its own Bash call — not chained after a long-running command "
        "and not in the background."
    )


def _stale_message(
    name: str, operation: str, group: list[Invocation], *, refused: bool = False
) -> str:
    facts = (
        f"jj-sensei: workspace {name} is STALE — its working copy was rewritten from "
        f"outside (not updated since operation {operation})"
    )
    if refused:
        return (
            f"{facts}, so a bare `jj workspace update-stale` is refused here: it would "
            "snapshot the on-disk edits at that old operation and can fork the change into "
            'divergent copies. Load the jj-sensei harmony skill and follow "Realign a stale '
            'workspace", then run its `repair` helper, which realigns under a lock with a '
            "resumable journal. Inspect read-only with "
            "`jj --no-pager --ignore-working-copy ...` meanwhile."
        )
    labels = ", ".join(dict.fromkeys(invocation.label for invocation in group))
    return (
        f"{facts}, and this call runs {labels} "
        "there. `jj workspace update-stale`, or any jj command when "
        "`snapshot.auto-update-stale` is set, snapshots the on-disk edits at that old "
        "operation and can fork the change into divergent copies. Stop: load the "
        'jj-sensei harmony skill and follow "Realign a stale workspace", which ends in '
        "its `repair` helper, never a bare `jj workspace update-stale`. Inspect read-only "
        "with `jj --no-pager --ignore-working-copy ...` meanwhile."
    )
