"""``brethof-mind`` command-line tool: set up the client, wire Claude Code, and
check status. Stdlib only.

    brethof-mind setup --api-key bm_live_xxx [--endpoint URL] [--project KEY]
    brethof-mind install-hooks     # add the 4 hooks to ~/.claude/settings.json
    brethof-mind mcp-command       # print the `claude mcp add` line to run
    brethof-mind status            # show plan + usage
    brethof-mind doctor            # diagnose config / connectivity / wiring

(The hook dispatcher also understands a 5th event, ``commit``, for programmatic
wiring — e.g. a git post-commit hook; the installer wires the 4 session events.)
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import urllib.parse

from . import DEFAULT_ENDPOINT, __version__
from .client import Client, ClientError
from .config import (CONFIG_PATH, Config, ensure_dirs, save_file, valid_project)

# SessionStart is registered once PER PART: Claude Code caps each hook's
# output at 10k chars, so the server auto-splits the payload into as many
# ≤9k parts as the tenant's rules + projects need and returns "" for unused
# parts. 12 slots ≈ a 108KB envelope — sized so the server-side law
# budgets (48K general + 20K project rule pools) can never crowd out the
# briefing sections; same-event hooks run in parallel, so empty slots are
# almost free.
SESSION_START_PARTS = 12
# UserPromptSubmit is registered once per ambient part: part 1 = rule
# reminder + dead-end cards + top record, part 2 = the second strong match
# alone. One record per hook keeps every injection WHOLE under the 10k
# per-hook cap — a cut record misleads (the model uses cut text as if
# complete), so nothing is ever trimmed to fit.
PROMPT_SUBMIT_PARTS = 2
HOOK_EVENTS = (
    [("SessionStart", f"session-start {i}")
     for i in range(1, SESSION_START_PARTS + 1)]
    + [("UserPromptSubmit", f"prompt-submit {i}")
       for i in range(1, PROMPT_SUBMIT_PARTS + 1)]
    + [
        ("Stop", "stop"),
        ("PreCompact", "pre-compact"),
    ])
CLAUDE_SETTINGS = os.path.expanduser("~/.claude/settings.json")
CLAUDE_USER_MD = os.path.expanduser("~/.claude/CLAUDE.md")
MCP_PATH = "/v1/mcp"

# The PROVIDER BLOCK — our one scriptable line into the harness's own
# instruction channel (founder, 2026-08-10: "CLAUDE.md is the only thing
# which we can really script, so we could add the provider"). The
# hostile-harness bait measured why: a workspace CLAUDE.md saying "record
# facts in this file" was obeyed in half the runs, because agents obey
# CLAUDE.md. So the Brain claims the same channel — a managed block in
# the USER-level file (loads in every project); the customer's own
# project CLAUDE.md is never touched.
_MD_BEGIN = "<!-- brain:provider (managed by brethof-mind install-hooks) -->"
_MD_END = "<!-- /brain:provider -->"
PROVIDER_BLOCK = f"""{_MD_BEGIN}
## Memory provider: the Brain

Long-term memory on this machine is the BRAIN (the `brain` MCP server).
It is shared across sessions, projects and agents, curated automatically,
and survives every restart, reboot and compact.

- To remember something: save it to the Brain (`save_project` /
  `save_general`) — it files within a minute.
- To recall: search the Brain (`search_brain`, `list_brain`) BEFORE
  saying you don't remember something.
