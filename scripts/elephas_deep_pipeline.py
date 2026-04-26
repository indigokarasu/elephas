#!/usr/bin/env python3
"""
Elephas Deep Consolidation Pipeline
Ingests Memory files and session logs, then runs full deep consolidation
with identity reconciliation and inference generation.
"""
import json, os, sys, uuid, hashlib, re
from datetime import datetime, timezone
from pathlib import Path

# ── Paths ──────────────────────────────────────────────────────────────────
AGENT_ROOT = Path(os.environ.get("HERMES_HOME") or os.environ.get("OCAS_AGENT_ROOT") or Path.home() / ".hermes")
DB_PATH = AGENT_ROOT / "commons/db/ocas-elephas/chronicle.lbug"
CONFIG_PATH = AGENT_ROOT / "commons/db/ocas-elephas/config.json"
INGESTION_LOG = AGENT_ROOT / "commons/db/ocas-elephas/ingestion_log.jsonl"
MEMORY_INGESTION_LOG = AGENT_ROOT / "commons/db/ocas-elephas/memory_ingestion_log.jsonl"
SESSION_INGESTION_LOG = AGENT_ROOT / "commons/db/ocas-elephas/session_ingestion_log.jsonl"
JOURNALS_ROOT = AGENT_ROOT / "commons/journals"
MEMORIES_DIR = AGENT_ROOT / "memories"
SESSIONS_DIR = AGENT_ROOT / "sessions"
DECISIONS_LOG = AGENT_ROOT / "commons/db/ocas-elephas/decisions.jsonl"

assert DB_PATH.exists(), f"DB not found: {DB_PATH}"

# ── Helpers ────────────────────────────────────────────────────────────────
def _ts():
    return datetime.now(timezone.utc).isoformat()

def _esc(s):
    if not s: return ""
    s = str(s)
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n").replace("\r", "")

def _gen_id(prefix="sig"):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

def _content_hash(content):
    return hashlib.sha256(content.encode()).hexdigest()[:16]

def parse_repr_payload(text):
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

def safe_json_loads(text):
    if not text: return {}
    try: return json.loads(text)
    except (json.JSONDecodeError, TypeError): return parse_repr_payload(str(text))

def _extract_name(e):
    if isinstance(e, str): return e
    if isinstance(e, (int, float)): return str(e)
    for field in ["name", "description", "entity_id", "entity"]:
        val = e.get(field, "")
        if val and str(val).strip() and str(val) != "0":
            sval = str(val)
            if field == "entity_id" and ":" in sval: return sval.split(":", 1)[-1]
            if field == "entity" and "/" in sval: return sval.split("/")[-1]
            return sval
    return ""

def _extract_type(e):
    if isinstance(e, (str, int, float)): return "Entity"
    for field in ["type", "entity_type", "entity"]:
        val = e.get(field, "")
        if val and str(val).strip():
            sval = str(val)
            if "/" in sval: return sval
            return sval
    return "Entity"

def _get_user_relevance(e):
    if isinstance(e, (str, int, float)): return "unknown"
    return e.get("user_relevance", "unknown")

def _get_confidence(e):
    if isinstance(e, (str, int, float)): return "low"
    conf = e.get("confidence", "")
    return str(conf).lower() if conf else "low"

def _node_type_from_proposed(pt):
    if "/" in pt: return pt.split("/")[0]
    return pt

def _subtype_from_proposed(pt):
    if "/" in pt: return pt.split("/")[-1]
    return "Unknown"

def is_promotable(conf_str):
    if conf_str in ("high",): return True
    if conf_str in ("medium", "med"): return True
    try: return float(conf_str) >= 0.6
    except: return False

# ── Database ───────────────────────────────────────────────────────────────
def open_db():
    import real_ladybug as lb
    return lb.Connection(lb.Database(str(DB_PATH)))

