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

ENDPOINT = os.environ.get("BRETHOF_MIND_ENDPOINT", "https://api.brethof.cloud").rstrip("/")
API_KEY = os.environ.get("BRETHOF_MIND_API_KEY", "").strip()
PROJECT = (os.environ.get("HERMES_MEMORY_PROJECT", "global") or "global").strip()
USER_AGENT = "brethof-mind-hermes/1.0"          # a real UA (the edge challenges generic ones)
_PROJECT_RE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")


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
        return bool(API_KEY)

    def get_config_schema(self) -> List[Dict[str, Any]]:
        return []  # all config via env

    # -- HTTP to the data plane (stdlib only) -------------------------------
    def _post(self, path: str, payload: dict, timeout: float = 20.0) -> dict:
        req = urllib.request.Request(
            ENDPOINT + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {API_KEY}",
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
            env = self._post("/v1/hooks/session-start", {"project": PROJECT})
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
                    "project": PROJECT, "prompt": query,
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

        def _sync():
            try:
                self._post("/v1/hooks/stop", {"project": PROJECT,
                                              "session_id": sid, "turns": turns})
            except Exception as e:
                logger.warning("brethofmind-cloud sync_turn failed: %s", e)

        prev = self._sync_thread
        if prev and prev.is_alive():
            prev.join(timeout=5.0)
        self._sync_thread = threading.Thread(
            target=_sync, daemon=True, name="brethofmind-cloud-sync")
        self._sync_thread.start()

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
                return json.dumps({"result": self._mcp("semantic_search",
                                                       query_text=q, project=PROJECT, top_k=k)})
            if tool_name == "brethofmind_recall":
                q = (args.get("query") or "").strip()
                if not q:
                    return tool_error("Missing required parameter: query")
                k = max(1, min(int(args.get("top_k", 8)), 25))
                return json.dumps({"result": self._mcp("search_chat",
                                                       query_text=q, project=PROJECT, top_k=k)})
            if tool_name == "brethofmind_save":
                title = (args.get("title") or "").strip()
                content = (args.get("content") or "").strip()
                if not title or not content:
                    return tool_error("brethofmind_save needs both title and content")
                proj = (args.get("project") or PROJECT).strip()
                if not _PROJECT_RE.match(proj):
                    return tool_error(f"invalid project '{proj}'")
                rid = self._record_id(args.get("record_id", ""), title, content)
                out = self._mcp("save_memory", project=proj, record_id=rid,
                                memory_type=args.get("memory_type", "note"),
                                title=title, content=content)
                return json.dumps({"result": out})
            if tool_name == "brethofmind_delete":
                proj = (args.get("project") or "").strip()
                rid = re.sub(r"[^a-zA-Z0-9_]+", "_", (args.get("record_id") or "").strip()).strip("_")
                if not proj or not rid:
                    return tool_error("brethofmind_delete needs project and record_id")
                if not _PROJECT_RE.match(proj) or proj.endswith(("_chat", "_commit")):
                    return tool_error("cannot delete from that table")
                self._mcp("query_raw", sql=f"DELETE {proj}:`{rid}`;")
                return json.dumps({"result": f"Deleted {proj}:{rid}"})
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
