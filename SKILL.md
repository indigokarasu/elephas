---
name: ocas-elephas
description: Elephas: long-term knowledge graph (Chronicle) maintenance. Ingests structured signals from system journals, resolves entity identity, promotes confirmed facts, and generates inferences. Trigger phrases: 'what does Chronicle know about', 'query the knowledge graph', 'ingest journals', 'consolidate', 'resolve entity', 'Chronicle status'. Use when querying world knowledge, ingesting signals, running consolidation, resolving entity duplicates, or promoting candidates to confirmed facts.
metadata: {"openclaw":{"emoji":"🐘"}}
---

# Elephas

Elephas maintains Chronicle, the system's long-term knowledge graph. It ingests structured signals from skill journals, converts them into candidates, resolves entity identity, promotes confirmed facts, and generates behavioral inferences. The Chronicle database initializes automatically on first use — no manual setup required.

Elephas runs in the background. It does not interact directly with the user except through query and status commands.


## When to use

- Query Chronicle for entities, relationships, events, or inferences
- Ingest new signals from skill journals
- Run consolidation passes on pending candidates
- Resolve entity identity (possible duplicates)
- Promote or reject candidates
- Check Chronicle health and pending queue


## When not to use

- Social relationship queries — use Weave
- Web research — use Sift
- Person-focused OSINT — use Scout
- Direct user communication — use Dispatch


## Responsibility boundary

Elephas owns Chronicle: the authoritative long-term knowledge graph for entities, places, concepts, things, and their relationships.

Only Elephas writes to Chronicle. All other skills are read-only consumers.

Elephas does not own the social graph (Weave), OSINT briefs (Scout), or web research (Sift).

Elephas and Mentor are parallel journal consumers. Elephas reads journals to extract entity knowledge. Mentor reads journals to evaluate skill performance. Neither blocks the other.



## Functions



## Storage layout

```
~/openclaw/db/ocas-elephas/
  chronicle.lbug      — Chronicle graph database (auto-created on first use)
  config.json         — consolidation and inference configuration
  staging/            — temporary files during ingestion passes
  intake/             — incoming signals from other skills
    {signal_id}.signal.json
    processed/        — moved here after ingestion

~/openclaw/journals/ocas-elephas/
  YYYY-MM-DD/
    {run_id}.json     — one Action Journal per consolidation or promotion run
```


Default config.json:
```json
{
  "skill_id": "ocas-elephas",
  "skill_version": "2.2.0",
  "config_version": "1",
  "created_at": "",
  "updated_at": "",
  "consolidation": {
    "immediate_interval_minutes": 15,
    "deep_interval_hours": 24
  },
  "identity": {
    "auto_merge_threshold": 0.90,
    "flag_review_threshold": 0.70
  },
  "inference": {
    "enabled": true,
    "min_supporting_nodes": 3
  },
  "retention": {
    "days": 0
  }
}
```


## Database rules

LadybugDB is an embedded single-file database. One `READ_WRITE` process at a time. Other skills open `chronicle.lbug` as `READ_ONLY` only — Elephas holds the `READ_WRITE` connection during active passes.

Surface lock errors immediately. Do not retry silently.


## Auto-initialization

Every command that opens the database runs `_ensure_init()` first. No manual init needed on first use.

```python
import real_ladybug as lb
from pathlib import Path
import json
from datetime import datetime, timezone

ROOT = Path("~/openclaw").expanduser()
DB_PATH = ROOT / "db/ocas-elephas/chronicle.lbug"
INTAKE = ROOT / "db/ocas-elephas/intake"
STAGING = ROOT / "db/ocas-elephas/staging"
JOURNALS = ROOT / "journals/ocas-elephas"
CONFIG_PATH = ROOT / "db/ocas-elephas/config.json"

def _open_db(read_only=False):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    INTAKE.mkdir(parents=True, exist_ok=True)
    (INTAKE / "processed").mkdir(parents=True, exist_ok=True)
    STAGING.mkdir(parents=True, exist_ok=True)
    JOURNALS.mkdir(parents=True, exist_ok=True)
    _ensure_config()
    db = lb.Database(str(DB_PATH), read_only=read_only)
    conn = lb.Connection(db)
    if not read_only:
        _ensure_init(conn)
    return db, conn

def _ensure_init(conn):
    tables = {row[0] for row in conn.execute("CALL show_tables() RETURN *")}
    if "Entity" not in tables:
        _run_ddl(conn)

def _run_ddl(conn):
    # Full DDL in references/schemas.md
    pass
```


## Commands

**elephas.ingest.journals** -- Ingest structured signals from skill journal files and signal intake directory. Read `references/ingestion_pipeline.md`. Auto-inits on first call. Writes Action Journal.

**elephas.consolidate.immediate** -- Immediate consolidation pass. Score candidate confidence, promote above threshold, flag possible matches. Writes Action Journal.

**elephas.consolidate.deep** -- Deep pass: full identity reconciliation, inference generation, graph cleanup. Writes Action Journal.

**elephas.identity.resolve** -- Attempt to resolve whether two Entity records refer to the same real-world entity. Read `references/ingestion_pipeline.md` → Deduplication. Never silently collapse records. Writes Action Journal.

**elephas.identity.merge** -- Merge two confirmed-same Entity records. Always reversible. Append to merge_history. Writes Action Journal.

**elephas.candidates.list** -- List pending candidates by confidence tier and age.

**elephas.candidates.promote** -- Manually promote a candidate to a confirmed Chronicle fact. Requires at least one supporting signal. Writes Action Journal.

**elephas.candidates.reject** -- Reject a candidate with stated reason. Writes Action Journal.

