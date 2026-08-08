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
  brethofmind_* tools   -> POST /v1/mcp                    (search/save/rule/delete)

Drop this file into ``$HERMES_HOME/plugins/brethofmind_cloud/`` and activate with
``memory.provider: brethofmind_cloud``. Stdlib only — no dependency on the
brethof-mind-client package, so it survives image rebuilds like its local twin.

Config (env):
  BRETHOF_MIND_API_KEY   your key (required; bm_live_… / bm_test_…)
  BRETHOF_MIND_ENDPOINT  data plane (default https://api.brethof.cloud)
  HERMES_MEMORY_PROJECT  project this session reads/archives to (default 'global')
"""
from __future__ import annotations

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
# Mirrors the SERVICE's project-name rule exactly (32 chars). It was 16 here
# until 2026-08-08, so a legal name the service accepts — anything 17-32 chars
# — was refused by the plugin with a confusing "invalid project". A client-side
# validator that is stricter than the server is a bug, not extra safety.
_PROJECT_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

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

    def _mcp(self, tool: str, **arguments: Any) -> str:
        """Call one memory tool on the customer surface; return its text
        result. Raises on a tool/JSON-RPC error."""
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

    # -- deliberate tools: FULL customer-surface parity ---------------------
    # An agent running on Hermes must be able to do everything an agent on any
    # other platform can. Until 2026-08-08 this wrapper exposed 5 of the
    # service's 16 customer tools: no project lifecycle (create / list /
    # delete), no way to browse or read a curated record, no rule listing, no
    # graph, no history cleanup. Those were not "untested" — they were
    # MISSING, and a half-a-product plugin is worse than none.
    #
    # Spec table, not an if-ladder: adding a service tool is one row, so the
    # next surface change cannot quietly skip this adapter (the conformance
    # suite asserts every row still resolves to a live customer tool).
    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        s = lambda t: {"type": "string"}                        # noqa: E731
        return [
            {"name": "brethofmind_search",
             "description": ("Search saved memory — the curated current truth "
                             "(facts, decisions, preferences) — by meaning."),
             "parameters": {"type": "object", "properties": {
                 "query": {"type": "string", "description": "What to recall."},
                 "top_k": {"type": "integer", "description": "Max results (default 8)."},
                 "project": {"type": "string", "description": "Search one project (default the session's)."}},
                 "required": ["query"]}},
            {"name": "brethofmind_recall",
             "description": ("Search past sessions (the full raw conversation "
                             "history) for what was discussed before. Use when "
                             "saved memory does not hold the detail."),
             "parameters": {"type": "object", "properties": {
                 "query": {"type": "string"}, "top_k": {"type": "integer"},
                 "project": s(1)}, "required": ["query"]}},
            {"name": "brethofmind_save",
             "description": ("Remember one fact. State it complete and "
                             "standalone; the memory service files it — "
                             "placement, dedupe and superseding are its job, "
                             "not yours."),
             "parameters": {"type": "object", "properties": {
                 "content": {"type": "string", "description":
                             "The fact, self-contained (names, dates, numbers)."},
                 "project": {"type": "string", "description":
                             "Project it belongs to (default the session's); "
                             "omit and set general=true for a cross-project fact."},
                 "general": {"type": "boolean", "description":
                             "True = not tied to one project."}},
                 "required": ["content"]}},
            {"name": "brethofmind_save_rule",
             "description": ("Save a RULE — a standing convention the agent "
                             "must follow every session without looking it "
                             "up. THE TEST: does it change behavior every "
                             "session? A fact, config or measurement is NOT "
                             "a rule — use brethofmind_save for those."),
             "parameters": {"type": "object", "properties": {
                 "content": {"type": "string", "description": "The rule, one clear statement."},
                 "scope": {"type": "string", "description":
                           "'project' (default) = law in this project only; "
                           "'general' = law in every project (costly — use sparingly)."},
                 "project": {"type": "string", "description": "Project for scope='project'."}},
                 "required": ["content"]}},
            {"name": "brethofmind_delete",
             "description": ("Delete ONE saved record that is wrong or dead, "
                             "by its id. Works for rules too (project "
                             "'rules'). Conversation history is never touched."),
             "parameters": {"type": "object", "properties": {
                 "project": s(1), "record_id": s(1)},
                 "required": ["project", "record_id"]}},
            {"name": "brethofmind_list",
             "description": "Browse a project's saved memory — ids and titles.",
             "parameters": {"type": "object", "properties": {
                 "project": s(1), "limit": {"type": "integer"}},
                 "required": []}},
            {"name": "brethofmind_get",
             "description": "Read ONE saved memory in full, by its id.",
             "parameters": {"type": "object", "properties": {
                 "record_id": s(1), "project": s(1)},
                 "required": ["record_id"]}},
            {"name": "brethofmind_rules",
             "description": ("See the saved rules — all of them, or those "
                             "active for one project."),
             "parameters": {"type": "object", "properties": {"project": s(1)},
                            "required": []}},
            {"name": "brethofmind_projects",
             "description": "List the projects in memory and how many memories each holds.",
             "parameters": {"type": "object", "properties": {}, "required": []}},
            {"name": "brethofmind_new_project",
             "description": ("Create a project and tell memory what it is FOR. "
                             "purpose is required — one or two sentences that "
                             "teach this project's memory what matters here "
                             "from day one."),
             "parameters": {"type": "object", "properties": {
                 "project": s(1),
                 "purpose": {"type": "string", "description":
                             "What this project IS and what to remember about it."},
                 "rules": {"type": "string", "description":
                           "Optional: what to always record / never record."}},
                 "required": ["project", "purpose"]}},
            {"name": "brethofmind_delete_project",
             "description": ("DESTRUCTIVE: delete everything saved under one "
                             "project. Requires confirm to equal the project "
                             "name. Conversation history is not affected."),
             "parameters": {"type": "object", "properties": {
                 "project": s(1),
                 "confirm": {"type": "string", "description":
                             "Must equal the project name, typed again."}},
                 "required": ["project", "confirm"]}},
            {"name": "brethofmind_graph",
             "description": ("Look something up in the knowledge graph — a "
                             "person, tool, service or decision: what it is, "
                             "its status (superseded = a dead end), other "
                             "names for it, and when it came up."),
             "parameters": {"type": "object", "properties": {
                 "name": s(1), "project": s(1)}, "required": ["name"]}},
            {"name": "brethofmind_context",
             "description": ("The full session-start briefing for a project "
                             "(rules, projects, state, open loops). Use to "
                             "refresh mid-session."),
             "parameters": {"type": "object", "properties": {"project": s(1)},
                            "required": []}},
            {"name": "brethofmind_cleanup_history",
             "description": ("DESTRUCTIVE: remove one project's conversation "
                             "history older than a cutoff (minimum 90 days). "
                             "Shows a preview first; only acts when confirm "
                             "equals the project name. Saved memories are "
                             "never touched."),
             "parameters": {"type": "object", "properties": {
                 "project": s(1), "older_than_days": {"type": "integer"},
                 "mode": {"type": "string", "description":
                          "'summarize' saves a compact summary before removal; "
                          "plain delete is free."},
                 "confirm": s(1)}, "required": ["project"]}},
        ]

    def handle_tool_call(self, tool_name: str, args: dict, **kwargs) -> str:
        def proj_arg(default_to_session: bool = True) -> str:
            p = (args.get("project") or
                 (_project() if default_to_session else "")).strip().lower()
            return p

        try:
            if tool_name in ("brethofmind_search", "brethofmind_recall"):
                q = (args.get("query") or "").strip()
                if not q:
                    return tool_error("Missing required parameter: query")
                k = max(1, min(int(args.get("top_k", 8)), 25))
                tool = ("search_memory" if tool_name == "brethofmind_search"
                        else "search_history")
                return json.dumps({"result": self._mcp(
                    tool, query_text=q, project=proj_arg(), top_k=k)})

            if tool_name == "brethofmind_save":
                content = (args.get("content") or "").strip()
                title = (args.get("title") or "").strip()   # legacy callers
                if title:
                    content = f"{title}: {content}" if content else title
                if not content:
                    return tool_error("brethofmind_save needs content")
                # An INTENT — the memory service files it (placement, id,
                # dedupe, supersede are its business, not ours).
                if args.get("general"):
                    return json.dumps({"result": self._mcp("save_general",
                                                           content=content)})
                proj = proj_arg()
                if not _PROJECT_RE.match(proj):
                    return tool_error(f"invalid project '{proj}'")
                return json.dumps({"result": self._mcp(
                    "save_project", content=content, project=proj)})

            if tool_name == "brethofmind_save_rule":
                content = (args.get("content") or "").strip()
                if not content:
                    return tool_error("brethofmind_save_rule needs content")
                if (args.get("scope") or "project").strip() == "general":
                    return json.dumps({"result": self._mcp(
                        "save_general_rule", content=content)})
                proj = proj_arg()
                if not _PROJECT_RE.match(proj):
                    return tool_error(f"invalid project '{proj}'")
                return json.dumps({"result": self._mcp(
                    "save_project_rule", content=content, project=proj)})

            if tool_name == "brethofmind_delete":
                proj = proj_arg(default_to_session=False)
                rid = (args.get("record_id") or "").strip()
                if not proj or not rid:
                    return tool_error("brethofmind_delete needs project and record_id")
                if proj.endswith(("_chat", "_commit")):
                    return tool_error("conversation history cannot be deleted")
                # 'rules' is a real project here — deleting dead law is a
                # first-class customer action, not an edge case.
                if proj != "rules" and not _PROJECT_RE.match(proj):
                    return tool_error(f"invalid project '{proj}'")
                return json.dumps({"result": self._mcp(
                    "delete_memory", project=proj, record_id=rid)})

            if tool_name == "brethofmind_list":
                return json.dumps({"result": self._mcp(
                    "list_memory", project=proj_arg(),
                    limit=args.get("limit"))})

            if tool_name == "brethofmind_get":
                rid = (args.get("record_id") or "").strip()
                if not rid:
                    return tool_error("brethofmind_get needs record_id")
                return json.dumps({"result": self._mcp(
                    "get_memory", record_id=rid,
                    project=proj_arg(default_to_session=False) or None)})

            if tool_name == "brethofmind_rules":
                return json.dumps({"result": self._mcp(
                    "list_rules",
                    project=proj_arg(default_to_session=False) or None)})

            if tool_name == "brethofmind_projects":
                return json.dumps({"result": self._mcp("list_projects")})

            if tool_name == "brethofmind_new_project":
                proj = proj_arg(default_to_session=False)
                purpose = (args.get("purpose") or "").strip()
                if not proj or not purpose:
                    return tool_error("brethofmind_new_project needs project "
                                      "and purpose (purpose teaches memory "
                                      "what matters there)")
                return json.dumps({"result": self._mcp(
                    "add_project", project=proj, purpose=purpose,
                    rules=(args.get("rules") or "").strip() or None)})

            if tool_name == "brethofmind_delete_project":
                proj = proj_arg(default_to_session=False)
                confirm = (args.get("confirm") or "").strip().lower()
                if not proj:
                    return tool_error("brethofmind_delete_project needs project")
                if confirm != proj:
                    return tool_error(
                        f"refusing: confirm must equal the project name "
                        f"('{proj}') — this deletes everything saved there")
                return json.dumps({"result": self._mcp(
                    "delete_project", project=proj, confirm=confirm)})

            if tool_name == "brethofmind_graph":
                name = (args.get("name") or "").strip()
                if not name:
                    return tool_error("brethofmind_graph needs name")
                return json.dumps({"result": self._mcp(
                    "graph", name=name,
                    project=proj_arg(default_to_session=False) or None)})

            if tool_name == "brethofmind_context":
                return json.dumps({"result": self._mcp(
                    "session_context", project=proj_arg())})

            if tool_name == "brethofmind_cleanup_history":
                proj = proj_arg(default_to_session=False)
                if not proj:
                    return tool_error("brethofmind_cleanup_history needs project")
                return json.dumps({"result": self._mcp(
                    "cleanup_history", project=proj,
                    older_than_days=args.get("older_than_days"),
                    mode=(args.get("mode") or "").strip() or None,
                    confirm=(args.get("confirm") or "").strip() or None)})
        except Exception as e:  # noqa: BLE001
            return tool_error(f"brethofmind-cloud error: {e}")
        # Falling through means a tool was DECLARED but not dispatched — a
        # silent None here would look like success to the host. Say so.
        return tool_error(f"Unknown tool: {tool_name}")
        return tool_error(f"Unknown tool: {tool_name}")

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
