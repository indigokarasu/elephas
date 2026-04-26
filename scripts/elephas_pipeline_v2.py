#!/usr/bin/env python3
"""Elephas ingest + consolidate pipeline v2.
Cleans stale log entries, ingests new journal files, runs immediate consolidation.
"""
import json, os, re, hashlib, uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# === PATHS ===
DB_DIR = Path("/root/.hermes/commons/db/ocas-elephas")
JOURNALS_ROOT = Path("/root/.hermes/commons/journals")
INGESTION_LOG = DB_DIR / "ingestion_log.jsonl"
STAGING_DIR = DB_DIR / "staging"
STAGING_DIR.mkdir(exist_ok=True)

# === HELPERS ===
def _ts():
    return datetime.now(timezone.utc).isoformat()

def _gen_id(prefix="sig"):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def _esc(s):
    """Escape single quotes for Cypher string interpolation."""
    if not s:
        return ""
    return str(s).replace("\\", "\\\\").replace("'", "\\'")

def _extract_name(e):
    if isinstance(e, str): return e
    if isinstance(e, (int, float)): return str(e)
    if not isinstance(e, dict): return str(e)
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
    if not isinstance(e, dict): return "Entity"
    for field in ["type", "entity_type"]:
        val = e.get(field, "")
        if val:
            sval = str(val)
            if "/" in sval:
                return sval
            return f"Entity/{sval}" if sval not in ("Entity", "Place", "Concept", "Thing") else sval
    return "Entity"

def _get_ur(e):
    if isinstance(e, str): return "unknown"
    if isinstance(e, (int, float)): return "unknown"
    if not isinstance(e, dict): return "unknown"
    return e.get("user_relevance", "unknown")

def _get_confidence(e):
    if isinstance(e, str): return "low"
    if isinstance(e, (int, float)): return "low"
    if not isinstance(e, dict): return "low"
    return e.get("confidence", "low")

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

def is_promotable(conf_str):
    if conf_str in ("high",): return True
    if conf_str in ("medium", "med"): return True
    try:
        return float(conf_str) >= 0.6
    except:
        return False

def load_processed():
    """Load all processed file paths from ingestion log, checking all key variants."""
    processed = set()
    if not INGESTION_LOG.exists():
        return processed
    lines = INGESTION_LOG.read_text().strip().split('\n')
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            f = (entry.get("file") or entry.get("journal_file") or 
                 entry.get("journal_path") or entry.get("file_path") or 
                 entry.get("source_file") or "")
            if f:
                processed.add(f)
        except:
            continue
    return processed

def clean_stale_entries():
    """Remove ingestion log entries with signals_created=0 older than 15 min."""
    if not INGESTION_LOG.exists():
        return 0
    lines = INGESTION_LOG.read_text().strip().split('\n')
    now = datetime.now(timezone.utc)
    kept = []
    removed = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except:
            kept.append(line)
            continue
        if entry.get("signals_created", 0) == 0:
            ingested_at = entry.get("ingested_at", "")
            if "T" in ingested_at:
                try:
                    t = datetime.fromisoformat(ingested_at.replace('Z', '+00:00'))
                    age_min = (now - t).total_seconds() / 60
                    if age_min > 15:
                        removed += 1
                        continue
                except:
                    pass
        kept.append(line)
    INGESTION_LOG.write_text('\n'.join(kept) + '\n')
    return removed

