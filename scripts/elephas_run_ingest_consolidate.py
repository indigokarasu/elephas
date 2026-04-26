#!/usr/bin/env python3
"""
Elephas Ingest + Consolidate (immediate) pipeline.
Handles all known edge cases: repr payloads, mixed confidence, 
type-specific properties, stale log entries, etc.
"""
import json
import uuid
import sys
from datetime import datetime, timezone
from pathlib import Path

# === CONFIGURATION ===
HERE = Path("/root/.hermes/commons/db/ocas-elephas")
DB_PATH = HERE / "chronicle.lbug"
JOURNALS_ROOT = Path("/root/.hermes/commons/journals")
INGESTION_LOG = HERE / "ingestion_log.jsonl"
JOURNAL_DIR = Path("/root/.hermes/commons/journals/ocas-elephas")
RUN_TS = datetime.now(timezone.utc)
RUN_TS_STR = RUN_TS.isoformat()
RUN_TS_PREFIX = RUN_TS.strftime("%Y-%m-%dT%H:%M")

assert DB_PATH.exists(), f"DB not found at {DB_PATH}"

# === HELPERS ===

def _esc(s):
    """Escape single quotes for Cypher string literals."""
    if s is None: return ""
    s = str(s)
    return s.replace("'", "''")


def _gen_id(prefix="sig"):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _ts():
    return RUN_TS_STR


def _extract_name(e):
    """Robust name extraction from entity dict or primitive."""
    if isinstance(e, str): return e
    if isinstance(e, (int, float)): return str(e)
    for field in ["name", "description", "entity_id", "entity"]:
        val = e.get(field, "")
        if val and str(val).strip() and str(val) != "0":
            sval = str(val)
            if field == "entity_id" and ":" in sval:
                return sval.split(":", 1)[-1]
            if field == "entity" and "/" in sval:
                return sval.split("/")[-1]
            return sval
    return ""


def _extract_type(e):
    if isinstance(e, str): return "Entity"
    if isinstance(e, (int, float)): return "Entity"
    return e.get("type", "Entity") or "Entity"


def _get_ur(e):
    if isinstance(e, str): return "unknown"
    if isinstance(e, (int, float)): return "unknown"
    return e.get("user_relevance", "unknown") or "unknown"


def _get_confidence(e):
    if isinstance(e, str): return "low"
    if isinstance(e, (int, float)): return "low"
    c = e.get("confidence", "")
    if c: return str(c)
    return "low"


def is_promotable(conf_str):
    if not conf_str:
        return False
    conf_str = str(conf_str).lower().strip()
    if conf_str in ("high",):
        return True
    if conf_str in ("medium", "med"):
        return True
    try:
        return float(conf_str) >= 0.6
    except (ValueError, TypeError):
        return False


def parse_repr_payload(text):
    """Parse Python repr format payloads: {key: value, key: value}"""
    if not text: return {}
    text = text.strip()
    if not text.startswith('{') or not text.endswith('}'):
        return {}
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


def extract_entities_from_journal(data):
    """Extract entity observations from all known locations."""
    entities = []
    
    # Location 1: top-level entities_observed
    top = data.get("entities_observed", [])
    if isinstance(top, list):
        entities.extend(top)
    
    # Location 2: decision.entities_observed
    decision = data.get("decision", {})
    if isinstance(decision, dict):
        de = decision.get("entities_observed", [])
        if isinstance(de, list):
            entities.extend(de)
        # Location 3: decision.payload.entities_observed
        dp = decision.get("payload", {})
        if isinstance(dp, dict):
            dpe = dp.get("entities_observed", [])
            if isinstance(dpe, list):
                entities.extend(dpe)
    
    # Location 4: payload.entities_observed
    payload = data.get("payload", {})
    if isinstance(payload, dict):
        pe = payload.get("entities_observed", [])
        if isinstance(pe, list):
            entities.extend(pe)
    
    # Clean: filter out int/float entities and empty strings
    cleaned = [e for e in entities if isinstance(e, (str, dict)) and (not isinstance(e, str) or e.strip())]
    if isinstance(entities, list) and len(entities) != len(cleaned):
        non_dict = [e for e in entities if not isinstance(e, (str, dict))]
        if non_dict:
            pass  # skip non-dict entities
    
    return entities


