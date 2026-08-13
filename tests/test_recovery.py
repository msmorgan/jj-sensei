from __future__ import annotations

import pytest

from jj_sensei.jj import Jj
from jj_sensei.recovery import (
    content_at,
    distinct_states,
    render,
    safe_operation,
    snapshots,
)


def test_safe_operation_refuses_anything_but_a_hex_id():
    assert safe_operation("b61ed259900e") == "b61ed259900e"
    for value in ("", "@", "abc; rm -rf /", "../..", "ZZZZ"):
        with pytest.raises(ValueError):
            safe_operation(value)


def test_snapshots_selects_only_snapshot_operations(jj_repo):
    jj_repo.write(jj_repo.root, "f.txt", "one\n")
    jj_repo.run(jj_repo.root, "st")

    found = snapshots(Jj(jj_repo.root))

    assert found
    assert all(snapshot.operation_id and snapshot.time for snapshot in found)


def test_distinct_states_collapses_repeated_content(jj_repo):
    jj = Jj(jj_repo.root)
    jj_repo.write(jj_repo.root, "f.txt", "first\n")
    jj_repo.run(jj_repo.root, "st")
    jj_repo.run(jj_repo.root, "st")
    jj_repo.write(jj_repo.root, "f.txt", "second\n")
    jj_repo.run(jj_repo.root, "st")

    states = distinct_states(jj, "f.txt")

    assert [state.size for state in states] == [len("second\n"), len("first\n"), len("base\n")]
    assert len({state.digest for state in states}) == 3


def test_content_at_reads_an_earlier_state_and_reports_a_missing_path(jj_repo):
    jj = Jj(jj_repo.root)
    jj_repo.write(jj_repo.root, "f.txt", "changed\n")
    jj_repo.run(jj_repo.root, "st")

    states = distinct_states(jj, "f.txt")
    oldest = states[-1]

    assert content_at(jj, oldest.snapshot.operation_id, "f.txt") == "base\n"
    assert content_at(jj, oldest.snapshot.operation_id, "absent.txt") is None


def test_render_explains_that_unsnapshotted_states_are_gone(jj_repo):
    assert "never recorded" in render("absent.txt", [])

    states = distinct_states(Jj(jj_repo.root), "f.txt")
    report = render("f.txt", states)

    assert "distinct recorded states of f.txt" in report
    assert "recover-file show OPERATION f.txt" in report
