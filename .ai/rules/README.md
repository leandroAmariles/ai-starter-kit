# rules/

This directory stores the **global operational constraints** for your team/organization.

## Purpose

Rules that every AI agent must follow in any project built from this starter kit,
regardless of the specific context of the service.

## Files

| File | What it defines |
|---|---|
| `development-guidelines.md` | Code standards, naming, module structure, authorized tools |
| `auto-enrichment.md` | Protocol to auto-feed `<AI_ROOT>/` when new patterns are detected |
| `session-identity-canary.md` | Context-integrity self-check: print a fixed rules-loaded line at the first turn of a session, and treat an inability to recall which rules are active as a context-drift signal. Delete this file to disable it. |
| `skill-transparency.md` | At every turn, state which callable skill and/or context-skill(s) the response draws on (or that none apply). Delete this file to disable it. |

## Scope

These rules are **non-negotiable** and apply in every work session by default:
- Code language: English
- Commit format: Conventional Commits
- Change flow: propose → apply → archive (OpenSpec) or specify → plan → tasks → implement
  (spec-kit) — whichever spec-driven workflow this repo installed, see `<AI_ROOT>/skills/README.md`
- Internal libraries: prefer your organization's shared libraries when the functionality exists
- Do not block the reactive thread (if your stack is reactive)

Adjust these defaults to your own team's standards.

Keep agent-specific conventions (e.g. a commit co-author trailer required by a particular AI tool)
out of these shared files — they get concatenated into **every** agent's generated instructions.
Put them instead in that agent's own configuration after installation.
