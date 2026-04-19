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
  version: "3.2.7"
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

### QueryResult API (critical)

`conn.execute()` returns a `real_ladybug.query_result.QueryResult` object. It is **iterable** (supports `for row in result`) but does **not** support `len()`, indexing, or direct boolean evaluation.

**Wrong** (crashes):
```python
result = conn.execute("MATCH (c:Candidate) RETURN c.id")
print(len(result))          # TypeError: no len()
if result:                  # Works but misleading (always True)
    first = result[0]       # TypeError: not subscriptable
```

**Correct** — iterate or collect to list:
```python
result = conn.execute("MATCH (c:Candidate) RETURN c.id")
rows = [row for row in result]    # Convert to list
print(len(rows))                  # Now works

# Or iterate directly:
for row in result:
    print(row[0])  # row is a list of column values
```

**Correct** — count via Cypher instead of len():
```python
result = conn.execute("MATCH (c:Candidate {status: 'pending'}) RETURN count(c)")
rows = [row for row in result]
count = rows[0][0] if rows else 0
```

Discovered 2026-04-19 during ingestion+consolidation run.

### LadybugDB Connection API (critical)

The `real_ladybug.Connection` class does **not** accept a `mode` parameter. The correct signature is:

```python
Connection.__init__(self, database: Database, num_threads: int = 0)
```

**Wrong** (from shipped script and some docs):
```python
conn = lb.Connection(db, mode="READ_WRITE")  # TypeError: unexpected keyword argument 'mode'
```

**Correct** — no mode parameter needed:
```python
db = lb.Database(str(DB_PATH))
conn = lb.Connection(db)  # Works — all connections are read-write capable
```

The `immediate_consolidate.py` shipped script uses the wrong API. Always write inline scripts with the correct constructor. Discovered 2026-04-19.

### entities_observed field type variation (critical)

The `entities_observed` field in journal entries can be either:
- **List of dicts** — skill journals from Scout, Weave, Sift, etc. containing actual entity observations
- **Integer (0)** — Elephas' own consolidation journal files reporting `entities_observed: 0` as a count

When processing journal files, always check the type before calling `.extend()`:

**Wrong** (crashes on integer):
```python
entities_observed.extend(journal_data.get("entities_observed", []))  # TypeError if int
```

**Correct**:
```python
top_entities = journal_data.get("entities_observed", [])
if isinstance(top_entities, list):
    entities_observed.extend(top_entities)
```

This applies to both top-level and nested `decision.payload.entities_observed` fields. Discovered 2026-04-19.

### proposed_type compound labels (critical)

The `Candidate.proposed_type` field stores compound labels like `"Entity/Place"` or `"Concept/Event"` — not bare node type names. When using `proposed_type` as a Cypher node label in `CREATE (e:{node_type} ...)`, LadybugDB fails with:

```
Parser exception: Invalid input <CREATE (e:Entity/>: expected rule oC_SingleQuery
```

**Wrong** (using proposed_type directly as label):
```python
node_type = candidate.proposed_type  # "Entity/Place"
conn.execute(f"CREATE (e:{node_type} {{...}})")  # Parser error
```

**Correct** — split on "/" and use only the first segment as the node label:
```python
if "/" in proposed_type:
    node_type = proposed_type.split("/")[0]      # "Entity"
    subtype = proposed_type.split("/")[-1]        # "Place"
else:
    node_type = proposed_type
    subtype = pdata.get("type", "Unknown")

# Validate against known types
if node_type not in ("Entity", "Place", "Concept", "Thing"):
    node_type = "Entity"
```

Discovered 2026-04-19 during immediate consolidation when promoting Taste/Custodian candidates.

### Node type-specific CREATE properties (critical)

Each Chronicle node type has **different required properties**. Using Entity's property set for all types causes `Binder exception: Cannot find property {prop} for {var}`.

**Property sets by node type:**

| Node Type | Required Properties |
|---|---|
| Entity | id, name, entity_type, aliases, identifiers, possible_matches, merge_history, identity_state, source_skill, record_time |
| Place | id, name, place_type, coordinates, address, source_skill, record_time |
| Concept | id, name, description, concept_type, event_time, source_skill, record_time |
| Thing | id, name, thing_type, metadata, source_skill, record_time |

