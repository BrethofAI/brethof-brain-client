# brethof-brain for Gemini CLI

Full ambient contract via Gemini CLI's native hooks (shipped December
2025, Claude-Code-shaped down to the output schema):

- **Session brief** — `SessionStart` injects your project's memory as the
  first turn in history.
- **Ambient recall** — `BeforeAgent` fires on every user prompt and pulls
  the matching memory in ahead of the answer.
- **Archive** — `AfterAgent` ships each turn — your prompt and the reply,
  without the injected memory — to your Brain's complete chat archive.

Every hook is fail-open: if the Brain is unreachable, Gemini CLI just
runs without memory.

## Install

```bash
git clone https://github.com/BrethofAI/brethof-brain-client ~/brethof-brain-client
python3 ~/brethof-brain-client/adapters/gemini-cli/setup.py
```

The key comes from `~/.brethof-brain/config.json` or `BRETHOF_BRAIN_API_KEY`.
The hooks go into `~/.gemini/settings.json` (user level, so they run in every
folder). Re-running is safe.
