from jj_sensei.jj import Jj
from jj_sensei.repair import EXIT_HUMAN_REQUIRED
from jj_sensei.setup import run_setup, workspace_overlaps


def test_setup_alias_is_contextual_and_reports_nested_workspaces(jj_repo):
    assert run_setup(jj_repo.root) == 0

    feature_a = jj_repo.add_workspace("feature-a")
    feature_b = jj_repo.add_workspace("feature-b")

    template = 'change_id.short() ++ "\\n"'
    default_protected = jj_repo.run(
        jj_repo.root,
        "log",
        "--no-graph",
        "-r",
        "working_copies() & immutable_heads()",
        "-T",
        template,
    ).stdout.splitlines()
    feature_protected = jj_repo.run(
        feature_a,
        "log",
        "--no-graph",
        "-r",
        "working_copies() & immutable_heads()",
        "-T",
        template,
    ).stdout.splitlines()
    assert default_protected == []
    assert len(feature_protected) == 2
    assert workspace_overlaps(Jj(jj_repo.root)) == []

    jj_repo.run(feature_a, "new", "feature-b@", "-m", "nested feature-a")
    overlaps = workspace_overlaps(Jj(jj_repo.root))
    assert {(item.left.name, item.right.name) for item in overlaps} == {("feature-a", "feature-b")}

    blocked = jj_repo.run(
        feature_b,
        "describe",
        "-m",
        "must remain blocked",
        check=False,
    )
    assert blocked.returncode != 0
    assert "immutable" in blocked.stderr


def test_setup_refuses_non_default_workspace(jj_repo):
    feature = jj_repo.add_workspace("feature")
    assert run_setup(feature) == EXIT_HUMAN_REQUIRED


def test_overlap_audit_catches_shared_feature_only_ancestor(jj_repo):
    assert run_setup(jj_repo.root) == 0
    feature_a = jj_repo.add_workspace("feature-a")
    feature_b = jj_repo.add_workspace("feature-b")
    jj_repo.write(feature_b, "feature-b.txt", "shared feature ancestry\n")
    jj_repo.commit(feature_b, "feature-b work")

    jj_repo.run(feature_a, "new", "feature-b@-", "-m", "fork feature-a inside feature-b")
    overlaps = workspace_overlaps(Jj(jj_repo.root))
    assert {(item.left.name, item.right.name) for item in overlaps} == {("feature-a", "feature-b")}

    blocked = jj_repo.run(
        feature_b,
        "describe",
        "-r",
        "@-",
        "-m",
        "must remain blocked",
        check=False,
    )
    assert blocked.returncode != 0
    assert "immutable" in blocked.stderr


def test_setup_check_refuses_missing_aliases(jj_repo, capsys):
    assert run_setup(jj_repo.root, check_only=True) == EXIT_HUMAN_REQUIRED
    error = capsys.readouterr().err
    assert "human judgment required" in error
    assert "missing or differs" in error


def test_setup_accepts_a_workspace_parked_on_an_immutable_head(jj_repo):
    """Trunk can move onto a live workspace's `@`, making that working copy a
    built-in immutable head. Checking `immutable_heads()` wholesale reported
    that correct topology as a broken alias; only this setup's own term counts."""
    jj_repo.run(jj_repo.root, "bookmark", "create", "trunk", "-r", "@-")
    jj_repo.run(jj_repo.root, "config", "set", "--repo", "revset-aliases.'trunk()'", "trunk")
    assert run_setup(jj_repo.root) == 0

    parked = jj_repo.add_workspace("parked")
    jj_repo.run(jj_repo.root, "bookmark", "set", "trunk", "-r", "parked@")

    # The precondition the old check tripped over.
    assert Jj(jj_repo.root).commits("working_copies() & immutable_heads()")

    assert run_setup(jj_repo.root) == 0
    assert run_setup(jj_repo.root, check_only=True) == 0
    assert parked.exists()
