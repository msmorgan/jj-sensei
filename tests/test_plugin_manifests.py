"""Pin the plugin manifests, which nothing else in the repository reads.

Each host discovers jj-sensei through its own `plugin.json`. No module, script,
or other test loads any of them, so without this file a manifest can be deleted
or renamed and every remaining test still passes.
"""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PLUGIN_MANIFESTS = {
    "Antigravity": "plugin.json",
    "Claude Code": ".claude-plugin/plugin.json",
    "Codex": ".codex-plugin/plugin.json",
}


@pytest.mark.parametrize("relative", PLUGIN_MANIFESTS.values(), ids=PLUGIN_MANIFESTS.keys())
def test_every_host_has_a_manifest_naming_the_plugin(relative):
    path = ROOT / relative

    assert path.is_file(), (
        f"{relative} is the manifest a host installs jj-sensei from. Nothing in "
        "this repository imports it, so it looks unused; it is not."
    )

    manifest = json.loads(path.read_text())
    assert manifest["name"] == "jj-sensei"
    assert manifest["description"]
    assert manifest["version"]
