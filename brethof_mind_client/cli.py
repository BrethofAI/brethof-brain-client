"""``brethof-mind`` command-line tool: set up the client, wire Claude Code, and
check status. Stdlib only.

    brethof-mind setup --api-key bm_live_xxx [--endpoint URL] [--project KEY]
    brethof-mind install-hooks     # add the 5 hooks to ~/.claude/settings.json
    brethof-mind mcp-command       # print the `claude mcp add` line to run
    brethof-mind status            # show plan + usage
    brethof-mind doctor            # diagnose config / connectivity / wiring
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import DEFAULT_ENDPOINT, __version__
from .client import Client, ClientError
from .config import (CONFIG_PATH, Config, ensure_dirs, save_file, valid_project)

HOOK_EVENTS = [
    ("SessionStart", "session-start"),
    ("UserPromptSubmit", "prompt-submit"),
    ("Stop", "stop"),
    ("PreCompact", "pre-compact"),
]
CLAUDE_SETTINGS = os.path.expanduser("~/.claude/settings.json")
MCP_PATH = "/v1/mcp"


def _hook_command(event_arg: str) -> str:
    """The command Claude Code runs for a hook. Bakes in THIS interpreter so the
    right Python (the one this package is installed into) is always used."""
    py = sys.executable.replace("\\", "/")
    return f'"{py}" -m brethof_mind_client.hook {event_arg}'


# ── commands ────────────────────────────────────────────────────────────────

def cmd_setup(args) -> int:
    api_key = args.api_key
    if not api_key:
        if sys.stdin.isatty():
            api_key = input("brethof-mind API key (bm_live_... or bm_test_...): ").strip()
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
    data["api_key"] = api_key
    data["endpoint"] = (args.endpoint or data.get("endpoint") or DEFAULT_ENDPOINT).rstrip("/")
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
    print("  brethof-mind mcp-command     # wire the 15 memory tools (remote MCP)")
    return 0


def _load_settings() -> dict:
    if os.path.exists(CLAUDE_SETTINGS):
        try:
            with open(CLAUDE_SETTINGS, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            print(f"error: {CLAUDE_SETTINGS} is not valid JSON - fix it first",
                  file=sys.stderr)
            raise SystemExit(2)
    return {}


def cmd_install_hooks(args) -> int:
    settings = _load_settings()
    hooks = settings.setdefault("hooks", {})
    added = 0
    for event_name, event_arg in HOOK_EVENTS:
        command = _hook_command(event_arg)
        groups = hooks.setdefault(event_name, [])
        # already wired? (idempotent)
        exists = any(
            h.get("command", "").endswith(f"brethof_mind_client.hook {event_arg}")
            for g in groups if isinstance(g, dict)
            for h in g.get("hooks", []) if isinstance(h, dict))
        if exists:
            continue
        groups.append({"matcher": "", "hooks": [{"type": "command", "command": command}]})
        added += 1

    if added and os.path.exists(CLAUDE_SETTINGS):
        bak = CLAUDE_SETTINGS + ".bak"
        try:
            with open(CLAUDE_SETTINGS, encoding="utf-8") as f:
                old = f.read()
            with open(bak, "w", encoding="utf-8") as f:
                f.write(old)
            print(f"OK: backed up existing settings -> {bak}")
        except Exception:
            pass

    os.makedirs(os.path.dirname(CLAUDE_SETTINGS), exist_ok=True)
    with open(CLAUDE_SETTINGS, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    if added:
        print(f"OK: wired {added} hook(s) into {CLAUDE_SETTINGS}")
        print("  Restart Claude Code (or start a new session) to activate.")
    else:
        print("OK: hooks already installed - nothing to do")
    return 0


def cmd_uninstall_hooks(args) -> int:
    settings = _load_settings()
    hooks = settings.get("hooks", {})
    removed = 0
    for event_name, event_arg in HOOK_EVENTS:
        groups = hooks.get(event_name, [])
        kept = []
        for g in groups:
            inner = [h for h in g.get("hooks", [])
                     if not h.get("command", "").endswith(
                         f"brethof_mind_client.hook {event_arg}")]
            removed += len(g.get("hooks", [])) - len(inner)
            if inner:
                g["hooks"] = inner
                kept.append(g)
        if kept:
            hooks[event_name] = kept
        elif event_name in hooks:
            del hooks[event_name]
    with open(CLAUDE_SETTINGS, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    print(f"OK: removed {removed} brethof-mind hook(s) from {CLAUDE_SETTINGS}")
    return 0


def cmd_mcp_command(args) -> int:
    cfg = Config.load()
    key = cfg.api_key or "bm_live_YOUR_KEY"
    url = cfg.endpoint + MCP_PATH
    print("Run this once to add the 15 memory tools to Claude Code:\n")
    print(f'  claude mcp add --transport http brethof-mind {url} \\')
    print(f'    --header "Authorization: Bearer {key}"')
    print("\n(That stores the server in Claude Code's MCP config; the tools then "
          "appear as recall, save_memory, get_memory, ...)")
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
    check("endpoint", bool(cfg.endpoint), cfg.endpoint)

    if cfg.configured():
        try:
            snap = Client(cfg, timeout=8.0).get("/v1/usage")
            check("service reachable + key valid", True, f"plan {snap.get('plan','?')}")
        except ClientError as e:
            check("service reachable + key valid", False, str(e))

    # hooks wired?
    try:
        settings = _load_settings()
    except SystemExit:
        settings = {}
    hooks = settings.get("hooks", {})
    for event_name, event_arg in HOOK_EVENTS:
        wired = any(
            h.get("command", "").endswith(f"brethof_mind_client.hook {event_arg}")
            for g in hooks.get(event_name, []) if isinstance(g, dict)
            for h in g.get("hooks", []) if isinstance(h, dict))
        check(f"hook {event_name}", wired,
              "" if wired else "run: brethof-mind install-hooks")

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
