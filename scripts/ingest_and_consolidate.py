"""
Elephas journal ingestion and immediate consolidation.
Processes unprocessed journal files, creates signals and candidates, promotes eligible candidates.
"""
import real_ladybug as lb
import json, uuid, re, hashlib
import shutil
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional

# Correct paths based on operational notes
DB_PATH = Path("/root/.hermes/commons/db/ocas-elephas/chronicle.lbug")
JOURNALS_DIR = Path("/root/.hermes/commons/journals")
INGESTION_LOG = Path("/root/.hermes/commons/db/ocas-elephas/ingestion_log.jsonl")
INTAKE_DIR = Path("/root/.hermes/commons/db/ocas-elephas/intake")
PROCESSED_DIR = INTAKE_DIR / "processed"
STAGING_DIR = Path("/root/.hermes/commons/db/ocas-elephas/staging")

# Create directories
INTAKE_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
STAGING_DIR.mkdir(parents=True, exist_ok=True)

NOW = datetime.now(timezone.utc).isoformat()
RUN_ID = f"ingest_{NOW[:19].replace(':', '-').replace('T', '_')}"

# Entity type mapping for Chronicle nodes
TYPE_PROPERTY_MAP = {
    "Entity": "entity_type",
    "Place": "place_type",
    "Concept": "concept_type",
    "Thing": "thing_type"
}

def _open_db():
    db = lb.Database(str(DB_PATH))
    conn = lb.Connection(db)
    return db, conn

def _esc(s):
    """Escape for Cypher string literals (backslash + single quote)."""
    if s is None: return ""
    return str(s).replace("\\", "\\\\").replace("'", "\\'")

def _parse_repr_payload(text):
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

def _extract_name(e):
    """Extract entity name from various field naming conventions."""
    if e.get("name"): return e["name"]
    if e.get("description"): return e["description"]
    ev = e.get("entity", "")
    if ev and "/" in ev: return ev.split("/")[-1]
    return ev or "unknown"

def _extract_entity_type(e):
    """Extract entity type from various field naming conventions."""
    return e.get("type") or e.get("entity_type") or e.get("proposed_type") or "Entity"

def _clean_stale_ingestion_log():
    """Remove stale ingestion log entries (signals_created=0 from interrupted runs).
    
    Failed or interrupted runs write entries with signals_created: 0. Subsequent runs
    skip those files because their paths are already logged, even though they were never
    actually processed. This cleanup allows reprocessing of those files.
    
    Returns: number of entries removed.
    """
    if not INGESTION_LOG.exists():
        return 0
    
    lines = INGESTION_LOG.read_text().strip().split('\n')
    kept = []
    removed = 0
    
    for line in lines:
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            if entry.get("signals_created", 0) == 0:
                removed += 1
            else:
                kept.append(line)
        except json.JSONDecodeError:
            kept.append(line)  # Keep malformed lines to avoid data loss
    
    if removed > 0:
        INGESTION_LOG.write_text('\n'.join(kept) + '\n' if kept else '')
    
    return removed

def _get_processed_files():
    """Read ingestion log to get already processed files."""
    processed = set()
    if INGESTION_LOG.exists():
        for line in INGESTION_LOG.read_text().splitlines():
            if line.strip():
                try:
                    entry = json.loads(line)
                    processed.add(entry.get("journal_path", ""))
                except:
                    pass
    return processed

