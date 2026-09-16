#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
AI_SOURCE="$SCRIPT_DIR/.ai"
GRAPH_RAG_SOURCE="$SCRIPT_DIR/graph-rag"

supports_color() {
  [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]] && [[ "${TERM:-}" != "dumb" ]]
}

if supports_color; then
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  RED='\033[0;31m'
  BLUE='\033[0;34m'
  NC='\033[0m'
else
  GREEN=''
  YELLOW=''
  RED=''
  BLUE=''
  NC=''
fi

_QUIET=false
ok()   { ${_QUIET} && return 0; printf '%b✓%b %s\n' "$GREEN" "$NC" "$*"; }
warn() { printf '%b⚠%b %s\n' "$YELLOW" "$NC" "$*"; }
err()  { printf '%b✗%b %s\n' "$RED" "$NC" "$*" >&2; }
info() { printf '%b•%b %s\n' "$BLUE" "$NC" "$*"; }

_progress_bar() {
  [[ -t 1 ]] || return 0
  local current="$1" total="$2" label="${3:-}"
  local width=28 pct filled bar
  pct=$(( total > 0 ? 100 * current / total : 0 ))
  filled=$(( total > 0 ? width * current / total : 0 ))
  bar="$(printf '%*s' "$filled" '' | tr ' ' '█')$(printf '%*s' "$(( width - filled ))" '' | tr ' ' '░')"
  printf '\r  %b[%s]%b %3d%% (%d/%d) %-24s' "$BLUE" "$bar" "$NC" "$pct" "$current" "$total" "$label"
  [[ "$current" -ge "$total" ]] && printf '\n'
}

usage() {
  cat <<EOF2
Usage:
  $(basename "$0") --init <destination-repo>
  $(basename "$0") --copy <destination-repo>
  $(basename "$0") --scan <destination-repo>
  $(basename "$0") --agents <copilot,claude,cursor,windsurf,jetbrains> <destination-repo>
  $(basename "$0") --sync <destination-repo>
  $(basename "$0") --update <destination-repo>
  $(basename "$0") --check <destination-repo>
  $(basename "$0") --workflow <openspec|speckit|none> <destination-repo>
  $(basename "$0") --openspec <agent1,agent2,...> <destination-repo>
  $(basename "$0") --speckit <agent1,agent2,...> <destination-repo>
  $(basename "$0") --graph <destination-repo>
  $(basename "$0") --statusline <claude|copilot>
  $(basename "$0") --help

Modes:
  --init     Interactive wizard (recommended): prompts for which agent(s), which
             spec-driven workflow (OpenSpec / spec-kit / none), and whether to install
             the optional Neo4j graph, then runs every step below for you.
  --copy     Copy .ai/ into the destination repository using cp -rn. Step 1 (required).
  --scan     Analyze the destination repository and generate .ai/context/project-context.md.
  --agents   Generate native AI agent files from .ai/ for the requested agents.
  --sync     Regenerate native AI files for agents already detected in the destination.
  --update   One-shot upgrade of an already-installed <destination-repo> to the kit's current
             version — leaves it ready to use, no follow-up commands needed. Pulls the current
             .ai/ content in file by file (adds files new since the installed version, refreshes
             files the repo never customized, leaves alone — with a *.new sibling — any file the
             repo edited; tracked via .ai/VERSION and .ai/.ai-manifest.json, a per-file sha256
             baseline written automatically by --copy/--update, never edit it by hand; files
             intentionally removed at the destination, e.g. by --workflow, are never recreated),
             then automatically regenerates native files for every agent already detected (same as
             --sync) and finishes with the same validation as --check. See CHANGELOG.md for what
             changed between versions.
  --check    Post-install validation: confirms .ai/ and each detected agent's main file and
             skill/workflow files exist and have valid front-matter, warns if the configured
             spec-driven workflow's real CLI setup (openspec/config.yaml, .specify/) or the
             optional graph-rag/PR template are missing, and flags absent prerequisites
             (git always; docker/python, node/npx, uv/uvx only if that piece is installed).
             Exits non-zero only on hard errors (e.g. a missing/empty agent main file).
  --workflow Choose the spec-driven workflow non-interactively:
               openspec — keep the static skills/prompts shipped in .ai/ as a default/fallback
                          (default). Run --openspec afterward to also run the real CLI, which
                          creates openspec/config.yaml + changes/ and refreshes the skill files —
                          without it, the skills reference commands that have nothing to act on.
               speckit  — remove the OpenSpec skills/prompts and delegate to GitHub's
                          official 'specify' CLI (via uv/uvx) for every agent already
                          generated in the destination
               none     — remove the OpenSpec skills/prompts, install neither
             Run this BEFORE --agents/--sync so the choice is reflected in generated files.
  --openspec Run the official OpenSpec CLI ('openspec init --tools <slug> --force', via npx if
             not already installed) for each agent in the given comma-separated list. Creates
             openspec/config.yaml + changes/ and overwrites the static .ai/skills/openspec-*
             snapshot with your installed CLI's own current version (used internally by
             --init; callable directly for scripting).
  --speckit  Run the official spec-kit 'specify init --integration <agent>' for each
             agent in the given comma-separated list (used internally by --workflow speckit
             and --init; callable directly for scripting).
  --graph    OPTIONAL step 2: copy graph-rag/, then bootstrap and run the local Neo4j
             architecture graph (creates its venv, installs deps, starts Neo4j via Docker
             Compose, runs the Phase 1 scan). See graph-rag/README.md to configure multiple
             projects (PROJECT_PATHS). Every step degrades gracefully with an actionable
             warning if Docker/Python aren't available, instead of failing the install.
  --statusline OPTIONAL, user-level (not project-scoped): installs ~/.<target>/statusline.py and
             wires it into ~/.<target>/settings.json's statusLine, for <target> = "claude"
             (default) or "copilot". Also run automatically by --agents/--init whenever that
             agent is selected. Shows running token usage, and — if the current branch matches a
             specs/<branch>/ directory (spec-kit convention) — accumulates tokens into
             specs/<branch>/.token-usage.json (under a "claude" or "copilot" key, so both can
             accumulate into the SAME file without clobbering each other) so the commit-and-push
             skill can report a real total in that spec's PR. Each entry also gets a cost_usd
             estimate: Claude defaults to Anthropic's published per-model pricing (looked up by
             the model id in the statusline payload); Copilot has no published per-token rate, so
             its cost_usd is only computed if you set TOKEN_PRICE_INPUT_USD_PER_MTOK and
             TOKEN_PRICE_OUTPUT_USD_PER_MTOK yourself (USD per 1M tokens — same two env vars
             override Claude's default too, e.g. for partner/Bedrock pricing). Only sees each
             tool's own main thread; does not include subagent/Task-tool token usage (no verified
             way to capture that today). Never overwrites an existing statusline.py or statusLine
             config — warns instead. Requires restarting the agent to take effect. Cursor CLI has
             an officially
             documented equivalent (per-turn tokens included) but is not wired up yet — no
             confirmed usage of it in this kit's own projects to build/test against. Windsurf's
             hook system and JetBrains have no confirmed equivalent.
  --help     Show this help message.

Examples:
  $(basename "$0") --init /path/to/repo
  $(basename "$0") --copy /path/to/repo
  $(basename "$0") --workflow speckit /path/to/repo
  $(basename "$0") --scan /path/to/repo
  $(basename "$0") --agents copilot,claude,cursor /path/to/repo
  $(basename "$0") --openspec copilot,claude /path/to/repo
  $(basename "$0") --sync /path/to/repo
  $(basename "$0") --update /path/to/repo
  $(basename "$0") --check /path/to/repo
  $(basename "$0") --graph /path/to/repo
  $(basename "$0") --statusline copilot
EOF2
}

require_arg() {
  local value="${1:-}"
  local message="$2"
  if [[ -z "$value" ]]; then
    err "$message"
    usage
    exit 1
  fi
}

ensure_source_exists() {
  if [[ ! -d "$AI_SOURCE" ]]; then
    err "Source .ai directory not found at $AI_SOURCE"
    exit 1
  fi
}

