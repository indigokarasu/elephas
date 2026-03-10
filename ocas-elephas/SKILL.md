---
name: ocas-elephas
description: >
  Long-term knowledge graph (Chronicle) maintenance. Ingests structured signals
  from system journals, resolves entity identity, promotes confirmed facts,
  and generates inferences.
---

# Elephas

Elephas maintains Chronicle, the system's long-term knowledge graph. It ingests structured signals from journals, converts them into candidates, resolves identity, promotes confirmed facts, and generates behavioral inferences.

Elephas does not interact directly with the user. It runs in the background.

## When to use

- Query Chronicle for entities, relationships, events, or inferences
- Ingest new signals from skill journals
- Run consolidation passes on pending candidates
- Resolve entity identity (possible duplicates)
- Promote or reject candidates

## When not to use

- Social relationship queries — use Weave
- Web research — use Sift
- Person-focused OSINT — use Scout
- Direct user communication — use Dispatch

## Core promise

Chronicle stores structured world knowledge with provenance. Facts remain stable. Interpretations remain separate. Only Elephas writes to Chronicle.

## Commands

- `elephas.query` — query Chronicle for entities, relationships, events, or inferences
- `elephas.ingest.journals` — ingest structured signals from Observation, Action, and Research journals
- `elephas.consolidate.immediate` — immediate consolidation pass on pending candidates
- `elephas.consolidate.deep` — deep pass with identity reconciliation and inference generation
- `elephas.identity.resolve` — attempt to resolve whether two entity records are the same
- `elephas.identity.merge` — merge confirmed-same entities (reversible)
- `elephas.candidates.list` — list pending candidates
- `elephas.candidates.promote` — promote a candidate to confirmed fact
- `elephas.candidates.reject` — reject a candidate with reason
- `elephas.status` — node count, edge count, pending candidates, last consolidation time

## Memory lifecycle

Signal → Candidate → Chronicle Fact

Signals are immutable. Candidates remain until confirmed, rejected, or merged. Confirmed facts persist indefinitely. Inferences are separate from facts and never overwrite them.

## Consolidation passes

- **Immediate pass** — runs frequently. Creates candidates, increases confidence from new signals.
- **Scheduled pass** — runs periodically. Promotes high-confidence candidates, deduplicates.
- **Deep pass** — runs less frequently. Full identity reconciliation, inference generation, graph cleanup.

## Identity resolution rules

States: distinct, possible_match, confirmed_same. Merges are always reversible. See `references/ontology.md` for the full identity model.

Resolution precedence: exact identifier match > name+location with corroboration > behavioral pattern match.

## Write authority

Only Elephas writes to Chronicle. Other skills query but do not modify.

## Support file map

- `references/schemas.md` — node types, relationship types, Signal, Candidate, Inference schemas
- `references/ontology.md` — full type hierarchy from spec-ocas-ontology.md with Chronicle-specific extensions
- `references/ingestion_pipeline.md` — journal reading, signal creation, candidate promotion, dedup, inference rules

## Storage layout

```
.elephas/
  config.json
  chronicle.db
  ingestion_log.jsonl
  candidates.jsonl
  merge_history.jsonl
  decisions.jsonl
```

## Validation rules

- All confirmed facts have at least one supporting signal
- No orphaned candidates
- Merge history is intact and reversible
- Ingestion log is consistent with current state