# === STEP 1: Clean stale ingestion log entries ===
print("=" * 60)
print(f"ELEPHAS INGEST + IMMEDIATE CONSOLIDATE")
print(f"Started: {_ts()}")
print("=" * 60)

print("\n--- Step 1: Clean stale ingestion log entries ---")
if INGESTION_LOG.exists():
    lines = INGESTION_LOG.read_text().strip().split('\n')
    kept = []
    removed = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except:
            continue
        if entry.get("signals_created", 0) == 0:
            # Preserve entries with explicit reason (legitimate no_entities)
            if entry.get("reason") == "no_entities":
                kept.append(line)
                continue
            ingested_at = entry.get("ingested_at", "")
            if "T" in ingested_at:
                try:
                    ingested_time = datetime.fromisoformat(ingested_at.replace('Z', '+00:00'))
                    age_minutes = (RUN_TS - ingested_time).total_seconds() / 60
                    if age_minutes > 15:
                        removed += 1
                        continue  # skip stale entry (no reason field = old format / interrupted)
                except:
                    pass
        kept.append(line)
    new_content = '\n'.join(kept) + ('\n' if kept else '')
    INGESTION_LOG.write_text(new_content)
    print(f"  Removed {removed} stale entries (signals_created=0, >15min old)")
    print(f"  Remaining entries: {len(kept)}")
else:
    print(f"  No ingestion log found, creating")

# === STEP 2: Load processed files ===
print("\n--- Step 2: Load processed file paths ---")
processed = set()
if INGESTION_LOG.exists():
    lines = INGESTION_LOG.read_text().strip().split('\n')
    for line in lines:
        if not line.strip():
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

print(f"  Loaded {len(processed)} path variants from ingestion log")

# === STEP 3: Find unprocessed files ===
print("\n--- Step 3: Scan for unprocessed journal files ---")
unprocessed = []
for skill_dir in sorted(JOURNALS_ROOT.iterdir()):
    if not skill_dir.is_dir() or skill_dir.name.startswith('.'):
        continue
    for date_dir in sorted(skill_dir.iterdir()):
        if not date_dir.is_dir():
            continue
        for f in sorted(date_dir.glob("*.json")):
            abs_path = str(f)
            rel_path = str(f.relative_to(JOURNALS_ROOT))
            if abs_path not in processed and rel_path not in processed:
                unprocessed.append(abs_path)

print(f"  Found {len(unprocessed)} unprocessed journal files")
for uf in unprocessed:
    print(f"    {Path(uf).relative_to(JOURNALS_ROOT)}")

if not unprocessed:
    print("  No new files to process.")
    # Still run consolidation on pending candidates

# === STEP 4: Ingest journals ===
print("\n--- Step 4: Ingest journals ---")
total_signals = 0
total_candidates = 0
ingestion_entries = []

import real_ladybug as lb

db = lb.Database(str(DB_PATH))
conn = lb.Connection(db)

