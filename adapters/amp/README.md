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

Then connect this machine to your hub once:

```bash
pip install "git+https://github.com/BrethofAI/brethof-brain-client.git"
brethof-brain pair http://127.0.0.1:8600   # or https://<your hub>
```

`pair` shows a code; approve it on the hub's settings page, and the device
key lands in `~/.brethof-brain/config.json` (never printed) — the file the
plugin reads. `BRETHOF_BRAIN_*` environment variables override it.

On Windows the plugin folder is `%USERPROFILE%\.config\amp\plugins\`. Plugins load by
themselves; in execute mode (`amp -x`) add `--plugin-ready-timeout 30` so the
turn waits for the plugin.
