#!/usr/bin/env python3
"""Wire ZCode (Z.ai / Zhipu, the `zcode` agent inside the ZCode app) to
brethof-brain.

ZCode reads hooks from ~/.zcode/cli/config.json ({"hooks": {"enabled": true,
"events": {<Event>: [{"matcher", "hooks": [handler]}]}}}, timeouts in
seconds) and injects on SessionStart / UserPromptSubmit with
hookSpecificOutput.additionalContext. Its transcript_path is a one-line temp
file per hook call, so the turn is archived from the hooks: the prompt kept
at prompt-submit and Stop's last_assistant_message.

ZCode knows seven events only; a config naming any other (SessionEnd,
PreCompact) is dropped whole, with a line in its own log — so this writes
exactly SessionStart, UserPromptSubmit and Stop. Project-level hooks are
ignored by ZCode; this is the user-level file.

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
PATH = Path.home() / ".zcode" / "cli" / "config.json"


def _handler(event: str, timeout: int) -> dict:
    # "process" starts the program directly — no shell to differ per platform
    return {"type": "process", "command": sys.executable,
            "args": [str(ROOT / "hook_entry.py"), event, "--archive=hooks"], "timeout": timeout}


def _ours(entry: dict) -> bool:
    return any("hook_entry.py" in " ".join(map(str, h.get("args", []))) for h in entry.get("hooks", [])
               if isinstance(h, dict))


def main() -> int:
    if not os.environ.get("BRETHOF_BRAIN_API_KEY") and not (Path.home() / ".brethof-brain" / "config.json").exists():
        print("  ! no BRETHOF_BRAIN_API_KEY and no ~/.brethof-brain/config.json — "
              "installing anyway; the hooks stay silent until one exists.")
    PATH.parent.mkdir(parents=True, exist_ok=True)
    conf = {}
    if PATH.exists():
        try:
            conf = json.loads(PATH.read_text())
        except ValueError:
            print(f"  ! {PATH} is not valid JSON — leaving it untouched")
            return 1
    hooks = conf.setdefault("hooks", {})
    hooks["enabled"] = True
    events = hooks.setdefault("events", {})
    for event, arg, timeout in (("SessionStart", "session-start", 15),
                                ("UserPromptSubmit", "prompt-submit", 15),
                                ("Stop", "stop", 30)):
        events[event] = [e for e in events.get(event, []) if not _ours(e)] + \
            [{"matcher": "", "hooks": [_handler(arg, timeout)]}]
    PATH.write_text(json.dumps(conf, indent=2) + "\n")
    print(f"  hooks -> {PATH}")
    print("done — start a new zcode session to see the memory block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
