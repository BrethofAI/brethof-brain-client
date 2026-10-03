# brethof-brain for Qoder CLI

Qoder CLI (Alibaba) takes Claude Code's hook format, so the plugin's own hook
entry is the adapter:

- **Session brief** — `SessionStart` injects your project's memory.
- **Ambient recall** — `UserPromptSubmit` pulls the matching memory in ahead
  of every answer.
- **Archive** — `Stop` ships the turn to your Brain's complete chat archive:
  the prompt kept at prompt-submit and the reply from `last_assistant_message`.

Every hook is fail-open: if the Brain is unreachable, Qoder just runs.

## Install

```bash
git clone https://github.com/BrethofAI/brethof-brain-client ~/brethof-brain-client
python3 ~/brethof-brain-client/adapters/qoder/setup.py
```

The key comes from `~/.brethof-brain/config.json` or `BRETHOF_BRAIN_API_KEY`.
The hooks go into `~/.qoder/settings.json`. Re-running is safe.
