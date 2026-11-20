"""Agent-agnostic memory hooks.

Claude Code has its own hook wiring (``hook.py``) and Hermes has a memory
provider; every OTHER agent — OpenClaw, a cron job, a custom loop — gets memory
by calling these three hooks at its own lifecycle points:

    from brethof_brain_client import AgentHooks
    mem = AgentHooks(project="marketing", session_id=job_id)

    system_prompt += mem.session_start()          # once, at session start
    ...
    context = mem.before_prompt(user_message)      # before each model call
    ...
    mem.archive(user_message, assistant_reply)     # after each turn
    ...
    mem.end_session()                              # when the sitting is over

Use ONE session_id per sitting (a conversation, a job run) and a new one for
the next: the memory reads a session's exchanges together, five at a time,
and end_session() hands it the ones still waiting.

All three are FAIL-OPEN: if the service is unreachable they return empty / do
nothing rather than raising, so wiring memory in can never break the agent.
``archive`` additionally SPOOLS failed turns to disk (``~/.brethof-brain/spool``)
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
                 config: Optional[Config] = None, timeout: float = 15.0,
                 ephemeral: bool = False):
        self.cfg = config or Config.load()
        if not self.cfg.configured():
            raise ClientError("not paired with a hub (run: brethof-brain pair <hub address>, "
                              "or set BRETHOF_BRAIN_ENDPOINT and BRETHOF_BRAIN_API_KEY)")
        self._http = Client(self.cfg, timeout=timeout)
        self.project = project or self.cfg.default_project or "global"
        self.session_id = session_id or "default"
        # EPHEMERAL: the caller hands the prompt context to ONE model call and
        # never keeps it in the conversation (a per-call overlay). The memory
        # then serves a record again on a later prompt instead of holding it
        # back as already seen this session (the record cooldown) — without
        # it, the second prompt of a sitting got nothing (rig 2026-11-20,
        # openclaw-lib: parts 1-7 served the record on prompt one).
        self.ephemeral = bool(ephemeral)
        self._next_index = 0

    def session_start(self) -> str:
        """Memory to prepend to the system prompt (project index, rules, recent
        state). Empty string on any failure."""
        try:
            env = self._http.post("/v1/hooks/session-start", {
                "project": self.project, "session_id": self.session_id})
        except ClientError:
            return ""
        return env.get("injection", "") or ""

    def before_prompt(self, prompt: str) -> str:
        """Ambient recall relevant to ``prompt``, to inject as extra context:
        the full per-prompt memory, parts 1-7 (``before_prompt_parts``) — the
        legacy single part never carried the history of decisions, so every
        caller of this method now receives it too (2026-11-20). Empty string
        when there's nothing to add or on failure."""
        return self.before_prompt_parts(prompt)

    def before_prompt_parts(self, prompt: str, parts: tuple = (1, 2, 3, 4, 5, 6, 7)) -> str:
        """The FULL per-prompt memory, as Claude Code receives it: the server
        composes it once per prompt and hands it out in numbered parts (the
        rule and records in 1-6, the history of decisions near the prompt in
        7). The legacy single part (no part, or 0) never carries the history
        block (found 2026-11-18: a decided codename came back in part 7 and
        nowhere in part 0). Parts are asked in parallel and
        joined in order; any that fail are simply left out."""
        if not (prompt or "").strip():
            return ""
        import threading
        got: dict = {}

        def one(n: int) -> None:
            try:
                body = {"project": self.project, "prompt": prompt,
                        "session_id": self.session_id, "part": n}
                if self.ephemeral:
                    body["ephemeral"] = True
                env = self._http.post("/v1/hooks/prompt-submit", body)
                got[n] = env.get("injection", "") or ""
            except ClientError:
                got[n] = ""
        threads = [threading.Thread(target=one, args=(n,), daemon=True) for n in parts]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return "\n\n".join(got[n].strip() for n in parts if got.get(n, "").strip())

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

    def end_session(self, last_index: Optional[int] = None) -> dict:
        """The sitting is over: hand the memory the exchanges still waiting
        (it reads a session five exchanges at a time, so the last few of a
        sitting would otherwise wait until the next session starts). Also
        checks the archive holds every turn up to `last_index`.

        `last_index` defaults to this instance's own count, which is right
        only when ONE instance archived the whole sitting. An app that builds
        a fresh AgentHooks per message (a gateway) must pass the sitting's
        real last turn index. Returns the server envelope, or {} on failure."""
        last = self._next_index - 1 if last_index is None else int(last_index)
        try:
            return self._http.post("/v1/hooks/pre-compact", {
                "project": self.project, "session_id": self.session_id,
                "last_index": last})
        except ClientError:
            return {}

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
