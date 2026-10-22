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
    # `ccc` was written above `ddd`, which the other side replaced.
    assert "inserts lines beside the other side's change" in r.stdout
    assert "sorted-merge: removal present" in r.stdout
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
    assert "sorted-merge: removal present" in r.stdout


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


@pytest.mark.parametrize(
    "name",
    [
        "Cargo.lock",
        "flake.lock",
        "package-lock.json",
        "go.sum",
        "go.work.sum",
        ".terraform.lock.hcl",
        "gradle.lockfile",
        "packages.lock.json",
        "Package.resolved",
    ],
)
def test_auto_refuses_generated_files(tmp_path, name):
    f = tmp_path / name
    f.write_text(QUALIFYING)
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == QUALIFYING
    assert "regenerate it from its manifest" in r.stdout


def test_auto_refuses_minified_files(tmp_path):
    f = tmp_path / "bundle.min.js"
    f.write_text((SHAPES / "adjacent-line-edits.conflict").read_text())
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    assert "rebuild it from its source" in r.stdout
    assert "<<<<<<< conflict" in f.read_text()


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


# --- conflict shapes from real sessions -------------------------------------

# Minimised from the hunks `auto` met in a 2026 study of agent sessions (see
# docs/tickets/*/auto-resolver-zero-hunks.md). `NAME.conflict` is the marked-up
# file; `NAME.resolved`, when present, is the only acceptable resolution, and its
# absence means `auto` must leave the file untouched.
SHAPES = ROOT / "tests" / "fixtures" / "conflict-shapes"

INSERTS_BESIDE = "a side inserts lines beside the other side's change"
SHAPE_REASONS = {
    "same-line-edits": "both sides change the same line",
    "reflow-overlap": "both sides change the same line",
    "competing-rewrites": "both sides change the same line",
    "competing-values": "both sides change the same line",
    "modify-delete": "both sides change the same line",
    "adjacent-block-replacements": INSERTS_BESIDE,
    "insertion-beside-edited-line": INSERTS_BESIDE,
    "edit-then-append": INSERTS_BESIDE,
    "insertion-beside-replaced-line": INSERTS_BESIDE,
    "replace-and-insert-beside-deletion": INSERTS_BESIDE,
    "inverted-condition-beside-insertion": INSERTS_BESIDE,
    "same-line-added-twice": INSERTS_BESIDE,
    "same-point-additions": "both sides insert at the same point",
    "generated-header": "its header says so",
    "generated-header-below-conflict": "its header says so",
    "three-sided": "many-sided conflict",
    "no-newline": "no-newline at EOF",
}


@pytest.mark.parametrize("fixture", sorted(SHAPES.glob("*.conflict")), ids=lambda p: p.stem)
def test_auto_on_recorded_conflict_shape(tmp_path, fixture):
    f = tmp_path / fixture.name
    f.write_text(fixture.read_text())
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    resolved = fixture.with_suffix(".resolved")
    if resolved.exists():
        assert f.read_text() == resolved.read_text()
        assert "disjoint-merge ✓" in r.stdout
        assert "read the diff" in r.stdout
    else:
        assert f.read_text() == fixture.read_text()
        assert "resolved 0 hunk(s)" in r.stdout
        assert SHAPE_REASONS[fixture.stem] in r.stdout


def test_every_declined_shape_names_its_reason():
    declined = {
        p.stem for p in SHAPES.glob("*.conflict") if not p.with_suffix(".resolved").exists()
    }
    assert declined == set(SHAPE_REASONS)


def test_same_point_additions_point_at_stack(tmp_path):
    f = tmp_path / "doc.md"
    f.write_text((SHAPES / "same-point-additions.conflict").read_text())
    assert "accept stack or stack-snap-first" in _run("auto", str(f)).stdout


def _disjoint(tmp_path, text):
    hunk, _ = _hunk(tmp_path, text)
    return conflicts._disjoint_resolution(hunk)


# Both sides make the same edit to the first line; their other edits touch. jj
# settles a wholly identical change itself, so this only arises inside a hunk.
IDENTICAL_AND_ADJACENT = """\
<<<<<<< conflict 1 of 1
%%%%%%%
-alpha = 1
+alpha = 2
 mid = 1
-beta = 1
+beta = 2
 gamma = 1
+++++++
alpha = 2
mid = 1
beta = 1
gamma = 2
>>>>>>> conflict 1 of 1 ends
"""


