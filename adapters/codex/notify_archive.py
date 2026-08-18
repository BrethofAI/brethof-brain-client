#!/usr/bin/env python3
"""Codex turn archiver — the `notify` program.

Codex-cli (verified 0.147.0, 2026-08-17) does NOT fire hooks.json events in
`codex exec`, but its `notify` mechanism fires on every completed turn with
the whole exchange in one JSON argv argument:

    {"type": "agent-turn-complete", "thread-id": ..., "cwd": ...,
     "input-messages": [...], "last-assistant-message": ...}

So archival rides notify — proven, headless-testable — while the hooks
registration ships alongside for the day codex turns hook firing on.
Fail-open by contract: whatever happens, exit 0.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def main() -> int:
    try:
        evt = json.loads(sys.argv[1])
        if evt.get("type") != "agent-turn-complete":
            return 0
        thread = evt.get("thread-id") or "codex"
        prompts = [t for t in (evt.get("input-messages") or [])
                   if isinstance(t, str) and t.strip()]
        answer = (evt.get("last-assistant-message") or "").strip()
        if not prompts and not answer:
            return 0

        from brethof_brain_client.api import MindClient
        from brethof_brain_client.config import Config
        cfg = Config.load()
        project = (os.environ.get("BRETHOF_BRAIN_PROJECT")
                   or cfg.resolve(evt.get("cwd") or "")[0])

        state_dir = Path.home() / ".codex" / "brethof-brain"
        state_dir.mkdir(parents=True, exist_ok=True)
        state = state_dir / f"{thread}.idx"
        idx = int(state.read_text()) if state.exists() else 0

        turns = []
        for p in prompts:
            turns.append({"index": idx, "line_type": "user", "text": p})
            idx += 1
        if answer:
            turns.append({"index": idx, "line_type": "assistant",
                          "text": answer})
            idx += 1
        env = MindClient().archive_turns(project=project,
                                         session_id=f"codex-{thread}",
                                         turns=turns)
        if env.get("status", "ok") == "ok":
            state.write_text(str(idx))
    except Exception:
        pass                    # a notifier must never break the turn
    return 0


if __name__ == "__main__":
    sys.exit(main())