def _load_json_file(file_path):
    """Load JSON file with error handling."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"  JSON parse error in {file_path}: {e}")
        return None
    except Exception as e:
        print(f"  Error reading {file_path}: {e}")
        return None

def _extract_signals_from_journal(journal_data, file_path):
    """Extract signals from a journal file."""
    signals = []
    journal_type = journal_data.get("journal_type", "unknown")
    source_skill = journal_data.get("skill_id", "unknown")
    
    # Check for entities_observed at top level first, then nested
    # NOTE: entities_observed can be an integer (0) in Elephas' own consolidation journals
    # or a list of dicts in skill journals from Scout, Weave, Sift, etc.
    entities = journal_data.get("entities_observed", [])
    if not isinstance(entities, list):
        entities = []
    
    if not entities:
        decision = journal_data.get("decision", {})
        if isinstance(decision, dict):
            nested = decision.get("payload", {}).get("entities_observed", [])
            if isinstance(nested, list):
                entities = nested
    
    # Process entities_observed
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        
        name = _extract_name(entity)
        if not name or name == "unknown":
            continue
            
        entity_type = _extract_entity_type(entity)
        confidence = entity.get("confidence", "low")
        user_relevance = entity.get("user_relevance", "unknown")
        
        # Build payload
        payload = {
            "name": name,
            "type": entity_type,
            "confidence": confidence,
            "proposed_type": entity_type
        }
        
        # Add any additional fields
        for key in ["identifiers", "resolved_handles", "source_refs", "findings_summary"]:
            if key in entity:
                payload[key] = entity[key]
        
        signal = {
            "id": f"sig_{uuid.uuid4().hex[:12]}",
            "source_skill": source_skill,
            "source_type": "journal",
            "source_journal_type": journal_type,
            "payload": payload,
            "user_relevance": user_relevance,
            "timestamp": journal_data.get("timestamp", NOW),
            "status": "active"
        }
        signals.append(signal)
    
    # Check for signal payloads in journal
    signal_payload = journal_data.get("signal")
    if not signal_payload:
        decision = journal_data.get("decision", {})
        if isinstance(decision, dict):
            signal_payload = decision.get("payload", {}).get("signal")
    
    if signal_payload and isinstance(signal_payload, dict):
        # Normalize signal format
        normalized = _normalize_signal(signal_payload, source_skill, journal_type)
        if normalized:
            signals.append(normalized)
    
    return signals

def _normalize_signal(signal_data, source_skill, journal_type):
    """Normalize signal to native format."""
    # Check if already native format
    if "id" in signal_data and "signal_id" not in signal_data:
        return signal_data
    
    # Legacy format conversion
    if "signal_id" in signal_data:
        sig_id = signal_data["signal_id"]
        if not sig_id.startswith("sig_"):
            sig_id = f"sig_{sig_id}"
        
        # Map signal_type to source_journal_type
        sig_type = signal_data.get("signal_type", "").lower()
        journal_type_map = {
            "observation": "Observation",
            "action": "Action",
            "research": "Research"
        }
        source_journal_type = journal_type_map.get(sig_type, journal_type)
        
        # Map provenance.source_system to source_skill
        source_system = signal_data.get("provenance", {}).get("source_system", "")
        skill_map = {
            "google_workspace": "ocas-bower",
            "social_graph": "ocas-weave",
            "web_research": "ocas-sift",
            "osint": "ocas-scout"
        }
        skill = skill_map.get(source_system, f"legacy:{source_system}" if source_system else source_skill)
        
        # Build normalized signal
        normalized = {
            "id": sig_id,
            "source_skill": skill,
            "source_type": "journal",
            "source_journal_type": source_journal_type,
            "payload": signal_data.get("payload", {}),
            "user_relevance": signal_data.get("user_relevance", "unknown"),
            "timestamp": signal_data.get("timestamp", NOW),
            "status": "active",
            "_normalized_from": {
                "format": "legacy",
                "original_id": signal_data.get("signal_id"),
                "converted_at": NOW,
                "fields_mapped": ["signal_id", "signal_type", "provenance.source_system"]
            }
        }
        return normalized
    
    # Unknown format - create minimal signal
    return {
        "id": f"sig_{uuid.uuid4().hex[:12]}",
        "source_skill": source_skill,
        "source_type": "journal",
        "source_journal_type": journal_type,
        "payload": signal_data,
        "user_relevance": signal_data.get("user_relevance", "unknown"),
        "timestamp": signal_data.get("timestamp", NOW),
        "status": "active"
    }

def _ingest_journals(conn):
    """Process unprocessed journal files and create signals."""
    processed_files = _get_processed_files()
    signals_created = 0
    journal_files_processed = 0
    
    # Find all journal JSON files
    journal_files = []
    for skill_dir in JOURNALS_DIR.iterdir():
        if skill_dir.is_dir() and not skill_dir.name.startswith('.'):
            for date_dir in skill_dir.iterdir():
                if date_dir.is_dir():
                    for f in date_dir.glob("*.json"):
                        journal_files.append(f)
    
    print(f"Found {len(journal_files)} total journal files")
    
    # Filter to unprocessed ones
    unprocessed = [f for f in journal_files if str(f) not in processed_files]
    print(f"Unprocessed journal files: {len(unprocessed)}")
    
    for file_path in unprocessed[:50]:  # Limit to 50 files per run
        journal_data = _load_json_file(file_path)
        if not journal_data:
            continue
        
        # Extract signals from journal
        signals = _extract_signals_from_journal(journal_data, file_path)
        
        # Create Signal nodes
        for signal in signals:
            sig_id = signal["id"]
            
            # Check if signal already exists
            existing = list(conn.execute(
                "MATCH (s:Signal {id: $id}) RETURN s.id", {"id": sig_id}
            ))
            if existing:
                continue
            
            # Create Signal node
            payload_json = json.dumps(signal.get("payload", {}), default=str)
            conn.execute("""
                MERGE (s:Signal {id: $id})
                SET s.source_skill = $sk, s.source_type = $st,
                    s.source_journal_type = $sjt, s.payload = $pay,
                    s.user_relevance = $rel, s.timestamp = $ts, s.status = 'active'
            """, {
                "id": sig_id,
                "sk": signal.get("source_skill", "unknown"),
                "st": signal.get("source_type", "journal"),
                "sjt": signal.get("source_journal_type", "unknown"),
                "pay": payload_json,
                "rel": signal.get("user_relevance", "unknown"),
                "ts": signal.get("timestamp", NOW)
            })
            signals_created += 1
        
        # Log ingestion
        with open(INGESTION_LOG, "a") as log_file:
            log_file.write(json.dumps({
                "run_id": RUN_ID,
                "source_skill": journal_data.get("skill_id", "unknown"),
                "source_type": "journal",
                "journal_path": str(file_path),
                "journal_type": journal_data.get("journal_type", "unknown"),
                "signals_created": len(signals),
                "candidates_created": 0,  # Will be updated during candidate creation
                "ingested_at": NOW
            }) + "\n")
        
        journal_files_processed += 1
    
    print(f"Processed {journal_files_processed} journal files")
    print(f"Created {signals_created} signals")
    return signals_created

def _propose_candidates(conn):
    """For each active Signal not yet backing a Candidate, create one."""
    created = 0
    
    # Find signals without an outbound Supports edge
    rows = list(conn.execute("""
        MATCH (s:Signal {status: 'active'})
        WHERE NOT EXISTS { MATCH (s)-[:Supports]->() }
        RETURN s.id, s.payload, s.user_relevance, s.source_skill
    """))
    
    print(f"Found {len(rows)} signals without candidates")
    
    for sig_id, payload_json, rel, source_skill in rows:
        # Parse payload - handle both JSON and repr formats
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError:
            payload = _parse_repr_payload(payload_json)
            if payload:
                # Re-serialize as proper JSON
                conn.execute("""
                    MATCH (s:Signal {id: $id})
                    SET s.payload = $pay
                """, {"id": sig_id, "pay": json.dumps(payload, default=str)})
        
        if not payload:
            print(f"  SKIP empty payload for signal {sig_id}")
            continue
        
        name = payload.get("name", "")
        if not name:
            print(f"  SKIP no name in signal {sig_id}")
            continue
        
        ptype = payload.get("type", payload.get("proposed_type", "Entity"))
        conf = payload.get("confidence", "low")
        
        # Check for existing candidate with same name
        match = list(conn.execute("""
            MATCH (c:Candidate {status: 'pending'})
            WHERE c.proposed_data CONTAINS $nm
            RETURN c.id, c.supporting_signals, c.user_relevance
        """, {"nm": name}))
        
        if match:
            cand_id, existing_signals, existing_rel = match[0]
            # Update existing candidate
            signals_list = []
            if existing_signals:
                try:
                    signals_list = json.loads(existing_signals)
                except json.JSONDecodeError:
                    pass
            if sig_id not in signals_list:
                signals_list.append(sig_id)
                conn.execute("""
                    MATCH (c:Candidate {id: $cid})
                    SET c.supporting_signals = $ss
                """, {"cid": cand_id, "ss": json.dumps(signals_list)})
                
                # Create Supports edge
                conn.execute("""
                    MATCH (s:Signal {id: $sid}), (c:Candidate {id: $cid})
                    CREATE (s)-[:Supports]->(c)
                """, {"sid": sig_id, "cid": cand_id})
                
                # Upgrade user_relevance if needed
                if rel == "user" and existing_rel != "user":
                    conn.execute("""
                        MATCH (c:Candidate {id: $cid})
                        SET c.user_relevance = 'user'
                    """, {"cid": cand_id})
                
                print(f"  UPDATED candidate {cand_id} with signal {sig_id}")
            continue
        
        # Create new candidate
        cid = f"cand_{uuid.uuid4().hex[:12]}"
        conn.execute("""
            CREATE (c:Candidate {
                id: $cid, proposed_type: $pt, proposed_data: $pd,
                supporting_signals: $ss, confidence: $cf,
                user_relevance: $ur, status: 'pending',
                created_at: $now, resolved_at: '', resolved_reason: ''
            })
        """, {
            "cid": cid, "pt": ptype,
            "pd": json.dumps(payload, default=str),
            "ss": json.dumps([sig_id]),
            "cf": conf, "ur": rel, "now": NOW
        })
        
        # Create Supports edge
        conn.execute("""
            MATCH (s:Signal {id: $sid}), (c:Candidate {id: $cid})
            CREATE (s)-[:Supports]->(c)
        """, {"sid": sig_id, "cid": cid})
        
        created += 1
        print(f"  NEW CANDIDATE: {cid} for {name} (conf={conf}, rel={rel})")
    
    return created

def _get_promotable_candidates(conn):
    """Get candidates eligible for promotion."""
    rows = list(conn.execute("""
        MATCH (c:Candidate {status: 'pending', user_relevance: 'user'})
        WHERE c.confidence = 'high' OR c.confidence = 'med'
        RETURN c.id, c.proposed_data, c.confidence, c.proposed_type
    """))
    
    results = []
    for cid, pd_json, conf, ptype in rows:
        try:
            pdata = json.loads(pd_json)
        except json.JSONDecodeError:
            pdata = _parse_repr_payload(pd_json)
        results.append((cid, pdata, conf, ptype))
    
    return results

def _create_chronicle_node(conn, node_type, node_id, name, node_subtype, **kwargs):
    """Create a Chronicle node of the specified type."""
    type_property = TYPE_PROPERTY_MAP.get(node_type, "entity_type")
    
    # Check if node already exists
    existing = list(conn.execute(
        f"MATCH (n:{node_type} {{id: $id}}) RETURN n.id",
        {"id": node_id}
    ))
    if existing:
        return node_id
    
    # Create node
    conn.execute(f"""
        CREATE (n:{node_type} {{
            id: $id, name: $nm, {type_property}: $st,
            source_skill: 'ocas-elephas', record_time: $now
        }})
    """, {"id": node_id, "nm": name, "st": node_subtype, "now": NOW})
    
    # Set additional properties
    for key, value in kwargs.items():
        if value:
            escaped_value = _escape(str(value))
            conn.execute(f"""
                MATCH (n:{node_type} {{id: $id}})
                SET n.{key} = '{escaped_value}'
            """, {"id": node_id})
    
    return node_id

def _promote_candidates(conn):
    """Promote eligible candidates to Chronicle facts."""
    candidates = _get_promotable_candidates(conn)
    promoted = []
    
    print(f"Found {len(candidates)} promotable candidates")
    
    for cand_id, pdata, conf, ptype in candidates:
        name = pdata.get("name", "unknown")
        entity_type = pdata.get("type", ptype)
        desc = pdata.get("findings_summary", "")
        
        print(f"  PROMOTE: {name} ({entity_type}, conf={conf})")
        
        # Determine Chronicle node type
        if entity_type == "Person":
            node_type = "Entity"
            node_subtype = "Person"
        elif entity_type in ("Organization", "Company"):
            node_type = "Concept"
            node_subtype = "Idea"
        elif entity_type in ("Place", "Location", "Restaurant"):
            node_type = "Place"
            node_subtype = entity_type
        elif entity_type in ("Event", "Action"):
            node_type = "Concept"
            node_subtype = entity_type
        else:
            node_type = "Concept"
            node_subtype = "Idea"
        
        # Create node ID
        node_id = f"{node_type.lower()}_{name.lower().replace(' ', '_')}"
        
        # Prepare additional properties
        kwargs = {}
        if desc:
            kwargs["description"] = desc
        if pdata.get("identifiers"):
            kwargs["identifiers"] = json.dumps(pdata["identifiers"], default=str)
        if pdata.get("resolved_handles"):
            kwargs["aliases"] = json.dumps(pdata["resolved_handles"], default=str)
        
        # Create Chronicle node
        _create_chronicle_node(conn, node_type, node_id, name, node_subtype, **kwargs)
        
        # Create Promotes edge
        try:
            conn.execute(f"""
                MATCH (c:Candidate {{id: $cid}})
                MATCH (n:{node_type} {{id: $nid}})
                CREATE (c)-[:Promotes]->(n)
            """, {"cid": cand_id, "nid": node_id})
        except Exception as e:
            print(f"    Promotes edge error: {e}")
        
        # Update candidate status
        conn.execute("""
            MATCH (c:Candidate {id: $id})
            SET c.status = 'confirmed', c.resolved_at = $now,
                c.resolved_reason = 'promoted via immediate consolidation'
        """, {"id": cand_id, "now": NOW})
        
        # Consume supporting signals
        ss_row = list(conn.execute(
            "MATCH (c:Candidate {id: $id}) RETURN c.supporting_signals",
            {"id": cand_id}
        ))
        if ss_row:
            for sid in json.loads(ss_row[0][0] or "[]"):
                conn.execute(
                    "MATCH (s:Signal {id: $id}) SET s.status = 'consumed'",
                    {"id": sid}
                )
        
        promoted.append({"name": name, "type": entity_type, "confidence": conf})
        print(f"    DONE - created {node_type} node")
    
    return promoted

def _write_journal(promoted, sig_count, cand_count, stale_removed=0):
    """Write Action Journal for this run."""
    journal_dir = Path("/root/.hermes/commons/journals/ocas-elephas") / NOW[:10]
    journal_dir.mkdir(parents=True, exist_ok=True)
    
    journal = {
        "journal_type": "Action",
        "run_id": RUN_ID,
        "timestamp": NOW,
        "skill_id": "ocas-elephas",
        "actions": [{
            "type": "ingest + consolidate.immediate",
            "journal_files_processed": "see_ingestion_log",
            "stale_log_entries_cleaned": stale_removed,
            "signals_created": sig_count,
            "candidates_created": cand_count,
            "candidates_promoted": len(promoted),
            "result": "success"
        }],
        "decisions": [{
            "type": "promote",
            "payload": {"promoted": promoted}
        }]
    }
    
    journal_path = journal_dir / f"{RUN_ID}.json"
    with open(journal_path, 'w') as f:
        json.dump(journal, f, indent=2)
    
    print(f"Journal written to {journal_path}")

def _get_chronicle_stats(conn):
    """Get current Chronicle statistics."""
    stats = {}
    for label in ["Entity", "Place", "Concept", "Thing", "Signal", "Candidate", "Inference"]:
        try:
            cnt = list(conn.execute(f"MATCH (n:{label}) RETURN count(n)"))[0][0]
            stats[label] = cnt
        except:
            stats[label] = 0
    
    # Count relationships
    try:
        rel_cnt = list(conn.execute("MATCH ()-[r]->() RETURN count(r)"))[0][0]
        stats["Relationships"] = rel_cnt
    except:
        stats["Relationships"] = 0
    
    # Count pending candidates by relevance
    try:
        pending_user = list(conn.execute(
            "MATCH (c:Candidate {status: 'pending', user_relevance: 'user'}) RETURN count(c)"
        ))[0][0]
        stats["Pending_User"] = pending_user
    except:
        stats["Pending_User"] = 0
    
    try:
        pending_agent = list(conn.execute(
            "MATCH (c:Candidate {status: 'pending', user_relevance: 'agent_only'}) RETURN count(c)"
        ))[0][0]
        stats["Pending_Agent_Only"] = pending_agent
    except:
        stats["Pending_Agent_Only"] = 0
    
    return stats

def main():
    """Main ingestion and consolidation pipeline."""
    print(f"=== Elephas Ingestion & Consolidation ===")
    print(f"Run ID: {RUN_ID}")
    print(f"Timestamp: {NOW}")
    print()
    
    try:
        db, conn = _open_db()
        print("✓ Database connection established")
        
        # Step 0: Clean stale ingestion log entries
        print("\n--- Step 0: Cleaning stale ingestion log ---")
        stale_removed = _clean_stale_ingestion_log()
        print(f"Removed {stale_removed} stale entries (signals_created=0)")
        
        # Step 1: Ingest journals
        print("\n--- Step 1: Ingesting journals ---")
        signals_created = _ingest_journals(conn)
        
        # Step 2: Create candidates from signals
        print("\n--- Step 2: Creating candidates ---")
        candidates_created = _propose_candidates(conn)
        
        # Step 3: Promote eligible candidates
        print("\n--- Step 3: Promoting candidates ---")
        promoted = _promote_candidates(conn)
        
        # Step 4: Write journal
        print("\n--- Step 4: Writing journal ---")
        _write_journal(promoted, signals_created, candidates_created, stale_removed)
        
        # Step 5: Show statistics
        print("\n--- Chronicle Statistics ---")
        stats = _get_chronicle_stats(conn)
        for key, value in stats.items():
            print(f"  {key}: {value}")
        
        print("\n=== Summary ===")
        print(f"Signals created: {signals_created}")
        print(f"Candidates created: {candidates_created}")
        print(f"Candidates promoted: {len(promoted)}")
        
        if promoted:
            print("\nPromoted entities:")
            for p in promoted:
                print(f"  - {p['name']} ({p['type']}, confidence: {p['confidence']})")
        
        print("\n✓ Ingestion and consolidation complete")
        
    except Exception as e:
        print(f"\n✗ Error during ingestion/consolidation: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

if __name__ == "__main__":
    exit(main())