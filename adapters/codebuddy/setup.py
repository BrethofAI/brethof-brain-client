#!/usr/bin/env python3
"""Wire Tencent CodeBuddy Code to brethof-brain.

CodeBuddy's hooks are Claude Code's format, read from the user settings file
~/.codebuddy/settings.json (it does not read ~/.claude/settings.json), and
inject on SessionStart / UserPromptSubmit with hookSpecificOutput.
additionalContext; every event carries transcript_path (OpenAI Agents SDK
items, which the plugin's transcript reader understands). Hook commands run
under sh on Linux and macOS and under Git Bash on Windows (CodeBuddy requires
it there), so one command serves both.

Run from this directory:  python3 setup.py
Key:                      ~/.brethof-brain/config.json or BRETHOF_BRAIN_API_KEY
Stdlib only, Python 3.9+. Idempotent — safe to re-run after updates.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # plugin repo root
HOME = Path(os.environ.get("CODEBUDDY_CONFIG_DIR", Path.home() / ".codebuddy"))


def _hook(*args: str, timeout: int = 12) -> dict:
    cmd = f'sh "{ROOT.as_posix()}/hooks/run_hook.sh" {" ".join(args)}'
    return {"hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}


def main() -> int:
    HOME.mkdir(parents=True, exist_ok=True)
    path = HOME / "settings.json"
    settings = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text())
        except ValueError:
            print(f"  ! {path} is not valid JSON — leaving it untouched")
            return 1
    hooks = settings.setdefault("hooks", {})
    ours = {"SessionStart": _hook("session-start"),
            "UserPromptSubmit": _hook("prompt-submit"),
            "Stop": _hook("stop", timeout=30)}
    for event, entry in ours.items():
        existing = hooks.setdefault(event, [])
        if not any("run_hook.sh" in h.get("command", "") for e in existing for h in e.get("hooks", [])):
            existing.append(entry)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"  hooks -> {path}")
    print("done — start a new codebuddy session to see the memory block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