ensure_dest_exists() {
  local dest="$1"
  if [[ ! -d "$dest" ]]; then
    err "Destination directory does not exist: $dest"
    exit 1
  fi
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

append_section_file() {
  local output_file="$1"
  local title="$2"
  local input_file="$3"

  [[ -f "$input_file" ]] || return 0

  {
    printf '\n## %s\n\n' "$title"
    cat "$input_file"
    printf '\n'
  } >> "$output_file"
}

MANAGED_SECTION_START="<!-- ai-starter-kit:managed-section:start (regenerated by install-ai-package.sh --sync — edit .ai/ instead of this block; nothing above this line is touched) -->"
MANAGED_SECTION_END="<!-- ai-starter-kit:managed-section:end -->"

combine_context_and_rules() {
  local dest_file="$1"
  mkdir -p "$(dirname "$dest_file")"

  local tmp_file
  tmp_file="$(mktemp)"

  # Three cases:
  #  1. New file: nothing to preserve.
  #  2. Existing file, no managed-section marker: this predates the kit (a
  #     real, human-authored CLAUDE.md/copilot-instructions.md/etc.) — keep
  #     100% of it and append the managed block below, so re-running the
  #     installer against an already-established repo enriches it instead of
  #     either silently skipping it or destroying real content (both of
  #     which have happened here before).
  #  3. Existing file, marker present: a previous run of this same function
  #     — keep everything before the marker (the human preamble, plus any
  #     edits made there since) and regenerate only the managed block.
  if [[ -f "$dest_file" ]]; then
    if grep -qF "$MANAGED_SECTION_START" "$dest_file"; then
      awk -v m="$MANAGED_SECTION_START" '$0==m{exit} {print}' "$dest_file" > "$tmp_file"
    else
      cp "$dest_file" "$tmp_file"
      printf '\n' >> "$tmp_file"
      info "$dest_file predates this kit — appending managed content below its existing content."
    fi
  fi

  printf '%s\n' "$MANAGED_SECTION_START" >> "$tmp_file"

  append_section_file "$tmp_file" "Project Context" "$2"

  local rule_file
  while IFS= read -r rule_file; do
    local base title
    base="$(basename "$rule_file" .md)"
    title="$(printf '%s' "$base" | tr '-' ' ')"
    append_section_file "$tmp_file" "$title" "$rule_file"
  done < <(find "$3" -maxdepth 1 -type f -name '*.md' ! -name 'README.md' | sort)

  printf '%s\n' "$MANAGED_SECTION_END" >> "$tmp_file"

  mv "$tmp_file" "$dest_file"
}

list_non_readme_markdown() {
  local dir="$1"
  find "$dir" -maxdepth 1 -type f -name '*.md' ! -name 'README.md' | sort
}

skill_slug() {
  basename "$1" .md
}

skill_title() {
  local slug
  slug="$(skill_slug "$1")"
  printf '%s' "$slug" | tr '-' ' '
}

first_nonempty_line() {
  local file="$1"
  awk 'NF { print; exit }' "$file"
}

ensure_gitignore_entry() {
  local dest="$1" pattern="$2" comment="${3:-}"
  local gitignore="$dest/.gitignore"
  [[ -f "$gitignore" ]] || : > "$gitignore"
  grep -qxF "$pattern" "$gitignore" 2>/dev/null && return 0
  {
    [[ -s "$gitignore" ]] && printf '\n'
    [[ -n "$comment" ]] && printf '# %s\n' "$comment"
    printf '%s\n' "$pattern"
  } >> "$gitignore"
  ok "Added '$pattern' to $gitignore"
}

copy_dir_if_present() {
  local src="$1"
  local dest="$2"
  if [[ -d "$src" ]]; then
    mkdir -p "$dest"
    cp -R "$src"/. "$dest"/
    ok "Copied $(basename "$src") to $dest"
  else
    warn "Directory not found, skipping: $src"
  fi
}

write_context_skill_copy() {
  local src_file="$1"
  local dest_file="$2"
  mkdir -p "$(dirname "$dest_file")"
  cp "$src_file" "$dest_file"
  ok "Generated $dest_file"
}

write_cursor_rule() {
  local src_file="$1"
  local dest_file="$2"
  local description
  description="$(first_nonempty_line "$src_file")"
  description="${description#\# }"
  mkdir -p "$(dirname "$dest_file")"
  {
    printf '%s\n' '---'
    printf 'description: %s\n' "${description:-Context skill}"
    printf '%s\n' 'alwaysApply: true'
    printf '%s\n\n' '---'
    cat "$src_file"
    printf '\n'
  } > "$dest_file"
  ok "Generated $dest_file"
}

write_jetbrains_agents_overview() {
  local dest_root="$1"
  local output_file="$dest_root/AGENTS.md"
  local context_readme="$dest_root/.ai/context/README.md"
  mkdir -p "$dest_root/.aiassistant/rules"
  {
    printf '# AI Agents Overview\n\n'
    if [[ -f "$context_readme" ]]; then
      cat "$context_readme"
      printf '\n\n'
    fi
    printf '## Context Skills\n\n'
    local skill_file
    while IFS= read -r skill_file; do
      local slug first
      slug="$(skill_slug "$skill_file")"
      first="$(first_nonempty_line "$skill_file")"
      first="${first#\# }"
      printf -- '- `%s`: %s\n' "$slug" "${first:-Sin descripción}"
    done < <(list_non_readme_markdown "$dest_root/.ai/context/skills")
  } > "$output_file"
  ok "Generated $output_file"
}

extract_xml_tags() {
  local tag="$1"
  local file="$2"
  grep -oE "<$tag>[^<]+</$tag>" "$file" 2>/dev/null | sed -E "s#<$tag>([^<]+)</$tag>#\1#"
}

scan_pom() {
  local repo="$1"
  local pom="$repo/pom.xml"
  [[ -f "$pom" ]] || return 0

  info "Reading pom.xml"
  local artifact group packaging
  artifact="$(extract_xml_tags artifactId "$pom" | head -n 1 || true)"
  group="$(extract_xml_tags groupId "$pom" | head -n 1 || true)"
  packaging="$(extract_xml_tags packaging "$pom" | head -n 1 || true)"

  printf 'POM_ARTIFACT=%s\n' "${artifact:-}"
  printf 'POM_GROUP=%s\n' "${group:-}"
  printf 'POM_PACKAGING=%s\n' "${packaging:-}"

  local modules dependencies dep_groups dep_artifacts
  modules="$(awk '/<modules>/,/<\/modules>/ { if ($0 ~ /<module>/) { gsub(/.*<module>|<\/module>.*/, ""); print } }' "$pom" | sed '/^$/d' | sort -u || true)"
  dep_groups="$(awk '/<dependencies>/,/<\/dependencies>/ { if ($0 ~ /<groupId>/) { gsub(/.*<groupId>|<\/groupId>.*/, ""); print } }' "$pom" | sed '/^$/d' || true)"
  dep_artifacts="$(awk '/<dependencies>/,/<\/dependencies>/ { if ($0 ~ /<artifactId>/) { gsub(/.*<artifactId>|<\/artifactId>.*/, ""); print } }' "$pom" | sed '/^$/d' || true)"
  paste -d: <(printf '%s\n' "$dep_groups") <(printf '%s\n' "$dep_artifacts") | sed '/^:$/d' | sort -u | head -n 20 | sed 's/^/POM_DEP=/'
  printf '%s\n' "$modules" | sed '/^$/d' | head -n 20 | sed 's/^/POM_MODULE=/'
}

scan_package_json() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  info "Reading $(basename "$file")"
  awk '
    /"name"[[:space:]]*:/ && !name { match($0, /"name"[[:space:]]*:[[:space:]]*"([^"]+)"/, m); if (m[1] != "") { print "PKG_NAME=" m[1]; name=1 } }
    /"dependencies"[[:space:]]*:/ { indeps=1; next }
    /"devDependencies"[[:space:]]*:/ { indev=1; next }
    indeps && /}/ { indeps=0 }
    indev && /}/ { indev=0 }
    (indeps || indev) && /"[^"]+"[[:space:]]*:/ {
      match($0, /"([^"]+)"[[:space:]]*:/, m)
      if (m[1] != "") print "PKG_DEP=" m[1]
    }
  ' "$file" | sort -u | head -n 30
}

scan_build_gradle() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  info "Reading $(basename "$file")"
  grep -E "^[[:space:]]*(implementation|api|compileOnly|runtimeOnly|testImplementation)[[:space:]]+['\"]" "$file" 2>/dev/null \
    | sed -E "s/^[[:space:]]*(implementation|api|compileOnly|runtimeOnly|testImplementation)[[:space:]]+['\"]([^'\"]+)['\"].*/GRADLE_DEP=\2/" \
    | sort -u | head -n 20 || true
}

