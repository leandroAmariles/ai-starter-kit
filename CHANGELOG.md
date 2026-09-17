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

## [1.6.0] - 2026-09-17

Feat: microservices can now share one Neo4j architecture graph without any of them referencing
another's filesystem path. Two changes make this work:

- `--graph`/`--init`, before starting a new Neo4j container, checks whether one is already
  reachable at this repo's own `graph-rag/.env` `NEO4J_URI` — every repo ships the same default
  local-dev URI/credentials, so a second repo's install detects the first repo's already-running
  container and joins it instead of starting (and failing to start) a second one on the same host
  ports. Each repo's own `PROJECT_PATHS` stays `.` — it never lists a sibling's path.
- `ingestion/phase1_scan.py`/`graph_ingestor.py`: `DEPENDS_ON_PROJECT`, `CALLS_SERVICE`, and
  `SHARES_DATABASE` cross-project edges used to be computed by comparing every project configured
  in one process's `PROJECT_PATHS` in memory — which only worked if every related project was
  listed together in one run. They're now computed by each project's own ingestion querying the
  shared graph for already-ingested sibling `:Project` nodes (their persisted `provides`/`requires`
  Maven coordinates, in both directions), so the edges form correctly regardless of which project
  was ingested first or whether they were ever listed together. An earlier, unverified
  `CALLS_SERVICE` link to an `:ExternalService` placeholder is automatically promoted to the real
  `:Project` node once that project is later ingested by anyone. Verified end-to-end against a real
  Neo4j instance with three independently-ingested fake microservices (dependency, service-call,
  and retroactive-linking scenarios), plus the existing unit suite (18 tests, no regressions).
  `PROJECT_PATHS` listing several projects in one run still works exactly as before — it's just N
  of these same graph-side passes done back to back.

Prompted by a user asking how to point a second repo's install at the graph from a first, and
clarifying that neither repo's config should need to know the other exists. See
`graph-rag/README.md`'s "Sharing one graph across several microservices" section.

## [1.5.1] - 2026-09-16

Fix: `commit-and-push/SKILL.md`'s step 9 (1.5.0) said to "skip silently" the graph refresh when
`graph-rag/.venv/` doesn't exist, but didn't say the check was scoped to the current repository —
an agent that also knew (from earlier conversation) about a separate "hub" repo hosting a shared
Neo4j graph for several microservices took that as license to run the scan against that *other*
repo instead, describing it as following "the spirit" of the step. That's an agent committing in
repo A reaching into repo B's filesystem and executing a script there, based on inferred context
rather than anything this skill actually authorized. Step 9 now explicitly scopes the check to
`graph-rag/.venv/` directly under this repo's own root (`git rev-parse --show-toplevel`) and says
plainly that "doesn't exist here" always means skip, never "look elsewhere" — a multi-repo hub
topology (real, documented in `graph-rag/README.md`) is the *hub* repo's own responsibility to
refresh, not something this step reaches for from a different repo. Added a matching guardrail.

## [1.5.0] - 2026-09-16

Added: new rule `.ai/rules/skill-transparency.md` — at every assistant turn (not just session
start), the agent discloses which callable skill (`.ai/skills/*`) it's invoking and which
context-skill(s) (`.ai/context/skills/*`) it's actually drawing on for that response, or says
explicitly that none apply. Gets concatenated into every agent's main file automatically via the
existing `.ai/rules/*.md` mechanism — no installer changes needed. While adding it, found and fixed
the same stale description in three places (`README.md`, `.ai/rules/README.md`, `.ai/STARTUP.md`):
all three still described `session-identity-canary.md` as "ask for a name, prefix every response
with it," which is not what the file has done for a while now (it prints a fixed rules-loaded line
at session start instead) — updated all three to match the actual current behavior.

Added: `commit-and-push/SKILL.md` gained a step 9 — if `graph-rag/.venv/` exists in the repo (Step 2
already installed), it re-runs the deterministic Phase 1 architecture scan
(`ingestion/phase1_scan.py`) after the commit, so the Neo4j graph reflects what was just committed.
Best-effort and non-blocking: skipped silently if Step 2 was never installed, and a scan failure
(e.g. Neo4j not running) is reported without failing the commit/push/PR that already succeeded.
Nothing it produces needs to be committed (`graph-rag/data/*.json` is gitignored), and it never
starts/stops/reconfigures the Neo4j container itself. Phase 2 (summaries + embeddings) is
unaffected — still the separate, manual, LLM-driven `graph-rag/pipeline_tasks.md` step. Updated the
root `README.md` and `.ai/skills/README.md` to describe this.

