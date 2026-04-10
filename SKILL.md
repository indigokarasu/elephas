---
name: ocas-elephas
description: >
  Elephas: long-term knowledge graph (Chronicle) maintenance. Ingests
  structured signals from system journals, Memory files, and session logs.
  Resolves entity identity, evaluates user relevance, promotes confirmed
  facts, and generates inferences. Trigger phrases: 'what does Chronicle know
  about', 'query the knowledge graph', 'ingest journals', 'consolidate',
  'resolve entity', 'Chronicle status', 'update elephas'. Use when querying
  world knowledge, ingesting signals, running consolidation, resolving entity
  duplicates, or promoting candidates to confirmed facts.
metadata:
  author: Indigo Karasu
  email: mx.indigo.karasu@gmail.com
  version: "3.2.2"
  hermes:
    tags: [knowledge-graph, ingestion, entities]
    category: memory
    cron:
      - name: "elephas:update"
        schedule: "0 0 * * *"
        command: "elephas.update"
  openclaw:
    skill_type: system
    visibility: public
    filesystem:
      read:
        - "{agent_root}/commons/data/ocas-elephas/"
        - "{agent_root}/commons/journals/ocas-elephas/"
        - "{agent_root}/commons/db/ocas-elephas/"
        - "{agent_root}/commons/journals/*/"
        - "{agent_root}/commons/workspace/MEMORY.md"
        - "{agent_root}/commons/workspace/memory/"
        - "{agent_root}/commons/agents/*/sessions/"
      write:
        - "{agent_root}/commons/data/ocas-elephas/"
        - "{agent_root}/commons/journals/ocas-elephas/"
        - "{agent_root}/commons/db/ocas-elephas/"
    self_update:
      source: "https://github.com/indigokarasu/elephas"
      mechanism: "version-checked tarball from GitHub via gh CLI"
      command: "elephas.update"
      requires_binaries: [gh, tar, python3]
    cron:
      - name: "elephas:update"
        schedule: "0 0 * * *"
        command: "elephas.update"
---

# Elephas

Elephas is the system's long-term memory — the sole writer to Chronicle, the authoritative knowledge graph where entities, relationships, events, and inferences live permanently once confirmed. It ingests structured signals from every skill's journals, extracts entity knowledge from Memory files and session logs, scores candidate facts for confidence and user relevance, resolves identity across possible duplicates, and promotes what survives into durable Chronicle facts with full provenance. The Chronicle database initializes automatically on first use — no manual setup required.

Chronicle is the **user's** personal knowledge graph. Only entities relevant to the user's world are promoted to Chronicle facts. Entities encountered only during agent task execution (research, scanning, analysis) remain as unpromoted candidates and are never written to the permanent graph.


## When to use

- Query Chronicle for entities, relationships, events, or inferences
- Ingest new signals from skill journals, Memory files, or session logs
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

Elephas reads Memory files and session logs as additional ingestion sources during deep consolidation passes. It does not write to Memory files or session logs.

## Ontology types

Elephas is the authoritative owner of all entity types in Chronicle:

- **Entity/Person** — people and identities
- **Entity/AI** — AI agents and systems
- **Place** — locations and venues
- **Concept/Event** — discrete events and occurrences
- **Concept/Action** — behaviors and actions
- **Concept/Idea** — topics, themes, and abstract concepts
- **Thing/DigitalArtifact** — files, URLs, documents, and digital objects

Elephas is the sole writer to Chronicle. Signals arrive via skill journals, journal signal payloads (journal payload fields (see interfaces specification)), Memory files, and session logs.

## User relevance model

Chronicle is the user's personal knowledge graph. Not every entity the system encounters belongs in it.

Every Signal and Candidate carries a `user_relevance` field: `user` / `agent_only` / `unknown`.

- `user` — entity exists in the user's world. The user mentioned it, it appears in their files, or it has a direct relationship to the user. Only `user` entities are promoted to Chronicle facts.
- `agent_only` — entity was encountered during agent task execution with no demonstrated connection to the user. Remains as a Candidate indefinitely. Never promoted.
- `unknown` — relevance not yet determined. Resolved during consolidation.

