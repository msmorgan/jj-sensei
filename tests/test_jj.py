from __future__ import annotations

from pathlib import Path

import pytest

from jj_sensei.jj import Jj, parse_workspace

_ORPHANED_ROW = (
    '{"name":"feature","commit_id":"df6399c85d036aaebd4671715d9b73e12038ded2",'
    '"root":<Error: Failed to resolve workspace root: feature: '
    "/repo/.jj/repo/../../../feature: No such file or directory (os error 2)>}"
)


def test_parse_workspace_reads_a_resolvable_row():
    workspace = parse_workspace('{"name":"default","commit_id":"abc","root":"/repo"}')

    assert workspace.name == "default"
    assert workspace.commit_id == "abc"
    assert workspace.root == Path("/repo")
    assert workspace.orphaned is False


def test_parse_workspace_salvages_a_row_whose_root_failed_to_resolve():
    workspace = parse_workspace(_ORPHANED_ROW)

    assert workspace.name == "feature"
    assert workspace.commit_id == "df6399c85d036aaebd4671715d9b73e12038ded2"
    assert workspace.root is None
    assert workspace.orphaned is True
    assert "No such file or directory" in workspace.root_error


def test_parse_workspace_still_refuses_a_row_it_cannot_read():
    with pytest.raises(RuntimeError):
        parse_workspace("not json at all")


def test_workspaces_survives_one_orphaned_registration(jj_repo):
    jj_repo.add_workspace("live")
    jj_repo.orphan_workspace("dead")

    workspaces = {workspace.name: workspace for workspace in Jj(jj_repo.root).workspaces()}

    assert set(workspaces) == {"default", "live", "dead"}
    assert workspaces["dead"].orphaned is True
    assert workspaces["live"].orphaned is False
    assert workspaces["default"].root == jj_repo.root


def test_current_workspace_ignores_an_orphaned_registration(jj_repo):
    jj_repo.orphan_workspace("dead")

    assert Jj(jj_repo.root).current_workspace().name == "default"
