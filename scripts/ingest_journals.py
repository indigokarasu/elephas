#!/usr/bin/env python3
# elephas.ingest.journals — ingest structured signals from skill journal files
import sys, json, uuid, traceback, re
from pathlib import Path
from datetime import datetime, timezone

# ── paths ──────────────────────────────────────────────────────────────────
AGENT_ROOT       = Path.home() / '.hermes'
COMMONS_ROOT     = AGENT_ROOT / 'commons'
DB_DIR           = COMMONS_ROOT / 'db/ocas-elephas'
JOURNALS_DIR     = COMMONS_ROOT / 'journals'
STAGING          = DB_DIR / 'staging'
INGESTION_LOG    = DB_DIR / 'ingestion_log.jsonl'
CONFIG_PATH      = DB_DIR / 'config.json'
ELEPHAS_JOURNALS = COMMONS_ROOT / 'journals/ocas-elephas'

# ── db access ───────────────────────────────────────────────────────────────
sys.path.insert(0, str(AGENT_ROOT / 'hermes-agent' / 'venv' / 'lib' / 'python3.11' / 'site-packages'))
import real_ladybug as lb

DB_PATH = DB_DIR / 'chronicle.lbug'

def _open_db(read_only=False):
    DB_DIR.mkdir(parents=True, exist_ok=True)
    (DB_DIR / 'intake').mkdir(parents=True, exist_ok=True)
    (DB_DIR / 'intake' / 'processed').mkdir(parents=True, exist_ok=True)
    STAGING.mkdir(parents=True, exist_ok=True)
    ELEPHAS_JOURNALS.mkdir(parents=True, exist_ok=True)
    _ensure_config()
    db = lb.Database(str(DB_PATH), read_only=read_only)
    conn = lb.Connection(db)
    if not read_only:
        _ensure_init(conn)
    return db, conn

def _ensure_config():
    if CONFIG_PATH.exists():
        return
    now = datetime.now(timezone.utc).isoformat()
    config = {
        'skill_id': 'ocas-elephas', 'skill_version': '3.1.0', 'config_version': '2',
        'created_at': now, 'updated_at': now,
        'consolidation': {'immediate_interval_minutes': 15, 'deep_interval_hours': 24},
        'identity': {'auto_merge_threshold': 0.90, 'flag_review_threshold': 0.70},
        'inference': {'enabled': True, 'min_supporting_nodes': 3},
        'retention': {'days': 0},
        'memory_ingestion': {'enabled': True, 'cadence': 'deep'},
        'session_log_ingestion': {'enabled': True, 'cadence': 'deep',
                                  'entry_types': ['message'], 'roles': ['user', 'assistant']},
        'signal_normalization': {'enabled': True, 'log_conversions': True, 'requeue_errors_on_enable': True}
    }
    CONFIG_PATH.write_text(json.dumps(config, indent=2))

def _ensure_init(conn):
    tables = {row[1] for row in conn.execute('CALL show_tables() RETURN *')}
    if 'Entity' not in tables:
        _run_ddl(conn)

def _run_ddl(conn):
    stmts = [
        'CREATE NODE TABLE Entity (id STRING PRIMARY KEY, name STRING, entity_type STRING, aliases STRING, identifiers STRING, possible_matches STRING, merge_history STRING, identity_state STRING, source_skill STRING, record_time STRING)',
        'CREATE NODE TABLE Place (id STRING PRIMARY KEY, name STRING, place_type STRING, coordinates STRING, address STRING, source_skill STRING, record_time STRING)',
        'CREATE NODE TABLE Concept (id STRING PRIMARY KEY, name STRING, description STRING, concept_type STRING, event_time STRING, source_skill STRING, record_time STRING)',
        'CREATE NODE TABLE Thing (id STRING PRIMARY KEY, name STRING, thing_type STRING, metadata STRING, source_skill STRING, record_time STRING)',
        'CREATE NODE TABLE Signal (id STRING PRIMARY KEY, source_skill STRING, source_type STRING, source_journal_type STRING, payload STRING, user_relevance STRING, timestamp STRING, status STRING)',
        'CREATE NODE TABLE Candidate (id STRING PRIMARY KEY, proposed_type STRING, proposed_data STRING, supporting_signals STRING, confidence STRING, user_relevance STRING, status STRING, created_at STRING, resolved_at STRING, resolved_reason STRING)',
        'CREATE NODE TABLE Inference (id STRING PRIMARY KEY, inference_type STRING, confidence STRING, supporting_nodes STRING, description STRING, created_at STRING)',
        'CREATE REL TABLE Relates (FROM Entity TO Entity, FROM Entity TO Concept, FROM Entity TO Place, FROM Entity TO Thing, FROM Concept TO Place, FROM Concept TO Concept, relationship_type STRING, evidence_refs STRING, confidence STRING, event_time STRING, record_time STRING, valid_from STRING, valid_until STRING)',
        'CREATE REL TABLE Supports (FROM Signal TO Candidate)',
        'CREATE REL TABLE Promotes (FROM Candidate TO Entity, FROM Candidate TO Place, FROM Candidate TO Concept, FROM Candidate TO Thing)',
        'CREATE REL TABLE Infers (FROM Inference TO Entity, FROM Inference TO Concept, FROM Inference TO Place)',
    ]
    for s in stmts:
        conn.execute(s)

