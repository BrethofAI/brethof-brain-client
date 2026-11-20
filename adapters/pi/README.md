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

Then connect this computer to your hub once — `pair` shows a code, you approve
it on the hub's settings page, and the device key is saved without being shown;
your agent never sees it:

```bash
pip install "git+https://github.com/BrethofAI/brethof-brain-client.git"
brethof-brain pair http://127.0.0.1:8600   # or https://<your hub>
```

The key and address are read from `~/.brethof-brain/config.json` (what
`pair` saves); the environment overrides it (`BRETHOF_BRAIN_API_KEY`,
`BRETHOF_BRAIN_ENDPOINT`, `BRETHOF_BRAIN_PROJECT`).
