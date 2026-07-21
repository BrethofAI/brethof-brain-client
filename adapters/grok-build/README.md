# brethof-mind cloud + Grok Build

Grok Build (xAI's open-source coding CLI) is **Claude Code-compatible**: it
reads `~/.claude/settings.json` for hooks and `.claude/CLAUDE.md` for system
prompts. It also has its own `grok mcp` command for MCP server management.

This adapter wires Grok Build to brethof-mind cloud so it gets the same memory
as Claude Code and Hermes: **auto-recall at session start, ambient recall before
each prompt, archiving every turn, and 15 memory tools on demand**.

## What you get

| Feature | How | Effect |
|---|---|---|
| **Session-start injection** | `~/.claude/settings.json` hooks → cloud API | Memory index + rules + state loaded into system prompt |
| **Ambient recall** | `~/.claude/settings.json` hooks → cloud API | Relevant memory injected before each prompt |
| **Turn archival** | `~/.claude/settings.json` hooks → cloud API | Each user+assistant turn archived to chat memory |
| **15 memory tools** | `grok mcp add` → cloud MCP endpoint | `recall`, `search_memory`, `semantic_search`, `save_memory`, `list_memory`, `get_memory`, `memory_health`, etc. |
| **`/recall` `/curate` `/heal` `/onboard`** | Skills copied to `~/.grok/` | Slash commands for memory management |

## Install

### Option A: Automated (recommended)

```bash
# From this adapter directory:
python setup.py
```

The setup script:
1. Adds the `brethof-mind` HTTP MCP server to `~/.grok/config.toml` via `grok mcp add`
2. Verifies the Claude Code hooks in `~/.claude/settings.json` are wired (Grok reads these)
3. Copies the `/recall` `/curate` `/heal` `/onboard` skills to `~/.grok/skills/`

You'll need your **API key** from [brethof.ai/account](https://brethof.ai) →
brethof-mind tab. Set it in the environment:

```
BRETHOF_MIND_API_KEY=bm_live_your_key
BRETHOF_MIND_ENDPOINT=https://api.brethof.cloud   # optional, this is the default
```

### Option B: Manual

**1. Add the MCP server** (gives Grok the 15 memory tools):

```bash
grok mcp add --transport http brethof-mind https://api.brethof.cloud/v1/mcp \
  --header "Authorization: Bearer bm_live_YOUR_KEY"
```

**2. Verify hooks** (Grok reads `~/.claude/settings.json` — the Claude Code
hooks fire automatically if already installed):

```bash
grok mcp doctor    # should show brethof-mind: ✓ handshake OK, 15 tools discovered
```

If the Claude Code hooks aren't installed yet, install the Claude Code plugin
first (`/plugin install brethof-mind@brethof` in Claude Code) or copy the hooks
from the root of this repo into `~/.claude/hooks/`.

**3. Copy skills** (optional — adds `/recall` `/curate` `/heal` `/onboard`):

```bash
cp -r skills/* ~/.grok/skills/
```

## Verify

```bash
# MCP tools reachable?
grok mcp doctor

# In a Grok session, the agent should be able to call:
#   recall("your topic")           — hybrid search curated + chat
#   search_memory("keyword")       — keyword search curated memory
#   semantic_search("concept")      — vector search curated memory
#   save_memory("title", "content") — save a new record
#   memory_health()                — check memory system health
```

## How it works

Grok Build shares Claude Code's hook infrastructure (`~/.claude/settings.json`),
so the brethof-mind hooks fire for both agents. The hooks call the cloud API
at `api.brethof.cloud` (or your self-hosted endpoint) with your API key.

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
- The `BRETHOF_MIND_API_KEY` environment variable is read by the hooks; the
  MCP server uses the key embedded in the `grok mcp add` command.
- If you use both Claude Code and Grok Build on the same machine, they share
  the same hooks — turns from both agents are archived to the same memory.