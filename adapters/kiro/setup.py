#!/usr/bin/env python3
"""Wire Kiro CLI (AWS) to brethof-brain.

Kiro CLI's hooks live in an AGENT file (~/.kiro/agents/<name>.json) and its
built-in agent, kiro_default, has none — so this writes a `brethof-brain`
agent (every tool, as the default agent has) carrying our hooks, and makes
it the default (`kiro-cli agent set-default`). A hook's plain STDOUT is
added to the context, so the plugin's own hook entry runs in plain mode:

    agentSpawn         -> the session brief
    userPromptSubmit   -> per-prompt recall (the prompt is kept for the archive)
    stop               -> archive the turn (the reply is assistant_response)

Kiro passes no transcript; the turn is built from the hooks.

Run from this directory:  python3 setup.py
Key:                      ~/.brethof-brain/config.json or BRETHOF_BRAIN_API_KEY
Stdlib only, Python 3.9+. Idempotent — safe to re-run after updates.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # plugin repo root
AGENTS = Path.home() / ".kiro" / "agents"
NAME = "brethof-brain"


def _cmd(*args: str) -> str:
    if os.name == "nt":
        return (f'$env:BRETHOF_BRAIN_HOOK_PLAIN="1"; & "{sys.executable}" '
                f'"{ROOT / "hook_entry.py"}" {" ".join(args)}')
    return f'BRETHOF_BRAIN_HOOK_PLAIN=1 sh "{ROOT}/hooks/run_hook.sh" {" ".join(args)}'


def main() -> int:
    if not os.environ.get("BRETHOF_BRAIN_API_KEY") and not (Path.home() / ".brethof-brain" / "config.json").exists():
        print("  ! no BRETHOF_BRAIN_API_KEY and no ~/.brethof-brain/config.json — "
              "installing anyway; the hooks stay silent until one exists.")
    AGENTS.mkdir(parents=True, exist_ok=True)
    path = AGENTS / f"{NAME}.json"
    agent = {}
    if path.exists():
        try:
            agent = json.loads(path.read_text())
        except ValueError:
            print(f"  ! {path} is not valid JSON — leaving it untouched")
            return 1
    agent.setdefault("name", NAME)
    agent.setdefault("description", "Kiro's default agent with brethof-brain memory")
    agent.setdefault("tools", ["*"])
    agent["hooks"] = {**agent.get("hooks", {}),
                      "agentSpawn": [{"command": _cmd("session-start"), "timeout_ms": 15000}],
                      "userPromptSubmit": [{"command": _cmd("prompt-submit"), "timeout_ms": 15000}],
                      "stop": [{"command": _cmd("stop"), "timeout_ms": 30000}]}
    path.write_text(json.dumps(agent, indent=2) + "\n")
    print(f"  agent -> {path}")
    kiro = shutil.which("kiro-cli")
    if kiro:
        r = subprocess.run([kiro, "agent", "set-default", NAME], capture_output=True, text=True)
        print("  default agent -> " + (NAME if r.returncode == 0 else
              f"NOT SET ({(r.stderr or r.stdout).strip()[:200]}) — run: kiro-cli agent set-default {NAME}"))
    else:
        print(f"  kiro-cli not on PATH — make it the default yourself: kiro-cli agent set-default {NAME}")
    print("done — start a new kiro-cli chat to see the memory block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
