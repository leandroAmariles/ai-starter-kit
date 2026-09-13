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
#
# Usage:
#   ./ai-bootstrap.sh
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

INSTALLER="$TMP_DIR/kit/install-ai-package.sh"
chmod +x "$INSTALLER"

if [[ -d "$REPO_ROOT/.ai" ]]; then
  echo "Existing .ai/ found in $REPO_ROOT — updating to the latest kit version..."
  "$INSTALLER" --update "$REPO_ROOT"
else
  echo "No .ai/ found in $REPO_ROOT — running the first-install wizard..."
  "$INSTALLER" --init "$REPO_ROOT"
fi
