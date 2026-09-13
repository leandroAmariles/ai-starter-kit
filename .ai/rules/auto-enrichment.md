# Auto-enrichment Protocol

## Purpose

When the agent detects a new reusable pattern during a session, it must NOT pause, ask for prior permission, or interrupt the main task to document it. It should immediately launch a background sub-agent to investigate the pattern and draft an enrichment proposal independently. The main agent continues its work without waiting for that result. The sub-agent's proposal arrives asynchronously in a separate message.

**Fallback:** For environments without real background agent capabilities, the agent should formulate the proposal and print it at the end of its response after completing the current step of the main task.

## Detection criteria

It is considered a new pattern when any of these cases appear:
- A new architectural or modular structure that is not covered by any existing context-skill
- A recurring integration pattern with an undocumented library
- A new testing idiom used 2 or more times
- A new error handling convention

It is NOT considered a new pattern when it involves:
- Single-use feature-specific code
- Minor variations of already documented patterns
- Framework boilerplate
- Project-specific code

## Destination table

| Pattern type | Destination |
|---|---|
| Architecture / module structure | `<AI_ROOT>/context/skills/hexagonal-architecture.md` |
| Testing patterns | `<AI_ROOT>/context/skills/testing-java.md` |
| Observability | `<AI_ROOT>/context/skills/observability.md` |
| Reactive programming | `<AI_ROOT>/context/skills/reactive-programming.md` |
| Error handling | `<AI_ROOT>/context/skills/error-translation.md` |
| New skill (no match) | `<AI_ROOT>/context/skills/<new-skill>.md` (ask explicitly) |
| Library integration guide | `<AI_ROOT>/support/<library>-patterns.md` |
| Team rule | `<AI_ROOT>/rules/<name>.md` |

## Sub-agent protocol

1. The main agent detects the pattern and immediately launches a background sub-agent (or prepares it for the end of the response), without pausing the main work.
2. The sub-agent reads the related skill or file, identifies what information is truly new, and drafts an addition or change proposal.
3. The sub-agent presents exactly this format: `🔍 New pattern detected: [name]. Incorporate to <AI_ROOT>/context/skills/[file].md?` followed by a diff preview.
4. If the user approves, the proposed edit is applied.
5. If the user rejects, the proposal is discarded and not followed up on.
6. The main agent remains unaware of the proposal, unless the user explicitly mentions it.

## Autonomy limit

- Never create new files without explicit user permission
- Never modify existing skills without showing a diff first
- Only one proposal per pattern per session; if rejected, do not propose again
- Never propose enrichments for project-specific code