Relevance signals (strongest to weakest):
1. User mentioned entity in conversation (session log, human role)
2. Entity appears in Memory/ files
3. Entity appears in user's Drive (Bower signals)
4. Agent wrote about entity to Memory/
5. Direct relationship to known `user` entity in Chronicle
6. Skill research output only → `agent_only`

Relevance never downgrades. Once `user`, always `user`.

Read `references/ontology.md` → User relevance for full details.
Read `references/ingestion_pipeline.md` → User relevance scoring for implementation.

## Storage layout

```
{agent_root}/commons/db/ocas-elephas/
  chronicle.lbug          — Chronicle graph database (auto-created on first use)
  config.json             — consolidation, inference, and ingestion configuration
  ingestion_log.jsonl     — tracks processed journal files
  memory_ingestion_log.jsonl  — tracks processed Memory file hashes
  session_ingestion_log.jsonl — tracks processed session log offsets
  staging/                — temporary files during ingestion passes
    {signal_id}.signal.json
    processed/            — moved here after ingestion

{agent_root}/commons/journals/ocas-elephas/
  YYYY-MM-DD/
    {run_id}.json         — one Action Journal per consolidation or promotion run
```


Default config.json:
```json
{
  "skill_id": "ocas-elephas",
  "skill_version": "3.1.0",
  "config_version": "2",
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
  },
  "memory_ingestion": {
    "enabled": true,
    "cadence": "deep"
  },
  "session_log_ingestion": {
    "enabled": true,
    "cadence": "deep",
    "entry_types": ["message"],
    "roles": ["human", "assistant"]
  },
  "signal_normalization": {
    "enabled": true,
    "log_conversions": true,
    "requeue_errors_on_enable": true
  }
}
```


## Database rules

LadybugDB is an embedded single-file database. One `READ_WRITE` process at a time. Other skills open `chronicle.lbug` as `READ_ONLY` only — Elephas holds the `READ_WRITE` connection during active passes.

Surface lock errors immediately. Do not retry silently.


## Auto-initialization

Every command that opens the database runs `_ensure_init()` first. No manual init needed on first use.

Read `references/init_pattern.md` for the `_open_db` implementation pattern. Full DDL is in `references/schemas.md`.


## Commands

**elephas.ingest.journals** -- Ingest structured signals from skill journal files and signal journal payload. Intake signals are normalized to native format before processing (legacy and unknown formats are auto-detected and converted). Read `references/ingestion_pipeline.md`. Auto-inits on first call. Writes Action Journal.

**elephas.ingest.memory** -- Extract entity knowledge from Memory files (`MEMORY.md` and `memory/*.md`). Runs during deep consolidation. Tracks content hashes to avoid reprocessing unchanged files. All signals created from Memory files have `user_relevance: "user"`. Writes Action Journal.

**elephas.ingest.sessions** -- Extract entity knowledge from session log transcripts. Runs during deep consolidation. Only processes `message` entries from `human` and `assistant` roles — skips all machine-generated content (tool results, compaction summaries, custom entries). Signals from human messages have `user_relevance: "user"`. Tracks byte offsets to resume from last processed position. Writes Action Journal.

**elephas.consolidate.immediate** -- Immediate consolidation pass. Score candidate confidence, evaluate user relevance, promote above threshold (user-relevant only), flag possible matches. Writes Action Journal.

**elephas.consolidate.deep** -- Deep pass: ingest Memory files and session logs, full identity reconciliation, user relevance resolution, inference generation, graph cleanup. Writes Action Journal.

**elephas.identity.resolve** -- Attempt to resolve whether two Entity records refer to the same real-world entity. Read `references/ingestion_pipeline.md` → Deduplication. Never silently collapse records. Writes Action Journal.

**elephas.identity.merge** -- Merge two confirmed-same Entity records. Always reversible. Append to merge_history. Writes Action Journal.

