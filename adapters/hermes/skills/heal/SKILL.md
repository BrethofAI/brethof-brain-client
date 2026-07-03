---
name: heal
description: "Deep brethof-mind maintenance: dedupe, resolve contradictions, fix stale state/indexes, delete dead records. Run about weekly — /curate covers one session, /heal covers everything since the last heal. Trigger on: heal memory, clean up memory, dedupe memory, memory maintenance."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [memory, heal, brethof-mind, hygiene]
    related_skills: [curate]
---

# Heal — deep brethof-mind maintenance

`/curate` covers one session; `/heal` covers everything that accumulated between
heals. Be thorough and DECISIVE — this is what stops memory rot. Ask the user
only where two records genuinely conflict and the truth isn't decidable from
provenance. (Embeddings and storage are handled server-side — there are no local
scripts; work through the tools.)

## Your tools
- `brethofmind_search(query)` — curated memory; results start with `table:key`.
- `brethofmind_recall(query)` — the chat archive.
- `brethofmind_save(...)` — UPSERT (merge/update in place).
- `brethofmind_delete(project, record_id)` — remove a dead record.

## Steps
1. **Find duplication + contradiction.** `brethofmind_search` each project's key
   topics and its `memory_index`; surface pairs with near-identical titles or
   claims. Build a candidate list.
2. **Dedupe + contradictions** — for each pair:
   - Same fact twice → MERGE into the record with the better id/provenance
     (`brethofmind_save` it with anything unique from the other), then
     `brethofmind_delete` the loser.
   - Contradiction → the newer / better-sourced record wins; delete the old one.
     If genuinely undecidable, ask the user.
   - Related but distinct → leave them.
3. **State dashboard** — for each `state` row, check the project's recent records:
   does the status still describe reality? Fix stale ones; prune finished
   `open_loops`.
4. **Indexes** — the general `memory_index` and each project's: do they still map
   what exists? Update where drifted — the index is the router.
5. **Aging** — sample long-untouched records per project: dead / superseded →
   DELETE; still-true reference → keep. Never delete `*_chat`.
6. **Report** — N merged, M deleted, contradictions resolved, index/state fixes,
   and any open questions for the user.