def ensure_init(conn):
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
    if "Relates" not in existing:
        ddl.append("""CREATE REL TABLE Relates (
            FROM Entity TO Entity, FROM Entity TO Concept,
            FROM Entity TO Place, FROM Entity TO Thing,
            FROM Concept TO Place, FROM Concept TO Concept,
            relationship_type STRING, evidence_refs STRING, confidence STRING,
            event_time STRING, record_time STRING,
            valid_from STRING, valid_until STRING
        )""")
    if "Supports" not in existing:
        ddl.append("CREATE REL TABLE Supports (FROM Signal TO Candidate)")
    if "Promotes" not in existing:
        ddl.append("""CREATE REL TABLE Promotes (
            FROM Candidate TO Entity, FROM Candidate TO Place,
            FROM Candidate TO Concept, FROM Candidate TO Thing
        )""")
    if "Infers" not in existing:
        ddl.append("""CREATE REL TABLE Infers (
            FROM Inference TO Entity, FROM Inference TO Concept,
            FROM Inference TO Place
        )""")
    for stmt in ddl:
        try: conn.execute(stmt)
        except Exception as e: print(f"  DDL warning: {e}")

# ── Signal & Candidate Creation ────────────────────────────────────────────
def create_signal(conn, entity, source_skill, source_type="journal", journal_type="unknown"):
    sid = _gen_id("sig")
    name = _extract_name(entity)
    etype = _extract_type(entity)
    ur = _get_user_relevance(entity)
    conf = _get_confidence(entity)
    payload = json.dumps({"name": name, "type": etype, "confidence": conf, "user_relevance": ur, "source": source_skill})
    ts = _ts()
    conn.execute(f"""CREATE (s:Signal {{
        id: '{_esc(sid)}', source_skill: '{_esc(source_skill)}',
        source_type: '{_esc(source_type)}', source_journal_type: '{_esc(journal_type)}',
        payload: '{_esc(payload)}', user_relevance: '{_esc(ur)}',
        timestamp: '{ts}', status: 'active'
    }})""")
    return sid, name, etype, ur, conf

def create_candidate(conn, sid, name, etype, ur, conf, source_skill):
    escaped_name = _esc(name)
    existing = conn.execute(f"""
        MATCH (c:Candidate {{status: 'pending'}})
        WHERE c.proposed_data CONTAINS '{escaped_name}'
        RETURN c.id, c.supporting_signals, c.confidence, c.user_relevance
        LIMIT 1
    """)
    existing_rows = [r for r in existing]
    if existing_rows:
        ec = existing_rows[0]; cand_id = ec[0]
        existing_sigs = safe_json_loads(ec[1])
        existing_sigs.append(sid)
        existing_conf = ec[2]; existing_ur = ec[3]
        final_conf = conf if (is_promotable(conf) and not is_promotable(existing_conf)) else existing_conf
        final_ur = "user" if (ur == "user" or existing_ur == "user") else (
            "unknown" if (ur == "unknown" or existing_ur == "unknown") else "agent_only")
        conn.execute(f"""MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
            SET c.supporting_signals = '{_esc(json.dumps(existing_sigs))}',
                c.confidence = '{_esc(final_conf)}', c.user_relevance = '{_esc(final_ur)}'""")
        try: conn.execute(f"""MATCH (s:Signal {{id: '{_esc(sid)}'}})
            MATCH (c:Candidate {{id: '{_esc(cand_id)}'}}) CREATE (s)-[:Supports]->(c)""")
        except: pass
        return cand_id
    else:
        cand_id = _gen_id("cand")
        proposed_data = json.dumps({"name": name, "type": etype})
        ts = _ts()
        conn.execute(f"""CREATE (c:Candidate {{
            id: '{_esc(cand_id)}', proposed_type: '{_esc(etype)}',
            proposed_data: '{_esc(proposed_data)}',
            supporting_signals: '{_esc(json.dumps([sid]))}',
            confidence: '{_esc(conf)}', user_relevance: '{_esc(ur)}',
            status: 'pending', created_at: '{ts}', resolved_at: '', resolved_reason: ''
        }})""")
        try: conn.execute(f"""MATCH (s:Signal {{id: '{_esc(sid)}'}})
            MATCH (c:Candidate {{id: '{_esc(cand_id)}'}}) CREATE (s)-[:Supports]->(c)""")
        except: pass
        return cand_id