def test_disjoint_makes_an_identical_edit_once(tmp_path):
    lines, _ = _disjoint(tmp_path, IDENTICAL_AND_ADJACENT)
    assert "".join(lines) == "alpha = 2\nmid = 1\nbeta = 2\ngamma = 2\n"


# Two identical base lines: deleting "one of them" has two readings.
REPEATED_BASE = """\
<<<<<<< conflict 1 of 1
%%%%%%%
 }
-}
+++++++
}
}
tail()
>>>>>>> conflict 1 of 1 ends
"""


def test_disjoint_declines_a_base_region_with_repeated_lines(tmp_path):
    lines, reason = _disjoint(tmp_path, REPEATED_BASE)
    assert lines is None
    assert reason == "base region repeats a line"


# The snapshot adds a second `close()`: it could equally be read as inserting
# `close()` + `open()` before the old `close()`, which composes differently with
# the other side's edit.
SLIDING_ADD = """\
<<<<<<< conflict 1 of 1
%%%%%%%
-open()
+open(mode)
 close()
+++++++
open()
close()
open()
close()
>>>>>>> conflict 1 of 1 ends
"""


def test_disjoint_declines_an_addition_that_copies_a_base_line(tmp_path):
    lines, reason = _disjoint(tmp_path, SLIDING_ADD)
    assert lines is None
    assert reason == "a side adds a line the base region already has"


INSERT_INSIDE = """\
<<<<<<< conflict 1 of 1
%%%%%%%
-first()
-second()
+both()
+++++++
first()
middle()
second()
>>>>>>> conflict 1 of 1 ends
"""


def test_disjoint_declines_an_insertion_inside_the_other_change(tmp_path):
    lines, reason = _disjoint(tmp_path, INSERT_INSIDE)
    assert lines is None
    assert reason == "an insertion lands inside the other side's change"


INSERT_BESIDE_DELETION = """\
<<<<<<< conflict 1 of 1
%%%%%%%
-legacy_hook()
+++++++
legacy_hook()
new_hook()
>>>>>>> conflict 1 of 1 ends
"""


def test_disjoint_declines_an_insertion_beside_a_deleted_line(tmp_path):
    lines, reason = _disjoint(tmp_path, INSERT_BESIDE_DELETION)
    assert lines is None
    assert reason == INSERTS_BESIDE


def _hunk_from_sides(tmp_path, diff_lines, snapshot_lines):
    text = (
        "<<<<<<< conflict 1 of 1\n%%%%%%%\n"
        + "".join(f"{line}\n" for line in diff_lines)
        + "+++++++\n"
        + "".join(f"{line}\n" for line in snapshot_lines)
        + ">>>>>>> conflict 1 of 1 ends\n"
    )
    return _disjoint(tmp_path, text)


def test_disjoint_composes_an_edit_beside_a_deletion(tmp_path):
    lines, _ = _hunk_from_sides(tmp_path, ["-x = 1", "+x = 2", " y = 1"], ["x = 1"])
    assert "".join(lines) == "x = 2\n"


def test_disjoint_declines_a_shortened_range_beside_an_edit(tmp_path):
    # Two lines become one: which was dropped and which rewritten is unknown.
    lines, reason = _hunk_from_sides(
        tmp_path, ["-x = 1", "-y = 1", "+xy = 1", " z = 1"], ["x = 1", "y = 1", "z = 2"]
    )
    assert lines is None
    assert reason == "a side shortens lines beside the other side's change"


def test_disjoint_declines_the_same_line_written_by_both_sides(tmp_path):
    # Non-touching edits: an unchanged line separates them, yet both write
    # `release()`, which would then run twice.
    lines, reason = _hunk_from_sides(
        tmp_path,
        ["-work()", "+release()", " step()", " done()"],
        ["work()", "step()", "release()"],
    )
    assert lines is None
    assert reason == "both sides add the same line"


