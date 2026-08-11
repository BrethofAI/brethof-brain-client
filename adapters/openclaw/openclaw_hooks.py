"""OpenClaw memory hooks — give an OpenClaw agent brethof-mind cloud memory.

OpenClaw has no native memory/hook system (unlike Claude Code's hooks or Hermes's
memory provider), so we add one: wrap the agent's run loop with ``MemorySession``,
which calls the three generic ``AgentHooks`` at the right lifecycle points —
inject memory into the system prompt at session start, prefetch relevant memory
before each model call, and archive each turn afterward.

This is deliberately model-agnostic: you supply the function that calls your LLM;
``MemorySession`` handles the memory. Every hook is fail-open, so wiring memory in
can never break an OpenClaw run.

    from openclaw_hooks import MemorySession

    sess = MemorySession(project="marketing", session_id=job_id,
                         base_system_prompt="You are OpenClaw, a marketing agent.")
    system_prompt = sess.start()                      # memory-augmented system prompt

    for user_msg in conversation:
        context = sess.build_context(user_msg)        # ambient recall to prepend
        reply = call_your_model(system_prompt, context, user_msg)
        sess.record(user_msg, reply)                  # archive the turn
"""
from __future__ import annotations

from brethof_mind_client import AgentHooks
from brethof_mind_client.client import Client


