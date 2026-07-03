"""Read NEW turns from a Claude Code transcript, incrementally.

Claude Code appends JSONL to a per-session transcript. The Stop hook fires
every assistant turn; we keep a per-session byte offset (plus a monotonic turn
index) so each line is shipped exactly once and retries converge — the data
plane hashes (session_id, turn_index, text) into the row id, so re-sending the
same line is an idempotent UPSERT, never a duplicate.

Offset + index advance ONLY after the server confirms the write (see hook.stop),
so a failed flush is simply retried next turn from the same point.

Turn shape emitted (matches mindcore/archive.archive_turns):
    {"index": int, "line_type": "user"|"assistant", "text": str,
     "timestamp": iso-or-None, "embed": bool}
Only real conversation lines are emitted; tool-result noise and empty lines are
dropped so we neither store nor bill for them.
"""
from __future__ import annotations

import json
import os

from .config import STATE_DIR

TEXT_CAP = 50_000  # trim pathologically long single lines before shipping


def _state_path(session_id: str) -> str:
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return os.path.join(STATE_DIR, f"{safe}.json")


def load_state(session_id: str) -> dict:
    try:
        with open(_state_path(session_id), encoding="utf-8") as f:
            s = json.load(f)
        return {"offset": int(s.get("offset", 0)), "next_index": int(s.get("next_index", 0))}
    except Exception:
        return {"offset": 0, "next_index": 0}


def save_state(session_id: str, offset: int, next_index: int) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = _state_path(session_id) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"offset": offset, "next_index": next_index}, f)
    os.replace(tmp, _state_path(session_id))


def _extract_text(d: dict):
    """Return (text, embed_flag). embed_flag True only for genuine dialogue."""
    t = d.get("type")
    msg = d.get("message") if isinstance(d.get("message"), dict) else None
    if t == "user" and msg:
        c = msg.get("content")
        if isinstance(c, str):
            return c, True
        if isinstance(c, list):
            out = []
            for b in c:
                if not isinstance(b, dict):
                    continue
                bc = b.get("content")
                if isinstance(bc, str):
                    out.append(bc)
                elif isinstance(bc, list):
                    for x in bc:
                        if isinstance(x, dict) and x.get("type") == "text":
                            out.append(x.get("text", ""))
            # list-form user content is almost always a tool_result → don't embed
            return "\n".join(out), False
    if t == "assistant" and msg:
        c = msg.get("content")
        if isinstance(c, list):
            out = []
            for b in c:
                if not isinstance(b, dict):
                    continue
                bt = b.get("type")
                if bt == "text":
                    out.append(b.get("text", ""))
                elif bt == "thinking":
                    out.append(b.get("thinking", ""))
                elif bt == "tool_use":
                    out.append(f"[tool_use: {b.get('name', '?')}]")
            return "\n".join(s for s in out if s), True
    return "", False


def read_new_turns(transcript_path: str, session_id: str):
    """Return ``(turns, new_offset, next_index)`` for lines added since the last
    committed offset. Does not persist anything — the caller commits after a
    successful flush."""
    state = load_state(session_id)
    offset, idx = state["offset"], state["next_index"]
    turns = []
    if not transcript_path or not os.path.exists(transcript_path):
        return turns, offset, idx
    try:
        with open(transcript_path, encoding="utf-8") as f:
            f.seek(offset)
            while True:
                raw = f.readline()
                if not raw:
                    break
                line = raw.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                t = d.get("type")
                if t not in ("user", "assistant"):
                    continue
                text, embed = _extract_text(d)
                if not text.strip():
                    continue
                turns.append({
                    "index": idx,
                    "line_type": t,
                    "text": text[:TEXT_CAP],
                    "timestamp": d.get("timestamp"),
                    "embed": embed,
                })
                idx += 1
            new_offset = f.tell()
    except Exception:
        return [], offset, state["next_index"]
    return turns, new_offset, idx
