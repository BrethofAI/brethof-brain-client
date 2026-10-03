# brethof-brain for ZCode — not yet proven

ZCode (Z.ai) takes Claude-style hooks from `~/.zcode/cli/config.json`, so the
plugin's own hook entry serves it: `SessionStart` for the brief,
`UserPromptSubmit` for recall, `Stop` for the archive (the prompt kept and
`last_assistant_message`).

**Status:** written from ZCode's hooks reference and a headless run of its
agent; not yet proven on our rig, because ZCode installs as a desktop app
with no headless install the rig can drive. Not a supported platform until
it is.

```bash
python3 ~/brethof-brain-client/adapters/zcode/setup.py
```
