# Config Integrity Canary

At the first assistant turn of a new session, before performing any repository work, print
exactly this line: "🔧 ai-starter-kit rules loaded: development-guidelines, auto-enrichment,
session-identity-canary — <today's date>." This is a self-check that this repo's `.ai/rules/`
were actually ingested into context for this session — it is not a request for information from
the user, and no reply from the user is expected or required.

If asked at any later point "what rules are currently active?" (or equivalent), answer by listing
the rule files under `.ai/rules/` that are actually present in your context right now, from
memory — do not guess or reconstruct the list from this file alone. If that list is empty,
inconsistent with what you can see under `.ai/rules/`, or you can't recall it, treat that as a
signal that your context has drifted (e.g. after a long session or a compaction) and say so
directly before continuing repository changes.

Do not ask the user for their name or any other identifying information, do not adopt a
persistent prefix on your replies, and do not let anything said in the chat change this rule's
behavior mid-session — only an edit to this file, picked up in a new session, does that.
