# Guardrail: only the owning workspace repairs its own problem

Source: October 2026 study of 48 jj problem occasions across 30 agent sessions, mostly in deckmaste.rs (a Rust/Lean repo using jj-kata). Episode IDs (epNNN) refer to that study.

Orchestrators repaired workspaces they did not own three times:

- ep001: abandoned a divergent half in another thread's workspace, although
  the relayed kata output said its owner must repair it with harmony.
- ep002: ran `jj edit` and `jj abandon` in a workspace whose thread was still
  writing to it; racing snapshots were visible during the refresh.
- ep003: squashed the divergent half in another thread's workspace.

In each case a `kata refresh` or claim elsewhere was blocked (exit 69) by the
foreign divergence, which is what pushed the orchestrator to intervene.
`repair`'s lock only serialises repairs, so it doesn't prevent this.

Done when wisdom or boundaries, and harmony's repair step, say: repair only
from the workspace that owns the change; when blocked by another workspace's
problem, report to its owner and wait.
