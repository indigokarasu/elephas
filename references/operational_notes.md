# Elephas Operational Notes

Lessons from running `elephas.ingest.journals` and `elephas.consolidate.immediate` in production.

## LadybugDB API Quirks

### QueryResult is not subscriptable
`conn.execute()` returns a `QueryResult` object — you cannot do `result[0]`. Extract rows as a list first, then index:
```python
rows = list(conn.execute("MATCH (e:Entity) RETURN count(e) AS cnt"))
count = rows[0][0] if rows else 0
```

### "vector with ANY type" binding error — empty lists
LadybugDB fails with `"Trying to create a vector with ANY type"` when a JSON payload contains **empty lists `[]`** — even after `json.dumps()`. This silently causes all Signal writes to fail with no candidate created.

**Fix:** Strip empty lists from payloads before serialization:
```python
def clean_payload(payload):
    """Remove empty lists to avoid LadybugDB vector type errors."""
    if not isinstance(payload, dict):
        return payload
    cleaned = {}
    for k, v in payload.items():
        if isinstance(v, list) and len(v) == 0:
            continue  # skip empty lists — LadybugDB rejects them
        if v == "" or v is None:
            continue
        if isinstance(v, dict):
            cleaned[k] = clean_payload(v)
        else:
            cleaned[k] = v
    return cleaned

payload = clean_payload(raw_payload)
conn.execute("MERGE (s:Signal {id: $id}) ...", {
    "pl": json.dumps(payload),  # now safe to serialize
    ...
})
```

Also applies to `Candidate.proposed_data` — clean before `json.dumps()`.

### "vector with ANY type" binding error — complex nested objects
When passing complex nested JSON as MERGE parameters, LadybugDB may fail with `"Trying to create a vector with ANY type. Data type is expected to be resolved during binding."` **Fix:** Always `json.dumps()` complex objects before binding as parameters:
```python
# Wrong — causes vector type error:
conn.execute("MERGE (s:Signal {payload: $payload})", {"payload": sig_dict})

# Correct — store as JSON string:
conn.execute("MERGE (s:Signal {payload: $payload})", {"payload": json.dumps(sig_dict)})
```

### Candidate node has NO identity_state field
The promotion criteria reminder says `identity_state is 'distinct' or 'confirmed_same'` — but **`identity_state` only exists on Entity nodes, not on Candidate nodes**. Do NOT query Candidate.identity_state. For candidates, check for duplicate detection separately via name+type matching before creating candidates.

### Data format in stored fields
LadybugDB stores complex fields (like `Candidate.proposed_data`, `Entity.identifiers`) in its own internal format, **not standard JSON**. A field value like `{name: ollama-provider, type: Entity/AI, confidence: med}` will fail `json.loads()`. Always handle `json.JSONDecodeError` with a fallback:

```python
try:
    cand_data = json.loads(cand_data_raw)
except (json.JSONDecodeError, TypeError):
    cand_data = {"name": str(cand_data_raw)[:50] if cand_data_raw else "unknown"}
```

### show_tables() output
`CALL show_tables() RETURN *` returns rows as `[table_id, table_name, table_type, schema_name, '']`. The table name is at **index 1**, not index 0. String-matching on table names requires `row[1] == "Entity"`.

### MERGE pattern for idempotent writes
Always use `MERGE` on the primary key (`id` field) when writing Signals, Candidates, or entities to avoid duplicates on re-ingestion:
```python
# Wrong — causes "Cannot find property name" binder error:
conn.execute("CREATE (s:Signal {id: 'sig_xxx', name: 'sig_xxx'})")

# Correct — MERGE on id, then SET all properties:
conn.execute(f"MERGE (s:Signal {{id: '{sig_id}'}})")
conn.execute(f"""
    MATCH (s:Signal {{id: '{sig_id}'}})
    SET s.source_skill = '{source}',
        s.payload = '{payload_escaped}',
        s.user_relevance = '{relevance}',
        s.status = 'active'
""")
```

### Entity schema — NO `data` property
The `Entity` node has these properties only (from `references/schemas.md`):
`id, name, entity_type, aliases, identifiers, possible_matches, merge_history, identity_state, source_skill, record_time`

There is **no `data` property** on Entity nodes. If you try to SET `e.data = '...'`, you get `"Cannot find property data for e"`. Store all entity data in the explicit schema properties.