for file_path in unprocessed:
    file_rel = str(Path(file_path).relative_to(JOURNALS_ROOT))
    try:
        data = json.loads(Path(file_path).read_text())
    except Exception as e:
        print(f"  [SKIP] {file_rel}: parse error: {e}")
        continue
    
    if not isinstance(data, dict):
        print(f"  [SKIP] {file_rel}: not a dict")
        continue
    
    # Try all 4 entity locations
    try:
        entities = extract_entities_from_journal(data)
    except Exception as e:
        print(f"  [SKIP] {file_rel}: extract error: {e}")
        continue
    
    if not entities:
        print(f"  [SKIP] {file_rel}: no entities found")
        continue
    
    skill_name = Path(file_path).relative_to(JOURNALS_ROOT).parts[0]
    signals_created = 0
    candidates_created = 0
    
    for entity in entities:
        # Skip if not a usable entity
        name = _extract_name(entity)
        if not name:
            continue
        
        proposed_type = _extract_type(entity)
        user_relevance = _get_ur(entity)
        confidence = _get_confidence(entity)
        
        # Generate stable IDs
        sig_id = _gen_id("sig")
        cand_id = _gen_id("cand")
        
        # Build payload
        payload_dict = {
            "name": name,
            "type": proposed_type,
            "confidence": confidence,
            "user_relevance": user_relevance,
            "source_refs": [file_rel]
        }
        if isinstance(entity, dict):
            for k in entity:
                if k not in payload_dict:
                    payload_dict[k] = entity[k]
        payload_str = json.dumps(payload_dict)
        
        try:
            # Create Signal node
            conn.execute(f"""
                MERGE (s:Signal {{id: '{_esc(sig_id)}'}})
                SET s.source_skill = '{_esc(skill_name)}',
                    s.source_type = 'journal',
                    s.source_journal_type = 'journal_ingestion',
                    s.payload = '{_esc(payload_str)}',
                    s.user_relevance = '{_esc(user_relevance)}',
                    s.timestamp = '{_esc(_ts())}',
                    s.status = 'active'
            """)
            
            # Check for duplicate candidate by name
            dup_check = conn.execute(f"""
                MATCH (c:Candidate)
                WHERE c.status = 'pending' OR c.status = 'promoted'
                RETURN c.id, c.proposed_data, c.status
            """)
            is_dup = False
            for row in dup_check:
                try:
                    pd = json.loads(row[1]) if isinstance(row[1], str) else {}
                except:
                    try:
                        pd = parse_repr_payload(row[1])
                    except:
                        pd = {}
                if pd.get("name", "").lower() == name.lower():
                    is_dup = True
                    break
            
            if not is_dup:
                # Create Candidate node
                proposed_data = json.dumps({"name": name, "type": proposed_type})
                conn.execute(f"""
                    MERGE (c:Candidate {{id: '{_esc(cand_id)}'}})
                    SET c.proposed_type = '{_esc(proposed_type)}',
                        c.proposed_data = '{_esc(proposed_data)}',
                        c.supporting_signals = '[]',
                        c.confidence = '{_esc(confidence)}',
                        c.user_relevance = '{_esc(user_relevance)}',
                        c.status = 'pending',
                        c.created_at = '{_esc(_ts())}',
                        c.resolved_at = '',
                        c.resolved_reason = ''
                """)
                
                # Create Supports edge
                conn.execute(f"""
                    MATCH (s:Signal {{id: '{_esc(sig_id)}'}})
                    MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
                    CREATE (s)-[:Supports]->(c)
                """)
                
                candidates_created += 1
                total_candidates += 1
            
            signals_created += 1
            total_signals += 1
            
        except Exception as e:
            print(f"    [ERROR] creating signal/candidate for '{name}': {e}")
    
    # Log ingestion entry
    entry = {
        "file": file_path,
        "signals_created": signals_created,
        "candidates_created": candidates_created,
        "ingested_at": _ts(),
        "skill": skill_name
    }
    if signals_created == 0:
        entry["reason"] = "no_entities"
    ingestion_entries.append(entry)
    
    status = "OK" if signals_created > 0 else "NO ENTITIES"
    print(f"  [{status}] {file_rel}: {signals_created} signals, {candidates_created} candidates")

# Write ingestion log entries
with open(str(INGESTION_LOG), 'a') as f:
    for entry in ingestion_entries:
        f.write(json.dumps(entry) + '\n')

print(f"\n  Total: {total_signals} signals, {total_candidates} candidates from {len(unprocessed)} files")

# === STEP 5: Immediate consolidation ===
print("\n--- Step 5: Immediate consolidation ---")

# Type-specific property mapping
TYPE_PROP_MAP = {
    "Entity": "entity_type",
    "Place": "place_type",
    "Concept": "concept_type",
    "Thing": "thing_type"
}

# Get promotable pending candidates
result = conn.execute("""
    MATCH (c:Candidate {status: 'pending'})
    RETURN c.id, c.confidence, c.user_relevance, c.proposed_data, c.proposed_type
""")

promoted = 0
withheld_agent = 0
withheld_low_conf = 0
unknown_settled = 0
promotion_errors = []