# ── Promote Candidate ──────────────────────────────────────────────────────
def promote_candidate(conn, cand_id, proposed_type, pdata, source_skill="elephas-deep"):
    name = pdata.get("name", "Unknown")
    subtype = pdata.get("type", "Unknown")
    node_type = _node_type_from_proposed(proposed_type)
    if node_type not in ("Entity", "Place", "Concept", "Thing"):
        node_type = "Entity"
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
    conn.execute(f"""MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
        MATCH (e:{node_type} {{id: '{_esc(ent_id)}'}}) CREATE (c)-[:Promotes]->(e)""")
    conn.execute(f"""MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
        SET c.status = 'promoted', c.resolved_at = '{ts}', c.resolved_reason = 'deep_consolidation'""")
    return ent_id

# ── Phase 1: Memory Ingestion ──────────────────────────────────────────────
def extract_entities_from_memory(content):
    """Extract entity-like knowledge from Memory markdown files.
    Looks for lines that mention people, places, concepts."""
    entities = []
    lines = content.split('\n')
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        # Skip section headers and markers
        if line.startswith('§'):
            # § marker lines often contain entity info after the marker
            text = line[1:].strip()
            if text and len(text) > 3:
                # Check if it looks like an entity mention
                entities.append({
                    "name": text.split('---')[0].strip()[:80],
                    "type": "Entity",
                    "user_relevance": "user",
                    "confidence": "high"
                })
            continue
        # Skip code blocks
        if line.startswith('```'):
            continue
        # Lines with structured info
        if line.startswith('-') and ':' in line:
            # Could be a property definition
            key, val = line[1:].split(':', 1)
            key = key.strip()
            if len(key) > 2 and len(key) < 60 and len(val.strip()) > 2:
                entities.append({
                    "name": f"{key}: {val.strip()[:80]}",
                    "type": "Concept",
                    "user_relevance": "user",
                    "confidence": "medium"
                })
            continue
        if line.startswith('-'):
            text = line[1:].strip()
            if text and len(text) > 5:
                entities.append({
                    "name": text[:80],
                    "type": "Concept",
                    "user_relevance": "user",
                    "confidence": "medium"
                })
            continue
    return entities

def load_memory_processed():
    """Load processed memory files from memory_ingestion_log."""
    processed = {}
    if not MEMORY_INGESTION_LOG.exists():
        return processed
    for line in MEMORY_INGESTION_LOG.read_text().strip().split('\n'):
        if not line.strip(): continue
        try:
            e = json.loads(line)
            f = e.get("file", "")
            h = e.get("content_hash", e.get("hash", ""))
            if f: processed[f] = h
        except: pass
    return processed

