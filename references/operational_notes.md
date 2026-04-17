# Operational Notes

Production lessons from real Elephas runs. These override or supersede anything in the main SKILL.md that proves incorrect in practice.

---

## Journals directory: correct path vs. staging script

The `staging/elephas_immediate.py` script hard-codes the wrong journals path:

```
JOURNALS_ROOT = hermes_BASE / "journals"   # WRONG
JOURNALS_ROOT = hermes_BASE / "commons/journals"   # CORRECT
```

Actual skill journals live under `~/.hermes/commons/journals/`, not `~/.hermes/journals/`.

The `hermes-elephas` skill's own journals ARE under `~/.hermes/journals/hermes-elephas/` — but no other skill writes there. All OCAS skills write to `commons/journals/{skill-name}/`.

**Workaround:** When running ingest manually, point to `commons/journals/`. The staging script will be fixed in a future update.

---

## Journal ingestion log: write-after-extract, not before

The staging script logs journal entries to `ingestion_log.jsonl` **before** extracting signals from those journals. This means a journal file gets marked as "ingested" (with `signals_created: 0`) even if it contains entities that weren't extracted due to a code bug.

**Symptom:** `ingestion_log.jsonl` shows entries with `signals_created: 0`, but the journals actually contained `entities_observed`. The script skips re-processing those files on the next run because they're already in the log.

**Fix:** Truncate the ingestion log back to the last entry with `signals_created > 0` before re-running. Keep entries where `source_type != 'journal'` or `signals_created > 0`.

```python
# Remove bad entries: journal entries with 0 signals (pre-mature logging)
lines = ilog_path.read_text().splitlines()
good = [l for l in lines if not (json.loads(l).get('source_type') == 'journal'
                                   and json.loads(l).get('signals_created', 0) == 0)]
ilog_path.write_text('\n'.join(good) + '\n')
```

---

## Signal payload: Python dict literals vs. JSON

A manually-created test signal had its payload stored as a Python dict literal (e.g., `{name: Alice Johnson, type: Person}`) instead of valid JSON. `json.loads()` and `ast.literal_eval()` both fail on this format.

**Parser:**

```python
def parse_python_dict_literal(s):
    """Parse {key: value, ...} Python dict literal to Python dict."""
    s = s.strip()
    if not (s.startswith('{') and s.endswith('}')):
        return {}
    s = s[1:-1]
    parts = []
    depth = 0
    current = ''
    for ch in s:
        if ch in '{[':
            depth += 1
            current += ch
        elif ch in '}]':
            depth -= 1
            current += ch
        elif ch == ',' and depth == 0:
            parts.append(current.strip())
            current = ''
        else:
            current += ch
    if current.strip():
        parts.append(current.strip())
    result = {}
    for part in parts:
        try:
            colon_idx = part.index(':')
        except ValueError:
            continue
        key = part[:colon_idx].strip().strip('"\'')
        val = part[colon_idx+1:].strip()
        if val.startswith('{') or val.startswith('['):
            try:
                val = json.loads(val.replace("'", '"'))
            except:
                val = val.strip('"\'')
        else:
            val = val.strip('"\'')
        result[key] = val
    return result
```

---

## LadybugDB: Supports edge — no timestamp property

The `Supports` relationship table does not have a `timestamp` property in its schema. Creating an edge with `SET e.timestamp = $ts` fails with:

```
Binder exception: Cannot find property timestamp for e.
```

**Fix:** Create the edge without the timestamp property:

```cypher
CREATE (s)-[e:Supports]->(c)
```

Do NOT attempt to set edge properties not defined in the schema.

---

## LadybugDB: Candidate node — no `name` property

The `Candidate` node table does not have a `name` property. Using `CREATE (c:Candidate {id: $id, name: $name})` fails with:

```
Binder exception: Cannot find property name for c.
```

**Fix:** Use only schema-defined properties for initial `CREATE`:

```cypher
CREATE (c:Candidate {
    id: $id, proposed_type: $pt, proposed_data: $pd,
    supporting_signals: $ss, confidence: $cf,
    user_relevance: $rel, status: 'pending',
    created_at: $now, resolved_at: '', resolved_reason: ''
})
```

