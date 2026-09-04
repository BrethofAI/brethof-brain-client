# brethof-brain for OpenCode & Kilo Code

One native plugin, two platforms — Kilo Code's core is OpenCode-derived and
exposes the identical plugin interface. Full ambient contract:

- **Session brief** — the model is briefed on your project with the first
  message of the session.
- **Ambient recall** — every user message pulls the matching memory in
  ahead of the answer; no tool call, no command.
- **Archive** — when a turn settles, the exchange lands in your Brain's
  complete chat archive.

Injected memory parts are flagged `synthetic` (the platform's own
convention for machine text), so the human's words and the injected memory
never mix — in the archive or anywhere else. Every hook is fail-open: if
the Brain is unreachable, the agent just runs without memory.

## Install — OpenCode

Drop the plugin file in place (project or global):

```bash
mkdir -p .opencode/plugins && cp lib/index.js .opencode/plugins/brethof-brain.js
```

or global: `~/.config/opencode/plugins/brethof-brain.js` — or add the npm
package to `opencode.json`:

```json
{ "plugin": ["brethof-brain-opencode"] }
```

## Install — Kilo Code

Same file, Kilo's locations: `.kilocode/plugin/brethof-brain.js` (project)
or `~/.config/kilo/plugin/brethof-brain.js` (global), or the `plugin`
array in `kilo.json`. One install covers Kilo's VS Code, JetBrains, CLI
and TUI — they are all clients of the same core.

## Configure

`~/.brethof-brain/config.json` (the file every brethof-brain adapter reads):

```json
{
  "api_key": "bmv2_...",
  "endpoint": "http://127.0.0.1:8610",
  "default_project": "my-project"
}
```

Environment variables override the file: `BRETHOF_BRAIN_API_KEY`,
`BRETHOF_BRAIN_ENDPOINT`, `BRETHOF_BRAIN_PROJECT`. Hosted memory: add
`BRETHOF_BRAIN_UNLOCK_PASSPHRASE` (or `unlock_passphrase` in the config file)
and the plugin unlocks your memory itself when it has locked after idle;
`BRETHOF_BRAIN_LOCK_AFTER_MINUTES` sets that idle time (5-60).

Get a key at [brethof.ai/account](https://brethof.ai/account/).
