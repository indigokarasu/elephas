# LadybugDB Operational Reference

Practical guide for working with the `real_ladybug` Python package and the Chronicle graph database.

## Library Import

```python
from real_ladybug import Database, Connection, QueryResult
```

**Not** `LadybugDB` — the top-level export is `Database`.

## Opening the Database

```python
from real_ladybug import Database, Connection

# READ_WRITE mode (Elephas only; other skills MUST use read_only=True)
db = Database(db_path)  # defaults to read_write

# READ_ONLY mode (all other skills)
db = Database(db_path, read_only=True)

# Create connection
conn = Connection(db)
```

**Key**: `Database()` does NOT have an `access_mode` parameter. Use `read_only=True` keyword argument instead.

## Querying

```python
result = conn.execute("MATCH (e:Entity {identity_state: 'distinct'}) RETURN e.name AS name, e.entity_type AS type")
```

### Iterating Results

```python
# Row-by-row iteration
while result.has_next():
    row = result.get_next()  # Returns a list like ['Indigo Karasu', 'Person']
    name = row[0]
    etype = row[1]

# Get column names
columns = result.get_column_names()  # ['name', 'type']

# Get row count
count = result.get_num_tuples()

# Get all rows as list
all_rows = result.get_all()
```

**Important**: `as_dict` is a property, not a method. Access it as `result.as_dict` if needed, but typically `get_next()` in a loop is more reliable.

### Closing

```python
conn.close()
db.close()
```

Always close connections when done. Only one `READ_WRITE` connection can be open at a time.

## Node Property Names

Actual property names in Chronicle (differs from what schemas.md may suggest in some cases):

| Node Label | Key Properties |
|---|---|
| **Entity** | `id`, `name`, `entity_type`, `aliases` (list), `identifiers` (list), `possible_matches` (string, comma-separated or single entity_id), `merge_history` (string, JSON-ish), `identity_state` ('distinct', 'possible_match', 'confirmed_same'), `source_skill`, `record_time` |
| **Signal** | `id`, `source_skill`, `source_type`, `source_journal_type`, `payload` (string, JSON-ish), `user_relevance`, `timestamp`, `status` ('active', 'consumed', 'testing') |
| **Candidate** | `id`, `proposed_type`, `proposed_data` (string, JSON-ish), `supporting_signals` (string, list), `confidence` ('high', 'med', 'low'), `user_relevance` ('user', 'agent_only', 'unknown'), `status` ('pending', 'confirmed', 'rejected'), `created_at`, `resolved_at`, `resolved_reason` |
| **Thing** | `id`, `name`, `thing_type`, `source_skill` |
| **Concept** | `id`, `name`, `concept_type`, `source_skill` |
| **Inference** | `id`, `inference_type`, `content`, `confidence`, `supporting_nodes`, `created_at` |

**Pitfall**: Candidate uses `id`, NOT `candidate_id`. The skill spec mentions `candidate_id` but the actual property is `id`.

## Relationship Types

| Type | Description |
|---|---|
| `Supports` | Signal → Candidate (signal backs a candidate) |
| `Relates` | Entity → Entity (generic relationship) |
| `Promotes` | Entity → Candidate (entity was promoted from candidate) |
| `Infers` | Inference → Entity (inference drawn about entity) |

## Identity State Machine

```
distinct (default) → possible_match → confirmed_same
       ↑                                    |
       └── merge reversal ─────────────────┘
```

**Critical fix pattern**: After merging duplicate entities, BOTH the surviving and absorbed entity were left as `possible_match`. The correct state is:
- Surviving entity: `identity_state = 'distinct'`
- Absorbed entity: `identity_state = 'confirmed_same'`

### Fix Script

```python
merges_to_fix = [
    ("ent_surviving_id", "ent_absorbed_id", "Entity Name"),
]
for surviving_id, absorbed_id, name in merges_to_fix:
    conn.execute(f"MATCH (e:Entity {{id: '{surviving_id}'}}) SET e.identity_state = 'distinct'")
    conn.execute(f"MATCH (e:Entity {{id: '{absorbed_id}'}}) SET e.identity_state = 'confirmed_same'")
```

## LadybugDB Query Binding Pitfall

**MERGE with parameterized values fails for complex string fields.** When using `conn.execute("MERGE (s:Signal {id: $id}) ON CREATE SET s.payload = $payload", {...})` with JSON string values in the `payload` field, LadybugDB throws `Runtime exception: Trying to create a vector with ANY type. This should not happen. Data type is expected to be resolved during binding.`

