#!/usr/bin/env python3
"""Antigravity hook adapter — session brief, ambient recall, full archive.

Google Antigravity's hooks (antigravity.google/docs/hooks/) are their own
five-event schema — NOT a Claude Code clone and NOT Cascade's: camelCase
payloads (``conversationId``, ``transcriptPath``, ``workspacePaths``),
config in ``.agents/hooks.json`` (workspace) or ``~/.gemini/config/hooks.json``
(user), and ONE injection channel: PreInvocation/PostInvocation may return
``{"injectSteps": [{"ephemeralMessage": "..."}]}`` — a transient message the
model sees on that invocation without entering stored history (the Cline-
overlay property: injections can never leak into the archive).

Antigravity sends no hook_event_name field, so the event arrives as ARGV:
hooks.json commands are "python3 .../antigravity_hook.py pre-invocation" /
"stop".

  pre-invocation -> brief once per conversation + recall when the latest
                    user message changed -> injectSteps ephemeralMessage
  stop           -> archive new turns from transcriptPath

TRANSCRIPT FORMAT: documented location (~/.gemini/antigravity/brain/<conv>/
.system_generated/logs/transcript.jsonl) but not the line schema — the
parser below is deliberately tolerant (role/type + content/text/parts
variants) and gets hardened against a real file at live-rig time (needs
Google auth). Until then the archive leg is honest best-effort: wrong
shapes parse to nothing, fail-open, debuggable via BRETHOF_BRAIN_HOOK_DEBUG.

FAIL-OPEN: any error exits 0 and never breaks the session.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from brethof_brain_client.client import Client, ClientError
    from brethof_brain_client.config import Config
    from brethof_brain_client import hook as cc_hook
    from brethof_brain_client import transcript as tstate   # state helpers only
except Exception:                                          # noqa: BLE001
    sys.exit(0)

MAX_TURNS_PER_FLUSH = 40
MAX_BYTES_PER_FLUSH = 800_000
TEXT_CAP = 50_000

_ROLE = {"user": "user", "human": "user",
         "assistant": "assistant", "model": "assistant",
         "gemini": "assistant", "agent": "assistant"}


def _text_of(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return str(v.get("text") or v.get("content") or "")
    if isinstance(v, list):
        return "\n".join(t for t in (_text_of(x) for x in v) if t)
    return ""


def parse_transcript(path: str) -> list[dict]:
    """Tolerant JSONL -> conversation turns. Accepts role/type user- and
    assistant-shaped lines with text under content/text/parts/message."""
    turns: list[dict] = []
    with open(path, "rb") as f:
        for raw in f:
            try:
                d = json.loads(raw.decode("utf-8", "replace"))
            except Exception:                                # noqa: BLE001
                continue
            if not isinstance(d, dict):
                continue
            role = _ROLE.get(str(d.get("role") or d.get("type") or "").lower())
            if role is None:
                continue
            text = ""
            for key in ("content", "text", "parts", "message"):
                text = _text_of(d.get(key)).strip()
                if text:
                    break
            if not text:
                continue
            turns.append({"index": len(turns), "line_type": role,
                          "text": text[:TEXT_CAP], "embed": True})
    return turns


# ── tiny per-conversation state (brief-sent flag + last-prompt signature) ────

def _agstate_path(conv: str) -> str:
    home = os.environ.get("BRETHOF_BRAIN_HOME") or os.path.join(
        os.path.expanduser("~"), ".brethof-brain")
    d = os.path.join(home, "state-antigravity")
    os.makedirs(d, exist_ok=True)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in conv)[:120]
    return os.path.join(d, safe + ".json")


def _agstate_load(conv: str) -> dict:
    try:
        with open(_agstate_path(conv), encoding="utf-8") as f:
            return json.load(f)
    except Exception:                                        # noqa: BLE001
        return {}


def _agstate_save(conv: str, st: dict) -> None:
    try:
        with open(_agstate_path(conv), "w", encoding="utf-8") as f:
            json.dump(st, f)
    except Exception:                                        # noqa: BLE001
        pass


def _cc_shaped(payload: dict) -> dict:
    roots = payload.get("workspacePaths") or []
    return {"session_id": str(payload.get("conversationId") or ""),
            "cwd": roots[0] if roots else os.getcwd(),
            "transcript_path": str(payload.get("transcriptPath") or "")}


def _pre_invocation(cfg: Config, payload: dict) -> None:
    inp = _cc_shaped(payload)
    conv = inp["session_id"]
    if not conv:
        return
    project = cc_hook._project(cfg, inp)
    st = _agstate_load(conv)
    pieces = []
    if not st.get("brief_sent"):
        env = Client(cfg).post("/v1/hooks/session-start", {"project": project})
        brief = cc_hook._injection_from_envelope(env)
        if brief:
            pieces.append(brief)
        st["brief_sent"] = True
    prompt = ""
    path = inp["transcript_path"]
    if path and os.path.exists(path):
        turns = parse_transcript(path)
        for t in reversed(turns):
            if t["line_type"] == "user":
                prompt = t["text"]
                break
    if prompt:
        sig = hashlib.sha1(prompt.encode()).hexdigest()
        if sig != st.get("last_prompt_sig"):
            st["last_prompt_sig"] = sig
            env = Client(cfg).post("/v1/hooks/prompt-submit",
                                   {"project": project, "prompt": prompt,
                                    "session_id": conv})
            recall = cc_hook._injection_from_envelope(env)
            if recall:
                pieces.append(recall)
    _agstate_save(conv, st)
    if pieces:
        json.dump({"injectSteps": [{"ephemeralMessage": "\n\n".join(pieces)}]},
                  sys.stdout)


def _stop(cfg: Config, payload: dict) -> None:
    inp = _cc_shaped(payload)
    conv, path = inp["session_id"], inp["transcript_path"]
    if not conv or not path or not os.path.exists(path):
        return
    project = cc_hook._project(cfg, inp)
    all_turns = parse_transcript(path)
    st = tstate.load_state(conv)
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
                          {"project": project, "session_id": conv,
                           "turns": chunk})
        if env.get("status", "ok") != "ok":
            sys.stderr.write("brethof-brain: archive deferred "
                             f"({env.get('notice') or env.get('status')})\n")
            return
        tstate.save_state(conv, 0, chunk[-1]["index"] + 1)


def main() -> int:
    try:
        event = sys.argv[1] if len(sys.argv) > 1 else ""
        payload = json.loads(sys.stdin.read() or "{}")
        if not isinstance(payload, dict):
            return 0
        cfg = Config.load()
        if not cfg.configured():
            return 0
        if event == "pre-invocation":
            _pre_invocation(cfg, payload)
        elif event == "stop":
            _stop(cfg, payload)
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
