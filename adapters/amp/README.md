# brethof-brain for Amp

An Amp plugin — one TypeScript file, no shell, the same on Linux, macOS and
Windows:

- **Session brief** — your project's memory rides the first prompt of each
  thread (Amp's thread start cannot add text, so the first prompt carries it).
- **Ambient recall** — the matching memory is appended to every prompt,
  hidden from the screen.
- **Archive** — when a turn ends, your prompt and the reply go to your
  Brain's complete chat archive.

Every call is fail-open: if the Brain is unreachable, Amp just runs.

## Install

```bash
mkdir -p ~/.config/amp/plugins
curl -fsSL https://raw.githubusercontent.com/BrethofAI/brethof-brain-client/main/adapters/amp/brethof-brain.ts \
  -o ~/.config/amp/plugins/brethof-brain.ts
```

On Windows the folder is `%USERPROFILE%\.config\amp\plugins\`. The key comes
from `~/.brethof-brain/config.json` or `BRETHOF_BRAIN_API_KEY`. Plugins load by
themselves; in execute mode (`amp -x`) add `--plugin-ready-timeout 30` so the
turn waits for the plugin.
