---
description: Curate this session into brethof-mind — save decisions, prune what's superseded, update indexes/state/open-loops
---
Curate this session into memory. Be THOROUGH, and be DECISIVE about deletion.
This is what stops you having to remember everything — and what stops memory
from rotting. Capturing too little and deleting too little are BOTH failures.
Curated memory is DISPOSABLE: the only protected store is the `*_chat` archive
(never delete/overwrite it); delete freely from every other table. There is no
"obsolete" flag — a dead record is a DELETED record.

0. **Recover the whole session.** Review this conversation in context. If it was
   compacted and the early half is gone, rebuild it with `search_chat` /
   `search_chat_text` (your session's turns are archived server-side) — curate
   from THAT, not only from what survives in context.
1. Read the GENERAL index (`get_memory global:memory_index`) and, for each area
   you touched, that project's own index (`get_memory <project>:memory_index`).
   Navigate from them — do not guess.
2. Walk the WHOLE session and group what happened by AREA. Capture GENEROUSLY:
   every decision, correction, fact figured out, gotcha, runbook, dead-end ruled
   out, key file/path, and the "why" behind a choice. A future session should be
   able to resume cold from what you write.
3. For EACH touched area:
   - **state** — UPSERT `state:<area>` (one row, stable id, never fork) with
     `save_memory` (record_id = the area): refreshed `status`, prepend a dated
     one-line `recent_changes`, `next_actions`.
   - **knowledge** — save genuinely new decisions / facts / runbooks / gotchas
     to that area's table. Search first (`recall`/`search_memory`); update in
     place, never duplicate. Link related records with `[[other-id]]`.
   - **index** — if you added/renamed records or changed an area's shape, update
     that `<project>:memory_index` so it still maps reality.
   - **rules** — a new correction/convention → save into `rules` (`area`).
4. **DELETE — be confident.** Anything this session made false or superseded →
   `supersede_memory` (keeps lineage) or delete via `query_raw` (`DELETE
   table:id;`). Dedupe: two records saying the same thing → merge into one,
   delete the other. Never delete from `*_chat`.
5. **Open loops** — update `state:open_loops` (a markdown checklist, HARD CAP 10
   lines, each line one thread + its record id): REMOVE loops closed this
   session; ADD promises made and threads left hanging. This is what the next
   session picks up first.
6. **Report** a short per-area summary: state/index updated · N saved ·
   **M deleted** · open loops now (count).
