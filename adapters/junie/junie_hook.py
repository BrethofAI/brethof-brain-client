#!/usr/bin/env python3
"""JetBrains Junie CLI hook adapter — brief, recall, event-built archive.

Junie's hooks (junie.jetbrains.com/docs/junie-cli-hooks.html) are the
Claude-Code family: snake_case stdin (``hook_event_name``, ``session_id``,
``cwd``, ``project_path``, ``prompt``), and the friendliest output rule in
the fleet: "If the hook output is not valid JSON, the raw stdout is
treated as additionalContext" — so injection is plain printed text.

Junie hands no transcript path. The archive is EVENT-BUILT, dsh-style:
``UserPromptSubmit`` carries the user's prompt, ``Stop`` carries
``last_assistant_message`` — each files its turn with a monotonic index,
which together reconstruct the conversation.

  SessionStart     -> brief (raw stdout)
  UserPromptSubmit -> recall (raw stdout) + archive the user turn
  Stop             -> archive the assistant turn
  SessionEnd       -> flush any pending turns

FAIL-OPEN: any error exits 0 and never breaks the session.
"""
from __future__ import annotations

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

TEXT_CAP = 50_000


def _cc_shaped(payload: dict) -> dict:
    return {"session_id": str(payload.get("session_id") or ""),
            "cwd": str(payload.get("project_path") or payload.get("cwd")
                       or os.getcwd())}


def _archive_turn(cfg: Config, inp: dict, role: str, text: str) -> None:
    """One turn, event-built: index from the client's per-session state; a
    failed send leaves the index unadvanced, so the turn retries on the
    next event (server upserts are idempotent)."""
    session_id = inp["session_id"]
    text = (text or "").strip()
    if not session_id or not text:
        return
    project = cc_hook._project(cfg, inp)
    st = tstate.load_state(session_id)
    idx = st["next_index"]
    env = Client(cfg, timeout=20.0).post(
        "/v1/hooks/stop",
        {"project": project, "session_id": session_id,
         "turns": [{"index": idx, "line_type": role,
                    "text": text[:TEXT_CAP], "embed": True}]})
    if env.get("status", "ok") == "ok":
        tstate.save_state(session_id, 0, idx + 1)
    else:
        sys.stderr.write("brethof-brain: archive deferred "
                         f"({env.get('notice') or env.get('status')})\n")


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
        if event == "SessionStart":
            project = cc_hook._project(cfg, inp)
            env = Client(cfg).post("/v1/hooks/session-start",
                                   {"project": project})
            text = cc_hook._injection_from_envelope(env)
            if text:
                sys.stdout.write(text)   # raw stdout IS additionalContext
        elif event == "UserPromptSubmit":
            prompt = (payload.get("prompt") or "").strip()
            if prompt and inp["session_id"]:
                project = cc_hook._project(cfg, inp)
                env = Client(cfg).post("/v1/hooks/prompt-submit",
                                       {"project": project, "prompt": prompt,
                                        "session_id": inp["session_id"]})
                text = cc_hook._injection_from_envelope(env)
                if text:
                    sys.stdout.write(text)
                _archive_turn(cfg, inp, "user", prompt)
        elif event == "Stop":
            _archive_turn(cfg, inp, "assistant",
                          payload.get("last_assistant_message") or "")
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