- Do NOT keep long-term memory in local files (CLAUDE.md, MEMORY.md,
  notes): files are per-machine and unsearchable — a fact filed there is
  invisible to every other session and agent. Files are for code and
  config; memory belongs in the Brain.
{_MD_END}"""


def _install_provider_block() -> str:
    """Idempotent upsert of the managed block in ~/.claude/CLAUDE.md.
    Returns what happened: 'added' | 'updated' | 'current' | 'FAILED …'."""
    try:
        text = ""
        if os.path.exists(CLAUDE_USER_MD):
            with open(CLAUDE_USER_MD, encoding="utf-8") as f:
                text = f.read()
        if _MD_BEGIN in text and _MD_END in text:
            head, _, rest = text.partition(_MD_BEGIN)
            _, _, tail = rest.partition(_MD_END)
            new = head + PROVIDER_BLOCK + tail
            action = "current" if new == text else "updated"
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
#   "<python path>" -m brethof_mind_client.hook <event> [part]
_CMD_RE = re.compile(r'^"([^"]+)" -m brethof_mind_client\.hook (\S+(?: \d+)?)$')


def _hook_command(event_arg: str) -> str:
    """The command Claude Code runs for a hook. Bakes in THIS interpreter so the
    right Python (the one this package is installed into) is always used.
    Forward slashes always — Claude Code runs hook commands through bash even on
    Windows, and bash eats backslashes."""
    py = sys.executable.replace("\\", "/")
    return f'"{py}" -m brethof_mind_client.hook {event_arg}'


def _ours(command: str, event_arg: str):
    """If ``command`` is our hook command for ``event_arg``, return the baked
    interpreter path; else None."""
    m = _CMD_RE.match(command or "")
    return m.group(1) if m and m.group(2) == event_arg else None


def _valid_endpoint(url: str) -> str:
    """Return a normalized endpoint or raise ValueError with a human reason."""
    url = (url or "").strip().rstrip("/")
    p = urllib.parse.urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise ValueError(f"endpoint must be a full https:// URL, got {url!r}")
    if p.scheme == "http" and p.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("http:// endpoints would send your API key in cleartext — "
                         "use https:// (http is allowed for localhost only)")
    return url


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


# ── commands ────────────────────────────────────────────────────────────────

def cmd_setup(args) -> int:
    api_key = args.api_key
    if not api_key:
        if sys.stdin.isatty():
            # getpass: the key must not echo to the terminal or scrollback.
            api_key = getpass.getpass(
                "brethof-mind API key (bm_live_... or bm_test_..., hidden): ").strip()
        else:
            print("error: --api-key required (or run in an interactive terminal)",
                  file=sys.stderr)
            return 2
    if not api_key.startswith(("bm_live_", "bm_test_")):
        print("warning: key doesn't look like a brethof-mind key (bm_live_/bm_test_)",
              file=sys.stderr)

    ensure_dirs()
    data = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    try:
        endpoint = _valid_endpoint(args.endpoint or data.get("endpoint") or DEFAULT_ENDPOINT)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    data["api_key"] = api_key
    data["endpoint"] = endpoint
    if args.project:
        if not valid_project(args.project):
            print(f"error: invalid project key '{args.project}' "
                  "(must match [a-z][a-z0-9_]{0,15})", file=sys.stderr)
            return 2
        data["default_project"] = args.project
    data.setdefault("default_project", "global")
    save_file(data)
    print(f"OK: saved {CONFIG_PATH} (readable by you only)")

    # verify connectivity
    cfg = Config.load()
    try:
        snap = Client(cfg).get("/v1/usage")
        plan = snap.get("plan", "?")
        print(f"OK: connected to {cfg.endpoint} - plan: {plan}")
    except ClientError as e:
        print(f"warning: saved, but could not reach the service yet: {e}", file=sys.stderr)

    print("\nNext:")
    print("  brethof-mind install-hooks   # auto-load & archive memory in Claude Code")
    print("  brethof-mind mcp-command     # wire the memory tools (remote MCP)")
    return 0


def cmd_install_hooks(args) -> int:
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


def cmd_uninstall_hooks(args) -> int:
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
    print(f"OK: removed {removed} brethof-mind hook(s) from {CLAUDE_SETTINGS}")
    if _remove_provider_block():
        print(f"OK: removed the Brain provider block from {CLAUDE_USER_MD}")
    return 0


def cmd_mcp_command(args) -> int:
    cfg = Config.load()
    key = cfg.api_key or "bm_live_YOUR_KEY"
    url = cfg.endpoint + MCP_PATH
    print("Run this once to add the Brain to Claude Code:\n")
    # ONE line, no continuation characters — POSIX `\` breaks in PowerShell/cmd.
    # The server registers as "brain": the harness stamps that name into
    # every tool id the model reads (mcp__brain__search_brain).
    print(f'  claude mcp add --transport http brain {url} '
          f'--header "Authorization: Bearer {key}"')
    print("\n(That stores the server in Claude Code's MCP config; the tools then "
          "appear as save_project, search_brain, list_brain, ...)")
    if cfg.api_key:
        print("note: the line contains your real API key and will land in shell "
              "history - clear it afterwards if the machine is shared.")
    return 0


def cmd_status(args) -> int:
    cfg = Config.load()
    if not cfg.configured():
        print("not configured - run: brethof-mind setup --api-key ...", file=sys.stderr)
        return 2
    try:
        snap = Client(cfg).get("/v1/usage")
    except ClientError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    print(f"endpoint : {cfg.endpoint}")
    print(f"plan     : {snap.get('plan', '?')}")
    enforced = snap.get("enforced")
    if enforced is not None:
        print(f"enforced : {enforced}  (caps {'block' if enforced else 'measured only'})")
    counters = snap.get("counters") or snap.get("usage") or {}
    if isinstance(counters, dict) and counters:
        print("usage:")
        for k, v in counters.items():
            print(f"  {k:<22} {v}")
    return 0


def cmd_doctor(args) -> int:
    cfg = Config.load()
    ok = True

    def check(label, good, detail=""):
        nonlocal ok
        mark = "[ok]" if good else "[XX]"
        ok = ok and good
        print(f"  {mark} {label}" + (f" - {detail}" if detail else ""))

    print("brethof-mind client doctor")
    print(f"client version : {__version__}")
    check("config file", os.path.exists(CONFIG_PATH), CONFIG_PATH)
    check("api key set", bool(cfg.api_key),
          "run: brethof-mind setup" if not cfg.api_key else cfg.api_key[:12] + "...")
    try:
        _valid_endpoint(cfg.endpoint)
        check("endpoint", True, cfg.endpoint)
    except ValueError as e:
        check("endpoint", False, str(e))

    # project routing sanity
    env_proj = os.environ.get("BRETHOF_MIND_PROJECT")
    if env_proj:
        check("BRETHOF_MIND_PROJECT", valid_project(env_proj),
              env_proj if valid_project(env_proj)
              else f"'{env_proj}' invalid (must match [a-z][a-z0-9_]{{0,15}}) - IGNORED")
    if not valid_project(cfg.default_project):
        check("default_project", False,
              f"'{cfg.default_project}' invalid - falling back to 'global'")
    bad_keys = [p.get("key") for p in cfg.projects if isinstance(p, dict)
                and p.get("key") and not valid_project(p.get("key"))]
    if bad_keys:
        check("projects[].key", False, f"invalid keys ignored: {', '.join(bad_keys)}")

    if cfg.configured():
        try:
            snap = Client(cfg, timeout=8.0).get("/v1/usage")
            check("service reachable + key valid", True, f"plan {snap.get('plan','?')}")
        except ClientError as e:
            detail = str(e)
            if "1010" in detail or "Cloudflare" in detail:
                detail += "  <- looks like an edge/WAF block, NOT a bad key"
            check("service reachable + key valid", False, detail)

    # hooks wired? (and does each baked interpreter still exist?)
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
            check(f"hook {event_name}", False, "run: brethof-mind install-hooks")
        elif not all(os.path.exists(p) for p in pys):
            dead = next(p for p in pys if not os.path.exists(p))
            check(f"hook {event_name}", False,
                  f"interpreter missing: {dead} - rerun: brethof-mind install-hooks")
        else:
            check(f"hook {event_name}", True)

    print("\n" + ("all good" if ok else "issues found - see [XX] above"))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="brethof-mind",
                                description="brethof-mind cloud client")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="save credentials and verify connectivity")
    s.add_argument("--api-key", help="your brethof-mind API key")
    s.add_argument("--endpoint", help=f"data-plane URL (default {DEFAULT_ENDPOINT})")
    s.add_argument("--project", help="default project key for this account")
    s.set_defaults(func=cmd_setup)

    sub.add_parser("install-hooks", help="wire the hooks into Claude Code"
                   ).set_defaults(func=cmd_install_hooks)
    sub.add_parser("uninstall-hooks", help="remove the hooks from Claude Code"
                   ).set_defaults(func=cmd_uninstall_hooks)
    sub.add_parser("mcp-command", help="print the `claude mcp add` line"
                   ).set_defaults(func=cmd_mcp_command)
    sub.add_parser("status", help="show plan + usage").set_defaults(func=cmd_status)
    sub.add_parser("doctor", help="diagnose setup").set_defaults(func=cmd_doctor)
    return p


def main(argv=None) -> int:
    # Windows consoles default to cp1252; make our output crash-proof.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
