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
import os
import sys
import traceback

from .client import Client, ClientError
from .config import Config
from . import transcript

# BRETHOF_MIND_HOOK_DEBUG=1 turns the fail-open silence into stderr truth.
# The 2026-07-06 audit named silent swallowing this client's biggest risk;
# 2026-07-28 proved it: a pre-compact that never enqueued took four probing
# rounds to even OBSERVE because every layer ate the evidence.
DEBUG = bool(os.environ.get("BRETHOF_MIND_HOOK_DEBUG"))

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
        # A parse failure degrades to {} and every handler no-ops on the
        # missing session_id — fail-open holds. But silently: a mangled test
        # payload cost four debugging rounds on 2026-07-28 because this except
        # ate the JSONDecodeError. Debug mode tells the truth.
        if DEBUG:
            traceback.print_exc()
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

def _session_start(cfg: Config, inp: dict, args: tuple = ()) -> None:
    # Claude Code caps EACH hook's output at 10k chars, so the payload is
    # delivered as budgeted parts — settings registers this event once per
    # part ("session-start 1", "session-start 2"). No part argument = the
    # whole payload in one piece (legacy registrations keep working).
    project = cfg.project_for(inp.get("cwd", ""))
    payload: dict = {"project": project}
    if args:
        try:
            payload["part"] = int(args[0])
        except (TypeError, ValueError):
            pass
    env = Client(cfg).post("/v1/hooks/session-start", payload)
    _emit_context("SessionStart", _injection_from_envelope(env))


def _prompt_submit(cfg: Config, inp: dict, args: tuple = ()) -> None:
    project = cfg.project_for(inp.get("cwd", ""))
    prompt = (inp.get("prompt") or "").strip()
    session_id = inp.get("session_id") or ""
    if not prompt or not session_id:
        return
    env = Client(cfg).post("/v1/hooks/prompt-submit",
                           {"project": project, "prompt": prompt,
                            "session_id": session_id})
    _emit_context("UserPromptSubmit", _injection_from_envelope(env))


def _stop(cfg: Config, inp: dict, args: tuple = ()) -> None:
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


def _commit(cfg: Config, inp: dict, args: tuple = ()) -> None:
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


def _pre_compact(cfg: Config, inp: dict, args: tuple = ()) -> None:
    """/compact is the moment the client is about to summarize its transcript
    away — the last chance to guarantee the server archive holds ALL of it.

    ARCHIVE PARITY (the hook's whole job since 2026-08-06 — the compact-era
    curate enqueue is retired; per-turn curation owns every window):
    1. FLUSH the pending tail (stop-hook logic).
    2. HANDSHAKE — send our last index; the server answers with its own max
       AND row count, so both a lagging tail and MID-STREAM HOLES (backup
       restore, lost writes) are visible.
    3. HEAL — on any gap, reset the flush state to zero and re-send the
       whole transcript (server inserts are idempotent), then verify once
       more. A healed or unhealable gap is reported on stderr; the compact
       itself is never blocked — memory is an enhancement, not a gate.
    """
    session_id = inp.get("session_id", "")
    project = cfg.project_for(inp.get("cwd", ""))

    def _flush():
        try:
            _stop(cfg, inp)
        except Exception:  # noqa: BLE001 — flush is best-effort here; _stop
            if DEBUG:      # has its own state discipline, retries next turn
                traceback.print_exc()

    def _handshake():
        state = transcript.load_state(session_id)
        return Client(cfg, timeout=10.0).post(
            "/v1/hooks/pre-compact",
            {"session_id": session_id, "project": project,
             "last_index": max(0, state["next_index"] - 1)})

    _flush()
    try:
        env = _handshake()
        if env.get("flush_needed"):
            # The archive disagrees with this transcript — re-send it all.
            transcript.save_state(session_id, 0, 0)
            _flush()
            env = _handshake()
            if env.get("flush_needed"):
                sys.stderr.write(
                    "brethof-mind: archive STILL behind this transcript "
                    "after full re-flush — some turns may be lost to "
                    "compaction (server last_index="
                    f"{env.get('server_last_index')}).\n")
            else:
                sys.stderr.write("brethof-mind: archive gap detected and "
                                 "healed before compact.\n")
    except ClientError:
        if DEBUG:
            traceback.print_exc()


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
        if DEBUG:
            sys.stderr.write(f"[hook-debug] event={event} "
                             f"inp_keys={sorted(inp)}\n")
        handler(cfg, inp, tuple(argv[1:]))
        if DEBUG:
            sys.stderr.write(f"[hook-debug] {event} handler returned clean\n")
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
        if DEBUG:
            traceback.print_exc()
    return 0


if __name__ == "__main__":
    sys.exit(main())
