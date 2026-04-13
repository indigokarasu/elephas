# LadybugDB Operational Notes

Practical findings from running Elephas against real_ladybug v0.15.3. These are deviations from standard Cypher that affect every Elephas operation.

## Property filtering syntax

LadybugDB does **not** support property filtering in node pattern syntax like `{status: 'pending'}`. Use WHERE clauses instead:

```cypher
# WRONG — causes "Variable pending is not in scope"
MATCH (c:Candidate {status: 'pending'}) RETURN c

# CORRECT — use WHERE clause
MATCH (c:Candidate) WHERE c.status = 'pending' RETURN c
```

This applies to all node types. The `{prop: value}` shorthand in MATCH patterns is not supported.

## String quoting in WHERE

Use single quotes for string values in WHERE clauses and property setters:

```cypher
MATCH (c:Candidate) WHERE c.status = 'pending' AND c.user_relevance = 'user' RETURN c
```

Double quotes cause different parser behavior. When constructing Cypher in Python f-strings, use single quotes for Cypher string literals.

## Relationship creation with multiple node labels

`CREATE` for relationships cannot bind nodes using the bare `{{id: $val}}` pattern when the MATCH could match multiple node labels. Use explicit node labels:

```cypher
# WRONG — "Create rel bound by multiple node labels is not supported"
MATCH (a {id: $from_id}), (b {id: $to_id}) CREATE (a)-[:Relates]->(b)

# CORRECT — use explicit labels
MATCH (a:Entity {id: $from_id}), (b:Entity {id: $to_id}) CREATE (a)-[:Relates]->(b)
```

When creating relationships across different node types (Entity→Concept, Entity→Thing), specify the correct label for each endpoint.

## Reserved words in CREATE

The word `description` can trigger parser errors in CREATE statements. If you get "expected rule oC_SingleQuery" errors on CREATE, try:

1. Using f-string interpolation with single-quoted string values instead of parameterized `$desc`
2. Escaping the property name
3. Using a different field name (e.g., `desc` instead of `description`) — though the current schema uses `description` and it works with f-string interpolation

```cypher
# This works with f-string interpolation:
CREATE (i:Inference {id: 'inf_x', inference_type: 'team', confidence: 'high',
  supporting_nodes: '[]', description: 'text here', created_at: '2026-01-01'})

# This may fail with parameterized values containing complex strings:
CREATE (i:Inference {id: $id, description: $desc, ...})
```

## Querying relationship types

The `type()` function does not exist in LadybugDB. To count relationships by label, query each label separately:

```cypher
# WRONG
MATCH ()-[r]->() RETURN type(r), count(r)

# CORRECT
MATCH ()-[r:Relates]->() RETURN count(r)
MATCH ()-[r:Supports]->() RETURN count(r)
MATCH ()-[r:Promotes]->() RETURN count(r)
```

## Deleting nodes with relationships

Nodes with attached relationships cannot be deleted directly. Use `DETACH DELETE` or remove relationships first:

```cypher
# If this fails:
MATCH (e:Entity {id: $id}) DELETE e

# Use this instead:
MATCH (e:Entity {id: $id}) DETACH DELETE e

# Or mark as merged and skip:
MATCH (e:Entity {id: $id}) SET e.identity_state = 'merged'
```

## proposed_data format inconsistency

Candidate `proposed_data` may be stored in different formats depending on the source signal:
- JSON format: `{"name": "Jane Doe", "type": "Entity/Person", "confidence": "high"}`
- Python repr format: `{name: Jane Doe, type: Entity/Person, confidence: high}` (single-quoted keys, no quotes on values)

When parsing `proposed_data`, always try multiple formats:
1. `json.loads()` first
2. `ast.literal_eval()` second
3. Regex extraction as fallback: `r"name['\"]?\s*[:=]\s*['\"]?([^'\"},]+)['\"]?"`

## Entity name corruption pattern

When promoting Candidates to Entity/Concept/Thing nodes, if the `name` field is not explicitly set from `proposed_data`, the entity gets a placeholder name like `candidate_cand_963ddcf64235`. Always extract the real name from the candidate's proposed_data and set it explicitly during promotion.

## Session log actual format

Hermes session logs at `{agent_root}/sessions/*.jsonl` use:
- `role: "user"` (not `"human"` as the spec says)
- `role: "assistant"`
- `role: "tool"` (for tool results)
- `role: "session_meta"` (first line, contains tool schemas)

The `content` field may be a string or a list of objects (e.g., `[{"type": "text", "text": "..."}]`). Handle both.

## Memory file actual paths

In the Hermes environment, memory files are at:
- `{agent_root}/memories/MEMORY.md`
- `{agent_root}/memories/USER.md`

NOT at `{agent_root}/commons/workspace/MEMORY.md` or `{agent_root}/MEMORY.md` as the spec suggests.