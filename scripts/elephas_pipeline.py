#!/usr/bin/env python3
"""
Elephas Ingestion + Immediate Consolidation Pipeline
Self-contained script for cron execution.
"""
import json
import os
import re
import sys
import uuid
import hashlib
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path("/root/.hermes/commons/db/ocas-elephas/chronicle.lbug")
CONFIG_PATH = Path("/root/.hermes/commons/db/ocas-elephas/config.json")
INGESTION_LOG = Path("/root/.hermes/commons/db/ocas-elephas/ingestion_log.jsonl")
JOURNALS_ROOT = Path("/root/.hermes/commons/journals")
DECISIONS_LOG = Path("/root/.hermes/commons/db/ocas-elephas/decisions.jsonl")

# ── Helpers ──────────────────────────────────────────────────────────────

def _ts():
    return datetime.now(timezone.utc).isoformat()

def _esc(s):
    if not s:
        return ""
    s = str(s)
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "")

def _gen_id(prefix="sig"):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def parse_repr_payload(text):
    """Parse Python repr format: {key: value, key: value}"""
    if not text:
        return {}
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
            depth += 1; val += c
        elif c == '}':
            depth -= 1; val += c
        elif c == ':' and depth == 0 and in_key:
            in_key = False
        elif c == ',' and depth == 0 and not in_key:
            pairs.append((key.strip(), val.strip()))
            key = ""; val = ""; in_key = True
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

