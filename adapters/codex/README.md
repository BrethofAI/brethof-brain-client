# brethof-brain cloud + OpenAI Codex CLI

Codex (v0.124+) ships a full hook system with the same shape as Claude
Code's — which means Codex gets the **complete** brethof-brain contract:

| Hook | When | Effect |
|---|---|---|
| `SessionStart` | once per session | your memory brain block injected as context |
| `UserPromptSubmit` | every prompt | ambient recall relevant to what you asked |
| `Stop` | end of each reply | the turn archived into long-term memory |

Plus the Brain's MCP tools (`search_brain`, the save tools, …) via Codex's
native HTTP MCP support, and a short memory section in `~/.codex/AGENTS.md`.

## Install

```bash
export BRETHOF_BRAIN_API_KEY=bm_live_...   # your key
python3 setup.py                            # from this directory
```

The setup script:
1. Merges the three hooks into `~/.codex/hooks.json` (existing hooks kept).
2. Registers the `brethof-brain` HTTP MCP server in `~/.codex/config.toml`
   with `bearer_token_env_var = "BRETHOF_BRAIN_API_KEY"` — the key itself
   never enters the file.
3. Appends the memory section to `~/.codex/AGENTS.md` (marker-guarded,
   idempotent).

Keep `BRETHOF_BRAIN_API_KEY` exported in the shells you run `codex` from —
both the hooks and the MCP server read it from the environment.

## Uninstall

Remove the `brethof-brain` entries from `~/.codex/hooks.json` and
`~/.codex/config.toml`, and the marked section from `~/.codex/AGENTS.md`.

## Notes

- Hooks are fail-open: if the Brain is unreachable, your session runs
  normally without memory — never blocked.
- Python 3.9+ on PATH is the only dependency (the plugin bundles its own
  client package; no pip install).
