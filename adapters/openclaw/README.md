# brethof-mind cloud + OpenClaw

OpenClaw has **no native memory or hook system** (unlike Claude Code's hooks or
Hermes's memory provider). So this adapter *adds* one: a small `MemorySession`
wrapper (`openclaw_hooks.py`) that gives an OpenClaw agent brethof-mind cloud
memory by calling three fail-open hooks at the right lifecycle points.

| Hook | When | Effect |
|---|---|---|
| `session.start()` | once, at session start | memory brain block injected into the system prompt |
| `session.build_context(prompt)` | before each model call | ambient recall relevant to the prompt |
| `session.record(user, reply)` | after each turn | the turn is archived into long-term memory |

It's model-agnostic — you supply the function that calls your LLM; the wrapper
handles memory. Every hook is fail-open, so memory can never break a run.

## Use it

```python
from openclaw_hooks import MemorySession   # needs: pip install brethof-mind-client

sess = MemorySession(project="marketing", session_id=job_id,
                     base_system_prompt="You are OpenClaw, a marketing agent.")
system_prompt = sess.start()

for user_msg in conversation:
    context = sess.build_context(user_msg)
    reply   = call_your_model(system_prompt, context, user_msg)
    sess.record(user_msg, reply)
```

Set `BRETHOF_MIND_API_KEY` (and optionally `BRETHOF_MIND_ENDPOINT`) in the
environment.

## Scope: this is our test harness

Per the product plan, OpenClaw is **not a supported personal integration** — it's
the **containerized test agent** that proves the hook path works for an agent
with no built-in memory system. The `test-container/` at the repo root runs these
exact hooks against the live service in CI (see its README).
