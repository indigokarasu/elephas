# Ingestion Pipeline

## Source paths

Elephas reads from four sources per ingestion pass:

1. **Skill journals**: `~/openclaw/journals/{skill-name}/YYYY-MM-DD/{run_id}.json`
   Walk all skill directories under `~/openclaw/journals/`. Process any `.json` file whose `run_id` does not appear in the ingestion log at `~/openclaw/db/ocas-elephas/ingestion_log.jsonl`.

2. **Signal intake**: `~/openclaw/db/ocas-elephas/intake/{signal_id}.signal.json`
   Process signal files dropped by other skills. After processing, move to `intake/processed/`.

3. **Memory files** (deep consolidation only): `~/.openclaw/workspace/MEMORY.md` and `~/.openclaw/workspace/memory/*.md`
   Extract entity mentions, relationships, and preferences from the agent's curated memory files. Track file content hashes in `~/openclaw/db/ocas-elephas/memory_ingestion_log.jsonl` to avoid reprocessing unchanged files.

4. **Session logs** (deep consolidation only): `~/.openclaw/agents/*/sessions/*.jsonl`
   Extract entity knowledge from conversation transcripts. Only process `message` entries from `human` and `assistant` roles — skip `toolResult`, `compaction`, `custom`, and all other machine-generated entry types. Track processed session IDs and byte offsets in `~/openclaw/db/ocas-elephas/session_ingestion_log.jsonl`.

Sources 1 and 2 run during every ingestion pass (every 15 minutes).
Sources 3 and 4 run only during deep consolidation passes (daily at 4am).

Skip files that fail JSON parse — log the error, do not halt the pass.

## Ingestion log

Append-only JSONL at `~/openclaw/db/ocas-elephas/ingestion_log.jsonl`.

```json
{
  "run_id": "r_xxxxxxx",
  "source_skill": "ocas-weave",
  "source_type": "journal",
  "journal_path": "~/openclaw/journals/ocas-weave/2026-03-17/r_xxxxxxx.json",
  "journal_type": "observation",
  "signals_created": 3,
  "candidates_created": 2,
  "ingested_at": "2026-03-17T10:05:00-07:00"
}
```

### Memory ingestion log

Append-only JSONL at `~/openclaw/db/ocas-elephas/memory_ingestion_log.jsonl`.

```json
{
  "file_path": "~/.openclaw/workspace/MEMORY.md",
  "content_hash": "sha256:abc123...",
  "signals_created": 5,
  "ingested_at": "2026-03-18T04:02:00-07:00"
}
```

Only re-ingest a memory file when its content hash has changed since the last ingestion.

### Session ingestion log

Append-only JSONL at `~/openclaw/db/ocas-elephas/session_ingestion_log.jsonl`.

```json
{
  "session_file": "~/.openclaw/agents/main/sessions/sess_abc123.jsonl",
  "last_byte_offset": 48230,
  "signals_created": 2,
  "ingested_at": "2026-03-18T04:03:00-07:00"
}
```

Track byte offset per session file to resume from where the last pass left off. Only process new entries since the last ingestion.

## Signal creation

### From Observation Journals

Extract:
- `decision.payload.entities_observed` → one Signal per entity_id, type=Observation
- `decision.payload.relationships_observed` → one Signal per relationship pair
- `decision.payload.preferences_observed` → one Signal per preference

### From Action Journals

- `action.side_effect_intent` and `action.external_reference` → Signal capturing what was done

### From Research Journals (Scout, Sift)

- Extract entity names, identifiers, and relationships from the research payload

### From Memory files

Extract entity mentions from natural language content in `MEMORY.md` and `memory/*.md`. Memory files are curated by the agent — entities found here have high user relevance because the agent already judged them worth remembering.

For each extracted entity:
- Create Signal with `source_type: "memory"`, `source_skill: "openclaw-memory"`
- Set `user_relevance: "user"` — Memory/ content is inherently user-relevant
- Extract identifiers when present (emails, names, handles mentioned in context)

