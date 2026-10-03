# brethof-brain for goose

goose runs hooks from a plugin folder but shows the model none of their
output; what reaches the model every turn is the file named by
`GOOSE_MOIM_MESSAGE_FILE`, read after the prompt hook runs. So:

- **Session brief** — kept at session start and written into that file with
  your first prompt.
- **Ambient recall** — every prompt writes the matching memory into the file
  (and empties it when there is nothing, so nothing stale repeats).
- **Archive** — `Stop` ships the turn — your prompt and the reply — to your
  Brain's complete chat archive.

Every hook is fail-open: if the Brain is unreachable, goose just runs.

## Install

```bash
git clone https://github.com/BrethofAI/brethof-brain-client ~/brethof-brain-client
python3 ~/brethof-brain-client/adapters/goose/setup.py
```

The setup writes `~/.agents/plugins/brethof-brain/hooks/hooks.json` and adds
`GOOSE_MOIM_MESSAGE_FILE=~/.brethof-brain/goose-turn.md` to your shell profile
(bash, zsh, fish; your user environment on Windows) — open a new terminal
afterwards. The key comes from `~/.brethof-brain/config.json` or
`BRETHOF_BRAIN_API_KEY`. Re-running is safe.
