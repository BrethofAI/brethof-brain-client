"""Programmatic API — use brethof-mind cloud from any Python code.

The Claude Code hooks and MCP wiring cover agents that speak those protocols.
For everything else (a Hermes toolset, an OpenClaw job, a plain script, a test),
``MindClient`` is a small typed wrapper over the same remote endpoints:

    from brethof_mind_client import MindClient
    mind = MindClient()                 # reads ~/.brethof-mind/config.json / env
    print(mind.recall("how do we deploy the website?"))
    mind.save_memory("global", "note_x", "reference", "Title", "Body [[link]]")

The 15 memory tools are called over the remote MCP endpoint (/v1/mcp, stateless
JSON-RPC ``tools/call``); ``archive_turns`` and ``usage`` hit the hook/usage
endpoints. Every tool returns the server's text; ``query_raw``/``usage`` return
parsed JSON. Raises :class:`~brethof_mind_client.client.ClientError` on transport
failure and :class:`MindToolError` when the server flags a tool error.
"""
from __future__ import annotations

import json
from typing import Any, Optional

from .client import Client, ClientError
from .config import Config

MCP_PATH = "/v1/mcp"


class MindToolError(RuntimeError):
    """The MCP server returned isError=true (or a JSON-RPC error) for a tool."""


class MindClient:
    def __init__(self, config: Optional[Config] = None, timeout: float = 30.0):
        self.cfg = config or Config.load()
        if not self.cfg.configured():
            raise ClientError("no API key configured (set BRETHOF_MIND_API_KEY "
                              "or run: brethof-mind setup)")
        self._http = Client(self.cfg, timeout=timeout)
        self._id = 0

    # ── MCP tool plumbing ───────────────────────────────────────────────────

    def call_tool(self, name: str, arguments: dict | None = None,
                  **kwargs: Any) -> str:
        """Invoke a memory tool; return its text result.

        Tool arguments go in **kwargs, or in the ``arguments`` dict when a
        tool's own parameter collides with this method's signature — the
        ``graph`` tool takes a parameter literally called ``name``, which
        kwargs cannot express (found 2026-08-08).
        """
        self._id += 1
        merged = {**(arguments or {}), **kwargs}
        payload = {"jsonrpc": "2.0", "id": self._id, "method": "tools/call",
                   "params": {"name": name,
                              "arguments": {k: v for k, v in merged.items()
                                            if v is not None}}}
        resp = self._http.post(MCP_PATH, payload)
        if "error" in resp:
            raise MindToolError(resp["error"].get("message", "tool error"))
        result = resp.get("result") or {}
        if result.get("isError"):
            texts = "; ".join(c.get("text", "") for c in result.get("content", []))
            raise MindToolError(texts or "tool error")
        content = result.get("content") or []
        return "\n".join(c.get("text", "") for c in content if c.get("type") == "text")

    def list_tools(self) -> list[dict]:
        self._id += 1
        resp = self._http.post(MCP_PATH, {"jsonrpc": "2.0", "id": self._id,
                                          "method": "tools/list", "params": {}})
        return (resp.get("result") or {}).get("tools", [])

    # ── the 15 tools (thin, typed) ──────────────────────────────────────────

    def recall(self, query_text: str, project: str = None, top_k: int = None,
               include_chat: bool = None) -> str:
        return self.call_tool("recall", query_text=query_text, project=project,
                              top_k=top_k, include_chat=include_chat)

    def semantic_search(self, query_text: str, project: str = None,
                        top_k: int = None) -> str:
        return self.call_tool("semantic_search", query_text=query_text,
                              project=project, top_k=top_k)

    def search_memory(self, query_text: str, project: str = None) -> str:
        return self.call_tool("search_memory", query_text=query_text, project=project)

    def search_chat(self, query_text: str, project: str = None, top_k: int = None) -> str:
        return self.call_tool("search_chat", query_text=query_text, project=project,
                              top_k=top_k)

    def search_chat_text(self, query_text: str, project: str = None,
                         top_k: int = None) -> str:
        return self.call_tool("search_chat_text", query_text=query_text,
                              project=project, top_k=top_k)

    def get_memory(self, record_id: str, project: str = None) -> str:
        return self.call_tool("get_memory", record_id=record_id, project=project)

    def list_memory(self, project: str, memory_type: str = None, limit: int = None) -> str:
        return self.call_tool("list_memory", project=project, memory_type=memory_type,
                              limit=limit)

    def recent_records(self, project: str, days: int = None, where: str = None,
                       limit: int = None) -> str:
        return self.call_tool("recent_records", project=project, days=days,
                              where=where, limit=limit)

    def query_raw(self, sql: str) -> Any:
        out = self.call_tool("query_raw", sql=sql)
        try:
            return json.loads(out)
        except Exception:
            return out

    def memory_health(self, project: str = None) -> str:
        return self.call_tool("memory_health", project=project)

    def save_memory(self, project: str, record_id: str, memory_type: str,
                    title: str, content: str) -> str:
        return self.call_tool("save_memory", project=project, record_id=record_id,
                              memory_type=memory_type, title=title, content=content)

    def save_record(self, project: str, record_id: str, fields: Any,
                    embed_text: str = None) -> str:
        if not isinstance(fields, str):
            fields = json.dumps(fields)
        return self.call_tool("save_record", project=project, record_id=record_id,
                              fields=fields, embed_text=embed_text)

    def supersede_memory(self, project: str, old_record_id: str,
                         new_record_id: str) -> str:
        return self.call_tool("supersede_memory", project=project,
                              old_record_id=old_record_id, new_record_id=new_record_id)

    def save_commit(self, project: str, commit_hash: str, message: str,
                    files_changed: str, branch: str = None) -> str:
        return self.call_tool("save_commit", project=project, commit_hash=commit_hash,
                              message=message, files_changed=files_changed, branch=branch)

    def load_project(self, project: str) -> str:
        return self.call_tool("load_project", project=project)

    # ── non-MCP endpoints ───────────────────────────────────────────────────

    def usage(self) -> dict:
        """Per-tenant usage vs caps (measurement view; nothing blocked while
        enforcement is off)."""
        return self._http.get("/v1/usage")

    def archive_turns(self, project: str, session_id: str, turns: list[dict]) -> dict:
        """Archive conversation turns into the chat store. Each turn:
        {index:int, line_type:'user'|'assistant', text:str, timestamp?:iso,
         embed?:bool}. Returns the server envelope ({status, archived, ...})."""
        return self._http.post("/v1/hooks/stop",
                               {"project": project, "session_id": session_id,
                                "turns": turns})
