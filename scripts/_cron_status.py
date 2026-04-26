#!/usr/bin/env python3
"""Quick Chronicle status check for cron run."""
import real_ladybug as lb
from pathlib import Path

DB = Path("/root/.hermes/commons/db/ocas-elephas/chronicle.lbug")
assert DB.exists(), f"DB not found: {DB}"

db = lb.Database(str(DB))
conn = lb.Connection(db)

# Tables
tables = [r[1] for r in conn.execute("CALL show_tables() RETURN *")]
print(f"Tables: {','.join(tables)}")

# Nodes
for label in ["Entity", "Place", "Concept", "Thing"]:
    r = [r for r in conn.execute(f"MATCH (n:{label}) RETURN count(n)")]
    print(f"{label}: {r[0][0]}")

# Signals
r = [r for r in conn.execute("MATCH (s:Signal) RETURN count(s)")]
print(f"Total signals: {r[0][0]}")
r_a = [r for r in conn.execute("MATCH (s:Signal {status: 'active'}) RETURN count(s)")]
print(f"Active signals: {r_a[0][0]}")
r_o = [r for r in conn.execute("MATCH (s:Signal {status: 'active'}) WHERE NOT EXISTS { MATCH (s)-[:Supports]->() } RETURN count(s)")]
print(f"Orphan signals: {r_o[0][0]}")

# Candidates
r_pend = [r for r in conn.execute("MATCH (c:Candidate {status: 'pending'}) RETURN count(c)")]
print(f"Total pending: {r_pend[0][0]}")
r_prom = [r for r in conn.execute("MATCH (c:Candidate {status: 'promoted'}) RETURN count(c)")]
print(f"Total promoted: {r_prom[0][0]}")

# Pending by relevance
r_user = [r for r in conn.execute("MATCH (c:Candidate {status: 'pending', user_relevance: 'user'}) RETURN count(c)")]
r_unk = [r for r in conn.execute("MATCH (c:Candidate {status: 'pending', user_relevance: 'unknown'}) RETURN count(c)")]
r_ao = [r for r in conn.execute("MATCH (c:Candidate {status: 'pending', user_relevance: 'agent_only'}) RETURN count(c)")]
print(f"Pending user: {r_user[0][0]}, unknown: {r_unk[0][0]}, agent_only: {r_ao[0][0]}")

# Check user-relevant pending with promotable confidence
r_promotable = [r for r in conn.execute("""
    MATCH (c:Candidate {status: 'pending', user_relevance: 'user'})
    RETURN c.id, c.confidence
""")]
promotable_count = 0
for row in r_promotable:
    conf = row[1]
    if conf in ("high", "medium", "med"):
        promotable_count += 1
    else:
        try:
            if float(conf) >= 0.6:
                promotable_count += 1
        except:
            pass
print(f"User-relevant with promotable confidence: {promotable_count}")

# Other counts
r_rel = [r for r in conn.execute("MATCH ()-[r]->() RETURN count(r)")]
print(f"Relationships: {r_rel[0][0]}")
r_inf = [r for r in conn.execute("MATCH (i:Inference) RETURN count(i)")]
print(f"Inferences: {r_inf[0][0]}")
# elephas journal count today
r_journals = [r for r in conn.execute("MATCH (s:Signal {source_skill: 'ocas-elephas'}) RETURN count(s)")]
print(f"Elephas signals: {r_journals[0][0]}")
