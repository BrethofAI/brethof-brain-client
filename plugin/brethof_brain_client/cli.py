"""``brethof-brain`` command-line tool: set up the client, wire Claude Code, and
check status. Stdlib only.

    brethof-brain setup --api-key bmv2_xxx [--endpoint URL] [--project KEY]
    brethof-brain install-hooks     # wire the hooks into Claude Code (pip install only)
    brethof-brain mcp-command       # print the `claude mcp add` line to run
    brethof-brain status            # show plan + usage
    brethof-brain doctor            # diagnose config / connectivity / wiring

(The hook dispatcher also understands a 5th event, ``commit``, for programmatic
wiring — e.g. a git post-commit hook; the installer wires the 4 session events.)
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
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
MCP_PATH = "/v1/mcp"

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


# ── commands ────────────────────────────────────────────────────────────────

def cmd_setup(args) -> int:
    api_key = args.api_key
    if not api_key:
        if sys.stdin.isatty():
            # getpass: the key must not echo to the terminal or scrollback.
            api_key = getpass.getpass(
                "brethof-brain API key (bmv2_... or bm_test_..., hidden): ").strip()
        else:
            print("error: --api-key required (or run in an interactive terminal)",
                  file=sys.stderr)
            return 2
    if not api_key.startswith(("bmv2_", "bm_test_")):
        print("warning: key doesn't look like a brethof-brain key (bmv2_/bm_test_)",
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
    print("  brethof-brain install-hooks   # auto-load & archive memory in Claude Code")
    print("  brethof-brain mcp-command     # wire the memory tools (remote MCP)")
    return 0


CONTROL_URL = os.environ.get("BRETHOF_BRAIN_CONTROL_URL", "https://api.brethof.ai").rstrip("/")


def _post_json(url: str, body: dict, timeout: float = 30.0) -> tuple[int, dict]:
    import urllib.error
    import urllib.request
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          "User-Agent": f"brethof-brain-client/{__version__}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            # not the service speaking: Cloudflare's edge answers its own
            # pages (403 "error code: 1010" to a bare urllib, 2026-10-04)
            return e.code, {"error": "blocked",
                            "error_description": f"HTTP {e.code} from the network edge, not the service"}
    except (urllib.error.URLError, OSError) as e:
        return 0, {"error": "unreachable", "error_description": f"{type(e).__name__}: {e}"}


def _can_open_browser() -> bool:
    """A browser this process can show: a desktop session (Linux needs a
    display), macOS and Windows always; never over plain SSH."""
    if sys.platform in ("darwin", "win32"):
        return True
    if os.environ.get("SSH_CONNECTION") and not os.environ.get("DISPLAY"):
        return False
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _open_browser(url: str) -> bool:
    if not url or not _can_open_browser():
        return False
    try:
        import webbrowser
        return bool(webbrowser.open(url, new=2))
    except Exception:  # noqa: BLE001 — the printed link is the fallback
        return False


def cmd_login(args, sleep=None) -> int:
    """DEVICE LOGIN (2026-10-04): this machine asks the control plane for a
    code, the human approves it on brethof.ai/account/device while signed in
    (2FA), and the key comes back to this process — written to the config
    file and never printed, so an agent running the install never sees it.
    Hosted memories only: a local memory mints its own key on its machine."""
    import socket
    import time as _time
    sleep = sleep or _time.sleep
    control = (args.control or CONTROL_URL).rstrip("/")
    st, code = _post_json(f"{control}/v1/device/code",
                          {"client_name": f"brethof-brain on {socket.gethostname()}"[:80]})
    if st != 200 or not code.get("device_code"):
        print(f"error: could not start the sign-in ({st}: "
              f"{code.get('error_description') or code.get('error') or 'no answer'})", file=sys.stderr)
        return 1
    link = code.get("verification_uri_complete") or code.get("verification_uri") or ""
    opened = (not getattr(args, "no_browser", False)) and _open_browser(link)
    print("Opening your browser to confirm this machine…" if opened else
          "To connect this machine to your memory, open this page while signed in:")
    print(f"  {link}")
    print(f"and confirm the code  {code.get('user_code', '')}", flush=True)
    interval = max(1, int(code.get("interval") or 5))
    deadline = _time.time() + int(code.get("expires_in") or 600)
    while _time.time() < deadline:
        sleep(interval)
        st, tok = _post_json(f"{control}/v1/device/token", {"device_code": code["device_code"]})
        if st == 200 and tok.get("api_key"):
            break
        err = tok.get("error", "")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        print(f"error: {tok.get('error_description') or err or f'HTTP {st}'}", file=sys.stderr)
        return 1
    else:
        print("error: the code expired before it was approved — run login again", file=sys.stderr)
        return 1
    try:
        endpoint = _valid_endpoint(tok.get("endpoint") or "")
    except ValueError as e:
        print(f"error: the service answered an unusable endpoint: {e}", file=sys.stderr)
        return 1
    ensure_dirs()
    data = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    data["api_key"], data["endpoint"] = tok["api_key"], endpoint
    data.setdefault("default_project", "global")
    save_file(data)                     # the key first: it is good on its own
    if tok.get("needs_passphrase") and not data.get("unlock_passphrase"):
        # THE HUMAN'S OWN SECRET, never through the agent: a one-shot page in
        # their browser when one can open; a hidden prompt only on a real
        # terminal; never a prompt that waits on nobody (no tty under an agent)
        pp = ""
        if not getattr(args, "no_browser", False) and _can_open_browser():
            from . import connectpage
            pp = connectpage.serve({"passphrase": ""}, f"brethof-brain-client/{__version__}",
                                   _open_browser, endpoint=endpoint).get("passphrase", "")
        elif sys.stdin.isatty():
            print("WARNING: if you forget your passphrase, your memory can never be opened again — "
                  "by you or by us. There is no way to recover it.", file=sys.stderr)
            pp = getpass.getpass("Your memory's passphrase (hidden; it unlocks your hosted memory): ").strip()
            if pp and getpass.getpass("Passphrase again: ").strip() != pp:
                print("error: the two passphrases are not the same — not saved", file=sys.stderr)
                pp = ""
        if pp:
            data["unlock_passphrase"] = pp
            save_file(data)
        else:
            print("note: your hosted memory locks when idle and needs its passphrase — run "
                  "`brethof-brain login` again on a machine with a browser or a terminal, or set "
                  f"unlock_passphrase in {CONFIG_PATH}", file=sys.stderr)
    print(f"OK: connected — key and endpoint saved to {CONFIG_PATH} (readable by you only)")
    return 0


LOCAL_ENDPOINT = "http://127.0.0.1:8610"


def _local_memory_here() -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(LOCAL_ENDPOINT + "/v1/health", timeout=3) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001
        return False


def cmd_connect(args) -> int:
    """THE INSTALL'S ONE STEP FOR THE HUMAN (founder 2026-10-04): the client
    needs the API key and, for a hosted memory, the passphrase — and the agent
    running the install must see neither. A window opens on the person's own
    screen, takes them, checks them with the memory and saves them; the agent
    only learns that it is connected. No screen: hidden prompts on a real
    terminal. Neither: say so — never wait on nobody."""
    from . import connectpage
    ua = f"brethof-brain-client/{__version__}"
    ensure_dirs()
    data = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
    endpoint = args.endpoint or data.get("endpoint") or ""
    if not endpoint and _local_memory_here():
        endpoint = LOCAL_ENDPOINT
    got: dict = {}
    if not args.no_browser and _can_open_browser():
        got = connectpage.serve({"endpoint": endpoint, "key": "", "passphrase": ""}, ua, _open_browser)
        if not got:
            print("error: the window was not filled in before it timed out — run connect again", file=sys.stderr)
            return 1
    elif sys.stdin.isatty():
        ep = input(f"Where your memory is [{endpoint or 'https://memory.brethof.cloud/t/<yours>'}]: ").strip() or endpoint
        key = getpass.getpass("API key (bmv2_…, hidden): ").strip()
        pp = ""
        if not connectpage._is_local(ep):
            print("WARNING: if you forget your passphrase, your memory can never be opened again — "
                  "by you or by us. There is no way to recover it.", file=sys.stderr)
            pp = getpass.getpass("Passphrase (hosted memory; hidden, empty if none): ").strip()
            if pp and getpass.getpass("Passphrase again: ").strip() != pp:
                print("error: the two passphrases are not the same", file=sys.stderr)
                return 1
        why = connectpage.check(ep, key, pp, ua)
        if why:
            print(f"error: {why}", file=sys.stderr)
            return 1
        got = {"endpoint": ep.rstrip("/"), "key": key, "passphrase": pp}
    else:
        print("error: there is no screen and no terminal here to ask the person — they run "
              "`brethof-brain connect` themselves on this computer", file=sys.stderr)
        return 2
    try:
        data["endpoint"] = _valid_endpoint(got["endpoint"])
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    data["api_key"] = got["key"]
    if got.get("passphrase"):
        data["unlock_passphrase"] = got["passphrase"]
    data.setdefault("default_project", "global")
    save_file(data)
    print(f"OK: connected to your memory — saved to {CONFIG_PATH} (readable by you only)")
    return 0


def _claude_files():
    """The module that edits Claude Code's own files — absent in the plugin
    build (scripts/sync_plugin.py leaves it out; claude_files.py says why)."""
    try:
        from . import claude_files
        return claude_files
    except ImportError:
        return None


def cmd_install_hooks(args) -> int:
    files = _claude_files()
    if files is None:
        print("install-hooks is part of the pip-installed client; the Claude Code plugin "
              "wires its own hooks.", file=sys.stderr)
        return 2
    return files.install_hooks(args)


def cmd_uninstall_hooks(args) -> int:
    files = _claude_files()
    if files is None:
        print("uninstall-hooks is part of the pip-installed client; remove the plugin with "
              "`claude plugin uninstall brethof-brain`.", file=sys.stderr)
        return 2
    return files.uninstall_hooks(args)


def cmd_mcp_command(args) -> int:
    cfg = Config.load()
    key = cfg.api_key or "bmv2_YOUR_KEY"
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
        print("not configured - run: brethof-brain setup --api-key ...", file=sys.stderr)
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

    print("brethof-brain client doctor")
    print(f"client version : {__version__}")
    check("config file", os.path.exists(CONFIG_PATH), CONFIG_PATH)
    check("api key set", bool(cfg.api_key),
          "run: brethof-brain setup" if not cfg.api_key else cfg.api_key[:12] + "...")
    try:
        _valid_endpoint(cfg.endpoint)
        check("endpoint", True, cfg.endpoint)
    except ValueError as e:
        check("endpoint", False, str(e))

    # project routing sanity
    env_proj = os.environ.get("BRETHOF_BRAIN_PROJECT")
    if env_proj:
        check("BRETHOF_BRAIN_PROJECT", valid_project(env_proj),
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

    # hooks wired? (the pip-installed client only — a plugin install's hooks
    # come from the plugin itself and it ships no settings code)
    files = _claude_files()
    if files is not None and not os.environ.get("CLAUDE_PLUGIN_ROOT"):
        files.wiring_report(check)

    print("\n" + ("all good" if ok else "issues found - see [XX] above"))
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="brethof-brain",
                                description="brethof-brain cloud client")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("setup", help="save credentials and verify connectivity")
    s.add_argument("--api-key", help="your brethof-brain API key")
    s.add_argument("--endpoint", help=f"data-plane URL (default {DEFAULT_ENDPOINT})")
    s.add_argument("--project", help="default project key for this account")
    s.set_defaults(func=cmd_setup)

    sub.add_parser("install-hooks", help="wire the hooks into Claude Code"
                   ).set_defaults(func=cmd_install_hooks)
    sub.add_parser("uninstall-hooks", help="remove the hooks from Claude Code"
                   ).set_defaults(func=cmd_uninstall_hooks)
    sub.add_parser("mcp-command", help="print the `claude mcp add` line"
                   ).set_defaults(func=cmd_mcp_command)
    cn = sub.add_parser("connect", help="connect this computer to your memory: a window takes the key "
                        "(and a hosted memory's passphrase) — the agent never sees them")
    cn.add_argument("--endpoint", default="", help="where the memory is (found by itself for this computer)")
    cn.add_argument("--no-browser", action="store_true", help="ask in the terminal instead of a window")
    cn.set_defaults(func=cmd_connect)
    lg = sub.add_parser("login", help="connect this machine to your hosted memory by approving a code on brethof.ai")
    lg.add_argument("--control", default="", help=argparse.SUPPRESS)
    lg.add_argument("--no-browser", action="store_true", help="print the links instead of opening a browser")
    lg.set_defaults(func=cmd_login)
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
