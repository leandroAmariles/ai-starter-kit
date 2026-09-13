---
name: neo4j-architecture-graph
description: Discover classes, implementations, dependencies, annotations, Kafka topics (producers/consumers), databases, REST/Feign calls, and change impact with the local Neo4j architecture graph, then verify results in source. Use for architecture discovery and dependency tracing, including across multiple ingested microservices that only interact at runtime (no shared Maven dependency).
---

# Neo4j Architecture Graph — Usage Instructions

## Purpose

`graph-rag/` maintains a local Neo4j graph of this repository's classes, annotations, and
dependencies (and, if `graph-rag/.env`'s `PROJECT_PATHS` lists more than one project, of every
ingested sibling repository too). Use it to answer structural questions before searching source
files manually.

If this Neo4j container is shared with other, unrelated systems (see `PROJECT_GROUP` in
`graph-rag/.env`), results are scoped to this installation's own group by default — `Project`,
`Topic`, `Database`, and `ExternalService` nodes are partitioned by `group` precisely so an
unrelated system's "gateway" service or "app_db" database can't be mistaken for this one's. Class/
Document fqns are `<group>::<project>::<java-or-path-fqn>`.

The graph is a discovery tool, not a source of truth. Confirm important results in source code
before changing code, especially when the graph might be stale (run
`graph-rag/.venv/bin/python verify_graph.py --check` if in doubt).

## When to use it

Use the graph first when the task requires any of the following:

| Task | Examples |
|---|---|
| Locating a class or interface | finding where `OrdersPort` or `OrdersUseCase` is defined |
| Discovering implementations | identifying adapters that implement an outbound port |
| Tracing dependencies | determining which ports a use case depends on |
| Inspecting architecture relationships | listing controllers, adapters, use cases, ports, or configuration classes |
| Inspecting annotations | finding classes annotated with `@Configuration`, `@Primary`, or an endpoint annotation |
| Assessing change impact | identifying consumers of a class, port, or adapter before modifying it |
| Cross-service impact (build-time) | if multiple projects are ingested, finding which other services depend on this one via Maven (`DEPENDS_ON_PROJECT`) before a breaking change |
| Cross-service impact (runtime) | for services with **no** Maven coupling, finding which service produces/consumes a Kafka topic (`PRODUCES_TO`/`CONSUMES_FROM` a shared `:Topic`), calls another service via Feign (`CALLS_SERVICE`), or shares a database (`SHARES_DATABASE`) |
| Understanding a class's integration surface | what topics a class produces to/consumes from, what HTTP routes it exposes (`rest_endpoints` property), what external service a `@FeignClient` targets |

Do not use it for simple file reads when the exact file path is known, for editing files, or for
content-only searches that do not require relationships.

## How to query the graph

If `.mcp.json` has a `graph-rag` MCP server configured, prefer its tools
(`mcp__graph-rag__graph-rag-read_neo4j_cypher` / `mcp__graph-rag__graph-rag-get_neo4j_schema`) for
Cypher above — read-only by design. Otherwise, run
`graph-rag/queries/graph_rag_query.py "<question>"` (vector search + graph traversal) or connect
directly with `graph-rag/.venv/bin/python` and the `neo4j` driver. Use exact class names or narrow
fqn filters, select only required fields, and apply `LIMIT`.

### Locate a class

```cypher
MATCH (c:Class {name: 'OrdersUseCase'})
RETURN c.fqn, c.type, c.project
LIMIT 10
```

### Find port implementations

```cypher
MATCH (implementation:Class)-[:IMPLEMENTS]->(port:Class {name: 'OrdersPort'})
RETURN implementation.fqn, implementation.type
LIMIT 20
```

### Inspect direct dependencies

```cypher
MATCH (useCase:Class {name: 'OrdersUseCase'})-[:DEPENDS_ON]->(dependency:Class)
RETURN dependency.fqn, dependency.type
LIMIT 30
```

### Scope a query to one project (when more than one is ingested)

