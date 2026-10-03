#!/usr/bin/env python3
"""Wire Qoder CLI (Alibaba) to brethof-brain.

Qoder takes Claude Code's hook format from its user settings
(~/.qoder/settings.json; it does not read ~/.claude/settings.json) and
injects on SessionStart / UserPromptSubmit with hookSpecificOutput.
additionalContext — the plugin's own hook entry serves it:

    SessionStart       -> the session brief
    UserPromptSubmit   -> per-prompt recall (the prompt is kept for the archive)
    Stop               -> archive the turn from the hooks: the kept prompt and
                          last_assistant_message (BRETHOF_BRAIN_ARCHIVE=hooks)

Timeouts are seconds (Qoder's unit). On Windows the hook runs under
PowerShell ("shell": "powershell"), through the Python that ran this setup.

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
HOME = Path(os.environ.get("QODER_CONFIG_DIR", Path.home() / ".qoder"))


def _hook(*args: str, timeout: int = 15) -> dict:
    if os.name == "nt":
        cmd = (f'$env:BRETHOF_BRAIN_ARCHIVE="hooks"; & "{sys.executable}" '
               f'"{ROOT / "hook_entry.py"}" {" ".join(args)}')
        return {"hooks": [{"type": "command", "command": cmd, "timeout": timeout, "shell": "powershell"}]}
    cmd = f'BRETHOF_BRAIN_ARCHIVE=hooks sh "{ROOT}/hooks/run_hook.sh" {" ".join(args)}'
    return {"hooks": [{"type": "command", "command": cmd, "timeout": timeout}]}


def _ours(entry: dict) -> bool:
    return any("hook_entry.py" in h.get("command", "") or "run_hook.sh" in h.get("command", "")
               for h in entry.get("hooks", []) if isinstance(h, dict))


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
    for event, entry in (("SessionStart", _hook("session-start")),
                         ("UserPromptSubmit", _hook("prompt-submit")),
                         ("Stop", _hook("stop", timeout=30))):
        hooks[event] = [e for e in hooks.get(event, []) if not _ours(e)] + [entry]
    path.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"  hooks -> {path}")
    print("done — start a new qodercli session to see the memory block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
