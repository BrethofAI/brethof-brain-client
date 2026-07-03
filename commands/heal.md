---
description: Deep brethof-mind heal — dedupe, contradictions, stale state, dead records. Run ~weekly.
---
Heal the WHOLE memory system. `/curate` covers one session; `/heal` covers
everything that accumulated between heals. Be thorough and DECISIVE — this pass
is what stops memory rot. Work through every step; report at the end; ask only
where two records genuinely conflict and the truth isn't decidable from
provenance. Everything here runs through the memory tools (the server handles
embeddings and storage — there are no local scripts to run).

0. **Baseline** — `memory_health()`. Note per-table records / embedded% /
   recalled% / stale counts; you'll report before/after.
1. **Find duplication + contradiction.** For each project table, surface likely
   pairs: `recall` / `semantic_search` on its own recent titles, and
   `query_raw` for same-area records with near-identical titles. Build the
   candidate-pair list that drives step 2.
2. **Dedupe + contradictions** — for each candidate pair, `get_memory 'a, b'`
   and judge:
   - Same fact twice → MERGE into the record with the better id/provenance
     (update its content with anything unique from the other), then
     `supersede_memory` the loser.
   - Contradiction → the newer / better-sourced record wins; `supersede_memory`
     the old one. If genuinely undecidable, add it to the report's questions.
   - Related but distinct → leave them; add `[[links]]` if useful.
3. **State dashboard** — for each `state:<area>` row, check the area's recent
   records (`recent_records` / `list_memory`): does the status line still
   describe reality? Fix stale ones. Prune `state:open_loops` of finished loops.
4. **Indexes** — the general `memory_index` and each project's: do they still
   map the tables/areas/records that exist? Update where drifted — the index IS
   the router; a stale index misroutes every future session.
5. **Aging** — from the baseline, sample-read stale (long-untouched) and
   never-recalled records per table and judge: dead / superseded-in-practice →
   DELETE (`supersede_memory` or `query_raw` DELETE; only `*_chat` is immutable);
   still-true reference → keep.
6. **Graph spot-check** — `get_memory` a few linked records; fix or drop broken
   `[[refs]]` (target deleted/renamed) while you're editing anyway.
7. **Report** — per-table before/after numbers, N merged, M deleted,
   contradictions resolved, index/state fixes, and any open questions.
