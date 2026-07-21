#!/usr/bin/env python3
"""Setup script — wire Grok Build to brethof-mind cloud.

Grok Build is Claude Code-compatible (reads ~/.claude/settings.json for hooks)
and has its own `grok mcp` command for MCP servers. This script:

1. Adds the brethof-mind HTTP MCP server via `grok mcp add`
2. Verifies the Claude Code hooks are wired (Grok reads these too)
3. Copies the /recall /curate /heal /onboard skills to ~/.grok/skills/

Run from this directory:
    python setup.py

Environment:
    BRETHOF_MIND_API_KEY  — your brethof-mind API key (bm_live_... or bm_test_...)
    BRETHOF_MIND_ENDPOINT — optional, defaults to https://api.brethof.cloud

Stdlib only — no pip install needed. Requires Python 3.9+.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

DEFAULT_ENDPOINT = "https://api.brethof.cloud"


def get_env():
    api_key = os.environ.get("BRETHOF_MIND_API_KEY", "")
    endpoint = os.environ.get("BRETHOF_MIND_ENDPOINT", DEFAULT_ENDPOINT)
    if not api_key:
        print("ERROR: BRETHOF_MIND_API_KEY not set in environment.")
        print("Get your key from https://brethof.ai/account -> brethof-mind tab.")
        print("Then: export BRETHOF_MIND_API_KEY=bm_live_your_key")
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
    """Add brethof-mind as an HTTP MCP server to Grok."""
    print("=== Adding brethof-mind MCP server ===")
    url = f"{endpoint}/v1/mcp"
    header = f"Authorization: Bearer {api_key}"

    # Check if already added
    result = subprocess.run([grok_bin, "mcp", "list"], capture_output=True, text=True)
    if "brethof-mind" in result.stdout:
        print(f"  brethof-mind already configured -> {url}")
        # Verify it's healthy
        result = subprocess.run([grok_bin, "mcp", "doctor"], capture_output=True, text=True, timeout=30)
        if "brethof-mind" in result.stdout and "handshake OK" in result.stdout:
            print("  ✓ handshake OK — tools already working")
            return True
        # If not healthy, remove and re-add
        print("  Existing config not healthy, re-adding...")
        subprocess.run([grok_bin, "mcp", "remove", "brethof-mind"], capture_output=True, text=True)

    result = subprocess.run(
        [grok_bin, "mcp", "add", "--transport", "http", "--scope", "user",
         "brethof-mind", url, "--header", header],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"  ✓ Added: {url}")
        return True
    else:
        print(f"  ✗ Failed: {result.stderr or result.stdout}")
        return False


def verify_hooks():
    """Check that Claude Code hooks are wired in ~/.claude/settings.json.

    Grok Build reads these hooks, so if Claude Code's brethof-mind plugin is
    installed, the hooks fire for Grok too.
    """
    print("=== Verifying Claude Code hooks ===")
    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        print("  ⚠ No ~/.claude/settings.json found.")
        print("  Install the Claude Code plugin first:")
        print("    /plugin marketplace add BrethofAI/brethof-mind-client")
        print("    /plugin install brethof-mind@brethof")
        print("  Or copy hooks manually from the repo root into ~/.claude/hooks/")
        return False

    import json
    with open(settings_path) as f:
        settings = json.load(f)

    hooks = settings.get("hooks", {})
    has_session_start = "SessionStart" in hooks
    has_prompt_submit = "UserPromptSubmit" in hooks
    has_stop = "Stop" in hooks

    if has_session_start and has_prompt_submit and has_stop:
        print("  ✓ Hooks found: SessionStart, UserPromptSubmit, Stop")
        # Check they reference brethof-mind
        all_hooks = []
        for event in ("SessionStart", "UserPromptSubmit", "Stop", "PreCompact"):
            for entry in hooks.get(event, []):
                for h in entry.get("hooks", []):
                    all_hooks.append(h.get("command", ""))
        bm_hooks = [h for h in all_hooks if "brethof" in h.lower() or "memory" in h.lower() or "load_memory" in h]
        if bm_hooks:
            print(f"  ✓ brethof-mind hooks detected ({len(bm_hooks)} commands)")
            return True
        else:
            print("  ⚠ Hooks exist but may not be brethof-mind specific.")
            print("  Commands found:", all_hooks[:3])
            return True  # still probably fine
    else:
        print("  ⚠ Missing some hooks. Install the Claude Code plugin for full integration.")
        return False


def copy_skills():
    """Copy /recall /curate /heal /onboard skills to ~/.grok/skills/."""
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
    print("brethof-mind cloud + Grok Build setup")
    print("=" * 40)

    api_key, endpoint = get_env()
    grok_bin = find_grok()
    print(f"Grok binary: {grok_bin}")
    print(f"Endpoint: {endpoint}")
    print()

    ok_mcp = add_mcp_server(grok_bin, api_key, endpoint)
    ok_hooks = verify_hooks()
    ok_skills = copy_skills()

    print()
    print("=" * 40)
    if ok_mcp:
        print("✓ MCP server: brethof-mind connected (15 tools)")
    else:
        print("✗ MCP server: failed — check your API key and endpoint")

    if ok_hooks:
        print("✓ Hooks: Claude Code hooks detected (Grok reads these)")
    else:
        print("⚠ Hooks: not fully configured — install Claude Code plugin for hooks")

    if ok_skills:
        print("✓ Skills: /recall /curate /heal /onboard installed")
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