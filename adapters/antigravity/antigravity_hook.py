#!/usr/bin/env python3
"""Antigravity CLI (agy) hook adapter — session brief, ambient recall, archive.

Checked against agy 1.2.16 on 2026-10-03 (its bundled hooks docs and live
payloads). Antigravity's hooks are its own schema: camelCase payloads
(``conversationId``, ``transcriptPath``, ``invocationNum``), no event name
(so the event arrives as ARGV), config in ``~/.gemini/config/hooks.json``
or ``<ws>/.agents/hooks.json`` as ``{"<name>": {"PreInvocation": [handler],
"Stop": [handler]}}`` with flat handler lists, timeouts in seconds.

ONE injection channel: PreInvocation returns ``{"injectSteps":
[{"ephemeralMessage": "..."}]}`` — and that text reaches ONE model call
only (the next call does not carry it). So every PreInvocation injects the
brief and the current prompt's recall; both are fetched once and kept
(the brief per conversation, the recall per prompt), and the recall is
asked as ``ephemeral`` so the memory does not hold its records back for
the cooldown a persisting injection needs.

  pre-invocation -> brief + this prompt's recall -> injectSteps
  stop           -> archive new turns from the transcript

TRANSCRIPT (``…/brain/<conv>/.system_generated/logs/transcript_full.jsonl``):
one step per line ``{step_index, source, type, status, created_at,
content}``; USER_INPUT is the person (their words inside <USER_REQUEST>),
PLANNER_RESPONSE the reply; EPHEMERAL_MESSAGE (our own injection) and
SYSTEM_MESSAGE are not conversation. A step may be rewritten as its status
changes — the last line per step_index wins.

FAIL-OPEN: any error exits 0 and never breaks the session.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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
_REQUEST = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.S)


def _text_of(v) -> str:
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return str(v.get("text") or v.get("content") or "")
    if isinstance(v, list):
        return "\n".join(t for t in (_text_of(x) for x in v) if t)
    return ""


def parse_transcript(path: str) -> list[dict]:
    """transcript_full.jsonl -> the conversation's turns, in step order."""
    steps: dict = {}
    with open(path, "rb") as f:
        for raw in f:
            try:
                d = json.loads(raw.decode("utf-8", "replace"))
            except Exception:                                # noqa: BLE001
                continue
            if isinstance(d, dict) and d.get("type") in ("USER_INPUT", "PLANNER_RESPONSE"):
                steps[d.get("step_index", len(steps))] = d
    turns: list[dict] = []
    for _, d in sorted(steps.items(), key=lambda kv: (isinstance(kv[0], str), kv[0])):
        text = _text_of(d.get("content")).strip()
        if d["type"] == "USER_INPUT":
            m = _REQUEST.search(text)
            text, role = (m.group(1) if m else text).strip(), "user"
        else:
            role = "assistant"
        if text:
            turns.append({"index": len(turns), "line_type": role,
                          "text": text[:TEXT_CAP], "embed": True})
    return turns


# ── per-conversation state: the brief, and the recall of the current prompt ──
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


def _dbg(line: str) -> None:
    f = os.environ.get("BRETHOF_BRAIN_DEBUG_FILE")
    if f:
        try:
            with open(f, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
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
    if "brief" not in st:
        env = Client(cfg).post("/v1/hooks/session-start", {"project": project})
        st["brief"] = cc_hook._injection_from_envelope(env)
    prompt = ""
    path = inp["transcript_path"]
    if path and os.path.exists(path):
        for t in reversed(parse_transcript(path)):
            if t["line_type"] == "user":
                prompt = t["text"]
                break
    if prompt:
        sig = hashlib.sha1(prompt.encode()).hexdigest()
        if sig != st.get("prompt_sig"):
            env = Client(cfg).post("/v1/hooks/prompt-submit",
                                   {"project": project, "prompt": prompt,
                                    "session_id": conv, "ephemeral": True})
            st["prompt_sig"], st["recall"] = sig, cc_hook._injection_from_envelope(env)
    _agstate_save(conv, st)
    pieces = [p for p in (st.get("brief"), st.get("recall") if prompt else "") if p]
    _dbg(f"agy pre-invocation {conv} #{payload.get('invocationNum')} "
         f"brief {len(st.get('brief') or '')} recall {len(st.get('recall') or '') if prompt else 0}")
    if pieces:
        json.dump({"injectSteps": [{"ephemeralMessage": "\n\n".join(pieces)}]}, sys.stdout)


def _stop(cfg: Config, payload: dict) -> None:
    inp = _cc_shaped(payload)
    conv, path = inp["session_id"], inp["transcript_path"]
    if not conv or not path or not os.path.exists(path):
        return
    project = cc_hook._project(cfg, inp)
    st = tstate.load_state(conv)
    turns = [t for t in parse_transcript(path) if t["index"] >= st["next_index"]]
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
        env = client.post("/v1/hooks/stop", {"project": project, "session_id": conv,
                                             "turns": chunk})
        if env.get("status", "ok") != "ok":
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
    except ClientError:
        pass
    except Exception:                                      # noqa: BLE001
        if os.environ.get("BRETHOF_BRAIN_HOOK_DEBUG"):
            import traceback
            traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
