# context/skills/

This directory contains the **context-skills**: distilled architectural and implementation
patterns that the agent absorbs automatically when starting a session, **without explicit invocation**.

## What are context-skills

Context-skills capture decisions, conventions, and implementation patterns worth repeating across
projects. They are not callable flows; they are persistent operational context for the agent to
reason and execute with better alignment to your stack and style.

They must be read **at the beginning of each session** to incorporate these guidelines before
analyzing, designing, or modifying code.

## Skills in this directory

- **hexagonal-architecture**: organization by ports and adapters, boundaries between domain, application, and infrastructure.
- **testing-java**: testing strategy for Java services, useful coverage, types of tests, and common conventions.
- **observability**: logging, metrics, traceability, and practices to make diagnostics operable in production.
- **reactive-programming**: consistent use of reactive flows, composition, backpressure handling, and errors.
- **error-translation**: translation of technical errors to coherent and traceable business/API responses.
- **domain-modeling**: strict rules for domain object hydration, explicitly forbidding dynamic tools (ObjectMapper/Map) in favor of MapStruct.

These default to a Java/Spring/Maven profile. To support another stack, add or replace files here
following the same structure (What this pattern is → How to apply it → Anti-patterns).

## Difference with `<AI_ROOT>/skills/`

Files in `<AI_ROOT>/context/skills/` are incorporated as **automatic context**: the agent reads and applies them without anyone invoking them.

The contents of `<AI_ROOT>/skills/`, on the other hand, are **callable skills**: explicit flows that are activated on demand to execute structured processes.