scan_go_mod() {
  local file="$1"
  [[ -f "$file" ]] || return 0
  info "Reading go.mod"
  awk '
    /^module[[:space:]]+/ { print "GO_MODULE=" $2 }
    /^require[[:space:]]*\(/ { inblock=1; next }
    inblock && /^\)/ { inblock=0; next }
    inblock && NF >= 1 { print "GO_DEP=" $1 }
    /^require[[:space:]]+[^ (]/ { print "GO_DEP=" $2 }
  ' "$file" | sed 's#//# #' | sort -u | head -n 20
}

list_directories() {
  local repo="$1"
  find "$repo" -mindepth 1 -maxdepth 2 -type d \
    ! -path '*/.git*' ! -path '*/node_modules*' ! -path '*/target*' ! -path '*/build*' \
    | sed "s#^$repo/##" | sort
}

detect_cicd() {
  local repo="$1"
  local found=0
  [[ -d "$repo/.github/workflows" ]] && find "$repo/.github/workflows" -maxdepth 1 -type f | sed "s#^$repo/##" | sed 's/^/CICD=/' && found=1
  [[ -f "$repo/Jenkinsfile" ]] && printf 'CICD=Jenkinsfile\n' && found=1
  [[ -f "$repo/.gitlab-ci.yml" ]] && printf 'CICD=.gitlab-ci.yml\n' && found=1
  [[ -f "$repo/azure-pipelines.yml" ]] && printf 'CICD=azure-pipelines.yml\n' && found=1
  [[ -f "$repo/bitbucket-pipelines.yml" ]] && printf 'CICD=bitbucket-pipelines.yml\n' && found=1
  [[ $found -eq 0 ]] && true
}

do_copy() {
  local dest="${1:-}"
  require_arg "$dest" "Missing destination repository for --copy"
  ensure_source_exists
  ensure_dest_exists "$dest"

  info "Copying $AI_SOURCE to $dest/.ai using no-clobber mode"
  mkdir -p "$dest"
  local output
  output="$(cp -Rvn "$AI_SOURCE" "$dest/" 2>&1 || true)"
  if [[ -n "$output" ]]; then
    printf '%s\n' "$output"
  fi

  if [[ -f "$AI_SOURCE/templates/pull_request_template.md" && ! -f "$dest/.github/pull_request_template.md" ]]; then
    mkdir -p "$dest/.github"
    cp "$AI_SOURCE/templates/pull_request_template.md" "$dest/.github/pull_request_template.md"
    ok "Installed $dest/.github/pull_request_template.md (used by GitHub's PR UI and by the commit-and-push skill)"
  fi

  sync_manifest "$dest" quiet
  ok "Copy completed"
}

# ── Versioning: .ai/VERSION travels with the payload like any other file, so
# it is kept current automatically by sync_manifest below. .ai/.ai-manifest.json
# is destination-local bookkeeping (never shipped from AI_SOURCE): a map of
# relative-path -> sha256 for every shipped file, recorded as of the last
# successful --copy/--update, used to tell "still stock" apart from "the repo
# customized this file" without needing git history or a submodule. ─────────

sync_manifest() {
  local dest="$1" mode="${2:-quiet}"
  local py_bin=""
  for py_bin in python3 python; do
    command -v "$py_bin" >/dev/null 2>&1 && break
    py_bin=""
  done
  if [[ -z "$py_bin" ]]; then
    warn "No Python found on PATH; skipping the version manifest (.ai/.ai-manifest.json) — future --update runs will treat every file as unbaselined."
    return 0
  fi

  local report_flag=""
  [[ "$mode" == "report" ]] && report_flag="report"

  local output
  output="$("$py_bin" - "$AI_SOURCE" "$dest/.ai" "$report_flag" <<'PYEOF'
import hashlib
import json
import sys
from pathlib import Path

src_root = Path(sys.argv[1])
dest_root = Path(sys.argv[2])
report = len(sys.argv) > 3 and sys.argv[3] == "report"

manifest_path = dest_root / ".ai-manifest.json"

def sha256_file(p):
    h = hashlib.sha256()
    h.update(p.read_bytes())
    return h.hexdigest()

old_manifest = {}
if manifest_path.exists():
    try:
        old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        old_manifest = {}

src_files = {}
for p in src_root.rglob("*"):
    if p.is_file():
        src_files[p.relative_to(src_root).as_posix()] = p

new_manifest = {}
added, updated, unchanged, customized = [], [], [], []
adopted, intentional_removal, removed, orphaned = [], [], [], []

for rel, src_path in sorted(src_files.items()):
    dest_path = dest_root / rel
    new_hash = sha256_file(src_path)

    if not dest_path.exists():
        if rel in old_manifest:
            # Previously installed, now missing at the destination: the repo
            # (or a --workflow prune) deliberately removed it — never resurrect it.
            intentional_removal.append(rel)
            continue
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(src_path.read_bytes())
        new_manifest[rel] = new_hash
        added.append(rel)
        continue

    dest_hash = sha256_file(dest_path)
    old_hash = old_manifest.get(rel)

    if old_hash is None:
        # No recorded baseline for this path (first sync, or a file that
        # appeared without going through this tool). Never overwrite silently.
        if dest_hash == new_hash:
            new_manifest[rel] = new_hash
            unchanged.append(rel)
        else:
            new_manifest[rel] = dest_hash
            adopted.append(rel)
        continue

    if dest_hash == old_hash:
        if new_hash != dest_hash:
            dest_path.write_bytes(src_path.read_bytes())
            updated.append(rel)
        else:
            unchanged.append(rel)
        new_manifest[rel] = new_hash
    else:
        # Destination diverged from the last known-stock content: treat as
        # customized and never overwrite. Leave a .new copy of the upstream
        # version alongside it for a manual merge, if upstream actually moved.
        customized.append(rel)
        new_manifest[rel] = new_hash
        if new_hash != old_hash:
            Path(str(dest_path) + ".new").write_bytes(src_path.read_bytes())

for rel, old_hash in sorted(old_manifest.items()):
    if rel in src_files:
        continue
    dest_path = dest_root / rel
    if not dest_path.exists():
        continue
    if sha256_file(dest_path) == old_hash:
        dest_path.unlink()
        removed.append(rel)
    else:
        new_manifest[rel] = old_hash
        orphaned.append(rel)

manifest_path.write_text(json.dumps(new_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

if report:
    def section(label, items):
        if not items:
            return
        print(f"== {label} ({len(items)}) ==")
        for i in items:
            print(f"  {i}")

    section("Added", added)
    section("Updated", updated)
    section("Adopted as new baseline (no prior record, left as-is)", adopted)
    section("Customized - left untouched, upstream saved as *.new", customized)
    section("Removed (matched upstream deletion, was unmodified)", removed)
    section("Orphaned (upstream removed it, but you customized it - kept)", orphaned)
    section("Skipped (you removed it on purpose; not recreated)", intentional_removal)
    print(f"Unchanged: {len(unchanged)}")
    print(f"__RESULT__:{len(customized) + len(orphaned)}")
PYEOF
)"

  # `|| true`: in "quiet" mode (do_copy's call) $output never contains a
  # __RESULT__: line at all (the python script only prints it under `if
  # report:`), so grep finds no match and returns 1 — under `set -o
  # pipefail`, that failure would otherwise propagate to this assignment and,
  # under `set -e`, silently kill the whole script right here, before
  # do_init/do_update ever reach prune_workflow/do_scan/do_agents.
  LAST_SYNC_CONFLICTS="$(printf '%s\n' "$output" | grep '^__RESULT__:' | cut -d: -f2 || true)"
  LAST_SYNC_CONFLICTS="${LAST_SYNC_CONFLICTS:-0}"

  if [[ "$mode" == "report" ]]; then
    printf '%s\n' "$output" | grep -v '^__RESULT__:'
  fi
}

do_update() {
  local dest="${1:-}"
  require_arg "$dest" "Missing destination repository for --update"
  ensure_source_exists
  ensure_dest_exists "$dest"

  if [[ ! -d "$dest/.ai" ]]; then
    err "$dest/.ai not found — run --copy first (there is nothing to update)."
    exit 1
  fi

  local src_version dest_version
  src_version="$(trim "$(cat "$AI_SOURCE/VERSION" 2>/dev/null || printf 'unknown')")"
  dest_version="$(trim "$(cat "$dest/.ai/VERSION" 2>/dev/null || printf 'unknown')")"

  if [[ "$src_version" == "$dest_version" && "$src_version" != "unknown" ]]; then
    info "$dest/.ai is already at version $dest_version. Checking for drift anyway..."
  else
    info "Updating $dest/.ai: installed=$dest_version -> available=$src_version"
  fi

  sync_manifest "$dest" report
  local conflicts="$LAST_SYNC_CONFLICTS"

  # A repo that predates version tracking has no manifest recording that its
  # workflow choice previously pruned openspec-*: sync_manifest sees those
  # paths as simply missing (not "removed on purpose") and restores them. Redo
  # the prune for the repo's own recorded choice so --update never resurrects
  # a workflow's files the repo isn't using. Harmless (a no-op) when the
  # manifest already tracked the deletion, and when the workflow is openspec.
  local dest_workflow="openspec"
  [[ -f "$dest/.ai/.workflow" ]] && dest_workflow="$(trim "$(cat "$dest/.ai/.workflow")")"
  prune_workflow "$dest" "$dest_workflow"

  if [[ -f "$AI_SOURCE/templates/pull_request_template.md" && ! -f "$dest/.github/pull_request_template.md" ]]; then
    mkdir -p "$dest/.github"
    cp "$AI_SOURCE/templates/pull_request_template.md" "$dest/.github/pull_request_template.md"
    ok "Installed $dest/.github/pull_request_template.md"
  fi

  printf '\n'
  ok "$dest/.ai is now tracking version $(trim "$(cat "$dest/.ai/VERSION" 2>/dev/null || printf 'unknown')")"

  # --update is meant to leave the repo ready to use in one shot: regenerate
  # every already-installed agent's native files from the refreshed .ai/ right
  # away, the same way --sync does, instead of making the caller remember a
  # separate step.
  local detected
  detected="$(detect_agents "$dest")"
  if [[ -z "$detected" ]]; then
    info "No native agent files detected yet in $dest — nothing to regenerate. Run --agents once you pick one."
  else
    printf '\n'
    info "Regenerating native agent files from the updated .ai/..."
    do_sync "$dest"
  fi

  printf '\n'
  if [[ "${conflicts:-0}" -gt 0 ]]; then
    warn "$conflicts file(s) you customized were left untouched — review the matching *.new file(s) and merge by hand, then delete the *.new, then run --update again."
  fi
  do_check "$dest"
}

write_mcp_config() {
  local dest="$1" graph_dir="$2"
  local py_bin="$graph_dir/.venv/bin/python"
  [[ -x "$py_bin" ]] || py_bin="$graph_dir/.venv/Scripts/python.exe"
  [[ -x "$py_bin" ]] || { command -v python3 >/dev/null 2>&1 && py_bin="python3"; }
  [[ -x "$py_bin" || "$py_bin" == "python3" ]] || { warn "No Python available to write .mcp.json; skipping."; return 0; }

  local result
  result="$("$py_bin" - "$dest/.mcp.json" "$graph_dir/.env" <<'PYEOF'
import json
import sys
from pathlib import Path

mcp_path = Path(sys.argv[1])
env_path = Path(sys.argv[2])

env = {}
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

config = {}
if mcp_path.exists():
    try:
        config = json.loads(mcp_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        config = {}

config.setdefault("mcpServers", {})
if "graph-rag" in config["mcpServers"]:
    print(f"EXISTS:{mcp_path}")
else:
    # Read-only, namespaced so its tools appear as mcp__graph-rag__<name> and
    # never collide with another Neo4j MCP server the user may already have.
    config["mcpServers"]["graph-rag"] = {
        "command": "uvx",
        "args": ["mcp-neo4j-cypher@0.6.0", "--transport", "stdio", "--read-only", "--namespace", "graph-rag"],
        "env": {
            "NEO4J_URI": env.get("NEO4J_URI", "bolt://localhost:7687"),
            "NEO4J_USERNAME": env.get("NEO4J_USER", "neo4j"),
            "NEO4J_PASSWORD": env.get("NEO4J_PASSWORD", "password123"),
            "NEO4J_DATABASE": env.get("NEO4J_DATABASE", "neo4j"),
        },
    }
    mcp_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"WROTE:{mcp_path}")
PYEOF
)"
  case "$result" in
    WROTE:*) ok "Wrote graph-rag MCP server to ${result#WROTE:}. Restart your AI agent to pick it up." ;;
    EXISTS:*) info "graph-rag MCP server already present in ${result#EXISTS:}; leaving it as-is." ;;
    *) warn "Could not update .mcp.json: $result" ;;
  esac
}

