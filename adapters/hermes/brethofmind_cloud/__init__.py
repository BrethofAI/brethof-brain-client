"""brethof-mind CLOUD memory provider for Hermes.

The cloud counterpart of the local ``brethofmind`` provider. The local one talks
straight to a self-hosted SurrealDB with root creds and embeds turns itself; a
cloud TENANT can do none of that (no root, no direct DB, no server code). This
provider therefore routes every hook through the brethof-mind cloud HTTP API
with your API key — the server does isolation, embedding, recall, and metering.

The MemoryProvider hooks map onto the same endpoints the Claude Code client uses:
  initialize()          -> POST /v1/hooks/session-start   (brain block for the prompt)
  system_prompt_block() -> the cached brain block
  queue_prefetch()/prefetch() -> POST /v1/hooks/prompt-submit (ambient recall)
  sync_turn()           -> POST /v1/hooks/stop             (archive the turn)
  brethofmind_* tools   -> POST /v1/mcp                    (recall/search/save/delete)

Drop this file into ``$HERMES_HOME/plugins/brethofmind_cloud/`` and activate with
``memory.provider: brethofmind_cloud``. Stdlib only — no dependency on the
brethof-mind-client package, so it survives image rebuilds like its local twin.

Config (env):
  BRETHOF_MIND_API_KEY   your key (required; bm_live_… / bm_test_…)
  BRETHOF_MIND_ENDPOINT  data plane (default https://api.brethof.cloud)
  HERMES_MEMORY_PROJECT  project this session reads/archives to (default 'global')
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

try:
    from tools.registry import tool_error
except Exception:  # import surface may differ for a user plugin
    def tool_error(msg: str) -> str:
        return json.dumps({"error": msg})

USER_AGENT = "brethof-mind-hermes/1.0"          # a real UA (the edge challenges generic ones)
_PROJECT_RE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")

# Config is resolved at CALL time, not import time, reading os.environ first
# and falling back to parsing $HERMES_HOME/.env ourselves. Rationale: not every
# Hermes entrypoint loads the user .env before plugins import (and a module-
# level snapshot freezes whatever half-loaded state existed at import), so
# self-resolving keeps the provider correct in all of them.
_ENV_FILE_CACHE: Optional[Dict[str, str]] = None


def _candidate_env_files() -> List["os.PathLike"]:
    """.env files to consult, most-authoritative last. The plugin's OWN install
    home (``…/hermes/plugins/brethofmind_cloud/__init__.py`` -> parents[2]) is
    the canonical one and does not depend on HERMES_HOME being set."""
    files = []
    try:
        from hermes_constants import get_hermes_home
        files.append(get_hermes_home() / ".env")
    except Exception:
        pass
    try:
        import pathlib
        files.append(pathlib.Path(__file__).resolve().parents[2] / ".env")
    except Exception:
        pass
    return files


def _hermes_env_file() -> Dict[str, str]:
    global _ENV_FILE_CACHE
    if _ENV_FILE_CACHE is not None:
        return _ENV_FILE_CACHE
    data: Dict[str, str] = {}
    for envf in _candidate_env_files():
        try:
            if not envf.exists():
                continue
            for raw in envf.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip().strip('"').strip("'")  # later file wins
        except Exception:
            pass
    _ENV_FILE_CACHE = data
    return data


def _cfg(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    if v and v.strip():
        return v.strip()
    v = _hermes_env_file().get(name)
    return v.strip() if v and v.strip() else default


def _endpoint() -> str:
    return _cfg("BRETHOF_MIND_ENDPOINT", "https://api.brethof.cloud").rstrip("/")


def _api_key() -> str:
    return _cfg("BRETHOF_MIND_API_KEY", "")


def _project() -> str:
    return _cfg("HERMES_MEMORY_PROJECT", "global") or "global"


class BrethofMindCloudProvider(MemoryProvider):
    """Routes Hermes memory through brethof-mind cloud (api.brethof.cloud)."""

    def __init__(self) -> None:
        self._session_id = ""
        self._brain_block = ""
        self._prefetch_result = ""
        self._prefetch_lock = threading.Lock()
        self._prefetch_thread: Optional[threading.Thread] = None
        self._sync_thread: Optional[threading.Thread] = None
        self._next_index = 0
        self._rpc_id = 0

    @property
    def name(self) -> str:
        return "brethofmind-cloud"

    def is_available(self) -> bool:
        # Ready iff a key is configured. Per the ABC, no network call here;
        # hooks below degrade gracefully if the service is unreachable.
        return bool(_api_key())

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return []  # all config via env

    # -- HTTP to the data plane (stdlib only) -------------------------------
    def _post(self, path: str, payload: dict, timeout: float = 20.0) -> dict:
        req = urllib.request.Request(
            _endpoint() + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {_api_key()}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "X-BM-Client": "hermes-provider/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
        return json.loads(body or b"{}")

    _tool_names_cache: Optional[set] = None

    def _tool_names(self) -> set:
        """The tool names THIS key's tier actually has — asked once from
        tools/list, cached for the process. The v2 server resolves a
        toolset per key (full-access keys see the classic tools, panel
        keys see the intent tools), so the provider adapts instead of
        assuming: same brethofmind_* interface either way."""
        if self._tool_names_cache is not None:
            return self._tool_names_cache
        try:
            self._rpc_id += 1
            resp = self._post("/v1/mcp", {
                "jsonrpc": "2.0", "id": self._rpc_id, "method": "tools/list",
                "params": {}})
            names = {t.get("name") for t in
                     (resp.get("result") or {}).get("tools", [])}
        except Exception as e:  # noqa: BLE001 — degrade to classic names
            logger.warning("brethofmind-cloud tools/list failed: %s", e)
            names = set()
        self._tool_names_cache = names
        return names

    def _pick(self, *candidates: str) -> str:
        names = self._tool_names()
        for c in candidates:
            if c in names:
                return c
        return candidates[0]           # server answers unknown-tool cleanly

    def _mcp(self, tool: str, **arguments: Any) -> str:
        """Call one of the 15 memory tools; return its text result. Raises on
        a tool/JSON-RPC error."""
        self._rpc_id += 1
        resp = self._post("/v1/mcp", {
            "jsonrpc": "2.0", "id": self._rpc_id, "method": "tools/call",
            "params": {"name": tool,
                       "arguments": {k: v for k, v in arguments.items() if v is not None}},
        })
        if "error" in resp:
            raise RuntimeError(resp["error"].get("message", "tool error"))
        result = resp.get("result") or {}
        content = result.get("content") or []
        text = "\n".join(c.get("text", "") for c in content if c.get("type") == "text")
        if result.get("isError"):
            raise RuntimeError(text or "tool error")
        return text

    # -- lifecycle ----------------------------------------------------------
    def initialize(self, session_id: str, **kwargs) -> None:
        self._session_id = session_id or ""
        self._next_index = 0
        try:
            env = self._post("/v1/hooks/session-start", {"project": _project()})
            self._brain_block = env.get("injection") or ""
        except Exception as e:  # never break a session on a hiccup
            logger.warning("brethofmind-cloud: session-start failed: %s", e)
            self._brain_block = ""

    def system_prompt_block(self) -> str:
        return self._brain_block

    # -- recall (prefetch) --------------------------------------------------
    def prefetch(self, query: str, *, session_id: str = "") -> str:
        t = self._prefetch_thread
        if t and t.is_alive():
            t.join(timeout=3.0)
        with self._prefetch_lock:
            result = self._prefetch_result
            self._prefetch_result = ""
        return result

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        if not query or not query.strip():
            return

        def _run():
            try:
                env = self._post("/v1/hooks/prompt-submit", {
                    "project": _project(), "prompt": query,
                    "session_id": session_id or self._session_id})
                blob = env.get("injection") or ""
                if blob:
                    with self._prefetch_lock:
                        self._prefetch_result = blob
            except Exception as e:
                logger.debug("brethofmind-cloud prefetch failed: %s", e)

        self._prefetch_thread = threading.Thread(
            target=_run, daemon=True, name="brethofmind-cloud-prefetch")
        self._prefetch_thread.start()

    # -- archive (sync_turn) ------------------------------------------------
    def sync_turn(self, user_content: str, assistant_content: str, *,
                  session_id: str = "", messages=None) -> None:
        proj = _project()
        sid = session_id or self._session_id
        turns = []
        if user_content and user_content.strip():
            turns.append({"index": self._next_index, "line_type": "user",
                          "text": user_content, "embed": True})
            self._next_index += 1
        if assistant_content and assistant_content.strip():
            turns.append({"index": self._next_index, "line_type": "assistant",
                          "text": assistant_content, "embed": True})
            self._next_index += 1
        if not turns:
            return

        # Archive SYNCHRONOUSLY. Hermes' memory manager already dispatches
        # sync_turn on its own background worker (which lives with the agent),
        # so blocking here does not stall the user's response — and it avoids
        # the fire-and-forget-daemon-thread bug where the thread was torn down
        # before the (slow, server-embedding) POST completed, so turns were
        # silently never persisted.
        try:
            self._post("/v1/hooks/stop",
                       {"project": proj, "session_id": sid, "turns": turns})
        except Exception as e:
            logger.warning("brethofmind-cloud sync_turn failed: %s", e)

    # -- deliberate tools (same names/shape as the local provider) ----------
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        return [
            {"name": "brethofmind_search",
             "description": ("Search curated memory across your projects "
                             "(decisions, conventions, runbooks, status) by meaning."),
             "parameters": {"type": "object", "properties": {
                 "query": {"type": "string", "description": "What to recall."},
                 "top_k": {"type": "integer", "description": "Max results (default 8)."}},
                 "required": ["query"]}},
            {"name": "brethofmind_recall",
             "description": "Search past sessions (the chat archive) for what was discussed before.",
             "parameters": {"type": "object", "properties": {
                 "query": {"type": "string"}, "top_k": {"type": "integer"}},
                 "required": ["query"]}},
            {"name": "brethofmind_save",
             "description": ("Write a durable record into a project's curated memory. "
                             "Pass a stable record_id to update-in-place; omit for a new one."),
             "parameters": {"type": "object", "properties": {
                 "title": {"type": "string"}, "content": {"type": "string"},
                 "memory_type": {"type": "string", "description":
                                 "decision | architecture | project_status | bug | reference | note"},
                 "project": {"type": "string", "description": "Target project (default the session's)."},
                 "record_id": {"type": "string", "description": "Stable id to UPSERT (optional)."}},
                 "required": ["title", "content"]}},
            {"name": "brethofmind_delete",
             "description": "Delete a stale curated record by id (cannot touch *_chat archives).",
             "parameters": {"type": "object", "properties": {
                 "project": {"type": "string"}, "record_id": {"type": "string"}},
                 "required": ["project", "record_id"]}},
        ]

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        try:
            if tool_name == "brethofmind_search":
                q = (args.get("query") or "").strip()
                if not q:
                    return tool_error("Missing required parameter: query")
                k = max(1, min(int(args.get("top_k", 8)), 25))
                return json.dumps({"result": self._mcp(
                    self._pick("semantic_search", "search_memory"),
                    query_text=q, project=_project(), top_k=k)})
            if tool_name == "brethofmind_recall":
                q = (args.get("query") or "").strip()
                if not q:
                    return tool_error("Missing required parameter: query")
                k = max(1, min(int(args.get("top_k", 8)), 25))
                return json.dumps({"result": self._mcp(
                    self._pick("search_chat", "search_history"),
                    query_text=q, project=_project(), top_k=k)})
            if tool_name == "brethofmind_save":
                title = (args.get("title") or "").strip()
                content = (args.get("content") or "").strip()
                if not title or not content:
                    return tool_error("brethofmind_save needs both title and content")
                proj = (args.get("project") or _project()).strip()
                if not _PROJECT_RE.match(proj):
                    return tool_error(f"invalid project '{proj}'")
                if "save_memory" in self._tool_names():
                    # Full-access key: classic upsert with a stable id.
                    rid = self._record_id(args.get("record_id", ""), title,
                                          content)
                    out = self._mcp("save_memory", project=proj,
                                    record_id=rid,
                                    memory_type=args.get("memory_type",
                                                         "note"),
                                    title=title, content=content)
                else:
                    # Panel key: an INTENT — the memory service files it
                    # (placement, dedupe, supersede). record_id and
                    # memory_type are the service's business, not ours.
                    out = self._mcp("save_project",
                                    content=f"{title}: {content}",
                                    project=proj)
                return json.dumps({"result": out})
            if tool_name == "brethofmind_delete":
                proj = (args.get("project") or "").strip()
                rid = re.sub(r"[^a-zA-Z0-9_]+", "_", (args.get("record_id") or "").strip()).strip("_")
                if not proj or not rid:
                    return tool_error("brethofmind_delete needs project and record_id")
                if not _PROJECT_RE.match(proj) or proj.endswith(("_chat", "_commit")):
                    return tool_error("cannot delete from that table")
                # v2: the id-scoped delete tool on BOTH tiers — it refuses
                # the chat archive by construction. (The old path here was
                # a query_raw with SurrealDB syntax: doubly dead on v2,
                # where query_raw is read-only Postgres.)
                out = self._mcp("delete_memory", project=proj, record_id=rid)
                return json.dumps({"result": out})
        except Exception as e:  # noqa: BLE001
            return tool_error(f"brethofmind-cloud error: {e}")
        return tool_error(f"Unknown tool: {tool_name}")

    @staticmethod
    def _record_id(record_id: str, title: str, content: str) -> str:
        if record_id and record_id.strip():
            return re.sub(r"[^a-zA-Z0-9_]+", "_", record_id.strip()).strip("_")[:60] or "note"
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:40] or "note"
        return slug + "_" + hashlib.sha1((title + content).encode()).hexdigest()[:8]

    # -- optional hooks -----------------------------------------------------
    def on_pre_compress(self, messages):
        return ""  # turns already archived live via sync_turn

    def on_session_end(self, messages):
        return None

    def shutdown(self) -> None:
        for t in (self._prefetch_thread, self._sync_thread):
            if t and t.is_alive():
                t.join(timeout=5.0)


def register(ctx) -> None:
    """Register brethof-mind cloud as the active memory provider."""
    ctx.register_memory_provider(BrethofMindCloudProvider())