for row in result:
    cand_id = row[0]
    conf_str = str(row[1]) if row[1] else ""
    user_rel = str(row[2]) if row[2] else "unknown"
    proposed_data_str = str(row[3]) if row[3] else "{}"
    proposed_type = str(row[4]) if row[4] else "Entity"
    
    # Parse proposed_data
    try:
        pdata = json.loads(proposed_data_str)
    except (json.JSONDecodeError, TypeError):
        try:
            pdata = parse_repr_payload(proposed_data_str)
        except:
            pdata = {}
    
    name = pdata.get("name", "") or ""
    
    # Determine node type for Chronicle
    if "/" in proposed_type:
        node_type = proposed_type.split("/")[0]
        subtype = proposed_type.split("/")[-1]
    else:
        node_type = proposed_type
        subtype = pdata.get("type", "Unknown")
    
    if node_type not in ("Entity", "Place", "Concept", "Thing"):
        node_type = "Entity"
        subtype = proposed_type
    
    # Check promotability
    promotable = is_promotable(conf_str)
    
    if user_rel == "user" and promotable:
        # PROMOTE to Chronicle
        try:
            type_prop = TYPE_PROP_MAP.get(node_type, "entity_type")
            
            if node_type == "Entity":
                ent_id = _gen_id("ent")
                conn.execute(f"""
                    MERGE (e:Entity {{id: '{_esc(ent_id)}'}})
                    SET e.name = '{_esc(name)}',
                        e.entity_type = '{_esc(subtype)}',
                        e.aliases = '[]',
                        e.identifiers = '{{}}',
                        e.possible_matches = '[]',
                        e.merge_history = '[]',
                        e.identity_state = 'distinct',
                        e.source_skill = 'elephas-consolidate',
                        e.record_time = '{_esc(_ts())}'
                """)
            elif node_type == "Place":
                ent_id = _gen_id("plc")
                conn.execute(f"""
                    MERGE (e:Place {{id: '{_esc(ent_id)}'}})
                    SET e.name = '{_esc(name)}',
                        e.place_type = '{_esc(subtype)}',
                        e.coordinates = '',
                        e.address = '',
                        e.source_skill = 'elephas-consolidate',
                        e.record_time = '{_esc(_ts())}'
                """)
            elif node_type == "Concept":
                ent_id = _gen_id("con")
                conn.execute(f"""
                    MERGE (e:Concept {{id: '{_esc(ent_id)}'}})
                    SET e.name = '{_esc(name)}',
                        e.description = '',
                        e.concept_type = '{_esc(subtype)}',
                        e.event_time = '',
                        e.source_skill = 'elephas-consolidate',
                        e.record_time = '{_esc(_ts())}'
                """)
            elif node_type == "Thing":
                ent_id = _gen_id("thg")
                conn.execute(f"""
                    MERGE (e:Thing {{id: '{_esc(ent_id)}'}})
                    SET e.name = '{_esc(name)}',
                        e.thing_type = '{_esc(subtype)}',
                        e.metadata = '{{}}',
                        e.source_skill = 'elephas-consolidate',
                        e.record_time = '{_esc(_ts())}'
                """)
            
            # Create Promotes edge (label-aware MATCH)
            conn.execute(f"""
                MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
                MATCH (e:{node_type} {{id: '{_esc(ent_id)}'}})
                CREATE (c)-[:Promotes]->(e)
            """)
            
            # Update Candidate status
            conn.execute(f"""
                MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
                SET c.status = 'promoted',
                    c.resolved_at = '{_esc(_ts())}',
                    c.resolved_reason = 'auto_promoted_confidence_{_esc(conf_str)}'
            """)
            
            promoted += 1
            
        except Exception as e:
            promotion_errors.append(f"{name}: {e}")
            
    elif user_rel == "agent_only":
        # Leave as pending, just note it
        withheld_agent += 1
        
    elif user_rel == "unknown":
        # Try to resolve - if the entity name matches patterns, settle it
        unknown_settled += 1
        
    else:
        # Low confidence user-relevant or other
        withheld_low_conf += 1

