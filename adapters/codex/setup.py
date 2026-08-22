#!/usr/bin/env python3
"""Wire OpenAI Codex CLI to brethof-brain cloud.

Codex (v0.124+) hooks share Claude Code's shape — JSON on stdin with
session_id / cwd / prompt / transcript_path, stdout injected as context —
so the plugin's own hook entry drives all three lifecycle points directly:

1. ~/.codex/hooks.json      — SessionStart / UserPromptSubmit / Stop hooks
2. ~/.codex/config.toml     — brethof-brain HTTP MCP server (bearer via env)
3. ~/.codex/AGENTS.md       — short memory section (marker-guarded)

Run from this directory:  python3 setup.py
Environment:              BRETHOF_BRAIN_API_KEY (exported wherever codex runs)
Stdlib only, Python 3.9+. Idempotent — safe to re-run after updates.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # plugin repo root
CODEX = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
ENDPOINT = os.environ.get("BRETHOF_BRAIN_ENDPOINT", "https://api.brethof.cloud")
MARK_A, MARK_B = "<!-- brethof-brain:start -->", "<!-- brethof-brain:end -->"

AGENTS_SECTION = f"""{MARK_A}
## Long-term memory (brethof-brain)

This machine has persistent cross-session memory. Context blocks marked
"brethof-brain" in your session are recalled memory — trust them. To search
memory yourself use the `brethof-brain` MCP tools (`search_brain`,
`search_history`); save durable facts with `save_project`. Rules and
conventions you are told to remember belong in `save_rule`.
{MARK_B}"""


def _hook(event: str, *args: str) -> dict:
    cmd = f'sh "{ROOT}/hooks/run_hook.sh" {" ".join(args)}'
    return {"matcher": "", "hooks": [{"type": "command", "command": cmd,
                                      "timeout": 12 if event != "Stop" else 30}]}


def install_hooks() -> None:
    path = CODEX / "hooks.json"
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except ValueError:
            print(f"  ! {path} is not valid JSON — leaving it untouched")
            return
    hooks = data.setdefault("hooks", {})
    ours = {
        "SessionStart": _hook("SessionStart", "session-start"),
        "UserPromptSubmit": _hook("UserPromptSubmit", "prompt-submit", "1"),
        "Stop": _hook("Stop", "stop"),
    }
    for event, entry in ours.items():
        existing = hooks.setdefault(event, [])
        if not any("run_hook.sh" in h.get("command", "")
                   for e in existing for h in e.get("hooks", [])):
            existing.append(entry)
    CODEX.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"  hooks -> {path}")


def install_mcp() -> None:
    path = CODEX / "config.toml"
    text = path.read_text() if path.exists() else ""
    changed = False
    if "mcp_servers.brethof-brain" not in text \
            and "mcp_servers.brethof_brain" not in text:
        text += (f'\n[mcp_servers.brethof-brain]\n'
                 f'url = "{ENDPOINT}/v1/mcp"\n'
                 f'bearer_token_env_var = "BRETHOF_BRAIN_API_KEY"\n')
        changed = True
    # notify = the archival channel that actually fires in `codex exec`
    # (verified 0.147.0: hooks.json events do NOT fire headless; notify does,
    # with the full exchange). Never clobber an existing notify program.
    if "notify" not in text.splitlines()[0:1] and "\nnotify" not in text:
        text = (f'notify = ["python3", '
                f'"{ROOT}/adapters/codex/notify_archive.py"]\n') + text
        changed = True
    else:
        print("  ! a notify program is already configured — archival notify "
              "NOT installed (chain it manually if you want both)")
    # Hooks are default-on but the canonical key makes intent visible, and
    # guards against a future default flip.
    if "hooks = true" not in text and "codex_hooks" not in text:
        if "[features]" in text:
            text = text.replace("[features]", "[features]\nhooks = true", 1)
        else:
            text += "\n[features]\nhooks = true\n"
        changed = True
    if changed:
        CODEX.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    print(f"  mcp + notify + hooks feature -> {path}")
    print("  ! ONE MANUAL STEP LEFT: codex requires you to TRUST new hooks")
    print("    once — open codex, run /hooks, and trust the brethof-brain")
    print("    entries. Until then codex SILENTLY SKIPS them (their hash is")
    print("    recorded, so an adapter update needs re-trusting).")


def install_agents_md() -> None:
    path = CODEX / "AGENTS.md"
    text = path.read_text() if path.exists() else ""
    if MARK_A in text:
        head, _, rest = text.partition(MARK_A)
        _, _, tail = rest.partition(MARK_B)
        text = head + AGENTS_SECTION + tail
    else:
        text = (text.rstrip() + "\n\n" if text.strip() else "") \
               + AGENTS_SECTION + "\n"
    path.write_text(text)
    print(f"  memory section -> {path}")


def main() -> int:
    if not os.environ.get("BRETHOF_BRAIN_API_KEY"):
        print("  ! BRETHOF_BRAIN_API_KEY is not set — installing anyway; "
              "export it wherever you run codex or the hooks stay silent.")
    install_hooks()
    install_mcp()
    install_agents_md()
    print("done — start a new codex session to see the memory block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
