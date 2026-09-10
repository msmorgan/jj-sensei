from __future__ import annotations

import subprocess

import pytest

from jj_sensei import interpolate
from jj_sensei.interpolate import StateStore, run_abort, run_begin, run_finish, run_insert
from jj_sensei.jj import Jj, JjError
from jj_sensei.repair import EXIT_HUMAN_REQUIRED, EXIT_INTERNAL_ERROR
from jj_sensei.setup import run_setup


def _make_target(jj_repo):
    jj_repo.write(jj_repo.root, "catalog.json", '{"items":["alpha","beta"]}\n')
    jj_repo.write(
        jj_repo.root,
        "manifest.json",
        '{\n  "generated": [\n    "alpha",\n    "beta"\n  ]\n}\n',
    )
    jj_repo.run(jj_repo.root, "describe", "-m", "add alpha and beta")
    target = Jj(jj_repo.root).one_commit("@", snapshot=True)
    after = Jj(jj_repo.root).one_commit("@-")
    return after, target


def _write_intermediate(jj_repo):
    jj_repo.write(jj_repo.root, "catalog.json", '{"items":["alpha"]}\n')
    jj_repo.write(
        jj_repo.root,
        "manifest.json",
        '{\n  "generated": [\n    "alpha"\n  ]\n}\n',
    )


def _begin(jj_repo, after, target):
    return run_begin(
        jj_repo.root,
        after=after.change_id,
        before=target.change_id,
        message="add alpha",
    )


def test_interpolate_constructs_a_generated_intermediate_state(jj_repo):
    after, target = _make_target(jj_repo)

    assert _begin(jj_repo, after, target) == 1
    state = StateStore(jj_repo.root).load()
    assert state is not None
    assert state.phase == "editing"
    assert Jj(jj_repo.root).one_commit("@").description == "add alpha"

    _write_intermediate(jj_repo)
    assert run_finish(jj_repo.root) == 0

    jj = Jj(jj_repo.root)
    assert StateStore(jj_repo.root).load() is None
    assert jj.one_commit("@").change_id == target.change_id
    base = jj.one_commit("@-")
    assert base.description == "add alpha"
    assert jj.run("file", "show", "-r", base.change_id, "catalog.json").stdout == (
        '{"items":["alpha"]}\n'
    )
    assert jj.run("file", "show", "-r", target.change_id, "catalog.json").stdout == (
        '{"items":["alpha","beta"]}\n'
    )


def test_interpolate_runs_from_an_isolated_feature_workspace(jj_repo):
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")
    jj_repo.write(feature, "catalog.json", '{"items":["alpha","beta"]}\n')
    jj_repo.run(feature, "describe", "-m", "add alpha and beta")
    jj = Jj(feature)
    target = jj.one_commit("@", snapshot=True)
    after = jj.one_commit("@-")

    assert (
        run_begin(
            feature,
            after=after.change_id,
            before=target.change_id,
            message="add alpha",
        )
        == 1
    )
    state = StateStore(feature).load()
    assert state is not None
    assert state.workspace_name == "feature"
    assert state.workspace_root == str(feature)

    jj_repo.write(feature, "catalog.json", '{"items":["alpha"]}\n')
    assert run_finish(feature) == 0

    jj = Jj(feature)
    assert StateStore(feature).load() is None
    assert jj.one_commit("@").change_id == target.change_id
    base = jj.one_commit("@-")
    assert base.description == "add alpha"
    assert jj.run("file", "show", "-r", base.change_id, "catalog.json").stdout == (
        '{"items":["alpha"]}\n'
    )
    assert jj.run("file", "show", "-r", target.change_id, "catalog.json").stdout == (
        '{"items":["alpha","beta"]}\n'
    )


