# brethof-brain + OpenAI Codex CLI

Codex (v0.124+) ships a full hook system with the same shape as Claude
Code's — which means Codex gets the **complete** brethof-brain contract:

| Hook | When | Effect |
|---|---|---|
| `SessionStart` | once per session | your memory brain block injected as context |
| `UserPromptSubmit` | every prompt | ambient recall relevant to what you asked |
| `Stop` | end of each reply | the turn archived into long-term memory |

Plus the Brain's MCP tools (`search_brain`, the save tools, …) via Codex's
MCP support, and a short memory section in `~/.codex/AGENTS.md`.

## Install

```bash
pip install "git+https://github.com/BrethofAI/brethof-brain-client.git"
brethof-brain pair http://127.0.0.1:8600   # your hub; or https://<your hub>
python3 setup.py                           # from this directory
```

`pair` shows a code; approve it on the hub's settings page, and the device
key lands in `~/.brethof-brain/config.json` (never printed).

The setup script:
1. Merges the three hooks into `~/.codex/hooks.json` (existing hooks kept).
2. Registers the `brethof-brain` MCP server in `~/.codex/config.toml` as a
   stdio entry running `plugin/mcp_bridge.py` — the bridge reads the hub and
   key from `config.json` on every request, so no key enters the file.
3. Appends the memory section to `~/.codex/AGENTS.md` (marker-guarded,
   idempotent).

Both the hooks and the MCP bridge read `~/.brethof-brain/config.json`;
`BRETHOF_BRAIN_*` environment variables override it. Re-pairing needs no
re-run of the setup.

## Uninstall

Remove the `brethof-brain` entries from `~/.codex/hooks.json` and
`~/.codex/config.toml`, and the marked section from `~/.codex/AGENTS.md`.

## Notes

- Hooks are fail-open: if the Brain is unreachable, your session runs
  normally without memory — never blocked.
- Python 3.9+ on PATH is the only runtime dependency (the hooks use the
  plugin's bundled client package; pip is only for the `pair` command).
- **Codex on an Ollama model:** Codex hands the memory to the model as
  developer context, and Ollama's OpenAI-compatible Responses endpoint
  currently drops developer messages (seen on Ollama 0.32.13 and 0.35.0,
  2026-09-30), so the model never sees it. With OpenAI's models, or any
  Responses provider that keeps developer messages, it arrives as normal.
