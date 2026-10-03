#!/usr/bin/env python3
"""Wire GitHub Copilot CLI to brethof-brain.

Copilot CLI reads user hooks from ~/.copilot/hooks/*.json (no folder-trust
gate for user-level files) and accepts Claude Code's PascalCase event names,
which also give Claude Code's snake_case stdin fields (session_id, prompt,
transcript_path) — so the plugin's own hook entry serves it:

    SessionStart       -> the session brief   (Copilot reads a top-level
    UserPromptSubmit   -> per-prompt recall    additionalContext: the hook's
    Stop               -> archive the turn     env sets BRETHOF_BRAIN_HOOK_FLAT)

Run from this directory:  python3 setup.py
Environment:              BRETHOF_BRAIN_API_KEY (or ~/.brethof-brain/config.json)
Stdlib only, Python 3.9+. Idempotent — safe to re-run after updates.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # plugin repo root
HOME = Path(os.environ.get("COPILOT_HOME", Path.home() / ".copilot"))


def _cmd(*args: str) -> str:
    # Windows has no sh: call the Python that ran this setup on hook_entry.py
    if os.name == "nt":
        return f'& "{sys.executable}" "{ROOT / "hook_entry.py"}" {" ".join(args)}'
    return f'sh "{ROOT}/hooks/run_hook.sh" {" ".join(args)}'


def _hook(*args: str, timeout: int = 15) -> dict:
    return {"type": "command", "command": _cmd(*args), "timeoutSec": timeout,
            "env": {"BRETHOF_BRAIN_HOOK_FLAT": "1"}}


def main() -> int:
    if not os.environ.get("BRETHOF_BRAIN_API_KEY") and not (Path.home() / ".brethof-brain" / "config.json").exists():
        print("  ! no BRETHOF_BRAIN_API_KEY and no ~/.brethof-brain/config.json — "
              "installing anyway; the hooks stay silent until one exists.")
    (HOME / "hooks").mkdir(parents=True, exist_ok=True)
    path = HOME / "hooks" / "brethof-brain.json"
    path.write_text(json.dumps({"version": 1, "hooks": {
        "SessionStart": [_hook("session-start")],
        "UserPromptSubmit": [_hook("prompt-submit")],
        "Stop": [_hook("stop", timeout=30)],
    }}, indent=2) + "\n")
    print(f"  hooks -> {path}")
    print("done — start a new copilot session to see the memory block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