**Wrong** (using Entity properties for Concept):
```python
conn.execute(f"""CREATE (e:{node_type} {{
    id: '{ent_id}', name: '{name}', entity_type: '{subtype}',
    aliases: '[]', identifiers: '{{}}', ...  # ERROR: Concept has no 'aliases'
}})""")
```

**Correct** — use a type-aware factory function:
```python
def create_node(conn, node_type, name, subtype, source_skill="elephas-consolidate"):
    ent_id = _gen_id(node_type[:3].lower())
    ts = _ts()
    if node_type == "Entity":
        conn.execute(f"""CREATE (e:Entity {{
            id: '{_esc(ent_id)}', name: '{_esc(name)}', entity_type: '{_esc(subtype)}',
            aliases: '[]', identifiers: '{{}}', possible_matches: '[]', merge_history: '[]',
            identity_state: 'distinct', source_skill: '{_esc(source_skill)}', record_time: '{ts}'
        }})""")
    elif node_type == "Place":
        conn.execute(f"""CREATE (e:Place {{
            id: '{_esc(ent_id)}', name: '{_esc(name)}', place_type: '{_esc(subtype)}',
            coordinates: '', address: '', source_skill: '{_esc(source_skill)}', record_time: '{ts}'
        }})""")
    elif node_type == "Concept":
        conn.execute(f"""CREATE (e:Concept {{
            id: '{_esc(ent_id)}', name: '{_esc(name)}', description: '', concept_type: '{_esc(subtype)}',
            event_time: '', source_skill: '{_esc(source_skill)}', record_time: '{ts}'
        }})""")
    elif node_type == "Thing":
        conn.execute(f"""CREATE (e:Thing {{
            id: '{_esc(ent_id)}', name: '{_esc(name)}', thing_type: '{_esc(subtype)}',
            metadata: '{{}}', source_skill: '{_esc(source_skill)}', record_time: '{ts}'
        }})""")
    return ent_id
```

Discovered 2026-04-19 when promoting 15 Concept and 1 Place candidates failed with missing property errors.

### Mixed confidence formats in Candidates

The `Candidate.confidence` field stores confidence in two formats:
- **Text**: `"high"`, `"medium"`, `"low"` — from Scout/Sift/Custodian signals
- **Numeric string**: `"0.3"`, `"0.6"` — from Taste/other signals with float confidence

When filtering promotable candidates, handle all formats including legacy abbreviations:

```python
def is_promotable(conf_str):
    if conf_str in ("high",): return True
    if conf_str in ("medium", "med"): return True  # med = legacy abbreviation used by some candidates
    try:
        return float(conf_str) >= 0.6
    except:
        return False
```

**Wrong** (only checking text labels):
```python
# Misses all numeric-confidence candidates
r = conn.execute("MATCH (c:Candidate {status: 'pending', confidence: 'high'}) RETURN c")
```

**Correct** — query all pending then filter in Python:
```python
r = conn.execute("MATCH (c:Candidate {status: 'pending', user_relevance: 'user'}) RETURN c.id, c.confidence")
for row in r:
    if is_promotable(row[1]):
        # promote
```

Discovered 2026-04-19 when 132 user-relevant candidates with `confidence: "0.6"` were not being promoted.

### entities_observed strings (non-dict entities)

Some journal files store `entities_observed` as a list of **strings** rather than dicts (e.g., simple entity names from Taste or expansion journals). The `_extract_name()` function must handle both:

```python
def _extract_name(e):
    if isinstance(e, str): return e  # String entity
    if e.get("name"): return e["name"]
    # ... rest of dict handling
```

Similarly, `_extract_type()`, `_get_user_relevance()`, and confidence extraction must handle string entities gracefully:

```python
def _extract_type(e):
    if isinstance(e, str): return "Entity"  # Default for strings
    # ... dict handling

def _get_ur(e):
    if isinstance(e, str): return "unknown"  # Default for strings
    # ... dict handling
```

