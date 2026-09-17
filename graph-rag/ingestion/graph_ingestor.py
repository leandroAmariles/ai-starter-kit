from __future__ import annotations

import re

from neo4j import GraphDatabase

from ingestion.scanner import compare_inventory

RELATIONSHIP_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class GraphIngestor:
    def __init__(self, uri: str, user: str, password: str) -> None:
        self.driver = GraphDatabase.driver(uri, auth=(user, password))

    def execute_statement(self, statement: str, parameters: dict | None = None) -> None:
        with self.driver.session() as session:
            session.run(statement, parameters or {}).consume()

    def indexed_inventory(self, project: str, group: str) -> dict[str, list[dict]]:
        """Return the indexed inventory scoped to a single (group, project).

        Scoping by project is what makes it safe to ingest several repositories
        into one shared graph: reconciling project B must never see (and must
        never delete) project A's nodes. Scoping by group on top of that is
        what makes it safe to ingest several *unrelated* systems into that
        same shared graph: two systems reusing the same project name must
        never collide (see PROJECT_GROUP in graph-rag/.env)."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (node)
                WHERE node.project = $project
                  AND node.group = $group
                  AND ((node:Class AND node.file_path IS NOT NULL) OR node:Document)
                RETURN node.relative_path AS relative_path,
                       CASE WHEN node:Class THEN 'Class' ELSE 'Document' END AS node_label,
                       node.content_hash AS content_hash,
                       node.parser_version AS parser_version,
                       node.schema_version AS schema_version
                """,
                project=project,
                group=group,
            )
            inventory: dict[str, list[dict]] = {}
            for record in result:
                relative_path = record["relative_path"]
                if relative_path:
                    inventory.setdefault(relative_path, []).append(record.data())
            return inventory

    def reconcile_inventory(
        self, project: str, group: str, expected_inventory: dict[str, dict]
    ) -> tuple[set[str], set[str], dict[str, list[str]]]:
        missing, stale, modified = compare_inventory(
            expected_inventory, self.indexed_inventory(project, group)
        )
        paths_to_delete = sorted(stale | set(modified))
        if paths_to_delete:
            with self.driver.session() as session:
                session.run(
                    """
                    MATCH (node)
                    WHERE (node:Class OR node:Document)
                      AND node.project = $project
                      AND node.group = $group
                      AND node.relative_path IN $relative_paths
                    DETACH DELETE node
                    """,
                    project=project,
                    group=group,
                    relative_paths=paths_to_delete,
                ).consume()
        return missing, stale, modified

    def upsert_node(self, node_data: dict) -> None:
        """`node_data['fqn']` must already be project-scoped (see phase1_scan._scoped)."""
        properties = dict(node_data)
        fqn = properties["fqn"]
        with self.driver.session() as session:
            session.run(
                """
                MERGE (c:Class {fqn: $fqn})
                SET c += $properties
                """,
                fqn=fqn,
                properties=properties,
            ).consume()

    def upsert_relation(self, from_fqn: str, to_fqn: str, rel_type: str) -> None:
        """`from_fqn`/`to_fqn` must already be project-scoped."""
        if not RELATIONSHIP_PATTERN.fullmatch(rel_type):
            raise ValueError(f"Invalid relationship type: {rel_type}")

        query = f"""
        MERGE (from:Class {{fqn: $from_fqn}})
        MERGE (to:Class {{fqn: $to_fqn}})
        MERGE (from)-[:{rel_type}]->(to)
        """

        with self.driver.session() as session:
            session.run(query, from_fqn=from_fqn, to_fqn=to_fqn).consume()

    def upsert_annotation(self, class_fqn: str, annotation_name: str) -> None:
        with self.driver.session() as session:
            session.run(
                """
                MERGE (c:Class {fqn: $class_fqn})
                MERGE (a:Annotation {name: $annotation_name})
                MERGE (c)-[:ANNOTATED_WITH]->(a)
                """,
                class_fqn=class_fqn,
                annotation_name=annotation_name,
            ).consume()

    def upsert_document(self, doc_data: dict) -> None:
        """Upsert a :Document node (config files, markdown, yaml, etc.).

        `doc_data['fqn']` must already be project-scoped.
        """
        properties = dict(doc_data)
        fqn = properties["fqn"]
        with self.driver.session() as session:
            session.run(
                """
                MERGE (d:Document {fqn: $fqn})
                SET d += $properties
                """,
                fqn=fqn,
                properties=properties,
            ).consume()

    def upsert_document_reference(self, project: str, from_fqn: str, to_relative_path: str) -> bool:
        """Link a document to an existing document or AST-parsed source file.

        `to_relative_path` alone is not globally unique across projects (many repos
        have a README.md at the same relative path), so the target lookup is
        scoped to `project` as well.
        """
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (source:Document {fqn: $from_fqn})
                MATCH (target)
                WHERE (target:Document OR target:Class)
                  AND target.relative_path = $to_relative_path
                  AND target.project = $project
                MERGE (source)-[:REFERENCES]->(target)
                """,
                from_fqn=from_fqn,
                to_relative_path=to_relative_path,
                project=project,
            )
            return result.consume().counters.relationships_created > 0

    def upsert_project(self, name: str, path: str, group: str) -> None:
        """`group` (PROJECT_GROUP) is part of Project's identity, not just a
        property: two unrelated systems sharing one Neo4j instance can each
        have a microservice named e.g. "gateway" without colliding onto the
        same node."""
        with self.driver.session() as session:
            session.run(
                """
                MERGE (p:Project {name: $name, group: $group})
                SET p.path = $path
                """,
                name=name,
                group=group,
                path=path,
            ).consume()

    def link_belongs_to(self, fqn: str, project: str, group: str) -> None:
        with self.driver.session() as session:
            session.run(
                """
                MATCH (n {fqn: $fqn})
                MATCH (p:Project {name: $project, group: $group})
                MERGE (n)-[:BELONGS_TO]->(p)
                """,
                fqn=fqn,
                project=project,
                group=group,
            ).consume()

    def upsert_topic_relation(self, class_fqn: str, topic_name: str, direction: str, group: str) -> None:
        """`direction` is 'produces' or 'consumes'. `:Topic` nodes are NOT
        scoped by *project* (unlike `:Class`/`:Document`) — a Kafka topic is
        one broker-wide resource, and the point of this edge is exactly that
        two different services' classes can point at the *same* `:Topic`
        node, which is how a cross-service messaging relationship becomes
        visible in the graph. They ARE scoped by `group` (PROJECT_GROUP):
        two unrelated systems sharing one Neo4j instance are very likely to
        reuse a generic topic name like "events" by coincidence, and without
        this they would incorrectly appear to be integrated."""
        if direction not in ("produces", "consumes"):
            raise ValueError(f"Invalid topic direction: {direction}")
        rel_type = "PRODUCES_TO" if direction == "produces" else "CONSUMES_FROM"
        with self.driver.session() as session:
            session.run(
                f"""
                MATCH (c:Class {{fqn: $class_fqn}})
                MERGE (t:Topic {{name: $topic_name, group: $group}})
                MERGE (c)-[:{rel_type}]->(t)
                """,
                class_fqn=class_fqn,
                topic_name=topic_name,
                group=group,
            ).consume()

    def link_project_database(self, project: str, engine: str, database: str, group: str) -> None:
        """`:Database` nodes are keyed by (engine, database name, group), not
        by project — like `:Topic`, this is deliberate: if two ingested
        projects *in the same group* resolve to the same (engine, database)
        pair, they merge onto the same node and both `USES_DATABASE` edges
        become visible from it. `group` is still part of the key so two
        unrelated systems that both happen to use, say, a Postgres database
        named "app_db" don't appear to share one."""
        with self.driver.session() as session:
            session.run(
                """
                MATCH (p:Project {name: $project, group: $group})
                MERGE (d:Database {engine: $engine, database: $database, group: $group})
                MERGE (p)-[:USES_DATABASE]->(d)
                """,
                project=project,
                engine=engine,
                database=database,
                group=group,
            ).consume()

    def upsert_service_call(self, class_fqn: str, target_project: str, verified: bool, group: str) -> None:
        """A `@FeignClient`-declared call to another service. `verified=True`
        when `target_project` matches a project actually ingested into this
        graph (so it links to the real `:Project` node); otherwise it links
        to an `:ExternalService` node under that name, since the target
        wasn't confirmed to be present — mirrors how `DEPENDS_ON_PROJECT`
        only fires when both sides were actually ingested. Both node types
        are scoped by `group` for the same reason `:Topic`/`:Database` are."""
        with self.driver.session() as session:
            if verified:
                session.run(
                    """
                    MATCH (c:Class {fqn: $class_fqn})
                    MERGE (p:Project {name: $target_project, group: $group})
                    MERGE (c)-[:CALLS_SERVICE]->(p)
                    """,
                    class_fqn=class_fqn,
                    target_project=target_project,
                    group=group,
                ).consume()
            else:
                session.run(
                    """
                    MATCH (c:Class {fqn: $class_fqn})
                    MERGE (e:ExternalService {name: $target_project, group: $group})
                    MERGE (c)-[:CALLS_SERVICE]->(e)
                    """,
                    class_fqn=class_fqn,
                    target_project=target_project,
                    group=group,
                ).consume()

    def set_project_coordinates(
        self, project: str, group: str, provided: set[tuple[str, str]], required: set[tuple[str, str]]
    ) -> None:
        """Persists this project's own Maven coordinates on its `:Project` node
        so a LATER, independent ingestion of a *different* project — one that
        never reads this project's pom.xml directly, because each microservice
        runs its own `--graph` against a shared Neo4j instance without listing
        its siblings — can still discover a `DEPENDS_ON_PROJECT` edge against
        it via `link_project_dependencies()`. That's a graph-side join instead
        of the in-process set comparison this replaces; the persisted lists
        are what make it possible."""
        with self.driver.session() as session:
            session.run(
                """
                MATCH (p:Project {name: $project, group: $group})
                SET p.provides = $provides, p.requires = $requires
                """,
                project=project,
                group=group,
                provides=sorted(f"{g}:{a}" for g, a in provided),
                requires=sorted(f"{g}:{a}" for g, a in required),
            ).consume()

    def link_project_dependencies(self, project: str, group: str) -> int:
        """Graph-side equivalent of comparing every project's coordinates in
        one process: matches `project`'s own provides/requires (just persisted
        by `set_project_coordinates`) against every OTHER `:Project` already
        in the same group, in both directions — so it also retroactively links
        a project that was ingested earlier and needed what `project` just
        started providing, even though that earlier run never knew `project`
        existed. Like the in-process version it replaces, this only ever adds
        edges (MERGE): a dependency later removed from a pom.xml does not
        retract an edge created here in the past."""
        with self.driver.session() as session:
            depends_on = session.run(
                """
                MATCH (self:Project {name: $project, group: $group})
                MATCH (other:Project {group: $group})
                WHERE other.name <> self.name
                  AND self.requires IS NOT NULL AND other.provides IS NOT NULL
                  AND any(coordinate IN self.requires WHERE coordinate IN other.provides)
                MERGE (self)-[:DEPENDS_ON_PROJECT]->(other)
                RETURN count(other) AS linked
                """,
                project=project,
                group=group,
            ).single()
            depended_on_by = session.run(
                """
                MATCH (self:Project {name: $project, group: $group})
                MATCH (other:Project {group: $group})
                WHERE other.name <> self.name
                  AND other.requires IS NOT NULL AND self.provides IS NOT NULL
                  AND any(coordinate IN other.requires WHERE coordinate IN self.provides)
                MERGE (other)-[:DEPENDS_ON_PROJECT]->(self)
                RETURN count(other) AS linked
                """,
                project=project,
                group=group,
            ).single()
            return (depends_on["linked"] if depends_on else 0) + (
                depended_on_by["linked"] if depended_on_by else 0
            )

    def existing_project_names(self, names: set[str], group: str) -> set[str]:
        """Which of `names` are already ingested `:Project` nodes in `group` —
        used to decide whether a `@FeignClient`/WebClient call target should
        link to the real `:Project` node or an `:ExternalService` placeholder,
        without requiring the caller to already know every project name up
        front (the decentralized, one-repo-at-a-time ingestion case)."""
        if not names:
            return set()
        with self.driver.session() as session:
            result = session.run(
                "MATCH (p:Project) WHERE p.group = $group AND p.name IN $names RETURN p.name AS name",
                group=group,
                names=sorted(names),
            )
            return {record["name"] for record in result}

    def promote_external_services(self, project: str, group: str) -> int:
        """Upgrades any `:ExternalService` placeholder left by an earlier,
        independent ingestion of ANOTHER project that called `project` before
        `project` itself had ever been ingested (`upsert_service_call` only
        links to a real `:Project` when the target was already present at
        that time). Makes the decentralized model self-healing: as each
        microservice gets ingested — in whatever order, whenever its own
        `--graph` happens to run — earlier unverified references to it
        upgrade automatically instead of staying stuck as external calls."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (caller)-[old:CALLS_SERVICE]->(ext:ExternalService {name: $project, group: $group})
                MATCH (p:Project {name: $project, group: $group})
                MERGE (caller)-[:CALLS_SERVICE]->(p)
                DELETE old
                WITH DISTINCT ext
                DETACH DELETE ext
                RETURN count(ext) AS promoted
                """,
                project=project,
                group=group,
            ).single()
            return result["promoted"] if result else 0

    def link_shared_databases(self, project: str, group: str) -> int:
        """Two projects that resolve to the identical (engine, database)
        pair from their own application*.yml already point at the same
        `:Database` node (`link_project_database` merges onto it no matter
        which project's ingestion created it, so this is already correct
        across independent runs); this only adds the direct `Project`-to-
        `Project` convenience edge so "who else touches this database"
        doesn't need a 2-hop query. Direction is canonicalized by name
        (alphabetically first -> second)
        so two projects' independent runs converge on the exact same
        relationship instead of each creating one pointing the other way."""
        with self.driver.session() as session:
            result = session.run(
                """
                MATCH (self:Project {name: $project, group: $group})-[:USES_DATABASE]->(d:Database)
                      <-[:USES_DATABASE]-(other:Project {group: $group})
                WHERE other.name <> self.name
                WITH (CASE WHEN self.name < other.name THEN self ELSE other END) AS a,
                     (CASE WHEN self.name < other.name THEN other ELSE self END) AS b,
                     d
                MERGE (a)-[r:SHARES_DATABASE]->(b)
                SET r.engine = d.engine, r.database = d.database
                RETURN count(DISTINCT b) AS linked
                """,
                project=project,
                group=group,
            ).single()
            return result["linked"] if result else 0

    def update_document_embedding(self, fqn: str, embedding: list, summary: str) -> None:
        with self.driver.session() as session:
            record = session.run(
                """
                MATCH (d:Document {fqn: $fqn})
                SET d.embedding = $embedding,
                    d.summary = $summary
                RETURN count(d) AS updated
                """,
                fqn=fqn,
                embedding=embedding,
                summary=summary,
            ).single()
            if record is None or record["updated"] != 1:
                raise RuntimeError(f"Document node not found for embedding update: {fqn}")

    def update_embedding(self, fqn: str, embedding: list, summary: str) -> None:
        with self.driver.session() as session:
            record = session.run(
                """
                MATCH (c:Class {fqn: $fqn})
                SET c.embedding = $embedding,
                    c.summary = $summary
                RETURN count(c) AS updated
                """,
                fqn=fqn,
                embedding=embedding,
                summary=summary,
            ).single()
            if record is None or record["updated"] != 1:
                raise RuntimeError(f"Class node not found for embedding update: {fqn}")

    def cleanup_orphans(self) -> None:
        with self.driver.session() as session:
            session.run(
                """
                MATCH (annotation:Annotation)
                WHERE NOT (annotation)<-[:ANNOTATED_WITH]-()
                DELETE annotation
                """
            ).consume()
            session.run(
                """
                MATCH (class:Class)
                WHERE class.file_path IS NULL AND NOT (class)--()
                DELETE class
                """
            ).consume()

    def close(self) -> None:
        self.driver.close()
