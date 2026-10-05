from __future__ import annotations

import subprocess
import uuid

import pytest

from jj_sensei import repair
from jj_sensei.jj import Jj, JjError
from jj_sensei.repair import (
    EXIT_CLEAN,
    EXIT_EDIT_REQUIRED,
    EXIT_HUMAN_REQUIRED,
    EXIT_INTERNAL_ERROR,
    EXIT_LOCK_TIMEOUT,
    HumanRequired,
    LockTimeout,
    ResolutionState,
    StateStore,
    WorkspaceLock,
    converge,
    has_native_converge,
    run_converge,
    run_repair,
    run_resolve,
)
from jj_sensei.setup import run_setup


@pytest.fixture
def native_converge(jj_repo):
    if not has_native_converge(Jj(jj_repo.root)):
        pytest.skip("the installed jj has no `jj converge` (added in 0.45)")


@pytest.fixture
def legacy_converge(monkeypatch):
    """Take the path used on a jj without `jj converge`."""
    monkeypatch.setattr(repair, "has_native_converge", lambda _jj: False)


def test_guarded_helper_exit_status_contract():
    assert EXIT_CLEAN == 0
    assert EXIT_EDIT_REQUIRED == 1
    assert EXIT_INTERNAL_ERROR == 70
    assert EXIT_LOCK_TIMEOUT == 75
    assert EXIT_HUMAN_REQUIRED == 80


def _make_conflicted_feature(jj_repo):
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")

    jj_repo.write(jj_repo.root, "f.txt", "trunk\n")
    jj_repo.commit(jj_repo.root, "trunk edit")
    jj_repo.write(feature, "f.txt", "feature\n")
    jj_repo.commit(feature, "feature edit")
    jj_repo.run(
        feature,
        "rebase",
        "-s",
        "roots(default@..@)",
        "-d",
        "default@-",
    )
    assert Jj(feature).commits("::@ & conflicts()")
    return feature


def test_repair_walks_a_real_conflict_and_resumes(jj_repo):
    feature = _make_conflicted_feature(jj_repo)

    tip_change_id = Jj(feature).one_commit("@").change_id

    assert run_repair(feature) == 1
    store = StateStore(feature)
    state = store.load()
    assert state is not None
    assert state.phase == "editing"
    assert "<<<<<<< conflict" in (feature / "f.txt").read_text()

    jj_repo.write(feature, "f.txt", "trunk\nfeature\n")
    assert run_repair(feature) == 0

    assert store.load() is None
    assert Jj(feature).one_commit("@").change_id == tip_change_id
    assert Jj(feature).commits("::@ & conflicts()") == []
    assert (feature / "f.txt").read_text() == "trunk\nfeature\n"


def test_resolve_entry_point_runs_from_a_feature_workspace(jj_repo):
    feature = _make_conflicted_feature(jj_repo)

    assert run_resolve(feature) == 1
    jj_repo.write(feature, "f.txt", "trunk\nfeature\n")
    assert run_resolve(feature) == 0

    assert StateStore(feature).load() is None
    assert Jj(feature).commits("::@ & conflicts()") == []


def test_repair_auto_resolves_sorted_additions_in_one_run(jj_repo):
    base = "import aaa\nimport bbb\nimport ddd\nimport eee\n"
    jj_repo.write(jj_repo.root, "f.txt", base)
    jj_repo.commit(jj_repo.root, "sorted base")
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")

    jj_repo.write(
        jj_repo.root,
        "f.txt",
        "import aaa\nimport bbb\nimport ccc\nimport ddd\nimport eee\n",
    )
    jj_repo.commit(jj_repo.root, "trunk sorted add")
    jj_repo.write(
        feature,
        "f.txt",
        "import aaa\nimport bbb\nimport bcc\nimport ddd\nimport eee\n",
    )
    jj_repo.commit(feature, "feature sorted add")
    jj_repo.run(
        feature,
        "rebase",
        "-s",
        "roots(default@..@)",
        "-d",
        "default@-",
    )

    assert run_repair(feature) == 0
    assert (feature / "f.txt").read_text() == (
        "import aaa\nimport bbb\nimport bcc\nimport ccc\nimport ddd\nimport eee\n"
    )
    assert Jj(feature).commits("::@ & conflicts()") == []