**elephas.query** -- Query Chronicle for entities, relationships, events, or inferences. Read `references/schemas.md` for node types and Cypher patterns. All queries are read-only. Returns only confirmed facts unless `include_candidates=true` specified.

**elephas.init** -- Diagnostic and repair command. Checks schema, creates missing tables, verifies indexes. Use when troubleshooting — the database initializes automatically on first use.

**elephas.status** -- Report Chronicle health.

```cypher
CALL show_tables() RETURN *;
MATCH (e:Entity) RETURN count(e) AS entities;
MATCH (p:Place) RETURN count(p) AS places;
MATCH (c:Concept) RETURN count(c) AS concepts;
MATCH (s:Signal {status: 'active'}) RETURN count(s) AS pending_signals;
MATCH (c:Candidate {status: 'pending'}) RETURN count(c) AS pending_candidates;
MATCH ()-[r]->() RETURN count(r) AS relationships;
CALL show_warnings() RETURN *;
```

Also report: last consolidation timestamps, pending identity reviews, inference count, intake queue depth.

**elephas.journal** -- Write Action Journal for the current run. Read `references/journal.md`. Called at end of every consolidation, promotion, merge, or rejection run.


## Run completion

After every Elephas command that modifies Chronicle or processes signals:

1. Process all files in `~/openclaw/db/ocas-elephas/intake/`; move processed files to `intake/processed/`
2. Persist ingestion results, promotion decisions, and merge records
3. Log material decisions to `decisions.jsonl` (if data directory exists)
4. Write journal via `elephas.journal`

## Memory lifecycle

```
Skill Journal / Signal Intake
  → Signal (immutable after creation)
    → Candidate (pending until confirmed, rejected, or merged)
      → Chronicle Fact (persists indefinitely)
      → Inference (separate, never overwrites facts)
```


## Consolidation passes

Immediate (every 15 min) -- creates candidates, scores confidence, promotes high-confidence. Scheduled -- promotes remaining, deduplicates.
Deep (every 24 hr) -- full identity reconciliation, inference generation, graph cleanup.


## Identity resolution rules

States: `distinct` (default), `possible_match`, `confirmed_same`. Merges are always reversible.

Resolution precedence: exact identifier match → name+location with corroboration → behavioral pattern match.

Ambiguous cases preserve separation. Never silently collapse records.


## Write authority

Only Elephas writes to Chronicle. Other skills open `chronicle.lbug` as `READ_ONLY` only.

Elephas does not write to any other skill's database.


## OKRs

Universal OKRs from spec-ocas-journal.md apply. Elephas-specific:

```yaml
skill_okrs:
  - name: promotion_precision
    metric: fraction of promoted candidates uncontradicted after 30 days
    direction: maximize
    target: 0.90
    evaluation_window: 30_runs
  - name: identity_merge_accuracy
    metric: fraction of auto-merges not subsequently reversed by human review
    direction: maximize
    target: 0.95
    evaluation_window: 30_runs
  - name: candidate_queue_age
    metric: median age of pending candidates in hours
    direction: minimize
    target: 24
    evaluation_window: 30_runs
  - name: ingestion_coverage
    metric: fraction of journal files ingested within one consolidation cycle
    direction: maximize
    target: 0.99
    evaluation_window: 30_runs
```


## Optional skill cooperation

- All skills — ingest structured signals from skill journals and signal intake
- Weave — read-only cross-DB queries for social graph enrichment
- Mentor — Mentor reads Chronicle (read-only) for evaluation context


## Journal outputs

Action Journal — every consolidation, promotion, merge, rejection, and ingestion run.


## Initialization

On first invocation of any Elephas command, run `elephas.init`:

1. Create `~/openclaw/db/ocas-elephas/` and subdirectories (`staging/`, `intake/`, `intake/processed/`)
2. Write default `config.json` with ConfigBase fields if absent
3. Create `~/openclaw/journals/ocas-elephas/`
4. Open database with `_open_db()` which auto-creates `chronicle.lbug` and runs DDL if needed
5. Register cron jobs `elephas:ingest` and `elephas:deep` if not already present (check `openclaw cron list` first)
6. Log initialization as a DecisionRecord


## Background tasks

| Job name | Mechanism | Schedule | Command |
|---|---|---|---|
| `elephas:ingest` | cron | `*/15 * * * *` (every 15 min) | `elephas.ingest.journals` then `elephas.consolidate.immediate` |
| `elephas:deep` | cron | `0 4 * * *` (daily 4am) | `elephas.consolidate.deep` — full identity reconciliation, inference, cleanup |

Cron options: `sessionTarget: isolated`, `lightContext: true`, `wakeMode: next-heartbeat`.

Registration during `elephas.init`:
```
openclaw cron list
# If elephas:ingest absent:
openclaw cron add --name elephas:ingest --schedule "*/15 * * * *" --command "elephas.ingest.journals && elephas.consolidate.immediate" --sessionTarget isolated --lightContext true --wakeMode next-heartbeat --timezone America/Los_Angeles
# If elephas:deep absent:
openclaw cron add --name elephas:deep --schedule "0 4 * * *" --command "elephas.consolidate.deep" --sessionTarget isolated --lightContext true --wakeMode next-heartbeat --timezone America/Los_Angeles
```


## Visibility

public


## Reference file map

File | When to read
`references/schemas.md` | Before any DDL, query, or data write; before elephas.init
`references/ontology.md` | When evaluating entity types, relationship types, or identity rules
`references/ingestion_pipeline.md` | Before elephas.ingest.journals or any consolidation pass
`references/journal.md` | Before elephas.journal; at end of every run
