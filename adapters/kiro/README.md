# brethof-brain for Kiro (AWS)

Ambient memory via Kiro's shell-command hooks — a hook's **stdout is
added to the agent's context** on exit 0, so injection is plain printed
text:

- **Session brief** — `agentSpawn` / Session Start trigger; the brief
  persists for the session.
- **Ambient recall** — `userPromptSubmit` / Prompt Submit trigger; recall
  attaches to that prompt.
- **Archive** — the prompt (from the prompt-submit payload) plus the stop
  payload's assistant text, event-built. The stop payload's exact shape is
  not fully documented by AWS — this leg is best-effort until the live rig
  pins it.

Every hook is fail-open.

## Install (Kiro CLI — agent config format)

1. `pip install brethof-brain-client` (or run from a checkout).

2. Add to your Kiro agent config's `hooks` object:

```json
{
  "hooks": {
    "agentSpawn": [
      { "command": "python3 /ABSOLUTE/PATH/TO/adapters/kiro/kiro_hook.py session-start" }
    ],
    "userPromptSubmit": [
      { "command": "python3 /ABSOLUTE/PATH/TO/adapters/kiro/kiro_hook.py prompt-submit" }
    ],
    "stop": [
      { "command": "python3 /ABSOLUTE/PATH/TO/adapters/kiro/kiro_hook.py stop" }
    ]
  }
}
```

In the Kiro IDE, create the equivalent Session Start / Prompt Submit /
Stop hooks in `.kiro/hooks/` with a Shell Command action pointing at the
same script (default timeout 60s).

3. Key in `~/.brethof-brain/config.json` (`api_key`, `endpoint`,
   `default_project`); env vars `BRETHOF_BRAIN_*` override.

Rig status: adapter conformance-tested; the live rig row lands with an
AWS builder account.