def test_repair_starts_at_oldest_conflicted_change(jj_repo):
    jj_repo.write(jj_repo.root, "g.txt", "base\n")
    jj_repo.commit(jj_repo.root, "two-file base")
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")

    jj_repo.write(jj_repo.root, "f.txt", "trunk f\n")
    jj_repo.write(jj_repo.root, "g.txt", "trunk g\n")
    jj_repo.commit(jj_repo.root, "trunk edits")

    jj_repo.write(feature, "f.txt", "feature f\n")
    jj_repo.commit(feature, "first feature edit")
    oldest_change_id = Jj(feature).one_commit("@-").change_id
    jj_repo.write(feature, "g.txt", "feature g\n")
    jj_repo.commit(feature, "second feature edit")
    jj_repo.run(
        feature,
        "rebase",
        "-s",
        "roots(default@..@)",
        "-d",
        "default@-",
    )

    assert run_repair(feature) == 1
    state = StateStore(feature).load()
    assert state is not None
    assert state.target_change_id == oldest_change_id


def test_repair_reconciles_crash_after_new(jj_repo):
    feature = _make_conflicted_feature(jj_repo)
    jj = Jj(feature)
    tip = jj.one_commit("@")
    target = jj.commits("roots(::@ & conflicts() & mutable())")[0]
    run_id = uuid.uuid4().hex
    pin = f"jj-sensei: repair cursor {run_id}"
    state = ResolutionState(
        version=2,
        run_id=run_id,
        workspace_name="feature",
        workspace_root=str(feature),
        tip_change_id=tip.change_id,
        phase="start_pending",
        target_change_id=target.change_id,
        before_change_id=tip.change_id,
        tip_original_description=tip.description,
        tip_requires_pin=True,
        tip_pinned=True,
    )
    store = StateStore(feature)
    store.save(state)
    jj_repo.run(feature, "describe", "-m", pin)
    jj_repo.run(feature, "new", target.change_id)

    assert run_repair(feature) == 1
    resumed = store.load()
    assert resumed is not None
    assert resumed.phase == "editing"
    assert resumed.resolution_change_id == Jj(feature).one_commit("@").change_id


def test_repair_reconciles_crash_after_squash(jj_repo):
    feature = _make_conflicted_feature(jj_repo)
    assert run_repair(feature) == 1
    jj_repo.write(feature, "f.txt", "trunk\nfeature\n")
    jj_repo.run(feature, "st")

    store = StateStore(feature)
    state = store.load()
    assert state is not None
    target = Jj(feature).one_commit(state.target_change_id)
    state.phase = "fold_pending"
    state.destination_description = target.description
    store.save(state)
    jj_repo.run(feature, "squash", "-m", target.description)

    assert run_repair(feature) == 0
    assert store.load() is None
    assert Jj(feature).commits("::@ & conflicts()") == []


def test_repair_converges_stale_dirty_workspace_without_losing_edit(jj_repo):
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")

    jj_repo.write(jj_repo.root, "trunk.txt", "moved\n")
    jj_repo.commit(jj_repo.root, "move trunk")
    jj_repo.run(jj_repo.root, "rebase", "-r", "feature@", "-d", "default@-")
    jj_repo.write(feature, "precious.txt", "keep me\n")

    assert run_repair(feature) == 0
    assert (feature / "precious.txt").read_text() == "keep me\n"
    assert Jj(feature).commits("divergent()") == []


def _make_equivalent_divergence(jj_repo):
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")

    jj_repo.write(jj_repo.root, "trunk.txt", "moved\n")
    jj_repo.commit(jj_repo.root, "move trunk")
    jj_repo.run(jj_repo.root, "rebase", "-r", "feature@", "-d", "default@-")
    jj_repo.write(feature, "precious.txt", "keep me\n")
    jj_repo.run(feature, "workspace", "update-stale")

    jj = Jj(feature)
    current = jj.one_commit("@", snapshot=True)
    candidates = jj.commits(f"change_id({current.change_id})")
    assert len(candidates) == 2
    keeper = next(candidate for candidate in candidates if not candidate.empty)
    loser = next(candidate for candidate in candidates if candidate.empty)
    return feature, keeper, loser


def test_legacy_converge_allows_a_bookmark_on_the_keeper(jj_repo, legacy_converge):
    feature, keeper, _loser = _make_equivalent_divergence(jj_repo)
    jj_repo.run(feature, "bookmark", "create", "kept", "-r", keeper.commit_id)

    assert converge(Jj(feature))

    jj = Jj(feature)
    assert jj.commits("divergent()") == []
    assert jj.one_commit("kept").commit_id == jj.one_commit("@").commit_id


def test_legacy_converge_entry_point_runs_from_a_feature_workspace(jj_repo, legacy_converge):
    feature, keeper, _loser = _make_equivalent_divergence(jj_repo)

    assert run_converge(feature) == 0

    jj = Jj(feature)
    assert jj.commits("divergent()") == []
    assert jj.one_commit("@").commit_id == keeper.commit_id


