"""Everything that edits Claude Code's own files (2026-10-04): the hooks in
~/.claude/settings.json (`install-hooks` / `uninstall-hooks`, and doctor's
wiring check) and the managed memory-provider block in ~/.claude/CLAUDE.md.

It lives apart so the Claude Code PLUGIN can ship without it:
scripts/sync_plugin.py leaves this file out of plugin/. Anthropic's
directory scan flags a plugin that edits Claude's settings or instruction
files ("weakens permission or sandbox controls"), and a plugin needs none of
it, because Claude Code loads the plugin's own hooks. The pip-installed
client keeps all of it; for a plugin install the block is a manual step in
the README.
"""
from __future__ import annotations

import json
import os
import re
import sys

from .cli import HOOK_EVENTS

CLAUDE_SETTINGS = os.path.expanduser("~/.claude/settings.json")
CLAUDE_USER_MD = os.path.expanduser("~/.claude/CLAUDE.md")

# The PROVIDER BLOCK — our one scriptable line into the harness's own
# instruction channel (founder, 2026-08-10: "CLAUDE.md is the only thing
# which we can really script, so we could add the provider"). The
# hostile-harness bait measured why: a workspace CLAUDE.md saying "record
# facts in this file" was obeyed in half the runs, because agents obey
# CLAUDE.md. So the Brain claims the same channel — a managed block in
# the USER-level file (loads in every project); the customer's own
# project CLAUDE.md is never touched.
_MD_BEGIN = "<!-- brain:provider (managed by brethof-brain install-hooks) -->"
_MD_END = "<!-- /brain:provider -->"
PROVIDER_BLOCK = f"""{_MD_BEGIN}
## Memory provider: the Brain

Long-term memory on this machine is the BRAIN (the `brain` MCP server).
It is shared across sessions, projects and agents, curated automatically,
and survives every restart, reboot and compact. The session-start and
prompt hooks put the rules, each project's purpose, the last sessions'
notes and the matching records in front of you — if that block is
missing, the memory stack is broken; fix it first.

- Four doors, nothing else writes: `save_project` / `save_general` (a
  fact, a decision, a measurement — the Brain decides what becomes a
  record), `save_note` (where your work stands, before you stop),
  `save_playbook` (how a thing is done), `save_rule` (a standing
  convention). Unsure: save it.
- To recall: `search_brain` first (the current truth, with the history
  of decisions under it), then `search_history` (everything said, raw),
  `get_record` — BEFORE saying you don't remember something, and before
  diagnosing anything.
- Do NOT keep long-term memory in local files (CLAUDE.md, MEMORY.md,
  Claude Code's auto memory, notes): files are per-machine and
  unsearchable — a fact filed there is invisible to every other session
  and agent. When asked to remember something, save it to the Brain.
  Files are for code and config; memory belongs in the Brain.
{_MD_END}"""


def _install_provider_block() -> str:
    """Idempotent upsert of the managed block in ~/.claude/CLAUDE.md.
    Returns what happened: 'added' | 'updated' | 'current' | 'FAILED …'."""
    try:
        orig = ""
        if os.path.exists(CLAUDE_USER_MD):
            with open(CLAUDE_USER_MD, encoding="utf-8") as f:
                orig = f.read()
        # A block planted by the pre-rename client carries the old marker;
        # normalize it so the upsert below replaces it instead of doubling.
        # Compare against ORIG — a marker-only change must still be written.
        text = orig.replace("(managed by brethof-mind install-hooks)",
                            "(managed by brethof-brain install-hooks)")
        if _MD_BEGIN in text and _MD_END in text:
            head, _, rest = text.partition(_MD_BEGIN)
            _, _, tail = rest.partition(_MD_END)
            new = head + PROVIDER_BLOCK + tail
            action = "current" if new == orig else "updated"
        else:
            new = ((text.rstrip() + "\n\n") if text.strip() else "") \
                + PROVIDER_BLOCK + "\n"
            action = "added"
        if action != "current":
            os.makedirs(os.path.dirname(CLAUDE_USER_MD), exist_ok=True)
            with open(CLAUDE_USER_MD, "w", encoding="utf-8") as f:
                f.write(new)
        return action
    except OSError as e:
        return f"FAILED ({e})"


