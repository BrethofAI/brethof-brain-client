#!/usr/bin/env python3
"""Wire Devin CLI (Cognition; Windsurf's agent, Devin Local) to brethof-brain.

Devin reads Claude Code's hook format from its own user config
(~/.config/devin/config.json, %APPDATA%\\devin\\config.json on Windows,
under "hooks") and injects on SessionStart / UserPromptSubmit with
hookSpecificOutput.additionalContext — the plugin's own hook entry serves it:

    SessionStart       -> the session brief
    UserPromptSubmit   -> per-prompt recall (the prompt is kept for the archive)
    Stop               -> archive the turn

Devin passes no transcript_path: the Stop payload carries the reply as
last_assistant_message, and the hook archives the kept prompt with it.

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
if os.name == "nt":
    HOME = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "devin"
else:
    HOME = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "devin"


def _cmd(*args: str) -> str:
    # elsewhere the launcher finds a real Python
    return f'sh "{ROOT}/hooks/run_hook.sh" {" ".join(args)}'


def _hook(*args: str, timeout: int = 15) -> dict:
    h = {"type": "command", "command": _cmd(*args), "timeout": timeout}
    if os.name == "nt":
        # Windows: `command` runs through bash when Git Bash is there
        # (2026-10-03: a PowerShell-style command was a bash syntax error and
        # the failed prompt hook blocked the prompt) and `powershell` through
        # PowerShell — both call the Python that ran this setup directly
        py, entry = Path(sys.executable).as_posix(), (ROOT / "hook_entry.py").as_posix()
        h["command"] = f'"{py}" "{entry}" {" ".join(args)}'
        h["powershell"] = f'& "{sys.executable}" "{ROOT / "hook_entry.py"}" {" ".join(args)}'
    return {"matcher": "", "hooks": [h]}


def _ours(entry: dict) -> bool:
    return any("hook_entry.py" in h.get("command", "") or "run_hook.sh" in h.get("command", "")
               for h in entry.get("hooks", []) if isinstance(h, dict))


def main() -> int:
    if not os.environ.get("BRETHOF_BRAIN_API_KEY") and not (Path.home() / ".brethof-brain" / "config.json").exists():
        print("  ! no BRETHOF_BRAIN_API_KEY and no ~/.brethof-brain/config.json — "
              "installing anyway; the hooks stay silent until one exists.")
    HOME.mkdir(parents=True, exist_ok=True)
    path = HOME / "config.json"
    conf = {}
    if path.exists():
        try:
            conf = json.loads(path.read_text())
        except ValueError:
            print(f"  ! {path} is not valid JSON — leaving it untouched")
            return 1
    hooks = conf.setdefault("hooks", {})
    for event, entry in (("SessionStart", _hook("session-start")),
                         ("UserPromptSubmit", _hook("prompt-submit")),
                         ("Stop", _hook("stop", timeout=30))):
        hooks[event] = [e for e in hooks.get(event, []) if not _ours(e)] + [entry]
    path.write_text(json.dumps(conf, indent=2) + "\n")
    print(f"  hooks -> {path}")
    print("done — start a new devin session to see the memory block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
