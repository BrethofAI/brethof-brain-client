# brethof-mind cloud — test container

A small **containerized integration test** for brethof-mind cloud. It stands in
for an OpenClaw-style deployment: a headless, non-Claude-Code Python agent that
talks to the live service from inside Docker. Use it to confirm the whole path —
auth, the customer MCP tools, and turn archival — works from a clean container, on any
host, before shipping.

> Scope note: this is a **test harness**, not a production OpenClaw integration.
> It proves containerized/non-interactive agents can use brethof-mind cloud via
> the same `MindClient` programmatic API any Python agent would use.

## Run it

With Docker Compose (from the repo root):

```bash
BRETHOF_MIND_API_KEY=bm_test_xxxxxxxx \
  docker compose -f test-container/docker-compose.yml up --build
```

Or plain Docker:

```bash
docker build -f test-container/Dockerfile -t brethof-mind-smoke .
docker run --rm -e BRETHOF_MIND_API_KEY=bm_test_xxxxxxxx brethof-mind-smoke
```

Point it at a staging endpoint with `BRETHOF_MIND_ENDPOINT`, and pick the tenant
project with `BRETHOF_MIND_PROJECT` (default `global`).

## What it checks

`smoke_test.py` runs, in order:

1. **MCP transport** — `tools/list` returns all 15 tools.
2. **Auth** — `usage()` succeeds and reports a plan.
3. **Write→read** — `save_memory` then `get_memory` round-trip.
4. **Recall** — `recall()` finds the just-written probe.
5. **Archive** — `archive_turns()` stores two turns and returns `status: ok`.

It prints a `PASS`/`FAIL` line per check and exits non-zero if any fail, so it
drops straight into CI. The probe record and turns use fixed ids (UPSERT), so
re-running is idempotent.
