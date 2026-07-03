---
name: curate
description: "Distil the current session into brethof-mind memory: capture decisions/facts/gotchas, update state dashboards, prune stale records. Run before compacting or at the end of a work session. Trigger on: curate, save to memory, update memory, end of session."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, curate, brethof-mind, hygiene]
    related_skills: []
---

# Curate — distil this session into brethof-mind memory

brethof-mind is shared long-term memory you use exactly like Claude. This distils
a session into it so the next one resumes cleanly — and prunes what went stale.
Capturing too little and deleting too little are BOTH failures; under-deletion is
the worse, recurring one. Curated memory is disposable — only `*_chat` archives
are immutable. A dead record is a DELETED record.

## Your tools
- `brethofmind_search(query)` — find existing records across all projects. Each
  result STARTS with its full id `table:key` — use that id to update or delete it.
- `brethofmind_save(title, content, memory_type, project, record_id)` — UPSERT.
  `project` = the table it belongs to (a project key, or `state` / `rules`). Pass a
  STABLE `record_id` to update-in-place; omit for a new auto-id record.
- `brethofmind_delete(project, record_id)` — delete a stale/superseded record.
- `brethofmind_recall(query)` — search past sessions (read-only).

## Steps
1. **Navigate from the indexes.** `brethofmind_search("memory_index")` — follow the
   project index maps; don't guess tables or reinvent records.
2. **Walk the WHOLE session, group by the PROJECT each thing belongs to.** Capture
   GENEROUSLY: every decision, correction, fact figured out, gotcha, runbook,
   dead-end ruled out, key file/path, and the WHY behind a choice. A future agent
   should resume cold from what you write.
3. **For each touched project:**
   - **state** — UPSERT one row: `project="state"`, `record_id="<project-or-area>"`,
     with a `status` line, a dated note in `recent_changes`, and `next_actions`.
   - **knowledge** — save genuinely new decisions/facts/runbooks/gotchas to that
     project's table: `project="<key>"`, a STABLE `record_id`, the right
     `memory_type`. SEARCH FIRST — update-in-place, never duplicate.
   - **index** — if you added or renamed records, update `project="<key>"`,
     `record_id="memory_index"` so it still maps reality.
   - **rules** — a new convention the user gave → `project="rules"`.
4. **DELETE — be confident; this is the step agents wrongly skip.** Anything this
   session made false or superseded → `brethofmind_delete` it. Collapse standalone
   status snapshots into the `state` row, then delete the snapshots. Dedupe two
   records that say the same thing. NEVER delete `*_chat` (the tool blocks it).
5. **Report** a short per-project summary: state/index updated · N saved · **M DELETED**.
