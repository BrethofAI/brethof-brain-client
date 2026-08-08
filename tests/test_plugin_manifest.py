"""THE PLUGIN BUNDLE — the artifact `/plugin install brethof-mind@brethof`
actually installs.

Everything else in this repo tests the library. This tests the PACKAGE: the
manifests, the hook wiring and the MCP config that Claude Code reads. Nothing
imports these files, so nothing catches a typo in them — a wrong path or a
stale key means the plugin installs cleanly and then does nothing, which is the
worst possible failure for a memory product (the customer believes it is
remembering).

Two things this deliberately checks that look pedantic and are not:

  FORWARD SLASHES in hook commands. A backslash path in a hook is eaten by Git
  Bash, the hook exits 127, and the failure is visible ONLY in the transcript
  JSONL. That silently killed every mind hook for three days
  (global:bug_hooks_bash_backslash_2026_07_02).

  NO TOOL COUNT in customer-facing copy. The manifest advertised "15 memory
  tools" while the surface served 16 — a number in a description is a fact that
  rots, exactly like the "15 tools" assertion already removed from the
  container smoke test.

NOT COVERED, and it needs saying: running `/plugin marketplace add` for real
needs the repository to be PUBLIC, and the founder has not flipped it yet. The
end-to-end install from GitHub therefore cannot be exercised until then. This
proves the bundle is well-formed and self-consistent, not that GitHub serves it.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = REPO / ".claude-plugin" / "plugin.json"
MARKET = REPO / ".claude-plugin" / "marketplace.json"


def _json(p: pathlib.Path):
    assert p.is_file(), f"{p.name} is missing — the plugin cannot install"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        pytest.fail(f"{p.name} is not valid JSON: {e}")


def test_manifests_parse_and_agree_on_the_version():
    plug, market = _json(PLUGIN), _json(MARKET)
    listed = [p for p in market["plugins"] if p["name"] == plug["name"]]
    assert listed, (f"the marketplace does not list '{plug['name']}' — "
                    f"`/plugin install {plug['name']}@{market['name']}` "
                    f"cannot resolve")
    assert listed[0]["version"] == plug["version"], (
        f"version drift: marketplace says {listed[0]['version']}, the plugin "
        f"says {plug['version']} — installs pin the marketplace entry")


def test_every_path_the_manifest_names_exists():
    plug = _json(PLUGIN)
    for key in ("hooks", "mcpServers"):
        rel = plug.get(key)
        assert rel, f"plugin.json declares no {key}"
        # removeprefix, NOT lstrip: lstrip takes a CHARACTER SET, so
        # "./.mcp.json".lstrip("./") eats the dotfile's own dot and yields
        # "mcp.json" — a test that fails on a perfectly good bundle.
        target = (REPO / rel.removeprefix("./")).resolve()
        assert target.is_file(), (
            f"plugin.json -> {key} points at {rel}, which does not exist. The "
            f"plugin would install and do nothing.")


def test_hook_commands_point_at_real_files_and_use_forward_slashes():
    hooks = _json(REPO / "hooks" / "hooks.json")["hooks"]
    assert set(hooks) >= {"SessionStart", "UserPromptSubmit", "Stop"}, (
        f"a core hook is not wired: {sorted(hooks)} — without Stop nothing is "
        f"ever archived, and the customer's memory stays empty forever")
    seen = 0
    for event, entries in hooks.items():
        for entry in entries:
            for h in entry["hooks"]:
                cmd = h["command"]
                seen += 1
                assert "\\" not in cmd, (
                    f"{event} hook command contains a BACKSLASH: {cmd!r}. Git "
                    f"Bash eats it, the hook exits 127, and the only trace is "
                    f"the transcript JSONL — this killed every mind hook for "
                    f"three days on 2026-07-02.")
                assert "${CLAUDE_PLUGIN_ROOT}" in cmd, (
                    f"{event} hook does not use ${{CLAUDE_PLUGIN_ROOT}}: "
                    f"{cmd!r} — it would only work from one directory")
                m = re.search(r"\$\{CLAUDE_PLUGIN_ROOT\}/([^\"']+)", cmd)
                assert m, f"cannot read a script path out of {cmd!r}"
                assert (REPO / m.group(1)).is_file(), (
                    f"{event} hook runs {m.group(1)}, which is not in the "
                    f"bundle")
                assert int(h.get("timeout", 0)) > 0, (
                    f"{event} hook has no timeout — a hung memory call would "
                    f"block the customer's session")
    assert seen >= 4, f"only {seen} hook commands wired"


def test_the_mcp_server_is_wired_to_user_config_not_a_baked_in_key():
    mcp = _json(REPO / ".mcp.json")["mcpServers"]["brethof-mind"]
    assert "${user_config.api_key}" in json.dumps(mcp), (
        "the MCP server does not read the key from user config — a key baked "
        "into a published bundle would be OUR key, shipped to every customer")
    assert "bm_live_" not in json.dumps(mcp), "a real key is in the bundle"
    assert mcp["url"].endswith("/v1/mcp"), (
        f"the MCP url is {mcp['url']} — the customer surface is /v1/mcp")


def test_every_advertised_command_exists():
    for name in ("recall", "curate", "heal", "onboard"):
        assert (REPO / "commands" / f"{name}.md").is_file(), (
            f"/{name} is advertised in the README but commands/{name}.md is "
            f"not in the bundle")


def test_no_hardcoded_tool_COUNT_in_customer_facing_copy():
    """A number in a description is a fact that rots. The manifest claimed
    '15 memory tools' while the service served 16 — the same rot already
    removed from the container smoke test's assertions."""
    blob = " ".join(p.read_text(encoding="utf-8") for p in (PLUGIN, MARKET))
    stale = re.findall(r"\b\d+\s+(?:memory\s+)?tools\b", blob)
    assert not stale, (
        f"the plugin manifests advertise a tool COUNT ({stale}). It is already "
        f"wrong once and will be wrong again — describe the capability, not "
        f"the number.")
