#!/usr/bin/env python3
"""Setup script — wire Grok Build to brethof-brain cloud.

Grok Build has its own `grok mcp` command for MCP servers and a native hook
system under ~/.grok/hooks/ (Claude-style ~/.claude/settings.json hooks
verifiably CANNOT fire in grok — see install_hooks below). This script:

1. Adds the brethof-brain HTTP MCP server via `grok mcp add`
2. Installs the native Stop-hook archiver + pull-model memory rule
3. Copies the /recall /curate /onboard skills to ~/.grok/skills/

Run from this directory:
    python setup.py

Environment:
    BRETHOF_BRAIN_API_KEY  — your brethof-brain API key (bm_live_... or bm_test_...)
    BRETHOF_BRAIN_ENDPOINT — optional, defaults to https://api.brethof.cloud

Stdlib only — no pip install needed. Requires Python 3.9+.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# Windows consoles default to cp1252 — the ✓/✗ glyphs below would crash the
# script mid-setup. Force UTF-8 on the script's own streams, always.
for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

DEFAULT_ENDPOINT = "https://api.brethof.cloud"


def get_env():
    api_key = os.environ.get("BRETHOF_BRAIN_API_KEY", "")
    endpoint = os.environ.get("BRETHOF_BRAIN_ENDPOINT", DEFAULT_ENDPOINT)
    if not api_key:
        print("ERROR: BRETHOF_BRAIN_API_KEY not set in environment.")
        print("Get your key from https://brethof.ai/account -> brethof-brain tab.")
        print("Then: export BRETHOF_BRAIN_API_KEY=bm_live_your_key")
        sys.exit(1)
    return api_key, endpoint


def find_grok():
    """Find the grok binary."""
    # Check ~/.grok/bin/grok first (standard install location)
    home_grok = Path.home() / ".grok" / "bin" / "grok"
    if home_grok.exists():
        return str(home_grok)
    # Check PATH
    which = shutil.which("grok")
    if which:
        return which
    print("ERROR: grok not found. Install Grok Build first:")
    print("  curl -fsSL https://xai.org/grok | sh")
    sys.exit(1)


def add_mcp_server(grok_bin: str, api_key: str, endpoint: str):
    """Add brethof-brain as an HTTP MCP server to Grok."""
    print("=== Adding brethof-brain MCP server ===")
    url = f"{endpoint}/v1/mcp"
    header = f"Authorization: Bearer {api_key}"

    # Check if already added
    result = subprocess.run([grok_bin, "mcp", "list"], capture_output=True, text=True)
    if "brethof-brain" in result.stdout:
        print(f"  brethof-brain already configured -> {url}")
        # Verify it's healthy
        result = subprocess.run([grok_bin, "mcp", "doctor"], capture_output=True, text=True, timeout=30)
        if "brethof-brain" in result.stdout and "handshake OK" in result.stdout:
            print("  ✓ handshake OK — tools already working")
            return True
        # If not healthy, remove and re-add
        print("  Existing config not healthy, re-adding...")
        subprocess.run([grok_bin, "mcp", "remove", "brethof-brain"], capture_output=True, text=True)

    result = subprocess.run(
        [grok_bin, "mcp", "add", "--transport", "http", "--scope", "user",
         "brethof-brain", url, "--header", header],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  ✓ Added: {url}")
        return True
    else:
        print(f"  ✗ Failed: {result.stderr or result.stdout}")
        return False


def persist_key(api_key: str, endpoint: str):
    """Make sure the Stop-hook archiver can find the key AFTER this shell dies.

    The hook resolves its key via brethof_brain_client.Config: env var first,
    then ~/.brethof-brain/config.json. grok spawns hooks WITHOUT this shell's
    environment, so an env-only key means the archiver runs keyless and
    fail-open — silently archiving nothing. Persist the key to config.json
    unless one is already configured there (never overwrite an existing key:
    on a machine that also runs the Claude Code plugin, config.json may hold
    a different key on purpose)."""
    print("=== Persisting key for the Stop-hook archiver ===")
    import json as _json
    cfg_dir = Path(os.path.expanduser(os.environ.get("BRETHOF_BRAIN_HOME",
                                                     "~/.brethof-brain")))
    cfg_path = cfg_dir / "config.json"
    existing = {}
    if cfg_path.exists():
        try:
            existing = _json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            existing = {}
    if existing.get("api_key"):
        print(f"  {cfg_path} already has a key — leaving it untouched")
        return True
    existing["api_key"] = api_key
    if endpoint != DEFAULT_ENDPOINT:
        existing["endpoint"] = endpoint
    cfg_dir.mkdir(parents=True, exist_ok=True)
    tmp = cfg_path.with_suffix(".json.tmp")
    tmp.write_text(_json.dumps(existing, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, cfg_path)
    try:
        os.chmod(cfg_path, 0o600)
    except OSError:
        pass
    print(f"  ✓ key persisted to {cfg_path}")
    return True


def install_hooks():
    """Install the NATIVE grok Stop-hook archiver (~/.grok/hooks/).

    Grok Build does scan ~/.claude/settings.json for hooks, but the Claude hook
    entry CANNOT work there (verified empirically on grok 0.2.106, 2026-07-24):
    payloads are camelCase, passive-hook stdout (additionalContext) is ignored,
    and on Windows grok's spawner mangles the quoted `"exe" "script"` command
    form. So we wire grok_hook.py natively: a Stop hook that archives grok's
    own updates.jsonl transcript to the cloud. Memory INJECTION is replaced by
    the PULL model — a global rule tells Grok to call the MCP recall tools.
    """
    print("=== Installing native grok hooks ===")
    import json as _json
    adapter = Path(__file__).parent / "grok_hook.py"
    hooks_dir = Path.home() / ".grok" / "hooks"
    bin_dir = hooks_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    if sys.platform == "win32":
        # .cmd wrapper REQUIRED: grok's Windows spawner breaks on quoted
        # `"python" "script" arg` inline commands (exit 1 before Python runs).
        wrapper = bin_dir / "bm-grok-stop.cmd"
        wrapper.write_text(
            "@echo off\r\n"
            f'"{sys.executable}" "{adapter}" stop\r\n'
            "exit /b 0\r\n", encoding="utf-8")
        command = "bin/bm-grok-stop.cmd"
    else:
        wrapper = bin_dir / "bm-grok-stop.sh"
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{adapter}" stop\n',
                           encoding="utf-8")
        wrapper.chmod(0o755)
        command = "bin/bm-grok-stop.sh"

    hook_json = hooks_dir / "brethof-brain.json"
    hook_json.write_text(_json.dumps({"hooks": {"Stop": [
        {"hooks": [{"type": "command", "command": command, "timeout": 25}]}
    ]}}, indent=2) + "\n", encoding="utf-8")
    print(f"  ✓ Stop-hook archiver: {hook_json} -> {wrapper.name}")

    # PULL-model memory rule (grok has no hook context-injection channel).
    rules_dir = Path.home() / ".grok" / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    rule = rules_dir / "brethof-brain-memory.md"
    rule.write_text(
        "# brethof-brain memory (PULL model — you must call the tools)\n\n"
        "You have persistent cross-session memory: the **brethof-brain** MCP "
        "server. Use the tools it lists — `search_brain` (saved memory, "
        "the current truth) and `search_history` (full conversation "
        "history, raw) are the core pair.\n\n"
        "Grok cannot inject memory automatically, so YOU pull it:\n"
        "1. Before the first substantive answer on a known project, "
        "`search_brain` the topic.\n"
        "2. When a question touches past decisions/infra/runbooks — search "
        "first, never guess. Exact strings (paths, errors) → "
        "`search_history`.\n"
        "3. Memory LEARNS AUTOMATICALLY from every archived exchange — the "
        "service curates as you work. Save explicitly only what the user "
        "asks to remember or what must be recorded exactly: facts with "
        "`save_project`/`save_general`, standing RULES (conventions that "
        "bind every session) with `save_rule` — it asks one question back; answer it and the answer files it.\n"
        "4. Turns are archived automatically by the Stop hook — do not save "
        "chat history manually.\n\n"
        "Do NOT use Grok's built-in markdown memory — brethof-brain is the "
        "single memory system.\n", encoding="utf-8")
    print(f"  ✓ Pull-model rule: {rule}")
    print("  NOTE: consider `[compat.claude] hooks = false` in ~/.grok/config.toml"
          " — the Claude-sourced hooks fail in grok and only add log noise.")
    return True


def copy_skills():
    """Copy /recall /curate /onboard skills to ~/.grok/skills/."""
    print("=== Copying skills ===")
    skills_dir = Path(__file__).parent / "skills"
    if not skills_dir.exists():
        print("  ⚠ No skills/ directory found in adapter")
        return False

    target_dir = Path.home() / ".grok" / "skills"
    target_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for skill_dir in skills_dir.iterdir():
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            dest = target_dir / skill_dir.name
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(skill_dir, dest)
            print(f"  ✓ {skill_dir.name}")
            copied += 1

    print(f"  Copied {copied} skills to {target_dir}")
    return copied > 0


def main():
    print("brethof-brain cloud + Grok Build setup")
    print("=" * 40)

    api_key, endpoint = get_env()
    grok_bin = find_grok()
    print(f"Grok binary: {grok_bin}")
    print(f"Endpoint: {endpoint}")
    print()

    ok_mcp = add_mcp_server(grok_bin, api_key, endpoint)
    ok_key = persist_key(api_key, endpoint)
    ok_hooks = install_hooks() and ok_key
    ok_skills = copy_skills()

    print()
    print("=" * 40)
    if ok_mcp:
        print("✓ MCP server: brethof-brain connected")
    else:
        print("✗ MCP server: failed — check your API key and endpoint")

    if ok_hooks:
        print("✓ Hooks: native Stop-hook archiver + pull-model memory rule installed")
    else:
        print("⚠ Hooks: not configured — re-run or wire ~/.grok/hooks manually")

    if ok_skills:
        print("✓ Skills: /recall /curate /onboard installed")
    else:
        print("⚠ Skills: not copied")

    print()
    if ok_mcp:
        print("Memory is live! Run `grok mcp doctor` to verify, then start a session.")
    else:
        print("Setup incomplete. Fix the errors above and re-run.")
        sys.exit(1)


if __name__ == "__main__":
    main()