def test_legacy_converge_pauses_before_abandoning_a_bookmarked_loser(jj_repo, legacy_converge):
    feature, _keeper, loser = _make_equivalent_divergence(jj_repo)
    jj_repo.run(feature, "bookmark", "create", "needs-decision", "-r", loser.commit_id)

    try:
        converge(Jj(feature))
    except HumanRequired as error:
        assert "would affect bookmarks" in str(error)
        assert "user, task, or repository workflow" in str(error)
    else:
        raise AssertionError("convergence abandoned a bookmarked candidate")

    jj = Jj(feature)
    assert len(jj.commits("divergent()")) == 2
    assert jj.one_commit("needs-decision").commit_id == loser.commit_id


def test_legacy_repair_refuses_different_nonempty_successors(jj_repo, capsys, legacy_converge):
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")

    jj_repo.write(feature, "left.txt", "left side\n")
    jj_repo.run(feature, "st")
    jj_repo.write(jj_repo.root, "trunk.txt", "moved\n")
    jj_repo.commit(jj_repo.root, "move trunk")
    jj_repo.run(jj_repo.root, "rebase", "-r", "feature@", "-d", "default@-")
    jj_repo.write(feature, "right.txt", "right side\n")

    assert run_repair(feature) == EXIT_HUMAN_REQUIRED
    error = capsys.readouterr().err
    assert "different nonempty work" in error
    assert "human judgment required" in error
    assert "no later transaction step was attempted" in error.casefold()
    assert Jj(feature).commits("divergent()")


def _files(jj_repo, cwd, revision="@"):
    return jj_repo.run(cwd, "file", "list", "-r", revision).stdout.split()


def test_converge_keeps_the_edit_and_the_rebase(jj_repo, native_converge):
    feature, _keeper, _loser = _make_equivalent_divergence(jj_repo)

    assert run_converge(feature) == EXIT_CLEAN

    assert Jj(feature).commits("divergent()") == []
    # One candidate held the edit, the other the new parent; neither is dropped.
    assert _files(jj_repo, feature) == ["f.txt", "precious.txt", "trunk.txt"]
    assert (feature / "trunk.txt").read_text() == "moved\n"


def test_converge_moves_a_bookmark_from_either_candidate_to_the_result(jj_repo, native_converge):
    feature, keeper, loser = _make_equivalent_divergence(jj_repo)
    jj_repo.run(feature, "bookmark", "create", "on-edit", "-r", keeper.commit_id)
    jj_repo.run(feature, "bookmark", "create", "on-empty", "-r", loser.commit_id)

    assert converge(Jj(feature))

    jj = Jj(feature)
    assert jj.commits("divergent()") == []
    result = jj.one_commit("@").commit_id
    assert jj.one_commit("on-edit").commit_id == result
    assert jj.one_commit("on-empty").commit_id == result


def test_repair_merges_different_nonempty_successors(jj_repo, native_converge):
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")

    jj_repo.write(feature, "left.txt", "left side\n")
    jj_repo.run(feature, "st")
    jj_repo.write(jj_repo.root, "trunk.txt", "moved\n")
    jj_repo.commit(jj_repo.root, "move trunk")
    jj_repo.run(jj_repo.root, "rebase", "-r", "feature@", "-d", "default@-")
    jj_repo.write(feature, "right.txt", "right side\n")

    assert run_repair(feature) == EXIT_CLEAN

    assert Jj(feature).commits("divergent()") == []
    assert _files(jj_repo, feature) == ["f.txt", "left.txt", "right.txt", "trunk.txt"]


def test_repair_walks_the_conflict_a_convergence_records(jj_repo, native_converge, capsys):
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")

    jj_repo.write(feature, "f.txt", "base\nshared start\n")
    jj_repo.run(feature, "st")
    jj_repo.write(jj_repo.root, "f.txt", "base\nfrom default\n")
    jj_repo.run(jj_repo.root, "restore", "--from", "default@", "--into", "feature@", "f.txt")
    jj_repo.write(feature, "f.txt", "base\nfrom feature\n")

    assert run_repair(feature) == EXIT_EDIT_REQUIRED
    assert Jj(feature).commits("divergent()") == []
    assert "f.txt" in capsys.readouterr().err

    jj_repo.write(feature, "f.txt", "base\nfrom both\n")
    assert run_repair(feature) == EXIT_CLEAN
    assert Jj(feature).commits("conflicts()") == []


def test_converge_stops_when_jj_needs_a_decision(jj_repo, native_converge, capsys):
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")
    jj_repo.write(feature, "work.txt", "work\n")
    jj_repo.run(feature, "describe", "-m", "first wording")
    jj_repo.run(feature, "describe", "-m", "second wording", "--at-op", "@-")

    assert run_converge(feature) == EXIT_HUMAN_REQUIRED

    error = capsys.readouterr().err
    assert "description" in error
    assert "2 successors remain" in error
    descriptions = {commit.description for commit in Jj(feature).commits("divergent()")}
    assert descriptions == {"first wording", "second wording"}


