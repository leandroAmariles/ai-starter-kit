# Graph RAG Pipeline

The repository's local Neo4j architecture graph and Graph RAG pipeline. Phase 1 deterministically
indexes Java architecture plus every other tracked file, across **one or more** git repositories.
Phase 2 adds AI-written summaries and vector embeddings.

This is **optional Step 2** of the starter kit — install it whenever you want a local, queryable
graph of your codebase by running `install-ai-package.sh --graph <destination-repo>` from the kit
root. It is not copied or run by `--copy`/`--scan`/`--agents`/`--sync`.

## Prerequisites

* Docker and Docker Compose
* Python 3.11+
* A local clone of the repositories you want indexed

## Initial setup

`install-ai-package.sh --graph <destination-repo>` (run from the kit root) does steps 1-4 below
for you. To run them manually:

```bash
cd graph-rag
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp -n .env.example .env
docker compose --env-file .env up -d
.venv/bin/python ingestion/phase1_scan.py
```

Open [Neo4j Browser](http://localhost:7474) and use the local credentials from `.env`. The
committed password in `.env.example` is intentionally a dummy local-development credential —
never put real credentials in tracked files.

## Recreating a deleted Neo4j container

The ingested graph lives in a separate, named Docker volume (`graph-rag_neo4j_data`), not in the
container itself. If the container is stopped, removed, or your machine restarts, just bring it
back — the volume survives and the data is intact, no re-ingestion needed:

```bash
./install-ai-package.sh --graph <destination-repo>   # idempotent: reuses graph-rag/.env as-is
# or, from inside the destination repo, if it has ai-bootstrap.sh:
./ai-bootstrap.sh --graph
```

Both re-check whether Neo4j is already reachable before doing anything, so this is safe and quick
to run any time, including as part of every normal `ai-bootstrap.sh` run (it does this
automatically whenever `graph-rag/` already exists — see its own header comment).

**The one operation that actually destroys the graph is `docker compose down -v`** (or `docker
volume rm graph-rag_neo4j_data` directly) — the `-v` flag deletes the named volume along with the
container. Because that volume's name is shared by design across every microservice joined to this
same graph (see below), running it from *any one* of them deletes the graph for *all* of them, not
just the repo you're standing in. Plain `docker compose down`, `docker rm`, or removing the
container from Docker Desktop's UI are all safe — none of them touch the volume.

## Sharing one graph across several microservices

By default `PROJECT_PATHS=.` in `.env` — just the repository this kit was installed into. If you
work across several microservices, the recommended setup is **one independent `graph-rag/` install
per repo, all pointing at the same Neo4j** — not one repo listing every sibling's path:

* Every repo's `.env.example` ships the identical default `NEO4J_URI`/credentials, so running
  `install-ai-package.sh --graph <repo>` (or answering "yes" to the Neo4j question in `--init`'s
  wizard) in a **second** repo detects the **first** repo's already-running Neo4j container (same
  URI, already reachable) and joins it instead of starting a second, separate one — which would
  just fail on the same host ports anyway.
* Each repo's own `PROJECT_PATHS` stays `.` — it never lists any other repo's path. No microservice's
  config ever references another microservice by name or filesystem location.
* Cross-service edges (`DEPENDS_ON_PROJECT`, `CALLS_SERVICE`, `SHARES_DATABASE` — see below) are
  computed by each repo's own Phase 1 run **querying the shared graph** for already-ingested sibling
  projects, not by any repo enumerating its siblings. This works in any order: ingest `orders`
  today and `payments` next month against the same Neo4j, and both directions of any relationship
  between them appear as soon as the second one is ingested — including retroactively upgrading an
  earlier unverified `CALLS_SERVICE` call once its real target shows up.

The older alternative — one `graph-rag/` install whose `.env` lists every sibling checkout by path —
still works and is exactly equivalent from the graph's point of view (same shared Neo4j, same node
identities); it's just a single hub repo's config knowing about every other repo, which the
decentralized setup above avoids:

```bash
# graph-rag/.env
PROJECT_PATHS=orders=.,payments=../payments-service,shared-lib=../shared-lib
```

