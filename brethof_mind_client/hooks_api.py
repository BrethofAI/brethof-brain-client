"""Agent-agnostic memory hooks.

Claude Code has its own hook wiring (``hook.py``) and Hermes has a memory
provider; every OTHER agent — OpenClaw, a cron job, a custom loop — gets memory
by calling these three hooks at its own lifecycle points:

    from brethof_mind_client import AgentHooks
    mem = AgentHooks(project="marketing", session_id=job_id)

    system_prompt += mem.session_start()          # once, at session start
    ...
    context = mem.before_prompt(user_message)      # before each model call
    ...
    mem.archive(user_message, assistant_reply)     # after each turn

All three are FAIL-OPEN: if the service is unreachable they return empty / do
nothing rather than raising, so wiring memory in can never break the agent.
``archive`` additionally SPOOLS failed turns to disk (``~/.brethof-mind/spool``)
and drains the spool on the next call, so a transient outage delays archiving
instead of losing turns. The server does isolation, recall, embedding, and
archival; this is just glue.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from .client import Client, ClientError
from .config import SPOOL_DIR, Config, ensure_dirs

SPOOL_CAP_BYTES = 1_000_000  # per-session spool bound; oldest turns drop past it


class AgentHooks:
    def __init__(self, project: Optional[str] = None, session_id: str = "default",
                 config: Optional[Config] = None, timeout: float = 15.0):
        self.cfg = config or Config.load()
        if not self.cfg.configured():
            raise ClientError("no API key configured (set BRETHOF_MIND_API_KEY "
                              "or run: brethof-mind setup)")
        self._http = Client(self.cfg, timeout=timeout)
        self.project = project or self.cfg.default_project or "global"
        self.session_id = session_id or "default"
        self._next_index = 0

    def session_start(self) -> str:
        """Memory to prepend to the system prompt (project index, rules, recent
        state). Empty string on any failure."""
        try:
            env = self._http.post("/v1/hooks/session-start", {"project": self.project})
        except ClientError:
            return ""
        return env.get("injection", "") or ""

    def before_prompt(self, prompt: str) -> str:
        """Ambient recall relevant to ``prompt``, to inject as extra context.
        Empty string when there's nothing to add or on failure."""
        if not (prompt or "").strip():
            return ""
        try:
            env = self._http.post("/v1/hooks/prompt-submit", {
                "project": self.project, "prompt": prompt,
                "session_id": self.session_id})
        except ClientError:
            return ""
        return env.get("injection", "") or ""

    def archive(self, user_text: str = "", assistant_text: str = "") -> dict:
        """Archive a turn pair into the chat memory. Returns the server envelope
        ({status, archived, ...}) or {} on failure. Indices auto-increment per
        AgentHooks instance; the server UPSERTs on (session_id, index, text), so
        replaying a spooled turn is idempotent, never a duplicate."""
        turns = []
        if (user_text or "").strip():
            turns.append({"index": self._next_index, "line_type": "user",
                          "text": user_text, "embed": True})
            self._next_index += 1
        if (assistant_text or "").strip():
            turns.append({"index": self._next_index, "line_type": "assistant",
                          "text": assistant_text, "embed": True})
            self._next_index += 1
        if not turns:
            return {}
        batch = self._read_spool() + turns
        try:
            env = self._http.post("/v1/hooks/stop", {
                "project": self.project, "session_id": self.session_id,
                "turns": batch}, timeout=20.0)
        except ClientError:
            self._write_spool(batch)  # keep for the next call — outage ≠ loss
            return {}
        if env.get("status", "ok") == "ok":
            self._clear_spool()
        else:
            self._write_spool(batch)  # over_cap/read_only: defer, don't drop
        return env

    # ── spool (fail-open persistence for archive) ───────────────────────────

    def _spool_path(self) -> str:
        safe = "".join(c for c in self.session_id if c.isalnum() or c in "-_")
        return os.path.join(SPOOL_DIR, f"{safe or 'default'}.jsonl")

    def _read_spool(self) -> list:
        try:
            with open(self._spool_path(), encoding="utf-8") as f:
                return [t for t in (json.loads(x) for x in f if x.strip())
                        if isinstance(t, dict)]
        except Exception:
            return []

    def _write_spool(self, turns: list) -> None:
        try:
            ensure_dirs()
            lines = [json.dumps(t, ensure_ascii=False) for t in turns]
            # Bound the spool: keep the NEWEST turns within the cap.
            kept, size = [], 0
            for line in reversed(lines):
                size += len(line) + 1
                if size > SPOOL_CAP_BYTES:
                    break
                kept.append(line)
            tmp = self._spool_path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write("\n".join(reversed(kept)) + "\n")
            os.replace(tmp, self._spool_path())
        except Exception:
            pass  # spooling is best-effort; never let it break the agent

    def _clear_spool(self) -> None:
        try:
            os.remove(self._spool_path())
        except OSError:
            pass