```cypher
MATCH (p:Project {name: 'orders'})<-[:BELONGS_TO]-(c:Class)
WHERE c.fqn CONTAINS 'infrastructure'
RETURN c.name, c.type, c.fqn
LIMIT 50
```

### Trace cross-service impact

```cypher
MATCH (dependent:Project)-[:DEPENDS_ON_PROJECT]->(target:Project {name: 'shared-lib'})
RETURN dependent.name
```

### Find annotated classes

```cypher
MATCH (c:Class)-[:ANNOTATED_WITH]->(annotation:Annotation {name: 'Configuration'})
RETURN c.fqn
LIMIT 30
```

### Who produces/consumes a Kafka topic (works across services with no Maven link)

```cypher
MATCH (c:Class)-[r:PRODUCES_TO|CONSUMES_FROM]->(t:Topic {name: 'order-created'})
RETURN type(r) AS direction, c.fqn, c.project
```

```cypher
// Full producer -> topic -> consumer picture for one topic, across every ingested project
MATCH (producer:Class)-[:PRODUCES_TO]->(t:Topic {name: 'order-created'})<-[:CONSUMES_FROM]-(consumer:Class)
RETURN producer.fqn AS producer, consumer.fqn AS consumer
```

### What database(s) a project uses, and whether two projects share one

```cypher
MATCH (p:Project)-[:USES_DATABASE]->(d:Database)
RETURN p.name, d.engine, d.database
```

```cypher
MATCH (a:Project)-[r:SHARES_DATABASE]->(b:Project)
RETURN a.name, b.name, r.engine, r.database
```

### Which service a class calls via Feign

```cypher
MATCH (c:Class)-[:CALLS_SERVICE]->(target)
RETURN c.fqn, labels(target) AS target_kind, target.name
```

`target_kind` is `["Project"]` when the Feign `name`/`value` matched an actually-ingested project
(verified, like `DEPENDS_ON_PROJECT`), or `["ExternalService"]` when it didn't (the name is taken
at face value, unverified).

## Fallback and verification

If Neo4j is unavailable, returns no result, or lacks the relationship needed, fall back to
repository-local code search. Do not start or stop the Neo4j container as part of answering a
query, write to the graph outside the `graph-rag/ingestion` pipeline, or store connection
credentials in repository instructions.

After a graph result identifies relevant files or relationships:

1. Read the identified source files.
2. Confirm the current implementation and public contracts.
3. Make changes only after source verification.

## Anti-patterns to avoid

| Anti-pattern | Correction |
|---|---|
| Running broad unbounded graph queries | Use exact class names, narrow fqn filters, selected fields, and `LIMIT` |
| Treating graph results as current source truth | Confirm findings in source files before changing code |
| Using grep first for dependency or implementation discovery | Query the graph first when available |
| Using the graph to read a known file | Read the known file directly |
| Assuming `DEPENDS_ON_PROJECT` covers runtime calls | It only reflects Maven/build-time dependency coordinates, not REST/messaging calls between services — use `PRODUCES_TO`/`CONSUMES_FROM`/`CALLS_SERVICE`/`SHARES_DATABASE` for those |
| Assuming every Kafka topic is captured | Only `@KafkaListener`/`KafkaTemplate`/`ProducerRecord`/`KafkaHeaders.TOPIC` (spring-kafka) and `@Bean Consumer/Function/Supplier` + `StreamBridge.send(...)` (Spring Cloud Stream, resolved via `application*.yml`'s `spring.cloud.stream.bindings.*.destination`) are detected, and only when the topic name is a string literal or a `static final String` constant — a topic built at runtime from a variable is silently skipped, not guessed |
| Assuming every REST call between services is captured | Only `@FeignClient(name=...)` is modeled as `CALLS_SERVICE` — `WebClient`/`RestTemplate` base URLs are usually built from injected config, not literals, so they aren't extracted (a false "no calls found" is possible; check source when a REST-based integration is expected but not in the graph) |
| Adding graph credentials to source or instructions | Use `graph-rag/.env` (gitignored) or the configured MCP integration |
