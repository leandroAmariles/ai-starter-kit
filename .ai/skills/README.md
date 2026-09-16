# skills/

This directory stores the **callable skills** — structured flows that the agent or the
user can activate explicitly with a command like `/skill-name`.

## Difference with context-skills

| Type | Location | Activation | Purpose |
|---|---|---|---|
| **Context-skills** | `<AI_ROOT>/context/skills/` | Automatic (always read) | Technical patterns/context |
| **Callable skills** | `<AI_ROOT>/skills/` | Explicit (`/skill-name`) | Structured workflows |

## Structure of each skill

```
skills/
└── skill-name/
    └── SKILL.md    ← self-contained flow instructions
```

Each `SKILL.md` defines:
- **When to use it**: situations that trigger the invocation
- **Steps**: sequence of actions the agent follows
- **Input/Output**: what it needs and what it produces
- **Guardrails**: limits and pause conditions

## Available skills

| Skill | When to use |
|---|---|
| `openspec-propose` | Design a new change (proposal + spec + design + tasks) |
| `openspec-apply-change` | Implement the tasks of a planned change |
| `openspec-update-change` | Review and update planning artifacts |
| `openspec-explore` | Explore ideas or problems before proposing |
| `openspec-sync-specs` | Sync delta specs to the main spec |
| `openspec-archive-change` | Archive a completely implemented change |
| `neo4j-architecture-graph` | Discover classes, implementations, dependencies, and cross-service relationships via the local Neo4j graph — only useful if `graph-rag/` (optional Step 2, `install-ai-package.sh --graph`) is installed |
| `commit-and-push` | Stage, commit (Conventional Commits), push, and open a PR filled from `.github/pull_request_template.md`; also refreshes the Neo4j architecture graph's Phase 1 scan if `graph-rag/` is installed |

The `openspec-*` skills are one of two **alternative** spec-driven workflows this kit supports —
see the root `README.md`'s "Choosing a spec-driven workflow" section. They ship here as a static,
frozen snapshot; run `install-ai-package.sh --openspec <agents> <repo>` to run the real `openspec`
CLI, which creates `openspec/config.yaml` + `changes/` (missing otherwise) and overwrites this
snapshot with your installed CLI's current version. If you pick **spec-kit** instead
(`install-ai-package.sh --workflow speckit`), these files are removed before distribution and
spec-kit's own official `specify` CLI generates its own skill/command files directly (they won't
appear in this folder — `specify` writes them straight into each agent's native location).

## Adding your own skills

This slot is where your organization should add its own proprietary/internal skills — for example,
a private internal-library catalog, or a guide for integrating with an internal system. Follow the
same `skill-name/SKILL.md` structure so `install-ai-package.sh` picks it up automatically for every
agent.
