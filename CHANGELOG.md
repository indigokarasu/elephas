## [2026-04-08] Filesystem path normalization

### Fixed
- Corrected filesystem read paths to use `{agent_root}/commons/` prefix consistently instead of `{agent_root}/`
- Aligned workspace and memory paths with OCAS storage layout conventions

### Validation
- ✓ Version: 3.1.1 → 3.1.2
- ✓ All filesystem paths now conform to spec-ocas-skill-authoring-rules.md

## [2026-04-04] Spec Compliance Update

### Changes
- Added missing SKILL.md sections per ocas-skill-authoring-rules.md
- Updated skill.json with required metadata fields
- Ensured all storage layouts and journal paths are properly declared
- Aligned ontology and background task declarations with spec-ocas-ontology.md

### Validation
- ✓ All required SKILL.md sections present
- ✓ All skill.json fields complete
- ✓ Storage layout properly declared
- ✓ Journal output paths configured
- ✓ Version: 3.1.0 → 3.1.1

# Changelog

## [3.2.5] - 2026-04-18

### Documentation
- Rewrote `references/ladybugdb_operational.md` (architectural refactor)
- Added Node Type Property Names section to `references/schemas.md` documenting `entity_type`, `place_type`, `concept_type`, `thing_type` discriminator fields
- Updated `references/ingestion_pipeline.md` with journal field location variance notes and session file format details
- Added LadybugDB API notes to `references/init_pattern.md`

## [3.2.1] - 2026-04-08

### Storage Architecture Update

- Replaced $OCAS_DATA_ROOT variable with platform-native {agent_root}/commons/ convention
- Replaced intake directory pattern with journal payload convention
- Added errors/ as universal storage root alongside journals/
- Inter-skill communication now flows through typed journal payload fields
- No invented environment variables — skills ask the agent for its root directory


## [3.2.0] - 2026-04-08

### Multi-Platform Compatibility Migration

- Adopted agentskills.io open standard for skill packaging
- Replaced skill.json with YAML frontmatter in SKILL.md
- Replaced hardcoded ~/openclaw/ paths with {agent_root}/commons/ for platform portability
- Abstracted cron/heartbeat registration to declarative metadata pattern
- Added metadata.hermes and metadata.openclaw extension points
- Compatible with both OpenClaw and Hermes Agent


## [3.1.0] - 2026-04-03

### Added
- Signal format normalization layer in ingestion pipeline — auto-detects legacy format (`signal_id`, `signal_type`, `provenance`) and converts to native format (`id`, `source_skill`, `source_type`)
- Legacy-to-native field mapping with known system name resolution (e.g., `google_workspace` → `ocas-bower`)
- Unknown/extra fields preserved in `_legacy_metadata` — data is never silently discarded
- Audit trail via `_normalized_from` field on converted signals
- Best-effort conversion for unrecognized signal schemas (requires `payload` + timestamp)
- Config toggle: `signal_normalization.enabled` (default: `true`)
- Backlog recovery: `requeue_errors_on_enable` reprocesses previously rejected signals through normalization
- `_normalized_from` and `_legacy_metadata` field notes in schemas

### Fixed
- Resolves 9,009 rejected signals from intake/errors backlog caused by format mismatch between legacy emitters and native schema

## [3.0.0] - 2026-04-02

### Added
- Memory file ingestion (`elephas.ingest.memory`) — extracts entities from MEMORY.md and daily notes during deep consolidation
- Session log ingestion (`elephas.ingest.sessions`) — extracts entities from conversation transcripts, filtering out machine noise (toolResult, compaction, custom entries)
- User relevance model (`user` / `agent_only` / `unknown`) — only user-relevant entities promoted to Chronicle facts
- `user_relevance` field on Signal and Candidate schemas
- `source_type` field on Signal schema (journal / intake / memory / session_log)
- Relevance-related OKRs (relevance_accuracy, agent_only_filter_rate)
- Memory and session ingestion logs for tracking processed files
- Bower recognized as primary Drive artifact signal source

### Changed
- Promotion criteria now requires `user_relevance: "user"` — agent-only entities remain as candidates
- Deep consolidation cron now runs `elephas.ingest.memory && elephas.ingest.sessions && elephas.consolidate.deep`
- All skills now expected to include entity observations in journal payloads
- Filesystem permissions expanded to read Memory/ and session log paths

## [2.3.2] - 2026-03-30

### Added
- `## Ontology types` section per authoring rules v2.4.0