def run_memory_ingestion(conn):
    """Ingest Memory files (MEMORY.md and USER.md) into Chronicle."""
    print("\n=== Phase 1: Memory Ingestion ===")
    processed = load_memory_processed()
    print(f"  Previously processed files: {len(processed)}")
    
    signals_created = 0
    candidates_created = 0
    files_scanned = 0
    files_changed = 0
    log_entries = []
    
    for mem_file in sorted(MEMORIES_DIR.glob("*.md")):
        files_scanned += 1
        content = mem_file.read_text()
        curr_hash = _content_hash(content)
        prev_hash = processed.get(str(mem_file), "")
        
        if curr_hash == prev_hash and str(mem_file) in processed:
            print(f"  UNCHANGED: {mem_file.name} (hash: {curr_hash})")
            continue
        
        files_changed += 1
        print(f"  CHANGED: {mem_file.name} (hash: {curr_hash}, prev: {prev_hash})")
        
        entities = extract_entities_from_memory(content)
        print(f"  Found {len(entities)} entities in {mem_file.name}")
        
        file_sigs = 0
        file_cands = 0
        for entity in entities:
            try:
                sid, ename, etype, ur, conf = create_signal(
                    conn, entity, "ocas-elephas", "MemoryFile"
                )
                file_sigs += 1
                create_candidate(conn, sid, ename, etype, ur, conf, "ocas-elephas")
                file_cands += 1
            except Exception as e:
                print(f"  Error for '{_extract_name(entity)}': {e}")
        
        signals_created += file_sigs
        candidates_created += file_cands
        
        # Write memory ingestion log entry
        log_entries.append(json.dumps({
            "file": str(mem_file),
            "content_hash": curr_hash,
            "ingested_at": _ts(),
            "signals_created": file_sigs,
            "entities_found": len(entities),
            "entities_unique": file_cands
        }))
    
    if log_entries:
        with open(MEMORY_INGESTION_LOG, 'a') as f:
            for entry in log_entries:
                f.write(entry + '\n')
    
    print(f"  Files scanned: {files_scanned}")
    print(f"  Files changed (processed): {files_changed}")
    print(f"  Signals created: {signals_created}")
    print(f"  Candidates created: {candidates_created}")
    return signals_created, candidates_created

# ── Phase 2: Session Log Ingestion ─────────────────────────────────────────
def load_session_processed():
    """Load processed session files from session_ingestion_log."""
    processed = {}
    if not SESSION_INGESTION_LOG.exists():
        return processed
    for line in SESSION_INGESTION_LOG.read_text().strip().split('\n'):
        if not line.strip(): continue
        try:
            e = json.loads(line)
            f = e.get("file", "")
            o = e.get("last_offset", 0)
            if f: processed[f] = e
        except: pass
    return processed

def extract_entities_from_session(content_text):
    """Extract entity mentions from session log text (human/assistant messages)."""
    entities = set()
    patterns = [
        r'(?:about|working\s+on|looking\s+at|investigating|researching|analyzing|debugging)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)',
        r'(?:mentioned|discussed|talked\s+about|referenced)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)',
        r'(?:using|running|testing|building|deploying)\s+([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)',
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, content_text):
            name = match.group(1).strip()
            if len(name) > 3 and len(name) < 80:
                entities.add(name)
    return list(entities)

def run_session_ingestion(conn):
    """Ingest unprocessed session logs into Chronicle."""
    print("\n=== Phase 2: Session Log Ingestion ===")
    processed = load_session_processed()
    print(f"  Previously processed session files: {len(processed)}")
    
    signals_created = 0
    candidates_created = 0
    files_scanned = 0
    entries_processed = 0
    entries_skipped = 0
    log_entries = []
    
    # Find unprocessed session files
    for sf_path in sorted(SESSIONS_DIR.glob("*.jsonl")):
        abs_path = str(sf_path)
        if abs_path in processed:
            continue
        # Skip background session files
        if sf_path.name.startswith("bg_"):
            continue
        
        files_scanned += 1
        
        # Read session content
        try:
            lines = sf_path.read_text().strip().split('\n')
        except Exception as e:
            print(f"  SKIP {sf_path.name}: {e}")
            continue
        
        file_sigs = 0
        file_cands = 0
        file_entries_processed = 0
        file_entries_skipped = 0
        
        # Process only human and assistant message entries
        for line in lines:
            if not line.strip(): continue
            try:
                entry = json.loads(line)
            except:
                file_entries_skipped += 1
                continue
            
            role = entry.get("role", "")
            content = entry.get("content", "")
            
            if role not in ("human", "assistant"):
                file_entries_skipped += 1
                continue
            if not content or not isinstance(content, str):
                file_entries_skipped += 1
                continue
            
            file_entries_processed += 1
            
            # Extract entities from this message
            entities = extract_entities_from_session(content)
            for ename in entities:
                entity = {"name": ename, "type": "Entity", "user_relevance": "user" if role == "human" else "unknown", "confidence": "medium"}
                try:
                    sid, name2, etype2, ur2, conf2 = create_signal(
                        conn, entity, "session", "SessionLog"
                    )
                    file_sigs += 1
                    create_candidate(conn, sid, ename, "Entity", entity["user_relevance"], "medium", "session")
                    file_cands += 1
                except Exception as e:
                    print(f"  Error creating entity '{ename}': {e}")
        
        signals_created += file_sigs
        candidates_created += file_cands
        entries_processed += file_entries_processed
        entries_skipped += file_entries_skipped
        
        log_entries.append(json.dumps({
            "file": abs_path,
            "ingested_at": _ts(),
            "last_offset": len(sf_path.read_bytes()),
            "signals_created": file_sigs,
            "entries_processed": file_entries_processed,
            "entries_skipped": file_entries_skipped
        }))
        
        if file_sigs > 0:
            print(f"  + {sf_path.name}: {file_sigs} signals, {file_cands} candidates ({file_entries_processed} entries)")
    
    if log_entries:
        with open(SESSION_INGESTION_LOG, 'a') as f:
            for entry in log_entries:
                f.write(entry + '\n')
    
    print(f"  Session files scanned: {files_scanned}")
    print(f"  Entries processed: {entries_processed}")
    print(f"  Entries skipped: {entries_skipped}")
    print(f"  Signals created: {signals_created}")
    print(f"  Candidates created: {candidates_created}")
    return signals_created, candidates_created

