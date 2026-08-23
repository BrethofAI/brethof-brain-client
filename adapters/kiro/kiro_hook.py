#!/usr/bin/env python3
"""Kiro (AWS) hook adapter — brief and recall via stdout-to-context hooks.

Kiro's shell-command hooks (kiro.dev/docs/hooks/; the CLI is the renamed
Amazon Q Developer CLI, whose agent-format hooks carry the same behavior)
add a hook's STDOUT to the agent's context on exit 0 — plain text, no
envelope. agentSpawn/SessionStart output persists for the session;
userPromptSubmit/"Prompt Submit" output attaches to that prompt.

The event arrives as ARGV (Kiro's payloads are the thinnest of the fleet
and their stdin schema is not fully documented):

  session-start -> brief to stdout
  prompt-submit -> recall to stdout (prompt taken from stdin JSON under
                   any of prompt/user_prompt/message/text — TOLERANT,
                   hardened at live-rig time) + archive the user turn
  stop          -> archive any assistant text found on stdin (tolerant;
                   the stop payload shape is UNVERIFIED — until a live
                   run pins it, archive here is best-effort and honest
                   about it)

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


def _payload() -> dict:
    try:
        d = json.loads(sys.stdin.read() or "{}")
        return d if isinstance(d, dict) else {}
    except Exception:                                        # noqa: BLE001
        return {}


def _first(payload: dict, *keys: str) -> str:
    for k in keys:
        v = payload.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def _session(payload: dict) -> dict:
    return {"session_id": _first(payload, "session_id", "sessionId",
                                 "conversation_id", "conversationId") or "kiro",
            "cwd": _first(payload, "cwd", "workspace_root",
                          "workspaceRoot") or os.getcwd()}


def _archive_turn(cfg: Config, inp: dict, role: str, text: str) -> None:
    text = (text or "").strip()
    if not text:
        return
    project = cc_hook._project(cfg, inp)
    st = tstate.load_state(inp["session_id"])
    idx = st["next_index"]
    env = Client(cfg, timeout=20.0).post(
        "/v1/hooks/stop",
        {"project": project, "session_id": inp["session_id"],
         "turns": [{"index": idx, "line_type": role,
                    "text": text[:TEXT_CAP], "embed": True}]})
    if env.get("status", "ok") == "ok":
        tstate.save_state(inp["session_id"], 0, idx + 1)


def main() -> int:
    try:
        event = sys.argv[1] if len(sys.argv) > 1 else ""
        payload = _payload()
        cfg = Config.load()
        if not cfg.configured():
            return 0
        inp = _session(payload)
        if event == "session-start":
            project = cc_hook._project(cfg, inp)
            env = Client(cfg).post("/v1/hooks/session-start",
                                   {"project": project})
            text = cc_hook._injection_from_envelope(env)
            if text:
                sys.stdout.write(text)   # stdout IS the context channel
        elif event == "prompt-submit":
            prompt = _first(payload, "prompt", "user_prompt", "userPrompt",
                            "message", "text")
            if prompt:
                project = cc_hook._project(cfg, inp)
                env = Client(cfg).post("/v1/hooks/prompt-submit",
                                       {"project": project, "prompt": prompt,
                                        "session_id": inp["session_id"]})
                text = cc_hook._injection_from_envelope(env)
                if text:
                    sys.stdout.write(text)
                _archive_turn(cfg, inp, "user", prompt)
        elif event == "stop":
            _archive_turn(cfg, inp, "assistant",
                          _first(payload, "last_assistant_message",
                                 "lastAssistantMessage", "response",
                                 "assistant_message"))
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