def _remove_provider_block() -> bool:
    """Remove ONLY our managed block; everything else passes untouched."""
    try:
        if not os.path.exists(CLAUDE_USER_MD):
            return False
        with open(CLAUDE_USER_MD, encoding="utf-8") as f:
            text = f.read()
        if _MD_BEGIN not in text:
            return False
        head, _, rest = text.partition(_MD_BEGIN)
        _, _, tail = rest.partition(_MD_END)
        new = (head.rstrip() + "\n" + tail.lstrip()).strip()
        with open(CLAUDE_USER_MD, "w", encoding="utf-8") as f:
            f.write(new + ("\n" if new else ""))
        return True
    except OSError:
        return False

# Matches our own installed hook command and captures the baked interpreter:
#   "<python path>" -m brethof_brain_client.hook <event> [part]
# Accepts the pre-rename module too, so install-hooks MIGRATES an old
# install's entries in place instead of orphaning them beside new ones.
_CMD_RE = re.compile(r'^"([^"]+)" -m brethof_(?:brain|mind)_client\.hook (\S+(?: \d+)?)$')


def _hook_command(event_arg: str) -> str:
    """The command Claude Code runs for a hook. Bakes in THIS interpreter so the
    right Python (the one this package is installed into) is always used.
    Forward slashes always — Claude Code runs hook commands through bash even on
    Windows, and bash eats backslashes."""
    py = sys.executable.replace("\\", "/")
    return f'"{py}" -m brethof_brain_client.hook {event_arg}'


def _ours(command: str, event_arg: str):
    """If ``command`` is our hook command for ``event_arg``, return the baked
    interpreter path; else None."""
    m = _CMD_RE.match(command or "")
    return m.group(1) if m and m.group(2) == event_arg else None


# ── ~/.claude/settings.json plumbing (always backed up, always atomic) ───────

def _load_settings() -> dict:
    if os.path.exists(CLAUDE_SETTINGS):
        try:
            with open(CLAUDE_SETTINGS, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            print(f"error: {CLAUDE_SETTINGS} is not valid JSON - fix it first",
                  file=sys.stderr)
            raise SystemExit(2)
        if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
            print(f"error: {CLAUDE_SETTINGS} has an unexpected shape "
                  "(expected an object, with 'hooks' an object) - fix it first",
                  file=sys.stderr)
            raise SystemExit(2)
        return data
    return {}


def _write_settings(settings: dict) -> None:
    """Back up the current file, then write atomically (tmp + os.replace) so an
    interrupted write can never truncate the user's whole Claude Code config."""
    os.makedirs(os.path.dirname(CLAUDE_SETTINGS), exist_ok=True)
    if os.path.exists(CLAUDE_SETTINGS):
        try:
            with open(CLAUDE_SETTINGS, encoding="utf-8") as f:
                old = f.read()
            with open(CLAUDE_SETTINGS + ".bak", "w", encoding="utf-8") as f:
                f.write(old)
        except Exception:
            pass
    tmp = CLAUDE_SETTINGS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, CLAUDE_SETTINGS)


