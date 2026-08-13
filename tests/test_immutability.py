from __future__ import annotations

from jj_sensei.immutability import (
    active_definition,
    clauses,
    explain,
    render,
    split_union,
    unwrap,
)
from jj_sensei.jj import Jj


def test_split_union_keeps_nested_unions_inside_their_call():
    assert split_union("trunk() | tags()") == ["trunk()", "tags()"]
    assert split_union("only_if(a() | b(), c()) | d()") == ["only_if(a() | b(), c())", "d()"]
    assert split_union("description('a | b')") == ["description('a | b')"]


def test_unwrap_only_drops_parentheses_that_wrap_the_whole_expression():
    assert unwrap("(trunk())") == "trunk()"
    assert unwrap("((trunk()))") == "trunk()"
    assert unwrap("(a()) & (b())") == "(a()) & (b())"


def test_clauses_expand_the_builtin_umbrella_alias():
    expanded = clauses("builtin_immutable_heads() | other_workspaces()")

    assert [clause.text for clause in expanded] == [
        "trunk()",
        "tags()",
        "untracked_remote_bookmarks()",
        "other_workspaces()",
    ]
    assert expanded[0].origin == "builtin_immutable_heads()"
    assert expanded[3].origin is None


def test_active_definition_falls_back_to_the_builtin_alias(jj_repo):
    assert active_definition(Jj(jj_repo.root)) == "builtin_immutable_heads()"


def test_explain_reports_a_mutable_revision_plainly(jj_repo):
    verdicts = explain(Jj(jj_repo.root), "@")

    assert len(verdicts) == 1
    assert verdicts[0].immutable is False
    assert verdicts[0].captures == ()
    assert "mutable" in render("builtin_immutable_heads()", verdicts)


def test_explain_names_the_clause_and_anchor_of_an_immutable_revision(jj_repo):
    jj_repo.run(jj_repo.root, "tag", "set", "v1.0.0", "-r", "@-")

    verdicts = explain(Jj(jj_repo.root), "@-")

    assert len(verdicts) == 1
    assert verdicts[0].immutable is True
    assert [capture.clause.text for capture in verdicts[0].captures] == ["tags()"]
    anchors = verdicts[0].captures[0].anchors
    assert [anchor.tags for anchor in anchors] == ["v1.0.0"]

    report = render("builtin_immutable_heads()", verdicts)
    assert "captured by tags() (via builtin_immutable_heads())" in report
    assert "v1.0.0" in report


def test_explain_attributes_a_custom_clause_separately(jj_repo):
    jj_repo.run(jj_repo.root, "bookmark", "create", "pinned", "-r", "@-")
    jj_repo.run(
        jj_repo.root,
        "config",
        "set",
        "--repo",
        "revset-aliases.'immutable_heads()'",
        "builtin_immutable_heads() | bookmarks(exact:'pinned')",
    )

    jj = Jj(jj_repo.root)
    definition = active_definition(jj)
    verdicts = explain(jj, "@-", definition)

    assert [capture.clause.text for capture in verdicts[0].captures] == [
        "bookmarks(exact:'pinned')"
    ]
    assert verdicts[0].captures[0].clause.origin is None
    assert verdicts[0].unevaluated == ()


def test_explain_reports_a_clause_it_cannot_evaluate_without_failing(jj_repo):
    # jj rejects an unparseable alias outright, so a clause can only fail on
    # its own — which is what the report has to survive rather than crash on.
    verdicts = explain(Jj(jj_repo.root), "@", "trunk() | no_such_function()")

    assert verdicts[0].immutable is False
    assert verdicts[0].unevaluated == ("no_such_function()",)
