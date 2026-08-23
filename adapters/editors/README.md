# brethof-brain cloud in your editor (Cline · Windsurf/Cascade · Kimi)

Editor agents speak MCP — one config block gives them the Brain's memory
tools (`search_brain`, `search_history`, the save tools, `list_brain`, …).
Three editors, three dialects of the same block; copy yours exactly —
the field names differ on purpose.

## Cline (VS Code + CLI) — full ambient contract available

Cline is more than MCP now: our **native Cline SDK plugin**
(`adapters/cline`) delivers the full ambient loop — session brief, ambient
recall on every prompt, complete archive — with no tool call and no rule
file. Install it first, then add the MCP block below for the explicit tool
doors:

```bash
cline plugin install brethof-brain-cline
```

See [`adapters/cline/README.md`](../cline/README.md) for configuration.

For the MCP tool surface: Cline panel → MCP Servers → Configure
(`cline_mcp_settings.json`):

```json
{
  "mcpServers": {
    "brethof-brain": {
      "type": "streamableHttp",
      "url": "https://api.brethof.cloud/v1/mcp",
      "headers": { "Authorization": "Bearer bm_live_..." },
      "disabled": false,
      "autoApprove": []
    }
  }
}
```

⚠ `"type": "streamableHttp"` must be exactly that camelCase string —
anything else silently falls back to legacy SSE and fails with HTTP 405.

Teach Cline to use memory: add a rule file `.clinerules/brethof-brain.md`
in your workspace (or globally under `Documents/Cline/Rules`):

> This project has persistent memory via the brethof-brain MCP tools.
> Search memory (`search_brain`) before saying you don't know something
> from earlier work; save durable decisions with `save_project`.

## Windsurf / Cascade

`~/.codeium/windsurf/mcp_config.json` — note `serverUrl`, not `url`:

```json
{
  "mcpServers": {
    "brethof-brain": {
      "serverUrl": "https://api.brethof.cloud/v1/mcp",
      "headers": { "Authorization": "Bearer ${env:BRETHOF_BRAIN_API_KEY}" }
    }
  }
}
```

(The `${env:...}` interpolation keeps your key out of the file — export
`BRETHOF_BRAIN_API_KEY` instead.) Teach it in
`~/.codeium/windsurf/memories/global_rules.md` with the same memory rule as
above.

## Kimi (kimi-cli)

```bash
kimi mcp add --transport http brethof-brain https://api.brethof.cloud/v1/mcp \
  --header "Authorization: Bearer bm_live_..."
```

(or `~/.kimi/mcp.json` with plain `url` + `headers`). Teach it in
`~/.kimi/AGENTS.md` with the same memory rule.

## Notes

- Cline has the full ambient contract via our native plugin (above).
  Windsurf/Cascade and Kimi have no injection surface yet, so memory there
  is pull-model: the agent searches when the rule tells it to. For the full
  ambient contract use Claude Code, Cline, Codex, Qwen Code, Grok Build,
  dsh or OpenClaw with our plugins.
- One `project` per repo keeps memories separated; the tools take a
  `project` argument.
