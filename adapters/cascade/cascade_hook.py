#!/usr/bin/env python3
"""Cascade (Windsurf / Devin Desktop) hook adapter — full-session archive.

Cascade's hooks are CAPTURE-ONLY by design (docs.devin.ai/desktop/cascade/
hooks, verified 2026-08-23): no event can inject context, `pre_user_prompt`
can only block, and there is no session-start. What Cascade DOES hand over is
first-class: `post_cascade_response_with_transcript` fires after every agent
response with `tool_info.transcript_path` — the FULL conversation as JSONL.
So this adapter is the archive half of the contract; recall is pull-model via
the MCP tool doors (adapters/editors/README.md) plus a memory rule.

Transcript format (documented + this adapter's contract):
one JSON object per line; `type` discriminates —
  user_input        -> text at  user_input.user_response          (user turn)
  planner_response  -> text at  planner_response.response    (assistant turn)
other types (code_action, ...) are tool traffic, not conversation.

The file is REWRITTEN from the beginning on every firing, so byte-offset
tailing (the grok pattern) is wrong here: earlier lines may be rewritten in
place. Instead the WHOLE file is parsed every time and only turns at or past
the session's confirmed index are sent — the server upserts on
(session_id, index, text), so overlap is idempotent and a mid-flush failure
just retries next firing.

FAIL-OPEN: like every brethof-brain hook, any error exits 0 and never breaks
the session.
"""
from __future__ import annotations

import json
import os
import sys

# Checkout bootstrap: allow running straight from the repo (adapters/cascade/
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


def parse_cascade_transcript(path: str) -> list[dict]:
    """The whole transcript -> ordered conversation turns (index, role, text).

    Consecutive same-role lines coalesce into one turn (a user message split
    across inputs, an assistant response split across planner steps), closing
    on role switch or EOF."""
    turns: list[dict] = []
    cur_role, cur_text = None, []

    def close():
        nonlocal cur_role, cur_text
        text = "\n".join(t for t in cur_text if t).strip()
        if cur_role and text:
            turns.append({"index": len(turns), "line_type": cur_role,
                          "text": text[:TEXT_CAP], "embed": True})
        cur_role, cur_text = None, []

    with open(path, "rb") as f:
        for raw in f:
            try:
                d = json.loads(raw.decode("utf-8", "replace"))
            except Exception:                                # noqa: BLE001
                continue
            kind = d.get("type", "")
            if kind == "user_input":
                role = "user"
                text = (d.get("user_input") or {}).get("user_response", "")
            elif kind == "planner_response":
                role = "assistant"
                text = (d.get("planner_response") or {}).get("response", "")
            else:
                continue        # tool traffic — not conversation
            if cur_role is not None and role != cur_role:
                close()
            cur_role = role
            cur_text.append(text)
    close()
    return turns


def _archive(cfg: Config, session_id: str, path: str) -> None:
    if not session_id or not path or not os.path.exists(path):
        return
    project = cfg.project_for(os.getcwd())
    all_turns = parse_cascade_transcript(path)
    state = tstate.load_state(session_id)
    turns = [t for t in all_turns if t["index"] >= state["next_index"]]
    if not turns:
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
        env = client.post("/v1/hooks/stop",
                          {"project": project, "session_id": session_id,
                           "turns": chunk})
        if env.get("status", "ok") != "ok":
            # over_cap / read_only / server_error: keep what's confirmed,
            # retry the rest on the next firing.
            sys.stderr.write("brethof-brain: archive deferred "
                             f"({env.get('notice') or env.get('status')})\n")
            return
        tstate.save_state(session_id, 0, chunk[-1]["index"] + 1)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            return 0
        if payload.get("agent_action_name") != "post_cascade_response_with_transcript":
            return 0        # every other event is none of our business
        cfg = Config.load()
        if not cfg.configured():
            return 0
        _archive(cfg,
                 str(payload.get("trajectory_id") or ""),
                 str((payload.get("tool_info") or {}).get("transcript_path")
                     or ""))
    except ClientError as e:
        if getattr(e, "status_code", None) in (401, 403):
            sys.stderr.write("brethof-brain: API key rejected — archiving is "
                             "OFF. Run `brethof-brain setup`.\n")
    except Exception:                                      # noqa: BLE001
        if os.environ.get("BRETHOF_BRAIN_HOOK_DEBUG"):
            import traceback
            traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
