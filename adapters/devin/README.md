# brethof-brain for Devin CLI

Devin CLI (Cognition — the agent behind Windsurf's Devin Desktop) takes
Claude Code's hook format, so the plugin's own hook entry is the adapter:

- **Session brief** — `SessionStart` injects your project's memory.
- **Ambient recall** — `UserPromptSubmit` pulls the matching memory in ahead
  of every answer.
- **Archive** — `Stop` ships the turn to your Brain's complete chat archive.
  Devin passes no transcript, so the turn is built from the hooks: the
  prompt kept at prompt-submit and the reply from `last_assistant_message`.

Every hook is fail-open: if the Brain is unreachable, Devin just runs.

## Install

```bash
git clone https://github.com/BrethofAI/brethof-brain-client ~/brethof-brain-client
python3 ~/brethof-brain-client/adapters/devin/setup.py
```

The key comes from `~/.brethof-brain/config.json` or `BRETHOF_BRAIN_API_KEY`.
The hooks go into Devin's user config (`~/.config/devin/config.json`;
`%APPDATA%\devin\config.json` on Windows). Re-running is safe.
