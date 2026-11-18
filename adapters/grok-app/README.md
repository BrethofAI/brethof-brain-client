# Grok Build in Grok App, with Brethof Brain memory

[Grok App](https://github.com/RongleCat/grok-app) is a desktop GUI for xAI's
Grok Build. It runs `grok agent stdio` and talks to it over the Agent Client
Protocol (ACP). `brethof-brain-acp` sits in between: Grok App starts it in
place of `grok`, and it starts the real `grok`.

What it adds:

- **Before every prompt reaches Grok:** the memory's recall for that prompt.
  The first prompt of a session also gets the project's brief.
- **After every turn:** your words and Grok's reply go to the memory's archive.
- **When Grok App closes:** the session's waiting turns are handed over.

Everything else passes through untouched, so Grok App and Grok Build both keep
updating on their own. If the memory is unreachable, Grok works as if this
weren't there.

## Set up

```bash
pip install brethof-brain-client
brethof-brain pair <your hub>      # once per machine
brethof-brain grok-app             # writes the launcher, sets Grok App's CLI path
```

Restart Grok App. If its settings weren't found, set the path shown by hand,
under Grok App → Settings → Runtime → CLI path.

`brethof-brain grok-app --undo` puts Grok App back on Grok Build directly.

The project is chosen from each session's folder, the same way as for every
other agent.
