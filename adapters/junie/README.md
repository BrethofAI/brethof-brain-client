# brethof-brain for JetBrains Junie (CLI)

Full ambient contract via Junie CLI's hooks (Early Access):

- **Session brief** — `SessionStart` injects your project's memory (raw
  stdout is `additionalContext` on this platform).
- **Ambient recall** — `UserPromptSubmit` fires per prompt with the raw
  prompt text.
- **Archive** — event-built: the prompt from `UserPromptSubmit` plus
  `last_assistant_message` from `Stop` reconstruct every exchange (Junie
  hands no transcript file).

Every hook is fail-open. Note: JetBrains documents `UserPromptSubmit` as
interactive-TUI-only for now — headless runs get brief + archive until
they extend it.

## Install

1. `pip install git+https://github.com/BrethofAI/brethof-brain-client.git` (or run from a checkout — the hook
   bootstraps its own `sys.path`).

2. Merge into `~/.junie/config.json` (timeouts in seconds; Junie defaults
   SessionStart/UserPromptSubmit to 10s):

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "timeout": 10,
        "command": "python3 /ABSOLUTE/PATH/TO/adapters/junie/junie_hook.py" }] }
    ],
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "timeout": 10,
        "command": "python3 /ABSOLUTE/PATH/TO/adapters/junie/junie_hook.py" }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "timeout": 30,
        "command": "python3 /ABSOLUTE/PATH/TO/adapters/junie/junie_hook.py" }] }
    ]
  }
}
```

3. Key in `~/.brethof-brain/config.json` (`api_key`, `endpoint`,
   `default_project`); env vars `BRETHOF_BRAIN_*` override.

Rig status: adapter conformance-tested; the live rig row lands with a
JetBrains account + the EAP install path.