def test_abort_restores_the_original_change_and_working_copy(jj_repo):
    after, target = _make_target(jj_repo)
    assert _begin(jj_repo, after, target) == 1
    state = StateStore(jj_repo.root).load()
    assert state is not None
    base_change_id = state.base_change_id
    _write_intermediate(jj_repo)

    assert run_abort(jj_repo.root) == 0

    jj = Jj(jj_repo.root)
    assert StateStore(jj_repo.root).load() is None
    assert jj.one_commit("@").change_id == target.change_id
    assert jj.commits(f"change_id({base_change_id})") == []
    assert jj.run("file", "show", "-r", target.change_id, "catalog.json").stdout == (
        '{"items":["alpha","beta"]}\n'
    )


def test_interpolate_returns_to_an_empty_working_copy_above_an_older_edge(jj_repo):
    after, target = _make_target(jj_repo)
    jj_repo.commit(jj_repo.root, "add alpha and beta")
    return_change_id = Jj(jj_repo.root).one_commit("@").change_id

    assert _begin(jj_repo, after, target) == 1
    _write_intermediate(jj_repo)
    assert run_finish(jj_repo.root) == 0

    current = Jj(jj_repo.root).one_commit("@")
    assert current.change_id == return_change_id
    assert current.empty
    assert current.description == ""
    assert StateStore(jj_repo.root).load() is None


def test_interpolate_selects_one_edge_of_a_merge(jj_repo):
    jj_repo.write(jj_repo.root, "left.txt", "left\n")
    jj_repo.run(jj_repo.root, "describe", "-m", "left")
    left = Jj(jj_repo.root).one_commit("@", snapshot=True)

    jj_repo.run(jj_repo.root, "new", "@-", "-m", "right")
    jj_repo.write(jj_repo.root, "right.txt", "right\n")
    right = Jj(jj_repo.root).one_commit("@", snapshot=True)

    jj_repo.run(jj_repo.root, "new", left.change_id, right.change_id, "-m", "merge")
    jj_repo.write(jj_repo.root, "merged.txt", "complete\n")
    target = Jj(jj_repo.root).one_commit("@", snapshot=True)

    assert (
        run_begin(
            jj_repo.root,
            after=left.change_id,
            before=target.change_id,
            message="prepare merge",
        )
        == 1
    )
    state = StateStore(jj_repo.root).load()
    assert state is not None
    base = Jj(jj_repo.root).one_commit(state.base_change_id)
    assert {
        parent.change_id for parent in Jj(jj_repo.root).commits(f"parents({base.change_id})")
    } == {left.change_id}
    assert {
        parent.change_id for parent in Jj(jj_repo.root).commits(f"parents({target.change_id})")
    } == {base.change_id, right.change_id}

    jj_repo.write(jj_repo.root, "merged.txt", "prepared\n")
    assert run_finish(jj_repo.root) == 0
    jj = Jj(jj_repo.root)
    assert jj.one_commit("@").change_id == target.change_id
    assert jj.run("file", "show", "-r", target.change_id, "merged.txt").stdout == "complete\n"


def test_abort_restores_only_the_selected_merge_edge(jj_repo):
    jj_repo.write(jj_repo.root, "left.txt", "left\n")
    jj_repo.run(jj_repo.root, "describe", "-m", "left")
    left = Jj(jj_repo.root).one_commit("@", snapshot=True)

    jj_repo.run(jj_repo.root, "new", "@-", "-m", "right")
    jj_repo.write(jj_repo.root, "right.txt", "right\n")
    right = Jj(jj_repo.root).one_commit("@", snapshot=True)

    jj_repo.run(jj_repo.root, "new", left.change_id, right.change_id, "-m", "merge")
    jj_repo.write(jj_repo.root, "merged.txt", "complete\n")
    target = Jj(jj_repo.root).one_commit("@", snapshot=True)

    assert (
        run_begin(
            jj_repo.root,
            after=left.change_id,
            before=target.change_id,
            message="prepare merge",
        )
        == 1
    )
    jj_repo.write(jj_repo.root, "merged.txt", "prepared\n")
    assert run_abort(jj_repo.root) == 0

    jj = Jj(jj_repo.root)
    assert jj.one_commit("@").change_id == target.change_id
    assert {parent.change_id for parent in jj.commits(f"parents({target.change_id})")} == {
        left.change_id,
        right.change_id,
    }
    assert jj.run("file", "show", "-r", target.change_id, "merged.txt").stdout == "complete\n"


