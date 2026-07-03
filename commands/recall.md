---
description: Recall from brethof-mind using vector + graph + keyword (not just keyword)
argument-hint: <topic or question>
---
Recall everything relevant to: $ARGUMENTS

1. **Start with `recall`** — the hybrid search: vector + keyword over curated
   memory AND the full chat archive in one fused, ranked list.
2. Follow up with single-mode tools where the fused list points:
   - **search_chat_text / search_memory** (BM25) — EXACT strings the query
     didn't surface: file paths, error messages, commit hashes, flags, names.
   - **semantic_search / search_chat** (vector) — rephrase and re-probe a
     specific angle in curated memory or past sessions.
   - **query_raw graph traversal** (`->refs`, `->edges`) — relationships:
     what references what, what supersedes what, parent/child links.
3. **get_memory(id)** — read the full records the searches surface (previews
   are truncated).

Then synthesize ONE grounded answer:
- Cite the record ids you used.
- Check provenance dates; flag anything that looks stale or volatile.
- If the answer isn't in memory, say so plainly — never assert memory contents
  from assumption.