hook_speckit_graph_rag() {
  local dest="$1"
  local marker="<!-- graph-rag-hook -->"
  local note
  note="$(cat <<'EOF'

<!-- graph-rag-hook -->
## Architecture graph (optional, local)

Before writing the plan/tasks/implementation, check whether `graph-rag/queries/graph_rag_query.py`
exists and, if so, query it first for relevant existing classes, ports, adapters, and dependencies —
cheaper than grepping the whole codebase for architecture context:

```bash
cd graph-rag && .venv/*/python* queries/graph_rag_query.py "<question about this spec>"
```

If a `graph-rag` MCP server is configured (see `.mcp.json`), prefer its `read_neo4j_cypher` /
`get_neo4j_schema` tools over shelling out to the script. See
`.claude/skills/neo4j-architecture-graph/SKILL.md` for query patterns and anti-patterns. The graph
is a discovery aid, not source of truth — always confirm findings in the actual source before
changing code.
EOF
)"
  local f any_target=0 newly_hooked=0
  for f in "$dest"/.claude/skills/speckit-plan/SKILL.md \
           "$dest"/.claude/skills/speckit-tasks/SKILL.md \
           "$dest"/.claude/skills/speckit-implement/SKILL.md; do
    [[ -f "$f" ]] || continue
    any_target=1
    grep -qF "$marker" "$f" 2>/dev/null && continue
    printf '%s\n' "$note" >> "$f"
    ok "Hooked the architecture graph into $(basename "$(dirname "$f")")"
    newly_hooked=1
  done
  if [[ "$any_target" -eq 0 ]]; then
    info "No speckit skill files found to hook the architecture graph into yet."
  elif [[ "$newly_hooked" -eq 0 ]]; then
    info "Architecture graph already hooked into the speckit skill files."
  fi
}

do_statusline() {
  # User-level, not project-scoped: installs to the home directory regardless
  # of which repo you ran this from, so it takes no destination-repo argument.
  # $1 selects which tool to wire up: "claude" (default) or "copilot". Both
  # write to the SAME specs/<branch>/.token-usage.json in any repo you work
  # in, each under its own top-level key, so totals combine instead of
  # clobbering each other if you use more than one.
  local target="${1:-claude}"
  local config_dir statusline_cmd confidence_note
  case "$target" in
    claude)
      config_dir="$HOME/.claude"
      statusline_cmd="python ~/.claude/statusline.py"
      confidence_note=""
      ;;
    copilot)
      config_dir="$HOME/.copilot"
      statusline_cmd="python ~/.copilot/statusline.py"
      confidence_note=" Copilot CLI's statusLine schema/config path is based on a third-party walkthrough, not a dedicated official reference page (unlike Claude Code's) — if nothing shows up after restarting, run /statusline inside Copilot CLI to confirm or re-point it at this script."
      ;;
    *)
      err "Unknown --statusline target: $target (expected claude or copilot)"
      exit 1
      ;;
  esac

  local statusline_dest="$config_dir/statusline.py"
  local settings_dest="$config_dir/settings.json"
  local statusline_src="$AI_SOURCE/templates/statusline-${target}.py"

  if [[ ! -f "$statusline_src" ]]; then
    err "Source statusline template not found at $statusline_src"
    exit 1
  fi

  mkdir -p "$config_dir"

  if [[ -f "$statusline_dest" ]]; then
    warn "$statusline_dest already exists — leaving it as-is. Remove it first if you want the kit's version."
  else
    cp "$statusline_src" "$statusline_dest"
    ok "Installed $statusline_dest"
  fi

  local py_bin=""
  for py_bin in python3 python; do
    command -v "$py_bin" >/dev/null 2>&1 && break
    py_bin=""
  done
  if [[ -z "$py_bin" ]]; then
    warn "No Python found on PATH; cannot update $settings_dest. Add the statusLine block manually — see --help."
    return 0
  fi

  local result
  result="$("$py_bin" - "$settings_dest" "$statusline_cmd" <<'PYEOF'
import json
import sys
from pathlib import Path

settings_path = Path(sys.argv[1])
command = sys.argv[2]

config = {}
if settings_path.exists():
    try:
        config = json.loads(settings_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"INVALID:{settings_path}")
        raise SystemExit(0)

if "statusLine" in config:
    print(f"EXISTS:{settings_path}")
else:
    config["statusLine"] = {
        "type": "command",
        "command": command,
        "padding": 0,
    }
    settings_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"WROTE:{settings_path}")
PYEOF
)"
  case "$result" in
    WROTE:*) ok "Wired statusLine into ${result#WROTE:}. Restart ${target} to see it.${confidence_note}" ;;
    EXISTS:*) warn "${result#EXISTS:} already has a statusLine configured — leaving it as-is. Merge manually if you want both." ;;
    INVALID:*) err "${result#INVALID:} is not valid JSON — fix it, then re-run --statusline." ;;
    *) warn "Could not update $settings_dest: $result" ;;
  esac
}

do_graph() {
  local dest="${1:-}"
  require_arg "$dest" "Missing destination repository for --graph"
  ensure_dest_exists "$dest"

  if [[ ! -d "$dest/graph-rag" ]]; then
    if [[ ! -d "$GRAPH_RAG_SOURCE" ]]; then
      err "graph-rag source not found at $GRAPH_RAG_SOURCE"
      exit 1
    fi
    info "Copying $GRAPH_RAG_SOURCE to $dest/graph-rag using no-clobber mode"
    local output
    output="$(cp -Rvn "$GRAPH_RAG_SOURCE" "$dest/" 2>&1 || true)"
    if [[ -n "$output" ]]; then
      printf '%s\n' "$output"
    fi
  fi

  bootstrap_graph_rag "$dest"

  local workflow="openspec"
  [[ -f "$dest/.ai/.workflow" ]] && workflow="$(trim "$(cat "$dest/.ai/.workflow")")"
  if [[ "$workflow" == "speckit" && -f "$dest/graph-rag/queries/graph_rag_query.py" ]]; then
    hook_speckit_graph_rag "$dest"
  fi
}

bootstrap_graph_rag() {
  local dest="$1"
  local graph_dir="$dest/graph-rag"

  if [[ ! -d "$graph_dir" ]]; then
    warn "$graph_dir not found; run --copy first. Skipping the Neo4j architecture graph."
    return 0
  fi

  # Resolve to an absolute path: several steps below build $venv_python from
  # $graph_dir and then `cd "$graph_dir"` before using it (e.g. the Phase 1
  # scan step) — a relative $graph_dir would make that path resolve against
  # the new working directory instead, effectively doubling it.
  graph_dir="$(cd "$graph_dir" && pwd)"

  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker not found. Skipping the Neo4j architecture graph. Once Docker is installed, run:"
    warn "  (cd \"$graph_dir\" && docker compose --env-file .env up -d && .venv/bin/python ingestion/phase1_scan.py)"
    return 0
  fi
  if ! docker compose version >/dev/null 2>&1; then
    warn "Docker Compose plugin not found. Skipping the Neo4j architecture graph."
    return 0
  fi

  local python_bin="" use_uv=false
  if command -v uv >/dev/null 2>&1; then
    use_uv=true
  else
    local candidate
    for candidate in python3 python; do
      if command -v "$candidate" >/dev/null 2>&1; then
        python_bin="$candidate"
        break
      fi
    done
    if [[ -z "$python_bin" ]]; then
      warn "Neither 'uv' nor Python 3.11+ found. Skipping the Neo4j architecture graph. Once Python is installed, run:"
      warn "  (cd \"$graph_dir\" && python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt && docker compose --env-file .env up -d && .venv/bin/python ingestion/phase1_scan.py)"
      return 0
    fi
  fi

  [[ -f "$graph_dir/.env" ]] || cp "$graph_dir/.env.example" "$graph_dir/.env"

  if [[ ! -d "$graph_dir/.venv" ]]; then
    info "Creating the graph-rag Python virtual environment..."
    if [[ "$use_uv" == true ]]; then
      # Pin 3.12: tree-sitter-languages ships no wheels for very new CPython
      # releases (e.g. 3.14), so trusting whatever "python3"/"python" resolves
      # to on PATH can fail dependency installation even on "3.11+" machines.
      # uv downloads 3.12 automatically if it isn't already cached.
      if ! uv venv --python 3.12 "$graph_dir/.venv" >/dev/null 2>&1; then
        warn "uv could not provision a Python 3.12 virtual environment. Skipping the Neo4j architecture graph."
        return 0
      fi
    elif ! "$python_bin" -m venv "$graph_dir/.venv"; then
      warn "Could not create the virtual environment. Skipping the Neo4j architecture graph."
      return 0
    fi
  fi

  local venv_python="$graph_dir/.venv/bin/python"
  [[ -x "$venv_python" ]] || venv_python="$graph_dir/.venv/Scripts/python.exe"

  info "Installing graph-rag Python dependencies (first run only; can take a few minutes)..."
  if [[ "$use_uv" == true ]]; then
    # uv-created venvs ship without pip, so install through uv itself.
    if ! uv pip install --quiet -r "$graph_dir/requirements.txt" --python "$venv_python"; then
      warn "Dependency installation failed. See $graph_dir/README.md to install manually."
      return 0
    fi
  elif ! "$venv_python" -m pip install --quiet -r "$graph_dir/requirements.txt"; then
    warn "Dependency installation failed. See $graph_dir/README.md to install manually."
    return 0
  fi

  info "Starting the local Neo4j container..."
  if ! (cd "$graph_dir" && docker compose --env-file .env up -d); then
    warn "Could not start Neo4j. See $graph_dir/README.md to start it manually."
    return 0
  fi

  info "Waiting for Neo4j to accept connections..."
  local attempt ready=false
  for attempt in $(seq 1 30); do
    if "$venv_python" "$graph_dir/verify_graph.py" --connection >/dev/null 2>&1; then
      ready=true
      break
    fi
    sleep 2
  done
  if [[ "$ready" != true ]]; then
    warn "Neo4j did not become reachable in time. See $graph_dir/README.md to check its status."
    return 0
  fi

  info "Running the Phase 1 architecture scan (PROJECT_PATHS in $graph_dir/.env)..."
  if (cd "$graph_dir" && "$venv_python" ingestion/phase1_scan.py); then
    ok "Neo4j architecture graph ready — browse it at http://localhost:7474"
    info "Ask your AI agent to run: \"Read and execute graph-rag/pipeline_tasks.md\" to add summaries and embeddings."
    write_mcp_config "$dest" "$graph_dir"
  else
    warn "The Phase 1 scan failed. See $graph_dir/README.md to run it manually."
  fi
}