### From Session logs

Parse JSONL transcript files. For each entry:
- Skip if `type` is not `"message"`
- Skip if role is not `"human"` or `"assistant"`
- Skip `toolResult`, `compaction`, `custom`, `custom_message`, `branch_summary` entry types
- Extract entity mentions from the natural language message content

User relevance depends on who said it:
- Entities mentioned in `human` role messages → `user_relevance: "user"` (the user brought it up)
- Entities mentioned only in `assistant` role messages → `user_relevance: "unknown"` (agent may be discussing user-relevant topics or its own research; needs corroboration)

Create Signal with `source_type: "session_log"`, `source_skill: "openclaw-session"`.

### Signal structure

```json
{
  "id": "sig_{uuid7}",
  "source_skill": "ocas-weave",
  "source_type": "journal",
  "source_journal_type": "Observation",
  "payload": {
    "proposed_type": "Entity",
    "entity_type": "Person",
    "name": "Jane Doe",
    "identifiers": [{"type": "email", "value": "jane@example.com"}]
  },
  "user_relevance": "user",
  "timestamp": "2026-03-17T10:00:04-07:00",
  "status": "active"
}
```

`source_type` values: `journal` | `intake` | `memory` | `session_log`

Write Signal to Chronicle as a Signal node. Signals are immutable after creation.

## User relevance scoring

Every Signal carries a `user_relevance` field. This determines whether the entity it describes belongs in the user's personal knowledge graph or was only encountered during agent task execution.

### Default relevance by source

| Source | Default user_relevance | Rationale |
|---|---|---|
| Memory/ files | `user` | Agent curated this as worth remembering for the user |
| Session log (human role) | `user` | User mentioned it directly |
| Session log (assistant role) | `unknown` | Agent may be discussing user topics or its own research |
| Bower (Drive signals) | `user` | User's own files and documents |
| Skill journal (entities_observed) | `unknown` | Skill encountered it; relevance unclear |
| Signal intake (Scout/Sift) | `agent_only` | Research output; not demonstrated user connection |
| Signal intake with user_relevance set | (use provided value) | Emitting skill has already assessed relevance |

### Relevance on Candidates

When a Candidate is created or updated:
- Inherit the strongest `user_relevance` from supporting Signals
- Strength order: `user` > `unknown` > `agent_only`
- If any supporting Signal has `user_relevance: "user"`, the Candidate is `user`
- If all Signals are `agent_only`, the Candidate is `agent_only`

### Relevance upgrade

A Candidate's `user_relevance` can be upgraded when new supporting Signals arrive with stronger relevance. It never downgrades.

## Candidate creation

For each new Signal, check whether a matching Candidate exists:

```cypher
MATCH (c:Candidate {status: 'pending'})
WHERE c.proposed_data CONTAINS $entity_identifier
RETURN c.id
```

If matching Candidate exists: add Signal to `supporting_signals`, re-score confidence, re-evaluate `user_relevance`.
If no match: create new Candidate node, link via `Supports` edge from Signal.

## Confidence scoring

Initial confidence from a single Signal:
- Research journal with high provenance → `med`
- Multiple corroborating Signals from different skills → `high`
- Single Observation from one skill → `low`
- Memory file extraction → `med` (curated by agent)
- Session log extraction (human message) → `med` (user-stated)
- Session log extraction (assistant message) → `low` (needs corroboration)

Upgrade rules:
- 2+ Signals from different sources → +1 tier
- Cross-domain confirmation (e.g., Weave + Scout both observed same entity) → `high`
- Memory + session log corroboration → `high`
- Contradicting signal of equal or higher confidence → downgrade or flag

## Promotion criteria

