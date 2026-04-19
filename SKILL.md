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
  version: "3.2.4"
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

However, if the module is not importable or the database fails to initialize automatically, follow this manual setup procedure:

### Manual Setup Procedure

When `elephas` commands fail with import errors or missing table errors, run these steps:

1. **Initialize directories and database schema:**
   ```python
   import real_ladybug as lb
   from pathlib import Path
   
   DB_PATH = Path("/root/.hermes/db/hermes-elephas/chronicle.lbug")
   
   # Create directories
   DB_PATH.parent.mkdir(parents=True, exist_ok=True)
   (DB_PATH.parent / "intake").mkdir(parents=True, exist_ok=True)
   (DB_PATH.parent / "intake/processed").mkdir(parents=True, exist_ok=True)
   (DB_PATH.parent / "staging").mkdir(parents=True, exist_ok=True)
   (Path("/root/.hermes/journals/hermes-elephas")).mkdir(parents=True, exist_ok=True)
   
   # Run DDL to create tables
   db = lb.Database(str(DB_PATH))
   conn = lb.Connection(db)
   
   statements = [
       """CREATE NODE TABLE Entity (
           id STRING PRIMARY KEY, name STRING, entity_type STRING,
           aliases STRING, identifiers STRING, possible_matches STRING,
           merge_history STRING, identity_state STRING,
           source_skill STRING, record_time STRING
       )""",
       """CREATE NODE TABLE Place (
           id STRING PRIMARY KEY, name STRING, place_type STRING,
           coordinates STRING, address STRING,
           source_skill STRING, record_time STRING
       )""",
       """CREATE NODE TABLE Concept (
           id STRING PRIMARY KEY, name STRING, description STRING,
           concept_type STRING, event_time STRING,
           source_skill STRING, record_time STRING
       )""",
       """CREATE NODE TABLE Thing (
           id STRING PRIMARY KEY, name STRING, thing_type STRING,
           metadata STRING, source_skill STRING, record_time STRING
       )""",
       """CREATE NODE TABLE Signal (
           id STRING PRIMARY KEY, source_skill STRING,
           source_type STRING, source_journal_type STRING,
           payload STRING, user_relevance STRING,
           timestamp STRING, status STRING
       )""",
       """CREATE NODE TABLE Candidate (
           id STRING PRIMARY KEY, proposed_type STRING, proposed_data STRING,
           supporting_signals STRING, confidence STRING,
           user_relevance STRING, status STRING,
           created_at STRING, resolved_at STRING, resolved_reason STRING
       )""",
       """CREATE NODE TABLE Inference (
           id STRING PRIMARY KEY, inference_type STRING, confidence STRING,
           supporting_nodes STRING, description STRING, created_at STRING
       )""",
       """CREATE REL TABLE Relates (
           FROM Entity TO Entity,
           FROM Entity TO Concept,
           FROM Entity TO Place,
           FROM Entity TO Thing,
           FROM Concept TO Place,
           FROM Concept TO Concept,
           relationship_type STRING, evidence_refs STRING, confidence STRING,
           event_time STRING, record_time STRING,
           valid_from STRING, valid_until STRING
       )""",
       "CREATE REL TABLE Supports (FROM Signal TO Candidate)",
       """CREATE REL TABLE Promotes (
           FROM Candidate TO Entity,
           FROM Candidate TO Place,
           FROM Candidate TO Concept,
           FROM Candidate TO Thing
       )""",
       """CREATE REL TABLE Infers (
           FROM Inference TO Entity,
           FROM Inference TO Concept,
           FROM Inference TO Place
       )""",
   ]
   
   for stmt in statements:
       conn.execute(stmt)
   ```

2. **Create default config.json:**
   ```python
   from datetime import datetime, timezone
   import json
   
   CONFIG_PATH = Path("/root/.hermes/db/hermes-elephas/config.json")
   now = datetime.now(timezone.utc).isoformat()
   config = {
       "skill_id": "hermes-elephas",
       "skill_version": "3.1.0",
       "config_version": "2",
       "created_at": now,
       "updated_at": now,
       "consolidation": {"immediate_interval_minutes": 15, "deep_interval_hours": 24},
       "identity": {"auto_merge_threshold": 0.90, "flag_review_threshold": 0.70},
       "inference": {"enabled": True, "min_supporting_nodes": 3},
       "retention": {"days": 0},
       "memory_ingestion": {"enabled": True, "cadence": "deep"},
       "session_log_ingestion": {
           "enabled": True, "cadence": "deep",
           "entry_types": ["message"], "roles": ["human", "assistant"]
       },
       "signal_normalization": {
           "enabled": True, "log_conversions": True, "requeue_errors_on_enable": True
       }
   }
   CONFIG_PATH.write_text(json.dumps(config, indent=2))
   ```

3. **Test with a simple signal:**
   Create a test signal file in `~/.hermes/db/hermes-elephas/intake/test.signal.json`:
   ```json
   {
     "id": "test_signal_001",
     "source_skill": "hermes-scout",
     "source_type": "intake",
     "source_journal_type": "Research",
     "payload": {
       "name": "Alice Johnson",
       "type": "Person",
       "confidence": "high",
       "user_relevance": "user",
       "resolved_handles": {"twitter": "@alicej", "email": "alice.johnson@example.com"},
       "source_refs": ["https://example.com/alice-profile"],
       "findings_summary": "Researcher mentioned this person in context of project collaboration"
     },
     "user_relevance": "user",
     "emitted_at": "2026-04-17T08:00:00Z"
   }
   ```

4. **Run the immediate consolidation script:**
   ```bash
   python3 /root/.hermes/2026-04-06_21-34-18/skills/elephas/scripts/immediate_consolidate.py
   ```

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
2. Read local version from SKILL.md frontmatter `metadata.version`
3. Fetch remote version from SKILL.md frontmatter: `gh api "repos/{owner}/{repo}/contents/SKILL.md" --jq '.content' | base64 -d | grep 'version:' | head -1 | sed 's/.*"\(.*\)".*/\1/'`
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


## Operational notes
## Operational notes
See `references/operational_notes.md` for production lessons:
- LadybugDB stores complex fields in internal format (not standard JSON) — always handle `json.JSONDecodeError`
- Entity observation field names vary across skills (`entity` vs `name`, `entity_type` vs `type`) — check both top-level and `decision.payload`
- Use `MERGE` on primary key for idempotent writes to avoid duplicate signals
- Complex multi-step operations need Python script files (not inline terminal)
- `show_tables()` returns `[table_id, table_name, ...]` — name is at index 1

### Payload format bugs (critical)

**Python repr payloads**: Some skills emit signal payloads using `str(dict)` instead of `json.dumps(dict)`. This produces `{name: value, type: Entity}` — unquoted keys, single-quoted string values, special chars unescaped. When stored in `Signal.payload`, `json.loads()` fails silently and `_create_candidate` cannot parse the name, creating orphan signals with no candidates.

**Detection**: `json.loads()` raises `JSONDecodeError`. Fall back to the repr parser:

