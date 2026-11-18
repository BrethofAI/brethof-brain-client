"""GROK APP (2026-11-18): Grok Build in a GUI, with the memory in between.

`brethof-brain grok-app` writes the launcher Grok App (RongleCat/grok-app)
runs as its "CLI path" (Settings → Runtime) and sets that setting. The
launcher starts the real grok through brethof-brain-acp (acp.py); nothing of
Grok App's or Grok Build's changes, so both keep updating on their own.

NOT IN THE CLAUDE CODE PLUGIN (scripts/sync_plugin.py leaves it out): it
writes another app's settings file, which the plugin bundle must never carry
(claude_files.py says why). pip and the other adapters get it.
"""
from __future__ import annotations

import json
import os
import sys

from .config import Config


LAUNCHER_DIR = os.path.join(os.path.expanduser("~"), ".brethof-brain", "bin")


def grok_app_settings_path() -> str:
    """Where Grok App (RongleCat/grok-app) keeps settings.json: $GROK_APP_HOME,
    else its platform data folder (ProjectDirs com.grokapp.grok-app)."""
    if os.environ.get("GROK_APP_HOME"):
        return os.path.join(os.environ["GROK_APP_HOME"], "settings.json")
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        root = os.path.join(home, "Library", "Application Support", "com.grokapp.grok-app")
    elif os.name == "nt":
        root = os.path.join(os.environ.get("APPDATA") or home, "grokapp", "grok-app", "data")
    else:
        root = os.path.join(os.environ.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"), "grok-app")
    return os.path.join(root, "settings.json")


def _find_grok(given: str = "") -> str:
    import shutil
    if given:
        return os.path.abspath(os.path.expanduser(given))
    seen = []
    for c in (shutil.which("grok"), os.path.join(os.path.expanduser("~"), ".grok", "bin", "grok"),
              os.path.join(os.path.expanduser("~"), ".local", "bin", "grok"), "/usr/bin/grok", "/usr/local/bin/grok"):
        if c and os.path.isfile(c) and os.access(c, os.X_OK) and not os.path.realpath(c).startswith(
                os.path.realpath(LAUNCHER_DIR)):
            seen.append(c)
    return seen[0] if seen else ""


def cmd_grok_app(args) -> int:
    """Put the memory between Grok App and Grok Build: write the launcher Grok
    App runs as its "CLI path" (Settings → Runtime) and set that setting. The
    launcher starts the real grok through brethof-brain-acp; nothing of Grok
    App's or Grok Build's changes, so both keep updating on their own."""
    launcher = os.path.join(LAUNCHER_DIR, "grok-with-brain" + (".cmd" if os.name == "nt" else ""))
    settings = grok_app_settings_path()
    if args.undo:
        changed = _grok_app_set(settings, None, launcher)
        try:
            os.remove(launcher)
        except OSError:
            pass
        print("Grok App runs Grok Build directly again" + (" (restart Grok App)." if changed else "."))
        return 0
    grok = _find_grok(args.grok)
    if not grok or not os.path.isfile(grok):
        print("error: Grok Build (grok) not found — install it first, or pass --grok /path/to/grok",
              file=sys.stderr)
        return 1
    cfg = Config.load()
    if not cfg.configured():
        print("note: this machine is not connected to a memory yet (brethof-brain pair <hub>); "
              "Grok App will work, without memory, until it is.", file=sys.stderr)
    os.makedirs(LAUNCHER_DIR, exist_ok=True)
    py = sys.executable
    if os.name == "nt":
        body = f'@echo off\r\n"{py}" -m brethof_brain_client.acp --real "{grok}" -- %*\r\n'
    else:
        body = f'#!/bin/sh\nexec "{py}" -m brethof_brain_client.acp --real "{grok}" -- "$@"\n'
    with open(launcher, "w", encoding="utf-8", newline="") as f:
        f.write(body)
    if os.name != "nt":
        os.chmod(launcher, 0o755)
    print(f"Launcher: {launcher}\n  runs {grok} with the memory in between")
    if _grok_app_set(settings, launcher, launcher):
        print(f"Grok App's CLI path is set ({settings}). Restart Grok App to use it.")
    else:
        print("Grok App's settings were not found (open it once first), or set it by hand:\n"
              f"  Grok App → Settings → Runtime → CLI path → {launcher}")
    return 0


def _grok_app_set(settings: str, value, launcher: str) -> bool:
    """Set (or, with None, clear — only if it is ours) Grok App's manualCliPath,
    keeping every other setting. False when there is no settings file."""
    try:
        with open(settings, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    if value is None:
        if data.get("manualCliPath") != launcher:
            return False
        data.pop("manualCliPath", None)
    else:
        data["manualCliPath"] = value
    tmp = settings + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, settings)
    return True

