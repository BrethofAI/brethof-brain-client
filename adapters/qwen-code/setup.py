#!/usr/bin/env python3
"""Wire Qwen Code to brethof-brain cloud.

Qwen Code's hooks share the Claude/Codex shape — JSON on stdin, stdout
injected as context — so the plugin's own hook entry drives all three
lifecycle points. Everything lands in ~/.qwen/settings.json (merged, never
clobbered) plus a memory section in ~/.qwen/QWEN.md.

Run from this directory:  python3 setup.py
Environment:              BRETHOF_BRAIN_API_KEY (exported wherever qwen runs)
Stdlib only, Python 3.9+. Idempotent — safe to re-run after updates.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # plugin repo root
QWEN = Path.home() / ".qwen"
ENDPOINT = os.environ.get("BRETHOF_BRAIN_ENDPOINT", "https://api.brethof.cloud")
MARK_A, MARK_B = "<!-- brethof-brain:start -->", "<!-- brethof-brain:end -->"

QWEN_SECTION = f"""{MARK_A}
## Long-term memory (brethof-brain)

This machine has persistent cross-session memory. Context blocks marked
"brethof-brain" in your session are recalled memory — trust them. To search
memory yourself use the `brethof-brain` MCP tools (`search_brain`,
`search_history`); save durable facts with `save_project`; standing rules go
through `save_rule`.
{MARK_B}"""


def _hook(*args: str, timeout_ms: int = 12000) -> dict:
    cmd = f'sh "{ROOT}/hooks/run_hook.sh" {" ".join(args)}'
    return {"hooks": [{"type": "command", "command": cmd,
                       "timeout": timeout_ms}]}


def main() -> int:
    if not os.environ.get("BRETHOF_BRAIN_API_KEY"):
        print("  ! BRETHOF_BRAIN_API_KEY is not set — installing anyway; "
              "export it wherever you run qwen or the hooks stay silent.")
    QWEN.mkdir(parents=True, exist_ok=True)
    spath = QWEN / "settings.json"
    settings = {}
    if spath.exists():
        try:
            settings = json.loads(spath.read_text())
        except ValueError:
            print(f"  ! {spath} is not valid JSON — leaving it untouched")
            return 1

    hooks = settings.setdefault("hooks", {})
    ours = {"SessionStart": _hook("session-start"),
            "UserPromptSubmit": _hook("prompt-submit", "1"),
            "Stop": _hook("stop", timeout_ms=30000)}
    for event, entry in ours.items():
        existing = hooks.setdefault(event, [])
        if not any("run_hook.sh" in h.get("command", "")
                   for e in existing for h in e.get("hooks", [])):
            existing.append(entry)

    key = os.environ.get("BRETHOF_BRAIN_API_KEY", "")
    settings.setdefault("mcpServers", {})["brethof-brain"] = {
        "httpUrl": f"{ENDPOINT}/v1/mcp",
        "headers": {"Authorization": f"Bearer {key}"} if key else {},
        "timeout": 20000,
    }
    spath.write_text(json.dumps(settings, indent=2) + "\n")
    print(f"  hooks + mcp -> {spath}")

    mpath = QWEN / "QWEN.md"
    text = mpath.read_text() if mpath.exists() else ""
    if MARK_A in text:
        head, _, rest = text.partition(MARK_A)
        _, _, tail = rest.partition(MARK_B)
        text = head + QWEN_SECTION + tail
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") \
               + QWEN_SECTION + "\n"
    mpath.write_text(text)
    print(f"  memory section -> {mpath}")
    print("done — start a new qwen session to see the memory block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
