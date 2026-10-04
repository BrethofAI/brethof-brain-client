"""THE PLUGIN BUNDLE — the artifact `/plugin install brethof-brain@brethof`
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
# The plugin is its own folder since 2026-10-04 (scripts/sync_plugin.py says
# why); the marketplace stays at the repo root and points at it.
BUNDLE = REPO / "plugin"
PLUGIN = BUNDLE / ".claude-plugin" / "plugin.json"
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
    assert listed[0]["source"] == "./plugin", (
        f"the marketplace installs {listed[0]['source']!r} — the plugin is ./plugin")
    assert listed[0]["version"] == plug["version"], (
        f"version drift: marketplace says {listed[0]['version']}, the plugin "
        f"says {plug['version']} — installs pin the marketplace entry")


def test_hooks_load_from_the_standard_file_only():
    # Claude Code always loads hooks/hooks.json; naming it again in the
    # manifest makes the loader report a duplicate hooks file (Anthropic's
    # directory validator, HOOKS_STANDARD_FILE_DUPLICATED, 2026-10-04).
    assert "hooks" not in _json(PLUGIN), "plugin.json must not re-list hooks/hooks.json"
    assert (BUNDLE / "hooks" / "hooks.json").is_file()


def test_every_path_the_manifest_names_exists():
    plug = _json(PLUGIN)
    for key in ("mcpServers",):
        rel = plug.get(key)
        assert rel, f"plugin.json declares no {key}"
        # removeprefix, NOT lstrip: lstrip takes a CHARACTER SET, so
        # "./.mcp.json".lstrip("./") eats the dotfile's own dot and yields
        # "mcp.json" — a test that fails on a perfectly good bundle.
        target = (BUNDLE / rel.removeprefix("./")).resolve()
        assert target.is_file(), (
            f"plugin.json -> {key} points at {rel}, which does not exist. The "
            f"plugin would install and do nothing.")


def test_hook_commands_point_at_real_files_and_use_forward_slashes():
    hooks = _json(BUNDLE / "hooks" / "hooks.json")["hooks"]
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
                assert (BUNDLE / m.group(1)).is_file(), (
                    f"{event} hook runs {m.group(1)}, which is not in the "
                    f"bundle")
                assert int(h.get("timeout", 0)) > 0, (
                    f"{event} hook has no timeout — a hung memory call would "
                    f"block the customer's session")
    assert seen >= 4, f"only {seen} hook commands wired"


def test_the_mcp_server_carries_no_key_and_reads_the_customers_config():
    # "brain" since 2026-08-10 — the server name stamps the tool ids the
    # agent sees (mcp__brain__*), which is itself a product feature. Since
    # 2026-10-04 it is the local stdio bridge, which reads the key and address
    # from ~/.brethof-brain/config.json (what `connect` saves) — so nothing in
    # the bundle names a key, ours or anyone's.
    mcp = _json(BUNDLE / ".mcp.json")["mcpServers"]["brain"]
    assert "bmv2_" not in json.dumps(mcp), "a real key is in the bundle"
    assert mcp["type"] == "stdio" and mcp["args"][0].endswith("hooks/run_bridge.sh")
    assert (BUNDLE / "mcp_bridge.py").is_file() and (BUNDLE / "hooks" / "run_bridge.sh").is_file()


def test_every_advertised_command_exists():
    # /heal left the bundle 2026-09-04: curation, consolidation and heal are
    # the service's; the plugin ships the three commands the README names.
    for name in ("recall", "curate", "onboard"):
        assert (BUNDLE / "commands" / f"{name}.md").is_file(), (
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


def test_the_bundle_carries_the_shared_code_unchanged():
    # plugin/ ships COPIES of the client package, hook_entry.py, connect.py,
    # run_hook.sh and LICENSE; a release that forgets scripts/sync_plugin.py
    # would ship an older client inside the plugin than everywhere else.
    import subprocess, sys
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "sync_plugin.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, f"plugin/ is out of sync — run scripts/sync_plugin.py:\n{r.stdout}"


def test_the_bundle_ships_nothing_but_the_plugin():
    # What Anthropic's directory scans is exactly this folder; the local
    # edition's installer, the CI file and the other adapters stay out.
    for name in ("adapters", "local", ".github", "tests", "test-container", "pyproject.toml"):
        assert not (BUNDLE / name).exists(), f"plugin/{name} would ship with the plugin"