# ── Phase 3: Deep Consolidation ────────────────────────────────────────────
def run_deep_consolidation(conn):
    """Deep consolidation: promote user-relevant, resolve unknown, generate inferences."""
    print("\n=== Phase 3: Deep Consolidation ===")
    
    # 3a: Check pending candidates
    result = conn.execute("""
        MATCH (c:Candidate {status: 'pending'})
        RETURN c.user_relevance, count(c)
    """)
    pending_by_rel = {}
    for row in result:
        pending_by_rel[row[0]] = row[1]
    print(f"  Pending candidates by relevance: {pending_by_rel}")
    
    # 3b: Promote user-relevant candidates
    user_result = conn.execute("""
        MATCH (c:Candidate {status: 'pending', user_relevance: 'user'})
        RETURN c.id, c.proposed_type, c.proposed_data, c.confidence
    """)
    user_pending = [row for row in user_result]
    print(f"  Promotable (user-relevant): {len(user_pending)}")
    
    promoted = 0
    user_withheld = 0
    for row in user_pending:
        cand_id, proposed_type, proposed_data, conf = row
        if not is_promotable(conf):
            user_withheld += 1
            continue
        
        pdata = safe_json_loads(proposed_data)
        name = pdata.get("name", "")
        if not name:
            user_withheld += 1
            continue
        
        escaped_name = _esc(name)
        # Check for existing entity
        found = False
        for label in ("Entity", "Place", "Concept", "Thing"):
            try:
                r = conn.execute(f"""MATCH (e:{label}) WHERE e.name = '{escaped_name}' RETURN e.id LIMIT 1""")
                if [x for x in r]:
                    found = True
                    break
            except: pass
        
        if found:
            # Mark as promoted to existing
            try:
                conn.execute(f"""MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
                    SET c.status = 'promoted', c.resolved_at = '{_ts()}', c.resolved_reason = 'duplicate_of_existing'""")
                promoted += 1
            except Exception as e:
                print(f"  Error marking duplicate '{name}': {e}")
            continue
        
        try:
            ent_id = promote_candidate(conn, cand_id, proposed_type, pdata, "elephas-deep")
            promoted += 1
        except Exception as e:
            print(f"  Promotion error for '{name}': {e}")
    
    print(f"  Promoted: {promoted}")
    print(f"  User-relevant withheld (low conf or no name): {user_withheld}")
    
    # 3c: Resolve unknown-relevance candidates
    unknown_result = conn.execute("""
        MATCH (c:Candidate {status: 'pending', user_relevance: 'unknown'})
        RETURN c.id, c.proposed_data, c.confidence
    """)
    unknown_candidates = [row for row in unknown_result]
    print(f"  Unknown relevance candidates: {len(unknown_candidates)}")
    
    resolved_to_user = 0
    resolved_to_agent = 0
    for row in unknown_candidates:
        cand_id, proposed_data, conf = row
        pdata = safe_json_loads(proposed_data)
        name = pdata.get("name", "")
        if not name: continue
        
        # Check if entity name matches known user names in Chronicle
        # NOTE: Use exact match (=) not CONTAINS for duplicate detection.
        # CONTAINS causes false positives (e.g. "DuckDuckGo" inside "Google Brave DuckDuckGo Startpage")
        # and triggers Variant B bug where SET for duplicate doesn't persist.
        escaped_name = _esc(name)
        found_user_entity = False
        for label in ("Entity", "Place", "Concept", "Thing"):
            try:
                r = conn.execute(f"""MATCH (e:{label}) WHERE e.name = '{escaped_name}' RETURN e.id, e.name LIMIT 1""")
                for erow in r:
                    found_user_entity = True
                    break
            except: pass
        
        # Mark relevance based on existing entities
        if found_user_entity:
            try:
                conn.execute(f"""MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
                    SET c.user_relevance = 'user'""")
                resolved_to_user += 1
            except: pass
        else:
            try:
                conn.execute(f"""MATCH (c:Candidate {{id: '{_esc(cand_id)}'}})
                    SET c.user_relevance = 'agent_only'""")
                resolved_to_agent += 1
            except: pass
    
    print(f"  Resolved to 'user': {resolved_to_user}")
    print(f"  Resolved to 'agent_only': {resolved_to_agent}")
    
    # 3d: Generate inferences
    inference_result = conn.execute("MATCH (i:Inference) RETURN count(i)")
    inference_rows = [r for r in inference_result]
    pre_inference_count = inference_rows[0][0] if inference_rows else 0
    print(f"  Existing inferences: {pre_inference_count}")
    
    # Generate location-based inferences: Entities that share a Place
    location_results = conn.execute("""
        MATCH (e1:Entity)-[r:Relates]->(p:Place)
        WHERE r.relationship_type CONTAINS 'visits' OR r.relationship_type CONTAINS 'located_at'
        RETURN e1.name, p.name, r.relationship_type
        LIMIT 50
    """)
    loc_rows = [r for r in location_results]
    
    inference_count = pre_inference_count
    new_inferences = 0
    for row in loc_rows[:10]:
        entity_name, place_name, rel_type = row
        inf_id = _gen_id("inf")
        desc = f"Person {entity_name} has regular connection to {place_name}"
        try:
            conn.execute(f"""CREATE (i:Inference {{
                id: '{_esc(inf_id)}', inference_type: 'location_affinity',
                confidence: 'medium', supporting_nodes: '[]',
                description: '{_esc(desc)}', created_at: '{_ts()}'
            }})""")
            new_inferences += 1
        except Exception as e:
            print(f"  Inference error: {e}")
    
    print(f"  New inferences generated: {new_inferences}")
    print(f"  Total inferences: {pre_inference_count + new_inferences}")
    
    return promoted, resolved_to_user, resolved_to_agent, new_inferences