# ── helpers ─────────────────────────────────────────────────────────────────
def clean_payload(payload):
    if not isinstance(payload, dict):
        return payload
    cleaned = {}
    for k, v in payload.items():
        if isinstance(v, list) and len(v) == 0:
            continue
        if v == '' or v is None:
            continue
        if isinstance(v, dict):
            cleaned[k] = clean_payload(v)
        else:
            cleaned[k] = v
    return cleaned

def parse_repr_payload(text):
    if not text: return {}
    text = text.strip()
    if not (text.startswith('{') and text.endswith('}')): return {}
    result = {}
    inner = text[1:-1]
    pairs = []
    key = ''
    val = ''
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
            key = ''
            val = ''
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

def extract_name(entity):
    if isinstance(entity, dict):
        if entity.get('name'):
            return entity['name']
        if entity.get('description'):
            return entity['description']
        ev = entity.get('entity', '')
        if ev and '/' in ev:
            return ev.split('/')[-1]
        return ev or 'unknown'
    return str(entity) if entity else 'unknown'

def esc(s):
    return str(s).replace('\\', '\\\\').replace('\u0000', '').replace('\r', '')

def _load_ingestion_log():
    if not INGESTION_LOG.exists():
        return set()
    paths = set()
    for line in INGESTION_LOG.read_text().splitlines():
        try:
            e = json.loads(line)
            paths.add(e.get('journal_path', ''))
        except Exception:
            pass
    return paths

def _clean_stale_log_entries():
    if not INGESTION_LOG.exists():
        return
    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    kept = []
    for line in INGESTION_LOG.read_text().splitlines():
        try:
            e = json.loads(line)
            sc = e.get('signals_created', 0)
            ingested_at = e.get('ingested_at', '')
            if not (sc == 0 and now_str in ingested_at):
                kept.append(line)
        except Exception:
            kept.append(line)
    INGESTION_LOG.write_text('\n'.join(kept) + '\n')

def _normalize_signal(sig, source_skill):
    has_id = 'id' in sig and 'signal_id' not in sig
    has_legacy_id = 'signal_id' in sig and 'id' not in sig

    if has_id:
        return sig, None

    if has_legacy_id:
        converted = dict(sig)
        old_id = converted.pop('signal_id')
        if not old_id.startswith('sig_'):
            old_id = 'sig_' + old_id
        converted['id'] = old_id
        if 'signal_type' in converted:
            st = converted.pop('signal_type').lower()
            mapping = {'observation': 'Observation', 'action': 'Action', 'research': 'Research'}
            converted['source_journal_type'] = mapping.get(st, st.capitalize())
        if 'provenance' in converted:
            prov = converted.pop('provenance')
            if isinstance(prov, dict):
                ss = prov.get('source_system', '')
                if ss == 'google_workspace': ss = 'ocas-bower'
                elif ss == 'social_graph': ss = 'ocas-weave'
                elif ss == 'web_research': ss = 'ocas-sift'
                elif ss == 'osint': ss = 'ocas-scout'
                elif ss and not ss.startswith('legacy:'): ss = 'legacy:' + ss
                converted['source_skill'] = ss
        if 'payload' in converted and isinstance(converted['payload'], dict):
            if 'concept_type' in converted['payload']:
                converted['payload']['proposed_type'] = converted['payload'].pop('concept_type')
        converted['source_type'] = converted.get('source_type', 'journal')
        converted['user_relevance'] = converted.get('user_relevance', 'unknown')
        converted['status'] = converted.get('status', 'active')
        norm_from = {
            'format': 'legacy', 'original_id': str(old_id),
            'converted_at': datetime.now(timezone.utc).isoformat(),
            'fields_mapped': ['signal_id', 'signal_type', 'provenance.source_system', 'payload.concept_type'],
            'fields_preserved': ['salience', 'confidence', 'source_ref', 'provenance']
        }
        converted['_normalized_from'] = norm_from
        return converted, old_id

    return None, None