```python
def parse_repr_payload(text):
    """Parse Python repr format: {key: value, key: value}"""
    if not text: return {}
    text = text.strip()
    if not text.startswith('{') or not text.endswith('}'): return {}
    result = {}; inner = text[1:-1]
    pairs = []; key = ""; val = ""; depth = 0; in_key = True; i = 0
    while i < len(inner):
        c = inner[i]
        if c == '{': depth += 1; val += c
        elif c == '}': depth -= 1; val += c
        elif c == ':' and depth == 0 and in_key: in_key = False
        elif c == ',' and depth == 0 and not in_key:
            pairs.append((key.strip(), val.strip())); key = ""; val = ""; in_key = True
        else:
            if in_key: key += c
            else: val += c
        i += 1
    if key or val: pairs.append((key.strip(), val.strip()))
    for k, v in pairs:
        if v.startswith('"') and v.endswith('"'): v = v[1:-1]
        elif v.startswith("'") and v.endswith("'"): v = v[1:-1]
        result[k] = v
    return result
```

**Remediation**: On any parse failure, attempt `parse_repr_payload()` before skipping the signal. Fix stored payloads by re-serializing with `json.dumps(parsed)`.

**Name extraction**: Custodian journals use `entity` as type identifier (`Entity/Gateway`) and `description` as the display name. Use:
```python
def _extract_name(e):
    if e.get("name"): return e["name"]
    if e.get("description"): return e["description"]
    ev = e.get("entity","")
    if ev and "/" in ev: return ev.split("/")[-1]
    return ev
```

**Name extraction**: Custodian journals use `entity` as type identifier (`Entity/Gateway`) and `description` as the display name. Use:
```python
def _extract_name(e):
    if e.get("name"): return e["name"]
    if e.get("description"): return e["description"]
    ev = e.get("entity","")
    if ev and "/" in ev: return ev.split("/")[-1]
    return ev
```

**entities_observed field location**: Journal skills vary in where they emit `entities_observed`. Always check **both**:
1. Top-level: `j.get("entities_observed", [])`
2. Nested: `j.get("decision", {}).get("payload", {}).get("entities_observed", [])`

Many skills (Taste, Custodian) use top-level only. Scout uses top-level. Different skills have different conventions.

**Deduplication**: The `CONTAINS $nm` query on `proposed_data` fails if the payload is malformed repr. Always parse the payload first, extract the name, then use it for deduplication. Never let a malformed payload cause silent signal loss.

**Skipped signals leave orphans**: If `_create_candidate` fails partway through (e.g. on dedup query), the signal is still `active` but has no candidate. Always verify that every active signal eventually gets a Supports edge. Run a cleanup pass periodically:
```cypher
MATCH (s:Signal {status: 'active'})
WHERE NOT EXISTS { MATCH (s)-[:Supports]->() }
RETURN s.id, s.payload, s.user_relevance
```

### Ingestion log staleness

Failed runs write ingestion log entries with `signals_created: 0`. Subsequent runs skip those files because their paths are already logged. **Always clean stale entries** (signals_created=0 from interrupted runs) before re-processing:
```python
kept = []
for line in ingestion_log:
    e = json.loads(line)
    if not (e.get("signals_created", 0) == 0 and "TFAILURE_TIME" in e.get("ingested_at", "")):
        kept.append(line)
# rewrite ingestion_log with kept
```

### Path resolution (critical)

Elephas uses two separate database directories that are easy to confuse:

| Prefix | Path | Used by |
|---|---|---|
| `hermes-elephas` | `/root/.hermes/db/hermes-elephas/` | `immediate_consolidate.py` script (old, wrong) |
| `ocas-elephas` | `/root/.hermes/commons/db/ocas-elephas/` | Skill spec and actual Chronicle database |

**The `immediate_consolidate.py` script at `~/.hermes/2026-04-06_21-34-18/skills/elephas/scripts/immediate_consolidate.py` has hardcoded paths to `hermes-elephas` (wrong DB). Always use Python scripts you write inline that reference `commons/db/ocas-elephas/` — never run the shipped script directly without patching paths.**

Confirm the correct DB path before every run:
```python
from pathlib import Path
DB_PATH = Path("/root/.hermes/commons/db/ocas-elephas/chronicle.lbug")
assert DB_PATH.exists(), f"Wrong path: {DB_PATH}"
```

### F-string escaping in LadybugDB queries

When building Cypher queries with f-strings, escape internal quotes carefully. This FAILS:
```python
conn.execute(f"... description = '{_esc(pdata.get("findings_summary",""))}'")  # SyntaxError
```
Use single-level escaping:
```python
fs = pdata.get("findings_summary","") or ""
conn.execute(f"... description = '{_esc(fs)}'")  # OK
```

### Promotes edge creation requires label-aware MATCH (critical)

When creating Promotes edges in `_promote_candidate()`, the target entity node must be matched by its specific label. Using a label-less `MERGE (e {{id: $eid}})` causes LadybugDB to fail with:

```
Binder exception: Create node e with multiple node labels is not supported.
```

**Wrong** (in consolidate_immediate.py line ~147):
```python
conn.execute(f'''\n    MATCH (c:Candidate {{id: $cid}})\n    MERGE (e {{id: $eid}})\n    CREATE (c)-[:Promotes]->(e)\n''', {'cid': cand_id, 'eid': ent_id})
```

**Correct** — use the `node_type` variable (Entity/Place/Concept/Thing):
```python
conn.execute(f'''\n    MATCH (c:Candidate {{id: $cid}})\n    MATCH (e:{node_type} {{id: $eid}})\n    CREATE (c)-[:Promotes]->(e)\n''', {'cid': cand_id, 'eid': ent_id})
```

The entity node was already created by the preceding `MERGE` with the correct label. The Promotes edge just needs to `MATCH` it, not re-`MERGE` it without a label. Fixed 2026-04-18.

### Node type property names (critical)

When creating nodes in Chronicle, each node type has different property names for its type field. Using the wrong property name causes `Binder exception: Cannot find property {prop} for {var}`.

**Property mapping:**
| Node Type | Type Property | Example |
|---|---|---|
| Entity | `entity_type` | `entity_type: 'Person'` |
| Place | `place_type` | `place_type: 'Restaurant'` |
| Concept | `concept_type` | `concept_type: 'Event'` |
| Thing | `thing_type` | `thing_type: 'Document'` |

**Wrong** (using `entity_type` for all types):
```python
# Fails for Place/Concept/Thing nodes
conn.execute(f"""
    CREATE (e:{node_type} {{
        id: '{entity_id}',
        name: '{name}',
        entity_type: '{proposed_type}',  # WRONG for Place/Concept/Thing
        ...
    }})
""")
```

**Correct** — use type-specific property names:
```python
type_property_map = {
    "Entity": "entity_type",
    "Place": "place_type", 
    "Concept": "concept_type",
    "Thing": "thing_type"
}
type_property = type_property_map.get(node_type, "entity_type")

conn.execute(f"""
    CREATE (e:{node_type} {{
        id: '{entity_id}',
        name: '{name}',
        {type_property}: '{proposed_type}',
        ...
    }})
""")
```

Also applies to MATCH queries when filtering by type:
```python
# Wrong - fails for Place nodes
conn.execute("MATCH (p:Place) WHERE p.entity_type = 'Restaurant' RETURN p")

# Correct
conn.execute("MATCH (p:Place) WHERE p.place_type = 'Restaurant' RETURN p")
```

Discovered 2026-04-18 during immediate consolidation when promoting candidates to Place/Concept/Thing nodes.

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

---

## Integrated: elephas-debug-lessons

# Elephas Debug Lessons

LadybugDB has specific parameter quirks that cause silent failures or cryptic errors. These were discovered through direct troubleshooting and are not documented in the skill spec.

## Bug 1: Empty arrays crash Signal writes

