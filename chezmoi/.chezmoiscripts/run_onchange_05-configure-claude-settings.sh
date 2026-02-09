#!/bin/bash
# Configure Claude Code settings and CLAUDE.md
# This script:
# 1. Merges permissions.deny into ~/.claude/settings.json
# 2. Copies CLAUDE.md from chezmoi source to ~/.claude/CLAUDE.md
#
# run_onchange_: re-runs when this script's content changes
# hash: {{ include ".chezmoiscripts/run_onchange_05-configure-claude-settings.sh" | sha256sum }}

set -e

echo "=== Configuring Claude Code ==="

# Ensure directory exists
mkdir -p "$HOME/.claude"

# --- 1. Merge settings.json ---
SETTINGS_FILE="$HOME/.claude/settings.json"

synced_fields='{
  "permissions": {
    "deny": [
      "Read(.env*)",
      "Read(**/secrets/**)",
      "Write(.env*)",
      "Bash(rm -rf /)"
    ]
  }
}'

if command -v jq &>/dev/null; then
    if [ ! -f "$SETTINGS_FILE" ]; then
        echo "$synced_fields" | jq '.' > "$SETTINGS_FILE"
        echo "✓ Created $SETTINGS_FILE"
    else
        existing=$(cat "$SETTINGS_FILE")
        echo "$existing" | jq --argjson sync "$synced_fields" '. * $sync' > "${SETTINGS_FILE}.tmp"
        mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
        echo "✓ Updated $SETTINGS_FILE (merged permissions.deny)"
    fi
else
    echo "⚠ jq not found, skipping settings.json configuration"
fi

# --- 2. Copy CLAUDE.md ---
SOURCE_DIR="${CHEZMOI_SOURCE_DIR:-$(chezmoi source-path 2>/dev/null || echo "")}"
CLAUDE_MD_SRC="${SOURCE_DIR}/claude-code/CLAUDE.md"

if [ -n "$SOURCE_DIR" ] && [ -f "$CLAUDE_MD_SRC" ]; then
    cp "$CLAUDE_MD_SRC" "$HOME/.claude/CLAUDE.md"
    echo "✓ Copied CLAUDE.md to ~/.claude/"
else
    echo "⚠ CLAUDE.md source not found at $CLAUDE_MD_SRC, skipping"
fi

echo "=== Claude Code configuration complete ==="
