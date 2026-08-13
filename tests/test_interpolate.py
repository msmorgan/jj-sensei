from __future__ import annotations

import subprocess

import pytest

from jj_sensei import interpolate
from jj_sensei.interpolate import StateStore, run_abort, run_begin, run_finish
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
