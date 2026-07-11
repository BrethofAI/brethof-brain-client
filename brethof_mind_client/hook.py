"""Claude Code hook entrypoint.

One dispatcher wired to Claude Code's hook events. Invoke as::

    python -m brethof_mind_client.hook <event>

where ``<event>`` is one of: session-start, prompt-submit, stop, pre-compact,
commit. Each reads the hook JSON on stdin, forwards it to the data plane, and —
for the two injecting events — prints the server's memory blob back as
``additionalContext`` for Claude Code to load.

FAIL-OPEN CONTRACT: a hook must never break the user's session. Every path is
wrapped so that ANY error (bad config, network down, HTTP 5xx, malformed input)
exits 0 with no injected context. Memory is an enhancement, never a gate.

ONE deliberate exception to silence: auth failures (401/403, envelope
``auth_failed``). A rotated key or lapsed plan halts memory AND archiving
persistently — staying silent there means the user finds out weeks later,
after Claude Code's transcript cleanup has already deleted the unarchived
turns. Those get a one-line notice; everything transient stays quiet.
"""
from __future__ import annotations

import json
import sys

from .client import Client, ClientError
from .config import Config
from . import transcript

# Chunked archive flush: bounded batches, state committed per confirmed batch,
# so a large backlog (fresh install on an old session, over_cap period, outage)
# drains incrementally instead of all-or-nothing in a single doomed POST.
MAX_TURNS_PER_FLUSH = 40
MAX_BYTES_PER_FLUSH = 800_000

_EVENT_NAMES = {"session-start": "SessionStart", "prompt-submit": "UserPromptSubmit"}


def _read_stdin() -> dict:
    try:
        data = json.load(sys.stdin)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _emit_context(event_name: str, text: str) -> None:
    """Hand context back to Claude Code via the documented hook output shape."""
    if not text:
        return
    out = {
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": text,
        }
    }
    json.dump(out, sys.stdout)


AUTH_NOTICE = ("[brethof-mind: API key rejected — memory and archiving are OFF. "
               "Check brethof.ai/account, then run `brethof-mind setup`.]")


def _injection_from_envelope(env: dict) -> str:
    """Turn an envelope into the text to inject. On non-ok statuses we surface a
    short one-line notice instead of silently showing nothing (the anti-silent-
    failure contract), but never a stack trace or raw error."""
    status = env.get("status", "ok")
    injection = env.get("injection") or ""
    notice = env.get("notice") or ""
    if status == "ok":
        return injection
    if status == "auth_failed":
        return AUTH_NOTICE
    if status in ("provisioning", "over_cap", "read_only", "unknown_project"):
        tag = {"provisioning": "setting up", "over_cap": "memory full",
               "read_only": "read-only", "unknown_project": "no memory"}[status]
        return injection or (f"[brethof-mind: {tag}"
                             + (f" — {notice}" if notice else "") + "]")
    return injection  # server_error → transient, inject nothing extra


# ── event handlers ──────────────────────────────────────────────────────────

def _session_start(cfg: Config, inp: dict) -> None:
    project = cfg.project_for(inp.get("cwd", ""))
    env = Client(cfg).post("/v1/hooks/session-start", {"project": project})
    _emit_context("SessionStart", _injection_from_envelope(env))


def _prompt_submit(cfg: Config, inp: dict) -> None:
    project = cfg.project_for(inp.get("cwd", ""))
    prompt = (inp.get("prompt") or "").strip()
    session_id = inp.get("session_id") or ""
    if not prompt or not session_id:
        return
    env = Client(cfg).post("/v1/hooks/prompt-submit",
                           {"project": project, "prompt": prompt,
                            "session_id": session_id})
    _emit_context("UserPromptSubmit", _injection_from_envelope(env))


def _stop(cfg: Config, inp: dict) -> None:
    """Archive new conversation turns in bounded chunks. State (offset + index)
    advances ONLY past turns the server has confirmed, one chunk at a time, so
    a failure mid-backlog keeps every confirmed chunk and retries the rest."""
    session_id = inp.get("session_id") or ""
    transcript_path = inp.get("transcript_path") or ""
    if not session_id or not transcript_path:
        return
    project = cfg.project_for(inp.get("cwd", ""))
    turns, tail_offset, next_index = transcript.read_new_turns(transcript_path, session_id)
    if not turns:
        # Nothing to send, but advance past any complete non-conversation lines
        # we scanned so we don't re-read them forever.
        state = transcript.load_state(session_id)
        if (tail_offset, next_index) != (state["offset"], state["next_index"]):
            transcript.save_state(session_id, tail_offset, next_index)
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
        env = client.post("/v1/hooks/stop",
                          {"project": project, "session_id": session_id,
                           "turns": payload})
        if env.get("status", "ok") != "ok":
            # over_cap / read_only / server_error: keep what's confirmed,
            # DON'T advance past this chunk — retry next turn. stderr only
            # (shows in hook debug, never in the session).
            sys.stderr.write(
                f"brethof-mind: archive deferred ({env.get('notice') or env.get('status')})\n")
            return
        last = chunk[-1]
        transcript.save_state(session_id, last["_offset"], last["index"] + 1)
    # Whole backlog confirmed — also advance past trailing non-conversation lines.
    transcript.save_state(session_id, tail_offset, next_index)


def _commit(cfg: Config, inp: dict) -> None:
    project = cfg.project_for(inp.get("cwd", ""))
    payload = {"project": project}
    for k in ("hash", "branch", "repo", "message"):
        if inp.get(k) is not None:
            payload[k] = inp.get(k)
    files = inp.get("files")
    if isinstance(files, list):
        payload["files"] = files
    if not payload.get("hash"):
        return
    Client(cfg).post("/v1/hooks/commit", payload)


def _pre_compact(cfg: Config, inp: dict) -> None:
    # Server ack only; curate/marker behaviour is a local concern the server
    # doesn't gate. Best-effort — swallow anything.
    try:
        Client(cfg, timeout=5.0).post("/v1/hooks/pre-compact",
                                      {"session_id": inp.get("session_id", "")})
    except ClientError:
        pass


_HANDLERS = {
    "session-start": _session_start,
    "prompt-submit": _prompt_submit,
    "stop": _stop,
    "commit": _commit,
    "pre-compact": _pre_compact,
}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    event = argv[0] if argv else ""
    handler = _HANDLERS.get(event)
    if handler is None:
        # Unknown event: do nothing, don't break the session.
        return 0
    try:
        cfg = Config.load()
        if not cfg.configured():
            return 0  # not set up yet — stay silent, `brethof-mind setup` handles UX
        inp = _read_stdin()
        handler(cfg, inp)
    except ClientError as e:
        # Persistent auth problems are the ONE condition worth a signal: a dead
        # key silently halts archiving until the transcripts age out. Inject a
        # notice on the injecting events; stderr elsewhere.
        if e.status_code in (401, 403):
            if event in _EVENT_NAMES:
                _emit_context(_EVENT_NAMES[event], AUTH_NOTICE)
            else:
                sys.stderr.write("brethof-mind: API key rejected — archiving off; "
                                 "run `brethof-mind doctor`\n")
        # Anything else: data plane unreachable → memory just doesn't load.
    except Exception:  # noqa: BLE001 — absolute last resort; never break the turn
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