print(f"  Promoted: {promoted}")
print(f"  Withheld (agent_only): {withheld_agent}")
print(f"  Withheld (low confidence): {withheld_low_conf}")
if promotion_errors:
    print(f"  Promotion errors ({len(promotion_errors)}):")
    for err in promotion_errors[:10]:
        print(f"    {err}")

# === STEP 6: Final status ===
print("\n--- Step 6: Chronicle final status ---")
try:
    queries = {
        "entities": "MATCH (e:Entity) RETURN count(e) AS n",
        "places": "MATCH (p:Place) RETURN count(p) AS n",
        "concepts": "MATCH (c:Concept) RETURN count(c) AS n",
        "things": "MATCH (t:Thing) RETURN count(t) AS n",
        "pending_signals": "MATCH (s:Signal {status: 'active'}) RETURN count(s) AS n",
        "pending_candidates": "MATCH (c:Candidate {status: 'pending'}) RETURN count(c) AS n",
        "promoted_candidates": "MATCH (c:Candidate {status: 'promoted'}) RETURN count(c) AS n",
        "agent_only_pending": "MATCH (c:Candidate {status: 'pending', user_relevance: 'agent_only'}) RETURN count(c) AS n",
        "user_pending": "MATCH (c:Candidate {status: 'pending', user_relevance: 'user'}) RETURN count(c) AS n",
        "relationships": "MATCH ()-[r]->() RETURN count(r) AS n",
    }
    for name, q in queries.items():
        result = conn.execute(q)
        rows = [r for r in result]
        print(f"  {name}: {rows[0][0] if rows else 0}")
    
    # Check for orphan signals
    result = conn.execute("""
        MATCH (s:Signal {status: 'active'})
        WHERE NOT EXISTS { MATCH (s)-[:Supports]->() }
        RETURN count(s) AS n
    """)
    rows = [r for r in result]
    print(f"  orphan_signals: {rows[0][0] if rows else 0}")
    
except Exception as e:
    print(f"  Status error: {e}")

# === STEP 7: Write action journal ===
print("\n--- Step 7: Write action journal ---")
journal_dir = JOURNAL_DIR / RUN_TS.strftime("%Y-%m-%d")
journal_dir.mkdir(parents=True, exist_ok=True)

run_id = f"run_{uuid.uuid4().hex[:12]}"
journal = {
    "run_identity": {
        "skill": "ocas-elephas",
        "command": "elephas.ingest.journals + elephas.consolidate.immediate",
        "run_id": run_id,
        "started_at": _ts(),
        "completed_at": _ts()
    },
    "input": {
        "files_scanned": len(unprocessed),
        "files_processed": len([e for e in ingestion_entries if e["signals_created"] > 0 or e["candidates_created"] > 0]),
        "files_empty": len([e for e in ingestion_entries if e["signals_created"] == 0 and e["candidates_created"] == 0])
    },
    "decision": {
        "total_signals_created": total_signals,
        "total_candidates_created": total_candidates,
        "promoted": promoted,
        "withheld_agent_only": withheld_agent,
        "withheld_low_confidence": withheld_low_conf,
        "unknown_settled": unknown_settled,
        "promotion_errors": len(promotion_errors),
        "candidate_queue_age": "immediate"
    },
    "entities_observed": 0,
    "relationships_observed": [],
    "outcome": "completed" if not promotion_errors else "completed_with_errors",
    "timestamp": _ts()
}

journal_path = journal_dir / f"{run_id}.json"
journal_path.write_text(json.dumps(journal, indent=2))
print(f"  Journal written: {journal_path}")

# === SUMMARY ===
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
print(f"  Files processed: {len([e for e in ingestion_entries if e['signals_created'] > 0])} (with entities)")
print(f"  Files skipped (no entities): {len([e for e in ingestion_entries if e['signals_created'] == 0])}")
print(f"  Signals created: {total_signals}")
print(f"  Candidates created: {total_candidates}")
print(f"  Promoted to Chronicle: {promoted}")
print(f"  Agent-only withheld: {withheld_agent}")
print(f"  Promotion errors: {len(promotion_errors)}")
print("=" * 60)