def test_begin_refuses_endpoints_that_do_not_form_an_edge(jj_repo, capsys):
    after, target = _make_target(jj_repo)

    assert (
        run_begin(
            jj_repo.root,
            after="root()",
            before=target.change_id,
            message="not actually between them",
        )
        == EXIT_HUMAN_REQUIRED
    )
    assert "requested edge does not exist" in capsys.readouterr().err
    assert StateStore(jj_repo.root).load() is None


class _CrashAfterCommand:
    def __init__(self, root, command: str):
        self.delegate = Jj(root)
        self.command = command
        self.crashed = False

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def run(self, *args, **kwargs):
        result = self.delegate.run(*args, **kwargs)
        if not self.crashed and args[:1] == (self.command,):
            self.crashed = True
            failed = subprocess.CompletedProcess(
                result.args,
                1,
                result.stdout,
                "injected process death after command completed",
            )
            raise JjError(list(result.args), failed)
        return result


def _crash_after(monkeypatch, root, command: str):
    crashing = _CrashAfterCommand(root, command)
    monkeypatch.setattr(interpolate, "Jj", lambda _cwd=None: crashing)
    return crashing


@pytest.mark.parametrize("command", ["new", "restore"])
def test_begin_resumes_after_each_history_mutation(jj_repo, monkeypatch, command):
    after, target = _make_target(jj_repo)
    _crash_after(monkeypatch, jj_repo.root, command)

    assert _begin(jj_repo, after, target) == EXIT_INTERNAL_ERROR
    monkeypatch.setattr(interpolate, "Jj", Jj)
    assert _begin(jj_repo, after, target) == 1
    assert StateStore(jj_repo.root).load().phase == "editing"


def test_begin_resumes_after_pinning_an_empty_return_commit(jj_repo, monkeypatch):
    after, target = _make_target(jj_repo)
    jj_repo.commit(jj_repo.root, "add alpha and beta")
    return_change_id = Jj(jj_repo.root).one_commit("@").change_id
    _crash_after(monkeypatch, jj_repo.root, "describe")

    assert _begin(jj_repo, after, target) == EXIT_INTERNAL_ERROR
    monkeypatch.setattr(interpolate, "Jj", Jj)
    assert _begin(jj_repo, after, target) == 1
    state = StateStore(jj_repo.root).load()
    assert state is not None
    assert state.return_change_id == return_change_id
    assert state.return_pinned


def test_abort_after_interrupted_pin_removes_the_cursor(jj_repo, monkeypatch):
    after, target = _make_target(jj_repo)
    jj_repo.commit(jj_repo.root, "add alpha and beta")
    return_change_id = Jj(jj_repo.root).one_commit("@").change_id
    _crash_after(monkeypatch, jj_repo.root, "describe")

    assert _begin(jj_repo, after, target) == EXIT_INTERNAL_ERROR
    monkeypatch.setattr(interpolate, "Jj", Jj)
    assert run_abort(jj_repo.root) == 0

    current = Jj(jj_repo.root).one_commit("@")
    assert current.change_id == return_change_id
    assert current.description == ""
    assert StateStore(jj_repo.root).load() is None


def test_abort_after_interrupted_insert_removes_the_new_commit(jj_repo, monkeypatch):
    after, target = _make_target(jj_repo)
    _crash_after(monkeypatch, jj_repo.root, "new")

    assert _begin(jj_repo, after, target) == EXIT_INTERNAL_ERROR
    inserted_change_id = Jj(jj_repo.root).one_commit("@").change_id
    monkeypatch.setattr(interpolate, "Jj", Jj)
    assert run_abort(jj_repo.root) == 0

    jj = Jj(jj_repo.root)
    assert jj.one_commit("@").change_id == target.change_id
    assert jj.commits(f"change_id({inserted_change_id})") == []
    assert StateStore(jj_repo.root).load() is None


