from jj_sensei.jj import Jj
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
    assert run_setup(feature) == 2


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
    assert run_setup(jj_repo.root, check_only=True) == 2
    assert "missing or differs" in capsys.readouterr().err