**Symptom**: `RuntimeError: Trying to create a vector with ANY type. This should not happen.`

**Cause**: LadybugDB cannot bind `[]` (empty JSON array) as a query parameter. Payloads containing `identifiers: []` or `source_refs: []` fail at the `MERGE Signal` step.

**Fix**: Filter empty collections before `json.dumps()`:

```python
def clean_payload(d):
    """Remove None values and empty lists from dict before json.dumps."""
    if isinstance(d, dict):
        return {k: clean_payload(v) for k, v in d.items() if v is not None and v != []}
    if isinstance(d, list):
        return [clean_payload(x) for x in d if x is not None and x != []]
    return d

payload_str = json.dumps(clean_payload(sig["payload"]))
```

**Prevention**: Apply `clean_payload()` to any payload before passing to `conn.execute()` with `$pl` parameter.

---

## Bug 2: Python repr-format `supporting_signals` breaks consolidation

**Symptom**: `JSONDecodeError: Expecting value: line 1 column 2 (char 1)` when parsing `c.supporting_signals`.

**Cause**: Many candidates were created by older code (or skills) that stored Python repr lists instead of valid JSON arrays. Stored as `'[sig_a, sig_b]'` instead of `'["sig_a", "sig_b"]'`.

**Fix**: Fall back to repr parser on JSON parse failure:

```python
def parse_repr_list(s):
    """Parse Python repr list like '[item1,item2,item3]'."""
    if not s or not isinstance(s, str):
        return []
    s = s.strip()
    if not (s.startswith('[') and s.endswith(']')):
        return []
    inner = s[1:-1].strip()
    if not inner:
        return []
    result = []
    current = ""
    in_string = False
    for c in inner:
        if c == "'" and not in_string:
            in_string = True
            current += c
        elif c == "'" and in_string:
            in_string = False
            current += c
        elif c == ',' and not in_string:
            result.append(current.strip())
            current = ""
        else:
            current += c
    if current.strip():
        result.append(current.strip())
    return [x for x in result if x]

def safe_parse_json(s):
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return parse_repr_list(s)
```

**Usage**:
```python
sig_ids = safe_parse_json(supporting_raw) if supporting_raw else []
```

**Scope**: Affects `Candidate.supporting_signals` and any JSON array fields stored before this bug was known.

---

## Bug 3: `timestamp` parameter required even with defaults

**Symptom**: `Parameter 'ts' not found` when omitting optional timestamp.

**Cause**: LadybugDB Cypher parameters are always required if referenced in the query — there are no default values.

**Fix**: Always pass `ts` explicitly, even with a fallback:
```python
ts = sig.get("timestamp") or "2026-04-17T00:00:00Z"
conn.execute("... s.timestamp = $ts ...", {"ts": ts, ...})
```

---

## Bug 4: GROUP BY not supported in LadybugDB Cypher

**Symptom**: `RuntimeError: Parser exception: Invalid input <GROUP>: expected rule iC_Statements`

**Cause**: LadybugDB's Cypher dialect does not support `GROUP BY` clauses.

**Fix**: Group in Python after fetching raw results:
```python
r = list(conn.execute("MATCH (c:Candidate) RETURN c.status, count(c) as cnt"))
from collections import Counter
grouped = Counter(row[0] for row in r)
```

Same applies to any aggregation query — no `GROUP BY`, `ORDER BY` on aggregates, etc.

## Bug 5: show_tables() not available

**Symptom**: `show_tables()` or `CALL show_tables() RETURN *` produces parser errors.

**Cause**: `show_tables()` is not a valid function in this LadybugDB version.

**Fix**: Query known tables directly to verify schema:
```python
# Check if nodes exist by counting
r = list(conn.execute("MATCH (e:Entity) RETURN count(e) as cnt"))  # Works
r = list(conn.execute("MATCH (s:Signal) RETURN count(s) as cnt"))  # Works
```

## Bug 6: MERGE on relationship pattern creates duplicate nodes

**Symptom**: `RuntimeError: Found duplicated primary key value sig_XXXXXXXXXXXX, which violates the uniqueness constraint of the primary key column` when linking signals to candidates.

**Cause**: This is the most insidious bug. When you write:
```python
conn.execute(f"""
    MERGE (s:Signal {{id: '{sig_id}'}})-[:Supports]->(c:Candidate {{id: '{cand_id}'}})
""")
```
LadybugDB interprets the full pattern as a MERGE — it tries to **create new Signal and Candidate nodes** with those IDs, even though `s` and `c` are already in the DB. The error happens because nodes with those IDs already exist.

**Fix**: Separate MATCH (to find existing nodes) from MERGE (to create the edge only):
```python
conn.execute(f"""
    MATCH (s:Signal {{id: '{sig_id}'}})
    MATCH (c:Candidate {{id: '{cand_id}'}})
    MERGE (s)-[r:Supports]->(c)
""")
```

**Why this matters**: If your ingestion creates Signals but the Supports edge creation fails silently or throws, you get "orphan signals" — signals in the DB with no candidate link. Always verify after ingestion:
```cypher
MATCH (s:Signal {status: 'active'})
WHERE NOT EXISTS { MATCH (s)-[:Supports]->() }
RETURN s.id, s.payload, s.user_relevance
```

**Cleanup pattern for orphan signals**:
1. Try to find a matching pending candidate by name:
```python
existing = list(conn.execute("""
    MATCH (c:Candidate {status: 'pending'})
    WHERE c.proposed_data CONTAINS $nm
    RETURN c.id
""", {"nm": name}))
if existing:
    cand_id = existing[0][0]
    # Link using MATCH + MERGE
    conn.execute(f"""
        MATCH (s:Signal {{id: '{sig_id}'}})
        MATCH (c:Candidate {{id: '{cand_id}'}})
        MERGE (s)-[r:Supports]->(c)
    """)
    conn.execute(f"""
        MATCH (c:Candidate {{id: '{cand_id}'}})
        SET c.supporting_signals = c.supporting_signals + '|{sig_id}'
    """)
else:
    # No match - delete the orphan signal
    conn.execute(f"MATCH (s:Signal {{id: '{sig_id}'}}) DELETE s")
```

**Never use**: `CREATE (s)-[:Supports]->(c)` inside a transaction that also creates the signal — the CREATE on an already-existing signal throws.

## Bug 7: `CONTAINS` query on malformed repr payloads returns no match

**Symptom**: A signal is created and a candidate is created, but the deduplication query `WHERE c.proposed_data CONTAINS $nm` fails to find the existing candidate, causing duplicate candidates for the same entity.

**Cause**: If the existing candidate's `proposed_data` is stored in Python repr format (e.g., `{name: Alice, type: Person}`) and you're searching for `"Alice"`, the `CONTAINS` query still works — but if the field name itself differs (e.g., one candidate has `name` and another has `entity`), deduplication fails silently.

**Fix**: Normalize all proposed_data to JSON before storing. Always parse and re-serialize to ensure consistent format:
```python
pay = sig.get("payload", {})
pay_json = json.dumps(pay)  # Always use json.dumps
conn.execute(f"... c.proposed_data = '{_esc(pay_json)}' ...")
```

## Bug 8: Candidate proposed_type field name varies by emitting skill

**Symptom**: Deduplication queries using `proposed_type = 'Entity'` miss candidates stored as `type: 'Entity/Person'` or `type: 'Person'`.

**Cause**: Different skills use different field names (`proposed_type`, `type`, `entity_type`) and different values (`Entity`, `Entity/Person`, `Person`).

