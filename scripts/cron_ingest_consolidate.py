#!/usr/bin/env python3
"""Elephas cron: ingest unprocessed journals + consolidate (immediate)."""

import os
from pathlib import Path
import json
from datetime import datetime, timezone
import real_ladybug as lb

AGENT_ROOT = Path(os.environ.get("HERMES_HOME") or os.environ.get("OCAS_AGENT_ROOT") or Path.home() / ".hermes")
JOURNALS_ROOT = AGENT_ROOT / "commons/journals"
DB_DIR = AGENT_ROOT / "commons/db/ocas-elephas"
INGESTION_LOG = DB_DIR / "ingestion_log.jsonl"
DB_PATH = DB_DIR / "chronicle.lbug"

def esc(s):
    """Escape single quotes for Cypher."""
    if s is None:
        return ""
    return str(s).replace("'", "''")

# === Phase 1: Load processed files ===
processed = set()
if INGESTION_LOG.exists():
    for line in INGESTION_LOG.read_text().strip().split('\n'):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except:
            continue
        f = (entry.get("file") or entry.get("journal_file") or
             entry.get("journal_path") or entry.get("file_path") or
             entry.get("source_file", ""))
        if f:
            processed.add(f)
            if f.startswith('/'):
                try:
                    processed.add(str(Path(f).relative_to(JOURNALS_ROOT)))
                except ValueError:
                    pass
            else:
                processed.add(str(JOURNALS_ROOT / f))

# === Phase 2: Find unprocessed journal files ===
unprocessed = []
for skill_dir in sorted(JOURNALS_ROOT.iterdir()):
    if not skill_dir.is_dir() or skill_dir.name.startswith('.') or skill_dir.name == 'ocas-elephas':
        continue
    for date_dir in sorted(skill_dir.iterdir()):
        if not date_dir.is_dir():
            continue
        for f in sorted(date_dir.glob("*.json")):
            abs_p = str(f)
            rel_p = str(f.relative_to(JOURNALS_ROOT))
            if abs_p not in processed and rel_p not in processed:
                unprocessed.append(abs_p)

ts_now = datetime.now(timezone.utc).isoformat()
ts_short = ts_now[:19]

# Check for Weave enrichment files already present
# But first check if they're in the ingestion log by name pattern
weave_covered = set()
for p in processed:
    if "weave-enrichment" in p:
        weave_covered.add(p)

signals_created = 0
candidates_created = 0
promoted = 0

if not unprocessed:
    print(f"No unprocessed journal files found.")