# ── Verification ────────────────────────────────────────────────────────────
def verify(conn):
    """Run verification queries."""
    print("\n=== Verification ===")
    queries = {
        "Entities": "MATCH (e:Entity) RETURN count(e)",
        "Places": "MATCH (p:Place) RETURN count(p)",
        "Concepts": "MATCH (c:Concept) RETURN count(c)",
        "Things": "MATCH (t:Thing) RETURN count(t)",
        "Active Signals": "MATCH (s:Signal {status: 'active'}) RETURN count(s)",
        "Pending Candidates": "MATCH (c:Candidate {status: 'pending'}) RETURN count(c)",
        "Promotable (user)": "MATCH (c:Candidate {status: 'pending', user_relevance: 'user'}) RETURN count(c)",
        "Agent-Only Pending": "MATCH (c:Candidate {status: 'pending', user_relevance: 'agent_only'}) RETURN count(c)",
        "Unknown Relevance": "MATCH (c:Candidate {status: 'pending', user_relevance: 'unknown'}) RETURN count(c)",
        "Promoted Candidates": "MATCH (c:Candidate {status: 'promoted'}) RETURN count(c)",
        "Relationships": "MATCH ()-[r]->() RETURN count(r)",
        "Inferences": "MATCH (i:Inference) RETURN count(i)",
        "Orphan Signals": """MATCH (s:Signal {status: 'active'})
            WHERE NOT EXISTS { MATCH (s)-[:Supports]->() }
            RETURN count(s)""",
    }
    status = {}
    for label, query in queries.items():
        try:
            rows = [r for r in conn.execute(query)]
            count = rows[0][0] if rows else 0
            status[label] = count
        except Exception as e:
            status[label] = f"ERROR: {e}"
    
    for k, v in status.items():
        print(f"  {k}: {v}")
    return status

