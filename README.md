# brethof-mind client

Thin client for **[brethof-mind](https://brethof.cloud)** — shared long-term
memory for your AI coding agents. It gives Claude Code (and other agents)
persistent, searchable memory across sessions: it remembers past decisions,
conversations, and project context so you don't re-explain yourself every time.

This client is deliberately tiny. All the real work — storage, embeddings,
retrieval-augmented recall — happens on the brethof-mind service. The client
only:

1. forwards Claude Code **hook events** to the service over HTTPS, and pastes
   back the memory it returns, and
2. wires Claude Code's **remote MCP** endpoint so the 15 memory tools
   (`recall`, `save_memory`, `get_memory`, …) are available on demand.

It has **no third-party dependencies** — pure Python standard library, so it
runs anywhere Python 3.9+ does.

## What leaves your machine (read this)

The client is source-available precisely so you can verify this yourself — read
[`brethof_mind_client/`](brethof_mind_client/); it's a few hundred lines.

- On **session start** and **each prompt**, it sends your **project name** and
  (for ambient recall) your **current prompt text** to the service, and injects
  the memory that comes back.
- On **each assistant turn** (the `Stop` hook), it reads the *new* lines of your
  Claude Code transcript and sends them to be archived as your memory — this
  includes your messages, the assistant's replies, its thinking blocks, and
  tool-call markers. A local offset file (`~/.brethof-mind/state/`) ensures each
  line is sent once.
- Every request is authenticated with **your API key** and goes only to **your
  endpoint** (`api.brethof.cloud` by default). Your data lands in your own
  isolated tenant database, encrypted at rest.

Nothing else is collected. The client never sends files, environment variables,
or anything outside the transcript. If a hook can't reach the service it fails
silent — your session is never blocked.

## Install

```bash
pip install brethof-mind-client
```

## Set up

Get an API key from your account at [brethof.ai/account](https://brethof.ai)
(the brethof-mind tab), then:

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
then defaults. The config file is the only place your key is stored; `setup`
locks it to your user account.

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
  `BRETHOF_MIND_PROJECT`.

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
pip uninstall brethof-mind-client
```

## License

Source-available under the **brethof-mind Client License** (see
[`LICENSE`](LICENSE)) — free to read, audit, and use with the brethof-mind
service; not for redistribution or building a competing service. Not affiliated
with Anthropic; "Claude" and "Claude Code" are trademarks of Anthropic.