**Fix**: Check all type-like fields when parsing:
```python
def extract_proposed_type(pdata):
    return pdata.get("proposed_type") or pdata.get("type") or pdata.get("entity_type") or ""

def extract_name(pdata):
    return pdata.get("name") or pdata.get("description") or pdata.get("entity", "")
```

## Path Resolution

Elephas uses two separate database directories:

| Prefix | Path | Used by |
|---|---|---|
| `hermes-elephas` | `/root/.hermes/db/hermes-elephas/` | Old shipped scripts (wrong) |
| `ocas-elephas` | `/root/.hermes/commons/db/ocas-elephas/` | Skill spec and actual Chronicle |

The `immediate_consolidate.py` in the skill directory has hardcoded paths to `hermes-elephas`. **Always write new inline scripts referencing `commons/db/ocas-elephas/`**.

Verify before every run:
```python
from pathlib import Path
DB_PATH = Path("/root/.hermes/commons/db/ocas-elephas/chronicle.lbug")
assert DB_PATH.exists(), f"Wrong path: {DB_PATH}"
```

---

## Ingestion log format migration

Old entries use `processed_at` + `signals_created` fields. New entries use `journal_path` + `ingested_at`. Both formats coexist in the same log file.

Stale entries (from failed runs with `signals_created: 0` and `TFAILURE_TIME` in timestamp) must be cleaned before re-processing:
```python
kept = []
for line in open(log_path):
    e = json.loads(line)
    if not (e.get("signals_created", 0) == 0 and "TFAILURE_TIME" in e.get("processed_at", "")):
        kept.append(line)
```

## Ingestion Pipeline Failure Recovery

When a consolidation run is interrupted mid-way (e.g., script crash), signals may be created but the `Supports` edge (and candidate creation) fails. This leaves orphan signals.

**Recovery sequence**:
1. Clean up orphan signals before re-processing (see Bug 6 cleanup pattern)
2. Clean stale ingestion log entries
3. Re-process all unprocessed files using `MATCH + MERGE` for edges
4. Verify zero orphans after ingestion

**Never re-process files that already have ingestion log entries** (even if the previous run partially failed) — the log tracks what was processed. Only clean and re-process the files that have no log entry.

**Ingestion log check before processing**:
```python
processed_runs = set()
if INGESTION_LOG.exists():
    with open(INGESTION_LOG) as f:
        for line in f:
            try: processed_runs.add(json.loads(line.strip()).get("run_id",""))
            except: pass

unprocessed = []
for jf in journal_files:
    if jf.stem not in processed_runs:
        unprocessed.append(jf)
```

## Bug 8: MERGE + ON CREATE SET primary key constraint bug

**Symptom**: `Runtime exception: Found duplicated primary key value ent_xxxx, which violates the uniqueness constraint` even when the ID is freshly generated and should not exist.

**Cause**: `MERGE (e:Entity {id: $id}) ON CREATE SET e.name = $nm, ...` — when the ID already exists, LadybugDB's `ON CREATE` fires incorrectly and tries to re-create the node, hitting the primary key constraint. This can happen even with fresh UUIDs if a prior partial run created the entity but crashed before confirming the candidate.

**Workaround — check existence first, then branch**:
```python
existing = list(conn.execute(
    "MATCH (e:Entity) WHERE e.name = $nm RETURN e.id", {"nm": name}))
if existing:
    node_id = existing[0][0]  # reuse existing
else:
    node_id = f"ent_{secrets.token_hex(6)}"
    conn.execute("""
        MERGE (e:Entity {id: $id})
        ON CREATE SET e.name = $nm, e.entity_type = $et, ...
    """, {"id": node_id, "nm": name, ...})
```

**Workaround — MERGE then SET in separate queries**:
```python
conn.execute("MERGE (e:Entity {id: $id})", {"id": node_id})
conn.execute("""
    MATCH (e:Entity {id: $id})
    SET e.name = $nm, e.entity_type = $et, e.identity_state = 'distinct', ...
""", {"id": node_id, "nm": name, ...})
```

---

## Bug 9: Connection stability — exit code -11 segfaults

**Symptom**: `Script exited with code -11` (SIGSEGV) when running multiple LadybugDB operations in sequence.

**Cause**: The embedded DB adapter accumulates state across operations. More than ~5 write operations in a single `execute_code` call triggers a memory fault.

**Workaround**: Split multi-step operations into separate `execute_code` calls. Each call gets a fresh Python process and connection. Keep each call to ≤3 DB operations.

```python
# BAD — segfaults after ~5 operations
conn.execute("MERGE ...")
conn.execute("CREATE ...")
conn.execute("SET ...")
conn.execute("MATCH ...")
conn.execute("SET ...")

# GOOD — each in separate execute_code call
# Call 1: conn.execute("MERGE ...")
# Call 2: conn.execute("CREATE ...")
# Call 3: conn.execute("SET ...")
```

---

## Bug 10: `identity_state` only valid on Entity nodes

**Symptom**: `Binder exception: Cannot find property identity_state for e.` when promoting a Place, Concept, or Thing.

**Fix**: Only set `identity_state` on Entity labels:
```python
if label == "Entity":
    conn.execute(f"MERGE (e:Entity {id: $id}) ON CREATE SET e.name = $nm, e.identity_state = 'distinct', ...")
else:
    conn.execute(f"MERGE (e:{label} {{id: $id}}) ON CREATE SET e.name = $nm, ...")
```

---

## Bug 11: `decision.payload` can be a JSON string, not a dict

**Symptom**: `AttributeError: 'str' object has no attribute 'get'` when accessing `j["decision"]["payload"]`.

**Safe accessor**:
```python
def _get_journal_field(j, key, default=None):
    val = j.get(key, default)
    if isinstance(val, str):
        try: return json.loads(val)
        except: return default
    return val if isinstance(val, dict) else default
```

---

## Bug 12: Candidates confirmed but Promotes edge missing

**Symptom**: Entity exists in Chronicle, candidate `status` is `pending`, no `Promotes` edge.

**Recovery**: Find orphaned entities, match by name to pending candidates, link with separate queries.

---

## Consolidation Behavior: Why No Promotions Happen

**Symptom**: Immediate consolidation run completes but promotes 0 candidates, even though there are pending `user` relevance candidates.

**Explanation**: This is expected behavior. Candidates created from journal ingestion during immediate passes start at `low` confidence. Only `high` confidence candidates are promoted automatically.

**Corroboration upgrade path**: A `low` candidate upgrades to `high` only when it has 2+ supporting Signals from **different source skills**:
```cypher
MATCH (s:Signal)-[:Supports]->(c:Candidate {status: 'pending', confidence: 'low'})
WITH c, count(s) as sig_count, collect(DISTINCT s.source_skill) as sources
WHERE sig_count > 1 AND size(sources) > 1
RETURN c.id, c.user_relevance, sig_count, sources
```

**Immediate vs Deep passes**:
- Immediate (15 min): Ingests journal files. Journal-based candidates start `low`.
- Deep (daily 4am): Ingests Memory files and session logs. These carry inherent `user_relevance: user` and `confidence: med`.

High-confidence user promotions typically require either:
1. Multiple corroborated signals accumulated over several consolidation cycles, OR
2. A deep pass which ingests higher-quality user sources

**Agent-only candidates are correctly withheld**: High-confidence candidates with `user_relevance: agent_only` are never promoted — by design. They stay in the candidate pool in case future signals upgrade their relevance.

