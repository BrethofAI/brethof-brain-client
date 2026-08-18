# brethof-brain cloud in your editor (Cline · Windsurf/Cascade · Kimi)

Editor agents speak MCP — one config block gives them the Brain's memory
tools (`search_brain`, `search_history`, the save tools, `list_brain`, …).
Three editors, three dialects of the same block; copy yours exactly —
the field names differ on purpose.

## Cline (VS Code)

Cline panel → MCP Servers → Configure (`cline_mcp_settings.json`):

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

- Editors have no lifecycle hooks, so there is no ambient injection here —
  memory is pull-model: the agent searches when the rule tells it to.
  For the full ambient contract use Claude Code, Codex, Qwen Code, Grok
  Build or OpenClaw with our plugins.
- One `project` per repo keeps memories separated; the tools take a
  `project` argument.