do_scan() {
  local dest="${1:-}"
  require_arg "$dest" "Missing destination repository for --scan"
  ensure_dest_exists "$dest"

  mkdir -p "$dest/.ai/context"
  local output_file="$dest/.ai/context/project-context.md"
  local project_name="$(basename "$dest")"
  local pom_info pkg_info gradle_info go_info dirs cicd readme_snippet

  _progress_bar 1 7 "pom.xml"
  pom_info="$(scan_pom "$dest" || true)"
  _progress_bar 2 7 "package.json"
  pkg_info="$(scan_package_json "$dest/package.json" || true)"
  _progress_bar 3 7 "build files"
  gradle_info="$(scan_build_gradle "$dest/build.gradle" || true)"
  [[ -z "$gradle_info" ]] && gradle_info="$(scan_build_gradle "$dest/build.gradle.kts" || true)"
  _progress_bar 4 7 "go.mod"
  go_info="$(scan_go_mod "$dest/go.mod" || true)"
  _progress_bar 5 7 "directories"
  dirs="$(list_directories "$dest" || true)"
  _progress_bar 6 7 "CI/CD & README"
  cicd="$(detect_cicd "$dest" || true)"
  if [[ -f "$dest/README.md" ]]; then
    readme_snippet="$(head -n 100 "$dest/README.md")"
  else
    readme_snippet="README.md no encontrado"
  fi
  _progress_bar 7 7 "writing output"

  if grep -q '^POM_ARTIFACT=' <<< "$pom_info"; then
    project_name="$(grep '^POM_ARTIFACT=' <<< "$pom_info" | head -n 1 | cut -d= -f2-)"
  elif grep -q '^PKG_NAME=' <<< "$pkg_info"; then
    project_name="$(grep '^PKG_NAME=' <<< "$pkg_info" | head -n 1 | cut -d= -f2-)"
  elif grep -q '^GO_MODULE=' <<< "$go_info"; then
    project_name="$(grep '^GO_MODULE=' <<< "$go_info" | head -n 1 | cut -d= -f2-)"
  fi

  {
    printf '# Project Context\n\n'
    printf '## Project Name\n\n'
    printf -- '- Name: %s\n' "$project_name"
    if grep -q '^POM_GROUP=' <<< "$pom_info"; then
      printf -- '- Group: %s\n' "$(grep '^POM_GROUP=' <<< "$pom_info" | head -n 1 | cut -d= -f2-)"
    fi
    printf '\n## Stack & Frameworks\n\n'
    if [[ -n "$pom_info$pkg_info$gradle_info$go_info" ]]; then
      grep -E '^(POM_PACKAGING|PKG_NAME|GO_MODULE)=' <<< "$pom_info
$pkg_info
$go_info" 2>/dev/null | while IFS='=' read -r key value; do
        case "$key" in
          POM_PACKAGING) printf -- '- Maven packaging: %s\n' "$value" ;;
          PKG_NAME) printf -- '- Node package: %s\n' "$value" ;;
          GO_MODULE) printf -- '- Go module: %s\n' "$value" ;;
        esac
      done
      if [[ -f "$dest/pom.xml" ]]; then printf -- '- Build: Maven (pom.xml)\n'; fi
      if [[ -f "$dest/package.json" ]]; then printf -- '- Build: npm/package.json\n'; fi
      if [[ -f "$dest/build.gradle" || -f "$dest/build.gradle.kts" ]]; then printf -- '- Build: Gradle\n'; fi
      if [[ -f "$dest/go.mod" ]]; then printf -- '- Build: Go modules\n'; fi
    else
      printf -- '- ⚠️ Pending confirmation\n'
    fi

    printf '\n## Module Structure\n\n'
    if grep -q '^POM_MODULE=' <<< "$pom_info"; then
      grep '^POM_MODULE=' <<< "$pom_info" | cut -d= -f2- | while IFS= read -r module; do
        printf -- '- Maven module: %s\n' "$module"
      done
    fi
    if [[ -n "$dirs" ]]; then
      printf -- '- Top and second-level directories:\n'
      while IFS= read -r dir; do
        [[ -n "$dir" ]] && printf '  - %s\n' "$dir"
      done <<< "$dirs"
    else
      printf -- '- ⚠️ Pending confirmation\n'
    fi

    printf '\n## Key Dependencies\n\n'
    local deps_printed=0
    while IFS='=' read -r key value; do
      [[ -n "$value" ]] || continue
      case "$key" in
        POM_DEP|PKG_DEP|GRADLE_DEP|GO_DEP)
          printf -- '- %s\n' "$value"
          deps_printed=1
          ;;
      esac
    done <<< "$pom_info
$pkg_info
$gradle_info
$go_info"
    if [[ $deps_printed -eq 0 ]]; then
      printf -- '- ⚠️ Pending confirmation\n'
    fi

    printf '\n## CI/CD\n\n'
    if [[ -n "$cicd" ]]; then
      grep '^CICD=' <<< "$cicd" | cut -d= -f2- | while IFS= read -r item; do
        printf -- '- %s\n' "$item"
      done
    else
      printf -- '- ⚠️ Pending confirmation\n'
    fi

    printf '\n## Conventions\n\n'
    printf -- '- ⚠️ Pending confirmation: naming conventions\n'
    printf -- '- ⚠️ Pending confirmation: testing strategy\n'
    printf -- '- ⚠️ Pending confirmation: branching and release flow\n'
    printf -- '- ⚠️ Pending confirmation: observability and logging practices\n'

    printf '\n## README Snippet (first 100 lines)\n\n'
    printf '```md\n%s\n```\n' "$readme_snippet"
  } > "$output_file"

  ok "Generated $output_file"
}

generate_copilot() {
  local dest="$1"
  combine_context_and_rules "$dest/.github/copilot-instructions.md" "$dest/.ai/context/README.md" "$dest/.ai/rules"
  ok "Generated $dest/.github/copilot-instructions.md"
  copy_dir_if_present "$dest/.ai/skills" "$dest/.github/skills"
  copy_dir_if_present "$dest/.ai/prompts" "$dest/.github/prompts"
  local skill_files=() skill_file
  while IFS= read -r skill_file; do skill_files+=("$skill_file"); done \
    < <(list_non_readme_markdown "$dest/.ai/context/skills")
  local total="${#skill_files[@]}" step=0
  if [[ $total -gt 0 ]]; then
    info "Generating $total instruction files..."
    _QUIET=true
    for skill_file in "${skill_files[@]}"; do
      local slug; slug="$(skill_slug "$skill_file")"
      _progress_bar $(( ++step )) "$total" "$slug"
      write_context_skill_copy "$skill_file" "$dest/.github/instructions/$slug.instructions.md"
    done
    _QUIET=false
    ok "Generated $step instruction files → .github/instructions/"
  fi
}

generate_claude() {
  local dest="$1"
  combine_context_and_rules "$dest/CLAUDE.md" "$dest/.ai/context/README.md" "$dest/.ai/rules"
  ok "Generated $dest/CLAUDE.md"
  copy_dir_if_present "$dest/.ai/skills" "$dest/.claude/skills"
  copy_dir_if_present "$dest/.ai/prompts" "$dest/.claude/commands"
  ensure_gitignore_entry "$dest" ".claude/settings.local.json" \
    "Claude Code local settings (machine-specific; may hold enabled MCP servers/tokens)"
  local skill_files=() skill_file
  while IFS= read -r skill_file; do skill_files+=("$skill_file"); done \
    < <(list_non_readme_markdown "$dest/.ai/context/skills")
  local total="${#skill_files[@]}" step=0
  if [[ $total -gt 0 ]]; then
    info "Generating $total claude skills..."
    _QUIET=true
    for skill_file in "${skill_files[@]}"; do
      local slug; slug="$(skill_slug "$skill_file")"
      _progress_bar $(( ++step )) "$total" "$slug"
      write_context_skill_copy "$skill_file" "$dest/.claude/$slug.md"
    done
    _QUIET=false
    ok "Generated $step skills → .claude/"
  fi
}

generate_cursor() {
  local dest="$1"
  combine_context_and_rules "$dest/.cursorrules" "$dest/.ai/context/README.md" "$dest/.ai/rules"
  ok "Generated $dest/.cursorrules"
  copy_dir_if_present "$dest/.ai/skills" "$dest/.cursor/skills"
  copy_dir_if_present "$dest/.ai/prompts" "$dest/.cursor/commands"
  local skill_files=() skill_file
  while IFS= read -r skill_file; do skill_files+=("$skill_file"); done \
    < <(list_non_readme_markdown "$dest/.ai/context/skills")
  local total="${#skill_files[@]}" step=0
  if [[ $total -gt 0 ]]; then
    info "Generating $total cursor rules..."
    _QUIET=true
    for skill_file in "${skill_files[@]}"; do
      local slug; slug="$(skill_slug "$skill_file")"
      _progress_bar $(( ++step )) "$total" "$slug"
      write_cursor_rule "$skill_file" "$dest/.cursor/rules/$slug.mdc"
    done
    _QUIET=false
    ok "Generated $step rules → .cursor/rules/"
  fi
}