## [1.4.0] - 2026-09-16

Fix (critical, pre-existing, not introduced by the previous 1.3.0 fixes): `install-ai-package.sh`'s
`_progress_bar()` ended with a bare `[[ "$current" -ge "$total" ]] && printf '\n'`. Under this
script's `set -euo pipefail`, a bare `[[ cond ]] && cmd` as a function's *last* statement makes the
whole function return that failing exit code the moment `cond` is false — and since `errexit`
treats a plain (unguarded) function call the same as any other simple command, that silently killed
the entire script the first time a progress bar was drawn below 100% (i.e. on effectively every run).
This was invisible in every test run today because `_progress_bar` early-returns via `[[ -t 1 ]] ||
return 0` when stdout isn't a TTY — exactly the case for scripted/CI invocations, but *not* for a
real interactive terminal, which is the primary way people actually run `--init`/`--scan`/`--agents`/
`--sync`/`--update`. Confirmed by extracting the function and reproducing the silent-death with the
TTY guard bypassed. Fixed by using `if ... fi` instead of the bare `&&`. Audited every other function
in the file for the same "bare `&&`/`||` as the last statement" shape; the only two others that had
it (`detect_cicd`, `check_skill_frontmatter`) are already safe because every call site wraps them
(`"$(detect_cicd ... || true)"`, `if ! check_skill_frontmatter ...`).

Fix: the new `cleanup_stale_openspec_static()` helper added in 1.3.0 had the exact same bug in its
own trailing `[[ "$removed" -eq 1 ]] && ok "..."` line — caught immediately via live testing once a
scenario made `$removed` stay `0` for an agent (e.g. `github-copilot` in the `--tools` list, or a
second `--openspec` run after the first already cleaned up). Fixed the same way, and also refactored
the function to self-guard on the real CLI's own marker directory (`.claude/commands/opsx/`,
`.cursor/commands/opsx/`, `.devin/skills/`) rather than deleting unconditionally. That refactor also
fixes a second, related bug found by the same audit: `--sync`/`--update`/a second `--agents` call
unconditionally re-copies this kit's static `.ai/prompts`/`.ai/skills` snapshot, which was silently
resurrecting the exact stale `opsx-*`/`openspec-*` files `--openspec` had just removed. The cleanup
call now also runs at the end of `generate_claude()`/`generate_cursor()`/`generate_windsurf()`
themselves, so it's re-applied (and stays a no-op before `--openspec` has ever run) on every
regeneration, not just once right after `--openspec`.

Fix: investigated the `.windsurf/` vs `.devin/` question flagged in 1.3.0's changelog. Confirmed
directly against OpenSpec CLI 1.13.0 (`openspec init --help`): `windsurf` is now only a deprecated,
backward-compatible alias — the real, listed `--tools` value is `devin`, and running either produces
identical output for an integration the CLI itself calls "Devin Desktop (formerly Windsurf)", writing
`openspec-*/SKILL.md` + `opsx-*.md` entirely under **`.devin/`**, never under `.windsurf/` (it even
self-migrates its own old `.windsurf/workflows/openspec-*.md` output from before this rename).
`openspec_tool_for()` now maps this kit's `windsurf` agent to the `devin` slug directly (more
future-proof than relying on a documented-deprecated alias). This is scoped to OpenSpec's own
generated output only — this kit's separate, non-OpenSpec Windsurf conventions (`.windsurfrules`,
`.windsurf/rules/*`, `.windsurf/workflows/commit-and-push.md` /
`.windsurf/workflows/neo4j-architecture-graph.md`) are left exactly as they were; whether the
underlying editor itself has also renamed those conventions is unconfirmed, so nothing there was
changed. `prune_workflow()` (switching away from `openspec`) now also removes the real CLI's own
output — `.claude/commands/opsx/`, `.cursor/commands/opsx/`, and `.devin/` — which it previously
never did, leaving those behind forever after a workflow switch. `--check` gained a corresponding
`.devin/`-aware duplicate-output warning (previously it incorrectly compared two globs both inside
`.windsurf/workflows/`, which could never both be true). Root `README.md` and
`.ai/prompts/README.md` updated to describe the confirmed `.devin/` paths and the rename.

## [1.3.0] - 2026-09-16

