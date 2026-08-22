#!/usr/bin/env python3
"""Grok Build hook adapter — archive Grok sessions into brethof-brain cloud.

Grok Build has a full hooks system (SessionStart / UserPromptSubmit / Stop …)
and even auto-loads Claude Code's ~/.claude/settings.json hooks — but three
compat gaps mean the Claude hook entry cannot work there (verified empirically
on grok 0.2.106, 2026-07-24):

  1. Payloads are camelCase (``sessionId``, ``transcriptPath``) and the prompt
     arrives wrapped in ``<user_query>`` tags — the Claude client parses
     snake_case and misses every field.
  2. Passive-hook stdout is IGNORED (docs + injection probe): there is NO
     additionalContext channel, so session-brain / ambient-recall injection is
     impossible via hooks. Injection is replaced by the PULL model: a global
     rule in ~/.grok/rules/ tells Grok to call the brethof-brain MCP tools.
  3. On Windows, Grok's spawner mangles the ``"exe" "script" arg`` quoted
     command form (exit 1 before Python starts) — hooks must be wired through
     a .cmd wrapper (setup.py generates it).

What CAN work — and what this adapter does — is the STOP hook: Grok hands us
``transcriptPath`` (the session's updates.jsonl), which this script tails
incrementally and ships to POST /v1/hooks/stop, exactly like the Claude client
does for Claude transcripts. Full conversation archiving, same cloud brain.

Transcript format (grok updates.jsonl): one JSON per line;
``params.update.sessionUpdate`` ∈ {user_message_chunk, agent_message_chunk,
hook_execution, turn_completed, …}; text at ``params.update.content.text``.
Streaming may split one message across MANY chunk lines — consecutive
same-role chunks are coalesced into one turn.

Reuses brethof_brain_client (Config / Client / per-session offset state), so
install the client package first (``pip install git+https://github.com/BrethofAI/brethof-brain-client.git`` or run
from a checkout — sys.path bootstrap below handles the checkout case).

FAIL-OPEN: like every brethof-brain hook, any error exits 0 and never breaks
the session.
"""
from __future__ import annotations

import json
import os
import sys

# Checkout bootstrap: allow running straight from the repo (adapters/grok-build/
# is two levels below the repo root where brethof_brain_client lives).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from brethof_brain_client.client import Client, ClientError
    from brethof_brain_client.config import Config
    from brethof_brain_client import transcript as tstate   # state helpers only
except Exception:                                          # noqa: BLE001
    sys.exit(0)   # client not installed — memory off, never break the session

MAX_TURNS_PER_FLUSH = 40
MAX_BYTES_PER_FLUSH = 800_000
TEXT_CAP = 50_000


def _grok_own_key() -> str:
    """Key from grok's own MCP server entry in ~/.grok/config.toml.

    The archiver must ship transcripts to the SAME tenant grok's MCP tools
    write to. The shared Config fallback (~/.brethof-brain/config.json) can
    belong to a DIFFERENT agent on the same machine (e.g. Claude Code's owner
    key) — using it split-brains the memory: tools on one tenant, transcripts
    on another (observed 2026-08-11). So grok's config.toml wins; env var and
    config.json remain fallbacks for grok-only installs that never ran
    `grok mcp add`."""
    path = os.path.expanduser("~/.grok/config.toml")
    try:
        with open(path, "rb") as f:
            try:
                import tomllib
                data = tomllib.load(f)
                servers = data.get("mcp_servers", {})
                for name, entry in servers.items():
                    if "brethof" in name and isinstance(entry, dict):
                        auth = (entry.get("headers") or {}).get("Authorization", "")
                        if auth.startswith("Bearer "):
                            return auth[7:].strip()
            except ModuleNotFoundError:
                f.seek(0)
                import re
                text = f.read().decode("utf-8", "replace")
                m = re.search(
                    r"\[mcp_servers\.[^\]]*brethof[^\]]*\.headers\][^\[]*?"
                    r"Authorization\s*=\s*\"Bearer ([^\"]+)\"", text)
                if m:
                    return m.group(1).strip()
    except OSError:
        pass
    return ""


def _read_stdin() -> dict:
    try:
        d = json.load(sys.stdin)
        return d if isinstance(d, dict) else {}
    except Exception:                                       # noqa: BLE001
        return {}