Each entry is `name=path` (or just `path`, defaulting the name to the directory's basename); paths
resolve relative to this repository's root unless absolute. Every listed path must be its own git
repository — Phase 1 scans each one independently via `git ls-files --cached`.

**Why this is safe to share one graph:** every `Class`/`Document` node is tagged with a `project`
property, and Phase 1 reconciliation (deletion of stale/changed nodes) is scoped to that property.
Ingesting `payments-service` can never delete or overwrite `orders`'s nodes, even though they live
in the same Neo4j database — each project's node identity (`fqn`) is internally prefixed with its
project name to stay globally unique (e.g. two services both having a `README.md` at their root
does not collide). This holds whether all projects are ingested by one process (`PROJECT_PATHS`
listing several) or each by its own, fully independent `--graph` run.

### How cross-service relationships are modeled

Each ingested repository gets one `(:Project {name, path, provides, requires})` node, and every
`Class`/`Document` belonging to it gets a `-[:BELONGS_TO]->` edge to it. This lets you scope any
query to one project, or ask "what does project X contain".

For **inter-service** relationships, Phase 1 reads every tracked `pom.xml` in a project and persists
its own published/required Maven coordinates on its `:Project` node, then queries the graph for any
*other* `:Project` (in the same `PROJECT_GROUP`) whose coordinates intersect — in both directions.
If project A requires a `groupId:artifactId` that project B publishes, Phase 1 creates
`(A)-[:DEPENDS_ON_PROJECT]->(B)`. Because this is a graph-side lookup rather than an in-process
comparison, it fires correctly no matter which of A or B was ingested first, or whether they were
ever listed in the same `PROJECT_PATHS` at all — the tool never fabricates a service graph out of a
`pom.xml` dependency list alone, only out of coordinates it can actually verify by ingesting the
publisher too, at some point, into this same graph.

```cypher
// Which services does "orders" depend on?
MATCH (a:Project {name: 'orders'})-[:DEPENDS_ON_PROJECT]->(b:Project)
RETURN b.name

// Everything that would be affected by a breaking change in "shared-lib"
MATCH (dependent:Project)-[:DEPENDS_ON_PROJECT]->(target:Project {name: 'shared-lib'})
RETURN dependent.name
```

`CALLS_SERVICE` (from a `@FeignClient`/WebClient target) works the same way: if the target project
isn't in the graph yet, the call links to a placeholder `:ExternalService` node instead; once that
project is later ingested (by anyone, independently), the placeholder is automatically upgraded to
point at the real `:Project` node. `SHARES_DATABASE` piggybacks on the `:Database` node that two
projects' `USES_DATABASE` edges already merge onto when they resolve to the same (engine, database
name) pair, regardless of which project's run created it first.

This deterministic, dependency-based linking is the recommended starting point because it has no
false positives. Detecting *runtime* interactions (REST calls, message queues between services) is
not implemented — it would require parsing OpenAPI specs or client configuration and is much less
reliable. If you need it, it is the natural next extension: parse each service's declared HTTP
clients/consumer configs into a `CALLS` edge between `Project` nodes, following the same
"only link what you can verify from both sides" principle used for `DEPENDS_ON_PROJECT`.

## Manual Graph RAG operations

### 1. Build the deterministic graph

```bash
cd graph-rag
.venv/bin/python ingestion/phase1_scan.py
```

The inventory for each project is exactly the paths returned by `git ls-files --cached` in that
project's repo; untracked files are never indexed. Java files receive deterministic AST analysis as
`Class` nodes. Every other tracked file is represented generically as a `Document` node. Generic
reads are bounded, and binary files are stored as metadata only.

Each Class and Document stores the current working-tree Git blob hash, parser version, graph schema
version, and its `project`. Phase 1 reconciles paths whose content or parser/schema metadata
changed before recreating nodes and relationships, scoped to that project, and removes paths no
longer present in that project's tracked inventory.

Use `--reset` to fully rebuild every configured project's nodes:

```bash
.venv/bin/python ingestion/phase1_scan.py --reset
```

