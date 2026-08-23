# brethof-brain for Cascade (Windsurf / Devin Desktop)

**Archive adapter.** Cascade's hooks are capture-only by design — no event
can inject context and there is no session-start — but after every agent
response `post_cascade_response_with_transcript` hands over the **full
conversation transcript**, and this adapter ships it to your Brain's
complete chat archive.

Memory here is the pull model: add the MCP block from
[`adapters/editors/README.md`](../editors/README.md) for the tool doors
(`search_brain`, saves, ledger, playbooks) and a memory rule in
`~/.codeium/windsurf/memories/global_rules.md` teaching the agent to search
before claiming ignorance. The archive half — every exchange kept, in full,
forever searchable — is what this hook does, silently.

Every hook is fail-open: if the Brain is unreachable, Cascade just runs.

## Install

1. Get the client next to the hook (either works):
   ```bash
   pip install brethof-brain-client
   ```
   or run straight from a checkout of this repo — the hook bootstraps its
   own `sys.path`.

2. Copy `hooks.json.example` into `~/.codeium/windsurf/hooks.json` (all
   workspaces) or `<repo>/.windsurf/hooks.json` (one workspace), fixing the
   absolute path to `cascade_hook.py`. (On Windows use a `"powershell"`
   command instead of `"command"` — Cascade runs those via PowerShell.)

3. Configure the key — `~/.brethof-brain/config.json`:
   ```json
   {
     "api_key": "bm_live_...",
     "endpoint": "https://api.brethof.cloud",
     "default_project": "my-project"
   }
   ```
   Environment variables override the file: `BRETHOF_BRAIN_API_KEY`,
   `BRETHOF_BRAIN_ENDPOINT`, `BRETHOF_BRAIN_PROJECT`.

## Troubleshooting

`BRETHOF_BRAIN_HOOK_DEBUG=1` makes the hook print tracebacks to stderr
instead of failing silently (pair with `"show_output": true` in hooks.json
to see them in the Cascade UI).
