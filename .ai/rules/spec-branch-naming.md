# Spec branch naming (spec-kit)

Applies whenever you run `/speckit-specify` (or any request to specify a new feature/fix with
spec-kit). Stock spec-kit names the branch and the spec directory `NNN-slug` (sequential) — no type
prefix, no User Story number — so this rule overrides that default. Do **not** accept the default.

## Before specifying

1. Get the **User Story number** (e.g. `1234`) and the **change type** from the user's request. If
   either is missing, ask for it — never invent a number and never fall back to `001`.
2. Map the type to a prefix: `feature`, `fix`, `hotfix`, `chore`, `refactor`, `docs`. Default to
   `feature` only if the user clearly describes new functionality.
3. Derive a short kebab-case `<slug>` from the description (2–5 words).

## Names to use

- Directory name: `<slug>` (e.g. `1234-export-invoices`)
- Branch name: `<type>/<slug>` (e.g. `feature/1234-export-invoices`)

The branch's **last path segment must equal the spec directory name** — the statusline token
tracker and `loop-spec` match `specs/<last segment of branch>/`.

## How to apply it

- Pass `GIT_BRANCH_NAME=<type>/<slug>` to the `before_specify` git hook so it uses that exact
  branch instead of auto-generating `NNN-slug`.
- Set `SPECIFY_FEATURE_DIRECTORY=specs/<slug>` so the directory is created with the same name.
- Write `.specify/feature.json` with that **resolved** path (`{"feature_directory":
  "specs/<slug>"}`), never the literal variable name.

## Verify before finishing

Run `git branch --show-current` and read `.specify/feature.json`. Confirm the branch is
`<type>/<slug>`, the directory exists, and `feature.json` points to it. If any of the three
disagree, fix it (rename the branch or directory, rewrite `feature.json`) and report what you
changed. Never leave the work on the default branch.