def test_finish_resumes_after_restoring_the_target(jj_repo, monkeypatch):
    after, target = _make_target(jj_repo)
    assert _begin(jj_repo, after, target) == 1
    _write_intermediate(jj_repo)
    _crash_after(monkeypatch, jj_repo.root, "restore")

    assert run_finish(jj_repo.root) == EXIT_INTERNAL_ERROR
    monkeypatch.setattr(interpolate, "Jj", Jj)
    assert run_finish(jj_repo.root) == 0
    assert Jj(jj_repo.root).one_commit("@").change_id == target.change_id


def test_finish_resumes_after_returning_to_the_original_working_copy(jj_repo, monkeypatch):
    after, target = _make_target(jj_repo)
    assert _begin(jj_repo, after, target) == 1
    _write_intermediate(jj_repo)
    _crash_after(monkeypatch, jj_repo.root, "edit")

    assert run_finish(jj_repo.root) == EXIT_INTERNAL_ERROR
    monkeypatch.setattr(interpolate, "Jj", Jj)
    assert run_finish(jj_repo.root) == 0
    assert Jj(jj_repo.root).one_commit("@").change_id == target.change_id


def test_finish_resumes_after_unpinning_the_original_working_copy(jj_repo, monkeypatch):
    after, target = _make_target(jj_repo)
    jj_repo.commit(jj_repo.root, "add alpha and beta")
    return_change_id = Jj(jj_repo.root).one_commit("@").change_id
    assert _begin(jj_repo, after, target) == 1
    _write_intermediate(jj_repo)
    _crash_after(monkeypatch, jj_repo.root, "describe")

    assert run_finish(jj_repo.root) == EXIT_INTERNAL_ERROR
    monkeypatch.setattr(interpolate, "Jj", Jj)
    assert run_finish(jj_repo.root) == 0

    current = Jj(jj_repo.root).one_commit("@")
    assert current.change_id == return_change_id
    assert current.description == ""
    assert StateStore(jj_repo.root).load() is None


@pytest.mark.parametrize("command", ["restore", "abandon", "edit"])
def test_abort_resumes_after_each_history_mutation(jj_repo, monkeypatch, command):
    after, target = _make_target(jj_repo)
    assert _begin(jj_repo, after, target) == 1
    _write_intermediate(jj_repo)
    _crash_after(monkeypatch, jj_repo.root, command)

    assert run_abort(jj_repo.root) == EXIT_INTERNAL_ERROR
    monkeypatch.setattr(interpolate, "Jj", Jj)
    assert run_abort(jj_repo.root) == 0
    assert StateStore(jj_repo.root).load() is None
    assert Jj(jj_repo.root).one_commit("@").change_id == target.change_id


def _make_snapshots(jj_repo):
    snapshots = []
    for value in (1, 2):
        jj_repo.write(jj_repo.root, "f.txt", f"value = {value}\n")
        snapshots.append(Jj(jj_repo.root).one_commit("@", snapshot=True))
    jj_repo.write(jj_repo.root, "f.txt", "value = 3\n")
    jj_repo.write(jj_repo.root, "later.txt", "only in final\n")
    target = Jj(jj_repo.root).one_commit("@", snapshot=True)
    return snapshots, target


def _insert(jj_repo, snapshot, target, message="checkpoint"):
    return run_insert(
        jj_repo.root, source=snapshot.commit_id, before=target.change_id, message=message
    )


