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
    def _tool(self, name: str, **arguments) -> str:
        self._rpc_id += 1
        resp = self._http.post("/v1/mcp", {
            "jsonrpc": "2.0", "id": self._rpc_id, "method": "tools/call",
            "params": {"name": name, "arguments": {
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
