# brethof-mind cloud + Hermes

brethof-mind is designed to be Hermes's **sole** long-term memory (its built-in
`MEMORY.md`/`USER.md` note store is disabled). Hermes integrates memory through a
**`MemoryProvider`** — a plugin whose lifecycle methods are the hooks:

| Hook | brethof-mind cloud endpoint | When Hermes calls it |
|---|---|---|
| `initialize()` → `system_prompt_block()` | `POST /v1/hooks/session-start` | session start — brain block into the system prompt |
| `queue_prefetch()` / `prefetch()` | `POST /v1/hooks/prompt-submit` | before each model call — ambient recall |
| `sync_turn()` | `POST /v1/hooks/stop` | after each turn — archive to chat memory |
| `brethofmind_search/recall/save/delete` | `POST /v1/mcp` | deliberate tool calls |

The **cloud** provider (`brethofmind_cloud/`) is the counterpart of the local,
self-hosted `brethofmind` provider: instead of talking straight to SurrealDB with
root creds and embedding turns itself, it routes every hook through
`api.brethof.cloud` with your API key — the server does isolation, embedding,
recall, and metering. Stdlib only, so it drops in without new dependencies.

## Install

1. Copy `brethofmind_cloud/` into your Hermes state dir:
   `~/.hermes/plugins/brethofmind_cloud/` (or `$HERMES_HOME/plugins/...`).
2. Set the environment (secrets belong in `~/.hermes/.env`):
   ```
   BRETHOF_MIND_API_KEY=bm_live_your_key
   BRETHOF_MIND_ENDPOINT=https://api.brethof.cloud   # optional, this is the default
   HERMES_MEMORY_PROJECT=global                        # project this agent reads/archives to
   ```
3. Activate it in Hermes `cli-config.yaml`:
   ```yaml
   memory:
     provider: brethofmind_cloud
   ```
Restart Hermes. It now recalls at session start, prefetches per turn, archives
every turn, and exposes the `brethofmind_*` tools — all against the cloud.

## Tools-only alternative (no hooks)

If you just want the 15 memory tools in Hermes without the provider's automatic
inject/archive hooks, register the remote MCP endpoint instead (see
`mcp_servers.example.yaml`). The provider above is the fuller integration and the
recommended path when brethof-mind is Hermes's memory.
