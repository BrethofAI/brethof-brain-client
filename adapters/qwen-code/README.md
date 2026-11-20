# brethof-brain + Qwen Code

Qwen Code ships a full hook system (well beyond its Gemini-CLI ancestry) —
so it gets the **complete** brethof-brain contract:

| Hook | When | Effect |
|---|---|---|
| `SessionStart` | once per session | your memory brain block injected as context |
| `UserPromptSubmit` | every prompt | ambient recall relevant to what you asked |
| `Stop` | end of each reply | the turn archived into long-term memory |

Plus the Brain's MCP tools via Qwen Code's MCP support and
a short memory section in `~/.qwen/QWEN.md`.

## Install

```bash
pip install "git+https://github.com/BrethofAI/brethof-brain-client.git"
brethof-brain pair http://127.0.0.1:8600   # your hub; or https://<your hub>
python3 setup.py                           # from this directory
```

`pair` shows a code; approve it on the hub's settings page, and the device
key lands in `~/.brethof-brain/config.json` (never printed).

The setup script merges hooks + the `brethof-brain` MCP server into
`~/.qwen/settings.json` (existing settings kept) and appends the memory
section to `~/.qwen/QWEN.md` (marker-guarded, idempotent).

The MCP server is a stdio entry running `plugin/mcp_bridge.py`, which reads
the hub and key from `config.json` on every request — no key sits in
`settings.json`. The hooks read the same file; `BRETHOF_BRAIN_*` environment
variables override it.

## Uninstall

Remove the `brethof-brain` entries from `~/.qwen/settings.json` and the
marked section from `~/.qwen/QWEN.md`.

## Notes

- Hooks are fail-open — if the Brain is unreachable your session runs
  normally, just without memory.
- Python 3.9+ on PATH is the only dependency.
