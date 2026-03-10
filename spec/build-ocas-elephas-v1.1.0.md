
# build.ocas-elephas.v1.1.0.md

## Skill Name
ocas-elephas

## Summary
Elephas maintains Chronicle, the system's long‑term knowledge graph. It ingests signals from OpenClaw activity, converts them into structured candidates, resolves identity, promotes confirmed facts into Chronicle, and generates inferences about patterns and habits.

---

## Responsibility Boundary

Chronicle stores general world knowledge across Entities, Places, Concepts, and Things.

Weave specializes in relationship networks between people.

Weave may reference Chronicle records but does not replace Chronicle.

Chronicle does not directly ingest raw data streams.

It ingests structured signals from system journals.

Sources include:

Observation journals
Action journals
Research journals

---

# Purpose

Elephas is the long‑term memory system for the agent.

It performs four core roles:

1. Observe activity across the OpenClaw ecosystem
2. Convert observations into structured knowledge
3. Maintain a durable life knowledge graph (Chronicle)
4. Derive patterns and behavioral insights

Elephas does not interact directly with the user. It runs continuously in the background.

---

# Chronicle Database

Engine: LadybugDB  
Deployment: Embedded local database

Chronicle stores:

- entities
- places
- events
- relationships
- signals
- candidates
- inferences
- artifact pointers

Chronicle does **not** store full documents.

Artifacts remain in external systems such as:

- email
- calendar
- filesystem
- financial systems

Chronicle stores references to those artifacts.

---

# Ontology

## Core Node Types

Entity  
Place  
Concept  
Thing

### Entity subclasses

Person  
AI

### Concept subclasses

Event  
Action  
Idea

### Thing subclasses

DigitalArtifact  
PhysicalArtifact  
Signal  
Candidate

---

# Event Model

Events are first‑class nodes.

Examples:

TravelEvent  
AppointmentEvent  
PurchaseEvent  
MeetingEvent  
CommunicationEvent

Relationships

Entity → participated_in → Event  
Event → occurred_in → Place

---

# Evidence Model

Signals represent raw observations.

Signal → supports → Candidate  
Candidate → becomes → Event

Signals remain permanently attached as evidence.

---

# Time Model

Every relationship or event may contain:

event_time  
record_time  
valid_time

---

# Identity Model

Entities support identity resolution.

Identity states:

distinct  
possible_match  
confirmed_same

Entity nodes maintain:

aliases  
possible_matches  
merge_history

Merges must remain reversible.

---

# Memory Lifecycle

Signal  
→ Candidate  
→ Chronicle Fact

Signals are immutable.

Candidates remain until:

confirmed  
rejected  
merged

---

# Inference Layer

Inference nodes represent patterns or habits.

Examples:

habit patterns  
social opportunities  
recurring behaviors

Inference nodes contain:

type  
confidence  
supporting_nodes  
creation_time

Inferences never overwrite Chronicle facts.

---

# Ingestion Sources

Elephas ingests information from:

1. OCAS skill journals
2. memory.md
3. skill monologues and outputs
4. external connectors

Signals are created from observed artifacts.

---

# Consolidation

Elephas runs consolidation passes:

Immediate pass  
Scheduled pass  
Deep consolidation pass

These passes:

create candidates  
increase confidence  
promote confirmed events

---

# Maintenance Jobs

Elephas periodically runs background tasks:

identity reconciliation  
candidate promotion  
duplicate entity detection  
graph cleanup  
inference generation

---

# Graph Indexes

Indexes should exist for:

Entity.id  
Place.id  
Event.id  
Signal.id  
Candidate.id

Additional indexes

Place.name  
Event.event_time

---

# Expected Scale

Nodes: 100k–500k  
Edges: 5M–20M

System hardware:

Mac Studio  
512GB–1TB RAM

---

# Write Authority

Only Elephas writes to Chronicle.

Other skills query Chronicle but do not modify it.

---

## Skill Identity

- Skill name: `ocas-elephas`
- Version: `1.1.0`
- Skill type: `system`
- Author: `Indigo Karasu`
- Email: `mx.indigo.karasu@gmail.com`

---

## Optional Skill Cooperation

This skill may cooperate with other skills when present but must never depend on them.
If a cooperating skill is absent, this skill must still function normally.

- All skills — ingest structured signals from skill journals and outputs.
- Weave — coordinate entity identity resolution for people records.
- Mentor — provide Chronicle data for evaluation and trend analysis.

---

## Journal Outputs

Elephas does not emit journals. It consolidates all journal types (Observation, Action, Research) into Chronicle as structured knowledge. Elephas reads journals produced by other skills during ingestion passes.

---

## Visibility

visibility: public

---

## Universal OKRs

This skill must implement the universal OKRs defined in the OCAS Journal Specification (spec-ocas-Journals.md).

Required universal OKRs:

- Reliability: success_rate >= 0.95, retry_rate <= 0.10
- Validation Integrity: validation_failure_rate <= 0.05
- Efficiency: latency trending downward, repair_events <= 0.05
- Context Stability: context_utilization <= 0.70
- Observability: journal_completeness = 1.0

Skill-specific OKRs should be defined in the built SKILL.md to measure domain-relevant outcomes.

