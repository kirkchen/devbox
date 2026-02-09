#!/bin/bash
# Configure Claude Code settings
# This script merges synced fields into ~/.claude/settings.json
# without touching other files in ~/.claude/
#
# run_onchange_: re-runs when this script's content changes
# (e.g., when permissions.deny rules are updated)

set -e

SETTINGS_FILE="$HOME/.claude/settings.json"

echo "=== Configuring Claude Code Settings ==="

# Ensure directory exists
mkdir -p "$HOME/.claude"

# Define the fields we want to sync
# hash: {{ include ".chezmoiscripts/run_onchange_05-configure-claude-settings.sh" | sha256sum }}
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

if ! command -v jq &>/dev/null; then
    echo "⚠ jq not found, skipping Claude settings configuration"
    exit 0
fi

# If file doesn't exist, create with defaults
if [ ! -f "$SETTINGS_FILE" ]; then
    echo "$synced_fields" | jq '.' > "$SETTINGS_FILE"
    echo "✓ Created $SETTINGS_FILE"
    exit 0
fi

# Merge synced fields into existing settings
existing=$(cat "$SETTINGS_FILE")
echo "$existing" | jq --argjson sync "$synced_fields" '. * $sync' > "${SETTINGS_FILE}.tmp"
mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
echo "✓ Updated $SETTINGS_FILE (merged permissions.deny)"

echo "=== Claude Code settings configured ==="
