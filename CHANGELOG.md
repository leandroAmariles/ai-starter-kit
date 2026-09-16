# Changelog

All notable changes to this kit (`ai-starter-kit/.ai/`) are documented here. Format loosely follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/):

- **MAJOR** — a change that can break already-installed repos (e.g. renaming/removing a skill an
  agent's commands depend on, restructuring `.ai/`).
- **MINOR** — new context-skills, rules, or callable skills added in a backward-compatible way.
- **PATCH** — wording/content fixes to existing files, no structural change.

`ai-starter-kit/.ai/VERSION` always holds the current version. Installed repos track the version
they last synced in their own `.ai/VERSION` (copied verbatim by `--copy`/`--update`) and record a
per-file hash baseline in `.ai/.ai-manifest.json` (not meant to be edited by hand) so that
`--update` can tell which files a repo customized versus which are still stock and safe to refresh.
See the "Versioning & updates" section in `README.md` for how to cut a new version and how
installed repos pick it up.

## [1.1.1] - 2026-09-15

Fix: `--speckit`/`--workflow speckit` now also runs `specify extension add git` once per repo,
right after the per-agent `specify init` calls. Root cause: current spec-kit versions moved feature
branch creation out of the `/speckit-specify` core command entirely and into an optional
`before_specify` hook, registered via `.specify/extensions.yml` — only this official "git" extension
sets that up; a plain `specify init --integration <agent>` does not. Without it, every
`/speckit-specify` run silently did all of its spec/plan/tasks/implementation work as uncommitted
changes on whatever branch was already checked out (main, if that's what was active), with no branch
ever created and no warning that one wasn't. Confirmed end-to-end on a fresh repo: `--workflow
speckit` now installs the extension, the `before_specify` hook fires, and `/speckit-specify` creates
a real feature branch. Idempotent — re-running against an already-extended repo detects it and
no-ops instead of erroring.

## [1.1.0] - 2026-09-15

Graph-rag: `CALLS_SERVICE` now also fires for a `WebClient`/`RestTemplate` built off a **literal**
base URL — a hardcoded `.baseUrl("http://host:port")` or a `@Value("${prop:http://host:port}")`
default — not just `@FeignClient(name=...)`. The target hostname is verified against configured
`PROJECT_PATHS` like Feign already was (linked to a real `:Project` node if it matches, else an
`:ExternalService` node); a bare `localhost`/`127.0.0.1`/`0.0.0.0` default is skipped since it names
no real service. Updated `.ai/skills/neo4j-architecture-graph/SKILL.md` to match (it previously told
agents WebClient/RestTemplate calls were never captured).

Docs: README's "Feeding more than one project into the same graph" section now also covers growing
the graph by installing Step 2 independently in each microservice (rather than maintaining one
central `PROJECT_PATHS` list) — point every repo's `graph-rag/.env` `NEO4J_URI` at the same Neo4j
instance and each repo's own `phase1_scan.py` run safely adds/refreshes only its own scoped nodes.
Documents that Kafka `:Topic` and `:Database` nodes already connect across independently-scanned
projects for free (keyed by name, not by project), while the three explicit cross-project edges
(`DEPENDS_ON_PROJECT`, verified `CALLS_SERVICE`, `SHARES_DATABASE`) still need an occasional combined
scan listing every sibling path together. No `.ai/` rules/context changed.

## [1.0.6] - 2026-09-15

Fix: `install-ai-package.sh`'s installer script itself, not `.ai/` content. `sync_manifest`'s
`LAST_SYNC_CONFLICTS` line piped its python output through `grep '^__RESULT__:'` — but `do_copy`
always calls `sync_manifest` in "quiet" mode, where the python helper never prints that marker at
all (it's only emitted `if report:`). With `set -o pipefail` active, `grep` finding no match returned
1, and because the pipeline sat inside a plain assignment under `set -e`, that silently killed the
whole script right there — every single time, on every machine. In practice this meant `--copy` (and
therefore `--init`, and `--agents`/`--sync`/`--workflow` whenever they had to copy `.ai/` first) died
right after copying `.ai/`'s raw files, before ever reaching `prune_workflow`/`do_scan`/`do_agents`/
`do_speckit`/`do_openspec`/`do_graph` — so a from-scratch `--init` (or `ai-bootstrap.sh` on a repo
with no `.ai/` yet) silently installed nothing beyond the bare `.ai/` copy, regardless of which
agent(s) or workflow were selected in the wizard. Fixed by appending `|| true` to that pipeline.
Confirmed fixed end-to-end (agent generation, spec-kit install, and the Neo4j graph bootstrap all
completing) on a fresh destination.

## [1.0.5] - 2026-09-15

Docs only. This repo is now public: README's "Installation" section drops the `gh api`/token/private-repo
instructions from 1.0.4 in favor of a plain unauthenticated `curl` of `ai-bootstrap.sh`, with `gh`/`git`
kept as optional alternatives. No `.ai/` content changed.

## [1.0.4] - 2026-09-12

Docs/tooling. `ai-bootstrap.sh` was previously only shown as a code block in the README (nothing to
actually download) — it's now a real, downloadable file at the repo root, and README's "Installation"
section documents three ways to pull it into a consuming repo given this repo is private (`gh api`,
`git clone` + copy, or `curl` with a personal access token). No `.ai/` content changed.

## [1.0.3] - 2026-09-12

Fix: `prune_workflow` (used by `--workflow` and now also by `--update`, see 1.0.2) only ever pruned
`.ai/skills/openspec-*` and `.ai/prompts/opsx-*` — the already-*generated* copies under
`.claude/skills`, `.claude/commands`, `.github/skills`, `.github/prompts`, `.cursor/skills`,
`.cursor/commands`, and `.windsurf/workflows` were never cleaned up, since `copy_dir_if_present`
only adds/overwrites and never deletes. A repo switching away from OpenSpec (or a legacy repo
hitting the 1.0.2 fix) could still see `/openspec-*` commands offered by its agent. `prune_workflow`
now removes the matching paths in every one of those locations too.

## [1.0.2] - 2026-09-12

Fix: `--update` on a repo that predates version tracking (no `.ai/.ai-manifest.json` yet) could
resurrect `.ai/skills/openspec-*` and `.ai/prompts/opsx-*` even when that repo had already chosen
`speckit`/`none` as its workflow — it had no baseline recording those paths as intentionally pruned,
so the diff saw them as simply new. `--update` now re-applies the repo's own recorded workflow
choice (`.ai/.workflow`) right after syncing, so a first `--update` on a legacy install prunes them
straight back out (and every run after is a clean no-op, same as any other repo).

## [1.0.1] - 2026-09-12

Docs only. README now documents the recommended bootstrap-script installation for consuming repos
(clone this repo, run `--init` if not installed / `--update` if already installed) alongside the
existing manual-checkout workflow. No `.ai/` content changed.

## [1.0.0] - 2026-09-12

Baseline: first version tracked under this scheme. Includes the context-skills
(hexagonal-architecture, reactive-programming, testing-java, domain-modeling, observability,
error-translation), the development-guidelines/auto-enrichment/session-identity-canary rules, the
OpenSpec/spec-kit workflow skills, the commit-and-push and neo4j-architecture-graph skills, the PR
template, and the installer's `--init/--copy/--scan/--agents/--sync/--check/--workflow/--openspec/
--speckit/--graph/--statusline` commands.