---

## Required Package Output

Forge must produce a complete Agent Skill package:

```text
ocas-elephas/
  skill.json
  SKILL.md
  references/
    schemas.md
    ontology.md
    ingestion_pipeline.md
  scripts/
    validate_chronicle_state.py
```

### `skill.json` Requirements

Create a valid `skill.json` with:
- `name`: `ocas-elephas`
- `version`: `1.1.0`
- `description`: routing-optimized text
- `author`: `Indigo Karasu`
- `email`: `mx.indigo.karasu@gmail.com`

The description must make clear that this skill is for:
- maintaining the system's long-term knowledge graph (Chronicle)
- ingesting structured signals from system journals
- entity identity resolution and deduplication
- converting signals to candidates to confirmed facts
- generating pattern-based inferences
- providing queryable world knowledge to other skills

### `SKILL.md` Requirements

`SKILL.md` must begin on line 1 with valid YAML frontmatter delimited by `---`.

Target size: 200 to 300 lines.

#### Required `SKILL.md` Sections

The markdown body must contain these sections in this order:

1. `# Elephas`
2. `## When to use`
3. `## When not to use`
4. `## Core promise`
5. `## Commands`
6. `## Memory lifecycle`
7. `## Consolidation passes`
8. `## Identity resolution rules`
9. `## Write authority`
10. `## Support file map`
11. `## Storage layout`
12. `## Validation rules`

### Commands

The built skill must implement these commands:

- `elephas.query` — query Chronicle for entities, relationships, events, or inferences
- `elephas.ingest.journals` — ingest structured signals from system journals (Observation, Action, Research)
- `elephas.consolidate.immediate` — run an immediate consolidation pass on pending candidates
- `elephas.consolidate.deep` — run a deep consolidation pass with identity reconciliation and inference generation
- `elephas.identity.resolve` — attempt to resolve whether two entity records refer to the same real-world entity
- `elephas.identity.merge` — merge confirmed-same entity records (reversible)
- `elephas.candidates.list` — list pending candidates awaiting confirmation or rejection
- `elephas.candidates.promote` — promote a candidate to a confirmed Chronicle fact
- `elephas.candidates.reject` — reject a candidate with reason
- `elephas.status` — return Chronicle state including node count, edge count, pending candidates, and last consolidation time

### Storage Layout

Chronicle uses LadybugDB as the embedded graph database engine.

```text
.elephas/
  config.json
  chronicle.db (LadybugDB)
  ingestion_log.jsonl
  candidates.jsonl
  merge_history.jsonl
  decisions.jsonl
```

### Config

File: `.elephas/config.json`

Required fields:
- `consolidation.immediate_interval_minutes`: how often immediate passes run
- `consolidation.deep_interval_hours`: how often deep passes run
- `identity.auto_merge_threshold`: confidence threshold for automatic identity merges
- `identity.flag_review_threshold`: confidence threshold for flagging possible matches
- `inference.enabled`: whether inference generation is active
- `inference.min_supporting_nodes`: minimum supporting evidence for an inference

### `references/schemas.md`

Must define schemas for all core node types:
- `Entity` (subclasses: Person, AI) — id, name, aliases, identifiers, possible_matches, merge_history
- `Place` — id, name, coordinates, address, type
- `Concept` (subclasses: Event, Action, Idea) — id, name, description, type
- `Thing` (subclasses: DigitalArtifact, PhysicalArtifact, Signal, Candidate) — id, name, type, metadata
- `Relationship` — source_id, target_id, type, event_time, record_time, valid_time, evidence_refs
- `Signal` — signal_id, source_skill, source_journal_type, payload, timestamp, status
- `Candidate` — candidate_id, proposed_node, supporting_signals, confidence, status (pending|confirmed|rejected|merged)
- `Inference` — inference_id, type, confidence, supporting_nodes, creation_time

### `references/ontology.md`

Must document:
- the complete node type hierarchy (Entity, Place, Concept, Thing and all subclasses)
- the evidence model (Signal → supports → Candidate → becomes → Event/Fact)
- the time model (event_time, record_time, valid_time)
- the identity model (distinct, possible_match, confirmed_same) and reversible merge rules
- standard relationship types
- expected scale (100k–500k nodes, 5M–20M edges)

### `references/ingestion_pipeline.md`

Must document:
- how journals are read during ingestion passes
- signal creation from journal entries
- candidate creation from signals
- confidence scoring during consolidation
- promotion criteria from candidate to confirmed fact
- deduplication and identity reconciliation procedures
- inference generation rules and constraints
- that inferences never overwrite Chronicle facts

### `scripts/validate_chronicle_state.py`

A deterministic validator that checks:
- Chronicle database exists and is readable
- no orphaned candidates (candidates with missing supporting signals)
- no duplicate entity records that should have been merged
- all confirmed facts have at least one supporting signal
- merge history is intact and reversible
- ingestion log is consistent with current state

# Chronicle Philosophy

Chronicle is a structured life archive.

Facts remain stable.

Interpretations remain separate.

---

## Final Response Format for the Coder

Return:

1. package tree
2. full contents of every file
3. brief validation summary

Do not return planning commentary, process narration, or references to absent documents.
