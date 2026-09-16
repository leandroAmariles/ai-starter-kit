# Skill Usage Transparency

At every assistant turn in this session — not just the first — disclose which skills you are
drawing on for that specific response, before doing the substantive work:

- **Callable skill invoked** (`<AI_ROOT>/skills/*`, e.g. `openspec-propose`, `commit-and-push`,
  `neo4j-architecture-graph`, or any project-specific skill added under `<AI_ROOT>/skills/`):
  whether triggered by an explicit command or by mapping natural language to it yourself (see
  `<AI_ROOT>/STARTUP.md`'s routing table), name it explicitly — e.g. "Using skill: commit-and-push."
- **Context-skill(s) applied** (`<AI_ROOT>/context/skills/*`, e.g. `hexagonal-architecture`,
  `reactive-programming`, `testing-java`, `domain-modeling`, `observability`,
  `error-translation`, or any project-specific ones added later): name only the ones actually
  shaping this response's reasoning or code — not the full list every time.
- If neither applies — the turn is pure conversation, a read-only question, or general work that
  doesn't draw on any documented skill — say so explicitly (e.g. "No skills used this turn.")
  rather than staying silent.

This is a one-line disclosure, not a summary of the skill's content or a re-explanation of what it
does — name it, then proceed. Keep it accurate: naming a skill you did not actually apply, or
staying silent about one you did, defeats the purpose of this rule. This is independent of, and in
addition to, `session-identity-canary.md`'s once-per-session check.