def safe_json_loads(text):
    """Try json.loads, then repr parser."""
    if not text:
        return {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return parse_repr_payload(str(text))

def _extract_name(e):
    if isinstance(e, str):
        return e
    if isinstance(e, (int, float)):
        return str(e)
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
    if isinstance(e, str):
        return "Entity"
    if isinstance(e, (int, float)):
        return "Entity"
    for field in ["type", "entity_type", "entity"]:
        val = e.get(field, "")
        if val and str(val).strip():
            sval = str(val)
            if "/" in sval:
                return sval
            return sval
    return "Entity"

def _get_user_relevance(e):
    if isinstance(e, str):
        return "unknown"
    if isinstance(e, (int, float)):
        return "unknown"
    return e.get("user_relevance", "unknown")

def _get_confidence(e):
    if isinstance(e, str):
        return "low"
    if isinstance(e, (int, float)):
        return "low"
    conf = e.get("confidence", "")
    if conf:
        return str(conf).lower()
    return "low"

def is_promotable(conf_str):
    if conf_str in ("high",):
        return True
    if conf_str in ("medium", "med"):
        return True
    try:
        return float(conf_str) >= 0.6
    except (ValueError, TypeError):
        return False

def _node_type_from_proposed(proposed_type):
    if "/" in proposed_type:
        return proposed_type.split("/")[0]
    return proposed_type

def _subtype_from_proposed(proposed_type):
    if "/" in proposed_type:
        return proposed_type.split("/")[-1]
    return "Unknown"

# ── Database ─────────────────────────────────────────────────────────────

def open_db():
    import real_ladybug as lb
    db = lb.Database(str(DB_PATH))
    conn = lb.Connection(db)
    return conn

def ensure_init(conn):
    """Ensure Chronicle schema exists."""
    import real_ladybug as lb
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    (DB_PATH.parent / "staging").mkdir(exist_ok=True)

    tables_result = conn.execute("CALL show_tables() RETURN *")
    existing = [row[1] for row in tables_result]
    
    ddl = []
    if "Entity" not in existing:
        ddl.append("""CREATE NODE TABLE Entity (
            id STRING PRIMARY KEY, name STRING, entity_type STRING,
            aliases STRING, identifiers STRING, possible_matches STRING,
            merge_history STRING, identity_state STRING,
            source_skill STRING, record_time STRING
        )""")
    if "Place" not in existing:
        ddl.append("""CREATE NODE TABLE Place (
            id STRING PRIMARY KEY, name STRING, place_type STRING,
            coordinates STRING, address STRING,
            source_skill STRING, record_time STRING
        )""")
    if "Concept" not in existing:
        ddl.append("""CREATE NODE TABLE Concept (
            id STRING PRIMARY KEY, name STRING, description STRING,
            concept_type STRING, event_time STRING,
            source_skill STRING, record_time STRING
        )""")
    if "Thing" not in existing:
        ddl.append("""CREATE NODE TABLE Thing (
            id STRING PRIMARY KEY, name STRING, thing_type STRING,
            metadata STRING, source_skill STRING, record_time STRING
        )""")
    if "Signal" not in existing:
        ddl.append("""CREATE NODE TABLE Signal (
            id STRING PRIMARY KEY, source_skill STRING,
            source_type STRING, source_journal_type STRING,
            payload STRING, user_relevance STRING,
            timestamp STRING, status STRING
        )""")
    if "Candidate" not in existing:
        ddl.append("""CREATE NODE TABLE Candidate (
            id STRING PRIMARY KEY, proposed_type STRING, proposed_data STRING,
            supporting_signals STRING, confidence STRING,
            user_relevance STRING, status STRING,
            created_at STRING, resolved_at STRING, resolved_reason STRING
        )""")
    if "Inference" not in existing:
        ddl.append("""CREATE NODE TABLE Inference (
            id STRING PRIMARY KEY, inference_type STRING, confidence STRING,
            supporting_nodes STRING, description STRING, created_at STRING
        )""")
    
    # Check for relationship tables
    rel_tables = [r for r in existing if r in ("Relates", "Supports", "Promotes", "Infers")]
    if "Relates" not in existing:
        ddl.append("""CREATE REL TABLE Relates (
            FROM Entity TO Entity,
            FROM Entity TO Concept,
            FROM Entity TO Place,
            FROM Entity TO Thing,
            FROM Concept TO Place,
            FROM Concept TO Concept,
            relationship_type STRING, evidence_refs STRING, confidence STRING,
            event_time STRING, record_time STRING,
            valid_from STRING, valid_until STRING
        )""")
    if "Supports" not in existing:
        ddl.append("CREATE REL TABLE Supports (FROM Signal TO Candidate)")
    if "Promotes" not in existing:
        ddl.append("""CREATE REL TABLE Promotes (
            FROM Candidate TO Entity,
            FROM Candidate TO Place,
            FROM Candidate TO Concept,
            FROM Candidate TO Thing
        )""")
    if "Infers" not in existing:
        ddl.append("""CREATE REL TABLE Infers (
            FROM Inference TO Entity,
            FROM Inference TO Concept,
            FROM Inference TO Place
        )""")
    
    for stmt in ddl:
        try:
            conn.execute(stmt)
        except Exception as e:
            print(f"  DDL warning: {e}")

# ── Ingestion Log ────────────────────────────────────────────────────────

def load_processed():
    """Load processed file paths from ingestion log. Handles 5 key variants + path normalization."""
    processed = set()
    if not INGESTION_LOG.exists():
        return processed
    
    lines = INGESTION_LOG.read_text().strip().split('\n')
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
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
    return processed

def clean_stale_entries():
    """Remove ONLY interrupted-run entries (signals_created=0, no reason field) older than 15 min.
    Preserve legitimate 'no_entities' entries to prevent re-processing identical files."""
    if not INGESTION_LOG.exists():
        return
    lines = INGESTION_LOG.read_text().strip().split('\n')
    now = datetime.now(timezone.utc)
    kept = []
    for line in lines:
        if not line.strip():
            kept.append(line)
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            kept.append(line)
            continue
        # Only remove zero-signal entries WITHOUT a reason field (interrupted runs)
        # Entries with reason="no_entities" are legitimate and should be preserved
        if entry.get("signals_created", 0) == 0 and not entry.get("reason"):
            ingested_at = entry.get("ingested_at", "")
            if "T" in ingested_at:
                try:
                    ing_time = datetime.fromisoformat(ingested_at.replace('Z', '+00:00'))
                    age_min = (now - ing_time).total_seconds() / 60
                    if age_min > 15:
                        continue
                except Exception:
                    pass
        kept.append(line)
    INGESTION_LOG.write_text('\n'.join(kept) + '\n')

# ── Entity Extraction ────────────────────────────────────────────────────

def extract_entities(data):
    """Extract entities_observed from all 4 locations."""
    entities = []
    
    # Location 1: Top-level
    top = data.get("entities_observed", [])
    if isinstance(top, list):
        entities.extend(top)
    
    # Location 2: Under decision
    decision = data.get("decision", {})
    if isinstance(decision, dict):
        dec_top = decision.get("entities_observed", [])
        if isinstance(dec_top, list):
            entities.extend(dec_top)
        
        # Location 3: decision.payload
        payload = decision.get("payload", {})
        if isinstance(payload, dict):
            nested = payload.get("entities_observed", [])
            if isinstance(nested, list):
                entities.extend(nested)
    
    # Location 4: Under payload (top-level)
    top_payload = data.get("payload", {})
    if isinstance(top_payload, dict):
        ptop = top_payload.get("entities_observed", [])
        if isinstance(ptop, list):
            entities.extend(ptop)
    
    return entities

# ── Signal Creation ──────────────────────────────────────────────────────

def create_signal(conn, entity, source_skill, source_journal_type="unknown"):
    """Create a Signal node for an entity observation."""
    sid = _gen_id("sig")
    name = _extract_name(entity)
    etype = _extract_type(entity)
    ur = _get_user_relevance(entity)
    conf = _get_confidence(entity)
    
    payload = json.dumps({
        "name": name,
        "type": etype,
        "confidence": conf,
        "user_relevance": ur,
        "source": source_skill
    })
    
    ts = _ts()
    conn.execute(f"""
        CREATE (s:Signal {{
            id: '{_esc(sid)}',
            source_skill: '{_esc(source_skill)}',
            source_type: 'journal',
            source_journal_type: '{_esc(source_journal_type)}',
            payload: '{_esc(payload)}',
            user_relevance: '{_esc(ur)}',
            timestamp: '{ts}',
            status: 'active'
        }})
    """)
    return sid, name, etype, ur, conf

def create_candidate(conn, sid, name, etype, ur, conf, source_skill):
    """Create a Candidate node and link it to the signal via Supports."""
    # Check for existing candidate with same name
    escaped_name = _esc(name)
    existing = conn.execute(f"""
        MATCH (c:Candidate {{status: 'pending'}})
        WHERE c.proposed_data CONTAINS '{escaped_name}'
        RETURN c.id, c.supporting_signals, c.confidence, c.user_relevance
        LIMIT 1
    """)
    existing_rows = [r for r in existing]
    
    if existing_rows:
        # Update existing candidate
        ec = existing_rows[0]
        cand_id = ec[0]
        existing_sigs = safe_json_loads(ec[1])
        existing_sigs.append(sid)
        
        # Upgrade confidence if new signal has higher
        existing_conf = ec[2]
        if is_promotable(conf) and not is_promotable(existing_conf):
            final_conf = conf
        else:
            final_conf = existing_conf
        
        # Upgrade user_relevance if new signal says user
        existing_ur = ec[3]
        final_ur = "user" if (ur == "user" or existing_ur == "user") else (
            "unknown" if (ur == "unknown" or existing_ur == "unknown") else "agent_only"
        )
        
        conn.execute(f"""
            MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
            SET c.supporting_signals = '{_esc(json.dumps(existing_sigs))}',
                c.confidence = '{_esc(final_conf)}',
                c.user_relevance = '{_esc(final_ur)}'
        """)
        
        # Create Supports edge
        try:
            conn.execute(f"""
                MATCH (s:Signal {{id: '{_esc(sid)}'}})
                MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
                CREATE (s)-[:Supports]->(c)
            """)
        except Exception:
            pass
        return cand_id
    else:
        # Create new candidate
        cand_id = _gen_id("cand")
        proposed_data = json.dumps({"name": name, "type": etype})
        ts = _ts()
        
        conn.execute(f"""
            CREATE (c:Candidate {{
                id: '{_esc(cand_id)}',
                proposed_type: '{_esc(etype)}',
                proposed_data: '{_esc(proposed_data)}',
                supporting_signals: '{_esc(json.dumps([sid]))}',
                confidence: '{_esc(conf)}',
                user_relevance: '{_esc(ur)}',
                status: 'pending',
                created_at: '{ts}',
                resolved_at: '',
                resolved_reason: ''
            }})
        """)
        
        # Create Supports edge
        try:
            conn.execute(f"""
                MATCH (s:Signal {{id: '{_esc(sid)}'}})
                MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
                CREATE (s)-[:Supports]->(c)
            """)
        except Exception:
            pass
        return cand_id

# ── Promotion ────────────────────────────────────────────────────────────

def promote_candidate(conn, cand_id, proposed_type, pdata, source_skill="elephas-consolidate"):
    """Promote a candidate to a Chronicle fact."""
    name = pdata.get("name", "Unknown")
    subtype = pdata.get("type", "Unknown")
    
    # Determine node type from proposed_type
    if "/" in proposed_type:
        node_type = proposed_type.split("/")[0]
    else:
        node_type = proposed_type
    
    # Validate node type
    if node_type not in ("Entity", "Place", "Concept", "Thing"):
        node_type = "Entity"
    
    ent_id = _gen_id(node_type[:3].lower())
    ts = _ts()
    
    # Create node with type-specific properties
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
    
    # Create Promotes edge
    conn.execute(f"""
        MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
        MATCH (e:{node_type} {{id: '{_esc(ent_id)}'}})
        CREATE (c)-[:Promotes]->(e)
    """)
    
    # Mark candidate as promoted
    conn.execute(f"""
        MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
        SET c.status = 'promoted', c.resolved_at = '{ts}'
    """)
    
    return ent_id

# ── Weave Enrichment Ingestion ────────────────────────────────────────────

def extract_weave_enriched(data):
    """Extract contacts from Weave enrichment 'enriched' field.
    
    Weave enrichment journals store enriched contact data in a top-level
    'enriched' array (not in entities_observed in any of the 4 standard
    locations). This is a known format gap documented in the skill.
    """
    enriched = data.get("enriched", [])
    if not enriched or not isinstance(enriched, list):
        return []
    entities = []
    for contact in enriched:
        name = contact.get("name", "")
        if not name:
            continue
        entities.append({
            "name": name,
            "type": "Person",
            "user_relevance": "user",
            "confidence": str(contact.get("confidence", 0.8))
        })
    return entities

def write_log_entry(fpath, signals_created, reason=""):
    entry = {"file": str(fpath), "ingested_at": _ts(), "signals_created": signals_created}
    if reason:
        entry["reason"] = reason
    return json.dumps(entry)

def run_weave_enrichment_ingest(conn, processed):
    """Phase 1b: Ingest enriched contacts from Weave enrichment journals.
    
    Scans all weave-enrichment-*.json files in journal directories. Skips
    any that are already tracked in the ingestion log (processed set).
    Creates Signal → Candidate chains from the 'enriched' array data.
    """
    print("\n=== Phase 1b: Weave Enrichment Ingestion ===")
    signals_created = 0
    candidates_created = 0
    enrichment_files = 0
    log_entries = []

    for skill_dir in sorted(JOURNALS_ROOT.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith('.'):
            continue
        for date_dir in sorted(skill_dir.iterdir()):
            if not date_dir.is_dir():
                continue
            for f in sorted(date_dir.glob("weave-enrichment-*.json")):
                abs_path = str(f)
                rel_path = str(f.relative_to(JOURNALS_ROOT))
                
                # Skip if already logged (avoids duplicates on re-runs)
                if abs_path in processed or rel_path in processed:
                    continue
                
                try:
                    data = json.loads(f.read_text())
                except Exception as e:
                    print(f"  SKIP {f.name}: {e}")
                    log_entries.append(write_log_entry(f, 0, "parse_error"))
                    continue
                
                enriched = extract_weave_enriched(data)
                if not enriched:
                    log_entries.append(write_log_entry(f, 0, "no_enriched_contacts"))
                    continue
                
                enrichment_files += 1
                file_sigs = 0
                file_cands = 0
                
                for entity in enriched:
                    name = entity["name"]
                    etype = entity["type"]
                    ur = entity["user_relevance"]
                    conf = entity["confidence"]
                    try:
                        sid, ename, etype2, ur2, conf2 = create_signal(
                            conn, entity, "ocas-weave", "Enrichment"
                        )
                        file_sigs += 1
                        create_candidate(conn, sid, ename, etype, ur, conf, "ocas-weave")
                        file_cands += 1
                        print(f"  + {name} (conf={conf})")
                    except Exception as e:
                        print(f"  Error for '{name}': {e}")
                
                log_entries.append(write_log_entry(f, file_sigs))
                signals_created += file_sigs
                candidates_created += file_cands
    
    if log_entries:
        with open(INGESTION_LOG, 'a') as f:
            for entry in log_entries:
                f.write(entry + '\n')
    
    print(f"  Enrichment files scanned: {enrichment_files}")
    print(f"  Signals created: {signals_created}")
    print(f"  Candidates created: {candidates_created}")
    return signals_created, candidates_created

# ── Orphan Cleanup ───────────────────────────────────────────────────────

def clean_orphan_signals(conn):
    """Mark active signals with no Supports edge as orphaned."""
    orphans = conn.execute("""
        MATCH (s:Signal {status: 'active'})
        WHERE NOT EXISTS { MATCH (s)-[:Supports]->() }
        RETURN s.id
    """)
    count = 0
    for row in orphans:
        conn.execute(f"""
            MATCH (s:Signal {{id: '{_esc(row[0])}'}})
            SET s.status = 'orphaned'
        """)
        count += 1
    return count

# ── Main Pipeline ────────────────────────────────────────────────────────

def run_ingest(conn=None):
    """Phase 1: Ingest journal files, create signals and candidates."""
    print("=== Phase 1: Ingestion ===")
    
    if conn is None:
        conn = open_db()
        print("  (opened own DB connection)")
    
    # Clean stale entries
    clean_stale_entries()
    processed = load_processed()
    print(f"  Already processed: {len(processed)} files")
    
    # Find unprocessed files (3-level: skill_dir/date_dir/file.json)
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
    
    print(f"  Unprocessed files: {len(unprocessed)}")
    
    if not unprocessed:
        print("  Nothing to ingest.")
        return 0, 0
    
    signals_created = 0
    candidates_created = 0
    files_processed = 0
    log_entries = []
    
    for fpath in unprocessed:
        try:
            raw = json.loads(Path(fpath).read_text())
        except Exception as e:
            print(f"  SKIP {fpath}: {e}")
            continue
        
        # Handle JSON lists (some skill journals wrap in a list)
        data = raw[0] if isinstance(raw, list) and len(raw) > 0 else raw
        
        source_skill = Path(fpath).parent.parent.name  # journals/skill/date/file.json
        if not isinstance(data, dict):
            print(f"  SKIP {fpath}: unexpected type {type(data).__name__}")
            continue
        
        journal_type = data.get("journal_type", data.get("type", "unknown"))
        
        entities = extract_entities(data)
        
        if not entities:
            # Log as processed with 0 signals
            log_entries.append(json.dumps({
                "file": fpath,
                "ingested_at": _ts(),
                "signals_created": 0,
                "reason": "no_entities"
            }))
            files_processed += 1
            continue
        
        file_signals = 0
        file_candidates = 0
        
        for entity in entities:
            if isinstance(entity, (int, float)):
                continue  # Skip count-only entries
            
            name = _extract_name(entity)
            if not name or name == "0":
                continue
            
            try:
                sid, ename, etype, ur, conf = create_signal(
                    conn, entity, source_skill, journal_type
                )
                signals_created += 1
                file_signals += 1
                
                if ename:
                    create_candidate(conn, sid, ename, etype, ur, conf, source_skill)
                    candidates_created += 1
                    file_candidates += 1
            except Exception as e:
                print(f"  Signal error for '{name}': {e}")
        
        log_entries.append(json.dumps({
            "file": fpath,
            "ingested_at": _ts(),
            "signals_created": file_signals,
            "candidates_created": file_candidates
        }))
        files_processed += 1
    
    # Write ingestion log
    if log_entries:
        with open(INGESTION_LOG, 'a') as f:
            for entry in log_entries:
                f.write(entry + '\n')
    
    # Clean orphan signals
    orphans = clean_orphan_signals(conn)
    if orphans:
        print(f"  Cleaned {orphans} orphan signals")
    
    print(f"  Files processed: {files_processed}")
    print(f"  Signals created: {signals_created}")
    print(f"  Candidates created: {candidates_created}")
    
    return signals_created, candidates_created

def run_consolidate(conn=None):
    """Phase 2: Immediate consolidation - promote high-confidence user-relevant candidates."""
    print("\n=== Phase 2: Immediate Consolidation ===")
    
    if conn is None:
        conn = open_db()
        print("  (opened own DB connection)")
    
    # Get pending user-relevant candidates
    result = conn.execute("""
        MATCH (c:Candidate {status: 'pending', user_relevance: 'user'})
        RETURN c.id, c.proposed_type, c.proposed_data, c.confidence, c.user_relevance
    """)
    
    pending = [row for row in result]
    print(f"  Pending user-relevant candidates: {len(pending)}")
    
    # Also get unknown-relevance candidates
    unknown_result = conn.execute("""
        MATCH (c:Candidate {status: 'pending', user_relevance: 'unknown'})
        RETURN c.id, c.proposed_type, c.proposed_data, c.confidence, c.user_relevance
    """)
    unknown_pending = [row for row in unknown_result]
    print(f"  Pending unknown-relevance candidates: {len(unknown_pending)}")
    
    # Get agent_only count for reporting
    agent_result = conn.execute("""
        MATCH (c:Candidate {status: 'pending', user_relevance: 'agent_only'})
        RETURN count(c)
    """)
    agent_rows = [r for r in agent_result]
    agent_only_count = agent_rows[0][0] if agent_rows else 0
    print(f"  Agent-only candidates (withheld): {agent_only_count}")
    
    promoted = 0
    errors = 0
    
    for row in pending:
        cand_id, proposed_type, proposed_data, conf, ur = row
        
        if not is_promotable(conf):
            continue
        
        pdata = safe_json_loads(proposed_data)
        name = pdata.get("name", "")
        if not name:
            continue
        
        # Check if entity already exists in Chronicle
        escaped_name = _esc(name)
        existing_entities = []
        for label in ("Entity", "Place", "Concept", "Thing"):
            try:
                r = conn.execute(f"""
                    MATCH (e:{label})
                    WHERE e.name = '{escaped_name}'
                    RETURN e.id
                    LIMIT 1
                """)
                existing_entities.extend([x for x in r])
            except Exception:
                pass
        
        if existing_entities:
            # Already exists, mark candidate as promoted to existing
            conn.execute(f"""
                MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
                SET c.status = 'promoted', c.resolved_at = '{_ts()}', 
                    c.resolved_reason = 'duplicate_of_existing'
            """)
            promoted += 1
            continue
        
        try:
            ent_id = promote_candidate(conn, cand_id, proposed_type, pdata)
            promoted += 1
        except Exception as e:
            print(f"  Promotion error for '{name}': {e}")
            errors += 1
    
    # Report
    print(f"  Promoted: {promoted}")
    print(f"  Errors: {errors}")
    
    # Verify
    promoted_result = conn.execute("""
        MATCH (c:Candidate {status: 'promoted'})
        RETURN count(c)
    """)
    promoted_rows = [r for r in promoted_result]
    total_promoted = promoted_rows[0][0] if promoted_rows else 0
    
    pending_result = conn.execute("""
        MATCH (c:Candidate {status: 'pending'})
        RETURN count(c)
    """)
    pending_rows = [r for r in pending_result]
    total_pending = pending_rows[0][0] if pending_rows else 0
    
    print(f"\n=== Final Status ===")
    print(f"  Total promoted candidates: {total_promoted}")
    print(f"  Total pending candidates: {total_pending}")
    
    # Entity counts
    for label in ("Entity", "Place", "Concept", "Thing"):
        r = conn.execute(f"MATCH (n:{label}) RETURN count(n)")
        rows = [x for x in r]
        count = rows[0][0] if rows else 0
        print(f"  {label} nodes: {count}")
    
    return promoted

def write_journal(conn, signals_created, candidates_created, promoted):
    """Write Action Journal for this run."""
    journal_dir = Path("/root/.hermes/commons/journals/ocas-elephas")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    journal_dir = journal_dir / today
    journal_dir.mkdir(parents=True, exist_ok=True)
    
    run_id = _gen_id("run")
    journal = {
        "run_id": run_id,
        "journal_type": "IngestConsolidate",
        "skill": "ocas-elephas",
        "timestamp": _ts(),
        "decision": {
            "action": "ingest_and_consolidate",
            "result": "completed",
            "payload": {
                "signals_created": signals_created,
                "candidates_created": candidates_created,
                "candidates_promoted": promoted,
                "entities_observed": 0
            }
        },
        "entities_observed": 0
    }
    
    journal_path = journal_dir / f"{run_id}.json"
    journal_path.write_text(json.dumps(journal, indent=2))
    print(f"\n  Journal written: {journal_path}")

# ── Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"Elephas Pipeline — {_ts()}")
    print(f"DB: {DB_PATH}")
    
    conn = open_db()
    ensure_init(conn)
    
    # Phase 1a: Standard journal ingestion
    signals, candidates = run_ingest(conn)
    
    # Phase 1b: Weave enrichment format gap
    processed = load_processed()
    w_sigs, w_cands = run_weave_enrichment_ingest(conn, processed)
    
    total_sigs = signals + w_sigs
    total_cands = candidates + w_cands
    
    # Phase 2: Consolidation
    promoted = run_consolidate(conn)
    
    write_journal(conn, total_sigs, total_cands, promoted)
    print("\nDone.")