class MemorySession:
    """A thin memory wrapper for one OpenClaw agent session."""

    def __init__(self, project: str, session_id: str, base_system_prompt: str = ""):
        self.hooks = AgentHooks(project=project, session_id=session_id)
        self.base_system_prompt = base_system_prompt
        self._memory_block = ""
        self._http = Client(self.hooks.cfg, timeout=20.0)
        self._rpc_id = 0

    def start(self) -> str:
        """Call once at session start; returns the memory-augmented system prompt."""
        self._memory_block = self.hooks.session_start()
        return self.system_prompt()

    def system_prompt(self) -> str:
        if self._memory_block:
            return (self.base_system_prompt
                    + "\n\n# Long-term memory (brethof-mind)\n" + self._memory_block)
        return self.base_system_prompt

    def build_context(self, user_prompt: str) -> str:
        """Ambient recall relevant to this prompt — prepend to the turn's context.
        Empty when there's nothing to add."""
        return self.hooks.before_prompt(user_prompt)

    def record(self, user_prompt: str, assistant_reply: str) -> dict:
        """Archive a completed turn into long-term memory."""
        return self.hooks.archive(user_prompt, assistant_reply)

    # -- deliberate writes (the customer surface's two kinds) ---------------
    def _tool(self, tool, /, **arguments) -> str:
        # POSITIONAL-ONLY (the '/'): tool arguments are passed as **kwargs, and
        # the customer surface has tools whose OWN parameter is called 'name'
        # (graph). Without this, graph(name=...) collides with the dispatcher's
        # parameter and raises TypeError instead of calling the tool.
        self._rpc_id += 1
        resp = self._http.post("/v1/mcp", {
            "jsonrpc": "2.0", "id": self._rpc_id, "method": "tools/call",
            "params": {"name": tool, "arguments": {
                k: v for k, v in arguments.items() if v is not None}}})
        content = (resp.get("result") or {}).get("content") or []
        return "\n".join(c.get("text", "") for c in content
                         if c.get("type") == "text")

    def save_fact(self, content: str, project: str | None = None,
                  general: bool = False) -> str:
        """Remember one durable fact. State it self-contained; the memory
        service does the filing (placement, dedupe, superseding).
        ``general=True`` for a fact not tied to one project."""
        if general:
            return self._tool("save_general", content=content)
        return self._tool("save_project", content=content,
                          project=project or self.hooks.project)

    def save_rule(self, content: str, scope: str = "project",
                  project: str | None = None) -> str:
        """Save a RULE — a standing convention that binds every future
        session without being looked up. THE TEST: does it change what the
        agent DOES every session? Facts, configs and measurements are NOT
        rules — use :meth:`save_fact`. scope='general' makes it law in
        every project (costly; use sparingly)."""
        if scope == "general":
            return self._tool("save_general_rule", content=content)
        return self._tool("save_project_rule", content=content,
                          project=project or self.hooks.project)

    # -- the rest of the customer surface ----------------------------------
    # Full parity, added 2026-08-08: an OpenClaw agent must be able to do
    # everything an agent on any other platform can. Before this it could
    # only save — it could not read back a record, browse a project, list
    # its own rules, or manage the project lifecycle.
    def search(self, query: str, project: str | None = None,
               top_k: int = 8) -> str:
        """Search SAVED MEMORY — the curated current truth. Start here."""
        return self._tool("search_brain", query_text=query,
                          project=project or self.hooks.project, top_k=top_k)

    def search_history(self, query: str, project: str | None = None,
                       top_k: int = 8) -> str:
        """Search the FULL RAW conversation history — complete but unfiltered;
        use when saved memory does not hold the detail."""
        return self._tool("search_history", query_text=query,
                          project=project or self.hooks.project, top_k=top_k)

    def list_brain(self, project: str | None = None,
                    limit: int | None = None) -> str:
        """Browse a project's saved memory — ids and titles."""
        return self._tool("list_brain", project=project or self.hooks.project,
                          limit=limit)

    # Deprecated alias (pre-Brain name, 2026-08 rename) — existing OpenClaw
    # integrations keep working; the wire only speaks list_brain.
    list_memory = list_brain

    def get(self, record_id: str, project: str | None = None) -> str:
        """Read ONE saved memory in full, by id."""
        return self._tool("get_record", record_id=record_id, project=project)

    def list_rules(self, project: str | None = None) -> str:
        """The saved rules — all, or those active for one project."""
        return self._tool("list_rules", project=project)

    def list_projects(self) -> str:
        """Every project in this memory and how many memories each holds."""
        return self._tool("list_projects")

    def add_project(self, project: str, purpose: str,
                    rules: str | None = None) -> str:
        """Create a project AND tell memory what it is for. `purpose` is
        mandatory by design: one owner sentence teaches this project's
        curator what matters here, and beats anything it can infer alone."""
        return self._tool("add_project", project=project, purpose=purpose,
                          rules=rules)

    def delete_project(self, project: str, confirm: str) -> str:
        """DESTRUCTIVE — delete everything saved under one project. `confirm`
        must equal the project name; the guard is here as well as on the
        server so a mis-wired caller cannot wipe a project by accident.
        Conversation history is not affected."""
        if (confirm or "").strip().lower() != (project or "").strip().lower():
            return (f"Refusing: confirm must equal the project name "
                    f"('{project}') — this deletes everything saved there.")
        return self._tool("delete_project", project=project, confirm=confirm)

    def delete(self, project: str, record_id: str) -> str:
        """Delete ONE saved record (works for rules too, project='rules').
        The conversation archive is never touched."""
        return self._tool("delete_record", project=project,
                          record_id=record_id)

    def graph(self, name: str, project: str | None = None) -> str:
        """Look up a person / tool / service / decision in the knowledge
        graph: what it is, its status, aliases, when it came up."""
        return self._tool("graph", name=name, project=project)

    def session_context(self, project: str | None = None) -> str:
        """The full session-start briefing, on demand (mid-session refresh)."""
        return self._tool("session_context",
                          project=project or self.hooks.project)

    def cleanup_history(self, project: str, older_than_days: int | None = None,
                        mode: str | None = None,
                        confirm: str | None = None) -> str:
        """DESTRUCTIVE — remove conversation history older than a cutoff
        (90-day floor). Without `confirm` this returns a PREVIEW only."""
        return self._tool("cleanup_history", project=project,
                          older_than_days=older_than_days, mode=mode,
                          confirm=confirm)


def demo(call_model=None) -> bool:
    """Run a tiny two-turn session end-to-end against the cloud, using a stub
    model unless one is supplied. Returns True if the hooks all fired. Used by
    the test container to prove the OpenClaw hook path."""
    if call_model is None:
        def call_model(system, context, prompt):  # noqa: ANN001
            return f"(stub reply to: {prompt})"

    sess = MemorySession(project="global", session_id="openclaw-hooks-demo",
                         base_system_prompt="You are OpenClaw, a marketing agent.")
    system_prompt = sess.start()
    ok = isinstance(system_prompt, str)
    for msg in ("What did we decide about the launch?",
                "Draft a short teaser post."):
        context = sess.build_context(msg)
        reply = call_model(system_prompt, context, msg)
        env = sess.record(msg, reply)
        ok = ok and (env.get("status") == "ok")
    return ok


if __name__ == "__main__":
    import sys
    sys.exit(0 if demo() else 1)
