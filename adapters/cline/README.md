# brethof-brain for Cline

Cloud memory for [Cline](https://cline.bot) — the full ambient contract as a
**native Cline SDK plugin**:

- **Session brief** — the model is briefed on your project before turn 1.
- **Ambient recall** — every new prompt pulls the matching memory in ahead
  of the answer; no tool call, no command.
- **Archive** — every exchange lands in your Brain's complete chat archive.

Memory is applied as a request-only overlay, so injected context never
pollutes the stored conversation, and every hook is fail-open: if the Brain
is unreachable, Cline just runs without memory.

## Install

```bash
cline plugin install brethof-brain-cline
```

Or from a local checkout / git URL:

```bash
cline plugin install /path/to/brethof-brain-client/adapters/cline
```

Works in the Cline CLI and the VS Code extension — both run the same SDK
bundle and load the same installed plugins. (`--cwd <path>` installs
workspace-locally to `<path>/.cline/plugins` instead of globally.)

## Configure

Create `~/.brethof-brain/config.json` (the same file every brethof-brain
adapter reads):

```json
{
  "api_key": "bmv2_...",
  "endpoint": "http://127.0.0.1:8610",
  "default_project": "my-project"
}
```

Environment variables override the file: `BRETHOF_BRAIN_API_KEY`,
`BRETHOF_BRAIN_ENDPOINT`, `BRETHOF_BRAIN_PROJECT`.

Get a key at [brethof.ai/account](https://brethof.ai/account/).

## Why a plugin and not `.clinerules/hooks/` file hooks?

Verified against Cline's source (4.1.x): in the current SDK bridge the
TaskStart and UserPromptSubmit file hooks are gate-only — their
`contextModification` is not injected (only PreToolUse/PostToolUse inject),
and TaskComplete's payload carries only the final output text, never the
transcript. The plugin surface has both channels typed and complete:
`beforeModel` injects, `afterRun` sees the whole conversation.

For the Brain's explicit tool doors (`search_brain`, the save tools, the
ledger and playbooks) add the MCP block as well — see
`adapters/editors/README.md`.