**elephas.candidates.list** -- List pending candidates by confidence tier, user relevance, and age.

**elephas.candidates.promote** -- Manually promote a candidate to a confirmed Chronicle fact. Requires at least one supporting signal and `user_relevance: "user"`. Writes Action Journal.

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
MATCH (c:Candidate {status: 'pending', user_relevance: 'user'}) RETURN count(c) AS promotable_candidates;
MATCH (c:Candidate {status: 'pending', user_relevance: 'agent_only'}) RETURN count(c) AS agent_only_candidates;
MATCH ()-[r]->() RETURN count(r) AS relationships;
CALL show_warnings() RETURN *;
```

Also report: last consolidation timestamps, pending identity reviews, inference count, journal signal queue depth, memory ingestion last run, session ingestion last run.

**elephas.journal** -- Write Action Journal for the current run. Read `references/journal.md`. Called at end of every consolidation, promotion, merge, or rejection run.

**elephas.update** -- Pull latest skill package from GitHub source. Preserves journals and data.


## Run completion

After every Elephas command that modifies Chronicle or processes signals:

1. Process all files in journal payload fields (see interfaces specification); move processed files to the consumer's ingestion log
2. Persist ingestion results, promotion decisions, and merge records
3. Log material decisions to `decisions.jsonl` (if data directory exists)
4. Write journal via `elephas.journal`

## Knowledge lifecycle

```
Skill Journals / Signal Intake / Memory Files / Session Logs
  → Format Normalization (legacy/unknown → native, audit trail preserved)
    → Signal (immutable, carries user_relevance + source_type)
      → Candidate (pending, with confidence + user_relevance)
        → Chronicle Fact (only if user_relevance = "user" + confidence >= high)
        → Inference (separate, never overwrites facts)
        → Remains as Candidate (if agent_only — never promoted)
```


## Consolidation passes

Immediate (every 15 min) -- ingest journals and journal signal payloads, create candidates, score confidence, evaluate user relevance, promote high-confidence user-relevant candidates. Scheduled -- promotes remaining, deduplicates.

Deep (every 24 hr) -- ingest Memory files and session logs, full identity reconciliation, user relevance resolution for `unknown` candidates, inference generation, graph cleanup.


## Identity resolution rules

States: `distinct` (default), `possible_match`, `confirmed_same`. Merges are always reversible.

Resolution precedence: exact identifier match → name+location with corroboration → behavioral pattern match.

Ambiguous cases preserve separation. Never silently collapse records.


## Write authority

Only Elephas writes to Chronicle. Other skills open `chronicle.lbug` as `READ_ONLY` only.

Elephas does not write to any other skill's database. Elephas does not write to Memory files or session logs.


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
  - name: relevance_accuracy
    metric: fraction of user-relevance classifications not overridden by human review
    direction: maximize
    target: 0.90
    evaluation_window: 30_runs
  - name: agent_only_filter_rate
    metric: fraction of agent-only candidates correctly withheld from promotion
    direction: maximize
    target: 0.95
    evaluation_window: 30_runs
```


## Optional skill cooperation

- All skills — ingest structured signals from skill journals and journal signal payloads. All skills should include `entities_observed`, `relationships_observed`, and `preferences_observed` in journal payloads when entities are encountered during runs.
- Bower — ingest Drive artifact signals with user-relevant entity data
- Weave — read-only cross-DB queries for social graph enrichment; optional signal emission for Person entities
- Mentor — Mentor reads Chronicle (read-only) for evaluation context
- Corvus — reads Chronicle (read-only) for pattern analysis; reads Memory files and session logs
- Scout — emits research signals via journal payloads with `user_relevance` field
- Sift — emits research signals via journal payloads with `user_relevance` field
- Agent Memory — reads `MEMORY.md` and `memory/*.md` during deep consolidation
- Agent Sessions — reads session log transcripts during deep consolidation


## Journal outputs

Action Journal — every consolidation, promotion, merge, rejection, and ingestion run.