else:
    print(f"Processing {len(unprocessed)} unprocessed journal files...")
    db = lb.Database(str(DB_PATH))
    conn = lb.Connection(db)

    skipped_reason = []

    for jf in unprocessed:
        try:
            data = json.loads(Path(jf).read_text())
        except Exception as e:
            skipped_reason.append({"file": jf, "reason": f"parse_error: {e}"})
            continue

        entities_observed = []

        # 1. Top-level entities_observed
        top = data.get("entities_observed", [])
        if isinstance(top, list):
            entities_observed.extend(top)

        # 2. decision.entities_observed
        decision = data.get("decision", {})
        if isinstance(decision, dict):
            de = decision.get("entities_observed", [])
            if isinstance(de, list):
                entities_observed.extend(de)
            # 3. decision.payload.entities_observed
            dp = decision.get("payload", {})
            if isinstance(dp, dict):
                dpe = dp.get("entities_observed", [])
                if isinstance(dpe, list):
                    entities_observed.extend(dpe)

        # 4. payload.entities_observed
        payload = data.get("payload", {})
        if isinstance(payload, dict):
            pe = payload.get("entities_observed", [])
            if isinstance(pe, list):
                entities_observed.extend(pe)

        # 5. Weave enrichment enriched[] field
        enriched = data.get("enriched", [])
        if isinstance(enriched, list):
            for contact in enriched:
                if isinstance(contact, dict) and contact.get("name"):
                    entities_observed.append({
                        "name": contact["name"],
                        "type": "Person",
                        "user_relevance": "user",
                        "confidence": str(contact.get("confidence", 0.8))
                    })

        if not entities_observed:
            skipped_reason.append({"file": jf, "reason": "no_entities"})
            continue

        skill = data.get("skill", data.get("skill_id", "unknown"))
        sig_prefix = f"sig_{ts_short.replace(':','').replace('-','')}_{Path(jf).stem[:16]}"

        for i, entity in enumerate(entities_observed):
            if isinstance(entity, (int, float)):
                continue  # skip counts

            if isinstance(entity, str):
                name = entity
                etype = "Entity"
                ur = "unknown"
                conf = "low"
            else:
                name = ""
                for fn in ["name", "description", "entity"]:
                    v = entity.get(fn, "")
                    if v and str(v).strip():
                        name = str(v)
                        if fn == "entity" and "/" in name:
                            name = name.split("/")[-1]
                        break
                if not name:
                    continue
                etype = entity.get("type", entity.get("entity_type", "Entity"))
                ur = entity.get("user_relevance", "unknown")
                conf = entity.get("confidence", "low")
                if isinstance(conf, (int, float)):
                    conf = str(conf)

            if "/" in etype:
                etype_clean = etype.split("/")[0]
            else:
                etype_clean = etype
            if etype_clean not in ("Entity", "Place", "Concept", "Thing"):
                etype_clean = "Entity"

            sig_id = f"{sig_prefix}_{i}"
            payload_str = json.dumps({"name": name, "type": etype, "confidence": conf, "source_file": jf})
            cmd = data.get("command", "unknown")

            try:
                conn.execute(f"""
                    MERGE (s:Signal {{id: '{esc(sig_id)}'}})
                    SET s.source_skill = '{esc(skill)}',
                        s.source_type = 'journal',
                        s.source_journal_type = '{esc(cmd)}',
                        s.payload = '{esc(payload_str)}',
                        s.user_relevance = '{esc(ur)}',
                        s.timestamp = '{esc(ts_now)}',
                        s.status = 'active'
                """)
                signals_created += 1
            except Exception as e:
                print(f"ERROR creating signal {sig_id}: {e}")
                continue

            cand_id = f"cand_{sig_id}"
            pdata_str = json.dumps({"name": name, "type": etype})
            try:
                conn.execute(f"""
                    MERGE (c:Candidate {{id: '{esc(cand_id)}'}})
                    SET c.proposed_type = '{esc(etype_clean)}',
                        c.proposed_data = '{esc(pdata_str)}',
                        c.supporting_signals = '[{esc(sig_id)}]',
                        c.confidence = '{esc(conf)}',
                        c.user_relevance = '{esc(ur)}',
                        c.status = 'pending',
                        c.created_at = '{esc(ts_now)}',
                        c.resolved_at = '',
                        c.resolved_reason = ''
                """)
                candidates_created += 1
            except Exception as e:
                print(f"ERROR creating candidate {cand_id}: {e}")
                continue

            try:
                conn.execute(f"""
                    MATCH (s:Signal {{id: '{esc(sig_id)}'}})
                    MATCH (c:Candidate {{id: '{esc(cand_id)}'}})
                    CREATE (s)-[:Supports]->(c)
                """)
            except Exception as e:
                print(f"ERROR creating Supports edge: {e}")

        log_entry = {
            "file": jf,
            "skill": skill,
            "command": cmd,
            "signals_created": len(entities_observed),
            "candidates_created": len(entities_observed),
            "reason": "success",
            "ingested_at": ts_now
        }
        ing_lines = INGESTION_LOG.read_text().strip().split('\n') if INGESTION_LOG.exists() else []
        ing_lines.append(json.dumps(log_entry))
        INGESTION_LOG.write_text('\n'.join(ing_lines) + '\n')

    # skip-count summary
    skip_counts = {}
    for s in skipped_reason:
        r = s.get("reason", "unknown")
        skip_counts[r] = skip_counts.get(r, 0) + 1
    
    # Also log skipped files
    for s in skipped_reason:
        log_entry = {
            "file": s["file"],
            "skill": "unknown",
            "command": "unknown",
            "signals_created": 0,
            "candidates_created": 0,
            "reason": s["reason"],
            "ingested_at": ts_now
        }
        ing_lines = INGESTION_LOG.read_text().strip().split('\n') if INGESTION_LOG.exists() else []
        ing_lines.append(json.dumps(log_entry))
        INGESTION_LOG.write_text('\n'.join(ing_lines) + '\n')

    conn.close()
    db.close()

    print(f"Ingestion: {signals_created} signals, {candidates_created} candidates")
    print(f"Skipped: {skip_counts}")

