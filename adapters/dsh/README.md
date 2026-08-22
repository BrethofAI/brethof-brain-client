# brethof-brain cloud + DeepSeek Harness (dsh)

A **native cordis plugin** — the full brethof-brain contract on dsh's own
typed extension points:

| Extension point | Effect |
|---|---|
| `agent/session-start` | your memory brain block injected before turn 1 |
| `agent/pre-step` | ambient recall relevant to each prompt, added to the entered batch |
| `agent/turn-stopping` | the turn (user + assistant) archived into long-term memory |

Every listener is fail-open: memory can never break a run.

## Why native (not the Claude-Code hooks bridge)

dsh ships `@deepseek-ai/dsh-hooks-claude-code`, and it does run our hook
set — but two dsh design decisions cap what a bridge can deliver
(both measured 2026-08-22):

- dsh executes hooks through `ctx.shell`, whose **credential scrub strips
  `*_API_KEY`** from hook process environments — env-configured hooks
  silently run keyless.
- At `Stop`, the persisted transcript **deliberately omits the open
  turn** — a transcript-reading archiver can never see the exchange it is
  supposed to archive.

dsh's own design notes say bespoke integrations belong on the typed
extension points. This plugin is that.

## Install

```sh
# 1. Your key lives in the config FILE (the env var would be scrubbed):
mkdir -p ~/.brethof-brain
cat > ~/.brethof-brain/config.json <<EOF
{"api_key": "bm_live_YOUR_KEY", "default_project": "myproject"}
EOF

# 2. Install the plugin into your profile (from npm):
dsh plugin --profile <name> add brethof-brain-dsh

# 3. Register it — add to $DSH_HOME/profiles/<name>/cordis.patch.yml:
#    (new rows use the patch layer's `insert` form)
- insert:
    - id: brethof-brain
      name: brethof-brain-dsh
```

Restart the profile. Verify like every other platform: ask the agent to
search memory — a well-formed answer, even "no results", means connected.

Optional row config (all default from `~/.brethof-brain/config.json`):

```yaml
- insert:
    - id: brethof-brain
      name: brethof-brain-dsh
      config:
        endpoint: https://api.brethof.cloud
        project: myproject
```

## Notes

- Proven by the harness rig on dsh 0.1.1-rc.2 (fresh container, newest
  release, judged server-side by the Brain itself).
- dsh is a developer preview and its APIs move; the weekly rig run is what
  catches drift.
- The archive index is per-session and the server UPSERTs on
  `(session_id, index, text)` — replays are idempotent; transient outages
  defer turns in memory and retry on the next turn's archive call.
