---
name: loop-spec
description: Revise a spec-kit feature's spec.md after implementation started (or finished) - scoped to only the requirement, scenario, or entity that broke or changed - then cascade that same scoped edit into plan.md and tasks.md so the SDD cycle can resume on just the delta, handing off to /speckit-implement. Use when a bug reveals a wrong/missing requirement, or a stakeholder decision changes scope, for a spec-kit feature. Never for drafting a brand-new feature (use /speckit-specify) and never to regenerate an entire spec/plan/tasks file at once.
---

# loop-spec — Usage Instructions

## Purpose

spec-kit's own cycle (`constitution → specify → clarify → plan → tasks → analyze → implement`) is
built to run forward once: `/speckit-plan` and `/speckit-tasks` each regenerate their artifact from
the current `spec.md`. That's the right tool for standing up a new feature, but it has no scoped
"just fix this one requirement" mode - re-running it after implementation has already started would
blow away completed-task history and any plan/tasks content unrelated to the fix.

`loop-spec` is that missing scoped-update step, the spec-kit equivalent of this kit's
`openspec-update-change`. It closes the loop when reality diverges from the spec mid-flight or
after the fact: find the smallest edit to `spec.md`, cascade only what that edit actually touches
into `plan.md` and `tasks.md`, and hand off to `/speckit-implement` to execute just the delta - so
the feature can go through **plan → tasks → implement** again without redoing everything.

## When to use it

- Implementation (or QA, or a later bug report) revealed that a requirement, acceptance scenario,
  or key entity in `spec.md` was wrong, ambiguous, or incomplete.
- A stakeholder decision changed the scope of one part of an already-specified feature.
- Tasks are fully checked off and the feature shipped, but the discovered issue means the spec no
  longer matches what should exist - a post-implementation correction, not new work.

Do **not** use it to:
- Draft a brand-new feature - use `/speckit-specify` for that.
- Make a sweeping redesign that touches most of the spec - at that point re-running
  `/speckit-plan`/`/speckit-tasks` in full (or a fresh `/speckit-specify`) is the honest choice; say
  so and stop rather than forcing a "scoped" edit that isn't one.
- Edit application code - this skill never leaves the planning artifacts. The actual code change is
  `/speckit-implement`'s job, invoked after this skill hands off.

## Steps

1. **Confirm spec-kit is installed and find the feature.**
   - Check `.specify/` exists. If not, stop and point to this repo's `README.md` "Choosing a
     spec-driven workflow" section (`./install-ai-package.sh --workflow speckit ...` /
     `--speckit <agents> <repo>`) - there is nothing to loop without it.
   - Resolve the active feature directory under `specs/`. Prefer the one matching
     `git branch --show-current` (spec-kit names feature branches after their `specs/<NNN-slug>/`
     directory). If it doesn't match one, or more than one plausibly matches, list the candidates
     under `specs/` and ask the user to pick.

2. **Read current state from disk - never from conversation memory.**
   - Read the feature's `spec.md`, and `plan.md`/`tasks.md` if they exist (a feature may be mid-cycle
     with no plan/tasks yet).
   - If `.specify/templates/spec-template.md`, `plan-template.md`, `tasks-template.md` exist, read
     them too - they define this installation's actual section headers and ID conventions (e.g.
     `FR-00N`, `T0NN`). Don't assume a fixed template; match what's really in the files and templates.

3. **Understand what changed.** If the user's request doesn't already state it precisely, ask:
   - What broke, or what changed - quote the exact requirement/scenario/entity if possible.
   - Whether this is a correction (the spec was wrong) or a scope change (the world changed).
   - Ambiguity here changes what gets edited, so don't guess past it.

4. **Make the scoped edit to `spec.md`.**
   - Locate the single functional requirement, acceptance scenario, or key entity the change
     affects. Edit only that block - do not touch unrelated requirements, restructure sections, or
     rewrite the file's prose style.
   - Show the proposed diff and why. Write only after the user confirms. If the user rejects it,
     leave `spec.md` unchanged and stop.
   - If the requirement doesn't exist yet (this is new, not a correction), add it as a new block
     using the existing numbering scheme (next unused `FR-00N`), placed with its related requirements
     - not appended blindly at the end.

5. **Cascade into `plan.md`, scoped to the same delta.**
   - Search `plan.md` for the requirement ID, the user story, or the keywords the edit touched.
   - If nothing references it, say so and leave `plan.md` untouched.
   - If something does, propose the smallest edit to that section (a design decision, a data-model
     entry, a contract) - never a full regeneration. Confirm before writing, same as step 4.

6. **Cascade into `tasks.md`, scoped to the same delta.**
   - Search `tasks.md` for tasks tied to the changed requirement/user story.
   - For an affected task still unchecked (`- [ ]`): propose either updating its description to
     match the corrected requirement, or replacing it with a corrected task - ask the user which reads
     better. Keep its task ID.
   - For an affected task already checked (`- [x]`): leave it as the historical record - do not
     uncheck or delete it. Add a new task, at the next unused task ID, in the correct phase section,
     capturing the follow-up work needed to bring the implementation in line with the corrected
     requirement.
   - For a requirement that was removed entirely: mark its now-obsolete unchecked tasks for removal
     (confirm with the user) rather than silently deleting them; leave checked ones as history with a
     one-line note that they're superseded.
   - Never renumber existing task IDs and never touch tasks unrelated to this delta.

7. **Hand off - don't implement.**
   - Summarize what changed in `spec.md`, `plan.md`, and `tasks.md` (and what you deliberately left
     untouched).
   - If `/speckit-analyze` is available in this installation, suggest running it next to catch any
     cross-artifact inconsistency this scoped pass didn't cover.
   - Point to `/speckit-implement`, naming the specific new/updated task IDs, to execute just the
     delta. Stop here - do not start implementing in the same turn.

8. **This is a loop, not a one-shot.** Nothing here archives or closes the feature. The next time
   implementation surfaces a mismatch, or the spec changes again, re-enter at step 1.

## Guardrails

- Never rewrite `spec.md`, `plan.md`, or `tasks.md` wholesale - always find the smallest edit that
  captures the change. If you can't find one, say so instead of forcing it.
- Never edit code - this skill stops at the planning artifacts and hands off to `/speckit-implement`.
- Confirm every proposed edit with the user, file by file, before writing it.
- Always re-read `spec.md`/`plan.md`/`tasks.md` from disk before editing - the user may have changed
  them since this conversation started.
- Never invoke `/speckit-plan` or `/speckit-tasks` to regenerate an artifact from scratch as part of
  this flow - that both defeats the purpose and discards unrelated content and completed-task history.
- Never uncheck or delete an already-completed task; a correction after the fact becomes a new task,
  not a rewritten history.
- If the requested change is really a new feature or a sweeping redesign, say so and point to
  `/speckit-specify` (or a full plan/tasks regeneration) instead of stretching this skill to fit.