# === Phase 3: Consolidation ===
print("\n--- Consolidation Phase ---")
db = lb.Database(str(DB_PATH))
conn = lb.Connection(db)

# Get pending user-relevant candidates
r = conn.execute("""
    MATCH (c:Candidate {status: 'pending', user_relevance: 'user'})
    RETURN c.id, c.proposed_data, c.confidence, c.created_at
""")
promotable = []
for row in r:
    promotable.append({"id": row[0], "data": row[1], "confidence": row[2], "created_at": row[3]})

print(f"Pending user-relevant candidates: {len(promotable)}")

def is_promotable(conf_str):
    if conf_str in ("high",):
        return True
    if conf_str in ("medium", "med"):
        return True
    try:
        return float(conf_str) >= 0.6
    except (ValueError, TypeError):
        return False

promoted = 0
for cand in promotable:
    conf = cand["confidence"]
    if not is_promotable(conf):
        print(f"  SKIP (low conf): {cand['id'][:40]}... conf={conf}")
        continue

    try:
        pdata = json.loads(cand["data"])
    except (json.JSONDecodeError, TypeError):
        pdata = {"name": str(cand["data"])}

    name = pdata.get("name", "unknown")
    if not name:
        name = "unknown"

    proposed_type_str = pdata.get("type", "Entity")
    if "/" in proposed_type_str:
        label = proposed_type_str.split("/")[0]
        subtype = proposed_type_str.split("/")[-1]
    else:
        label = proposed_type_str
        subtype = proposed_type_str

    if label not in ("Entity", "Place", "Concept", "Thing"):
        label = "Entity"
    if not subtype:
        subtype = "Unknown"

    cand_id = cand["id"]
    escaped_name = name.replace("'", "''")

    # Check if entity already exists (exact match)
    existing = None
    try:
        r2 = conn.execute(f"MATCH (e:{label}) WHERE e.name = '{escaped_name}' RETURN e.id LIMIT 1")
        rows = [row for row in r2]
        if rows:
            existing = rows[0][0]
    except Exception as e:
        print(f"  ERROR checking existing entity for '{name}': {e}")

    if existing:
        try:
            res_at = datetime.now(timezone.utc).isoformat()
            conn.execute(f"""
                MATCH (c:Candidate {{id: '{esc(cand_id)}'}})
                SET c.status = 'promoted', c.resolved_at = '{esc(res_at)}',
                    c.resolved_reason = 'duplicate_of_existing'
            """)
            conn.execute(f"""
                MATCH (c:Candidate {{id: '{esc(cand_id)}'}})
                MATCH (e:{label} {{id: '{esc(existing)}'}})
                CREATE (c)-[:Promotes]->(e)
            """)
            promoted += 1
            print(f"  Duplicate: '{name}' -> existing {existing[:30]}")
        except Exception as e:
            print(f"  ERROR promoting duplicate '{name}': {e}")
    else:
        ent_id = f"ent_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{name[:20].lower().replace(' ','_')}"
        res_at = datetime.now(timezone.utc).isoformat()
        try:
            if label == "Entity":
                conn.execute(f"""
                    MERGE (e:Entity {{id: '{esc(ent_id)}'}})
                    SET e.name = '{escaped_name}',
                        e.entity_type = '{esc(subtype)}',
                        e.aliases = '[]',
                        e.identifiers = '{{}}',
                        e.possible_matches = '[]',
                        e.merge_history = '[]',
                        e.identity_state = 'distinct',
                        e.source_skill = 'elephas-cron',
                        e.record_time = '{esc(res_at)}'
                """)
            elif label == "Place":
                conn.execute(f"""
                    MERGE (e:Place {{id: '{esc(ent_id)}'}})
                    SET e.name = '{escaped_name}',
                        e.place_type = '{esc(subtype)}',
                        e.coordinates = '',
                        e.address = '',
                        e.source_skill = 'elephas-cron',
                        e.record_time = '{esc(res_at)}'
                """)
            elif label == "Concept":
                conn.execute(f"""
                    MERGE (e:Concept {{id: '{esc(ent_id)}'}})
                    SET e.name = '{escaped_name}',
                        e.description = '',
                        e.concept_type = '{esc(subtype)}',
                        e.event_time = '',
                        e.source_skill = 'elephas-cron',
                        e.record_time = '{esc(res_at)}'
                """)
            elif label == "Thing":
                conn.execute(f"""
                    MERGE (e:Thing {{id: '{esc(ent_id)}'}})
                    SET e.name = '{escaped_name}',
                        e.thing_type = '{esc(subtype)}',
                        e.metadata = '{{}}',
                        e.source_skill = 'elephas-cron',
                        e.record_time = '{esc(res_at)}'
                """)

            conn.execute(f"""
                MATCH (c:Candidate {{id: '{esc(cand_id)}'}})
                SET c.status = 'promoted', c.resolved_at = '{esc(res_at)}',
                    c.resolved_reason = 'ingest_consolidate'
            """)
            conn.execute(f"""
                MATCH (c:Candidate {{id: '{esc(cand_id)}'}})
                MATCH (e:{label} {{id: '{esc(ent_id)}'}})
                CREATE (c)-[:Promotes]->(e)
            """)
            promoted += 1
            print(f"  Promoted: '{name}' ({label}:{subtype})")
        except Exception as e:
            print(f"  ERROR promoting '{name}': {e}")