This affects Signal, Candidate, and any node with JSON-like string fields (`payload`, `proposed_data`, `supporting_signals`, `identifiers`, etc.).

**Workaround**: Use string-formatting (f-strings or concatenation) to build Cypher queries instead of parameter binding for these fields. Escape single quotes in string values:

```python
# BAD — parameterized binding fails for JSON payload fields
conn.execute(
    "MERGE (s:Signal {id: $id}) ON CREATE SET s.payload = $payload",
    {"id": signal_id, "payload": json_str}  # Runtime exception!
)

# GOOD — string formatting with escaped quotes
escaped = payload_str.replace("'", "\\'")
conn.execute(
    f"MERGE (s:Signal {{id: '{signal_id}'}}) ON CREATE SET "
    f"s.payload = '{escaped}', ..."
)
```

Simple string fields (`source_skill`, `user_relevance`, `status`, `confidence`) work fine with both parameterized and string-formatted queries. The issue only manifests with complex/string-structured values that LadybugDB's query planner cannot type-resolve during binding.

If MERGE still fails, use `CREATE` as a fallback (but note CREATE will error on duplicate IDs).

## Common Consolidation Patterns

### Finding redundant candidates (already-confirmed entities)

```python
# Match candidates whose proposed_data contains a confirmed entity's name
result = conn.execute("""
MATCH (c:Candidate {status: 'pending', user_relevance: 'user'})
MATCH (e:Entity {identity_state: 'distinct'})
WHERE c.proposed_data CONTAINS e.name
RETURN c.id AS cand_id, e.id AS ent_id, e.name AS name
""")
```

### Marking candidates as confirmed (corroborating existing facts)

```python
from datetime import datetime, timezone
ts = datetime.now(timezone.utc).isoformat()
conn.execute(f"MATCH (c:Candidate {{id: '{cand_id}'}}) SET c.status = 'confirmed', c.resolved_at = '{ts}', c.resolved_reason = 'entity already confirmed in Chronicle as {ent_id}'")
```

### Checking signal counts per candidate

```python
result = conn.execute("""
MATCH (c:Candidate {status: 'pending', user_relevance: 'user'})
MATCH (s:Signal)-[:Supports]->(c)
RETURN c.id AS cand_id, count(s) AS signal_count
ORDER BY signal_count DESC
""")
```

## Ingestion Log Format

The ingestion log is at `~/.hermes/commons/db/ocas-elephas/ingestion_log.jsonl`. Each line is a JSON object:

```json
{
  "run_id": "filename-without-extension",
  "source_skill": "ocas-dispatch",
  "source_type": "journal",
  "journal_path": "/full/path/to/file.json",
  "journal_type": "Action",
  "signals_created": 0,
  "candidates_created": 0,
  "ingested_at": "2026-04-14T18:16:33.690126+00:00"
}
```

To check which journals have been processed, read the log and collect `journal_path` values, then diff against files on disk.

## Query Patterns Reference

### Status query (elephas.status)

```cypher
-- Node counts by label
MATCH (e:Entity) RETURN count(e) AS entities;
MATCH (t:Thing) RETURN count(t) AS things;
MATCH (c:Concept) RETURN count(c) AS concepts;
MATCH (i:Inference) RETURN count(i) AS inferences;

-- Signal counts
MATCH (s:Signal {status: 'active'}) RETURN count(s);
MATCH (s:Signal {status: 'consumed'}) RETURN count(s);

-- Candidate counts
MATCH (c:Candidate {status: 'pending'}) RETURN count(c);
MATCH (c:Candidate {status: 'pending', user_relevance: 'user'}) RETURN count(c);
MATCH (c:Candidate {status: 'pending', user_relevance: 'agent_only'}) RETURN count(c);
MATCH (c:Candidate {status: 'confirmed'}) RETURN count(c);
MATCH (c:Candidate {status: 'rejected'}) RETURN count(c);

-- Relationship count
MATCH ()-[r]->() RETURN count(r) AS relationships;

-- Tables
CALL show_tables() RETURN *;
```

### Identity resolution queries

```cypher
-- Find entities needing identity resolution
MATCH (e:Entity {identity_state: 'possible_match'}) RETURN e.id, e.name, e.possible_matches;

-- Find all duplicate pairs
MATCH (e1:Entity), (e2:Entity)
WHERE e1.entity_id < e2.entity_id AND e1.identity_state = 'possible_match'
RETURN e1.name, e2.name, e1.identity_state;
```