def test_snapshot_series_preserves_working_copy_and_produces_incremental_diffs(jj_repo):
    snapshots, target = _make_snapshots(jj_repo)
    jj = Jj(jj_repo.root)
    previous = jj.one_commit("@-")
    for i, snapshot in enumerate(snapshots, 1):
        assert _insert(jj_repo, snapshot, target, f"checkpoint {i}") == 0
        current = jj.one_commit("@")
        assert current.change_id == target.change_id
        assert not jj.diff_between(current.commit_id, target.commit_id)
        assert (jj_repo.root / "f.txt").read_text() == "value = 3\n"
        assert (jj_repo.root / "later.txt").read_text() == "only in final\n"
        inserted = jj.one_commit("@-")
        assert inserted.description == f"checkpoint {i}"
        assert jj.one_commit("@--").change_id == previous.change_id
        assert not jj.diff_between(inserted.commit_id, snapshot.commit_id)
        assert not inserted.conflict
        previous = inserted
    diff = jj.run("diff", "--git", "-r", previous.change_id).stdout
    assert "-value = 1" in diff and "+value = 2" in diff
    assert StateStore(jj_repo.root).load() is None


def test_snapshot_insertion_preserves_descendants_and_an_empty_working_copy(jj_repo):
    snapshots, target = _make_snapshots(jj_repo)
    jj_repo.commit(jj_repo.root, "target")
    jj_repo.write(jj_repo.root, "f.txt", "descendant edits the same line\n")
    jj_repo.commit(jj_repo.root, "descendant")
    jj = Jj(jj_repo.root)
    current = jj.one_commit("@")
    descendants = jj.commits(f"{target.change_id}::")

    assert _insert(jj_repo, snapshots[0], target) == 0

    assert jj.one_commit("@").change_id == current.change_id
    assert jj.one_commit("@").description == ""
    assert jj.one_commit("@").empty
    assert (jj_repo.root / "f.txt").read_text() == "descendant edits the same line\n"
    for old in descendants:
        new = jj.one_commit(old.change_id)
        assert new.description == old.description
        assert not jj.diff_between(old.commit_id, new.commit_id)


@pytest.mark.parametrize("command", ["new", "restore", "describe"])
def test_snapshot_insertion_resumes_after_each_mutation(jj_repo, monkeypatch, command):
    snapshots, target = _make_snapshots(jj_repo)
    _crash_after(monkeypatch, jj_repo.root, command)
    assert _insert(jj_repo, snapshots[0], target) == EXIT_INTERNAL_ERROR
    jj = Jj(jj_repo.root)
    assert jj.one_commit("@").change_id == target.change_id
    assert not jj.diff_between(jj.one_commit("@").commit_id, target.commit_id)
    inserted = jj.one_commit("@-")
    monkeypatch.setattr(interpolate, "Jj", Jj)

    assert _insert(jj_repo, snapshots[0], target) == 0

    assert jj.one_commit("@-").change_id == inserted.change_id
    assert jj.one_commit("@-").description == "checkpoint"
    assert not jj.diff_between(jj.one_commit("@-").commit_id, snapshots[0].commit_id)
    assert StateStore(jj_repo.root).load() is None


@pytest.mark.parametrize("command", ["new", "restore", "describe"])
def test_snapshot_abort_discards_only_its_checkpoint(jj_repo, monkeypatch, command):
    snapshots, target = _make_snapshots(jj_repo)
    jj = Jj(jj_repo.root)
    original_parent = jj.one_commit("@-")
    _crash_after(monkeypatch, jj_repo.root, command)
    assert _insert(jj_repo, snapshots[0], target) == EXIT_INTERNAL_ERROR
    inserted = jj.one_commit("@-")
    monkeypatch.setattr(interpolate, "Jj", Jj)

    assert run_abort(jj_repo.root) == 0

    assert jj.one_commit("@").change_id == target.change_id
    assert not jj.diff_between(jj.one_commit("@").commit_id, target.commit_id)
    assert jj.one_commit("@-").commit_id == original_parent.commit_id
    assert not jj.commits(f"change_id({inserted.change_id})")
    assert StateStore(jj_repo.root).load() is None


def test_snapshot_abort_resumes_after_abandon(jj_repo, monkeypatch):
    snapshots, target = _make_snapshots(jj_repo)
    _crash_after(monkeypatch, jj_repo.root, "restore")
    assert _insert(jj_repo, snapshots[0], target) == EXIT_INTERNAL_ERROR
    _crash_after(monkeypatch, jj_repo.root, "abandon")
    assert run_abort(jj_repo.root) == EXIT_INTERNAL_ERROR
    monkeypatch.setattr(interpolate, "Jj", Jj)
    assert run_abort(jj_repo.root) == 0
    assert StateStore(jj_repo.root).load() is None