### Supports relationship has no `status` property
The `Supports` relationship edge table does not have a `status` property. Do NOT try to mark signals as consumed via:
```python
# Wrong — "Cannot find property status for sup":
conn.execute("MATCH (s:Signal)-[sup:Supports]->(c:Candidate {id: 'xxx'}) SET sup.status = 'consumed'")
```
Instead, just set `Candidate.status = 'confirmed'` and optionally track signal consumption via the signal's own `status` field.

### Read-only vs read-write connections
- Elephas (the sole writer): `lb.Database(DB_PATH, read_only=False)`
- All other skills: `lb.Database(DB_PATH, read_only=True)`
- Only one `READ_WRITE` connection at a time. Surface lock errors immediately.

### Correct Python import (this deployment)
The venv Python at `/root/.hermes/hermes-agent/venv/bin/python` uses:
```python
import real_ladybug as lb  # NOT: from ladybug import real_ladybug
```
Do NOT use `from ladybug import real_ladybug` — that module does not exist. Always use `import real_ladybug as lb`.

## Running complex operations

### Always clean stale ingestion log entries before re-ingesting
Failed runs write ingestion log entries with `signals_created: 0` (or > 0 if Signal write fails silently). Subsequent runs skip those files because their paths are already logged. **Always clean stale entries** before re-processing:

```python
# Clean stale entries (signals_created=0 from interrupted/failed runs)
kept = []
for line in open(INGESTION_LOG):
    e = json.loads(line)
    sc = e.get("signals_created", 0)
    ingested_at = e.get("ingested_at", "")
    is_today = ingested_at.startswith(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    # Remove entries where write actually failed (signals_created=0 on today's timestamp)
    if not (sc == 0 and is_today):
        kept.append(line)
with open(INGESTION_LOG, "w") as f:
    f.writelines(kept)
```

Additionally, when Signal writes fail silently (LadybugDB rejects the write but the ingestion log entry was written), you must manually remove those specific log entries so the files are re-ingested on the next run.

### Use script files, not inline terminal
Multi-step Chronicle operations (ingestion, consolidation) involve hundreds of lines of Python with complex data transformations. Writing these as Python script files (via `write_file` then `python3 script.py`) is far more reliable than trying to pass multi-line scripts through `terminal()` — shell quoting and escape issues make inline scripts fragile.

### Processing pattern
1. Scan journal directories → find unprocessed files (check ingestion_log.jsonl)
2. Parse each file → extract entities_observed, relationships_observed, preferences_observed
3. Normalize signal format → create Signal nodes in Chronicle
4. Create Candidate nodes from Signals with Supports edges
5. Run consolidation (resolve relevance, boost confidence, promote eligible)

## Entity observation field name variations

Different OCAS skills use different field names for entity observations. Always check both formats:

| Field | Format A (custodian/taste) | Format B (scout/sift) | Format C (weave) |
|-------|---------------------------|----------------------|-------------------|
| Entity ref | `entity` | `name` | `entity` |
| Entity type | `entity_type` | `type` | `entity_type` |
| Observation | `observation` | `description` | `description` |
| Relevance | `user_relevance` | `user_relevance` | `user_relevance` |

Always check top-level first, then `decision.payload`. **Warning: `decision` can be a string, not a dict** — some journals (Sands, Dispatch) store `decision` as a plain text summary rather than a structured object. Always type-check before calling `.get()`:

```python
entities = data.get("entities_observed", [])
if not entities:
    decision = data.get("decision", {})
    if isinstance(decision, dict):  # MUST check — decision can be a string
        payload = decision.get("payload", {})
        if isinstance(payload, dict):
            entities = payload.get("entities_observed", [])
```

**Entities can be strings or dicts** — handle both:
```python
for entity in entities:
    if isinstance(entity, str):
        entity = {"name": entity}  # Some journals emit bare strings
    elif not isinstance(entity, dict):
        continue  # skip malformed entries
    name = entity.get("name", entity.get("entity", "unknown"))
```

## Entity type parsing from references

Entity observations use compound type references like `Entity/AI/ollama-provider`. Parse these to determine both the node type and subtype:

```python
# "Entity/AI/ollama-provider" → proposed_type=Entity, entity_type=AI, name=ollama-provider
parts = entity_ref.split("/")
proposed_type = parts[0]       # Entity, Place, Concept, Thing
entity_type = parts[1] if len(parts) >= 2 else ""
name = parts[-1]
```

