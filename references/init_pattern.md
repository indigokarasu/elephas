# Elephas Initialization Pattern

Use this pattern when implementing `_open_db` for Elephas. The database auto-initializes on first use — no manual init command is needed.

```python
import real_ladybug as lb
from pathlib import Path
import json
from datetime import datetime, timezone

ROOT = Path("{agent_root}/commons").expanduser()
DB_PATH = ROOT / "db/ocas-elephas/chronicle.lbug"
STAGING = ROOT / "db/ocas-elephas/staging"
JOURNALS = ROOT / "journals/ocas-elephas"
CONFIG_PATH = ROOT / "db/ocas-elephas/config.json"
WORKSPACE = Path("{agent_root}/workspace").expanduser()
SESSIONS_ROOT = Path("{agent_root}/agents").expanduser()

def _open_db(read_only=False):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    INTAKE.mkdir(parents=True, exist_ok=True)
    (INTAKE / "processed").mkdir(parents=True, exist_ok=True)
    STAGING.mkdir(parents=True, exist_ok=True)
    JOURNALS.mkdir(parents=True, exist_ok=True)
    _ensure_config()
    db = lb.Database(str(DB_PATH), read_only=read_only)
    conn = lb.Connection(db)
    if not read_only:
        _ensure_init(conn)
    return db, conn

def _ensure_init(conn):
    tables = {row[0] for row in conn.execute("CALL show_tables() RETURN *")}
    if "Entity" not in tables:
        _run_ddl(conn)

def _run_ddl(conn):
    # Full DDL in references/schemas.md
    pass
```

Full schema DDL is in `references/schemas.md`.

## LadybugDB API notes

- `CALL show_tables()` returns numeric table IDs, not string names. To check if a table exists, query it directly (e.g., `MATCH (e:Entity) RETURN count(e)`) and catch exceptions, rather than relying on string matching in `show_tables()` output.
- Node and relationship counts: use `MATCH (n:Label) RETURN count(n)` for each label. The `show_tables()` call is only useful for confirming the database file is open.
- When writing Signals, Candidates, or entities, always use `MERGE` on the primary key (`id` field) to avoid duplicates on re-ingestion.
- `real_ladybug` Python module is available at runtime. Import as `import real_ladybug as lb`. Use `lb.Database(path, read_only=False)` for writes, `lb.Database(path, read_only=True)` for reads.
- **Cypher string literals must use single quotes**: `MERGE (n:Entity {id: 'e1', name: 'Jane'})` works, but double quotes cause Python syntax errors when the Cypher string itself is in double quotes. Always use single quotes for Cypher string values. In Python, wrap the Cypher query in double quotes: `conn.execute("MERGE (n:Entity {id: 'e1', name: 'Jane'})")`.
- `show_tables()` returns rows as `[table_id, table_name, table_type, schema_name, '']`. The table name is at index 1. String-matching on table names works with index 1.
