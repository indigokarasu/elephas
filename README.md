# 🐘 Elephas

Elephas maintains Chronicle, the suite's long-term knowledge graph, running continuously in the background. It converts activity signals into candidates, resolves identity ambiguities, promotes high-confidence facts, and generates behavioral inferences. All writes to Chronicle go through Elephas, ensuring provenance and consistency.

---

## 📖 Overview

Long-term knowledge graph (Chronicle) maintenance. Ingests structured signals from system journals, resolves entity identity, promotes confirmed facts, and generates inferences.

---

## 🔧 Tool Surface

- `elephas.query` — query Chronicle for entities, relationships, events, or inferences
- `elephas.ingest.journals` — ingest signals from Observation, Action, and Research journals
- `elephas.consolidate.immediate` — immediate consolidation pass on pending candidates
- `elephas.consolidate.deep` — deep pass with identity reconciliation and inference generation
- `elephas.identity.resolve` — determine whether two entity records are the same
- `elephas.identity.merge` — merge confirmed-same entities (reversible)
- `elephas.candidates.list` — list pending candidates with confidence scores
- `elephas.candidates.promote` — promote a candidate to confirmed fact
- `elephas.candidates.reject` — reject a candidate with reason
- `elephas.status` — node/edge counts, pending candidates, last consolidation time

---

## 📊 Output & Journals

Produces: Maintains ingestion log, candidate records, merge history, and decision log. Produces consolidated fact records and inference outputs.

---

## ⏱️ Heartbeat & Background Tasks

**Scheduled Consolidation Passes**: Immediate pass runs frequently; scheduled pass (periodic) promotes high-confidence candidates and deduplicates; deep pass (less frequent) performs full identity reconciliation and inference generation.

---

## 📚 Documentation

Read `SKILL.md` for operational details, schemas, and validation rules.

See `references/` for detailed specifications and examples.

---

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.
