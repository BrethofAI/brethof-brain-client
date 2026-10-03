#!/usr/bin/env python3
"""Wire Google Antigravity's CLI (agy) to brethof-brain.

Writes a `brethof-brain` entry into the user hooks file
~/.gemini/config/hooks.json (agy 1.2.16: {"<name>": {"<Event>": [handler]}},
flat handler lists, timeouts in seconds), calling antigravity_hook.py:

    PreInvocation  -> the brief and this prompt's recall, on every model call
                      (agy's injected text reaches one call only)
    Stop           -> archive the turn from agy's transcript

agy runs hook commands with `sh -c` (`cmd /c` on Windows).

Run from this directory:  python3 setup.py
Key:                      ~/.brethof-brain/config.json or BRETHOF_BRAIN_API_KEY
Stdlib only, Python 3.9+. Idempotent — safe to re-run after updates.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "antigravity_hook.py"
PATH = Path.home() / ".gemini" / "config" / "hooks.json"


def _short(path: Path) -> str:
    """A path with no spaces: agy on Windows splits the command itself and
    keeps quote marks as part of the word (2026-10-03: python was handed
    '"C:\\...\\antigravity_hook.py"' and looked for it inside the config
    folder) — so the Windows command carries no quotes, and a path with a
    space goes by its 8.3 short name."""
    p = str(path)
    if " " not in p:
        return p
    import ctypes
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024)
    return buf.value if n else p


def _cmd(event: str) -> str:
    if os.name == "nt":
        # no quotes (see _short); the Python launcher, called by name
        return f"py -3 {_short(HOOK)} {event}"
    return f'python3 "{HOOK}" {event}'


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
    conf["brethof-brain"] = {
        "PreInvocation": [{"type": "command", "command": _cmd("pre-invocation"), "timeout": 15}],
        "Stop": [{"type": "command", "command": _cmd("stop"), "timeout": 30}],
    }
    PATH.write_text(json.dumps(conf, indent=2) + "\n")
    print(f"  hooks -> {PATH}")
    print("done — start a new agy conversation to see the memory block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