Discovered 2026-04-19 when processing Taste cal-scan journals with string entities.

### decision field can be a string

Some journal files store `decision` as a string rather than a dict. Always guard nested access:

```python
# Wrong - crashes if decision is a string
nested = data.get("decision", {}).get("payload", {}).get("entities_observed", [])

# Correct
decision = data.get("decision", {})
if isinstance(decision, dict):
    payload = decision.get("payload", {})
    if isinstance(payload, dict):
        nested = payload.get("entities_observed", [])
```

Discovered 2026-04-19.

### Promotion counter bug (elephas_ingest_consolidate.py)

The `elephas_ingest_consolidate.py` script's promotion counter is inaccurate. It reports "Promoted: 0" even when candidates are successfully promoted. The actual promotion logic works correctly (candidates do get promoted to Chronicle), but the counter variable is not being incremented properly.

**Symptoms**: Script output shows "Promoted: 0" but `Candidate.status = 'promoted'` entries exist in the database.

**Workaround**: Trust the database state over the script counter. Query for promoted candidates directly:
```python
result = conn.execute("""
    MATCH (c:Candidate {status: 'promoted'})
    WHERE c.resolved_at STARTS WITH '{today}'
    RETURN count(c)
""")
```

**Root cause**: The `run_consolidation()` function returns a counter that may not capture all promotion paths. Investigate the counter increment logic in the promotion flow.

Discovered 2026-04-19.

### Stale ingestion log cleanup (pre-run requirement)

Before running ingestion, always clean stale entries from `ingestion_log.jsonl`. Failed/interrupted runs write entries with `signals_created: 0`, causing subsequent runs to skip those files.

**Cleanup pattern**:
```python
from datetime import datetime, timezone

INGESTION_LOG = Path("/root/.hermes/commons/db/ocas-elephas/ingestion_log.jsonl")
lines = INGESTION_LOG.read_text().strip().split('\n')
kept = []
for line in lines:
    if not line.strip():
        continue
    entry = json.loads(line)
    if entry.get("signals_created", 0) == 0:
        ingested_at = entry.get("ingested_at", "")
        if "T" in ingested_at:
            ingested_time = datetime.fromisoformat(ingested_at.replace('Z', '+00:00'))
            age_hours = (datetime.now(timezone.utc) - ingested_time).total_seconds() / 3600
            if age_hours > 1:  # Older than 1 hour = likely stale
                continue
    kept.append(line)
INGESTION_LOG.write_text('\n'.join(kept) + '\n')
```

In a 2026-04-19 run, this cleaned 2,320 stale entries out of 3,196 total.

Discovered 2026-04-19.

### Agent-only classification for Taste signals

Taste journal signals with `user_relevance: user` in `latest_ingestion_signals.json` may still be classified as `agent_only` during ingestion. This happens because:

1. The `latest_ingestion_signals.json` format differs from what the ingestion script expects
2. The script uses different field names (`signal_id` vs `id`, `name` at top level vs nested in `payload`)
3. The user_relevance classification logic may not properly handle the Taste signal format

**Investigation needed**: Check the `_extract_relevance()` function in the ingestion script to ensure it correctly reads `user_relevance` from Taste signals.

**Workaround**: After ingestion, manually review agent_only candidates from Taste and promote user-relevant ones via `elephas.candidates.promote`.

Discovered 2026-04-19.

### Cypher CREATE closing paren bug (critical)

When writing `CREATE` statements with f-strings, the `}}` escape produces a single `}` but the Cypher statement also needs a closing `)` for the node pattern. Missing `)` causes:

```
Parser exception: Invalid input <CREATE (c:Candidate {...}: expected rule oC_SingleQuery
```

**Wrong** — `}}` on its own line, then `"""`:
```python
conn.execute(f"""
    CREATE (c:Candidate {{
        id: '{_esc(cand_id)}',
        proposed_type: '{_esc(proposed_type)}',
        ...
        resolved_reason: ''
    }}
""")
```

