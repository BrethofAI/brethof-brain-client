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
pip install "git+https://github.com/BrethofAI/brethof-brain-client.git"
brethof-brain pair http://127.0.0.1:8600   # or https://<your hub>
git clone https://github.com/BrethofAI/brethof-brain-client ~/brethof-brain-client
python3 ~/brethof-brain-client/adapters/goose/setup.py
```

The setup writes `~/.agents/plugins/brethof-brain/hooks/hooks.json` and adds
`GOOSE_MOIM_MESSAGE_FILE=~/.brethof-brain/goose-turn.md` to your shell profile
(bash, zsh, fish; your user environment on Windows) — open a new terminal
afterwards. On Windows, goose needs Microsoft's Visual C++ runtime
(`vc_redist.x64.exe` from aka.ms/vs/17/release) and Git Bash on PATH (goose
runs hooks through `sh`). `pair` shows a code; approve it on the hub's settings page, and the device
key lands in `~/.brethof-brain/config.json` (never printed) — the file the
hooks read. `BRETHOF_BRAIN_*` environment variables override it. Re-running is safe.
