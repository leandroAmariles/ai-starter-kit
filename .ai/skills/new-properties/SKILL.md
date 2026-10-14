---
name: new-properties
description: After an implementation, list the configuration properties that were added (e.g. @Value, @ConfigurationProperties, application*.yml) with a value for each, as a YAML snippet ready to paste into the environment's config yml. Returns nothing if no new properties were added. Use when the user asks for the new properties/config of an implementation, or right after /speckit-implement or /opsx-apply.
---

# new-properties — Usage Instructions

## Purpose

An implementation often introduces configuration keys that the deployed environment's config yml
(config server, ConfigMap, Helm values) does not have yet. This skill finds exactly those keys and
prints them, with values, as a YAML block to paste in. If there are none, it prints **nothing**.

## Steps

1. **Define the change set.** Use the diff of the work just done: `git diff <base>...HEAD` plus
   uncommitted changes (`git status`, `git diff`), where `<base>` is `main`/`master`/the branch the
   current one forked from. Never scan the whole repo — only what this implementation touched.
2. **Find new properties**, in this order:
   - Added/changed lines in `application*.yml|yaml|properties` (and `bootstrap*`): keys that did not
     exist before the change.
   - New `@Value("${a.b.c[:default]}")`, `@ConditionalOnProperty`, `@ConfigurationProperties(prefix=...)`
     classes/fields (each field becomes `prefix.field`, kebab-case), and `@Scheduled(cron = "${...}")`
     style placeholders in the diff.
   - Keys referenced in new/changed tests only are **not** new properties.
3. **Discard what already exists.** Compare against the base version of the same files
   (`git show <base>:<path>`); a key present there is not new. A property used with an inline default
   (`${a.b:30}`) is still new — the environment may want to override it.
4. **Choose a value for each**, in this order: value written in the new yml lines → default in the
   `@Value`/field initializer → value stated in the spec/plan (`spec.md`, `plan.md`, `design.md`) →
   a clearly marked placeholder (`<set-me>`). Values must be correct for a deployed environment, not
   a dev shortcut; never invent URLs or credentials.
5. **Secrets.** For passwords, tokens, keys, client secrets, emit an env placeholder
   (`${SERVICE_API_KEY}`) — never a literal value — and add a `# secret` comment.
6. **Output.** If there is at least one property, print a single fenced `yaml` block with the nested
   structure, a short trailing comment per key when the purpose is not obvious, and nothing else:

   ```yaml
   payments:
     invoice-export:
       enabled: true
       batch-size: 500
       api-key: ${PAYMENTS_API_KEY} # secret
   ```

   If there are none, output **no text at all** (no "no new properties" message, no empty block).

## Guardrails

- Read-only: do not edit any file, including the repo's own yml.
- Only properties introduced by this change; never list pre-existing ones.
- Never print real secrets found in the repo; redact to an env placeholder.
- Flag (one line, after the block) any property you had to leave as `<set-me>`, since that is the
  only case where the user must act.