print(f"\nPromoted this run: {promoted}")

# Verify state
r = conn.execute("MATCH (c:Candidate {status: 'pending', user_relevance: 'user'}) RETURN count(c)")
remaining = [row for row in r][0][0]

r = conn.execute("MATCH (c:Candidate {status: 'pending', user_relevance: 'agent_only'}) RETURN count(c)")
agent_only = [row for row in r][0][0]

r = conn.execute("MATCH (e:Entity) RETURN count(e)")
entities = [row for row in r][0][0]

r = conn.execute("MATCH (c:Candidate {status: 'promoted'}) RETURN count(c)")
promoted_total = [row for row in r][0][0]

r = conn.execute("""
    MATCH (s:Signal {status: 'active'})
    WHERE NOT EXISTS { MATCH (s)-[:Supports]->() }
    RETURN count(s)
""")
orphans = [row for row in r][0][0]

r = conn.execute("MATCH (s:Signal {status: 'active'}) RETURN count(s)")
active_signals = [row for row in r][0][0]

r = conn.execute("MATCH (c:Candidate {status: 'pending'}) RETURN count(c)")
pending_total = [row for row in r][0][0]

print(f"Active signals: {active_signals}")
print(f"Total entities: {entities}")
print(f"Total promoted candidates: {promoted_total}")
print(f"Pending candidates (user): {remaining}")
print(f"Pending candidates (agent_only): {agent_only}")
print(f"Pending candidates (total): {pending_total}")
print(f"Orphan signals: {orphans}")

conn.close()
db.close()

# Write decision record
decisions_file = DB_DIR / "decisions.jsonl"
decision = {
    "type": "cron_ingest_consolidate",
    "timestamp": ts_now,
    "files_scanned": len(unprocessed),
    "signals_created": signals_created,
    "candidates_created": candidates_created,
    "promoted": promoted,
    "state": {
        "active_signals": active_signals,
        "entities": entities,
        "promoted_candidates": promoted_total,
        "pending_user": remaining,
        "pending_agent_only": agent_only,
        "pending_total": pending_total,
        "orphan_signals": orphans
    },
    "summary": f"Scanned {len(unprocessed)} files, {signals_created} signals, {candidates_created} candidates, {promoted} promoted"
}
if decisions_file.exists():
    lines = decisions_file.read_text().strip().split('\n')
else:
    lines = []
lines.append(json.dumps(decision))
decisions_file.write_text('\n'.join(lines) + '\n')
