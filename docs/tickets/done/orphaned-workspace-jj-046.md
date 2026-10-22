# Orphaned-workspace detection fails under jj 0.46.0

Three tests fail on the default line with jj 0.46.0 (found 2026-10-22 while
integrating `inline-conflict-procedure`; they fail without that change):

- `tests/test_jj.py::test_workspaces_survives_one_orphaned_registration`
- `tests/test_setup.py::test_setup_check_diagnoses_an_orphaned_workspace_without_forgetting_it`
- `tests/test_status.py::test_status_survives_and_flags_an_orphaned_workspace`

In each, the orphaned registration is not flagged (e.g. the status line lacks
`⚠ orphaned workspace 'dead'`). Likely jj 0.46 changed how `workspace list`
or `workspace root` reports a workspace whose directory is gone.

Done when detection works on jj 0.46.0 without breaking the minimum supported
version, and all three tests pass.