All Phase 1 ingestion, including normal reconciliation and `--reset`, refuses any Neo4j URI whose
host is not `localhost`, `127.0.0.1`, or `::1`. Reconciliation updates and deletes nodes, so it is
safe only for the dedicated local graph.

### 2. Generate class summaries

Phase 1 generates `data/extracted_classes.json` (fqns prefixed per project) and `pipeline_tasks.md`.
Ask your AI agent to execute the latter:

> Read and execute `graph-rag/pipeline_tasks.md`.

This produces the ignored `data/summaries.json` required by embedding ingestion.

### 3. Create embeddings and ingest them

```bash
.venv/bin/python ingestion/phase2_embed_ingest.py
```

Phase 2 requires exactly one non-empty summary for every fqn in `data/extracted_classes.json`.
Unknown, duplicate, or missing fqns fail ingestion. Embedding generation failures and vectors that
do not match `EMBEDDING_DIM` also fail instead of leaving a partially valid index. The default model
and Neo4j vector indexes use 384 dimensions. Phase 2 also refuses non-loopback Neo4j URIs because it
updates graph nodes with repository-derived summaries and embeddings.

### 4. Query the graph

```bash
.venv/bin/python queries/graph_rag_query.py \
  "Which adapters implement the orders port?"
```

### 5. Verify connectivity and freshness

```bash
.venv/bin/python verify_graph.py --connection
.venv/bin/python verify_graph.py --check
```

A current graph reports, per project:

```text
[orders] Graph coverage: expected=<count> indexed=<count> missing=0 stale=0 modified=0
```

`missing` means a tracked path has no graph node, `stale` means the graph contains a path no longer
tracked, and `modified` means the path exists but its node kind, content hash, parser version, graph
schema version, or node cardinality differs.

## Tests

Run from the `graph-rag/` directory:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

## Example queries in Neo4j Browser

```cypher
// List all classes in one project.
MATCH (p:Project {name: 'orders'})<-[:BELONGS_TO]-(c:Class)
RETURN c.name, c.type, c.annotations
LIMIT 50

// List port implementations.
MATCH (adapter:Class)-[:IMPLEMENTS]->(port:Class)
WHERE port.name CONTAINS 'Port'
RETURN adapter.name, port.name
LIMIT 50

// List use case dependencies.
MATCH (useCase:Class)-[:DEPENDS_ON]->(dependency:Class)
WHERE useCase.name CONTAINS 'UseCase'
RETURN useCase.name, dependency.name, dependency.type
LIMIT 50

// Map every service's dependencies on every other ingested service.
MATCH (a:Project)-[:DEPENDS_ON_PROJECT]->(b:Project)
RETURN a.name AS service, b.name AS depends_on
```

## AI agent integration

Use [`ai-agent-neo4j-instructions.md`](ai-agent-neo4j-instructions.md) as the concise query
reference, and the `neo4j-architecture-graph` callable skill (`.ai/skills/`) for when/how to reach
for the graph. Always confirm graph discoveries in the current source before making changes.

### "Connection timed out" on the graph-rag MCP server's first use

The `graph-rag` entry in `.mcp.json` launches via `uvx mcp-neo4j-cypher@0.6.0` — a Python process
with a fairly heavy dependency tree (`fastmcp`, `authlib`, `starlette`, `uvicorn`, the Neo4j driver,
...). `--graph` pre-warms `uvx`'s package cache during install specifically so the very first
connection doesn't also have to download it, but that only removes the *download* cost. On some
machines — measured on Windows with antivirus/EDR scanning every file the interpreter touches —
just starting the process can still take 30-90+ seconds even fully cached and offline, which is
longer than an MCP client's default connection timeout. If your AI agent reports the `graph-rag`
server timed out or failed to connect:

1. **Just retry** (e.g. restart the session) — the OS/AV having already scanned these files once
   usually makes the next attempt noticeably faster, and it may connect fine.
2. If it keeps timing out, raise the client's connection timeout. For Claude Code, set the
   `MCP_TIMEOUT` environment variable (milliseconds, default `30000`) to something larger, e.g.
   `120000`, before launching it — check your AI agent's own docs for the equivalent if you're
   using a different one.