Fix: `.ai/skills/openspec-explore/SKILL.md` and `.ai/prompts/opsx-explore.prompt.md` had drifted —
the skill carried a full "Handling Different Entry Points" section (worked examples with ASCII
diagrams for a vague idea, a specific problem, mid-implementation, and comparing options) and a
richer "Ending Discovery" summary format that the prompt/command version was missing entirely.
Anyone invoking explore mode via `/opsx-explore` got a materially thinner experience than via the
`openspec-explore` skill or natural language, despite `.ai/prompts/README.md` describing these files
as mirrors of each other. Brought `opsx-explore.prompt.md` back to parity; only the command-specific
`**Input**` block and the "read the mentioned change's artifacts" line remain prompt-only, both
intentional.

Fix: running `install-ai-package.sh --openspec <agents> <repo>` (the real OpenSpec CLI) never
removed this kit's own static `opsx-*` command files it had already generated at a *different* path
than the CLI's own output (`.claude/commands/opsx-*.prompt.md` vs. the CLI's
`.claude/commands/opsx/*`; `.cursor/commands/opsx-*.prompt.md` vs. `.cursor/commands/opsx/*`;
`.windsurf/workflows/openspec-*.md` vs. the CLI's `opsx-*.md` there) — `openspec init --force` only
overwrites paths it recognizes as its own, so the two sets lingered side by side indefinitely with
nothing indicating which was current. `do_openspec` now removes the stale static files for
Claude/Cursor/Windsurf right after a successful CLI run (Copilot is left alone — no confirmed CLI
output path to compare against). `--check` also now warns if both sets are already present (e.g. an
install from before this fix, or a manual `openspec init` run), so it's not silently missed.

While testing that cleanup live, found and documented (not yet acted on further) that the current
OpenSpec CLI lists its `windsurf` integration as "Devin Desktop (formerly Windsurf)" and, in that
same run, uses **three different command-naming conventions per agent** for the exact same
workflow: `/opsx:propose` for Claude Code, `/opsx-propose` for Cursor, `/openspec-propose` for
Windsurf/Devin. `STARTUP.md`'s routing table previously asserted one universal `/opsx-<name>` syntax
(itself wrong — it had said `/openspec-<name>`, matching none of the real, generated command files);
it now states the column is this kit's own static naming, calls out that it changes per agent once
`--openspec` has actually run, and points to the skill name / natural language as the naming-agnostic
fallback. The root `README.md`'s two `/openspec-propose` examples were the same bug and are fixed
the same way. The `.windsurf/` vs. `.devin/` directory question itself is out of scope for this
fix — flagged for a follow-up since it touches this kit's own agent-name mapping, not just wording.

## [1.2.0] - 2026-09-16

Fix: `STARTUP.md`'s "Callable Skills & Autonomous Invocation" section — the directive that tells the
agent to map natural-language requests to a skill on its own, plus the skill-routing table — was
never actually reaching any agent. `STARTUP.md` is copied into the destination's `.ai/STARTUP.md`
by `--copy`, but `combine_context_and_rules()` (which builds every agent's real, auto-loaded main
file — `CLAUDE.md`, `.github/copilot-instructions.md`, `.cursorrules`, `.windsurfrules`,
`.aiassistant/rules/project.md`) only ever concatenated `.ai/context/README.md` +
`.ai/rules/*.md`. `STARTUP.md` itself is never read automatically by any agent, so its "AI
Directive" and routing table were dead content — most consequential for Cursor/JetBrains/Copilot,
which (unlike Claude Code) have no confirmed native "discover and proactively invoke a skill"
mechanism of their own to fall back on.

`STARTUP.md`'s section 4 is now wrapped in `<!-- ai-starter-kit:startup-routing:start/end -->`
markers; `combine_context_and_rules()` takes a 4th argument (each `generate_<agent>()` now passes
`$dest/.ai/STARTUP.md`), extracts that marked block, and appends it as a "Callable Skills &
Autonomous Invocation" section to every agent's main file — inside the existing managed section, so
`--sync`/`--update` keep it current automatically. Also fixed `STARTUP.md`'s own "Receives prompt
files?" table, which incorrectly said Claude and Cursor don't receive prompt files (they do — for
years, wrongly contradicting the root `README.md` and `.ai/prompts/README.md`, and the actual
`generate_claude`/`generate_cursor` behavior which copies `.ai/prompts` into
`.claude/commands`/`.cursor/commands`).

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
