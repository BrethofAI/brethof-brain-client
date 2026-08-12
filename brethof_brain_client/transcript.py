"""Read NEW turns from a Claude Code transcript, incrementally.

Claude Code appends JSONL to a per-session transcript. The Stop hook fires
every assistant turn; we keep a per-session byte offset (plus a monotonic turn
index) so each line is shipped exactly once and retries converge — the data
plane hashes (session_id, turn_index, text) into the row id, so re-sending the
same line is an idempotent UPSERT, never a duplicate.

Offset + index advance ONLY after the server confirms the write (see hook.stop),
so a failed flush is simply retried next turn from the same point. The file is
read in BINARY mode and offsets are plain byte counts, so they can be validated
against the file size and a stored offset can never land mid-character.

Safety properties:
- Only NEWLINE-TERMINATED lines are consumed. A half-written final line (the
  writer mid-flush) is left for the next pass instead of being skipped forever.
- If the transcript was replaced or truncated (stored offset > file size),
  state resets to (0, 0) and the file is re-read from the start — identical
  (session_id, index, text) triples upsert to the same server rows, so the
  resend cannot duplicate.
- Every turn carries ``_offset`` (the byte offset just past its line) so the
  caller can flush in bounded chunks and commit state per confirmed chunk.

Turn shape emitted (matches mindcore/archive.archive_turns), minus the
client-internal ``_offset``:
    {"index": int, "line_type": "user"|"assistant", "text": str,
     "timestamp": iso-or-None, "embed": bool}
Only real conversation lines are emitted. Tool RESULTS are dropped entirely —
they carry the contents of the user's files and command output, which the
README promises never leave the machine. Assistant tool CALLS ship as one-line
markers ("[tool_use: Bash]").
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
            # List-form user content mixes genuine typed text blocks with
            # tool_result blocks. Keep the dialogue; DROP tool results — they
            # carry file contents and command output that must not leave the
            # machine (the README's "What leaves your machine" contract).
            out = [b.get("text", "") for b in c
                   if isinstance(b, dict) and b.get("type") == "text"]
            text = "\n".join(s for s in out if s)
            return text, bool(text)
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
    """Return ``(turns, tail_offset, next_index)`` for COMPLETE lines added
    since the last committed offset.

    ``tail_offset`` is the byte offset just past the last newline-terminated
    line scanned (conversation or not); each turn's ``_offset`` is the offset
    just past its own line. Does not persist anything — the caller commits
    state only after the server confirms a flush."""
    state = load_state(session_id)
    offset, idx = state["offset"], state["next_index"]
    turns = []
    if not transcript_path or not os.path.exists(transcript_path):
        return turns, offset, idx
    try:
        if offset > os.path.getsize(transcript_path):
            # Transcript replaced/rewritten shorter: reset and re-read from 0.
            # The server's idempotent row ids turn the resend into a no-op.
            offset, idx = 0, 0
        pos = offset
        with open(transcript_path, "rb") as f:
            f.seek(offset)
            while True:
                raw = f.readline()
                if not raw or not raw.endswith(b"\n"):
                    # EOF, or a half-written final line: leave it for the next
                    # pass rather than committing the offset past it.
                    break
                pos += len(raw)
                line = raw.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line.decode("utf-8", "replace"))
                except Exception:
                    continue
                if not isinstance(d, dict):
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
                    "_offset": pos,
                })
                idx += 1
    except Exception:
        return [], state["offset"], state["next_index"]
    return turns, pos, idx