Additional decision payload fields for new ingestion sources:

elephas.ingest.memory:
- `memory_files_scanned`, `memory_files_changed`, `signals_created`, `candidates_created`

elephas.ingest.sessions:
- `session_files_scanned`, `session_entries_processed`, `signals_created`, `candidates_created`, `entries_skipped` (machine noise)

elephas.consolidate.immediate / .deep (extended):
- `relevance_resolved` — count of candidates moved from `unknown` to `user` or `agent_only`
- `agent_only_withheld` — count of candidates withheld from promotion due to `agent_only` relevance


## Initialization

On first invocation of any Elephas command, run `elephas.init`:

1. Create `{agent_root}/commons/db/ocas-elephas/` and subdirectories (`staging/`, journal entries, the consumer's ingestion log)
2. Write default `config.json` with ConfigBase fields if absent
3. Create `{agent_root}/commons/journals/ocas-elephas/`
4. Open database with `_open_db()` which auto-creates `chronicle.lbug` and runs DDL if needed
5. Register cron jobs `elephas:ingest`, `elephas:deep`, and `elephas:update` if not already present (check the platform scheduling registry first)
6. Log initialization as a DecisionRecord


## Background tasks

| Job name | Mechanism | Schedule | Command |
|---|---|---|---|
| `elephas:ingest` | cron | `*/15 * * * *` (every 15 min) | `elephas.ingest.journals` then `elephas.consolidate.immediate` |
| `elephas:deep` | cron | `0 4 * * *` (daily 4am) | `elephas.ingest.memory` then `elephas.ingest.sessions` then `elephas.consolidate.deep` |
| `elephas:update` | cron | `0 0 * * *` (midnight daily) | `elephas.update` |

Cron options: `sessionTarget: isolated`, `lightContext: true`, `wakeMode: next-heartbeat`.

Registration during `elephas.init`:
```
# Check platform scheduling registry for existing tasks
# Task declared in SKILL.md frontmatter metadata.{platform}.cron
# If elephas:deep absent:
# Task declared in SKILL.md frontmatter metadata.{platform}.cron
# If elephas:update absent:
# Task declared in SKILL.md frontmatter metadata.{platform}.cron
```


## Self-update

`elephas.update` pulls the latest package from the `source:` URL in this file's frontmatter. Runs silently — no output unless the version changed or an error occurred.

1. Read `source:` from frontmatter → extract `{owner}/{repo}` from URL
2. Read local version from `skill.json`
3. Fetch remote version: `gh api "repos/{owner}/{repo}/contents/skill.json" --jq '.content' | base64 -d | python3 -c "import sys,json;print(json.load(sys.stdin)['version'])"`
4. If remote version equals local version → stop silently
5. Download and install:
   ```bash
   TMPDIR=$(mktemp -d)
   gh api "repos/{owner}/{repo}/tarball/main" > "$TMPDIR/archive.tar.gz"
   mkdir "$TMPDIR/extracted"
   tar xzf "$TMPDIR/archive.tar.gz" -C "$TMPDIR/extracted" --strip-components=1
   cp -R "$TMPDIR/extracted/"* ./
   rm -rf "$TMPDIR"
   ```
6. On failure → retry once. If second attempt fails, report the error and stop.
7. Output exactly: `I updated Elephas from version {old} to {new}`


## Visibility

public


## Support file map

| File | When to read |
|---|---|
| `references/schemas.md` | Before any DDL, query, or data write; before elephas.init |
| `references/init_pattern.md` | When implementing _open_db or troubleshooting initialization |
| `references/ontology.md` | When evaluating entity types, relationship types, identity rules, or user relevance |
| `references/ingestion_pipeline.md` | Before elephas.ingest.journals, elephas.ingest.memory, elephas.ingest.sessions, or any consolidation pass |
| `references/journal.md` | Before elephas.journal; at end of every run |

## Update command

This skill self-updates every 24 hours via:

```bash
elephas.update
```

This pulls the latest version from GitHub and restarts the skill's background tasks if applicable.
