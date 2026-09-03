# brethof-brain for Factory Droid

**There is no adapter code here — that's the point.** Factory Droid's hook
contract is exact Claude Code parity: same snake_case stdin fields
(`session_id`, `transcript_path`, `cwd`, `hook_event_name`, `prompt`),
same `hookSpecificOutput.additionalContext` output schema, same event
names. Our Claude Code hook module IS the Droid adapter:

- **Session brief** — `SessionStart` → injected context before turn 1.
- **Ambient recall** — `UserPromptSubmit` fires per prompt with the raw
  prompt; matching memory rides in ahead of the answer.
- **Archive** — `Stop` ships new transcript turns; `PreCompact` runs the
  archive-parity handshake before compaction, exactly as on Claude Code.

Every hook is fail-open: if the Brain is unreachable, Droid just runs.

## Install

1. ```bash
   pip install git+https://github.com/BrethofAI/brethof-brain-client.git
   ```

2. Copy `hooks.json.example` into `~/.factory/hooks.json` (all projects)
   or `<repo>/.factory/hooks.json` (one project). Timeouts are in
   **seconds** (Droid's convention; default 60).

3. Configure the key — `~/.brethof-brain/config.json`:
   ```json
   {
     "api_key": "bmv2_...",
     "endpoint": "http://127.0.0.1:8610",
     "default_project": "my-project"
   }
   ```
   Environment variables override the file: `BRETHOF_BRAIN_API_KEY`,
   `BRETHOF_BRAIN_ENDPOINT`, `BRETHOF_BRAIN_PROJECT`.

Works in the Droid CLI, the Factory desktop app, and `droid exec`
headless runs — they share the hooks system.

## Note on the transcript

Droid's `transcript_path` points at its `session.jsonl`. The archiver
feeds it to the same reader that parses Claude Code transcripts; if
Factory's line shape deviates, archiving degrades to a silent no-op
(fail-open) — set `BRETHOF_BRAIN_HOOK_DEBUG=1` to see the truth, and
report it so the reader learns the shape.
