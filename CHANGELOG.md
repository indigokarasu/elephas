# Changelog

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