@pytest.mark.parametrize("destination", ["target", "checkpoint"])
def test_snapshot_resume_and_abort_preserve_external_edits(jj_repo, monkeypatch, destination):
    snapshots, target = _make_snapshots(jj_repo)
    _crash_after(monkeypatch, jj_repo.root, "new")
    assert _insert(jj_repo, snapshots[0], target) == EXIT_INTERNAL_ERROR
    monkeypatch.setattr(interpolate, "Jj", Jj)
    jj = Jj(jj_repo.root)
    if destination == "checkpoint":
        checkpoint = jj.one_commit("@-")
        jj_repo.run(
            jj_repo.root,
            "restore",
            "--from",
            snapshots[1].commit_id,
            "--into",
            checkpoint.change_id,
            "--restore-descendants",
        )
        edited = jj.one_commit(checkpoint.change_id)
    else:
        jj_repo.write(jj_repo.root, "f.txt", "external edit\n")
        edited = jj.one_commit("@", snapshot=True)

    assert _insert(jj_repo, snapshots[0], target) == EXIT_HUMAN_REQUIRED
    assert run_abort(jj_repo.root) == EXIT_HUMAN_REQUIRED
    assert jj.one_commit(edited.change_id).commit_id == edited.commit_id
    assert StateStore(jj_repo.root).load() is not None


def test_snapshot_insertion_rejects_changed_base_content(jj_repo, capsys):
    snapshots, target = _make_snapshots(jj_repo)
    jj_repo.run(jj_repo.root, "new", "@-", "-m", "unrelated base change")
    jj_repo.write(jj_repo.root, "unrelated.txt", "must stay in the base\n")
    jj_repo.run(jj_repo.root, "rebase", "-r", target.change_id, "-d", "@")
    jj_repo.run(jj_repo.root, "edit", target.change_id)
    jj = Jj(jj_repo.root)
    before = jj.one_commit("@", snapshot=True)

    assert _insert(jj_repo, snapshots[0], target) == EXIT_HUMAN_REQUIRED

    assert "incompatible" in capsys.readouterr().err
    assert jj.one_commit("@").commit_id == before.commit_id
    assert StateStore(jj_repo.root).load() is None


def test_snapshot_insertion_rejects_merge_target(jj_repo):
    snapshots, target = _make_snapshots(jj_repo)
    jj_repo.run(jj_repo.root, "new", "@-", "-m", "sibling")
    jj_repo.write(jj_repo.root, "sibling.txt", "sibling\n")
    jj_repo.run(jj_repo.root, "new", "@", target.change_id, "-m", "merge")
    jj_repo.write(jj_repo.root, "merge.txt", "merge content\n")
    merge = Jj(jj_repo.root).one_commit("@", snapshot=True)
    assert _insert(jj_repo, snapshots[0], merge) == EXIT_HUMAN_REQUIRED
    assert StateStore(jj_repo.root).load() is None


def test_snapshot_resume_rejects_different_request_and_wrong_phase(jj_repo, monkeypatch):
    snapshots, target = _make_snapshots(jj_repo)
    _crash_after(monkeypatch, jj_repo.root, "new")
    assert _insert(jj_repo, snapshots[0], target) == EXIT_INTERNAL_ERROR
    monkeypatch.setattr(interpolate, "Jj", Jj)
    assert _insert(jj_repo, snapshots[1], target) == EXIT_HUMAN_REQUIRED
    assert run_finish(jj_repo.root) == EXIT_HUMAN_REQUIRED
    assert run_begin(jj_repo.root, after="@-", before="@", message="other") == EXIT_HUMAN_REQUIRED
    assert _insert(jj_repo, snapshots[0], target) == 0