---

## Integrated: elephas-runner

# Elephas Runner

Execute Elephas ingestion and consolidation passes directly via Python scripts
using the `real_ladybug` library. The skill `ocas-elephas` is documentation-only —
there is no `elephas` CLI command in this environment.

## Environment Facts

- **Correct DB path**: `/root/.hermes/commons/db/ocas-elephas/chronicle.lbug`
  - NOT `/root/.hermes/db/hermes-elephas/` (older, separate instance)
- **real_ladybug import**: `import real_ladybug as lb`
- **Open DB pattern**:
  ```python
  db = lb.Database(str(DB_PATH))
  conn = lb.Connection(db)
  ```
- **Parameterized queries `$var` fail** with `RuntimeError: Parameter now not found` — use f-string interpolation with escaped single quotes instead:
  ```python
  conn.execute(f"MATCH (c:Candidate {{id: '{cid}'}}) SET c.confidence = '{new_conf}'")
  ```

## Known Issues

### Place entities promoted as Concepts
When promoting candidates with `proposed_type = "Place"`, the current script incorrectly creates a `Concept` node instead of a `Place` node. The MERGE and SET use `ptype` directly which maps "Place" → "Concept". Fix: branch on `ptype == "Place"` and create a `Place` node instead:
```python
if ptype == "Place":
    entity_id = f"place_{safe_name}"
    conn.execute(f"MERGE (p:Place {{id: '{entity_id}'}})")
    conn.execute(f"MATCH (p:Place {{id: '{entity_id}'}}) SET p.name = '{name}', p.place_type = 'Restaurant', p.source_skill = 'ocas-elephas', p.record_time = '{NOW}'")
    ttype = "Place"
```

