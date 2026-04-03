# 🐘 Elephas

Elephas is the system's long-term memory -- the sole writer to Chronicle, the authoritative knowledge graph where entities, relationships, events, and inferences live permanently once confirmed. It ingests structured signals from every skill's journals, extracts entity knowledge from Memory files and session logs, scores candidate facts for confidence and user relevance, resolves identity across possible duplicates, and promotes what survives into durable Chronicle facts with full provenance.

---

## Overview

Every other skill in the OCAS suite generates signals -- Elephas is what makes those signals permanent. It ingests structured signal files from all skill journals, Memory files, and session log transcripts, scores candidate facts for confidence, evaluates whether entities are relevant to the user's world (vs. incidental to agent task execution), resolves identity across potential duplicates using a staged merge protocol, and promotes what survives into Chronicle as durable facts with full provenance. As the sole writer to Chronicle, Elephas is the single source of truth for long-term world knowledge in the system. The Chronicle database (LadybugDB, embedded single-file graph) initializes automatically on first use at `~/openclaw/db/ocas-elephas/chronicle.lbug`.

Chronicle is the **user's** personal knowledge graph. Only entities relevant to the user's world are promoted. Entities encountered only during agent research or task execution remain as unpromoted candidates.

## Commands

| Command | Description |
|---|---|
| `elephas.ingest.journals` | Ingest structured signals from skill journal files and signal intake directory |
| `elephas.ingest.memory` | Extract entity knowledge from Memory files (MEMORY.md and memory/*.md) |
| `elephas.ingest.sessions` | Extract entity knowledge from session log transcripts |
| `elephas.consolidate.immediate` | Score candidate confidence, evaluate user relevance, promote above threshold |
| `elephas.consolidate.deep` | Full ingestion (including Memory and sessions), identity reconciliation, inference, cleanup |
| `elephas.identity.resolve` | Attempt to resolve whether two Entity records are the same real-world entity |
| `elephas.identity.merge` | Merge two confirmed-same Entity records (always reversible) |
| `elephas.candidates.list` | List pending candidates by confidence tier, user relevance, and age |
| `elephas.candidates.promote` | Manually promote a candidate to a confirmed Chronicle fact |
| `elephas.candidates.reject` | Reject a candidate with stated reason |
| `elephas.query` | Query Chronicle for entities, relationships, events, or inferences |
| `elephas.init` | Diagnostic and repair: checks schema, creates missing tables, verifies indexes |
| `elephas.status` | Chronicle health: entity counts, pending candidates, last consolidation timestamps |
| `elephas.journal` | Write journal for the current run |
| `elephas.update` | Pull latest from GitHub source (preserves journals and data) |

## Setup

`elephas.init` runs automatically on first invocation and creates all required directories, config.json, the Chronicle database, and JSONL files. It also registers the `elephas:ingest` and `elephas:deep` cron jobs and `elephas:update` (midnight daily, self-update). No manual setup is required.

## Dependencies

**OCAS Skills**
- All skills -- ingest structured signals from skill journals and signal intake directory
- [Bower](https://github.com/indigokarasu/bower) -- ingest Drive artifact signals with user-relevant entity data
- [Weave](https://github.com/indigokarasu/weave) -- read-only cross-DB queries for social graph enrichment
- [Mentor](https://github.com/indigokarasu/mentor) -- reads Chronicle read-only for evaluation context

**OpenClaw Platform**
- Memory files -- reads `MEMORY.md` and `memory/*.md` during deep consolidation
- Session logs -- reads session log transcripts during deep consolidation

**External**
- LadybugDB -- embedded single-file graph database (auto-created at `~/openclaw/db/ocas-elephas/chronicle.lbug`)

## Scheduled Tasks

| Job | Mechanism | Schedule | Command |
|---|---|---|---|
| `elephas:ingest` | cron | `*/15 * * * *` (every 15 min) | Ingest journals then immediate consolidation |
| `elephas:deep` | cron | `0 4 * * *` (daily 4am) | Ingest Memory + sessions, full identity reconciliation, inference, cleanup |
| `elephas:update` | cron | `0 0 * * *` (midnight daily) | Self-update from GitHub source |

## Changelog

### v3.1.0 -- April 3, 2026
- Added signal format normalization layer to ingestion pipeline
- Auto-detects legacy format (`signal_id`, `signal_type`, `provenance`) and converts to native format (`id`, `source_skill`, `source_type`)
- Unknown/extra fields preserved in `_legacy_metadata` — data is never silently discarded
- Audit trail via `_normalized_from` field on converted signals
- Best-effort conversion for unrecognized signal schemas (requires `payload` + timestamp)
- Config toggle: `signal_normalization.enabled` (default: `true`)
- Backlog recovery: `requeue_errors_on_enable` reprocesses previously rejected signals through normalization
- Resolves 9,009 rejected signals from intake/errors backlog

### v3.0.0 -- April 2, 2026
- Added Memory file ingestion (`elephas.ingest.memory`) — extracts entities from MEMORY.md and daily notes
- Added session log ingestion (`elephas.ingest.sessions`) — extracts entities from conversation transcripts, filtering out machine noise
- Added user relevance model (`user` / `agent_only` / `unknown`) — only user-relevant entities are promoted to Chronicle facts
- Added `user_relevance` field to Signal and Candidate schemas
- Added `source_type` field to Signal schema (journal / intake / memory / session_log)
- Updated promotion criteria to require `user_relevance: "user"`
- Updated deep consolidation cron to include Memory and session ingestion
- Added relevance-related OKRs (relevance_accuracy, agent_only_filter_rate)
- All skills now expected to include entity observations in journal payloads
- Bower recognized as primary Drive artifact signal source

### v2.3.0 -- March 27, 2026
- Added `elephas.update` command and midnight cron for automatic version-checked self-updates

### v2.2.0 -- March 22, 2026
- Routing improvements

### v2.1.0 -- March 22, 2026
- Automated maintenance with cron registration
- Ingestion pipeline with staged signal promotion
- Deep consolidation pass with identity reconciliation

### v2.0.0 -- March 18, 2026
- Initial release as part of the unified OCAS skill suite
---

*Elephas is part of the [OpenClaw Agent Suite](https://github.com/indigokarasu) -- a collection of interconnected skills for personal intelligence, autonomous research, and continuous self-improvement. Each skill owns a narrow responsibility and communicates with others through structured signal files, shared journals, and Chronicle, a long-term knowledge graph that accumulates verified facts over time.*
