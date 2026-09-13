---
name: commit-and-push
description: Stage relevant changes, commit with a Conventional Commits message, push the branch, and open a pull request filled from the team's PR template. Use when the user asks to commit, push, or open a PR, or after finishing a logical unit of work that's ready for review.
---

# Commit, Push & Open PR — Usage Instructions

## Purpose

Turns a finished change into a reviewable pull request in one flow: stage → commit → push → open
a PR filled from `.github/pull_request_template.md`. Never runs against the repository's default
branch, and never force-pushes.

## When to use it

Use when the user asks to "commit this", "push my changes", "open a PR", or after completing a
scoped piece of work that's ready for review. Do not use for work-in-progress the user explicitly
wants to keep local or uncommitted, and do not chain straight into it after an unrelated task
without the user asking — committing and opening a PR are visible, shared-state actions.

## Steps

1. **Check the branch.** Run `git branch --show-current`. If it matches the repository's default
   branch (check `git remote show origin` or `gh repo view --json defaultBranchRef`), stop and ask
   the user to create a feature branch first. Never commit, push, or open a PR directly against
   the default branch.

2. **Review what would be committed.** Run `git status --short` and `git diff`. Stage only the
   files relevant to the current change (`git add <specific paths>`, or `git add -p` for partial
   files) — never `git add -A` / `git add .` blindly, since that can pull in unrelated local files
   or secrets.

3. **Write a Conventional Commits message** (`type(scope): description`, see
   `<AI_ROOT>/rules/development-guidelines.md`). Summarize the *why*, not a restatement of the diff.

4. **Commit.** `git commit -m "<message>"`.

5. **Push.** `git push -u origin <branch-name>` (the `-u` only matters on the branch's first push).
   Never use `--force` or `--force-with-lease`. If the push is rejected as non-fast-forward, stop
   and ask the user how they want to proceed instead of force-pushing on their behalf.

6. **Check for an existing PR first.** Run `gh pr view --json url` for the current branch. If one
   already exists, report its URL and stop here — do not create a duplicate.

7. **Fill the PR template.** Read `.github/pull_request_template.md` (fallback:
   `<AI_ROOT>/templates/pull_request_template.md` if the repo copy is missing). Fill in:
   - **Description** — summarize the commits on this branch, in your own words
   - **Type of change** — check only the box(es) that match the actual change
   - **How was this tested** — describe only tests/commands you actually ran this session; never
     claim testing you didn't do
   - Leave every other checklist item **unchecked** — those confirm things only the human
     author/reviewer can actually verify (self-review, docs, style), not you
   - **Token usage (if present):** if `specs/<current-branch>/.token-usage.json` exists (written by
     `~/.claude/statusline.py` and/or `~/.copilot/statusline.py`, configured via
     `install-ai-package.sh --statusline <claude|copilot>`), it's a JSON object keyed by tool name
     (e.g. `"claude"`, `"copilot"`), each with `input_tokens`/`output_tokens`/`turns` and,
     optionally, `cost_usd` (an estimate from published per-token pricing or a
     `TOKEN_PRICE_*_USD_PER_MTOK` override — present for Claude by default, only present for
     Copilot if the user configured those env vars, since Copilot has no published per-token
     rate). Add one line per tool key actually present, e.g. `Claude Code usage for this spec:
     {input_tokens} in / {output_tokens} out over {turns} turns` + `, ~${cost_usd} estimated` only
     if `cost_usd` is in that tool's entry + ` (main thread only — excludes subagent/Task-tool
     calls).` — plus, if more than one key is present, a combined total line (sum `cost_usd` across
     tools only if every present tool has one; otherwise state which tool's cost is missing rather
     than silently under-reporting the total). Use the file's real numbers verbatim — never
     estimate, round in a way that implies more precision than the source has, or fabricate a
     tool's line (or its `cost_usd`) when it isn't in the file (most repos won't have this file at
     all — that's fine, just omit the whole section).

8. **Open the PR.**
   ```bash
   gh pr create --title "<title>" --body-file <path-to-filled-template> --base <default-branch>
   ```
   Report the PR URL to the user.

## Guardrails

- Never commit, push, or open a PR against the repository's default branch.
- Never `git push --force` / `--force-with-lease` without the user explicitly asking for it.
- Never stage files you haven't reviewed — no blind `git add -A`.
- Never check a checklist box in the PR body for something you didn't verify yourself.
- If `gh` is not installed or not authenticated, stop after the push and tell the user how to open
  the PR themselves (`gh auth login`, or the web UI) — do not fabricate a PR URL.
- If a PR already exists for the branch, do not create a second one; report the existing one.
- Never invent a token-usage figure for the PR body — only include it when
  `specs/<branch>/.token-usage.json` actually exists, and always copy its numbers verbatim.

## Adapting for other Git hosts

This skill assumes GitHub (`gh` CLI) for steps 6-8. For GitLab, use `glab mr create` in place of
`gh pr create` (`glab mr view` for the duplicate check). For Bitbucket or others without an
equivalent CLI, use the REST API or ask the user to open the PR/MR manually from the pushed
branch — adjust this file for your host.
