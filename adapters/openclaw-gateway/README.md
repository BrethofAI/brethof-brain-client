# brethof-brain + OpenClaw gateway

Native OpenClaw plugin — persistent cross-session memory for your gateway
agent:

| Hook | When | Effect |
|---|---|---|
| `before_prompt_build` | first turn of a session | your memory brain block appended to the system context |
| `before_prompt_build` | every prompt | ambient recall relevant to the message |
| `agent_end` | after each reply | the turn archived into long-term memory (fire-and-forget) |

## Install

```bash
pip install "git+https://github.com/BrethofAI/brethof-brain-client.git"
brethof-brain pair http://127.0.0.1:8600   # your hub; or https://<your hub>
openclaw plugins install --force --accept-capabilities ./adapters/openclaw-gateway
openclaw gateway restart
```

`pair` shows a code; approve it on the hub's settings page, and the device
key lands in `~/.brethof-brain/config.json` (never printed), which the plugin
reads.

OpenClaw 2026.8.2+ requires both flags for a plugin installed from a
local path: `--force` because the source is outside ClawHub review (you
are the review — you have the source in front of you), and
`--accept-capabilities` because this plugin declares
`allowConversationAccess` (archival reads the conversation; that is the
product). OpenClaw before 2026.8 (e.g. 2026.7.1) does not know
`--accept-capabilities` and refuses the command — drop that flag there and
keep `--force`.

Configure (optional) in `openclaw.json` — env vars override the file too
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
        url: "http://127.0.0.1:8600/v1/mcp",   // or https://<your hub>/v1/mcp
        transport: "streamable-http",
        headers: { Authorization: "Bearer bd_..." }
      }
    }
  }
}
```

`bd_...` is the device key `pair` saved; `brethof-brain mcp-command` prints the
address and key in a ready-made line. The hub accepts the key only as
`Authorization: Bearer`.

## Notes

- Every hook is fail-open — memory can never block or break a run.
- One `project` per agent keeps memories separated; the Brain curates each
  project independently.
