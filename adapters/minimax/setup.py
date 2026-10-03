#!/usr/bin/env python3
"""Install brethof-brain into MiniMax Code (mcode) as a local plugin.

MiniMax Code loads Claude Code plugins — .claude-plugin/plugin.json plus
hooks/hooks.json — from direct child folders of its plugins directory
(~/.minimax/plugins, or $MINIMAX_DATA_DIR/plugins); symlinks are refused, so
the plugin is COPIED. Two of its rules shape the copy (MiniMax Code 0.6.2,
docs/hooks.md, 2026-10-03): a hook timeout must be 1-10 seconds or the
handler is dropped, so every timeout is capped at 10; and hooks run with a
stripped environment, so the key comes from ~/.brethof-brain/config.json.

Run from this directory:  python3 setup.py   (re-run after updating the plugin)
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent   # plugin repo root
DATA = Path(os.environ.get("MINIMAX_DATA_DIR", Path.home() / ".minimax"))
KEEP = (".claude-plugin", "hooks", "brethof_brain_client", "hook_entry.py")


def main() -> int:
    if not (Path.home() / ".brethof-brain" / "config.json").exists():
        print("  ! ~/.brethof-brain/config.json is missing — MiniMax runs hooks with a stripped "
              "environment, so the key must be in that file; installing anyway.")
    dest = DATA / "plugins" / "brethof-brain"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in KEEP:
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, dest / name, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            shutil.copy2(src, dest / name)
    hooks_path = dest / "hooks" / "hooks.json"
    hooks = json.loads(hooks_path.read_text())
    for entries in hooks.get("hooks", {}).values():
        for e in entries:
            for h in e.get("hooks", []):
                h["timeout"] = max(1, min(10, int(h.get("timeout") or 5)))
    hooks_path.write_text(json.dumps(hooks, indent=2) + "\n")
    print(f"  plugin -> {dest} (hook timeouts capped at 10 s)")
    print("done — start a new mcode session to see the memory block.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