**Correct** — `}})` to close both the Cypher object and the CREATE pattern:
```python
conn.execute(f"""
    CREATE (c:Candidate {{
        id: '{_esc(cand_id)}',
        proposed_type: '{_esc(proposed_type)}',
        ...
        resolved_reason: ''
    }})""")
```

This affects ALL `CREATE (n:Label { ... })` statements — Candidate, Entity, Place, Concept, Thing. The `})` must be on the same line or the parser sees an unclosed pattern.

Also applies to `CREATE (e:Entity { ... })` node creation in consolidation. Same fix: `}})"""` not `}}\n"""`.

Discovered 2026-04-19 during ingest+consolidate run.

### _extract_name() doesn't handle int/float types (critical)

When `entities_observed` is an integer (e.g., `0` — Elephas' own consolidation journals report `entities_observed: 0` as a count, not a list), `_extract_name(e)` crashes with:

```
argument of type 'int' is not iterable
```

This happens because the function tries `"/" in ev` where `ev` is an int (from `e.get("entity", "")` returning `0`).

**Wrong**:
```python
def _extract_name(e):
    if isinstance(e, str): return e
    if e.get("name"): return e["name"]
    ev = e.get("entity", "")
    if ev and "/" in ev:  # TypeError if ev is int
        return ev.split("/")[-1]
    return ev
```

**Correct** — guard all type checks:
```python
def _extract_name(e):
    if isinstance(e, str): return e
    if isinstance(e, (int, float)): return str(e)
    if e.get("name"): return e["name"]
    if e.get("description"): return e["description"]
    ev = e.get("entity", "")
    if ev and "/" in str(ev): return str(ev).split("/")[-1]
    return str(ev)
```

Also affects `_extract_type()`, `_get_user_relevance()`, and confidence extraction — all must handle non-dict entity values.

Discovered 2026-04-19 during ingest+consolidate run.

### Current-run stale ingestion log entries (critical)

If ingestion fails partway through (e.g., Cypher bug prevents candidate creation), the script logs ALL files with `signals_created: 0`. The standard cleanup only removes entries older than 1 hour. A re-run within the same hour finds 0 new files because they're all already logged.

**Cleanup pattern for current-run failures**:
```python
# Remove entries from this run's timestamp range with signals=0
for line in lines:
    entry = json.loads(line)
    ingested_at = entry.get("ingested_at", "")
    # Match this run's timestamp prefix (e.g., "2026-04-19T12:37")
    if RUN_TIMESTAMP_PREFIX in ingested_at and entry.get("signals_created", 0) == 0:
        continue  # skip this entry
    kept.append(line)
```

**Prevention**: Don't log ingestion entries until the file is fully processed. Use a temporary log during processing, then commit atomically.

Discovered 2026-04-19 during ingest+consolidate run.

### elephas_run_v4.py parameter binding bug

The `elephas_run_v4.py` script in the DB directory fails with:

```
RuntimeError: Runtime exception: Trying to a create a vector with ANY type. This should not happen. Data type is expected to be resolved during binding.
```

This occurs in `create_signal_node()` when passing parameters via `conn.execute()` with a dict of parameters. LadybugDB's parameter binding has issues with certain data types in the parameter dict.

**Symptoms**: Script crashes on first signal creation attempt during ingestion.

**Workaround**: Write inline Python scripts that use string interpolation with proper escaping instead of parameter binding:

```python
# Wrong (parameter binding - fails):
conn.execute(
    "MERGE (s:Signal {id: $id}) SET s.payload = $pl ...",
    {"id": sid, "pl": payload_str}
)

# Correct (string interpolation - works):
conn.execute(f"""
    MERGE (s:Signal {{id: '{esc(sid)}'}})
    SET s.payload = '{esc(payload_str)}'
""")
```

**Root cause**: LadybugDB's parameter binding doesn't handle mixed-type parameter dicts well. String interpolation with proper escaping is more reliable.

**Alternative**: Use the manual ingestion approach documented in this conversation - write a custom script that handles heterogeneous journal structures and uses string interpolation.

Discovered 2026-04-19.

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