def find_unprocessed(processed):
    """Find journal JSON files not yet in the ingestion log."""
    results = []
    if not JOURNALS_ROOT.exists():
        return results
    for skill_dir in sorted(JOURNALS_ROOT.iterdir()):
        if not skill_dir.is_dir():
            continue
        # Skip elephas' own journals
        if skill_dir.name == "ocas-elephas":
            continue
        for date_dir in sorted(skill_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            for f in sorted(date_dir.glob("*.json")):
                abs_path = str(f)
                rel_path = str(f.relative_to(JOURNALS_ROOT))
                if abs_path not in processed and rel_path not in processed:
                    results.append(abs_path)
    return results

# === MAIN ===
print(f"[{_ts()}] Elephas pipeline v2 starting...")

# Step 1: Clean stale entries
removed = clean_stale_entries()
print(f"Cleaned {removed} stale ingestion log entries")

# Step 2: Load processed files
processed = load_processed()
print(f"Processed paths in log: {len(processed)}")

# Step 3: Find unprocessed files
unprocessed = find_unprocessed(processed)
print(f"Unprocessed journal files: {len(unprocessed)}")

if not unprocessed:
    print("No new journal files to ingest. Skipping to consolidation.")
else:
    # Step 4: Open database
    import real_ladybug as lb
    db = lb.Database(str(DB_DIR / "chronicle.lbug"))
    conn = lb.Connection(db)

    # Step 5: Ingest each file
    signals_created = 0
    candidates_created = 0
    log_entries = []

    for filepath in unprocessed:
        fpath = Path(filepath)
        try:
            content = fpath.read_text()
            data = json.loads(content)
        except Exception as e:
            print(f"  SKIP {fpath.name}: {e}")
            continue

        # Extract entities from multiple locations
        entities = []
        
        # Top-level entities_observed
        top_eo = data.get("entities_observed", [])
        if isinstance(top_eo, list):
            entities.extend(top_eo)
        
        # Nested in decision.payload
        decision = data.get("decision", {})
        if isinstance(decision, dict):
            payload = decision.get("payload", {})
            if isinstance(payload, dict):
                nested_eo = payload.get("entities_observed", [])
                if isinstance(nested_eo, list):
                    entities.extend(nested_eo)

        if not entities:
            # Log as processed with 0 signals
            rel_path = str(fpath.relative_to(JOURNALS_ROOT))
            log_entries.append(json.dumps({
                "file": rel_path,
                "signals_created": 0,
                "candidates_created": 0,
                "ingested_at": _ts()
            }))
            continue

        # Determine source skill from path
        parts = fpath.parts
        source_skill = "unknown"
        for i, p in enumerate(parts):
            if p == "journals" and i + 1 < len(parts):
                source_skill = parts[i + 1]
                break

        file_signals = 0
        file_candidates = 0

        for entity in entities:
            name = _extract_name(entity)
            if not name or name == "0":
                continue

            etype = _extract_type(entity)
            ur = _get_ur(entity)
            confidence = _get_confidence(entity)

            # Create Signal
            sig_id = _gen_id("sig")
            payload_str = json.dumps(entity) if isinstance(entity, dict) else str(entity)

            try:
                conn.execute(f"""
                    CREATE (s:Signal {{
                        id: '{_esc(sig_id)}',
                        source_skill: '{_esc(source_skill)}',
                        source_type: 'journal',
                        source_journal_type: 'observation',
                        payload: '{_esc(payload_str)}',
                        user_relevance: '{_esc(ur)}',
                        timestamp: '{_ts()}',
                        status: 'active'
                    }})
                """)
                file_signals += 1
            except Exception as e:
                print(f"    Signal error for {name}: {e}")
                continue

            # Check for existing candidate with same name
            try:
                r = conn.execute(f"MATCH (c:Candidate) WHERE c.proposed_data CONTAINS '{_esc(name)}' AND c.status = 'pending' RETURN c.id LIMIT 1")
                existing = [row for row in r]
            except:
                existing = []

            if existing:
                # Link signal to existing candidate
                try:
                    conn.execute(f"""
                        MATCH (s:Signal {{id: '{_esc(sig_id)}'}})
                        MATCH (c:Candidate {{id: '{_esc(existing[0][0])}'}})
                        CREATE (s)-[:Supports]->(c)
                    """)
                except Exception as e:
                    print(f"    Link error: {e}")
            else:
                # Create new candidate
                cand_id = _gen_id("cand")
                proposed_data = json.dumps({"name": name, "type": etype, "user_relevance": ur, "confidence": confidence})

                try:
                    conn.execute(f"""
                        CREATE (c:Candidate {{
                            id: '{_esc(cand_id)}',
                            proposed_type: '{_esc(etype)}',
                            proposed_data: '{_esc(proposed_data)}',
                            supporting_signals: '["{sig_id}"]',
                            confidence: '{_esc(confidence)}',
                            user_relevance: '{_esc(ur)}',
                            status: 'pending',
                            created_at: '{_ts()}',
                            resolved_at: '',
                            resolved_reason: ''
                        }})
                    """)
                    file_candidates += 1

                    # Create Supports edge
                    conn.execute(f"""
                        MATCH (s:Signal {{id: '{_esc(sig_id)}'}})
                        MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
                        CREATE (s)-[:Supports]->(c)
                    """)
                except Exception as e:
                    print(f"    Candidate error for {name}: {e}")

        signals_created += file_signals
        candidates_created += file_candidates

        # Log this file
        rel_path = str(fpath.relative_to(JOURNALS_ROOT))
        log_entries.append(json.dumps({
            "file": rel_path,
            "signals_created": file_signals,
            "candidates_created": file_candidates,
            "ingested_at": _ts()
        }))

    # Write ingestion log entries
    if log_entries:
        with open(INGESTION_LOG, 'a') as f:
            for entry in log_entries:
                f.write(entry + '\n')

    print(f"\nIngestion complete:")
    print(f"  Files processed: {len(unprocessed)}")
    print(f"  Signals created: {signals_created}")
    print(f"  Candidates created: {candidates_created}")

# Step 6: Consolidation - promote high-confidence user-relevant candidates
print(f"\n--- Consolidation ---")
import real_ladybug as lb
db = lb.Database(str(DB_DIR / "chronicle.lbug"))
conn = lb.Connection(db)

type_property_map = {
    "Entity": "entity_type",
    "Place": "place_type",
    "Concept": "concept_type",
    "Thing": "thing_type"
}

# Get pending user-relevant candidates
try:
    r = conn.execute("MATCH (c:Candidate {status: 'pending', user_relevance: 'user'}) RETURN c.id, c.proposed_type, c.proposed_data, c.confidence")
    pending = [row for row in r]
except Exception as e:
    print(f"Query error: {e}")
    pending = []

print(f"Pending user-relevant candidates: {len(pending)}")

promoted = 0
for row in pending:
    cand_id, proposed_type, proposed_data_str, confidence = row[0], row[1], row[2], row[3]

    if not is_promotable(confidence):
        continue

    # Parse proposed data
    try:
        pdata = json.loads(proposed_data_str)
    except:
        try:
            pdata = parse_repr_payload(proposed_data_str)
        except:
            continue

    name = pdata.get("name", "")
    if not name:
        continue

    # Determine node type
    if "/" in proposed_type:
        node_type = proposed_type.split("/")[0]
        subtype = proposed_type.split("/")[-1]
    else:
        node_type = proposed_type
        subtype = pdata.get("type", "Unknown")

    if node_type not in ("Entity", "Place", "Concept", "Thing"):
        node_type = "Entity"

    type_prop = type_property_map.get(node_type, "entity_type")
    ent_id = _gen_id(node_type[:3].lower())
    ts = _ts()

    # Create node with type-specific properties
    try:
        if node_type == "Entity":
            conn.execute(f"""CREATE (e:Entity {{
                id: '{_esc(ent_id)}', name: '{_esc(name)}', entity_type: '{_esc(subtype)}',
                aliases: '[]', identifiers: '{{}}', possible_matches: '[]', merge_history: '[]',
                identity_state: 'distinct', source_skill: 'elephas-consolidate', record_time: '{ts}'
            }})""")
        elif node_type == "Place":
            conn.execute(f"""CREATE (e:Place {{
                id: '{_esc(ent_id)}', name: '{_esc(name)}', place_type: '{_esc(subtype)}',
                coordinates: '', address: '', source_skill: 'elephas-consolidate', record_time: '{ts}'
            }})""")
        elif node_type == "Concept":
            conn.execute(f"""CREATE (e:Concept {{
                id: '{_esc(ent_id)}', name: '{_esc(name)}', description: '', concept_type: '{_esc(subtype)}',
                event_time: '', source_skill: 'elephas-consolidate', record_time: '{ts}'
            }})""")
        elif node_type == "Thing":
            conn.execute(f"""CREATE (e:Thing {{
                id: '{_esc(ent_id)}', name: '{_esc(name)}', thing_type: '{_esc(subtype)}',
                metadata: '{{}}', source_skill: 'elephas-consolidate', record_time: '{ts}'
            }})""")
    except Exception as e:
        print(f"  Node create error for {name}: {e}")
        continue

    # Mark candidate as promoted
    try:
        conn.execute(f"""MATCH (c:Candidate {{id: '{_esc(cand_id)}'}}) SET c.status = 'promoted', c.resolved_at = '{ts}'""")
    except Exception as e:
        print(f"  Candidate update error: {e}")

    # Create Promotes edge
    try:
        conn.execute(f"""
            MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
            MATCH (e:{node_type} {{id: '{_esc(ent_id)}'}})
            CREATE (c)-[:Promotes]->(e)
        """)
    except Exception as e:
        print(f"  Promotes edge error for {name}: {e}")

    promoted += 1

print(f"Promoted: {promoted}")

# Summary stats
try:
    r = conn.execute("MATCH (e:Entity) RETURN count(e)")
    entity_count = [row for row in r][0][0]
    r = conn.execute("MATCH (p:Place) RETURN count(p)")
    place_count = [row for row in r][0][0]
    r = conn.execute("MATCH (c:Concept) RETURN count(c)")
    concept_count = [row for row in r][0][0]
    r = conn.execute("MATCH (t:Thing) RETURN count(t)")
    thing_count = [row for row in r][0][0]
    r = conn.execute("MATCH (c:Candidate {status: 'pending'}) RETURN count(c)")
    pending_remaining = [row for row in r][0][0]
    r = conn.execute("MATCH ()-[rel]->() RETURN count(rel)")
    rel_count = [row for row in r][0][0]
    
    print(f"\n--- Chronicle Status ---")
    print(f"Entities: {entity_count}")
    print(f"Places: {place_count}")
    print(f"Concepts: {concept_count}")
    print(f"Things: {thing_count}")
    print(f"Relationships: {rel_count}")
    print(f"Pending candidates: {pending_remaining}")
except Exception as e:
    print(f"Status query error: {e}")

print(f"\n[{_ts()}] Pipeline complete.")
