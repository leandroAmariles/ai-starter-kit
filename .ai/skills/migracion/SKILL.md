---
name: migracion
description: End-to-end Spring Boot 4 migration orchestrator. Use whenever the user simply asks to migrate a Java/Maven service to Spring Boot 4, Spring 7, Jackson 3 or the BAC parent ("migra este repo", "haz la migración", "migrate to Spring Boot 4"). Collects the missing inputs, installs the tooling if needed, then runs code-context-builder followed by spring-boot-4-migration, gating each step on the previous one.
---

# migracion — Spring Boot 4 migration orchestrator

One entry point for the pipeline. It does not duplicate the rules of the two skills it drives; it
collects inputs, verifies prerequisites, runs them in order, and stops at each gate. Reply in the
user's language.

Sequence: **inputs → prerequisites → code-context-builder → gate → spring-boot-4-migration → report**.

## Step 1 — Collect inputs (ask only what is missing)

Ask everything still unknown in a single message, proposing a default for each:

| Input | Required | Default / how to resolve |
|---|---|---|
| Maven reactor root to migrate (folder with the root `pom.xml`) | Yes | Propose the current repo root; **the user must confirm it** — never infer silently. |
| Approved parent POM (`com.bac.core:banca-digital-parent-pom:7.0.0-SNAPSHOT`) | Yes, unless `.ai/migration-context/pom.xml` already exists | Ask for its path. |
| Maven profiles needed to compile/test | No | None. |
| Modules to exclude from the migration | No | None. |
| Tests that need external infrastructure and must be skipped | No | None. |
| May the app be started locally? May DB schema migrations be created? | No | No / No. |
| Jackson 2 coexistence acceptable? Known internal BAC library constraints? | No | No / none. |

Do not proceed past this step until the target folder is confirmed and the parent POM is available.

## Step 2 — Verify prerequisites (fix what you can, ask before changing anything)

1. `migration-tools/code-context-builder/pom.xml` exists in the repo. If not, tell the user it is
   missing and, with their approval, run `./ai-bootstrap.sh --migration --parent-pom <path>` (or
   `install-ai-package.sh --migration <repo> --parent-pom <path>` from a kit clone). Never download
   or write a copy of the tool yourself.
2. `.ai/migration-context/pom.xml` exists. If the user gave a path and it is missing, copy it there
   (never overwrite an existing one). Never modify it afterwards.
3. `mvn -version` runs on JDK 17 or newer; report the JDK Maven uses.
4. `git status --short` of the target: if there are unrelated uncommitted changes, warn and get an
   explicit go-ahead (or suggest a clean branch) — the migration diff must stay reviewable.
5. `.ai/migration-context/` is git-ignored (the installer does this; if not, offer to add it).

## Step 3 — Generate context

Invoke the **`code-context-builder`** skill for the confirmed target and follow it exactly. When it
returns, show the user a short summary (modules, parse coverage, findings by severity, artifact
paths — never the XML contents).

**Gate A:** continue only if the result is `complete`. If there are parse errors, truncation,
omissions or XML validation failures, list them and ask whether to (a) fix/inspect the affected
files and re-run, or (b) proceed knowingly with incomplete context (the migration skill will then
inspect those files directly). Do not proceed on your own.

## Step 4 — Migrate

Invoke the **`spring-boot-4-migration`** skill with the same target folder and the extra
information collected in Step 1 (profiles, exclusions, skipped tests, local startup, schema
migrations, Jackson 2 policy, BAC library constraints). Let it apply its own stop conditions
(context/parent mismatch, stale context) — if it stops, relay why and offer the fix (usually
re-running Step 3) rather than working around it.

If the source project starts on Spring Boot 2 / Spring Framework 5, that skill will refuse the
direct jump; surface that to the user as the plan (Boot 2 → 3 first) instead of forcing it.

## Step 5 — Final report

Return the report the migration skill defines (context/freshness, files changed, effective parent
and resolved Spring Boot/Framework/Java/Cloud/Jackson versions, validation commands and results,
blockers, Jackson 2 leftovers, guide applicability, discrepancies), plus:

- What was skipped or could not run, and why.
- Files that must **not** be committed: `.ai/migration-context/`, `migration-tools/` (unless the
  team chose to version it), `target/`, effective POMs, `.github/leo-assistant/`, module-level
  generated `.gitignore`.
- The pre-production checklist (staging, traffic, rollback, feature flags, DB migration order,
  monitoring) — provided, never executed.
- Suggested next step: review the diff, then use `commit-and-push`.

## Guardrails

- Never skip a gate or run the migration on incomplete context without the user's explicit consent.
- Never deploy, publish, shift traffic, or run DDL against a shared database.
- Never echo secrets from Maven settings, environment variables, or configuration.
- Never edit `migration-tools/`, `.ai/migration-context/`, or the parent POM.
- Do not claim success unless the Maven validation the migration skill requires actually ran.
