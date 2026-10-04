#!/usr/bin/env python3
"""Copy the shared client code into plugin/ — the Claude Code plugin's own
folder, which is all the plugin ships (2026-10-04).

Why a folder of its own: Claude Code installs a plugin from its marketplace
`source` folder and copies nothing outside it (a symlink that leaves the
folder is refused), and Anthropic's directory scans every file the plugin
ships. With the plugin at the repo root it shipped the local-edition
installer, the CI file and twenty other harnesses' adapters, and the scan
flagged them. plugin/ holds the plugin's own files (manifest, icon, hooks,
MCP bridge, commands) plus COPIES of the shared code below, which stays
where every other adapter and `pip install` find it.

    python3 scripts/sync_plugin.py           # copy
    python3 scripts/sync_plugin.py --check   # exit 1 on any drift (the test suite runs this)
"""
from __future__ import annotations

import filecmp
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "plugin"
SHARED_FILES = ("hook_entry.py", "connect.py", "hooks/run_hook.sh", "LICENSE")
SHARED_PACKAGE = "brethof_brain_client"


def pairs() -> list[tuple[Path, Path]]:
    out = [(REPO / f, PLUGIN / f) for f in SHARED_FILES]
    out += [(p, PLUGIN / SHARED_PACKAGE / p.name) for p in sorted((REPO / SHARED_PACKAGE).glob("*.py"))]
    return out


def drift() -> list[str]:
    bad = [str(dst.relative_to(REPO)) for src, dst in pairs()
           if not dst.is_file() or not filecmp.cmp(src, dst, shallow=False)]
    want = {p.name for p in (REPO / SHARED_PACKAGE).glob("*.py")}
    bad += [str(p.relative_to(REPO)) + " (stale)" for p in (PLUGIN / SHARED_PACKAGE).glob("*.py")
            if p.name not in want]
    return bad


def main(argv: list[str]) -> int:
    if "--check" in argv:
        bad = drift()
        for b in bad:
            print(f"out of sync: {b}")
        return 1 if bad else 0
    for p in (PLUGIN / SHARED_PACKAGE).glob("*.py"):
        p.unlink()
    for src, dst in pairs():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print(f"synced {len(pairs())} files into {PLUGIN.relative_to(REPO)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
