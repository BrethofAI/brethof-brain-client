# brethof-brain for Pi

Long-term memory for [Pi](https://pi.dev) as one in-process extension — the
same on Linux, macOS and Windows:

- **Session brief** — a system-prompt section from your memory, once per session.
- **Ambient recall** — the records that bear on each prompt, before the model answers.
- **Archive** — every run's user and assistant messages land in your memory.

Fail-open: a memory that cannot be reached never blocks Pi.

## Install

```bash
pi install npm:brethof-brain-pi
```

Then connect this computer to your memory once — a window on your screen takes
the API key (and a hosted memory's passphrase); your agent never sees them:

```bash
pip install git+https://github.com/BrethofAI/brethof-brain-client.git
brethof-brain connect
```

The key and address are read from `~/.brethof-brain/config.json` (what
`connect` saves) or the environment (`BRETHOF_BRAIN_API_KEY`,
`BRETHOF_BRAIN_ENDPOINT`, `BRETHOF_BRAIN_PROJECT`,
`BRETHOF_BRAIN_UNLOCK_PASSPHRASE`). Sign up at
[brethof.ai/brain](https://brethof.ai/brain/).