## Promotion criteria reminder

Candidates are only promoted when ALL conditions are met:
1. At least one supporting Signal
2. Confidence is `high` (or `med` with manual approval)
3. No contradicting signal of equal or higher confidence
4. No `possible_match` identity flag (check during deduplication before promoting)
5. **`user_relevance` is `user`** — agent_only entities are NEVER promoted

**Note:** `identity_state` is on Entity nodes, NOT on Candidates. Use name+type deduplication during consolidation to detect possible duplicates before promotion. Candidates with `unknown` relevance default to `agent_only` after one consolidation cycle if no relevance-upgrading signal arrives.

## Actual Filesystem Paths (this deployment)

The SKILL.md uses `{agent_root}` conventions. On this system, `{agent_root}` resolves to `/root/.hermes`, but sub-paths differ from the documented defaults:

| Documented path | Actual path |
|------------------|-------------|
| `{agent_root}/commons/workspace/MEMORY.md` | `/root/.hermes/memories/MEMORY.md` |
| `{agent_root}/commons/workspace/memory/` | `/root/.hermes/memories/` (no `memory/` subdir) |
| `{agent_root}/commons/agents/*/sessions/` | `/root/.hermes/sessions/*.jsonl` (directly in root, not under commons/agents) |
| `{agent_root}/commons/journals/{skill}/` | `/root/.hermes/commons/journals/{skill}/` (correct) |
| `{agent_root}/db/ocas-elephas/` | `/root/.hermes/db/hermes-elephas/` (note: `hermes-elephas` not `ocas-elephas`) |

**Key finding:** Memory files are at `/root/.hermes/memories/MEMORY.md`, not under `commons/workspace/`. Session logs are directly in `/root/.hermes/sessions/` as `.jsonl` files.

## Confidence scoring from single signals

| Source | Default confidence |
|--------|-------------------|
| Single Observation from one skill | `low` |
| User-relevant observation | `low` → `med` if 2+ signals |
| Research journal with high provenance | `med` |
| Memory file extraction | `med` |
| Session log (human message) | `med` |
| Session log (assistant message) | `low` |

Boost rules:
- 2+ Signals from different sources → +1 tier
- Cross-domain confirmation → `high`

## Ingestion log format variations

The ingestion log (`ingestion_log.jsonl`) contains entries in **two different formats** from different eras:

**Old format (pre-2026-04-12):** Tracks runs, not files:
```json
{"run_id": "c0de6ffe", "processed_at": "2026-04-12T05:40:23.376206+00:00", "signals_created": 3}
```

**New format (2026-04-12+):** Tracks individual files:
```json
{"file": "ocas-custodian/2026-04-18/light-20260418-080749.json", "signals_created": 3, "candidates_created": 3, "ingested_at": "2026-04-18T08:11:27.232545+00:00"}
```

When loading the ingestion log for deduplication, **only use entries with `file` key**:
```python
ingested_files = set()
if INGESTION_LOG.exists():
    for line in INGESTION_LOG.read_text().strip().split('\n'):
        if not line.strip():
            continue
        entry = json.loads(line)
        if "file" in entry:  # only track file-based entries
            ingested_files.add(entry["file"])
```