Promote when **all** conditions are met:
1. At least one supporting Signal
2. Confidence is `high` (or `med` with manual approval)
3. No contradicting signal of equal or higher confidence
4. `identity_state` is `distinct` or `confirmed_same` (not `possible_match`)
5. `user_relevance` is `user` — **agent-only entities are never promoted**

On promotion: write proposed_data as Chronicle node, create `Promotes` edge from Candidate, set `Candidate.status = 'confirmed'`, set `Signal.status = 'consumed'`.

Candidates with `user_relevance: "agent_only"` remain in the candidate pool indefinitely. They may be promoted if a subsequent signal upgrades their relevance to `user`.

Candidates with `user_relevance: "unknown"` are held for one consolidation cycle. If no relevance-upgrading signal arrives, they default to `agent_only`.

## Deduplication

During consolidation passes, detect duplicate Entity nodes:

```cypher
MATCH (a:Entity), (b:Entity)
WHERE a.id < b.id
  AND a.entity_type = b.entity_type
  AND (a.identifiers CONTAINS b.name OR a.name = b.name)
RETURN a.id, b.id, a.name, b.name
```

For each candidate pair, apply resolution precedence:
1. Exact identifier overlap → `confirmed_same` if above `auto_merge_threshold`
2. Name + location with corroborating signal → `possible_match` if between thresholds
3. Name only → flag as `possible_match`, do not auto-merge

Auto-merge: call `elephas.identity.merge`. Preserve merge history. Write Action Journal.

## Identity merge

```python
def merge_entities(conn, surviving_id: str, merged_id: str, reason: str):
    now = datetime.now(timezone.utc).isoformat()
    # Get merged entity data
    merged = list(conn.execute(
        "MATCH (e:Entity {id: $id}) RETURN e", {"id": merged_id}
    ))
    if not merged:
        raise ValueError(f"Entity {merged_id} not found")
    # Append to surviving entity's merge_history
    import json
    surviving = list(conn.execute(
        "MATCH (e:Entity {id: $id}) RETURN e.merge_history", {"id": surviving_id}
    ))
    history = json.loads(surviving[0][0] or "[]")
    history.append({"merged_id": merged_id, "merged_at": now,
                    "merged_by": "ocas-elephas", "reason": reason})
    conn.execute("""
        MERGE (e:Entity {id: $sid})
        SET e.merge_history = $history, e.identity_state = 'confirmed_same'
    """, {"sid": surviving_id, "history": json.dumps(history)})
    # Mark merged entity
    conn.execute("""
        MERGE (e:Entity {id: $mid})
        SET e.identity_state = 'confirmed_same'
    """, {"mid": merged_id})
```

Merges are reversible: the merge_history preserves the full audit trail.

## Inference generation

Runs during deep consolidation passes only (`inference.enabled: true`).

Minimum supporting nodes: `inference.min_supporting_nodes` (default: 3).

Pattern types:
- `habit_pattern` — entity repeatedly participates in events of the same type within a recurring time window
- `social_opportunity` — two entities share multiple connections but have no direct relationship
- `recurring_behavior` — entity consistently performs a specific action type

```cypher
CREATE (i:Inference {
  id: $id,
  inference_type: $type,
  confidence: $confidence,
  supporting_nodes: $supporting_nodes_json,
  description: $description,
  created_at: $now
})
```

Link via `Infers` edges. Inferences never overwrite or modify Chronicle facts.

## Error handling

Journal file unparseable — log error with path and reason, skip, continue.
Signal references entity not in Chronicle — create Candidate, do not create dangling fact.
Candidate promotion write fails — mark Candidate `pending`, log error, retry next pass.
Lock error on chronicle.lbug — surface immediately, abort pass, do not corrupt ingestion log.
Malformed intake signal file — move to `intake/errors/` with `.error` suffix, log, continue.
Memory file read error — log error, skip file, continue with remaining files.
Session log parse error — log error with file path and byte offset, skip entry, continue.
Session log lock contention — skip file, retry next deep pass. Do not interfere with active sessions.