def install_hooks(args) -> int:
    settings = _load_settings()
    hooks = settings.setdefault("hooks", {})
    added = repaired = 0
    # MIGRATION: the pre-parts registration was a single bare "session-start"
    # hook. Left in place next to "session-start 1/2" it would inject the
    # whole payload a THIRD time — remove ours (and only ours) on sight.
    legacy = 0
    for g in hooks.get("SessionStart", []) or []:
        if isinstance(g, dict):
            inner = [h for h in g.get("hooks", [])
                     if not (isinstance(h, dict)
                             and _ours(h.get("command", ""), "session-start"))]
            legacy += len(g.get("hooks", [])) - len(inner)
            g["hooks"] = inner
    if legacy:
        repaired += legacy
    for event_name, event_arg in HOOK_EVENTS:
        command = _hook_command(event_arg)
        groups = hooks.setdefault(event_name, [])
        if not isinstance(groups, list):
            print(f"error: settings hooks.{event_name} is not a list - fix it first",
                  file=sys.stderr)
            return 2
        found = False
        for g in groups:
            if not isinstance(g, dict):
                continue
            for h in g.get("hooks", []):
                if not isinstance(h, dict):
                    continue
                py = _ours(h.get("command", ""), event_arg)
                if py is None:
                    continue
                found = True
                # Repair a stale interpreter (deleted venv, Python upgrade):
                # the baked path must exist AND be this install's interpreter.
                if not os.path.exists(py) or h.get("command") != command:
                    h["command"] = command
                    repaired += 1
        if not found:
            groups.append({"matcher": "", "hooks": [{"type": "command", "command": command}]})
            added += 1

    if added or repaired:
        _write_settings(settings)
        what = []
        if added:
            what.append(f"wired {added} hook(s)")
        if repaired:
            what.append(f"repaired {repaired} stale interpreter path(s)")
        print(f"OK: {', '.join(what)} in {CLAUDE_SETTINGS} (backup: {CLAUDE_SETTINGS}.bak)")
        print("  Restart Claude Code (or start a new session) to activate.")
    else:
        print("OK: hooks already installed - nothing to do")
    action = _install_provider_block()
    print(f"OK: Brain provider block {action} in {CLAUDE_USER_MD}")
    return 0


def uninstall_hooks(args) -> int:
    if not os.path.exists(CLAUDE_SETTINGS):
        print("OK: no Claude Code settings file - nothing installed")
        return 0
    settings = _load_settings()
    hooks = settings.get("hooks", {})
    removed = 0
    # "session-start" (bare) = the pre-parts registration — still removable.
    for event_name, event_arg in HOOK_EVENTS + [("SessionStart", "session-start")]:
        groups = hooks.get(event_name, [])
        if not isinstance(groups, list):
            continue
        kept = []
        for g in groups:
            if not isinstance(g, dict):
                kept.append(g)  # not ours — pass through untouched
                continue
            inner = [h for h in g.get("hooks", [])
                     if not (isinstance(h, dict) and _ours(h.get("command", ""), event_arg))]
            lost = len(g.get("hooks", [])) - len(inner)
            removed += lost
            # Drop a group only if WE emptied it; a user's own (even empty)
            # group passes through untouched.
            if inner or not lost:
                g["hooks"] = inner if lost else g.get("hooks", inner)
                kept.append(g)
        if kept:
            hooks[event_name] = kept
        elif event_name in hooks:
            del hooks[event_name]
    if removed:
        _write_settings(settings)
    print(f"OK: removed {removed} brethof-brain hook(s) from {CLAUDE_SETTINGS}")
    if _remove_provider_block():
        print(f"OK: removed the Brain provider block from {CLAUDE_USER_MD}")
    return 0




def wiring_report(check) -> None:
    """doctor: are the hooks wired, and does each baked interpreter exist?"""
    try:
        settings = _load_settings()
    except SystemExit:
        settings = {}
    hooks = settings.get("hooks", {}) if isinstance(settings.get("hooks", {}), dict) else {}
    for event_name, event_arg in HOOK_EVENTS:
        pys = [
            _ours(h.get("command", ""), event_arg)
            for g in hooks.get(event_name, []) if isinstance(g, dict)
            for h in g.get("hooks", []) if isinstance(h, dict)
        ]
        pys = [p for p in pys if p]
        if not pys:
            check(f"hook {event_name}", False, "run: brethof-brain install-hooks")
        elif not all(os.path.exists(p) for p in pys):
            dead = next(p for p in pys if not os.path.exists(p))
            check(f"hook {event_name}", False,
                  f"interpreter missing: {dead} - rerun: brethof-brain install-hooks")
        else:
            check(f"hook {event_name}", True)

