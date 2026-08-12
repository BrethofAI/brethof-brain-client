# brethof-brain cloud + Grok Build

Grok Build (xAI's open-source coding CLI) has its own `grok mcp` command for
MCP servers and a native hook system under `~/.grok/hooks/`.

> **Note:** Grok advertises Claude Code hook compatibility
> (`~/.claude/settings.json`), but the Claude hook entries **cannot work**
> there (verified on grok 0.2.106): payloads are camelCase, passive-hook
> stdout (`additionalContext`) is ignored, and the Windows spawner mangles
> quoted commands. This adapter therefore uses grok's NATIVE hooks plus a
> pull-model memory rule — not the Claude hook files.

This adapter wires Grok Build to brethof-brain cloud: **the Brain's memory
tools on demand, pull-model recall taught by a global rule, and every turn
archived via a native Stop hook**.

## What you get

| Feature | How | Effect |
|---|---|---|
| **Memory tools** | `grok mcp add` → cloud MCP endpoint | The server lists the toolset your key is entitled to — `search_brain`, `search_history`, the save tools, `list_brain`, `get_record`, `delete_record`, `cleanup_history`, etc. |
| **Pull-model recall** | Global rule in `~/.grok/rules/` | Grok is taught to call `search_brain`/`search_history` itself (grok has no context-injection channel) |
| **Turn archival** | Native Stop hook in `~/.grok/hooks/` | Each session's transcript archived to chat memory |
| **`/recall` `/curate` `/onboard`** | Skills copied to `~/.grok/` | Slash commands for memory management |

## Install

### Option A: Automated (recommended)

```bash
# From this adapter directory:
python setup.py
```

The setup script:
1. Adds the `brethof-brain` HTTP MCP server to `~/.grok/config.toml` via `grok mcp add`
2. Installs the NATIVE Stop-hook archiver (`~/.grok/hooks/`) + the pull-model
   memory rule (`~/.grok/rules/brethof-brain-memory.md`)
3. Copies the `/recall` `/curate` `/onboard` skills to `~/.grok/skills/`

You'll need your **API key** from [brethof.ai/account](https://brethof.ai) →
brethof-brain tab. Set it in the environment:

```
BRETHOF_BRAIN_API_KEY=bm_live_your_key
BRETHOF_BRAIN_ENDPOINT=https://api.brethof.cloud   # optional, this is the default
```

### Option B: Manual

**1. Add the MCP server** (gives Grok the memory tools):

```bash
grok mcp add --transport http brethof-brain https://api.brethof.cloud/v1/mcp \
  --header "Authorization: Bearer bm_live_YOUR_KEY"
```

**2. Install the native hooks + rule** (do NOT rely on `~/.claude/settings.json`
— Claude-style hooks verifiably cannot fire in grok; see the note at the top).
Run `python setup.py` for this part even if you added the MCP server manually,
or hand-create `~/.grok/hooks/brethof-brain.json` (Stop → `grok_hook.py stop`)
and `~/.grok/rules/brethof-brain-memory.md` from this adapter.

```bash
grok mcp doctor    # should show brethof-brain: ✓ handshake OK, tools discovered
```

**3. Copy skills** (optional — adds `/recall` `/curate` `/onboard`):

```bash
cp -r skills/* ~/.grok/skills/
```

## Verify

```bash
# MCP tools reachable?
grok mcp doctor

# In a Grok session, the agent should be able to call:
#   search_brain("your topic")    — saved memory: the current truth
#   search_history("exact string") — full conversation history, raw
#   save_project("fact", project)  — save one durable fact (the service
#                                    files it; memory also learns from
#                                    every exchange automatically)
```

## How it works

Memory INJECTION is replaced by the PULL model: grok has no working
context-injection channel, so a global rule (`~/.grok/rules/`) teaches the
agent to call `search_brain`/`search_history` itself. Turn ARCHIVAL is a
native grok Stop hook (`~/.grok/hooks/brethof-brain.json` → `grok_hook.py`)
that ships grok's own `updates.jsonl` transcript to the cloud API with your
key. On Windows the hook runs through a `.cmd` wrapper because grok's spawner
breaks on quoted inline commands.

The MCP server is added separately via `grok mcp add` because Grok has its own
MCP server registry in `~/.grok/config.toml` (it doesn't read `.mcp.json` from
the Claude Code plugin).

## Custom models (e.g. local GLM via Ollama)

Grok Build supports custom models via `~/.grok/config.toml`. Memory works the
same regardless of model — the hooks and MCP tools are model-agnostic.

```toml
[model."glm-5.2-cloud"]
model = "glm-5.2:cloud"
base_url = "http://localhost:11434/v1"
name = "GLM 5.2 Cloud (Ollama)"
api_key = "ollama"
context_window = 1000000

[models]
default = "glm-5.2-cloud"
```

## Notes

- Grok Build's `grok mcp doctor` is the fastest way to verify connectivity.
- The hooks are **fail-open**: if the cloud is unreachable, Grok continues
  normally without memory (no session blocking).
- The `BRETHOF_BRAIN_API_KEY` environment variable is read by the Stop-hook
  archiver; the MCP server uses the key embedded in the `grok mcp add` command.
- If you also run Claude Code on the same machine, set
  `[compat.claude] hooks = false` in `~/.grok/config.toml` — the Claude-sourced
  hook entries fail inside grok and only add log noise. Both agents can still
  archive to the same memory (each through its own working hook path).