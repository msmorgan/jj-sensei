from __future__ import annotations

import subprocess
import uuid

from jj_sensei.jj import Jj, JjError
from jj_sensei.repair import (
    HumanRequired,
    LockTimeout,
    ResolutionState,
    StateStore,
    WorkspaceLock,
    converge,
    run_repair,
)
from jj_sensei.setup import run_setup


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


def test_converge_allows_a_bookmark_on_the_keeper(jj_repo):
    feature, keeper, _loser = _make_equivalent_divergence(jj_repo)
    jj_repo.run(feature, "bookmark", "create", "kept", "-r", keeper.commit_id)

    assert converge(Jj(feature))

    jj = Jj(feature)
    assert jj.commits("divergent()") == []
    assert jj.one_commit("kept").commit_id == jj.one_commit("@").commit_id


def test_converge_pauses_before_abandoning_a_bookmarked_loser(jj_repo):
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


def test_repair_refuses_different_nonempty_successors(jj_repo, capsys):
    assert run_setup(jj_repo.root) == 0
    feature = jj_repo.add_workspace("feature")

    jj_repo.write(feature, "left.txt", "left side\n")
    jj_repo.run(feature, "st")
    jj_repo.write(jj_repo.root, "trunk.txt", "moved\n")
    jj_repo.commit(jj_repo.root, "move trunk")
    jj_repo.run(jj_repo.root, "rebase", "-r", "feature@", "-d", "default@-")
    jj_repo.write(feature, "right.txt", "right side\n")

    assert run_repair(feature) == 2
    error = capsys.readouterr().err
    assert "different nonempty work" in error
    assert "paused without running another jj command" in error
    assert Jj(feature).commits("divergent()")


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

    assert run_repair(root) == 2
    assert fake.calls == [("workspace", "update-stale")]
    error = capsys.readouterr().err
    assert "no subsequent jj command was run" in error
    assert "Pause" in error


def test_workspace_lock_times_out_while_held(tmp_path):
    root = tmp_path / "workspace"
    (root / ".jj").mkdir(parents=True)
    with WorkspaceLock(root, timeout=0.01):
        try:
            with WorkspaceLock(root, timeout=0.01):
                raise AssertionError("second lock unexpectedly succeeded")
        except LockTimeout:
            pass


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