def test_disjoint_declines_a_side_equal_to_the_base(tmp_path):
    lines, reason = _hunk_from_sides(tmp_path, ["-x = 1", "+x = 2"], ["x = 1"])
    assert lines is None
    assert reason == "one side leaves the region unchanged"


# A three-sided conflict drawn with one diff and two snapshots: the parser keeps
# only the last snapshot, so a merge would silently drop the middle side.
TWO_SNAPSHOTS = """\
<<<<<<< conflict 1 of 1
%%%%%%%
-b
+B
 c
+++++++
b
C
+++++++
b
c2
>>>>>>> conflict 1 of 1 ends
"""


def test_auto_leaves_a_conflict_with_two_snapshots(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text(TWO_SNAPSHOTS)
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == TWO_SNAPSHOTS
    assert "many-sided conflict" in r.stdout


def test_generated_header_is_read_from_each_side_not_the_raw_file(tmp_path):
    # The header is line 10 on each side but far lower in the marked-up file.
    f = tmp_path / "api.pb.go"
    source = (SHAPES / "generated-header-below-conflict.conflict").read_text()
    f.write_text(source)
    assert (
        conflicts._split_lines(source).index("// Code generated by protoc-gen-go. DO NOT EDIT.\n")
        >= conflicts._GENERATED_HEADER_LINES
    )
    assert conflicts._generated_reason(f) is not None
    pushed = source.replace("// note 9\n", "// note 9\n// note 10\n")
    f.write_text(pushed)
    assert conflicts._generated_reason(f) is None


def test_auto_lists_every_merged_hunk_with_its_lines(tmp_path):
    merged = (SHAPES / "adjacent-line-edits.conflict").read_text()
    left = (SHAPES / "same-line-edits.conflict").read_text()
    f = tmp_path / "kind.py"
    f.write_text(left.replace("1 of 1", "1 of 2") + merged.replace("1 of 1", "2 of 2"))
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    text = f.read_text()
    first = text.index("        case Named")
    line = text[:first].count("\n") + 1
    assert "inspect each before continuing" in r.stdout
    assert f"{f}:{line}-{line + 1} (disjoint-merge)" in r.stdout


def test_auto_dry_run_lists_what_it_would_merge(tmp_path):
    f = tmp_path / "kind.py"
    f.write_text((SHAPES / "adjacent-line-edits.conflict").read_text())
    r = _run("auto", "--dry-run", str(f))
    assert "would be auto-merged" in r.stdout
    assert f"{f}:3-12 (disjoint-merge)" in r.stdout


def test_auto_names_a_hunk_that_resolved_to_no_lines(tmp_path):
    f = tmp_path / "list.py"
    f.write_text((SHAPES / "adjacent-deletions.conflict").read_text())
    r = _run("auto", str(f))
    assert f"{f}:2 (disjoint-merge; the hunk resolved to no lines)" in r.stdout


def test_accept_sort_does_not_merge_disjoint_edits(tmp_path):
    source = (SHAPES / "adjacent-line-edits.conflict").read_text()
    f = tmp_path / "kind.py"
    f.write_text(source)
    r = _run("accept", str(f), "sort")
    assert r.returncode == 0, r.stderr
    assert f.read_text() == source


def test_auto_resolves_disjoint_and_sorted_hunks_in_one_file(tmp_path):
    shape = (SHAPES / "adjacent-line-edits.conflict").read_text()
    f = tmp_path / "mixed.txt"
    f.write_text(QUALIFYING + shape.replace("conflict 1 of 1", "conflict 2 of 2"))
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    assert f.read_text() == EXPECTED + (SHAPES / "adjacent-line-edits.resolved").read_text()
    assert "resolved 2 hunk(s), 0 left" in r.stdout


def test_auto_disjoint_merge_preserves_crlf(tmp_path):
    shape = (SHAPES / "adjacent-line-edits.conflict").read_text()
    f = _write_raw(tmp_path / "kind.py", shape.replace("\n", "\r\n"))
    r = _run("auto", str(f))
    assert r.returncode == 0, r.stderr
    expected = (SHAPES / "adjacent-line-edits.resolved").read_text()
    assert f.read_bytes() == expected.replace("\n", "\r\n").encode()


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
