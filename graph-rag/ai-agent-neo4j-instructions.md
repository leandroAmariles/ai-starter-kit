# Neo4j Code Graph — AI Agent Reference

Setup, ingestion, freshness checks, troubleshooting, and test commands live in
[`README.md`](README.md). Use this file only as a quick query reference. Use credentials from the
local environment and verify important graph findings in source before editing.

## Query with the local script

Run from `graph-rag/`:

```bash
.venv/bin/python queries/graph_rag_query.py \
  "Which adapters implement the orders port?"
```

## Example Cypher queries

```cypher
// Find all classes that implement a specific interface.
MATCH (c:Class)-[:IMPLEMENTS]->(i:Class {name: 'OrdersPort'})
RETURN c.fqn, c.type, c.annotations

// Find all infrastructure adapters.
MATCH (c:Class)
WHERE c.fqn CONTAINS 'infrastructure'
RETURN c.fqn, c.type
LIMIT 50

// Find a use case's dependencies.
MATCH (uc:Class {name: 'OrdersUseCase'})-[:DEPENDS_ON]->(dep:Class)
RETURN dep.fqn, dep.type
LIMIT 30

// Find a short dependency chain.
MATCH path = (c:Class {name: 'OrdersUseCase'})-[:DEPENDS_ON|IMPLEMENTS*1..2]-(related)
RETURN [node IN nodes(path) | node.fqn] AS chain
LIMIT 50

// Restrict any query to one project when more than one is ingested.
MATCH (p:Project {name: 'orders'})<-[:BELONGS_TO]-(c:Class)
WHERE c.fqn CONTAINS 'UseCase'
RETURN c.fqn
LIMIT 50

// See which other ingested services a project depends on.
MATCH (a:Project {name: 'orders'})-[:DEPENDS_ON_PROJECT]->(b:Project)
RETURN b.name
```
