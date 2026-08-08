"""Programmatic API — use brethof-mind cloud from any Python code.

The Claude Code hooks and MCP wiring cover agents that speak those protocols.
For everything else (a Hermes toolset, an OpenClaw job, a plain script, a test),
``MindClient`` is a small typed wrapper over the same remote endpoints:

    from brethof_mind_client import MindClient
    mind = MindClient()                 # reads ~/.brethof-mind/config.json / env
    print(mind.search_memory("how do we deploy the website?"))
    mind.save_project("Deploys go out via `git push vps main`.", "website")

The customer memory tools are called over the remote MCP endpoint (/v1/mcp,
stateless JSON-RPC ``tools/call``); ``archive_turns`` and ``usage`` hit the
hook/usage endpoints. Every tool returns the server's text; ``usage`` returns
parsed JSON. Raises :class:`~brethof_mind_client.client.ClientError` on
transport failure and :class:`MindToolError` when the server flags a tool
error.

SAVES ARE INTENTS, NOT FILING INSTRUCTIONS. You state the fact; the service
picks the id, merges duplicates, and retires what the fact contradicts — and
does it asynchronously, so a save returns before the record is searchable.
Poll ``search_memory`` if you need to see it land.
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

    # ── the customer surface, thin and typed ────────────────────────────────
    #
    # REWRITTEN 2026-08-08. Every method here used to name an OWNER-tier tool
    # (recall, save_memory, save_record, query_raw, semantic_search,
    # search_chat…). Those tools do not exist for a customer key, so this —
    # the documented programmatic API for "any Python agent" — failed with
    # "unknown tool" on almost every call the moment a real customer used it.
    # A clean-room container install with a freshly provisioned account is
    # what finally said so out loud.
    #
    # The rule that keeps it fixed: this library speaks the CUSTOMER surface
    # ONLY. It ships to customers and the repo goes public; our admin
    # vocabulary has no business in it. The conformance suite asserts every
    # name below still exists on the live tools/list.

    # -- read -----------------------------------------------------------
    def search_memory(self, query_text: str, project: str = None,
                      top_k: int = None) -> str:
        """Saved memory — the curated current truth. Start here."""
        return self.call_tool("search_memory", query_text=query_text,
                              project=project, top_k=top_k)

    def search_history(self, query_text: str, project: str = None,
                       top_k: int = None) -> str:
        """The full raw conversation archive, for detail saved memory does
        not hold."""
        return self.call_tool("search_history", query_text=query_text,
                              project=project, top_k=top_k)

    def get_memory(self, record_id: str, project: str = None) -> str:
        return self.call_tool("get_memory", record_id=record_id, project=project)

    def list_memory(self, project: str, memory_type: str = None,
                    limit: int = None) -> str:
        return self.call_tool("list_memory", project=project,
                              memory_type=memory_type, limit=limit)

    def list_projects(self) -> str:
        return self.call_tool("list_projects")

    def list_rules(self, project: str = None) -> str:
        return self.call_tool("list_rules", project=project)

    def graph(self, name: str, project: str = None) -> str:
        """A person / tool / service / decision in the knowledge graph.

        Uses the ``arguments`` dict, not kwargs: this tool's own parameter is
        called ``name``, which would collide with call_tool's first parameter
        and raise TypeError instead of calling the tool. The identical trap
        bit the OpenClaw wrapper the same day."""
        return self.call_tool("graph", {"name": name, "project": project})

    def session_context(self, project: str) -> str:
        """The full session-start briefing for a project."""
        return self.call_tool("session_context", project=project)

    # -- write (INTENTS: the service does the filing) --------------------
    def save_project(self, content: str, project: str) -> str:
        """Remember one fact about a project. State it self-contained; the
        service decides placement, id, dedupe and what it supersedes."""
        return self.call_tool("save_project", content=content, project=project)

    def save_general(self, content: str) -> str:
        """Remember one fact true across all projects."""
        return self.call_tool("save_general", content=content)

    def save_project_rule(self, content: str, project: str) -> str:
        """LAW for one project: it changes what an agent DOES every session
        there. A fact or measurement is knowledge — use save_project."""
        return self.call_tool("save_project_rule", content=content,
                              project=project)

    def save_general_rule(self, content: str) -> str:
        """LAW for every project. Costly by design — it loads into every
        session and teaches every project's curator. Use sparingly."""
        return self.call_tool("save_general_rule", content=content)

    def delete_memory(self, record_id: str, project: str = None) -> str:
        """Delete one saved record (works for rules too, project='rules').
        The conversation archive is never touched."""
        return self.call_tool("delete_memory", record_id=record_id,
                              project=project)

    # -- project lifecycle -----------------------------------------------
    def add_project(self, project: str, purpose: str, rules: str = None) -> str:
        """Create a project AND tell memory what it is for. `purpose` is
        mandatory by design — one owner sentence teaches this project's
        curator more than anything it can infer alone."""
        return self.call_tool("add_project", project=project, purpose=purpose,
                              rules=rules)

    def delete_project(self, project: str, confirm: str) -> str:
        """DESTRUCTIVE. `confirm` must equal the project name. Conversation
        history is not affected."""
        return self.call_tool("delete_project", project=project,
                              confirm=confirm)

    def cleanup_history(self, project: str, older_than_days: int = None,
                        mode: str = None, confirm: str = None) -> str:
        """DESTRUCTIVE past a 90-day floor. Without `confirm` this returns a
        PREVIEW only."""
        return self.call_tool("cleanup_history", project=project,
                              older_than_days=older_than_days, mode=mode,
                              confirm=confirm)

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
