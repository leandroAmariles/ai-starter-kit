# prompts/

This directory stores **prompt files** — predefined command shortcuts that some AI coding
tools can invoke directly from the editor, as if they were a command.

## Structure

```
prompts/
├── README.md               ← this file
├── opsx-propose.prompt.md
├── opsx-apply.prompt.md
├── opsx-update.prompt.md
├── opsx-explore.prompt.md
├── opsx-sync.prompt.md
└── opsx-archive.prompt.md
```

## What is a prompt file?

A `.prompt.md` file is a predefined instruction that can be invoked directly
from the editor as if it were a command. It reduces the friction of remembering the exact syntax
of each skill and ensures that the correct context is passed. These mirror the `openspec-*` callable
skills in `<AI_ROOT>/skills/`.

## Compatibility

`install-ai-package.sh` distributes these prompt files to:
- **GitHub Copilot** — `.github/prompts/`
- **Claude** — `.claude/commands/` (Claude Code's native custom-slash-command directory)
- **Cursor** — `.cursor/commands/`

Windsurf and JetBrains AI don't get a separate copy of these — Windsurf already gets equivalent,
fuller content as `.windsurf/workflows/<name>.md` generated directly from `<AI_ROOT>/skills/*`
(see `<AI_ROOT>/skills/README.md`), and JetBrains AI has no confirmed native command-file
convention in this kit yet. This only describes this kit's own static/frozen OpenSpec snapshot: once
`--openspec windsurf <repo>` actually runs the real CLI, that content moves out of `.windsurf/`
entirely, to `.devin/skills/*` + `.devin/workflows/opsx-*.md` — the CLI has renamed that integration
"Devin Desktop (formerly Windsurf)" (`windsurf` is now only a deprecated alias for its real `devin`
`--tools` value). See the root `README.md`'s "About `windsurf` → `devin`" note for details.

If you chose **spec-kit** or **OpenSpec via `--openspec`** (see the root `README.md`), the official
CLI generates its own command files directly in each agent's native location, at a different path
than what's copied from here (confirmed: nested under `.claude/commands/opsx/*` /
`.cursor/commands/opsx/*` for OpenSpec, rather than this kit's flat `opsx-*.prompt.md`) — the two
sets never collide by filename, but once the real CLI's copy exists it supersedes this kit's static
one; `--openspec <agents> <repo>` removes the now-stale static files automatically, and `--check`
flags it if an older install still has both.