def test_converge_stops_at_an_immutable_candidate(jj_repo, native_converge, capsys):
    feature, keeper, _loser = _make_equivalent_divergence(jj_repo)
    jj_repo.run(feature, "tag", "set", "v1", "-r", keeper.commit_id)

    assert run_converge(feature) == EXIT_HUMAN_REQUIRED

    assert "is immutable" in capsys.readouterr().err
    assert len(Jj(feature).commits("divergent()")) == 2


def test_converge_refuses_a_candidate_another_workspace_is_editing(jj_repo, capsys):
    feature, keeper, _loser = _make_equivalent_divergence(jj_repo)
    other = jj_repo.add_workspace("other")
    jj_repo.run(other, "edit", keeper.commit_id)

    assert run_converge(feature) == EXIT_HUMAN_REQUIRED

    assert "working copies of other workspaces (other)" in capsys.readouterr().err
    assert len(Jj(feature).commits("divergent()")) == 2


def test_failed_jj_step_stops_before_any_followup(tmp_path, monkeypatch, capsys):
    root = tmp_path / "workspace"
    (root / ".jj").mkdir(parents=True)

    class FailingJj:
        def __init__(self, _cwd=None):
            self.calls = []

        def workspace_root(self):
            return root

        def run(self, *args):
            self.calls.append(args)
            result = subprocess.CompletedProcess(
                ["jj", "--no-pager", *args],
                1,
                "",
                "workspace became stale again",
            )
            raise JjError(list(result.args), result)

    fake = FailingJj()
    monkeypatch.setattr("jj_sensei.repair.Jj", lambda _cwd=None: fake)

    assert run_repair(root) == EXIT_INTERNAL_ERROR
    assert fake.calls == [("workspace", "update-stale")]
    error = capsys.readouterr().err
    assert "internal error occurred" in error
    assert "no later transaction step was attempted" in error.casefold()
    assert "do not improvise recovery" in error


def test_workspace_lock_times_out_while_held(tmp_path):
    root = tmp_path / "workspace"
    (root / ".jj").mkdir(parents=True)
    with WorkspaceLock(root, timeout=0.01):
        try:
            with WorkspaceLock(root, timeout=0.01):
                raise AssertionError("second lock unexpectedly succeeded")
        except LockTimeout:
            pass


def test_repair_handles_a_path_longer_than_the_padded_column(jj_repo):
    """jj caps the path column at 32 characters and then writes one more space,
    so a long path is separated from its description by a single space. Reading
    the row on a run of spaces used to abort the whole repair."""
    long_path = "a/very/deeply/nested/directory/tree/module.py"
    assert len(long_path) >= 35

    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")

    jj_repo.write(jj_repo.root, long_path, "trunk\n")
    jj_repo.commit(jj_repo.root, "trunk adds a deeply nested module")
    jj_repo.write(feature, long_path, "feature\n")
    jj_repo.commit(feature, "feature adds the same module")
    jj_repo.run(feature, "rebase", "-s", "roots(default@..@)", "-d", "default@-")

    listing = Jj(feature).run("resolve", "--list").stdout
    assert f"{long_path} 2-sided conflict" in listing, listing
    assert Jj(feature).conflict_files() == [long_path]

    assert run_repair(feature) == 1
    assert StateStore(feature).load().phase == "editing"

    jj_repo.write(feature, long_path, "feature\n")
    assert run_repair(feature) == 0
    assert Jj(feature).commits("::@ & conflicts()") == []


def test_repair_handles_a_delete_modify_conflict(jj_repo):
    """`jj resolve --list` describes this one as "2-sided conflict including 1
    deletion". Reading the path back as a fixed word count yields a file that
    does not exist, which used to abort the whole repair."""
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")

    (jj_repo.root / "f.txt").unlink()
    jj_repo.commit(jj_repo.root, "trunk deletes f.txt")
    jj_repo.write(feature, "f.txt", "feature\n")
    jj_repo.commit(feature, "feature edits f.txt")
    jj_repo.run(feature, "rebase", "-s", "roots(default@..@)", "-d", "default@-")

    listing = Jj(feature).run("resolve", "--list").stdout
    assert "including 1 deletion" in listing
    assert Jj(feature).conflict_files() == ["f.txt"]

    # Stops for a human edit rather than dying on a path it could not read.
    assert run_repair(feature) == 1
    assert StateStore(feature).load().phase == "editing"

    jj_repo.write(feature, "f.txt", "feature\n")
    assert run_repair(feature) == 0
    assert Jj(feature).commits("::@ & conflicts()") == []
