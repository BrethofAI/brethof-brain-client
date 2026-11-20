"""brethof-brain memory provider for Hermes Agent.

Hermes integrates memory through a MemoryProvider (single-select,
``memory.provider: brethof-brain`` in config.yaml). Its lifecycle IS the
ambient contract every brethof-brain adapter ships:

  initialize()          -> POST /v1/hooks/session-start   the brain's briefing
  system_prompt_block() -> that briefing, in the system prompt
  prefetch()            -> POST /v1/hooks/prompt-submit   ambient recall, per turn
  sync_turn()           -> POST /v1/hooks/stop            the turn, archived

Explicit memory tools (search_brain, save_project, ...) are deliberately NOT
registered here: point Hermes's native MCP client at the same endpoint
(see README) — one config block, the full customer surface, zero duplicate
code. Stdlib only, so it drops into ~/.hermes/plugins/ without dependencies.

Config, env first, then $HERMES_HOME/.env, then ~/.brethof-brain/config.json:
  BRETHOF_BRAIN_API_KEY            this device's key (bd_..., required)
  BRETHOF_BRAIN_ENDPOINT           your hub (default http://127.0.0.1:8600;
                                   or https://<your hub's address>)
  BRETHOF_BRAIN_PROJECT            the project this agent reads and archives to
`brethof-brain pair <hub address>` writes the endpoint and the key into
~/.brethof-brain/config.json; nothing else needs setting.

Every path is fail-open: memory can never block or break a run.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

VERSION = "1.0.0"
USER_AGENT = f"brethof-brain-hermes/{VERSION}"
DEFAULT_ENDPOINT = "http://127.0.0.1:8600"   # the hub's front door
HOOK_TIMEOUT = 12.0          # session-start / prompt-submit
ARCHIVE_TIMEOUT = 20.0       # stop
PROMPT_PARTS = (1, 2, 3, 4, 5, 6, 7)


# ---------------------------------------------------------------- config --
def _hermes_env_file() -> Dict[str, str]:
    """$HERMES_HOME/.env — Hermes loads it for most entrypoints, not all."""
    out: Dict[str, str] = {}
    candidates: List[Path] = []
    try:
        from hermes_constants import get_hermes_home  # type: ignore
        candidates.append(Path(get_hermes_home()) / ".env")
    except Exception:
        pass
    home = os.environ.get("HERMES_HOME")
    if home:
        candidates.append(Path(home) / ".env")
    candidates.append(Path.home() / ".hermes" / ".env")
    for f in candidates:
        try:
            if not f.exists():
                continue
            for raw in f.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                out.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            break
        except Exception:
            continue
    return out


def _client_file() -> Dict[str, Any]:
    """~/.brethof-brain/config.json — the file every brethof-brain adapter shares."""
    try:
        home = os.environ.get("BRETHOF_BRAIN_HOME") or str(Path.home() / ".brethof-brain")
        return json.loads(Path(home, "config.json").read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def load_config() -> Dict[str, Any]:
    env = os.environ
    envf = _hermes_env_file()
    f = _client_file()

    def pick(*names: str, file_key: str = "", default: str = "") -> str:
        for n in names:
            v = env.get(n) or envf.get(n)
            if v and v.strip():
                return v.strip()
        v = f.get(file_key) if file_key else None
        return str(v).strip() if v else default

    return {
        "endpoint": pick("BRETHOF_BRAIN_ENDPOINT", file_key="endpoint",
                         default=DEFAULT_ENDPOINT).rstrip("/"),
        "api_key": pick("BRETHOF_BRAIN_API_KEY", file_key="api_key"),
        "project": pick("BRETHOF_BRAIN_PROJECT", "HERMES_MEMORY_PROJECT",
                        file_key="default_project", default="global"),
    }


# -------------------------------------------------------------- provider --
class BrethofBrainProvider(MemoryProvider):
    """Routes Hermes's memory lifecycle through a brethof-brain box."""

    def __init__(self) -> None:
        self._cfg = load_config()
        self._session_id = ""
        self._brief = ""
        self._index = 0
        self._writes = True          # False for cron/subagent/flush contexts
        self._lock = threading.Lock()

    # -- identity ------------------------------------------------------
    @property
    def name(self) -> str:
        return "brethof-brain"

    def is_available(self) -> bool:
        # No network here, per the contract: configured means ready.
        self._cfg = load_config()
        return bool(self._cfg["api_key"])

    def unavailable_reason(self) -> str:
        return ("pair this machine with your hub: `brethof-brain pair <hub address>` "
                "(or set BRETHOF_BRAIN_API_KEY in ~/.hermes/.env)")

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return [
            {"key": "api_key", "description":
                "This device's key (bd_...) — `brethof-brain pair` saves it for you",
             "secret": True, "required": True, "env_var": "BRETHOF_BRAIN_API_KEY",
             "url": "https://brethof.ai/brain"},
            {"key": "endpoint", "description":
                "Your hub: http://127.0.0.1:8600 on this machine, "
                "https://<your hub's address> for a hub on another machine",
             "default": DEFAULT_ENDPOINT, "env_var": "BRETHOF_BRAIN_ENDPOINT"},
            {"key": "project", "description":
                "The project this agent reads from and archives to",
             "default": "global", "env_var": "BRETHOF_BRAIN_PROJECT"},
        ]

    # -- HTTP (stdlib) -------------------------------------------------
    def _post(self, path: str, payload: Dict[str, Any],
              timeout: float) -> Optional[Dict[str, Any]]:
        # The hub's front door takes the device key as a Bearer token only.
        req = urllib.request.Request(
            self._cfg["endpoint"] + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self._cfg['api_key']}",
                     "Content-Type": "application/json",
                     "Accept": "application/json",
                     "User-Agent": USER_AGENT},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            logger.debug("brethof-brain: %s -> %s", path, e.code)
            return None
        except Exception as e:  # noqa: BLE001
            logger.debug("brethof-brain: %s failed: %s", path, e)
            return None

    # -- lifecycle -----------------------------------------------------
    def initialize(self, session_id: str, **kwargs: Any) -> None:
        self._cfg = load_config()
        self._session_id = session_id or ""
        self._index = 0
        # Cron system prompts and subagents must not write as the user.
        self._writes = (kwargs.get("agent_context") or "primary") == "primary"
        env = self._post("/v1/hooks/session-start",
                         {"project": self._cfg["project"], "source": "startup",
                          "session_id": self._session_id}, HOOK_TIMEOUT)
        self._brief = (env or {}).get("injection") or ""

    def system_prompt_block(self) -> str:
        return self._brief

    def on_session_switch(self, new_session_id: str, *, reset: bool = False,
                          **kwargs: Any) -> None:
        self._session_id = new_session_id or self._session_id
        if reset:
            self._index = 0

    # -- recall, per turn (synchronous: the box answers in well under a second)
    def prefetch(self, query: str, *, session_id: str = "") -> str:
        q = (query or "").strip()
        if not q:
            return ""
        # PARTS 1-7, as Claude Code receives them: records and rules in 1-6,
        # the history of decisions near the prompt in 7 (no part = the legacy
        # blob, which never carries that history). In parallel, so the wall
        # time stays one request's HOOK_TIMEOUT; a failed part is left out.
        body = {"project": self._cfg["project"], "prompt": q,
                "session_id": session_id or self._session_id}
        got: Dict[int, str] = {}

        def one(n: int) -> None:
            env = self._post("/v1/hooks/prompt-submit", {**body, "part": n}, HOOK_TIMEOUT)
            got[n] = str((env or {}).get("injection") or "").strip()
        threads = [threading.Thread(target=one, args=(n,), daemon=True) for n in PROMPT_PARTS]
        for t in threads:
            t.start()
        for t in threads:
            t.join(HOOK_TIMEOUT + 1)
        return "\n\n".join(got[n] for n in PROMPT_PARTS if got.get(n))

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        return None  # prefetch() runs at turn start

    # -- archive, per turn ---------------------------------------------
    def sync_turn(self, user_content: str, assistant_content: str, *,
                  session_id: str = "", messages: Optional[List[Dict[str, Any]]] = None,
                  **kwargs: Any) -> None:
        if not self._writes:
            return
        turns: List[Dict[str, Any]] = []
        with self._lock:
            for role, text in (("user", user_content), ("assistant", assistant_content)):
                if text and text.strip():
                    turns.append({"index": self._index, "line_type": role,
                                  "text": text, "embed": True})
                    self._index += 1
        if not turns:
            return
        # Hermes dispatches sync_turn off the reply path; block here so the
        # POST completes (a fire-and-forget thread was torn down before slow
        # archives finished, measured on the first version of this provider).
        self._post("/v1/hooks/stop",
                   {"project": self._cfg["project"],
                    "session_id": session_id or self._session_id,
                    "turns": turns}, ARCHIVE_TIMEOUT)

    # -- tools: none here, by design (Hermes's MCP client carries them) ----
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return []

    def shutdown(self) -> None:
        return None


def register(ctx: Any) -> None:
    """Hermes's memory loader calls this and takes the provider."""
    ctx.register_memory_provider(BrethofBrainProvider())
