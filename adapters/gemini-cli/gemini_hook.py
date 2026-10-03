#!/usr/bin/env python3
"""Gemini CLI hook adapter — session brief, ambient recall, archive.

Gemini CLI's hooks take Claude Code's output schema
(``hookSpecificOutput.additionalContext``, wrapped by Gemini in
``<hook_context>``); one script serves every event, dispatched on the
payload's ``hook_event_name`` (checked against Gemini CLI 0.62.0, 2026-10-03):

  SessionStart -> POST /v1/hooks/session-start -> additionalContext
  BeforeAgent  -> POST /v1/hooks/prompt-submit  -> additionalContext
                  (in headless mode the prompt arrives with the brief in
                  front as a <hook_context> block — stripped before recall)
  AfterAgent   -> archive the turn from the payload's own ``prompt`` and
                  ``prompt_response`` — the transcript's user line carries
                  our injected brief and recall, the payload does not

FAIL-OPEN: any error exits 0 and never breaks the session. Nothing goes to
stderr: Gemini shows a silent hook's stderr to the user.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

# Checkout bootstrap: allow running straight from the repo.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

try:
    from brethof_brain_client.client import Client, ClientError
    from brethof_brain_client.config import Config
    from brethof_brain_client import hook as cc_hook
except Exception:                                          # noqa: BLE001
    sys.exit(0)   # client not installed — memory off, never break the session

_CONTEXT = re.compile(r"^\s*(?:<hook_context>.*?</hook_context>\s*)+", re.S)


def clean_prompt(prompt: str) -> str:
    """The person's words: Gemini puts injected context in front of the
    prompt as <hook_context> blocks in headless mode."""
    return _CONTEXT.sub("", prompt or "").strip()


def _emit(event: str, text: str) -> None:
    if not text:
        return
    json.dump({"hookSpecificOutput": {"hookEventName": event,
                                      "additionalContext": text}}, sys.stdout)


def _session_start(cfg: Config, inp: dict) -> None:
    project = cc_hook._project(cfg, inp)
    env = Client(cfg).post("/v1/hooks/session-start", {"project": project})
    _emit("SessionStart", cc_hook._injection_from_envelope(env))


def _before_agent(cfg: Config, inp: dict) -> None:
    session_id = inp.get("session_id") or ""
    prompt = clean_prompt(inp.get("prompt") or "")
    if not prompt or not session_id:
        return
    project = cc_hook._project(cfg, inp)
    env = Client(cfg).post("/v1/hooks/prompt-submit",
                           {"project": project, "prompt": prompt,
                            "session_id": session_id})
    _emit("BeforeAgent", cc_hook._injection_from_envelope(env))


def _after_agent(cfg: Config, inp: dict) -> None:
    session_id = inp.get("session_id") or ""
    if not session_id:
        return
    cc_hook._stop_from_payload(cfg, {**inp, "prompt": clean_prompt(inp.get("prompt") or "")},
                               session_id)


def main() -> int:
    debug = bool(os.environ.get("BRETHOF_BRAIN_HOOK_DEBUG"))
    err, sys.stderr = sys.stderr, (sys.stderr if debug else io.StringIO())
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
            _before_agent(cfg, payload)
        elif event == "AfterAgent":
            _after_agent(cfg, payload)
    except ClientError:
        pass
    except Exception:                                      # noqa: BLE001
        if debug:
            import traceback
            traceback.print_exc()
    finally:
        sys.stderr = err
    return 0


if __name__ == "__main__":
    sys.exit(main())
