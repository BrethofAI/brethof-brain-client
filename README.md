# brethof-mind client

Thin client for **[brethof-mind](https://brethof.cloud)** — shared long-term
memory for your AI coding agents. It gives your agents persistent, searchable
memory across sessions: it remembers past decisions, conversations, and project
context so you don't re-explain yourself every time.

Works with **Claude Code**, **Hermes**, **Grok Build**, and any agent that
supports hooks and/or MCP.

## How it works

The client is deliberately tiny. All the real work — storage, embeddings,
retrieval-augmented recall — happens on the brethof-mind service. The client
only:

1. forwards agent **hook events** to the service over HTTPS, and pastes back
   the memory it returns, and
2. wires the **remote MCP** endpoint so the 15 memory tools
   (`recall`, `save_memory`, `get_memory`, …) are available on demand.

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

The plugin bundles this client, wires the hooks + the 15 memory tools, and adds
the `/recall` `/curate` `/heal` `/onboard` commands — no `pip install` needed,
only Python 3.9+ on your PATH.

```
/plugin marketplace add BrethofAI/brethof-mind-client
/plugin install brethof-mind@brethof
```

You'll be prompted for your **API key** (from
[brethof.ai/account](https://brethof.ai) → brethof-mind tab); Claude Code stores
it as plugin config (sensitive values go to your OS keychain where available)
and passes it to the hooks via the environment — never on a command line.
Restart Claude Code and memory is live. Commands are namespaced:
`/brethof-mind:recall`, `/brethof-mind:curate`, `/brethof-mind:heal`,
`/brethof-mind:onboard`.

### Grok Build

Grok Build is Claude Code-compatible — it reads `~/.claude/settings.json` for
hooks and has its own `grok mcp` command for MCP servers. See
[`adapters/grok-build/README.md`](adapters/grok-build/README.md) for the
automated setup script, or add manually:

```bash
grok mcp add --transport http --scope user brethof-mind \
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
[`brethof_mind_client/`](brethof_mind_client/); it's a few hundred lines.

- On **session start** and **each prompt**, it sends your **project name** and
  (for ambient recall) your **current prompt text** to the service, and injects
  the memory that comes back.
- On **each assistant turn** (the `Stop` hook), it reads the *new* lines of your
  agent transcript and sends them to be archived as your memory — this
  includes your messages, the assistant's replies, its thinking blocks, and
  one-line tool-call markers (`[tool_use: Bash]`). **Tool outputs are dropped
  client-side**: the contents of files the assistant reads and the output of
  commands it runs never leave your machine. A local offset file
  (`~/.brethof-mind/state/`) ensures each line is sent once.
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
pip install brethof-mind-client
```

Get an API key from [brethof.ai/account](https://brethof.ai) (the brethof-mind
tab), then:

```bash
brethof-mind setup --api-key bm_live_xxxxxxxx
brethof-mind install-hooks      # auto-load & archive memory in Claude Code
brethof-mind mcp-command        # prints the `claude mcp add …` line to run
```

Restart Claude Code (or open a new session) and your memory is live. Check
everything with:

```bash
brethof-mind doctor
brethof-mind status
```

## Configuration

Settings resolve from environment variables, then `~/.brethof-mind/config.json`,
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
  directory: `$BRETHOF_MIND_PROJECT` wins, else the longest matching `path`
  prefix, else `default_project`. A project key matches `[a-z][a-z0-9_]{0,15}`.
- Env overrides: `BRETHOF_MIND_ENDPOINT`, `BRETHOF_MIND_API_KEY`,
  `BRETHOF_MIND_PROJECT` (this session's project), `BRETHOF_MIND_DEFAULT_PROJECT`
  (fallback default), `BRETHOF_MIND_HOME` (move `~/.brethof-mind` elsewhere).
- Corporate proxies work out of the box: the client honors the standard
  `HTTPS_PROXY` / `HTTP_PROXY` environment variables.

## Commands

| Command | Does |
|---|---|
| `brethof-mind setup` | Save credentials, verify connectivity |
| `brethof-mind install-hooks` | Add the hooks to `~/.claude/settings.json` (idempotent, backs up first) |
| `brethof-mind uninstall-hooks` | Remove them |
| `brethof-mind mcp-command` | Print the `claude mcp add` line for the memory tools |
| `brethof-mind status` | Show your plan and usage |
| `brethof-mind doctor` | Diagnose config, connectivity, and hook wiring |

## Uninstall

```bash
brethof-mind uninstall-hooks
claude mcp remove brethof-mind
grok mcp remove brethof-mind    # if using Grok Build adapter
pip uninstall brethof-mind-client
```

## License

Source-available under the **brethof-mind Client License** (see
[`LICENSE`](LICENSE)) — free to read, audit, and use with the brethof-mind
service; not for redistribution or building a competing service. Not affiliated
with Anthropic; "Claude" and "Claude Code" are trademarks of Anthropic.