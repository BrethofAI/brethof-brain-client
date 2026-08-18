# brethof-brain cloud + Qwen Code

Qwen Code ships a full hook system (well beyond its Gemini-CLI ancestry) —
so it gets the **complete** brethof-brain contract:

| Hook | When | Effect |
|---|---|---|
| `SessionStart` | once per session | your memory brain block injected as context |
| `UserPromptSubmit` | every prompt | ambient recall relevant to what you asked |
| `Stop` | end of each reply | the turn archived into long-term memory |

Plus the Brain's MCP tools via Qwen Code's native `httpUrl` MCP support and
a short memory section in `~/.qwen/QWEN.md`.

## Install

```bash
export BRETHOF_BRAIN_API_KEY=bm_live_...   # your key
python3 setup.py                            # from this directory
```

The setup script merges hooks + the `brethof-brain` MCP server into
`~/.qwen/settings.json` (existing settings kept) and appends the memory
section to `~/.qwen/QWEN.md` (marker-guarded, idempotent).

Keep `BRETHOF_BRAIN_API_KEY` exported wherever you run `qwen` — the hooks
read it from the environment; the MCP header carries it for the tools.

## Uninstall

Remove the `brethof-brain` entries from `~/.qwen/settings.json` and the
marked section from `~/.qwen/QWEN.md`.

## Notes

- Hooks are fail-open — if the Brain is unreachable your session runs
  normally, just without memory.
- Python 3.9+ on PATH is the only dependency.
