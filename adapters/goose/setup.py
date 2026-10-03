#!/usr/bin/env python3
"""Wire goose (Block / AAIF) to brethof-brain.

goose (1.53) runs Claude-shaped hooks from an Open Plugins folder
(~/.agents/plugins/<name>/hooks/hooks.json) but adds none of their output
to the model's context. What reaches the model every turn is the file named
by GOOSE_MOIM_MESSAGE_FILE, read AFTER the prompt hook ran — so the hooks
write there:

    SessionStart       -> keeps the brief for the first prompt
    UserPromptSubmit   -> writes brief (first prompt) + recall to the turn file
    Stop               -> archives the turn (the prompt kept, last_assistant_message)

goose reads GOOSE_MOIM_MESSAGE_FILE only from the environment, so this adds
it to your shell profile (bash, zsh, fish) or, on Windows, your user
environment. Open a new terminal afterwards.

Run from this directory:  python3 setup.py
Key:                      ~/.brethof-brain/config.json or BRETHOF_BRAIN_API_KEY
Stdlib only, Python 3.9+. Idempotent — safe to re-run after updates.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # plugin repo root
PLUGIN = Path.home() / ".agents" / "plugins" / "brethof-brain"
TURN = Path.home() / ".brethof-brain" / "goose-turn.md"
MARK = "# brethof-brain: goose reads memory from this file every turn"


def _cmd(event: str) -> str:
    if os.name == "nt":
        # goose launches hooks through sh on every platform (Git Bash on Windows)
        py = Path(sys.executable).as_posix()
        return f'BRETHOF_BRAIN_TURN_FILE="{TURN.as_posix()}" "{py}" "{(ROOT / "hook_entry.py").as_posix()}" {event}'
    return f'BRETHOF_BRAIN_TURN_FILE="{TURN}" sh "{ROOT}/hooks/run_hook.sh" {event}'


def _profiles() -> list[str]:
    done = []
    line_sh = f'{MARK}\nexport GOOSE_MOIM_MESSAGE_FILE="{TURN}"\n'
    for rc in (Path.home() / ".bashrc", Path.home() / ".zshrc"):
        if rc.exists() and MARK not in rc.read_text(errors="replace"):
            with open(rc, "a") as fh:
                fh.write("\n" + line_sh)
            done.append(str(rc))
    fish = Path.home() / ".config" / "fish"
    if fish.is_dir():
        f = fish / "conf.d" / "brethof-brain-goose.fish"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f'{MARK}\nset -gx GOOSE_MOIM_MESSAGE_FILE "{TURN}"\n')
        done.append(str(f))
    return done


def main() -> int:
    if not os.environ.get("BRETHOF_BRAIN_API_KEY") and not (Path.home() / ".brethof-brain" / "config.json").exists():
        print("  ! no BRETHOF_BRAIN_API_KEY and no ~/.brethof-brain/config.json — "
              "installing anyway; the hooks stay silent until one exists.")
    (PLUGIN / "hooks").mkdir(parents=True, exist_ok=True)
    TURN.parent.mkdir(parents=True, exist_ok=True)
    TURN.touch()
    hooks = {"hooks": {
        "SessionStart": [{"hooks": [{"type": "command", "command": _cmd("session-start"), "timeout": 15}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": _cmd("prompt-submit"), "timeout": 15}]}],
        "Stop": [{"hooks": [{"type": "command", "command": _cmd("stop"), "timeout": 30}]}],
    }}
    (PLUGIN / "hooks" / "hooks.json").write_text(json.dumps(hooks, indent=2) + "\n")
    print(f"  hooks -> {PLUGIN / 'hooks' / 'hooks.json'}")
    if os.name == "nt":
        r = subprocess.run(["setx", "GOOSE_MOIM_MESSAGE_FILE", str(TURN)], capture_output=True, text=True)
        print("  GOOSE_MOIM_MESSAGE_FILE -> your user environment" if r.returncode == 0 else
              f"  ! could not set GOOSE_MOIM_MESSAGE_FILE — set it to {TURN} yourself")
    else:
        done = _profiles()
        print("  GOOSE_MOIM_MESSAGE_FILE -> " + (", ".join(done) if done else "already set"))
    print(f"done — open a new terminal (GOOSE_MOIM_MESSAGE_FILE={TURN}) and start goose.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
