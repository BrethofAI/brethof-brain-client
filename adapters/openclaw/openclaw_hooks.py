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


class MemorySession:
    """A thin memory wrapper for one OpenClaw agent session."""

    def __init__(self, project: str, session_id: str, base_system_prompt: str = ""):
        self.hooks = AgentHooks(project=project, session_id=session_id)
        self.base_system_prompt = base_system_prompt
        self._memory_block = ""

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
