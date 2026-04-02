# Chronicle Ontology

Chronicle implements the OCAS Shared Ontology (spec-ocas-ontology.md v1.1). This file documents Chronicle-specific implementation details.

## Node type hierarchy

Entity (entity_type: Person | AI)
Place (place_type: restaurant | office | city | venue | ...)
Concept (concept_type: Event | Action | Idea)
  Event subtypes: TravelEvent, MeetingEvent, PurchaseEvent, AppointmentEvent, CommunicationEvent
Thing (thing_type: DigitalArtifact | PhysicalArtifact | Signal | Candidate)

Chronicle does not store full documents. Artifacts remain in external systems. Chronicle stores references via Thing nodes with metadata pointing to the external location.

## Identifier vocabulary

The `identifiers` field on Entity nodes is a JSON array of typed identifier objects. Stored as a STRING in LadybugDB — serialize/deserialize as JSON.

Standard types: `email`, `phone`, `handle`, `url`, `domain`, `employee_id`, `external_id`

Skill-namespaced cross-references (reference pointers, not identity signals):
```json
{"type": "weave:person_id", "value": "uuid-from-weave-db"}
{"type": "scout:subject_id", "value": "req_20260305_001"}
```

## Standard relationship types

Used in `Relates.relationship_type`:

Entity-Entity: knows, friend_of, colleague_of, family_of, introduced_by, spouse_of, reports_to, acquaintance_of
Entity-Concept: participated_in, organized, attended
Entity-Place: lives_in, works_at, visited, associated_with
Entity-Thing: created, owns, uses
Concept-Place: occurred_at, located_in
Concept-Concept: related_to, derived_from, part_of

## Confidence

Relationship and Candidate confidence uses label form: `high` / `med` / `low`.

Derivation from numeric score (0.0–1.0):
- >= 0.8 → high
- >= 0.5 → med
- < 0.5 → low

## User relevance

Chronicle is the **user's** personal knowledge graph. Not every entity the system encounters belongs in it. The `user_relevance` field distinguishes entities that matter to the user's world from entities the system encountered incidentally during task execution.

User relevance labels: `user` / `agent_only` / `unknown`.

- `user` — the entity exists in the user's world. The user mentioned it in conversation, it appears in their files (Drive, Memory/), or it has a direct relationship to the user. **Only `user` relevance entities are eligible for promotion to Chronicle facts.**
- `agent_only` — the entity was encountered by the agent during task execution (research, scanning, analysis) but has no demonstrated connection to the user's life. These remain as Candidates indefinitely and are not promoted. They may be upgraded to `user` if a subsequent signal demonstrates user relevance.
- `unknown` — relevance has not been determined yet. Default for new Candidates. Resolved during consolidation passes.

### Relevance signals (strongest to weakest)

1. **User message mention** — user named the entity in conversation (session log extraction). Strongest signal → `user`.
2. **Memory/ file reference** — entity appears in `MEMORY.md` or `memory/*.md`. The agent already judged it worth remembering → `user`.
3. **User's Drive content** — entity appears in the user's files (Bower signals). The user created or saved this → `user`.
4. **Agent memory write** — agent wrote about the entity to `MEMORY.md`. Agent judged it relevant to the user → `user`.
5. **Direct relationship to known user entity** — entity is connected to someone/something already marked `user` in Chronicle (e.g., a colleague of the user's friend) → `user` if within 1 hop, `unknown` if further.
6. **Skill research output only** — entity appeared only in Scout/Sift/Rally research with no user engagement → `agent_only`.

### Relevance upgrade

An `agent_only` entity can be upgraded to `user` when:
- The user mentions it in a subsequent conversation
- It appears in a Memory/ file
- It appears in the user's Drive
- A new signal establishes a direct relationship to a `user` entity

Relevance never downgrades. Once `user`, always `user`.

## Time model

event_time — when the real-world event occurred
record_time — when Elephas wrote this to Chronicle
valid_from / valid_until — validity window. valid_until null = currently valid.

All timestamps: ISO 8601 with timezone offset.

## Identity model

States: distinct (default), possible_match, confirmed_same.
Resolution precedence: exact identifier match → name+location with corroboration → behavioral pattern match.
Merges are reversible. merge_history preserved on surviving node.

## Evidence model

```
Skill Journal / Signal Intake / Memory Files / Session Logs
  → Signal (immutable after creation)
    → Supports → Candidate (with user_relevance + confidence)
      → Promotes → Chronicle Fact (only if user_relevance = user)
      → Inference (via Infers, never overwrites facts)
```

Every Chronicle fact traces back to at least one Signal. Signals are immutable after creation.

Only candidates with `user_relevance: "user"` are eligible for promotion. Candidates with `user_relevance: "agent_only"` remain in the candidate pool but are never promoted to Chronicle facts.

## Chronicle-to-skill reference model

Chronicle stores reference pointers for entities that exist in both Chronicle and skill-local databases:

```json
{"type": "weave:person_id", "value": "uuid-from-weave"}
{"type": "triage:task_id", "value": "uuid-from-triage"}
{"type": "bower:file_id", "value": "gdrive-file-id"}
```

The authoritative record lives in the skill's database. Chronicle holds a pointer. Skills are responsible for their own data integrity.

## Expected scale

Nodes: 100k–500k
Edges: 5M–20M
Hardware: Mac Studio, 512GB–1TB RAM
LadybugDB indexes primary keys automatically. At this scale, filtering by `entity_type`, `identity_state`, `status`, `confidence`, and `user_relevance` should use indexed primary key lookups where possible to avoid full scans.
