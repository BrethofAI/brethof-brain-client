# brethof-brain client

Thin client for **[brethof-brain](https://brethof.cloud)** — shared long-term
memory for your AI coding agents. It gives your agents persistent, searchable
memory across sessions: it remembers past decisions, conversations, and project
context so you don't re-explain yourself every time.

Works with **Claude Code**, **Hermes**, **Grok Build**, and any agent that
supports hooks and/or MCP.

## How it works

The client is deliberately tiny. All the real work — storage, embeddings,
retrieval-augmented recall — happens on the brethof-brain service. The client
only:

1. forwards agent **hook events** to the service over HTTPS, and pastes back
   the memory it returns, and
2. wires the **remote MCP** endpoint so the memory tools
   (`search_memory`, `search_history`, `save_project`, `save_project_rule`,
   `get_memory`, …) are available on demand.

It has **no third-party dependencies** — pure Python standard library, so it
runs anywhere Python 3.9+ does.

## Supported agents

| Agent | Adapter | How it connects |
|---|---|---|
| **Claude Code** | built-in | Plugin install (recommended) or CLI hooks |
| **Hermes** (Nous Research) | [`adapters/hermes/`](adapters/hermes/) | Memory provider plugin + skills |
| **Grok Build** (xAI) | [`adapters/grok-build/`](adapters/grok-build/) | `grok mcp add` + Claude Code hooks + skills |
| **OpenClaw** | [`adapters/openclaw/`](adapters/openclaw/) | `MemorySession` wrapper (test harness) |

Each adapter has its own README with install instructions. The table above
links to them.

### Claude Code (recommended)

The plugin bundles this client, wires the hooks + the memory tools, and adds
the `/recall` `/curate` `/heal` `/onboard` commands — no `pip install` needed,
only Python 3.9+ on your PATH.

```
/plugin marketplace add BrethofAI/brethof-brain-client
/plugin install brethof-brain@brethof
```

You'll be prompted for your **API key** (from
[brethof.ai/account](https://brethof.ai) → brethof-brain tab); Claude Code stores
it as plugin config (sensitive values go to your OS keychain where available)
and passes it to the hooks via the environment — never on a command line.
Restart Claude Code and memory is live. Commands are namespaced:
`/brethof-brain:recall`, `/brethof-brain:curate`, `/brethof-brain:heal`,
`/brethof-brain:onboard`.

### Grok Build

Grok Build is Claude Code-compatible — it reads `~/.claude/settings.json` for
hooks and has its own `grok mcp` command for MCP servers. See
[`adapters/grok-build/README.md`](adapters/grok-build/README.md) for the
automated setup script, or add manually:

```bash
grok mcp add --transport http --scope user brethof-brain \
  https://api.brethof.cloud/v1/mcp \
  --header "Authorization: Bearer bm_live_YOUR_KEY"
```

### Hermes

Hermes integrates through a **MemoryProvider** plugin that auto-recalls at
session start, prefetches per turn, archives every turn, and exposes the
`brethofmind_*` tools. See [`adapters/hermes/README.md`](adapters/hermes/README.md).

### OpenClaw (test harness)

OpenClaw has no native memory system — this adapter adds one via a
`MemorySession` wrapper. It's the containerized test agent that proves the hook
path works. See [`adapters/openclaw/README.md`](adapters/openclaw/README.md).

## What leaves your machine (read this)

The client is source-available precisely so you can verify this yourself — read
[`brethof_brain_client/`](brethof_brain_client/); it's a few hundred lines.

- On **session start** and **each prompt**, it sends your **project name** and
  (for ambient recall) your **current prompt text** to the service, and injects
  the memory that comes back.
- On **each assistant turn** (the `Stop` hook), it reads the *new* lines of your
  agent transcript and sends them to be archived as your memory — this
  includes your messages, the assistant's replies, its thinking blocks, and
  one-line tool-call markers (`[tool_use: Bash]`). **Tool outputs are dropped
  client-side**: the contents of files the assistant reads and the output of
  commands it runs never leave your machine. A local offset file
  (`~/.brethof-brain/state/`) ensures each line is sent once.
- Every request is authenticated with **your API key** and goes only to **your
  endpoint** (`api.brethof.cloud` by default). Your data lands in your own
  isolated tenant database, encrypted at rest.

Nothing else is collected. The client never sends files, environment variables,
or anything outside the transcript text described above. If a hook can't reach
the service it fails silent — your session is never blocked. The one exception
to silence: if your **API key is rejected**, the next session start shows a
one-line notice, because silently stopping archival would mean losing history.

## Install as a library / CLI (alternative)

For non-plugin use (scripting, other agents), install the package directly:

```bash
pip install brethof-brain-client
```

Get an API key from [brethof.ai/account](https://brethof.ai) (the brethof-brain
tab), then:

```bash
brethof-brain setup --api-key bm_live_xxxxxxxx
brethof-brain install-hooks      # auto-load & archive memory in Claude Code
brethof-brain mcp-command        # prints the `claude mcp add …` line to run
```

Restart Claude Code (or open a new session) and your memory is live. Check
everything with:

```bash
brethof-brain doctor
brethof-brain status
```

## Configuration

Settings resolve from environment variables, then `~/.brethof-brain/config.json`,
then defaults. With the **CLI install**, the config file is where your key is
stored — `setup` creates it owner-readable-only (`0600`) on Linux/macOS; on
Windows your user-profile ACLs protect it. With the **plugin install**, Claude
Code holds the key instead and the config file isn't needed.

```json
{
  "endpoint": "https://api.brethof.cloud",
  "api_key": "bm_live_…",
  "default_project": "global",
  "projects": [
    { "path": "/home/me/work/acme", "key": "acme" },
    { "path": "/home/me/work/blog", "key": "blog" }
  ]
}
```

- **Projects** partition your memory. The client picks a project per working
  directory: `$BRETHOF_BRAIN_PROJECT` wins, else the longest matching `path`
  prefix, else `default_project`. A project key matches `[a-z][a-z0-9_]{0,15}`.
- Env overrides: `BRETHOF_BRAIN_ENDPOINT`, `BRETHOF_BRAIN_API_KEY`,
  `BRETHOF_BRAIN_PROJECT` (this session's project), `BRETHOF_BRAIN_DEFAULT_PROJECT`
  (fallback default), `BRETHOF_BRAIN_HOME` (move `~/.brethof-brain` elsewhere).
- Corporate proxies work out of the box: the client honors the standard
  `HTTPS_PROXY` / `HTTP_PROXY` environment variables.

## Commands

| Command | Does |
|---|---|
| `brethof-brain setup` | Save credentials, verify connectivity |
| `brethof-brain install-hooks` | Add the hooks to `~/.claude/settings.json` (idempotent, backs up first) |
| `brethof-brain uninstall-hooks` | Remove them |
| `brethof-brain mcp-command` | Print the `claude mcp add` line for the memory tools |
| `brethof-brain status` | Show your plan and usage |
| `brethof-brain doctor` | Diagnose config, connectivity, and hook wiring |

## Uninstall

```bash
brethof-brain uninstall-hooks
claude mcp remove brethof-brain
grok mcp remove brethof-brain    # if using Grok Build adapter
pip uninstall brethof-brain-client
```

## License

Source-available under the **brethof-brain Client License** (see
[`LICENSE`](LICENSE)) — free to read, audit, and use with the brethof-brain
service; not for redistribution or building a competing service. Not affiliated
with Anthropic; "Claude" and "Claude Code" are trademarks of Anthropic.