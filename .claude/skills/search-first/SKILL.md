# Search-First: Code Retrieval Loop

## Default behavior

When you need to read code, go through search → get_code. This is the default path.

Read is reserved for: `config/*.php`, `.env*`, database migrations (`database/migrations/`),
vendor files (`vendor/`), package manifests (`composer.json`, `package.json`, `package-lock.json`),
generated files, and anything outside the indexed source paths
(`app/`, `tests/`, `database/upgrade_tasks/`, `database/factories/`, `routes/`).

When in doubt: call `search_code` first. If it returns no relevant hits after 1–2 rephrased
queries, then Read is appropriate.

## Zoom levels

Use these tools in order of specificity:

1. `get_project_structure()` — project-level orientation: which subsystems, directories, classes exist
2. `search_code(query)` — find chunks by semantic query; returns chunk_ids + snippets
3. `search_symbol(name)` — find chunks by class or method name; always returns full code
4. `get_file_chunks(filename)` — file-level orientation: list all chunks + their symbols/locations
5. `get_code(chunk_id)` — read one chunk's full body; no re-embedding, no waste
6. `find_similar_to(chunk_id)` — lateral discovery from a chunk you already hold

## The read loop

### Finding code

1. `search_code(query, top_k=5)` — read snippets, chunk_ids, doc_summaries, layer_type
2. Identify the 1–3 chunks that actually matter
3. `get_code(chunk_id)` for each — one call per body, full implementation returned

Raise `top_k` (to 10–20) for exploratory orientation queries where you don't yet know
the codebase structure. Keep it at 5 for targeted lookups where you know what you want.

### Modifying code

1. `search_code(query, top_k=5)` — identify relevant chunks
2. `get_code(chunk_id)` for the chunks you'll modify
3. `get_file_chunks(filename)` for **every file you'll modify** — understand what else is in
   the file before changing it. This catches observers, traits, hooks, and interface
   obligations that interact with the method you're changing.
4. Make changes

Step 3 is mandatory for modification tasks, not optional.

### Exploring a pattern across the codebase

1. `search_code(query)` — find one canonical example
2. `get_code(chunk_id)` — read it
3. `find_similar_to(chunk_id, layer_type="service")` — find other implementations of the
   same pattern, scoped to the same layer type
4. `get_code(chunk_id)` for the ones that differ in interesting ways

## When to use `find_similar_to`

Use it when:
- You're refactoring a pattern and need to find other places that follow it
- You've found a bug-prone implementation and want to check whether similar code has the same issue
- You want to understand codebase conventions by example before writing new code

Don't use it as a substitute for `search_code` with a clear query. If you can name what
you're looking for, search for it. `find_similar_to` is for "find me more of what I already
have" — it can't help you find what you haven't found yet.

Default `min_score=0.5` is intentional. Results below 0.5 are usually noise (boilerplate
similarity rather than semantic similarity). If you lower it, expect many false positives
from Eloquent model boilerplate.

## When search fails

If `search_code` returns no relevant hits:
1. Rephrase and try again — embeddings are sensitive to phrasing. Try synonyms or describe
   the behavior rather than the name: "billing retry" instead of "RetryBillingJob".
2. After 1–2 rephrased queries with no hits, the code may not be indexed. Use Read on the
   most likely file path.
3. If you have no candidate file, ask the user.

Do not loop on empty results. Two focused queries are enough before switching to Read.

## Stale index

The index updates via `make cocoindex-index` (CocoIndex) and `make qdrant-index` (Qdrant).
Staleness is **silent** — search returns old chunks with old line numbers, `get_code` returns
the old code from the DB, and the agent has no way to detect this automatically.

Practical guidance: if you know you've just edited a file in this session, do not trust
search results for that specific file. Use `Read` directly on files you've just modified.
Do not try to detect staleness from search results alone — you can't.

## Anti-patterns (never do these)

- `search_code(..., include_code=True)` — costs tokens on all results to get one body.
  Use `get_code(chunk_id)` instead.
- `Read(source_file)` when you have a chunk_id in hand — `get_code` is cheaper and
  returns exactly the chunk you identified.
- Calling `search_code` a second time to "get the full code" for a result you already have.
  You have the chunk_id. Call `get_code`.
- Using `find_similar_to` instead of `search_code` when you have a clear query — similarity
  search from an anchor finds neighboring embeddings, not the best match for a concept.

## Tool quick-reference

| Tool | When |
|------|------|
| `search_code(query, top_k=5)` | Default first step. Find by concept. |
| `search_symbol(name)` | Know a class or method name. Returns full code. |
| `get_code(chunk_id)` | Read a body you've already located. Always use this over Read. |
| `get_file_chunks(filename)` | Understand file structure before modifying. |
| `find_similar_to(chunk_id)` | Find related implementations from a known example. |
| `get_project_structure()` | Orient at project level. Use when you don't know where to start. |
| `Read` | Config, migrations, vendor, generated, unindexed files only. |
