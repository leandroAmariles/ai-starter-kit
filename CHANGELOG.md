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
