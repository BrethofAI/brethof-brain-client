#!/usr/bin/env python3
"""Wire Gemini CLI to brethof-brain.

Writes three hooks into Gemini CLI's user settings (~/.gemini/settings.json,
%USERPROFILE%\\.gemini\\settings.json on Windows) — user-level hooks run in
every folder, trusted or not — each calling gemini_hook.py:

    SessionStart  -> the session brief
    BeforeAgent   -> per-prompt recall
    AfterAgent    -> archive the turn

Timeouts are milliseconds (Gemini's unit). On Windows Gemini runs hook
commands in PowerShell, so the hook is called through the Python that ran
this setup.

Run from this directory:  python3 setup.py
Key:                      ~/.brethof-brain/config.json or BRETHOF_BRAIN_API_KEY
Stdlib only, Python 3.9+. Idempotent — safe to re-run after updates.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "gemini_hook.py"
HOME = Path(os.environ.get("GEMINI_CLI_HOME", Path.home())) / ".gemini"


def _cmd() -> str:
    if os.name == "nt":
        return f'& "{sys.executable}" "{HOOK}"'
    return f'python3 "{HOOK}"'


def _ours(entry: dict) -> bool:
    return any("gemini_hook.py" in str(h.get("command", "")) for h in entry.get("hooks", [])
               if isinstance(h, dict))


def main() -> int:
    if not os.environ.get("BRETHOF_BRAIN_API_KEY") and not (Path.home() / ".brethof-brain" / "config.json").exists():
        print("  ! no BRETHOF_BRAIN_API_KEY and no ~/.brethof-brain/config.json — "
              "installing anyway; the hooks stay silent until one exists.")
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
    for event, timeout in (("SessionStart", 15000), ("BeforeAgent", 15000), ("AfterAgent", 30000)):
        entry = {"hooks": [{"name": "brethof-brain", "type": "command",
                            "command": _cmd(), "timeout": timeout}]}
        hooks[event] = [e for e in hooks.get(event, []) if not _ours(e)] + [entry]
    # the 2026-08 adapter also archived at SessionEnd; AfterAgent covers it
    if "SessionEnd" in hooks:
        hooks["SessionEnd"] = [e for e in hooks["SessionEnd"] if not _ours(e)]
        if not hooks["SessionEnd"]:
            del hooks["SessionEnd"]
    path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"  hooks -> {path}")
    print("done — start a new gemini session to see the memory block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
