# Steer stale workspaces to `repair`, not manual `update-stale`

ep032: a manual `jj workspace update-stale` produced a divergent change.
Make references/stale.md (and SKILL.md's route) explicit that `repair` is the
path and a bare `update-stale` is not. Check ep007 (agent's own squash) for
any related rule before writing one.
