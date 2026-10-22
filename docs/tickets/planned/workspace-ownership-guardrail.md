# Guardrail: only the owning workspace repairs its conflicts

Orchestrators repaired workspaces they don't own 3 times (ep001–ep003); in
ep002 the owning thread was still writing to it. The `repair` lock only
serialises repairs, so it doesn't prevent this.

Add guidance to wisdom or boundaries (and harmony's §3): repair only from the
workspace that owns the change; otherwise report to the owner.