def parse_payload(payload_str):
    try:
        return json.loads(payload_str)
    except (json.JSONDecodeError, TypeError):
        return parse_repr_payload(str(payload_str))

def write_signal(conn, sig_id, skill_name, source_type, source_journal_type, payload, user_relevance, timestamp):
    payload = clean_payload(payload)
    try:
        pl_str = json.dumps(payload)
    except Exception:
        pl_str = json.dumps({'raw': str(payload)})

    conn.execute('''
        MERGE (s:Signal {id: $id})
        SET s.source_skill = $ss, s.source_type = $st,
            s.source_journal_type = $sjt, s.payload = $pl,
            s.user_relevance = $ur, s.timestamp = $ts, s.status = $status
    ''', {'id': sig_id, 'ss': esc(skill_name), 'st': esc(source_type),
          'sjt': esc(source_journal_type), 'pl': pl_str,
          'ur': esc(user_relevance), 'ts': esc(timestamp), 'status': 'active'})

def upsert_candidate(conn, name, proposed_type, entity_type, sig_id, user_relevance, confidence):
    rows = list(conn.execute(
        'MATCH (c:Candidate {status: $st}) WHERE c.proposed_data CONTAINS $nm RETURN c.id',
        {'st': 'pending', 'nm': esc(name[:30])}
    ))
    if rows:
        cand_id = rows[0][0]
        # Update existing candidate
        existing_data = list(conn.execute(
            'MATCH (c:Candidate {id: $id}) RETURN c.proposed_data, c.supporting_signals, c.confidence, c.user_relevance',
            {'id': cand_id}
        ))
        if existing_data:
            try:
                old_data = json.loads(existing_data[0][0] or '{}')
                old_sigs = json.loads(existing_data[0][1] or '[]')
                old_conf = existing_data[0][2] or 'low'
                old_rel = existing_data[0][3] or 'unknown'
            except (json.JSONDecodeError, TypeError):
                old_data = {'name': name}
                old_sigs = []
                old_conf = 'low'
                old_rel = 'unknown'

            if sig_id not in old_sigs:
                old_sigs.append(sig_id)
            new_conf = _boost_confidence(old_conf, confidence)
            new_rel = _upgrade_relevance(old_rel, user_relevance)
            conn.execute('''
                MATCH (c:Candidate {id: $id})
                SET c.supporting_signals = $ss, c.confidence = $conf, c.user_relevance = $rel
            ''', {'id': cand_id, 'ss': json.dumps(old_sigs), 'conf': esc(new_conf), 'rel': esc(new_rel)})
        return cand_id, False
    else:
        cand_id = 'cand_' + uuid.uuid4().hex[:7]
        now = datetime.now(timezone.utc).isoformat()
        conn.execute('''
            MERGE (c:Candidate {id: $id})
            SET c.proposed_type = $pt, c.proposed_data = $pd,
                c.supporting_signals = $ss, c.confidence = $conf,
                c.user_relevance = $ur, c.status = $st, c.created_at = $ca
        ''', {'id': cand_id, 'pt': esc(proposed_type),
              'pd': json.dumps({'name': name, 'type': entity_type}),
              'ss': json.dumps([sig_id]), 'conf': esc(confidence),
              'ur': esc(user_relevance), 'st': 'pending', 'ca': now})
        return cand_id, True

def link_signal_candidate(conn, sig_id, cand_id):
    conn.execute('''
        MATCH (s:Signal {id: $sid}), (c:Candidate {id: $cid})
        CREATE (s)-[:Supports]->(c)
    ''', {'sid': sig_id, 'cid': esc(cand_id)})

def _boost_confidence(existing, new):
    order = {'low': 0, 'med': 1, 'high': 2}
    e = order.get(existing, 0)
    n = order.get(new, 0)
    best = max(e, n)
    return ['low', 'med', 'high'][best]