generate_windsurf() {
  local dest="$1"
  combine_context_and_rules "$dest/.windsurfrules" "$dest/.ai/context/README.md" "$dest/.ai/rules"
  ok "Generated $dest/.windsurfrules"
  local workflow_files=() workflow_file
  while IFS= read -r workflow_file; do workflow_files+=("$workflow_file"); done \
    < <(find "$dest/.ai/skills" -mindepth 2 -maxdepth 2 -type f -name 'SKILL.md' 2>/dev/null | sort)
  if [[ "${#workflow_files[@]}" -gt 0 ]]; then
    info "Generating ${#workflow_files[@]} windsurf workflows..."
    for workflow_file in "${workflow_files[@]}"; do
      local slug; slug="$(basename "$(dirname "$workflow_file")")"
      write_context_skill_copy "$workflow_file" "$dest/.windsurf/workflows/$slug.md"
    done
    ok "Generated ${#workflow_files[@]} workflows → .windsurf/workflows/"
  fi
  local skill_files=() skill_file
  while IFS= read -r skill_file; do skill_files+=("$skill_file"); done \
    < <(list_non_readme_markdown "$dest/.ai/context/skills")
  local total="${#skill_files[@]}" step=0
  if [[ $total -gt 0 ]]; then
    info "Generating $total windsurf rules..."
    _QUIET=true
    for skill_file in "${skill_files[@]}"; do
      local slug; slug="$(skill_slug "$skill_file")"
      _progress_bar $(( ++step )) "$total" "$slug"
      write_context_skill_copy "$skill_file" "$dest/.windsurf/rules/$slug.md"
    done
    _QUIET=false
    ok "Generated $step rules → .windsurf/rules/"
  fi
}

generate_jetbrains() {
  local dest="$1"
  combine_context_and_rules "$dest/.aiassistant/rules/project.md" "$dest/.ai/context/README.md" "$dest/.ai/rules"
  ok "Generated $dest/.aiassistant/rules/project.md"
  local skill_files=() skill_file
  while IFS= read -r skill_file; do skill_files+=("$skill_file"); done \
    < <(list_non_readme_markdown "$dest/.ai/context/skills")
  local total="${#skill_files[@]}" step=0
  if [[ $total -gt 0 ]]; then
    info "Generating $total JetBrains rules..."
    _QUIET=true
    for skill_file in "${skill_files[@]}"; do
      local slug; slug="$(skill_slug "$skill_file")"
      _progress_bar $(( ++step )) "$total" "$slug"
      write_context_skill_copy "$skill_file" "$dest/.aiassistant/rules/$slug.md"
    done
    _QUIET=false
    ok "Generated $step rules → .aiassistant/rules/"
  fi
  write_jetbrains_agents_overview "$dest"
}

normalize_agent() {
  local agent
  agent="$(trim "$1")"
  case "$agent" in
    copilot|claude|cursor|windsurf|jetbrains) printf '%s' "$agent" ;;
    *) return 1 ;;
  esac
}

do_agents() {
  local agent_list="${1:-}"
  local dest="${2:-}"
  require_arg "$agent_list" "Missing agent list for --agents"
  require_arg "$dest" "Missing destination repository for --agents"
  ensure_dest_exists "$dest"
  ensure_source_exists

  if [[ ! -d "$dest/.ai" ]]; then
    warn "Destination has no .ai directory; copying source package first"
    do_copy "$dest"
  fi

  local agents=()
  while IFS= read -r _agent; do
    [[ -n "$_agent" ]] && agents+=("$_agent")
  done < <(tr ',' '\n' <<< "$agent_list")
  local agent normalized total_agents="${#agents[@]}" agent_step=0
  for agent in "${agents[@]}"; do
    normalized="$(normalize_agent "$agent")" || {
      err "Unknown agent: $agent"
      exit 1
    }
    (( ++agent_step ))
    info "[$agent_step/$total_agents] Generating $normalized..."
    case "$normalized" in
      copilot) generate_copilot "$dest"; do_statusline copilot ;;
      claude) generate_claude "$dest"; do_statusline claude ;;
      cursor) generate_cursor "$dest" ;;
      windsurf) generate_windsurf "$dest" ;;
      jetbrains) generate_jetbrains "$dest" ;;
    esac
  done
}

detect_agents() {
  local dest="$1"
  local detected=()
  [[ -f "$dest/.github/copilot-instructions.md" || -d "$dest/.github/skills" || -d "$dest/.github/prompts" || -d "$dest/.github/instructions" ]] && detected+=(copilot)
  [[ -f "$dest/CLAUDE.md" || -d "$dest/.claude" ]] && detected+=(claude)
  [[ -f "$dest/.cursorrules" || -d "$dest/.cursor/rules" ]] && detected+=(cursor)
  [[ -f "$dest/.windsurfrules" || -d "$dest/.windsurf/rules" ]] && detected+=(windsurf)
  [[ -f "$dest/.aiassistant/rules/project.md" || -f "$dest/AGENTS.md" || -d "$dest/.aiassistant/rules" ]] && detected+=(jetbrains)
  printf '%s\n' "${detected[@]:-}"
}

do_sync() {
  local dest="${1:-}"
  require_arg "$dest" "Missing destination repository for --sync"
  ensure_dest_exists "$dest"
  ensure_source_exists

  if [[ ! -d "$dest/.ai" ]]; then
    warn "Destination has no .ai directory; copying source package first"
    do_copy "$dest"
  fi

  local detected
  detected="$(detect_agents "$dest")"
  if [[ -z "$detected" ]]; then
    warn "No known agent targets detected in $dest"
    return 0
  fi

  local csv
  csv="$(printf '%s\n' "$detected" | tr '\n' ',' | sed 's/,$//')"
  info "Detected agents: $csv"
  do_agents "$csv" "$dest"
}

# ── Post-install validation ─────────────────────────────────────────────────

check_skill_frontmatter() {
  local skill_file="$1"
  [[ "$(head -n 1 "$skill_file")" == "---" ]] || return 1
  local frontmatter
  frontmatter="$(awk '/^---$/{c++; next} c==1' "$skill_file")"
  grep -q '^name:' <<< "$frontmatter" && grep -q '^description:' <<< "$frontmatter"
}

check_agent_files() {
  local dest="$1" agent="$2"
  local main_file="" skills_dir=""
  case "$agent" in
    copilot) main_file="$dest/.github/copilot-instructions.md"; skills_dir="$dest/.github/skills" ;;
    claude) main_file="$dest/CLAUDE.md"; skills_dir="$dest/.claude/skills" ;;
    cursor) main_file="$dest/.cursorrules"; skills_dir="$dest/.cursor/skills" ;;
    windsurf) main_file="$dest/.windsurfrules"; skills_dir="$dest/.windsurf/workflows" ;;
    jetbrains) main_file="$dest/.aiassistant/rules/project.md"; skills_dir="" ;;
  esac

  if [[ -s "$main_file" ]]; then
    ok "[$agent] main file present: ${main_file#"$dest"/}"
  else
    err "[$agent] main file missing or empty: ${main_file#"$dest"/}"
    errors=$((errors + 1))
  fi

  [[ -n "$skills_dir" ]] || return 0

  if [[ ! -d "$skills_dir" ]]; then
    info "[$agent] ${skills_dir#"$dest"/} not present (no callable skills distributed to this agent)"
    return 0
  fi

  local count
  count="$(find "$skills_dir" -mindepth 1 -maxdepth 2 \( -name 'SKILL.md' -o -name '*.md' -o -name '*.mdc' \) 2>/dev/null | wc -l | tr -d ' ')"
  if [[ "$count" -gt 0 ]]; then
    ok "[$agent] $count skill/workflow file(s) in ${skills_dir#"$dest"/}"
  else
    warn "[$agent] ${skills_dir#"$dest"/} exists but is empty"
    warnings=$((warnings + 1))
  fi

  local skill_file
  while IFS= read -r skill_file; do
    [[ -n "$skill_file" ]] || continue
    if ! check_skill_frontmatter "$skill_file"; then
      warn "[$agent] ${skill_file#"$dest"/} is missing name/description front-matter"
      warnings=$((warnings + 1))
    fi
  done < <(find "$skills_dir" -mindepth 1 -maxdepth 2 -name 'SKILL.md' 2>/dev/null)
}