Then `SET` additional fields via `MATCH (c:Candidate {id: $id}) SET ...` in a separate query.

---

## LadybugDB: CREATE + SET pattern (no multi-line SET with params)

LadybugDB's Cypher parser fails when a SET clause spans multiple lines or has 3+ fields using `$param` notation:

```
RuntimeError: Parser exception: Invalid input ... expected rule oC_SingleQuery
```

**Workaround — two-phase create + inline SET:**

```python
# Phase 1: CREATE with only id and name (the required fields)
conn.execute(f"CREATE (n:{node_type} {{id: '{node_id}', name: '{escape(name)}'}})")

# Phase 2: SET remaining fields using inline literals (no $param)
conn.execute(f"MATCH (c:Concept {{id: '{node_id}'}}) SET c.description = '{desc}', c.concept_type = '{ct}', c.event_time = '', c.source_skill = 'ocas-elephas', c.record_time = '{NOW}'")
```

Inline literals must have single quotes escaped as `''`. JSON array strings (`identifiers`, `supporting_signals`) must also use inline literals, not `$param` — the parameter layer strips inner quotes from JSON.

## LadybugDB: proposed_data format (Python repr, not JSON)

Some candidates have `proposed_data` stored as Python repr — single-quoted keys without JSON double-quotes:

```
'{name: ollama-provider, proposed_type: Entity, entity_type: AI, confidence: med}'
```

`json.loads()` fails on this. `ast.literal_eval()` also fails because unquoted keys like `name` are treated as Python variables.

**Parser — handle both JSON and LadybugDB map format:**

```python
def parse_payload(pd):
    if not pd or not isinstance(pd, str):
        return {"name": "unknown"}
    # Try JSON first
    try:
        return json.loads(pd)
    except (json.JSONDecodeError, TypeError):
        pass
    # LadybugDB map: {key: value, key: value} — keys are unquoted
    if pd.startswith('{') and not pd.startswith('{"'):
        result = {}
        pattern = r'(\w+):\s*'
        matches = list(re.finditer(pattern, pd))
        for i, m in enumerate(matches):
            key = m.group(1)
            start = m.end()
            end = matches[i+1].start() if i+1 < len(matches) else len(pd)
            value = pd[start:end].strip().rstrip(',').strip()
            result[key] = value
        return result
    return {"name": str(pd)[:50]}
```

## LadybugDB: supported_signals JSON string

LadybugDB can store `supporting_signals` as a Python list repr that `json.loads()` rejects. Use:

```python
def parse_ss(ss_str):
    if not ss_str: return []
    try: return json.loads(ss_str)
    except:
        try: return ast.literal_eval(ss_str)
        except: return []
```

## LadybugDB: Signal payload — empty lists and empty strings cause "ANY type" errors

Storing a JSON payload containing an empty list `[]` or empty string `""` on a Signal node throws:

```
RuntimeError: Runtime exception: Trying to a create a vector with ANY type.
Data type is expected to be resolved during binding.
```

This affects both `source_refs: []`, `notes: ""`, and similar fields.

**Fix:** Clean all payloads before writing — strip `""`, `None`, and empty lists recursively:

```python
def clean_payload(payload):
    if not isinstance(payload, dict):
        return payload
    result = {}
    for k, v in payload.items():
        if v == "" or v is None:
            continue
        if isinstance(v, dict):
            cleaned_v = clean_payload(v)
            if cleaned_v:           # skip {}
                result[k] = cleaned_v
        elif isinstance(v, list):
            cleaned_list = []
            for item in v:
                if isinstance(item, dict):
                    ci = clean_payload(item)
                    if ci: cleaned_list.append(ci)
                elif item != "" and item is not None:
                    cleaned_list.append(item)
            if cleaned_list:         # skip [] — THIS IS THE KEY FIX
                result[k] = cleaned_list
        else:
            result[k] = v
    return result
```

**Always apply `clean_payload` before `json.dumps()` when writing Signal payloads.**

---

## `show_tables()` column order