class _CrashBeforeCommand(_CrashAfterCommand):
    def run(self, *args, **kwargs):
        if not self.crashed and args[:1] == (self.command,):
            self.crashed = True
            failed = subprocess.CompletedProcess(args, 1, "", "injected death before command")
            raise JjError(["jj", "--no-pager", *args], failed)
        return self.delegate.run(*args, **kwargs)


@pytest.mark.parametrize("command", ["new", "restore", "describe"])
@pytest.mark.parametrize("abort", [False, True])
def test_snapshot_recovers_when_a_journaled_command_never_ran(jj_repo, monkeypatch, command, abort):
    snapshots, target = _make_snapshots(jj_repo)
    jj = Jj(jj_repo.root)
    count = len(jj.commits("all()"))
    crashing = _CrashBeforeCommand(jj_repo.root, command)
    monkeypatch.setattr(interpolate, "Jj", lambda _cwd=None: crashing)
    assert _insert(jj_repo, snapshots[0], target) == EXIT_INTERNAL_ERROR
    monkeypatch.setattr(interpolate, "Jj", Jj)

    assert (run_abort(jj_repo.root) if abort else _insert(jj_repo, snapshots[0], target)) == 0
    assert len(jj.commits("all()")) == count + (0 if abort else 1)
    assert not jj.diff_between(target.commit_id, jj.one_commit(target.change_id).commit_id)
    assert jj.one_commit("@").change_id == target.change_id
    assert StateStore(jj_repo.root).load() is None


def test_snapshot_refuses_a_replaced_insertion_edge(jj_repo, monkeypatch):
    snapshots, target = _make_snapshots(jj_repo)
    _crash_after(monkeypatch, jj_repo.root, "new")
    assert _insert(jj_repo, snapshots[0], target) == EXIT_INTERNAL_ERROR
    monkeypatch.setattr(interpolate, "Jj", Jj)
    jj_repo.run(
        jj_repo.root, "new", "--no-edit", "-B", target.change_id, "-m", "external insertion"
    )
    jj = Jj(jj_repo.root)
    external = jj.one_commit("@-")

    assert _insert(jj_repo, snapshots[0], target) == EXIT_HUMAN_REQUIRED
    assert run_abort(jj_repo.root) == EXIT_HUMAN_REQUIRED
    assert jj.one_commit("@-").commit_id == external.commit_id


def test_snapshot_respects_workspace_immutability(jj_repo, capsys):
    snapshots, target = _make_snapshots(jj_repo)
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")
    assert (
        run_insert(
            feature,
            source=snapshots[0].commit_id,
            before=target.change_id,
            message="must not rewrite default",
        )
        == EXIT_HUMAN_REQUIRED
    )
    assert "immutable" in capsys.readouterr().err
    assert StateStore(feature).load() is None

    jj_repo.write(feature, "feature.txt", "first\n")
    jj = Jj(feature)
    snapshot = jj.one_commit("@", snapshot=True)
    jj_repo.write(feature, "feature.txt", "second\n")
    own_target = jj.one_commit("@", snapshot=True)
    assert (
        run_insert(
            feature,
            source=snapshot.commit_id,
            before=own_target.change_id,
            message="feature checkpoint",
        )
        == 0
    )
    assert jj.one_commit("@").change_id == own_target.change_id
    assert jj.one_commit(target.change_id).commit_id == target.commit_id


def test_snapshot_cli_dispatch(jj_repo, monkeypatch):
    snapshots, target = _make_snapshots(jj_repo)
    monkeypatch.chdir(jj_repo.root)
    assert (
        interpolate.main(
            ["insert", "--from", snapshots[0].commit_id, "-B", "@", "-m", "CLI checkpoint"]
        )
        == 0
    )
    jj = Jj(jj_repo.root)
    assert jj.one_commit("@-").description == "CLI checkpoint"
    assert not jj.diff_between(jj.one_commit("@-").commit_id, snapshots[0].commit_id)
    assert jj.one_commit("@").change_id == target.change_id
