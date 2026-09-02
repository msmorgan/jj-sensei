import os
import subprocess
import sys
from pathlib import Path

import pytest

from jj_sensei import conflicts, jj

ROOT = Path(__file__).resolve().parent.parent
CONFLICTS = ROOT / "skills" / "harmony" / "scripts" / "conflicts"

# A qualifying conflict: branch X adds `import bcc`, branch Y adds `import ccc`,
# into a sorted block with `import aaa` above and `import eee` below.
QUALIFYING = """\
import aaa
<<<<<<< conflict 1 of 1
%%%%%%%
 import bbb
+import bcc
 import ddd
+++++++
import bbb
import ccc
import ddd
>>>>>>> conflict 1 of 1
import eee
"""

EXPECTED = """\
import aaa
import bbb
import bcc
import ccc
import ddd
import eee
"""


def _hunk(tmp_path, text):
    f = tmp_path / "f.txt"
    f.write_text(text)
    hunks, lines = conflicts.parse_file(f)
    return hunks[0], lines


def test_sorted_merge_qualifies(tmp_path):
    hunk, lines = _hunk(tmp_path, QUALIFYING)
    new_lines, n_adds = conflicts._sorted_merge_resolution(hunk, lines)
    assert new_lines is not None
    assert "".join(new_lines) == EXPECTED
    assert n_adds == 2


REMOVAL = """\
import aaa
<<<<<<< conflict 1 of 1
%%%%%%%
 import bbb
-import ddd
+import bcc
+++++++
import bbb
import ccc
import ddd
>>>>>>> conflict 1 of 1
import eee
"""

UNSORTED_BASE = """\
zzz
<<<<<<< conflict 1 of 1
%%%%%%%
 ddd
+ccc
 bbb
+++++++
ddd
aaa
bbb
>>>>>>> conflict 1 of 1
"""

TOO_SHORT = """\
<<<<<<< conflict 1 of 1
%%%%%%%
 bbb
+bcc
+++++++
bbb
ccc
>>>>>>> conflict 1 of 1
"""


def test_declines_on_removal(tmp_path):
    hunk, lines = _hunk(tmp_path, REMOVAL)
    new_lines, reason = conflicts._sorted_merge_resolution(hunk, lines)
    assert new_lines is None
    assert reason == "removal present"


def test_declines_on_unsorted_base(tmp_path):
    hunk, lines = _hunk(tmp_path, UNSORTED_BASE)
    new_lines, reason = conflicts._sorted_merge_resolution(hunk, lines)
    assert new_lines is None
    assert reason == "base region not sorted"


def test_declines_on_short_run(tmp_path):
    hunk, lines = _hunk(tmp_path, TOO_SHORT)
    new_lines, reason = conflicts._sorted_merge_resolution(hunk, lines)
    assert new_lines is None
    assert reason.startswith("sorted run too short")


BLANK_APPEND = """import aaa
<<<<<<< conflict 1 of 1
%%%%%%%
 import bbb
+import eee
 import ccc
+++++++
import bbb
import ddd
import ccc
>>>>>>> conflict 1 of 1

import zzz_separate_group
"""

BLANK_APPEND_EXPECTED = """import aaa
import bbb
import ccc
import ddd
import eee

import zzz_separate_group
"""


def test_sorted_merge_appends_past_block_before_blank(tmp_path):
    hunk, lines = _hunk(tmp_path, BLANK_APPEND)
    new_lines, n_adds = conflicts._sorted_merge_resolution(hunk, lines)
    assert new_lines is not None  # must NOT decline: blank line is a normal group boundary
    assert "".join(new_lines) == BLANK_APPEND_EXPECTED
    assert n_adds == 2


SAME_ADD = """import aaa
<<<<<<< conflict 1 of 1
%%%%%%%
 import bbb
+import new
 import ddd
+++++++
import bbb
import new
import ddd
>>>>>>> conflict 1 of 1
import eee
"""

SAME_ADD_EXPECTED = """import aaa
import bbb
import ddd
import eee
import new
"""


def test_sorted_merge_dedups_identical_add(tmp_path):
    hunk, lines = _hunk(tmp_path, SAME_ADD)
    new_lines, n_adds = conflicts._sorted_merge_resolution(hunk, lines)
    assert "".join(new_lines) == SAME_ADD_EXPECTED
    assert n_adds == 1


PREPEND = """zzz non-import line
<<<<<<< conflict 1 of 1
%%%%%%%
 import bbb
+import aaa
 import ddd
+++++++
import bbb
import aab
import ddd
>>>>>>> conflict 1 of 1
import eee
"""

PREPEND_EXPECTED = """zzz non-import line
import aaa
import aab
import bbb
import ddd
import eee
"""