def _upgrade_relevance(existing, new):
    order = {'agent_only': 0, 'unknown': 1, 'user': 2}
    e = order.get(existing, 0)
    n = order.get(new, 0)
    best = max(e, n)
    return ['agent_only', 'unknown', 'user'][best]

# ── main ────────────────────────────────────────────────────────────────────
def main():
    _clean_stale_log_entries()
    db, conn = _open_db()

    run_id = 'r_' + uuid.uuid4().hex[:7]
    ts_start = datetime.now(timezone.utc).isoformat()

    processed_paths = _load_ingestion_log()
    all_journal_files = []

    for skill_dir in sorted(JOURNALS_DIR.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith('.'):
            continue
        if skill_dir.name == 'ocas-elephas':
            continue
        for date_dir in sorted(skill_dir.iterdir()):
            if not date_dir.is_dir() or not re.match(r'\d{4}-\d{2}-\d{2}', date_dir.name):
                continue
            for jfile in sorted(date_dir.glob('*.json')):
                if str(jfile) not in processed_paths:
                    all_journal_files.append(jfile)

    signals_created = 0
    candidates_created = 0
    journals_ingested = 0
    errors = []

    for jfile in all_journal_files:
        skill_name = jfile.parent.parent.name
        journal_type_str = 'Observation'

        try:
            raw = jfile.read_text()
            journal_data = json.loads(raw)
        except Exception as e:
            errors.append({'file': str(jfile), 'error': str(e)})
            continue

        # Ensure journal_data is a dict
        if not isinstance(journal_data, dict):
            errors.append({'file': str(jfile), 'error': 'Not a dict after parse'})
            continue

        # Detect journal type from content
        journal_type_str = 'Observation'
        try:
            decision = journal_data.get('decision', {})
            if isinstance(decision, dict):
                if decision.get('decision_type') == 'research':
                    journal_type_str = 'Research'
            if 'action' in journal_data and isinstance(journal_data.get('action'), dict):
                journal_type_str = 'Action'
        except Exception:
            pass

        # Extract entities_observed from top-level or decision.payload
        entities = journal_data.get('entities_observed', [])
        if not isinstance(entities, list):
            entities = []
        if not entities and 'decision' in journal_data:
            dec = journal_data.get('decision')
            if isinstance(dec, dict):
                entities = dec.get('payload', {}).get('entities_observed', [])

        relationships = journal_data.get('relationships_observed', [])
        if not isinstance(relationships, list):
            relationships = []
        if not relationships and 'decision' in journal_data:
            dec = journal_data.get('decision')
            if isinstance(dec, dict):
                relationships = dec.get('payload', {}).get('relationships_observed', [])

        preferences = journal_data.get('preferences_observed', [])
        if not isinstance(preferences, list):
            preferences = []
        if not preferences and 'decision' in journal_data:
            dec = journal_data.get('decision')
            if isinstance(dec, dict):
                preferences = dec.get('payload', {}).get('preferences_observed', [])

        sig_count_this_file = 0

        # Extract signal from journal payload (signal field)
        signal_data = None
        try:
            sd = journal_data.get('signal')
            if sd and isinstance(sd, dict):
                signal_data = sd
            else:
                dec = journal_data.get('decision')
                if isinstance(dec, dict):
                    sd2 = dec.get('payload', {}).get('signal')
                    if sd2 and isinstance(sd2, dict):
                        signal_data = sd2
        except Exception:
            pass
        if signal_data and isinstance(signal_data, dict):
            sig, orig_id = _normalize_signal(signal_data, skill_name)
            if sig:
                sig_id = sig.get('id', 'sig_' + uuid.uuid4().hex[:7])
                sig.setdefault('source_skill', skill_name)
                sig.setdefault('source_type', 'journal')
                sig.setdefault('source_journal_type', journal_type_str)
                sig.setdefault('user_relevance', sig.get('user_relevance', 'unknown'))
                sig.setdefault('status', 'active')
                sig.setdefault('timestamp', datetime.now(timezone.utc).isoformat())

                payload = sig.get('payload', {})
                if isinstance(payload, str):
                    parsed = parse_payload(payload)
                    payload = parsed if parsed else {'raw': payload}

                write_signal(conn, sig_id, skill_name, 'journal', journal_type_str,
                           payload, sig.get('user_relevance', 'unknown'),
                           sig.get('timestamp', datetime.now(timezone.utc).isoformat()))
                sig_count_this_file += 1

        # Process entities_observed
        for entity in (entities or []):
            if isinstance(entity, str):
                entity = {'name': entity, 'type': 'Entity/Person'}
            elif not isinstance(entity, dict):
                continue

            ent_name = extract_name(entity)
            if not ent_name or ent_name == 'unknown':
                continue

            entity_type_ref = entity.get('type', entity.get('entity_type', 'Person'))
            parts = entity_type_ref.split('/')
            proposed_type = parts[0] if parts else 'Entity'
            ent_type = parts[1] if len(parts) >= 2 else (parts[0] if parts else 'Person')

            user_rel = entity.get('user_relevance', 'unknown')
            confidence = entity.get('confidence', 'low')

            sig_id = 'sig_' + uuid.uuid4().hex[:7]
            payload = clean_payload({
                'name': ent_name, 'entity_type': ent_type,
                'proposed_type': proposed_type, 'confidence': confidence,
                'identifiers': entity.get('identifiers', []),
                'description': entity.get('description', entity.get('observation', ''))
            })

            write_signal(conn, sig_id, skill_name, 'journal', journal_type_str,
                        payload, user_rel, datetime.now(timezone.utc).isoformat())

            cand_id, is_new = upsert_candidate(conn, ent_name, proposed_type, entity_type_ref,
                                                sig_id, user_rel, confidence)
            link_signal_candidate(conn, sig_id, cand_id)

            if is_new:
                candidates_created += 1
            sig_count_this_file += 1

        signals_created += sig_count_this_file

        # Log processed file
        with open(INGESTION_LOG, 'a') as f:
            f.write(json.dumps({
                'run_id': run_id, 'source_skill': skill_name, 'source_type': 'journal',
                'journal_path': str(jfile), 'journal_type': journal_type_str,
                'signals_created': sig_count_this_file, 'candidates_created': 0,
                'ingested_at': datetime.now(timezone.utc).isoformat()
            }) + '\n')
        journals_ingested += 1

    ts_end = datetime.now(timezone.utc).isoformat()

    # Write action journal
    date_str = ts_end[:10]
    journal_dir = ELEPHAS_JOURNALS / date_str
    journal_dir.mkdir(parents=True, exist_ok=True)
    journal_path = journal_dir / f'{run_id}.json'

    entry = {
        'run_identity': {
            'comparison_group_id': 'cg_' + uuid.uuid4().hex[:7],
            'run_id': run_id, 'role': 'champion',
            'skill_name': 'ocas-elephas', 'skill_version': '3.1.0',
            'timestamp_start': ts_start, 'timestamp_end': ts_end,
            'journal_spec_version': '1.3', 'journal_type': 'action'
        },
        'input': {
            'normalized_input_hash': '', 'input_schema_version': '1.0',
            'context_tokens': 0, 'command': 'elephas.ingest.journals',
            'journals_scanned': len(all_journal_files),
            'signals_found': signals_created
        },
        'decision': {
            'decision_type': 'ingestion',
            'payload': {
                'journals_scanned': len(all_journal_files),
                'journals_ingested': journals_ingested,
                'signals_created': signals_created,
                'candidates_created': candidates_created,
                'errors': len(errors)
            },
            'confidence': 1.0,
            'reasoning_summary': f'Ingested {journals_ingested} journals, created {signals_created} signals, {candidates_created} candidates'
        },
        'action': {
            'side_effect_intent': 'chronicle_write', 'side_effect_executed': True,
            'external_reference': None
        },
        'artifacts': [],
        'metrics': {
            'latency_ms': 0, 'retry_count': 0, 'validation_failures': 0,
            'context_tokens_used': 0, 'records_written': signals_created,
            'records_skipped': len(all_journal_files) - journals_ingested,
            'records_failed': len(errors)
        },
        'okr_evaluation': {'success_rate': 1.0 if not errors else 0.0, 'reliability_score': 1.0 if not errors else 0.0}
    }

    tmp = journal_path.with_suffix('.tmp')
    tmp.write_text(json.dumps(entry, indent=2))
    tmp.rename(journal_path)

    print(f'elephas.ingest.journals: journals={journals_ingested} signals={signals_created} candidates={candidates_created} errors={len(errors)}')
    if errors:
        for e in errors[:5]:
            print(f'  ERROR: {e}')

    return journals_ingested, signals_created, candidates_created

if __name__ == '__main__':
    main()