do_check() {
  local dest="${1:-}"
  require_arg "$dest" "Missing destination repository for --check"
  ensure_dest_exists "$dest"

  local errors=0 warnings=0

  printf '\n=== AI Workspace Starter Kit — post-install check ===\n\n'

  if [[ ! -d "$dest/.ai" ]]; then
    err ".ai/ not found in $dest — run --copy first."
    exit 2
  fi
  ok ".ai/ present"

  local src_version dest_version
  src_version="$(trim "$(cat "$AI_SOURCE/VERSION" 2>/dev/null || printf 'unknown')")"
  dest_version="$(trim "$(cat "$dest/.ai/VERSION" 2>/dev/null || printf 'unknown')")"
  if [[ "$dest_version" == "unknown" ]]; then
    warn "$dest/.ai has no VERSION file (predates versioning) — run: $(basename "$0") --update $dest"
    warnings=$((warnings + 1))
  elif [[ "$dest_version" != "$src_version" ]]; then
    warn "$dest/.ai is at version $dest_version; $src_version is available — run: $(basename "$0") --update $dest"
    warnings=$((warnings + 1))
  else
    ok ".ai/ is up to date (version $dest_version)"
  fi

  if command -v git >/dev/null 2>&1; then
    ok "git available"
  else
    err "git not found on PATH"
    errors=$((errors + 1))
  fi

  local workflow="openspec"
  [[ -f "$dest/.ai/.workflow" ]] && workflow="$(trim "$(cat "$dest/.ai/.workflow")")"
  info "Configured spec-driven workflow: $workflow"
  case "$workflow" in
    openspec)
      if [[ -f "$dest/openspec/config.yaml" ]]; then
        ok "openspec/config.yaml present"
      else
        warn "openspec/config.yaml missing — the static .ai/skills/openspec-* files have nothing to" \
             "act on yet. Run: $(basename "$0") --openspec <agents> $dest"
        warnings=$((warnings + 1))
      fi
      if ! command -v openspec >/dev/null 2>&1 && ! command -v npx >/dev/null 2>&1; then
        warn "Neither 'openspec' nor 'npx' found — --openspec would not be able to run automatically."
        warnings=$((warnings + 1))
      fi
      ;;
    speckit)
      if [[ -d "$dest/.specify" ]]; then
        ok ".specify/ present"
      else
        warn ".specify/ missing — run: $(basename "$0") --speckit <agents> $dest"
        warnings=$((warnings + 1))
      fi
      if ! command -v uvx >/dev/null 2>&1 && ! command -v uv >/dev/null 2>&1; then
        warn "Neither 'uv' nor 'uvx' found — --speckit would not be able to run automatically."
        warnings=$((warnings + 1))
      fi
      ;;
    none)
      ok "No spec-driven workflow selected (workflow=none)"
      ;;
    *)
      warn "Unrecognized value in .ai/.workflow: '$workflow'"
      warnings=$((warnings + 1))
      ;;
  esac

  # Coexistence check: a workflow's real CLI setup can be present even when it
  # is not the currently configured one (e.g. spec-kit was installed before
  # switching to OpenSpec, or before this kit was installed at all). Neither
  # --workflow nor --openspec/--speckit ever delete the other tool's files, so
  # both can end up active for your agents at once — not broken, but worth
  # flagging since it means duplicate command sets (e.g. /speckit-* alongside
  # /opsx-*).
  if [[ "$workflow" != "speckit" && -d "$dest/.specify" ]]; then
    warn "spec-kit appears to be installed (.specify/ present) even though the configured workflow" \
         "is '$workflow'. Both will coexist for your agents (e.g. /speckit-* alongside" \
         "$( [[ "$workflow" == "openspec" ]] && printf '/opsx-*' || printf 'nothing else' ) commands)." \
         "Not an error — run '$(basename "$0") --workflow speckit $dest' if you meant to standardize on it."
    warnings=$((warnings + 1))
  fi
  if [[ "$workflow" != "openspec" && -f "$dest/openspec/config.yaml" ]]; then
    warn "OpenSpec appears to be installed (openspec/config.yaml present) even though the configured" \
         "workflow is '$workflow'. Both will coexist for your agents. Not an error — run" \
         "'$(basename "$0") --workflow openspec $dest' if you meant to standardize on it."
    warnings=$((warnings + 1))
  fi

  if [[ -d "$dest/graph-rag" ]]; then
    info "graph-rag/ present (optional Step 2)"
    if [[ -f "$dest/graph-rag/.env" ]]; then
      ok "graph-rag/.env present"
    else
      warn "graph-rag/.env missing — run --graph to bootstrap it"
      warnings=$((warnings + 1))
    fi
    command -v docker >/dev/null 2>&1 || { warn "Docker not found — required to run the graph"; warnings=$((warnings + 1)); }
    { command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; } \
      || { warn "Python not found — required for graph-rag ingestion"; warnings=$((warnings + 1)); }
    if [[ ! -f "$dest/graph-rag/data/extracted_classes.json" ]]; then
      info "graph-rag Phase 1 (AST scan) not run yet — run: $(basename "$0") --graph $dest"
    elif [[ -f "$dest/graph-rag/data/summaries.json" ]]; then
      ok "graph-rag Phase 2 (summaries + embeddings) already run"
    else
      info "graph-rag Phase 2 pending (needs an LLM) — ask your AI agent to read and execute" \
           "graph-rag/pipeline_tasks.md, then run graph-rag/ingestion/phase2_embed_ingest.py"
    fi
  else
    info "graph-rag/ not installed (optional Step 2 — run --graph if you want it)"
  fi

  if [[ -f "$dest/.github/pull_request_template.md" ]]; then
    ok ".github/pull_request_template.md present"
  else
    warn ".github/pull_request_template.md missing — the commit-and-push skill's PR step has no" \
         "template to fill. Re-run --copy or copy it manually from .ai/templates/."
    warnings=$((warnings + 1))
  fi

  local detected
  detected="$(detect_agents "$dest")"
  if [[ -z "$detected" ]]; then
    warn "No agent native files detected — run: $(basename "$0") --agents <list> $dest"
    warnings=$((warnings + 1))
  else
    local agent
    while IFS= read -r agent; do
      [[ -n "$agent" ]] || continue
      check_agent_files "$dest" "$agent"
    done <<< "$detected"
  fi

  printf '\n'
  if [[ "$errors" -gt 0 ]]; then
    err "$errors error(s), $warnings warning(s)."
    exit 2
  elif [[ "$warnings" -gt 0 ]]; then
    warn "$warnings warning(s), no errors."
  else
    ok "Everything checks out."
  fi
}

# ── Spec-driven workflow selection: OpenSpec (static skills, shipped in .ai/)
# vs spec-kit (delegates to the official `specify` CLI) vs none. ─────────────

prune_workflow() {
  local dest="$1" workflow="$2"
  case "$workflow" in
    openspec)
      ok "Keeping the OpenSpec skills/prompts (default)."
      ;;
    speckit|none)
      # Prune the source (.ai/) AND every already-generated agent output that
      # was copied verbatim from it — copy_dir_if_present only ever adds/
      # overwrites, it never deletes, so a stale .claude/skills/openspec-*
      # from before the workflow was switched (or, on --update, resurrected
      # because a legacy repo had no manifest baseline recording the original
      # prune) would otherwise linger forever even though .ai/ itself is clean.
      local removed=0 dir file
      for dir in "$dest"/.ai/skills/openspec-* \
                 "$dest"/.github/skills/openspec-* \
                 "$dest"/.claude/skills/openspec-* \
                 "$dest"/.cursor/skills/openspec-*; do
        [[ -d "$dir" ]] || continue
        rm -rf "$dir"
        removed=1
      done
      for file in "$dest"/.ai/prompts/opsx-*.prompt.md \
                  "$dest"/.github/prompts/opsx-*.prompt.md \
                  "$dest"/.claude/commands/opsx-*.prompt.md \
                  "$dest"/.cursor/commands/opsx-*.prompt.md; do
        [[ -f "$file" ]] || continue
        rm -f "$file"
        removed=1
      done
      for file in "$dest"/.windsurf/workflows/openspec-*.md; do
        [[ -f "$file" ]] || continue
        rm -f "$file"
        removed=1
      done
      if [[ "$removed" -eq 1 ]]; then
        ok "Removed the OpenSpec skills/prompts from $dest/.ai and every already-generated agent output (workflow=$workflow)."
      fi
      ;;
    *)
      err "Unknown workflow: $workflow (expected openspec, speckit, or none)"
      exit 1
      ;;
  esac
  mkdir -p "$dest/.ai"
  printf '%s\n' "$workflow" > "$dest/.ai/.workflow"
}

speckit_runner() {
  # Pin a stable CPython (uv downloads it automatically if missing) instead of
  # whatever "python"/"python3" resolves to on PATH — some machines default to
  # a preview/alpha interpreter that spec-kit's dependencies can't build against.
  if command -v uvx >/dev/null 2>&1; then
    printf 'uvx --python 3.12 --from git+https://github.com/github/spec-kit.git specify'
  elif command -v uv >/dev/null 2>&1; then
    printf 'uv tool run --python 3.12 --from git+https://github.com/github/spec-kit.git specify'
  else
    return 1
  fi
}

# Maps this kit's own agent names to spec-kit's `--integration` slugs, which
# do not always match (confirmed by running `specify integration list`).
# Left blank = no confirmed mapping; spec-kit does not currently ship an
# integration for that agent, or this kit can't tell its slug apart from a
# similarly-named but distinct product. Verify with `specify integration list`.
speckit_integration_for() {
  case "$1" in
    copilot) printf 'copilot' ;;
    claude) printf 'claude' ;;
    cursor) printf 'cursor-agent' ;;
    windsurf) printf '' ;;
    jetbrains) printf '' ;;
    *) printf '' ;;
  esac
}