def read_new_grok_turns(path: str, session_id: str):
    """Incremental read of a grok updates.jsonl → (turns, tail_offset, next_index).

    Same contract as brethof_brain_client.transcript.read_new_turns: byte-offset
    state per session, only newline-terminated lines consumed, each turn carries
    ``_offset`` (just past its LAST consumed line) so flushes can commit state
    per confirmed chunk. Consecutive same-role chunks coalesce into one turn; a
    turn closes on role switch or EOF (Stop fires after the turn completed, so
    EOF-close is safe; resends are idempotent server-side anyway)."""
    state = tstate.load_state(session_id)
    offset, idx = state["offset"], state["next_index"]
    turns: list[dict] = []
    if not path or not os.path.exists(path):
        return turns, offset, idx
    cur_role, cur_text, cur_ts = None, [], None

    def close(pos):
        nonlocal cur_role, cur_text, cur_ts, idx
        text = "".join(cur_text).strip()
        if cur_role and text:
            turns.append({"index": idx, "line_type": cur_role,
                          "text": text[:TEXT_CAP], "timestamp": cur_ts,
                          "embed": True, "_offset": pos})
            idx += 1
        cur_role, cur_text, cur_ts = None, [], None

    try:
        if offset > os.path.getsize(path):
            offset, idx = 0, 0
        pos = offset
        with open(path, "rb") as f:
            f.seek(offset)
            while True:
                raw = f.readline()
                if not raw or not raw.endswith(b"\n"):
                    break
                prev = pos
                pos += len(raw)
                try:
                    d = json.loads(raw.decode("utf-8", "replace"))
                except Exception:                            # noqa: BLE001
                    continue
                upd = (d.get("params") or {}).get("update") or {}
                kind = upd.get("sessionUpdate", "")
                role = {"user_message_chunk": "user",
                        "agent_message_chunk": "assistant"}.get(kind)
                if role is None:
                    # non-conversation line (hook_execution, turn_completed, plan
                    # updates …) closes any open turn at the PREVIOUS boundary.
                    close(prev)
                    continue
                if cur_role is not None and role != cur_role:
                    close(prev)
                cur_role = role
                content = upd.get("content") or {}
                if isinstance(content, dict) and content.get("type") == "text":
                    cur_text.append(content.get("text", ""))
                if cur_ts is None and d.get("timestamp"):
                    try:
                        import datetime
                        cur_ts = datetime.datetime.fromtimestamp(
                            int(d["timestamp"]),
                            datetime.timezone.utc).isoformat()
                    except Exception:                        # noqa: BLE001
                        cur_ts = None
        close(pos)   # EOF closes the trailing turn (Stop == turn complete)
    except Exception:                                        # noqa: BLE001
        return [], state["offset"], state["next_index"]
    return turns, pos, idx


def _stop(cfg: Config, inp: dict) -> None:
    """Archive new grok turns in bounded, per-confirmed-chunk committed flushes."""
    session_id = inp.get("sessionId") or ""
    path = inp.get("transcriptPath") or ""
    if not session_id or not path:
        return
    project = cfg.project_for(inp.get("cwd", ""))
    turns, tail_offset, next_index = read_new_grok_turns(path, session_id)
    if not turns:
        st = tstate.load_state(session_id)
        if (tail_offset, next_index) != (st["offset"], st["next_index"]):
            tstate.save_state(session_id, tail_offset, next_index)
        return
    client = Client(cfg, timeout=20.0)
    i = 0
    while i < len(turns):
        chunk, size = [], 0
        while (i < len(turns) and len(chunk) < MAX_TURNS_PER_FLUSH
               and size < MAX_BYTES_PER_FLUSH):
            chunk.append(turns[i])
            size += len(turns[i]["text"])
            i += 1
        payload = [{k: v for k, v in t.items() if k != "_offset"} for t in chunk]
        env = client.post("/v1/hooks/stop", {"project": project,
                                             "session_id": session_id,
                                             "turns": payload})
        if env.get("status", "ok") != "ok":
            sys.stderr.write("brethof-brain(grok): archive deferred "
                             f"({env.get('notice') or env.get('status')})\n")
            return
        last = chunk[-1]
        tstate.save_state(session_id, last["_offset"], last["index"] + 1)
    tstate.save_state(session_id, tail_offset, next_index)


_HANDLERS = {"stop": _stop}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    handler = _HANDLERS.get(argv[0] if argv else "")
    if handler is None:
        return 0
    try:
        cfg = Config.load()
        own = _grok_own_key()
        if own:
            cfg.api_key = own
        if not cfg.configured():
            return 0
        handler(cfg, _read_stdin())
    except ClientError as e:
        if e.status_code in (401, 403):
            sys.stderr.write("brethof-brain(grok): API key rejected — archiving "
                             "off; run `brethof-brain doctor`\n")
    except Exception:                                        # noqa: BLE001
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
