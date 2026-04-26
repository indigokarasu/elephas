# Elephas Scripts

Utility scripts for Chronicle maintenance and diagnostics.

## elephas_pipeline.py

Self-contained ingest + immediate consolidation pipeline. This is the
canonical script invoked by the `elephas:ingest` cron and by the
`elephas.ingest.journals` / `elephas.consolidate.immediate` commands.

**Features:**
- Cleans stale ingestion-log entries
- Processes unprocessed journal files from all skill directories
- Extracts entities_observed, relationships_observed, preferences_observed
- Handles legacy and native signal payload formats (including Python repr)
- Creates Signal nodes and Candidate nodes
- Runs `run_weave_enrichment_ingest()` for the Weave enrichment format gap
- Promotes eligible candidates to Chronicle facts
- Writes Action Journal

**Usage:**
```bash
python3 /root/.hermes/skills/ocas-elephas/scripts/elephas_pipeline.py
```

**Key behaviors:**
- Checks ingestion log to avoid reprocessing files
- Handles Python repr payloads (common format bug)
- Uses correct paths: `/root/.hermes/commons/db/ocas-elephas/`
- Maps node types to correct property names (entity_type, place_type, etc.)
- Creates label-aware Promotes edges

**Output:**
- Processes up to 50 unprocessed journal files per run
- Creates signals from entities_observed and signal payloads
- Creates or updates candidates from signals
- Promotes user-relevant candidates with high/med confidence
- Writes detailed journal to `journals/ocas-elephas/YYYY-MM-DD/`

## elephas_deep_pipeline.py

Companion script for deep consolidation: ingests Memory files and session
logs, then runs identity reconciliation and inference generation. Invoked
by the `elephas:deep` cron.

**Usage:**
```bash
python3 /root/.hermes/skills/ocas-elephas/scripts/elephas_deep_pipeline.py
```

## _cron_status.py

Cron health diagnostic helper.

## Diagnostic queries

Quick Cypher queries for Chronicle health checks:

```cypher
-- Orphan signals (should be 0)
MATCH (s:Signal {status: 'active'})
WHERE NOT EXISTS { MATCH (s)-[:Supports]->() }
RETURN count(s) as orphans;

-- Active signal relevance breakdown
MATCH (s:Signal {status: 'active'})
RETURN s.user_relevance, count(s);

-- Candidate status distribution
MATCH (c:Candidate)
RETURN c.status, count(c)
ORDER BY count(c) DESC;

-- Candidates needing attention
MATCH (c:Candidate)
WHERE c.status IN ['flagged', 'possible_match']
RETURN c.id, c.status, c.user_relevance, c.confidence, c.proposed_data;

-- Promotable candidates
MATCH (c:Candidate {status: 'pending', user_relevance: 'user'})
WHERE c.confidence IN ['high', 'med']
RETURN c.id, c.proposed_data, c.confidence;
```
