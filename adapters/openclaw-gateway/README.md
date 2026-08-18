# brethof-brain cloud + OpenClaw gateway

Native OpenClaw plugin — persistent cross-session memory for your gateway
agent:

| Hook | When | Effect |
|---|---|---|
| `before_prompt_build` | first turn of a session | your memory brain block appended to the system context |
| `before_prompt_build` | every prompt | ambient recall relevant to the message |
| `agent_end` | after each reply | the turn archived into long-term memory (fire-and-forget) |

## Install

```bash
export BRETHOF_BRAIN_API_KEY=bm_live_...
openclaw plugins install ./adapters/openclaw-gateway
openclaw gateway restart
```

Configure (optional) in `openclaw.json` — env vars work too
(`BRETHOF_BRAIN_API_KEY`, `BRETHOF_BRAIN_ENDPOINT`, `BRETHOF_BRAIN_PROJECT`):

```json5
{
  plugins: {
    entries: {
      "brethof-brain": {
        enabled: true,
        // REQUIRED for archival: agent_end carries conversation content,
        // which OpenClaw blocks for non-bundled plugins by default. Without
        // this line memory archival silently never runs (the gateway log
        // says 'typed hook "agent_end" blocked').
        hooks: { allowConversationAccess: true },
        config: { project: "my-agent" }
      }
    }
  }
}
```

## Explicit memory tools (recommended)

The plugin handles the ambient loop only. For the agent to search and save
memory on demand, add the Brain's MCP server with OpenClaw's native client —
one block, full customer toolset:

```json5
{
  mcp: {
    servers: {
      "brethof-brain": {
        url: "https://api.brethof.cloud/v1/mcp",
        transport: "streamable-http",
        headers: { Authorization: "Bearer bm_live_..." }
      }
    }
  }
}
```

## Notes

- Every hook is fail-open — memory can never block or break a run.
- One `project` per agent keeps memories separated; the Brain curates each
  project independently.
