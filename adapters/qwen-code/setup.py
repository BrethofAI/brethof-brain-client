#!/usr/bin/env python3
"""Wire Qwen Code to your Brain hub.

Qwen Code's hooks share the Claude/Codex shape — JSON on stdin, stdout
injected as context — so the plugin's own hook entry drives all three
lifecycle points. Everything lands in ~/.qwen/settings.json (merged, never
clobbered) plus a memory section in ~/.qwen/QWEN.md.

Run from this directory:  python3 setup.py
Connect first:            brethof-brain pair <hub address>  (writes ~/.brethof-brain/config.json)
Stdlib only, Python 3.9+. Idempotent — safe to re-run after updates.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # plugin repo root
QWEN = Path.home() / ".qwen"
MARK_A, MARK_B = "<!-- brethof-brain:start -->", "<!-- brethof-brain:end -->"
BRIDGE = ROOT / "plugin" / "mcp_bridge.py"


def _paired() -> bool:
    """This machine is paired with a hub: `brethof-brain pair` wrote the
    config file, or the key is in the environment."""
    if os.environ.get("BRETHOF_BRAIN_API_KEY"):
        return True
    home = os.environ.get("BRETHOF_BRAIN_HOME") or str(Path.home() / ".brethof-brain")
    try:
        return bool(json.loads((Path(home) / "config.json").read_text()).get("api_key"))
    except (OSError, ValueError):
        return False

QWEN_SECTION = f"""{MARK_A}
## Long-term memory (brethof-brain)

This machine has persistent cross-session memory. Context blocks marked
"brethof-brain" in your session are recalled memory — trust them. To search
memory yourself use the `brethof-brain` MCP tools (`search_brain`,
`search_history`); save durable facts with `save_project`; standing rules go
through `save_rule`.
{MARK_B}"""


def _hook(*args: str, timeout_s: int = 12) -> dict:
    """Qwen Code reads a hook's timeout in SECONDS since 0.23.4 (2026-09-12;
    it was milliseconds — 12000 there now means three hours). Windows has no
    sh and Qwen runs hooks through cmd.exe, whose quoting breaks a quoted
    program path (QwenLM/qwen-code#8649), so on Windows the hook runs under
    PowerShell ("shell": "powershell") and calls the Python that ran this
    setup on hook_entry.py directly (2026-10-03, the Windows rig row)."""
    if os.name == "nt":
        cmd = f'& "{sys.executable}" "{ROOT / "hook_entry.py"}" {" ".join(args)}'
        return {"hooks": [{"type": "command", "command": cmd, "shell": "powershell",
                           "timeout": timeout_s}]}
    cmd = f'sh "{ROOT}/hooks/run_hook.sh" {" ".join(args)}'
    return {"hooks": [{"type": "command", "command": cmd,
                       "timeout": timeout_s}]}


def main() -> int:
    if not _paired():
        print("  ! this machine is not paired with a hub yet — installing anyway; "
              "run `brethof-brain pair <hub address>` or the hooks stay silent.")
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
            "UserPromptSubmit": _hook("prompt-submit"),
            "Stop": _hook("stop", timeout_s=30)}
    for event, entry in ours.items():
        existing = hooks.setdefault(event, [])
        if not any("run_hook.sh" in h.get("command", "") or "hook_entry.py" in h.get("command", "")
                   for e in existing for h in e.get("hooks", [])):
            existing.append(entry)

    # THE TOOLS OVER STDIO (local-first, 2026-11-20): the bridge reads the
    # hub and the device key `pair` saved on every request — no key in this
    # file, and an older install's HTTP entry is replaced.
    settings.setdefault("mcpServers", {})["brethof-brain"] = {
        "command": sys.executable if os.name == "nt" else "python3",
        "args": [str(BRIDGE)],
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
