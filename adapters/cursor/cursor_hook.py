#!/usr/bin/env python3
"""Cursor hook adapter — session brief + full-session archive for Cursor.

Cursor's hooks contract (cursor.com/docs/agent/hooks, verified 2026-08-23) is
deliberately Claude-Code-shaped — it even exports CLAUDE_PROJECT_DIR as an
alias — so this adapter is a FIELD-NAME SHIM over the existing Python client,
not a reimplementation:

  sessionStart  ->  POST /v1/hooks/session-start  ->  {"additional_context"}
  stop          ->  hook.py's chunked archive flush (conversation_id maps to
  sessionEnd    ->  session_id, transcript_path rides through unchanged)

One script serves every event: Cursor sends ``hook_event_name`` in the stdin
payload, so hooks.json points each event at this same file.

What Cursor does NOT offer (docs, 2026-08-23): a per-prompt injection channel.
``beforeSubmitPrompt`` is gate-only (continue/block — its output cannot add
context), so there is no ambient per-prompt recall here. The session brief
covers session start; the MCP block (adapters/editors/README.md) provides the
explicit tool doors for pull-model recall.

TRANSCRIPT FORMAT: Cursor documents ``transcript_path`` on every payload but
not the file's format. This adapter feeds it to the client's Claude-Code JSONL
reader (the format Cursor's contract mirrors everywhere else). If a real
install shows a different shape, read_new_turns yields nothing, the session is
never broken (fail-open), and BRETHOF_BRAIN_HOOK_DEBUG=1 shows the truth —
extend brethof_brain_client/transcript.py then, against the real file.

FAIL-OPEN: like every brethof-brain hook, any error exits 0 and never breaks
the session.
"""
from __future__ import annotations

import json
import os
import sys

# Checkout bootstrap: allow running straight from the repo (adapters/cursor/
# is two levels below the repo root where brethof_brain_client lives).
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from brethof_brain_client import hook as cc_hook
    from brethof_brain_client.config import Config
except Exception:                                          # noqa: BLE001
    sys.exit(0)   # client not installed — memory off, never break the session


def _cc_shaped(payload: dict) -> dict:
    """Cursor payload -> the dict shape hook.py's handlers read."""
    roots = payload.get("workspace_roots") or []
    return {
        "session_id": payload.get("conversation_id") or "",
        "transcript_path": payload.get("transcript_path") or "",
        "cwd": roots[0] if roots else (os.environ.get("CURSOR_PROJECT_DIR")
                                       or os.getcwd()),
    }


def _session_start(cfg: Config, inp: dict) -> None:
    """The one Cursor event that can inject: reply {"additional_context"}."""
    project = cc_hook._project(cfg, inp)
    env = cc_hook.Client(cfg).post("/v1/hooks/session-start",
                                   {"project": project})
    text = cc_hook._injection_from_envelope(env)
    if text:
        json.dump({"additional_context": text}, sys.stdout)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            return 0
        cfg = Config.load()
        if not cfg.configured():
            return 0
        event = payload.get("hook_event_name") or ""
        inp = _cc_shaped(payload)
        if event == "sessionStart":
            _session_start(cfg, inp)
        elif event in ("stop", "sessionEnd"):
            # Both flush: stop fires per completed turn, sessionEnd is the
            # belt-and-braces final pass. hook.py's chunked state discipline
            # makes replays idempotent and outages deferrals, never losses.
            cc_hook._stop(cfg, inp)
    except cc_hook.ClientError as e:
        if getattr(e, "status_code", None) in (401, 403):
            sys.stderr.write("brethof-brain: API key rejected — memory and "
                             "archiving are OFF. Run `brethof-brain setup`.\n")
    except Exception:                                      # noqa: BLE001
        if os.environ.get("BRETHOF_BRAIN_HOOK_DEBUG"):
            import traceback
            traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
