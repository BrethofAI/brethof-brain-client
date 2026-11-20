# brethof-brain + Hermes Agent

brethof-brain is Hermes's long-term memory through a **MemoryProvider** — the
one plugin type Hermes selects with `memory.provider`. Its lifecycle is the
whole ambient contract:

| Hermes calls | brethof-brain does | When |
|---|---|---|
| `initialize()` → `system_prompt_block()` | your brain's briefing (rules, projects, last notes) into the system prompt | session start |
| `prefetch()` | ambient recall — the records that bear on this prompt | every turn |
| `sync_turn()` | the turn archived into memory | after every turn |

Stdlib only — the provider itself needs no pip install. Every path is fail-open: memory can never
block or break a run.

## What it sends

- Every prompt you type, and each turn's user and assistant text, go with
  this device's key to your Brain hub: `127.0.0.1:8600` by default, or a hub
  you run on another machine.
- The server's briefing and recall text are put into the system prompt and
  into each turn.
- It reads `BRETHOF_BRAIN_*` from `$HERMES_HOME/.env` and
  `~/.brethof-brain/config.json`. Nothing else leaves the machine; no
  telemetry.

## Install

From the Hermes plugin catalog:

```bash
hermes plugins install brethof-brain --no-enable
hermes config set memory.provider brethof-brain
```

or straight from this repo:

```bash
hermes plugins install BrethofAI/brethof-brain-client/adapters/hermes --no-enable
```

(`--no-enable` only skips the general plugin prompt — memory providers are
activated by `memory.provider`, not by `plugins.enabled`.)

Connect this machine to your hub once:

```bash
pip install "git+https://github.com/BrethofAI/brethof-brain-client.git"
brethof-brain pair http://127.0.0.1:8600   # or https://<your hub's address>
```

`pair` shows a code; approve it on the hub's settings page, and it writes
`~/.brethof-brain/config.json` (`endpoint`, the device key `api_key` — never
printed), the file every brethof-brain adapter shares. Name the project this
agent works in, and override the file if you need to, in `~/.hermes/.env`:

```
BRETHOF_BRAIN_PROJECT=my-agent                     # the project this agent works in
# BRETHOF_BRAIN_ENDPOINT=https://<your hub's address>   # overrides config.json
```

`hermes memory setup` walks the same fields interactively. Restart Hermes;
`hermes memory status` shows `brethof-brain` active.

## Explicit memory tools (recommended)

The provider handles the ambient loop only. For the agent to search and save
memory on demand, add the Brain's MCP server with Hermes's native client — one
block in `~/.hermes/config.yaml`, the full customer toolset:

```yaml
mcp_servers:
  brethof-brain:
    url: "http://127.0.0.1:8600/v1/mcp"          # another machine: https://<your hub's address>/v1/mcp
    headers:
      Authorization: "Bearer bd_..."
```

`bd_...` is the device key `pair` saved; `brethof-brain mcp-command` prints the
address and key in a ready-made line. The hub accepts the key only as
`Authorization: Bearer`.

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
