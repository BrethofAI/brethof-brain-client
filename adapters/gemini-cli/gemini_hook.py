#!/usr/bin/env python3
"""Gemini CLI hook adapter — session brief, ambient recall, full archive.

Gemini CLI shipped Claude-Code-grade hooks (docs/hooks in the repo, Dec
2025) and the output schema is LITERALLY Claude Code's —
``hookSpecificOutput.additionalContext`` — with consumption verified in
source (packages/core/src/core/client.ts). This adapter is the same shim
family as the Cursor one: one script for every event, dispatched on the
payload's ``hook_event_name``.

  SessionStart -> POST /v1/hooks/session-start -> additionalContext
                  ("injected as the first turn in history")
  BeforeAgent  -> POST /v1/hooks/prompt-submit  -> additionalContext
                  (fires per user prompt; payload hands the RAW prompt —
                  no unwrapping needed on this platform)
  AfterAgent   -> archive new turns from transcript_path
  SessionEnd   -> final archive flush

Transcript format (source: services/chatRecordingTypes.ts): JSONL of
MessageRecords ``{id, timestamp, content, type: user|gemini|info|...}``.
CAREFUL: the recording service UPDATES records by id — a later line with
the same id supersedes the earlier one — so this parser is id-aware
(last record per id wins, insertion order kept) and the archive ships by
turn INDEX, never by byte offset.

FAIL-OPEN: like every brethof-brain hook, any error exits 0 and never
breaks the session.
"""
from __future__ import annotations

import json
import os
import sys

# Checkout bootstrap: allow running straight from the repo.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from brethof_brain_client.client import Client, ClientError
    from brethof_brain_client.config import Config
    from brethof_brain_client import hook as cc_hook
    from brethof_brain_client import transcript as tstate   # state helpers only
except Exception:                                          # noqa: BLE001
    sys.exit(0)   # client not installed — memory off, never break the session

MAX_TURNS_PER_FLUSH = 40
MAX_BYTES_PER_FLUSH = 800_000
TEXT_CAP = 50_000


def _text_of(content) -> str:
    """genai PartListUnion -> plain text (string | Part | list of either)."""
    if isinstance(content, str):
        return content
    if isinstance(content, dict):
        return str(content.get("text") or "")
    if isinstance(content, list):
        return "\n".join(t for t in (_text_of(c) for c in content) if t)
    return ""


def parse_gemini_transcript(path: str) -> list[dict]:
    """Whole transcript -> ordered conversation turns, id-aware."""
    records: dict[str, dict] = {}
    with open(path, "rb") as f:
        for raw in f:
            try:
                d = json.loads(raw.decode("utf-8", "replace"))
            except Exception:                                # noqa: BLE001
                continue
            if not isinstance(d, dict) or "id" not in d or "type" not in d:
                continue
            # Later lines supersede earlier ones with the same id; a dict
            # keyed by id keeps insertion order in Python.
            records[d["id"]] = d
    turns: list[dict] = []
    for d in records.values():
        role = {"user": "user", "gemini": "assistant"}.get(d.get("type"))
        if role is None:
            continue        # info / error / warning — not conversation
        text = _text_of(d.get("content")).strip()
        if not text:
            continue
        turns.append({"index": len(turns), "line_type": role,
                      "text": text[:TEXT_CAP], "embed": True,
                      "timestamp": d.get("timestamp")})
    return turns


def _emit(event: str, text: str) -> None:
    if not text:
        return
    json.dump({"hookSpecificOutput": {"hookEventName": event,
                                      "additionalContext": text}}, sys.stdout)


def _session_start(cfg: Config, inp: dict) -> None:
    project = cc_hook._project(cfg, inp)
    env = Client(cfg).post("/v1/hooks/session-start", {"project": project})
    _emit("SessionStart", cc_hook._injection_from_envelope(env))


def _before_agent(cfg: Config, inp: dict, prompt: str) -> None:
    session_id = inp.get("session_id") or ""
    prompt = (prompt or "").strip()
    if not prompt or not session_id:
        return
    project = cc_hook._project(cfg, inp)
    env = Client(cfg).post("/v1/hooks/prompt-submit",
                           {"project": project, "prompt": prompt,
                            "session_id": session_id})
    _emit("BeforeAgent", cc_hook._injection_from_envelope(env))


def _archive(cfg: Config, inp: dict) -> None:
    session_id = inp.get("session_id") or ""
    path = inp.get("transcript_path") or ""
    if not session_id or not path or not os.path.exists(path):
        return
    project = cc_hook._project(cfg, inp)
    all_turns = parse_gemini_transcript(path)
    st = tstate.load_state(session_id)
    turns = [t for t in all_turns if t["index"] >= st["next_index"]]
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
            sys.stderr.write("brethof-brain: archive deferred "
                             f"({env.get('notice') or env.get('status')})\n")
            return
        tstate.save_state(session_id, 0, chunk[-1]["index"] + 1)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            return 0
        cfg = Config.load()
        if not cfg.configured():
            return 0
        event = payload.get("hook_event_name") or ""
        if event == "SessionStart":
            _session_start(cfg, payload)
        elif event == "BeforeAgent":
            _before_agent(cfg, payload, payload.get("prompt") or "")
        elif event in ("AfterAgent", "SessionEnd", "Stop"):
            _archive(cfg, payload)
    except ClientError as e:
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
