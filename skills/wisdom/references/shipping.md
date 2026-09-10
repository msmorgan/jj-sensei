# Publish and land work

Load only the branch that owns the requested operation:

| Request or output | Reference |
|---|---|
| Push or publish described work | [Push work](shipping/push.md) |
| Fetch, tracking, upstream rebasing, or choosing among remotes | [Fetch and track upstream](shipping/sync.md) |
| Create, advance, rename, forget, or delete a bookmark | [Manage bookmarks](shipping/bookmarks.md) |
| `??` or `(conflicted)` on a bookmark | [Reconcile a conflicted bookmark](shipping/bookmark-conflicts.md) |
| Create, move, track, publish, or delete a tag | [Manage tags](shipping/tags.md) |

Routing is complete when every requested remote effect and every relevant jj
output token has an owner. A workflow may require more than one branch—for
example, advancing a bookmark and then pushing it—but unrelated branches stay
unloaded.
