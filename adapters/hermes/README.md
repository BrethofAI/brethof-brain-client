# brethof-brain cloud + Hermes

brethof-brain is designed to be Hermes's **sole** long-term memory (its built-in
`MEMORY.md`/`USER.md` note store is disabled). Hermes integrates memory through a
**`MemoryProvider`** — a plugin whose lifecycle methods are the hooks:

| Hook | brethof-brain cloud endpoint | When Hermes calls it |
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
   BRETHOF_BRAIN_API_KEY=bm_live_your_key
   BRETHOF_BRAIN_ENDPOINT=https://api.brethof.cloud   # optional, this is the default
   HERMES_MEMORY_PROJECT=global                        # project this agent reads/archives to
   ```
3. Activate it in Hermes `config.yaml`:
   ```yaml
   memory:
     provider: brethofmind_cloud
   ```
Restart Hermes. It now recalls at session start, prefetches per turn, archives
every turn, and exposes the `brethofmind_*` tools — all against the cloud.

### Install gotchas (learned the hard way)

- **`memory.provider` is the ONLY activation path.** Do **not** run
  `hermes plugins enable brethofmind_cloud` — the general plugin loader has no
  `register_memory_provider` on its `PluginContext` and the plugin fails to
  load through it. Keep the plugin out of BOTH `plugins.enabled` and
  `plugins.disabled`.
- **Verify the write path, not just recall.** After install, send one message
  and confirm a fresh row lands in your `<project>_chat` (e.g. via the
  `recent_records` tool). Recall working does NOT prove archiving works — they
  fail independently.
- **Editing `$HERMES_HOME/.env` from a sandboxed agent can silently miss.**
  MSIX-packaged apps (e.g. the Claude desktop app) copy-on-write their writes
  under `%LOCALAPPDATA%\Packages\<pkg>\LocalCache\`, so the "edited" `.env`
  never reaches Hermes while the editor keeps seeing its own shadow copy.
  If config edits mysteriously don't take effect, compare the file's hash from
  a shell spawned outside the sandbox.

## Memory commands (skills)

The provider gives Hermes automatic memory + the `brethofmind_*` tools. To also
get the `/recall`, `/curate`, `/onboard` commands, copy the `skills/`
folder here into your Hermes skills dir:

```
cp -r skills/* ~/.hermes/skills/
```

They use the provider's tools (no local scripts), so they work anywhere the
provider does. Run `/onboard` once. Memory curates itself automatically as you work —
`/curate` is only for explicit "remember this" saves.

## Tools-only alternative (no hooks)

If you just want the memory tools in Hermes without the provider's automatic
inject/archive hooks, register the remote MCP endpoint instead (see
`mcp_servers.example.yaml`). The provider above is the fuller integration and the
recommended path when brethof-brain is Hermes's memory.