def test_sorted_merge_prepends_before_run_start(tmp_path):
    hunk, lines = _hunk(tmp_path, PREPEND)
    new_lines, n_adds = conflicts._sorted_merge_resolution(hunk, lines)
    assert new_lines is not None
    assert "".join(new_lines) == PREPEND_EXPECTED
    assert n_adds == 2


def _run(*args, env_overrides=None):
    return subprocess.run(
        [sys.executable, str(CONFLICTS), *args],
        capture_output=True,
        text=True,
        env={**os.environ, **(env_overrides or {})},
    )


def _stub_jj(monkeypatch, returncode, stdout, stderr):
    result = subprocess.CompletedProcess(
        args=["jj"], returncode=returncode, stdout=stdout, stderr=stderr
    )
    monkeypatch.setattr(jj.subprocess, "run", lambda *args, **kwargs: result)


def test_list_normalizes_no_conflicts_to_empty_success(monkeypatch, capsys):
    _stub_jj(monkeypatch, 2, "", "Error: No conflicts found at this revision\n")
    assert conflicts.cmd_list([]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_list_reports_a_real_jj_failure(monkeypatch, capsys):
    _stub_jj(monkeypatch, 2, "", 'Error: There is no jj repo in "."\n')
    assert conflicts.cmd_list([]) == 2
    assert "no jj repo" in capsys.readouterr().err


def test_auto_resolves_qualifying_file(tmp_path):
    f = tmp_path / "imports.txt"
    f.write_text(QUALIFYING)
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == EXPECTED
    assert "sorted-merge" in r.stdout
    assert "resolved 1" in r.stdout


def test_auto_dry_run_changes_nothing(tmp_path):
    f = tmp_path / "imports.txt"
    f.write_text(QUALIFYING)
    r = _run("auto", "--dry-run", str(f))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == QUALIFYING  # unchanged
    assert "sorted-merge" in r.stdout


def test_auto_leaves_non_qualifying(tmp_path):
    f = tmp_path / "imports.txt"
    f.write_text(REMOVAL)
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == REMOVAL  # left untouched
    assert "left (removal present)" in r.stdout
    assert "resolved 0" in r.stdout


SNAPSHOT_REMOVAL = """import aaa
<<<<<<< conflict 1 of 1
%%%%%%%
 import bbb
+import ccc
 import ddd
+++++++
import ddd
>>>>>>> conflict 1 of 1
import zzz
"""


def test_declines_on_snapshot_side_removal(tmp_path):
    # The %%% side keeps `import bbb` as context and adds ccc; the +++ snapshot
    # side DELETED `import bbb`. Must decline (else bbb is silently resurrected).
    hunk, lines = _hunk(tmp_path, SNAPSHOT_REMOVAL)
    new_lines, reason = conflicts._sorted_merge_resolution(hunk, lines)
    assert new_lines is None
    assert reason == "removal present (snapshot side)"
    assert hunk["stackable"] is False


def test_accept_stack_declines_non_additive_conflict(tmp_path):
    f = tmp_path / "imports.txt"
    f.write_text(SNAPSHOT_REMOVAL)
    r = _run("accept", str(f), "stack")
    assert r.returncode == 1
    assert f.read_text() == SNAPSHOT_REMOVAL
    assert "not two pure additions" in r.stdout


def test_accept_stack_preserves_base_and_orders_additions(tmp_path):
    f = tmp_path / "imports.txt"
    f.write_text(QUALIFYING)
    r = _run("accept", str(f), "stack")
    assert r.returncode == 0, r.stderr
    assert f.read_text() == EXPECTED


def test_accept_stack_snapshot_first_reverses_only_addition_order(tmp_path):
    f = tmp_path / "imports.txt"
    f.write_text(QUALIFYING)
    r = _run("accept", str(f), "stack-snap-first")
    assert r.returncode == 0, r.stderr
    assert f.read_text() == EXPECTED.replace("import bcc\nimport ccc", "import ccc\nimport bcc")


def test_accept_sort_one_file(tmp_path):
    f = tmp_path / "imports.txt"
    f.write_text(QUALIFYING)
    r = _run("accept", str(f), "sort")
    assert r.returncode == 0, r.stderr
    assert f.read_text() == EXPECTED


# A blank line below the conflict must bound the run: the add stays in the upper
# group and the blank-separated lower group is untouched.
BLANK_GROUP = """\
import aaa
<<<<<<< conflict 1 of 1
%%%%%%%
 import bbb
+import bcc
 import ddd
+++++++
import bbb
import ccc
import ddd
>>>>>>> conflict 1 of 1

import zzz
"""

BLANK_GROUP_EXPECTED = """\
import aaa
import bbb
import bcc
import ccc
import ddd

import zzz
"""


def test_auto_respects_blank_group_boundary(tmp_path):
    f = tmp_path / "g.txt"
    f.write_text(BLANK_GROUP)
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == BLANK_GROUP_EXPECTED


def test_auto_mixed_file_resolves_one_leaves_other(tmp_path):
    # Concatenate a qualifying block and a removal (non-qualifying) block.
    f = tmp_path / "m.txt"
    f.write_text(QUALIFYING + REMOVAL)
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    txt = f.read_text()
    # qualifying hunk resolved...
    assert "import bcc\nimport ccc" in txt
    # ...removal hunk still has its markers
    assert "<<<<<<< conflict" in txt
    assert "resolved 1" in r.stdout
    assert "left (removal present)" in r.stdout


GIT_STYLE = """\
<<<<<<< left
left content
||||||| base
base content
=======
right content
>>>>>>> right
"""


def test_accept_declines_unsupported_marker_style(tmp_path):
    f = tmp_path / "git-style.txt"
    f.write_text(GIT_STYLE)
    r = _run("accept", str(f), "snapshot")
    assert r.returncode == 1
    assert f.read_text() == GIT_STYLE
    assert "Unsupported conflict marker style" in r.stderr


def test_auto_leaves_unsupported_marker_style(tmp_path):
    f = tmp_path / "git-style.txt"
    f.write_text(GIT_STYLE)
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == GIT_STYLE
    assert "left (unsupported marker style)" in r.stdout


# --- record-structured text is not a sorted list ----------------------------

# Verbatim from `jj new` on two commits that each added a package to this
# Cargo.lock. The base region is empty and the surrounding run — blank line,
# `[[package]]`, `name = "zzz"`, `version = "1.0.0"` — is non-decreasing by
# ASCII coincidence, so every sortedness guard passes honestly.
RECORD = """\
# This file is automatically @generated by Cargo.
# It is not intended for manual editing.
version = 4

[[package]]
name = "conformance-runner"
version = "0.0.0"

[[package]]
<<<<<<< conflict 1 of 1
%%%%%%% diff from: uqywvkpy aa65709d "base"
\\\\\\\\\\\\\\        to: tpklvrqp f3b7433d "probe"
+name = "probe"
+version = "0.0.0"
+[[package]]
+++++++ nzuormno bd915b26 "quill"
name = "quill"
version = "0.0.0"
[[package]]
>>>>>>> conflict 1 of 1 ends
name = "zzz"
version = "1.0.0"
"""


def test_sorted_merge_declines_record_structured_adds(tmp_path):
    # Both sides add `[[package]]` and `version = "0.0.0"`. Deduping them would
    # leave one header and one version for two packages.
    hunk, lines = _hunk(tmp_path, RECORD)
    new_lines, reason = conflicts._sorted_merge_resolution(hunk, lines)
    assert new_lines is None
    assert "overlapping" in reason


# One side adds a record header that the run already contains; the other adds a
# single unrelated line, so the sides do not overlap with each other.
COLLIDES_WITH_RUN = """\
[[package]]
<<<<<<< conflict 1 of 1
%%%%%%%
 name = "aaa"
+[[package]]
 version = "1"
+++++++
name = "aaa"
name = "bbb"
version = "1"
>>>>>>> conflict 1 of 1
zzz
"""


def test_sorted_merge_declines_add_already_in_run(tmp_path):
    hunk, lines = _hunk(tmp_path, COLLIDES_WITH_RUN)
    new_lines, reason = conflicts._sorted_merge_resolution(hunk, lines)
    assert new_lines is None
    assert "already present in the run" in reason


def test_auto_leaves_record_structured_file_untouched(tmp_path):
    f = tmp_path / "deps.txt"
    f.write_text(RECORD)
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == RECORD
    assert "resolved 0 hunk(s), 1 left" in r.stdout


# --- generated files are regenerated, not merged ----------------------------


@pytest.mark.parametrize("name", ["Cargo.lock", "flake.lock", "package-lock.json", "go.sum"])
def test_auto_refuses_generated_files(tmp_path, name):
    f = tmp_path / name
    f.write_text(QUALIFYING)
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == QUALIFYING
    assert "regenerate it from its manifest" in r.stdout


def test_accept_sort_refuses_generated_files(tmp_path):
    f = tmp_path / "Cargo.lock"
    f.write_text(QUALIFYING)
    r = _run("accept", str(f), "sort")
    assert r.returncode == 0, r.stderr
    assert f.read_text() == QUALIFYING
    assert "regenerate it from its manifest" in r.stdout


def test_auto_summary_cautions_only_when_it_resolved_something(tmp_path):
    f = tmp_path / "imports.txt"
    f.write_text(QUALIFYING)
    resolved = _run("auto", str(f))
    assert "read the diff" in resolved.stdout

    g = tmp_path / "records.txt"
    g.write_text(RECORD)
    assert "read the diff" not in _run("auto", str(g)).stdout


# --- work-tree fidelity -----------------------------------------------------


def _write_raw(path, text):
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


def test_auto_preserves_crlf_line_endings(tmp_path):
    f = _write_raw(tmp_path / "imports.txt", QUALIFYING.replace("\n", "\r\n"))
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    assert f.read_bytes() == EXPECTED.replace("\n", "\r\n").encode()


def test_accept_preserves_crlf_line_endings(tmp_path):
    f = _write_raw(tmp_path / "imports.txt", QUALIFYING.replace("\n", "\r\n"))
    r = _run("accept", str(f), "diff")
    assert r.returncode == 0, r.stderr
    assert f.read_bytes() == (
        b"import aaa\r\nimport bbb\r\nimport bcc\r\nimport ddd\r\nimport eee\r\n"
    )


def test_resolution_does_not_reflow_a_form_feed(tmp_path):
    # `str.splitlines` breaks on form feed; a page-separated source file must not
    # gain line breaks just by passing through the resolver.
    source = QUALIFYING.replace("import eee\n", "\x0cimport eee\n")
    f = _write_raw(tmp_path / "imports.txt", source)
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    with f.open(encoding="utf-8", newline="") as handle:
        actual = handle.read()
    assert actual == EXPECTED.replace("import eee\n", "\x0cimport eee\n")


def test_non_utf8_locale_still_reads_utf8_content(tmp_path):
    f = _write_raw(tmp_path / "imports.txt", QUALIFYING.replace("import eee", "import éee"))
    # PYTHONUTF8=0 keeps the C locale from silently enabling UTF-8 mode, so a
    # read without an explicit encoding really would fail here.
    r = _run(
        "auto",
        str(f),
        env_overrides={"LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"},
    )
    assert r.returncode == 0, r.stderr
    assert f.read_text(encoding="utf-8") == EXPECTED.replace("import eee", "import éee")


# --- `jj resolve --list` row parsing ----------------------------------------


def test_conflict_path_survives_a_longer_description():
    # A delete/modify conflict adds words to the description; a fixed word count
    # would return a path that does not exist and skip the file silently.
    assert jj.parse_conflict_path("del.txt    2-sided conflict including 1 deletion") == "del.txt"
    assert (
        jj.parse_conflict_path("exe.txt    2-sided conflict including an executable") == "exe.txt"
    )


def test_conflict_path_keeps_internal_spaces():
    assert jj.parse_conflict_path("a b.txt    2-sided conflict") == "a b.txt"
    assert jj.parse_conflict_path("a  b.txt    3-sided conflict") == "a  b.txt"


def test_conflict_path_survives_the_collapsed_single_space_column():
    # jj pads the path column to `min(longest_path, 32) + 3` and then writes one
    # more space, so a path of 35 characters or more gets exactly one space
    # before its description. Requiring a run of spaces skipped these files.
    row = "a/very/deeply/nested/directory/tree/module.py 2-sided conflict"
    assert jj.parse_conflict_path(row) == "a/very/deeply/nested/directory/tree/module.py"
    assert jj.parse_conflict_path("x" * 35 + " 2-sided conflict including 1 deletion") == "x" * 35


def test_conflict_path_reads_a_multi_object_description():
    # Several special objects are joined with commas and a trailing "and".
    row = "w.txt  4-sided conflict including 2 deletions, an executable and a symlink"
    assert jj.parse_conflict_path(row) == "w.txt"
    assert (
        jj.parse_conflict_path("v  2-sided conflict including a directory and a git submodule")
        == "v"
    )


def test_conflict_path_prefers_the_trailing_description():
    # A single space is a legal separator, so a path that itself looks like a
    # description is only resolved by anchoring the real one to end of line.
    row = "notes 2-sided conflict.txt 2-sided conflict"
    assert jj.parse_conflict_path(row) == "notes 2-sided conflict.txt"


def test_conflict_path_refuses_an_unreadable_row():
    with pytest.raises(RuntimeError, match="could not read a path"):
        jj.parse_conflict_path("something entirely unexpected")
    # Trailing prose is not a description; guessing a path out of it would name
    # a file that does not exist.
    with pytest.raises(RuntimeError, match="could not read a path"):
        jj.parse_conflict_path("f.txt  2-sided conflict including a wombat")


def test_conflict_files_parses_every_row(monkeypatch):
    listing = "a b.txt    2-sided conflict\ndel.txt    2-sided conflict including 1 deletion\n"
    _stub_jj(monkeypatch, 0, listing, "")
    assert jj.Jj().conflict_files() == ["a b.txt", "del.txt"]
