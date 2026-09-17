#!/usr/bin/env bash
# Installs or updates this repo's AI agent configuration (CLAUDE.md, .claude/,
# .github/copilot-instructions.md, etc.) from the centralized, versioned
# ai-starter-kit — https://github.com/leandroAmariles/ai-starter-kit.
#
# This is the ONLY thing this repo keeps locally for that purpose: no vendored
# copy of the kit itself. Every run clones the kit fresh, then:
#   - no .ai/ yet here            -> runs the interactive first-install wizard
#   - .ai/ already installed here -> runs a non-interactive update (safe to
#                                    re-run any time; no-ops cleanly if already
#                                    current)
# Either way, if the optional Neo4j architecture graph (graph-rag/) is already
# set up here — or --graph is passed — this also re-verifies it and brings its
# Docker container back up (or creates it fresh) if it was stopped or removed
# since the last run. That container's data lives in a separate, named Docker
# volume that survives the container being deleted, so recreating it picks the
# graph back up rather than starting over — this only re-scans the repo to
# refresh it. See "Recreating a deleted Neo4j container" in graph-rag/README.md.
#
# Usage:
#   ./ai-bootstrap.sh            # install/update .ai/, heal the graph if present
#   ./ai-bootstrap.sh --graph    # also (re)run the optional Neo4j graph step,
#                                #  even on a repo that doesn't have it yet
#
# Override via environment variables if needed:
#   AI_KIT_REPO_URL=git@github.com:leandroAmariles/ai-starter-kit.git ./ai-bootstrap.sh
#   AI_KIT_REF=v1.0.0 ./ai-bootstrap.sh   # pin a specific tag instead of main (latest)
set -euo pipefail

AI_KIT_REPO_URL="${AI_KIT_REPO_URL:-https://github.com/leandroAmariles/ai-starter-kit.git}"
AI_KIT_REF="${AI_KIT_REF:-main}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

echo "Fetching ai-starter-kit (@${AI_KIT_REF}) from ${AI_KIT_REPO_URL}..."
git clone --quiet --depth 1 --branch "$AI_KIT_REF" "$AI_KIT_REPO_URL" "$TMP_DIR/kit"

# Self-update FIRST, before anything else runs: if the freshly-cloned kit
# ships a different ai-bootstrap.sh than the one currently executing, replace
# the on-disk copy and immediately `exec` it (same args) so every line below
# always runs the current logic. Rewriting this running script's own file
# and continuing to execute past that point WITHOUT re-exec-ing is unsafe —
# bash can end up reading a spliced mix of old/new bytes for what follows and
# fail with a confusing syntax error, even though the copy on disk is fine.
SELF="$TMP_DIR/kit/ai-bootstrap.sh"
if [[ -f "$SELF" ]] && ! cmp -s "$SELF" "$REPO_ROOT/ai-bootstrap.sh" 2>/dev/null; then
  cp "$SELF" "$REPO_ROOT/ai-bootstrap.sh"
  chmod +x "$REPO_ROOT/ai-bootstrap.sh"
  echo "ai-bootstrap.sh itself was updated to the latest version — re-running it (review with 'git diff ai-bootstrap.sh' and commit it once it's done)..."
  # `exec` replaces this process outright, so the EXIT trap above never
  # fires for it — clean up the clone manually before handing off.
  rm -rf "$TMP_DIR"
  exec "$REPO_ROOT/ai-bootstrap.sh" "$@"
fi

INSTALLER="$TMP_DIR/kit/install-ai-package.sh"
chmod +x "$INSTALLER"

if [[ -d "$REPO_ROOT/.ai" ]]; then
  echo "Existing .ai/ found in $REPO_ROOT — updating to the latest kit version..."
  "$INSTALLER" --update "$REPO_ROOT"
else
  echo "No .ai/ found in $REPO_ROOT — running the first-install wizard..."
  "$INSTALLER" --init "$REPO_ROOT"
fi

# The wizard's own Neo4j question above only runs on a brand-new --init. On
# every later run (the common --update case), or if graph-rag/ already
# exists, or if --graph was passed explicitly, re-verify the graph: --graph
# is idempotent — it reuses graph-rag/.env exactly as-is (never touching
# PROJECT_PATHS you configured) and starts its Docker container only if one
# isn't already reachable, so this is safe and quick to run every time.
if [[ -d "$REPO_ROOT/graph-rag" || "${1:-}" == "--graph" ]]; then
  echo "Making sure the Neo4j architecture graph is up in $REPO_ROOT..."
  "$INSTALLER" --graph "$REPO_ROOT"
fi
