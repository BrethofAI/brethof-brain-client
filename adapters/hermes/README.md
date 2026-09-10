# brethof-brain + Hermes Agent

brethof-brain is Hermes's long-term memory through a **MemoryProvider** — the
one plugin type Hermes selects with `memory.provider`. Its lifecycle is the
whole ambient contract:

| Hermes calls | brethof-brain does | When |
|---|---|---|
| `initialize()` → `system_prompt_block()` | your brain's briefing (rules, projects, last notes) into the system prompt | session start |
| `prefetch()` | ambient recall — the records that bear on this prompt | every turn |
| `sync_turn()` | the turn archived into memory | after every turn |

Stdlib only; nothing to pip-install. Every path is fail-open: memory can never
block or break a run.

## Install

```bash
hermes plugins install BrethofAI/brethof-brain-client/adapters/hermes --no-enable
hermes config set memory.provider brethof-brain
```

(`--no-enable` only skips the general plugin prompt — memory providers are
activated by `memory.provider`, not by `plugins.enabled`.)

Put your key in `~/.hermes/.env`:

```
BRETHOF_BRAIN_API_KEY=bmv2_...
BRETHOF_BRAIN_ENDPOINT=http://127.0.0.1:8610      # your local box (default)
# BRETHOF_BRAIN_ENDPOINT=https://memory.brethof.cloud/t/<tenant>   # hosted
BRETHOF_BRAIN_PROJECT=my-agent                     # the project this agent works in
# hosted memory only — it locks after idle; the provider unlocks it itself:
# BRETHOF_BRAIN_UNLOCK_PASSPHRASE=...
# BRETHOF_BRAIN_LOCK_AFTER_MINUTES=30              # 5-60
```

`hermes memory setup` walks the same fields interactively. The provider also
reads `~/.brethof-brain/config.json` (`api_key`, `endpoint`, `default_project`,
`unlock_passphrase`), the file every brethof-brain adapter shares. Restart
Hermes; `hermes memory status` shows `brethof-brain` active.

## Explicit memory tools (recommended)

The provider handles the ambient loop only. For the agent to search and save
memory on demand, add the Brain's MCP server with Hermes's native client — one
block in `~/.hermes/config.yaml`, the full customer toolset:

```yaml
mcp_servers:
  brethof-brain:
    url: "http://127.0.0.1:8610/v1/mcp"          # hosted: https://memory.brethof.cloud/t/<tenant>/v1/mcp
    headers:
      Authorization: "Bearer bmv2_..."
```

`/reload-mcp` inside a session, or restart Hermes.

## Skills (optional)

`skills/` carries the three skills /recall, /onboard and /curate — the same three the Claude
Code plugin ships as commands. Copy them into your skills tree to make them
visible to the agent:

```bash
cp -r ~/.hermes/plugins/brethof-brain/skills/* ~/.hermes/skills/
```

Run `onboard` once on a fresh memory. Memory curates itself as you work —
`curate` is for closing a session deliberately.

## Notes

- One `BRETHOF_BRAIN_PROJECT` per Hermes agent: Hermes resolves the provider
  once per session, so the project is the agent's, not the prompt's. Address
  other projects with the MCP tools (`search_brain(project=...)`).
- Cron runs and subagents read memory but never archive as you
  (`agent_context` other than `primary` skips writes).
- Hermes's built-in `MEMORY.md`/`USER.md` keeps working alongside; the
  external provider is additive by Hermes's design.