do_speckit() {
  local agents_csv="${1:-}" dest="${2:-}"
  require_arg "$agents_csv" "Missing agent list for --speckit"
  require_arg "$dest" "Missing destination repository for --speckit"
  ensure_dest_exists "$dest"

  local runner
  if ! runner="$(speckit_runner)"; then
    warn "Neither 'uvx' nor 'uv' found. Install uv (https://docs.astral.sh/uv/), then run per agent from $dest:"
    warn "  uvx --from git+https://github.com/github/spec-kit.git specify init --here --force --non-interactive --integration <agent>"
    return 0
  fi

  local agent agents=()
  while IFS= read -r agent; do
    [[ -n "$agent" ]] && agents+=("$agent")
  done < <(tr ',' '\n' <<< "$agents_csv")

  for agent in "${agents[@]}"; do
    agent="$(trim "$agent")"
    [[ -n "$agent" ]] || continue

    local integration
    integration="$(speckit_integration_for "$agent")"
    if [[ -z "$integration" ]]; then
      warn "No confirmed spec-kit --integration slug for '$agent'. From $dest, run 'specify integration list'" \
           "to check the current options for your installed spec-kit version, then run manually if one applies:" \
           "specify init --here --force --non-interactive --integration <value>"
      continue
    fi

    info "Installing spec-kit for '$agent' (--integration $integration) via the official specify CLI (downloads spec-kit on first use)..."
    if (cd "$dest" && $runner init --here --force --non-interactive --integration "$integration"); then
      ok "spec-kit installed for '$agent'."
    else
      warn "spec-kit init failed for '$agent' (--integration $integration). From $dest, run 'specify integration list' to see" \
           "the valid values for your installed spec-kit version, then retry:" \
           "specify init --here --integration <value>"
    fi
  done

  # Without this, spec-kit's own /speckit-specify never creates a feature
  # branch: recent spec-kit versions moved that out of the core command and
  # into an optional `before_specify` hook (see .specify/extensions.yml),
  # which only this "git" extension registers — plain `specify init` does
  # not. Repo-level, not per-agent (regenerates the hook-invoking skill/
  # command files for whichever agent integrations are already installed).
  # Idempotent: `extension add` exits non-zero with "already installed" on a
  # repo that already has it (e.g. a --workflow speckit re-run) — treated as
  # a no-op, not a failure.
  local extension_output
  if extension_output="$(cd "$dest" && $runner extension add git 2>&1)"; then
    ok "Installed spec-kit's git branching extension (creates/switches to a feature branch automatically before /speckit-specify)."
  elif grep -qi "already installed" <<< "$extension_output"; then
    info "spec-kit's git branching extension is already installed — leaving it as-is."
  else
    warn "Could not install spec-kit's git branching extension automatically. Without it, /speckit-specify will not" \
         "create a feature branch on its own. From $dest, run: $runner extension add git"
    printf '%s\n' "$extension_output" | sed 's/^/    /'
  fi

  ensure_gitignore_entry "$dest" "specs/*/.token-usage.json" \
    "Per-spec AI agent token usage (local telemetry written by ~/.claude or ~/.copilot/statusline.py; not source)"
}

# Maps this kit's own agent names to the OpenSpec CLI's `--tools` slugs, which
# also don't always match this kit's or spec-kit's naming (confirmed against
# the OpenSpec CLI reference docs). Left blank = no confirmed mapping.
openspec_tool_for() {
  case "$1" in
    copilot) printf 'github-copilot' ;;
    claude) printf 'claude' ;;
    cursor) printf 'cursor' ;;
    windsurf) printf 'windsurf' ;;
    jetbrains) printf '' ;;
    *) printf '' ;;
  esac
}

openspec_runner() {
  if command -v openspec >/dev/null 2>&1; then
    printf 'openspec'
  elif command -v npx >/dev/null 2>&1; then
    printf 'npx --yes @fission-ai/openspec@latest'
  else
    return 1
  fi
}

do_openspec() {
  local agents_csv="${1:-}" dest="${2:-}"
  require_arg "$agents_csv" "Missing agent list for --openspec"
  require_arg "$dest" "Missing destination repository for --openspec"
  ensure_dest_exists "$dest"

  local runner
  if ! runner="$(openspec_runner)"; then
    warn "Neither 'openspec' nor 'npx' found. Install Node.js 20.19+ (https://nodejs.org), then run from $dest:"
    warn "  npx --yes @fission-ai/openspec@latest init --tools <value> --force"
    return 0
  fi

  local agent agents=() tools=()
  while IFS= read -r agent; do
    [[ -n "$agent" ]] && agents+=("$agent")
  done < <(tr ',' '\n' <<< "$agents_csv")

  for agent in "${agents[@]}"; do
    agent="$(trim "$agent")"
    [[ -n "$agent" ]] || continue
    local tool
    tool="$(openspec_tool_for "$agent")"
    if [[ -z "$tool" ]]; then
      warn "No confirmed OpenSpec --tools slug for '$agent'. From $dest, run 'openspec init --help' to check current options."
      continue
    fi
    tools+=("$tool")
  done

  if [[ "${#tools[@]}" -eq 0 ]]; then
    warn "No mappable agents for OpenSpec; skipping 'openspec init'."
    return 0
  fi

  local tools_csv
  tools_csv="$(IFS=,; printf '%s' "${tools[*]}")"
  info "Running 'openspec init --tools $tools_csv' via $runner (creates openspec/config.yaml + changes/," \
       "and refreshes the native skill files for these agents — this can overwrite the static snapshot" \
       "shipped in .ai/skills/openspec-* with your installed OpenSpec CLI's own current version)..."
  if (cd "$dest" && $runner init --tools "$tools_csv" --force); then
    ok "OpenSpec initialized for: $tools_csv"
  else
    warn "openspec init failed. From $dest, run manually: $runner init --tools $tools_csv --force"
  fi
}

do_workflow() {
  local workflow="${1:-}" dest="${2:-}"
  require_arg "$workflow" "Missing workflow for --workflow (openspec|speckit|none)"
  require_arg "$dest" "Missing destination repository for --workflow"
  ensure_dest_exists "$dest"
  ensure_source_exists

  if [[ ! -d "$dest/.ai" ]]; then
    warn "Destination has no .ai directory; copying source package first"
    do_copy "$dest"
  fi

  prune_workflow "$dest" "$workflow"

  if [[ "$workflow" == "speckit" ]]; then
    local detected
    detected="$(detect_agents "$dest" | tr '\n' ',' | sed 's/,$//')"
    if [[ -z "$detected" ]]; then
      warn "No native agent files detected yet in $dest. Run --agents first, then re-run:"
      warn "  $(basename "$0") --workflow speckit $dest"
      return 0
    fi
    do_speckit "$detected" "$dest"
  elif [[ "$workflow" == "openspec" ]]; then
    info "Reminder: the static .ai/skills/openspec-* files alone can't create openspec/config.yaml" \
         "or changes/ — those only come from the real OpenSpec CLI. Run, once agents are generated:"
    info "  $(basename "$0") --openspec <agents> $dest"
  fi
}

do_init() {
  local dest="${1:-}"
  require_arg "$dest" "Missing destination repository for --init"
  ensure_dest_exists "$dest"
  ensure_source_exists

  printf '\n=== AI Workspace Starter Kit — interactive install ===\n\n'

  printf 'Which AI agent(s) do you use? (comma-separated numbers, e.g. 1,2)\n'
  printf '  1) GitHub Copilot\n  2) Claude\n  3) Cursor\n  4) Windsurf\n  5) JetBrains AI\n'
  local agent_choice
  read -r -p "> " agent_choice
  local agent_names=() nums n
  IFS=',' read -ra nums <<< "$agent_choice"
  for n in "${nums[@]}"; do
    n="$(trim "$n")"
    case "$n" in
      1) agent_names+=("copilot") ;;
      2) agent_names+=("claude") ;;
      3) agent_names+=("cursor") ;;
      4) agent_names+=("windsurf") ;;
      5) agent_names+=("jetbrains") ;;
      "") ;;
      *) warn "Ignoring unrecognized option: $n" ;;
    esac
  done
  if [[ "${#agent_names[@]}" -eq 0 ]]; then
    err "No valid agent selected."
    exit 1
  fi
  local agents_csv
  agents_csv="$(IFS=,; printf '%s' "${agent_names[*]}")"

  printf '\nWhich spec-driven workflow do you want?\n'
  printf '  1) OpenSpec  — delegates to the official '\''openspec'\'' CLI (installed automatically via npx if missing)\n'
  printf '  2) spec-kit  — delegates to GitHub'\''s official '\''specify'\'' CLI (installed automatically via uv/uvx if missing)\n'
  printf '  3) None      — skip both, no spec-driven workflow skills installed\n'
  local workflow_choice workflow
  read -r -p "> " workflow_choice
  case "$(trim "$workflow_choice")" in
    1) workflow="openspec" ;;
    2) workflow="speckit" ;;
    3) workflow="none" ;;
    *) warn "Unrecognized choice, defaulting to OpenSpec."; workflow="openspec" ;;
  esac

  printf '\n'
  local graph_choice
  read -r -p "Install the optional Neo4j architecture graph (Step 2)? [y/N] " graph_choice

  printf '\n'
  info "Installing .ai/ into $dest..."
  do_copy "$dest"
  prune_workflow "$dest" "$workflow"
  do_scan "$dest"
  do_agents "$agents_csv" "$dest"
  if [[ "$workflow" == "speckit" ]]; then
    do_speckit "$agents_csv" "$dest"
  elif [[ "$workflow" == "openspec" ]]; then
    do_openspec "$agents_csv" "$dest"
  fi
  case "$(trim "${graph_choice:-}")" in
    y|Y|yes|YES) do_graph "$dest" ;;
    *) info "Skipping the Neo4j architecture graph. Run '$(basename "$0") --graph $dest' later if you change your mind." ;;
  esac

  printf '\n'
  ok "Setup complete for: $agents_csv (workflow=$workflow)"
  do_check "$dest"
}

case "${1:-}" in
  --copy)
    do_copy "${2:-}"
    ;;
  --scan)
    do_scan "${2:-}"
    ;;
  --agents)
    do_agents "${2:-}" "${3:-}"
    ;;
  --sync)
    do_sync "${2:-}"
    ;;
  --update)
    do_update "${2:-}"
    ;;
  --check)
    do_check "${2:-}"
    ;;
  --graph)
    do_graph "${2:-}"
    ;;
  --statusline)
    do_statusline "${2:-claude}"
    ;;
  --init)
    do_init "${2:-}"
    ;;
  --workflow)
    do_workflow "${2:-}" "${3:-}"
    ;;
  --speckit)
    do_speckit "${2:-}" "${3:-}"
    ;;
  --openspec)
    do_openspec "${2:-}" "${3:-}"
    ;;
  --help|"")
    usage
    ;;
  *)
    err "Unknown option: ${1:-}"
    usage
    exit 1
    ;;
esac
