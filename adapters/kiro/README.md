# brethof-brain for Kiro CLI (AWS)

Kiro CLI adds a hook's plain output to the agent's context, and its hooks
live in an agent file. The setup writes a `brethof-brain` agent — every tool,
like Kiro's default — with three hooks, and makes it your default agent:

- **Session brief** — `agentSpawn` injects your project's memory.
- **Ambient recall** — `userPromptSubmit` pulls the matching memory in ahead
  of every answer.
- **Archive** — `stop` ships the turn to your Brain's complete chat archive:
  the prompt kept at prompt-submit and the reply from `assistant_response`.

Every hook is fail-open: if the Brain is unreachable, Kiro just runs.

## Install

```bash
git clone https://github.com/BrethofAI/brethof-brain-client ~/brethof-brain-client
python3 ~/brethof-brain-client/adapters/kiro/setup.py
```

The key comes from `~/.brethof-brain/config.json` or `BRETHOF_BRAIN_API_KEY`.
The agent is `~/.kiro/agents/brethof-brain.json`; the setup runs
`kiro-cli agent set-default brethof-brain` for you. To use memory with
another agent of yours, copy its `hooks` block into that agent. Re-running
is safe.