### agent_only candidates have HIGH confidence but stay pending
Gateway entities (Custodian's `Entity/Gateway`) and other system-level entities are `user_relevance: agent_only` with `confidence: high`. The consolidation logic must NOT promote them — `agent_only` is a hard gate, not a confidence gate. A candidate with `confidence: high` but `user_relevance: agent_only` is correctly withheld from promotion. Only promote when `user_relevance == "user"` AND `confidence >= "high"`.

### Dispatch journals have no entities_observed
ocas-dispatch journals use `decision.payload.{drafts_created, threads_updated}` format — no `entities_observed`. Skip gracefully.

### supporting_signals JSON parse errors
The `supporting_signals` field may be stored as an invalid JSON string. Use safe parsing:
```python
def safe_json_parse(s, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except:
        return default
```

## Execution Pattern

```python
import real_ladybug as lb
import json
from pathlib import Path
from datetime import datetime, timezone

hermes_BASE = Path("/root/.hermes")
DB_PATH = hermes_BASE / "commons/db/ocas-elephas/chronicle.lbug"
ELEPHAS_JOURNALS = hermes_BASE / "commons/journals/ocas-elephas"
DECISIONS_LOG = hermes_BASE / "commons/db/ocas-elephas/decisions.jsonl"
INGESTION_LOG = hermes_BASE / "commons/db/ocas-elephas/ingestion_log.jsonl"
JOURNALS_ROOT = hermes_BASE / "commons/journals"

NOW = datetime.now(timezone.utc).isoformat()
run_id = f"cron_eiep_{NOW[:10]}_{NOW[11:19].replace(':','')}"

def _open_db():
    db = lb.Database(str(DB_PATH))
    conn = lb.Connection(db)
    return db, conn

db, conn = _open_db()
# ... do work ...
db.close()
```

## Journal File Structure

Elephas reads from: `{agent_root}/commons/journals/{skill}/YYYY-MM-DD/{run_id}.json`

### entities_observed extraction (3 locations!)

Signal entities appear in **three possible locations** in journal JSON — check all three:

1. **Top-level** `journal["entities_observed"]` — used by custodian, lucid, and many ocas skills
2. **`decision.payload.entities_observed`** — used by dispatch-style Action journals
3. **`decisions[].payload.entities_observed`** — legacy multi-decision format

```python
entities = []
if "entities_observed" in journal:
    entities.extend(journal["entities_observed"])
if "decision" in journal and isinstance(journal["decision"], dict):
    dp = journal["decision"].get("payload", {})
    if isinstance(dp, dict) and "entities_observed" in dp:
        entities.extend(dp["entities_observed"])
if "decisions" in journal and isinstance(journal["decisions"], list):
    for dec in journal["decisions"]:
        if isinstance(dec, dict) and "payload" in dec:
            pl = dec["payload"]
            if isinstance(pl, dict) and "entities_observed" in pl:
                entities.extend(pl["entities_observed"])
```

### Signal payloads (journal signal intake)

Skills like Scout/Sift drop signal objects in:
- Top-level `journal["signal"]` (may be dict or JSON string)
- `decisions[].payload.signal` (may be dict or JSON string)

Handle both. Also handle repr-format payloads (Python `str(dict)` output with unquoted keys):
```python
def parse_repr_payload(text):
    """Parse Python repr format: {key: value, key: value}"""
    if not text: return {}
    text = text.strip()
    if not text.startswith('{') or not text.endswith('}'): return {}
    result = {}
    inner = text[1:-1]
    pairs = []
    key = ""
    val = ""
    depth = 0
    in_key = True
    i = 0
    while i < len(inner):
        c = inner[i]
        if c == '{':
            depth += 1
            val += c
        elif c == '}':
            depth -= 1
            val += c
        elif c == ':' and depth == 0 and in_key:
            in_key = False
        elif c == ',' and depth == 0 and not in_key:
            pairs.append((key.strip(), val.strip()))
            key = ""
            val = ""
            in_key = True
        else:
            if in_key:
                key += c
            else:
                val += c
        i += 1
    if key or val:
        pairs.append((key.strip(), val.strip()))
    for k, v in pairs:
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        elif v.startswith("'") and v.endswith("'"):
            v = v[1:-1]
        result[k] = v
    return result
```

### custodian-light journal format (Entity/Gateway)

Custodian journals emit entities with `entity: "Entity/Gateway"` and `description` as display name. Use:
```python
def _extract_name(e):
    if e.get("name"):
        return e["name"]
    if e.get("description"):
        return e["description"]
    ev = e.get("entity", "")
    if ev and "/" in ev:
        return ev.split("/")[-1]
    return ev
```

### Journal type and skill name detection

Prefer `run_identity` over directory name:
```python
journal_type = "unknown"
source_skill = skill  # fallback to directory name
if "run_identity" in journal:
    ri = journal["run_identity"]
    journal_type = ri.get("journal_type", "unknown")
    if ri.get("skill_name"):
        source_skill = ri["skill_name"]
```

### Ingestion log — stale failure entries

Clean entries where `signals_created == 0` and `ingested_at` contains `"TFAILURE_TIME"` before re-processing. These are interrupted runs that left stale log entries:
```python
kept = []
for line in INGESTION_LOG.read_text().strip().split('\n'):
    if not line.strip():
        continue
    e = json.loads(line)
    if not (e.get("signals_created", 0) == 0 and "TFAILURE_TIME" in e.get("ingested_at", "")):
        kept.append(line)
# rewrite with kept
```

## Chronicle Node Counts Query

```python
for label in ["Entity", "Concept", "Place", "Signal", "Candidate"]:
    cnt = list(conn.execute(f"MATCH (n:{label}) RETURN count(n)"))[0][0]
    print(f"  {label}: {cnt}")
```

## Pending Candidates Query

```python
pending = list(conn.execute(
    "MATCH (c:Candidate) WHERE c.status = 'pending' RETURN c.user_relevance, count(c)"
))
for rel, cnt in pending:
    print(f"  Pending {rel}: {cnt}")
```

## Consolidation Pass (elephas.consolidate.immediate)

Full pattern for evaluating and promoting candidates:

```python
import real_ladybug as lb
import json
from pathlib import Path
from datetime import datetime, timezone
import uuid

COMMONS_ROOT = Path("/root/.hermes/commons")
DB_PATH = COMMONS_ROOT / "db/ocas-elephas/chronicle.lbug"
DECISIONS_LOG = COMMONS_ROOT / "db/ocas-elephas/decisions.jsonl"
JOURNALS = COMMONS_ROOT / "journals/ocas-elephas"

NOW = datetime.now(timezone.utc).isoformat()
run_id = f"cron_consolidate_{NOW[:10]}_{NOW[11:19].replace(':','')}"

def _esc(s):
    if s is None:
        return ""
    return str(s).replace("\\", "\\\\").replace("'", "\\'")

def safe_json_parse(s, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except:
        return default

db = lb.Database(str(DB_PATH))
conn = lb.Connection(db)

promotions = []
candidates_evaluated = 0
candidates_promoted = 0
agent_only_withheld = 0
relevance_resolved = 0

pending = list(conn.execute("""
    MATCH (c:Candidate) 
    WHERE c.status = 'pending' 
    RETURN c.id, c.proposed_type, c.proposed_data, c.supporting_signals, 
           c.confidence, c.user_relevance, c.created_at
"""))

for row in pending:
    cid, ptype, pdata_raw, sigs_raw, conf, urel, created = row
    candidates_evaluated += 1
    
    pdata = safe_json_parse(pdata_raw, {})
    if isinstance(pdata, str):
        pdata = safe_json_parse(pdata, {})
    name = pdata.get("name", "unknown") if isinstance(pdata, dict) else "unknown"
    
    sigs = safe_json_parse(sigs_raw, [])
    if isinstance(sigs, str):
        sigs = safe_json_parse(sigs, [])
    
    # Resolve unknown relevance
    if urel == "unknown":
        user_sig = any(
            list(conn.execute(f"MATCH (s:Signal {{id: '{sid}'}}) RETURN s.user_relevance"))[0][0] == "user"
            for sid in sigs
        )
        new_urel = "user" if user_sig else "agent_only"
        conn.execute(f"MATCH (c:Candidate {{id: '{cid}'}}) SET c.user_relevance = '{new_urel}'")
        urel = new_urel
        relevance_resolved += 1
    
    # HARD GATE: agent_only never promoted
    if urel == "agent_only":
        agent_only_withheld += 1
        continue
    
    # Promote only high-confidence user candidates
    if conf == "high" and urel == "user":
        safe_name = _esc(name.lower().replace(" ", "_")[:40])
        
        if ptype == "Place":
            entity_id = f"place_{safe_name}"
            conn.execute(f"MERGE (p:Place {{id: '{entity_id}'}})")
            conn.execute(f"MATCH (p:Place {{id: '{entity_id}'}}) SET p.name = '{_esc(name)}', p.place_type = 'Location', p.source_skill = 'ocas-elephas', p.record_time = '{NOW}'")
        elif ptype == "Thing":
            entity_id = f"thing_{safe_name}"
            conn.execute(f"MERGE (t:Thing {{id: '{entity_id}'}})")
            conn.execute(f"MATCH (t:Thing {{id: '{entity_id}'}}) SET t.name = '{_esc(name)}', t.thing_type = 'DigitalArtifact', t.source_skill = 'ocas-elephas', t.record_time = '{NOW}'")
        elif ptype == "Entity":
            entity_id = f"entity_{safe_name}"
            conn.execute(f"MERGE (e:Entity {{id: '{entity_id}'}})")
            conn.execute(f"MATCH (e:Entity {{id: '{entity_id}'}}) SET e.name = '{_esc(name)}', e.entity_type = 'Person', e.identity_state = 'distinct', e.source_skill = 'ocas-elephas', e.record_time = '{NOW}'")
        else:  # Concept
            entity_id = f"concept_{safe_name}"
            conn.execute(f"MERGE (c:Concept {{id: '{entity_id}'}})")
            conn.execute(f"MATCH (c:Concept {{id: '{entity_id}'}}) SET c.name = '{_esc(name)}', c.concept_type = 'Idea', c.source_skill = 'ocas-elephas', c.record_time = '{NOW}'")
        
        conn.execute(f"MATCH (ca:Candidate {{id: '{cid}'}}) MATCH (n {{id: '{entity_id}'}}) MERGE (ca)-[:Promotes]->(n)")
        conn.execute(f"MATCH (c:Candidate {{id: '{cid}'}}) SET c.status = 'confirmed', c.resolved_at = '{NOW}', c.resolved_reason = 'promoted'")
        for sid in sigs:
            conn.execute(f"MATCH (s:Signal {{id: '{sid}'}}) SET s.status = 'consumed'")
        
        candidates_promoted += 1
        promotions.append({"candidate_id": cid, "entity_name": name, "confidence": conf})

db.close()
print(f"Evaluated: {candidates_evaluated}, Promoted: {candidates_promoted}, Withheld: {agent_only_withheld}")
```

---

## Integrated: elephas-consolidation-runner

# Elephas Consolidation Runner

Run `elephas.ingest.journals` + `elephas.consolidate.immediate` via inline Python in `execute_code`. This replaces the shipped `immediate_consolidate.py` script which has hardcoded wrong paths.

## Correct DB path
```
/root/.hermes/commons/db/ocas-elephas/chronicle.lbug
```
**Not** `hermes-elephas` — that is the old wrong path.

## Python execution pattern

```python
import sys
sys.path.insert(0, '/root/.hermes/2026-04-06_21-34-18/skills/elephas/scripts')
import real_ladybug as lb
from pathlib import Path
import json, uuid
from datetime import datetime, timezone

COMMONS_ROOT = Path("/root/.hermes/commons")
DB_PATH = COMMONS_ROOT / "db/ocas-elephas/chronicle.lbug"
db = lb.Database(str(DB_PATH), read_only=False)
conn = lb.Connection(db)
```

## Orphan signal cleanup (critical)

Active signals without candidates accumulate when `_create_candidate` fails partway through (e.g., malformed repr payload). Always run this before consolidation:

```python
orphans = list(conn.execute("""
MATCH (s:Signal {status: 'active'})
WHERE NOT EXISTS { MATCH (s)-[:Supports]->() }
RETURN s.id, s.payload, s.user_relevance, s.source_skill
"""))
```

For each orphan, parse the payload (try `json.loads` first, fall back to `parse_repr_payload` below), extract name/type, check for existing candidate by name, then either link or create candidate.

## Payload parsing

Many skills emit payloads as Python repr format (`{name: value}`) instead of JSON. Always try both parsers:

```python
def parse_repr_payload(text):
    """Parse Python repr format: {key: value, key: value}"""
    if not text: return {}
    text = text.strip()
    if not text.startswith('{') or not text.endswith('}'): return {}
    result = {}
    inner = text[1:-1]
    pairs = []
    key = ""
    val = ""
    depth = 0
    in_key = True
    i = 0
    while i < len(inner):
        c = inner[i]
        if c == '{':
            depth += 1
            val += c
        elif c == '}':
            depth -= 1
            val += c
        elif c == ':' and depth == 0 and in_key:
            in_key = False
        elif c == ',' and depth == 0 and not in_key:
            pairs.append((key.strip(), val.strip()))
            key = ""
            val = ""
            in_key = True
        else:
            if in_key:
                key += c
            else:
                val += c
        i += 1
    if key or val:
        pairs.append((key.strip(), val.strip()))
    for k, v in pairs:
        if v.startswith('"') and v.endswith('"'):
            v = v[1:-1]
        elif v.startswith("'") and v.endswith("'"):
            v = v[1:-1]
        result[k] = v
    return result
```

## Confidence scoring rules

- Single signal → `low`
- 2+ signals from different source skills → `med`
- 3+ signals OR 4+ total signals → `high`

Only `high` confidence + `user` relevance candidates are promoted.

## Unknown relevance resolution

Candidates with `user_relevance: unknown` should be resolved:
- If any supporting signal has `user_relevance: user` → upgrade to `user`
- Otherwise → downgrade to `agent_only`

## Write journal

After every run, write Action Journal to:
`/root/.hermes/commons/journals/ocas-elephas/YYYY-MM-DD/{run_id}.json`

Use atomic write (write to `.tmp`, then rename).

## Standard run sequence

1. Open DB (read_write)
2. Clean stale ingestion log entries (signals_created=0 from interrupted runs)
3. Scan for new journal files not in ingestion log
4. Read each journal, extract `entities_observed` from top-level and `decision.payload`
5. Create signals for each entity
6. Create or link candidates
7. Handle orphan signals (signals without candidates)
8. Score confidence for all pending candidates
9. Resolve unknown relevance candidates
10. Promote high-confidence user candidates (or log why none eligible)
11. Log to ingestion_log.jsonl
12. Write Action Journal

---

## Integrated: elephas-operations

# Elephas Operations Skill

## Purpose
Reusable workflow for executing Elephas operations including ingestion and consolidation.

## Key Findings

### Database Architecture
- Chronicle database uses custom binary format (`.lbug` extension), not standard SQLite
- Database location: `{agent_root}/commons/db/ocas-elephas/chronicle.lbug`
- Contains tables: Entity, Signal, Candidate, Relationship, Inference, Action_Order
- Database initialized automatically on first use via `elephas.init`

### Ingestion Process
- **Command**: `elephas.ingest.journals`
- Ingests structured signals from skill journals and journal signal payloads
- Normalizes legacy/unknown formats to native format
- Creates candidates with confidence scores and user_relevance flags
- User relevance levels: `user` (promotable), `agent_only` (never promoted), `unknown` (to be resolved)
- Processes files from: `{agent_root}/commons/journals/`, Memory files, session logs

### Consolidation Process
- **Immediate pass**: `elephas.consolidate.immediate` - Runs every 15 minutes
  - Scores candidate confidence
  - Evaluates user relevance
  - Promotes high-confidence user-relevant candidates
  
- **Deep pass**: `elephas.consolidate.deep` - Runs daily at 4am
  - Ingests Memory files and session logs
  - Full identity reconciliation
  - User relevance resolution for `unknown` candidates
  - Inference generation and graph cleanup

### Execution Results
- Database: 20MB Chronicle database with active data
- Ingestion log: 285 entries processed
- System ready for journal and candidate processing
- No errors detected during operations

## Reusable Pattern
1. Verify database initialization (`elephas.init` auto-runs on first use)
2. Execute `elephas.ingest.journals` to process new signals
3. Execute `elephas.consolidate.immediate` for scoring and promotion
4. Monitor via `elephas.status` for health metrics

## Key Configuration
- Auto-initialization on first command invocation
- Cron jobs: `elephas:ingest` (every 15 min), `elephas:deep` (daily 4am), `elephas:update` (daily midnight)
- User relevance never degrades once set to `user`
- Only Elephas writes to Chronicle; other skills are read-only consumers

---

## Integrated: elephas-orphaned-signal-repair

# Elephas Orphaned Signal Repair

## When to Use

- Orphaned signals count > 0 in `elephas.status` output
- Candidates with `user_relevance: user` exist but `candidates_promoted: 0`
- `json.JSONDecodeError` on signal payloads during consolidation
- Promotion silently skips candidates due to "no name found"

## Problem Pattern

Custodian and other skills emit signal payloads using Python `str(dict)` instead of `json.dumps(dict)`, producing unquoted keys:
```
{name: Hermes gateway process running normally, proposed_type: Entity}
```
This fails `json.loads()` silently. Signal is created but no Candidate is ever linked.

Additionally, some signals use non-standard field names (`entity`, `description` instead of `name`).

## Solution Script

```python
import real_ladybug as lb
import json
import ast
import uuid
import re
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path("/root/.hermes/commons/db/ocas-elephas/chronicle.lbug")
INGESTION_LOG = Path("/root/.hermes/commons/db/ocas-elephas/ingestion_log.jsonl")
JOURNALS_DIR = Path("/root/.hermes/commons/journals/ocas-elephas")
NOW = datetime.now(timezone.utc).isoformat()

def _open_db():
    db = lb.Database(str(DB_PATH))
    conn = lb.Connection(db)
    return db, conn

def _esc(s):
    return s.replace("'", "''") if s else ""

def parse_repr_payload(text):
    """Parse Python repr format: {key: value, key: value}"""
    if not text: return {}
    text = text.strip()
    if not text.startswith('{') or not text.endswith('}'): return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    result = {}
    try:
        inner = text[1:-1]
        pairs = []; key = ""; val = ""; depth = 0; in_key = True; i = 0
        while i < len(inner):
            c = inner[i]
            if c == '{': depth += 1; val += c
            elif c == '}': depth -= 1; val += c
            elif c == ':' and depth == 0 and in_key: in_key = False
            elif c == ',' and depth == 0 and not in_key:
                pairs.append((key.strip(), val.strip())); key = ""; val = ""; in_key = True
            else:
                if in_key: key += c
                else: val += c
            i += 1
        if key or val: pairs.append((key.strip(), val.strip()))
        for k, v in pairs:
            if v.startswith('"') and v.endswith('"'): v = v[1:-1]
            elif v.startswith("'") and v.endswith("'"): v = v[1:-1]
            result[k.strip()] = v.strip()
        return result
    except:
        return {}

def _extract_name(e):
    """Extract name from entity dict per operational notes"""
    if e.get("name"): return e["name"]
    if e.get("description"): return e["description"]
    ev = e.get("entity","")
    if ev and "/" in ev: return ev.split("/")[-1]
    return ev

db, conn = _open_db()

# Step 1: Find and repair orphaned signals
orphans = list(conn.execute("""
    MATCH (s:Signal {status: 'active'})
    WHERE NOT EXISTS { MATCH (s)-[:Supports]->() }
    RETURN s.id, s.payload, s.user_relevance
"""))

repaired = 0
for sid, payload, rel in orphans:
    if not payload or payload == '{}':
        continue
    try:
        pdata = json.loads(payload)
    except json.JSONDecodeError:
        pdata = parse_repr_payload(payload)
        if pdata:
            fixed_payload = json.dumps(pdata, default=str)
            conn.execute(f"MATCH (s:Signal {{id: '{sid}'}}) SET s.payload = '{_esc(fixed_payload)}'")
            repaired += 1

print(f"Repaired: {repaired}")

# Step 2: Create candidates for orphaned signals
created = 0
active_sigs = list(conn.execute("""
    MATCH (s:Signal {status: 'active'})
    WHERE NOT EXISTS { MATCH (s)-[:Supports]->() }
    RETURN s.id, s.payload, s.user_relevance
"""))

for sig_id, payload_json, rel in active_sigs:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        payload = parse_repr_payload(payload_json)
    
    name = _extract_name(payload)
    if not name: continue
    
    ptype = payload.get("type", payload.get("proposed_type", "Entity"))
    conf = payload.get("confidence", "low")
    
    match = list(conn.execute(f"MATCH (c:Candidate {{status: 'pending'}}) WHERE c.proposed_data CONTAINS $nm RETURN c.id", {"nm": name}))
    if match: continue
    
    cid = f"cand_{uuid.uuid4().hex[:12]}"
    proposed_data = json.dumps(payload, default=str)
    conn.execute(f"""
        CREATE (c:Candidate {{
            id: '{cid}', proposed_type: '{ptype}', proposed_data: '{_esc(proposed_data)}',
            supporting_signals: '["{sig_id}"]', confidence: '{conf}',
            user_relevance: '{rel}', status: 'pending',
            created_at: '{NOW}', resolved_at: '', resolved_reason: ''
        }})
    """)
    conn.execute(f"MATCH (s:Signal {{id: '{sig_id}'}}), (c:Candidate {{id: '{cid}'}}) CREATE (s)-[:Supports]->(c)")
    created += 1

print(f"Candidates created: {created}")

# Step 3: Link orphaned signals to existing candidates
linked = 0
for sid, payload_json, rel in orphans:
    try:
        pdata = json.loads(payload_json)
    except:
        pdata = parse_repr_payload(payload_json)
    name = _extract_name(pdata)
    if not name: continue
    match = list(conn.execute(f"MATCH (c:Candidate {{status: 'pending'}}) WHERE c.proposed_data CONTAINS $nm RETURN c.id", {"nm": name}))
    if match:
        try:
            conn.execute(f"MATCH (s:Signal {{id: '{sid}'}}), (c:Candidate {{id: '{match[0][0]}'}}) CREATE (s)-[:Supports]->(c)")
            linked += 1
        except: pass

print(f"Supports edges created: {linked}")

# Step 4: Fix malformed candidate proposed_data (Python repr format)
user_cands = list(conn.execute("MATCH (c:Candidate {status: 'pending', user_relevance: 'user'}) RETURN c.id, c.proposed_data, c.confidence"))

for cid, pd, conf in user_cands:
    pdata = parse_repr_payload(pd)
    if not pdata:
        name_match = re.search(r'name:\s*([^,}]+)', pd)
        type_match = re.search(r'type:\s*([^,}]+)', pd)
        name = name_match.group(1).strip().strip("'\"") if name_match else ""
        ptype = type_match.group(1).strip().strip("'\"") if type_match else "Entity"
        pdata = {"name": name, "type": ptype}
    if not _extract_name(pdata): continue
    fixed_pd = json.dumps(pdata, default=str)
    conn.execute(f"MATCH (c:Candidate {{id: '{cid}'}}) SET c.proposed_data = '{_esc(fixed_pd)}'")
    if conf == "low":
        conn.execute(f"MATCH (c:Candidate {{id: '{cid}'}}) SET c.confidence = 'med'")

print(f"User candidates fixed")

db.close()
```

## Key Findings

1. **repr payloads are widespread**: Most custodian signals use `str(dict)` format — must parse with custom parser
2. **`_extract_name()` order**: check `name` first, then `description`, then `entity` (split on `/`)
3. **Orphaned signals with name matches**: signals whose names match existing candidates need Supports edge only, not new candidates
4. **User candidates with low confidence**: user_relevance=user means the user mentioned it — safe to upgrade low→med
5. **promote only after fixing payloads**: promotion checks `pdata.get("name")` — if repr payload not fixed, name extraction fails

## Verification Query

```python
# After repair, verify orphaned count
orphans = list(conn.execute("""
    MATCH (s:Signal {status: 'active'})
    WHERE NOT EXISTS { MATCH (s)-[:Supports]->() }
    RETURN count(s)
"""))[0][0]
print(f"Orphaned signals: {orphans}")

# Promotable user candidates
promotable = list(conn.execute("""
    MATCH (c:Candidate {status: 'pending', user_relevance: 'user'})
    WHERE c.confidence = 'high' OR c.confidence = 'med'
    RETURN c.id, c.proposed_data, c.confidence
"""))
print(f"Promotable: {len(promotable)}")
```

---

## Integrated: mempalace-setup

# MemPalace Setup & Indexing

This skill describes the process of initializing a memory palace from a directory structure and performing a deep mine (indexing) of its contents.

## Trigger Conditions
- User wants to "set up mempalace" for a specific directory.
- User wants to perform a "deep scan" or "mine" of their filesystem into MemPalace.
- Need to synchronize a large codebase or system root into the AI's long-term memory.

## Procedure

1. **Initialize Palace Structure**
   Use the `init` command to detect rooms based on the folder structure. Use the `--yes` flag to avoid interactive prompts in a CLI environment.
   ```bash
   mempalace init <directory_path> --yes
   ```

2. **Deep Indexing (Mining)**
   Run the `mine` command to process files. For large directories (e.g., root directories with >1,000 files), this process is resource-intensive and slow.
   
   **Critical Execution Strategy:**
   - **Do NOT run in foreground** for large datasets; it will likely timeout or be interrupted.
   - Use a background process with `notify_on_complete=true`.
   - If using a terminal tool, ensure the timeout is set high or the process is detached.
   
   ```bash
   mempalace mine <directory_path>
   ```

3. **Verification**
   Check the status of the filed data to ensure mining completed successfully.
   ```bash
   mempalace status
   ```

## Pitfalls & Lessons Learned
- **Interactive Prompt Failure**: `mempalace init` prompts for entity confirmation. In non-interactive shells, this causes an `EOFError`. Always use `--yes` to auto-accept detected entities.
- **Timeout Risks**: Mining thousands of files (e.g., `/root`) takes minutes to hours. Foreground tool calls will time out. Always move this to a background process.
- **Config Locations**: MemPalace typically looks for config in `~/.mempalace/config.json` or a local `mempalace.yaml` generated by `init`.
- **Python Path in MCP Config**: The hermes venv's `python3` is Python 3.11, but mempalace installs under the system Python 3.13 (`/usr/bin/python3`). The MCP server config in `~/.hermes/config.yaml` MUST use `command: /usr/bin/python3`, NOT `command: python3`. Using bare `python3` causes the MCP server to fail at startup with `ModuleNotFoundError: No module named 'mempalace'` — but Hermes swallows this error silently, so you'll only notice when skills that depend on mempalace (like ocas-lucid) can't file content. Verify with: `mempalace status` (should show drawers) and check `~/.mempalace/wal/write_log.jsonl` for recent write timestamps.
- **Delegate Agent MCP Isolation**: When a subagent (via delegate_task) connects to mempalace MCP, it gets its own ephemeral MCP process. Writes that succeed in the tool_trace may not persist to the same ChromaDB if the MCP server binary path is wrong. Always verify filings landed by checking `mempalace status` drawer count and searching for the filed content after the run.

## Verification Steps
- Run `mempalace status` to see a summary of indexed rooms and files.
- Test a search query using `mempalace search "query"` to verify data retrieval.
