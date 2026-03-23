# 🐘 Elephas

Long-term knowledge graph (Chronicle) maintenance and signal ingestion.

**Skill name:** `ocas-elephas`
**Version:** 2.2.0
**Type:** system
**Layer:** Memory
**Author:** Indigo Karasu

---

## Files

| File | Purpose |
|---|---|
| `skill.json` | Package metadata and routing description |
| `SKILL.md` | Operational instructions for the agent |
| `references/` | Support files referenced by SKILL.md |

---

## Changelog

### 2.2.0 (2026-03-22)

- Added short-name routing aliases to skill.json description and SKILL.md frontmatter for natural invocation ('Scout', 'Sift', etc.)
- Added trigger phrases to descriptions for improved routing accuracy
- Cross-skill references in descriptions now use 'use X' format for routing clarity

### 2.1.0 (2026-03-22)

- Added Run completion section with explicit intake processing, decision logging, and journal write
- Added Initialization section with cron job registration for elephas:ingest (every 15 min) and elephas:deep (daily 4am)
- Added Background tasks section declaring cron jobs
- Removed non-conformant OCAS_ROOT environment variable reference from prose and Python code
- Fixed Python code to use literal ~/openclaw/ path

### 2.0.0 (2026-03-18)

- Initial build of all OCAS skills as a unified suite