`CALL show_tables() RETURN *` returns `[table_id, table_name, table_type, graph_name, comment]`. The table name is at index **1**, not index 0.

---

## Journal signals: most journals have none

Of ~199 journal files scanned, only 2 contained `entities_observed` in their decision payloads. The vast majority are empty for this field. This is normal — most skills don't observe entities on every run.

Only two journals had `entities_observed`:
- `ocas-custodian/2026-04-15/escalation-20260415-161942.json` — 2 entities (both `agent_only`)
- `ocas-vesper/2026-04-14/run-074309.json` — 9 entities (all `user` relevance)

---

## Critical: Signal payload format (repr, not JSON)

Chronicle stores Signal and Candidate payload fields (`Signal.payload`, `Candidate.proposed_data`, `Candidate.supporting_signals`) as **Python repr format strings**, NOT JSON. Example:

```
{name: Indigo Karasu, type: Person, confidence: high, source_refs: [https://github.com/indigokarasu], resolved_handles: {github: indigokarasu, bluesky: @indigokarasu.bsky.social}}
```

When reading payloads back from Chronicle, `json.loads()` will fail silently or raise `JSONDecodeError`. Always use a repr parser:

```python
def parse_repr_payload(text):
    """Parse Python repr format: {key: value, key: value}"""
    if not text: return {}
    text = text.strip()
    if not text.startswith('{') or not text.endswith('}'): return {}
    result = {}
    inner = text[1:-1]
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
```

Also parse repr-format lists (for `supporting_signals` which stores `['sig_xxx', 'sig_yyy']`):

```python
def parse_repr_list(text):
    """Parse repr format list like ['a', 'b', 'c']"""
    if not text: return []
    text = text.strip()
    if not text.startswith('[') or not text.endswith(']'): return []
    inner = text[1:-1]
    result = []; current = ""; depth = 0; in_str = False; str_char = None; i = 0
    while i < len(inner):
        c = inner[i]
        if c in ("'", '"') and not in_str:
            in_str = True; str_char = c
        elif c == str_char and in_str:
            in_str = False; str_char = None
        elif c == ',' and depth == 0 and not in_str:
            result.append(current.strip()); current = ""
        else:
            if c == '[': depth += 1
            elif c == ']': depth -= 1
            current += c
        i += 1
    if current.strip(): result.append(current.strip())
    return result
```

When writing payloads, convert dict to repr format:

```python
def dict_to_repr(d):
    """Convert dict to Python repr format string"""
    parts = []
    for k, v in d.items():
        if isinstance(v, list):
            list_str = "[" + ", ".join(str(x) for x in v) + "]"
            parts.append(f"{k}: {list_str}")
        elif isinstance(v, dict):
            inner = ", ".join(f"{kk}: {vv}" for kk, vv in v.items())
            parts.append(f"{k}: {{{inner}}}")
        else:
            parts.append(f"{k}: {v}")
    return "{" + ", ".join(parts) + "}"
```

## Critical: decision.payload can be a string, not a dict

When iterating journal entries, `journal_data.get("decision", {}).get("payload", {}).get("entities_observed", [])` will throw `AttributeError: 'str' object has no attribute 'get'` if `decision.payload` is a string (not a dict). This happens in some journal formats.

Always guard with isinstance checks:

```python
decision = journal_data.get("decision")
entities = journal_data.get("entities_observed", [])
if isinstance(decision, dict):
    payload = decision.get("payload", {})
    if isinstance(payload, dict):
        entities.extend(payload.get("entities_observed", []))
```

## Entity observation field name variations

The `entities_observed` payload format varies across skills:
- `entity` (string) vs `name` (string) — use `name` for display, `entity` for type info
- `type` — may be `"agent_only"` (relevance flag) or `"Entity/Person"` (ontology type)
- `user_relevance` — explicitly set by emitting skill; use this over inferred relevance

When extracting:
```python
entity_name = pd.get('name', pd.get('entity', 'unknown'))
proposed_type = pd.get('proposed_type', pd.get('entity_type', pd.get('type', 'Entity')))
relevance = entity.get('user_relevance', 'unknown')  # from entity dict, not sig
```