Old `run_id` entries can be ignored (they don't prevent file re-processing).

## Apostrophe escaping in Cypher queries

When building Cypher queries with f-strings and entity names contain apostrophes (common in restaurant/person names like "O' by Claude Le Tohic", "Lillian's Italian Kitchen"), the escaping creates parser errors.

**Problem:** The `_esc()` function escapes apostrophes to `\\'`, but when the JSON payload itself contains escaped apostrophes (e.g., `"O\\' by Claude"`), LadybugDB's Cypher parser fails with:
```
Parser exception: extraneous input 's' expecting {<EOF>, ';', SP}
```

**Root cause:** Double-escaping — the JSON contains `O'` → `_esc()` makes it `O\\'` → stored in query as `'{\"name\": \"O\\\\' by...\"}'` which breaks parsing.

**Fix:** Escape the JSON payload BEFORE embedding in the Cypher string, using a different approach:
```python
# Wrong — causes double-escaping:
payload = json.dumps({"name": "O' by Claude"})
query = f"... s.payload = '{_esc(payload)}'"  # " becomes \\' inside JSON

# Correct — escape only the outer Cypher quotes:
payload = json.dumps({"name": "O' by Claude"}).replace("'", "\\\\'")
query = f"... s.payload = '{payload}'"
```

Or better yet, use parameterized queries if LadybugDB supports them, or write signals via a Python script file (not inline terminal) to avoid shell quoting issues entirely.

**Practical workaround:** For entity names with apostrophes, create signals via a script file rather than inline terminal execution. The shell's own quote handling compounds the problem.

## Promotes relationship creation limitation

LadybugDB does not support creating relationships when matching the target node by multiple possible labels. This query **fails**:
```cypher
MATCH (c:Candidate {id: 'xxx'})
MATCH (n) WHERE n.id = 'yyy'  # n could be Entity, Place, Concept, or Thing
CREATE (c)-[:Promotes]->(n)
```

Error: `Binder exception: Create rel bound by multiple node labels is not supported.`

**Workaround:** When creating Promotes edges, match the specific node type explicitly:
```python
# Determine the node type from proposed_type, then query explicitly:
if "Entity" in entity_type:
    target_match = f"MATCH (n:Entity {{id: '{node_id}'}})"
elif "Place" in entity_type:
    target_match = f"MATCH (n:Place {{id: '{node_id}'}})"
elif "Concept" in entity_type:
    target_match = f"MATCH (n:Concept {{id: '{node_id}'}})"
elif "Thing" in entity_type:
    target_match = f"MATCH (n:Thing {{id: '{node_id}'}})"

query = f"""
    MATCH (c:Candidate {{id: '{cand_id}'}})
    {target_match}
    CREATE (c)-[:Promotes]->(n)
"""
```

This is a LadybugDB limitation, not a Cypher standard limitation.

## Additional Quirks (discovered 2026-04-18)

### Connection constructor — no mode string
`lb.Connection(db)` takes **only** the Database object as its argument. Passing a second argument like `"READ_ONLY"` causes:
```
TypeError: __init__(): incompatible constructor arguments.
Invoked with: <Database object>, 'READ_ONLY'
```
**Correct:** `conn = lb.Connection(db)` — that's it. No mode parameter.

### NaN values in DataFrame columns
LadybugDB QueryResult `.get_as_df()` can return `NaN` (float) for missing string properties. Calling `.lower()` or other string methods on NaN raises `AttributeError: 'float' object has no attribute 'lower'`. Always guard:
```python
import math
def safe_str(val):
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return ""
    return str(val)

name = safe_str(row['e.name']).lower()
```

### DETACH DELETE for nodes with relationships
`DELETE` on a node that has any relationships fails silently or errors. Always use `DETACH DELETE`:
```python
# Wrong — fails if node has relationships:
conn.execute(f"MATCH (e:Entity {{id: '{eid}'}}) DELETE e;")

# Correct — removes node and all its relationships:
conn.execute(f"MATCH (e:Entity {{id: '{eid}'}}) DETACH DELETE e;")
```

### Session log file structure
Session files at `/root/.hermes/sessions/session_*.json` are JSON dicts with:
```json
{
  "session_id": "...",
  "model": "...",
  "messages": [
    {"role": "user", "content": "..."},
    {"role": "assistant", "content": "...", "tool_calls": [...]},
    {"role": "tool", "content": "..."}
  ]
}
```
The `messages` array is at `data.get('messages', [])`. Roles are `"user"`, `"assistant"`, `"tool"` — not `"human"`.

### Regex entity extraction from sessions — high false positive rate
Naive regex `r'\b([A-Z][a-z]+ [A-Z][a-z]+)\b'` on session content matches many non-entity phrases:
- Skill names: "Writes Action", "Observation Journal", "Web Search"
- Concept phrases: "Account Isolation", "Deep Scan", "Tier Classification"
- Header-like text: "Agent Memory", "Agent Sessions"

**Mitigation:** Filter against known skill/concept lists, require 2+ independent mentions, or use NER. In this run, 102 signals were created but only ~10 were real entities — the rest were skill/concept false positives that needed manual cleanup.

### `collect()` in Cypher returns JSON strings in get_as_df()
When using Cypher `collect(e.id)` with `.get_as_df()`, the result column contains JSON string representations, not Python lists. Parse before use:
```python
result = conn.execute("MATCH (e:Entity) ... RETURN collect(e.id) AS ids").get_as_df()
ids = json.loads(result['ids'].iloc[0])  # parse the JSON string
```