# ── Journal ─────────────────────────────────────────────────────────────────
def write_journal(conn, memory_sigs, session_sigs, promoted, resolved_user, resolved_agent, inferences):
    journal_dir = AGENT_ROOT / "commons/journals/ocas-elephas"
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    journal_dir = journal_dir / today
    journal_dir.mkdir(parents=True, exist_ok=True)
    
    run_id = _gen_id("run")
    ts = _ts()
    
    journal = {
        "run_id": run_id,
        "journal_type": "DeepConsolidation",
        "skill": "ocas-elephas",
        "timestamp": ts,
        "decision": {
            "action": "deep_consolidation",
            "result": "completed",
            "payload": {
                "memory_signals_created": memory_sigs,
                "session_signals_created": session_sigs,
                "candidates_promoted": promoted,
                "relevance_resolved_to_user": resolved_user,
                "relevance_resolved_to_agent": resolved_agent,
                "inferences_generated": inferences,
                "entities_observed": 0
            }
        },
        "entities_observed": 0
    }
    
    journal_path = journal_dir / f"{run_id}.json"
    journal_path.write_text(json.dumps(journal, indent=2))
    print(f"\n  Journal written: {journal_path}")
    
    # Also write decision record
    if DECISIONS_LOG.parent.exists():
        decision = {
            "run_id": run_id,
            "skill": "ocas-elephas",
            "action": "deep_consolidation",
            "timestamp": ts,
            "result": "completed",
            "details": {
                "memory_signals": memory_sigs,
                "session_signals": session_sigs,
                "promoted": promoted,
                "relevance_resolved": resolved_user + resolved_agent,
                "inferences": inferences
            }
        }
        with open(DECISIONS_LOG, 'a') as f:
            f.write(json.dumps(decision) + '\n')

# ── Entry Point ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"Elephas Deep Consolidation — {_ts()}")
    print(f"DB: {DB_PATH}")
    
    conn = open_db()
    ensure_init(conn)
    
    # Phase 1: Memory Ingestion
    mem_sigs, mem_cands = run_memory_ingestion(conn)
    
    # Phase 2: Session Log Ingestion
    sess_sigs, sess_cands = run_session_ingestion(conn)
    
    # Phase 3: Deep Consolidation
    promoted, resolved_user, resolved_agent, inference_count = run_deep_consolidation(conn)
    
    # Verification
    status = verify(conn)
    
    # Journal
    write_journal(conn, mem_sigs, sess_sigs, promoted, resolved_user, resolved_agent, inference_count)
    
    conn.close()
    
    print("\n=== Summary ===")
    print(f"  Memory signals created: {mem_sigs}")
    print(f"  Session signals created: {sess_sigs}")
    print(f"  Total candidates promoted: {promoted}")
    print(f"  Relevance resolved (user): {resolved_user}")
    print(f"  Relevance resolved (agent): {resolved_agent}")
    print(f"  Inferences generated: {inference_count}")
    print(f"\nDone: {_ts()}")
