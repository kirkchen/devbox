#!/bin/bash
# Configure Claude Code settings, CLAUDE.md, and custom skills
# This script:
# 1. Merges permissions.deny into ~/.claude/settings.json
# 2. Copies CLAUDE.md from chezmoi source to ~/.claude/CLAUDE.md
# 3. Installs custom commands to ~/.claude/commands/
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

agent_state_cmd="~/.tmux/plugins/tmux-agent-indicator/scripts/agent-state.sh"

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

    # Ensure agent-indicator hooks exist for Claude Code state tracking
    for pair in \
        "UserPromptSubmit:$agent_state_cmd --agent claude --state running" \
        "Notification:$agent_state_cmd --agent claude --state needs-input" \
        "Stop:$agent_state_cmd --agent claude --state done"; do
        event="${pair%%:*}"
        hook_cmd="${pair#*:}"
        hook_json="{\"type\":\"command\",\"command\":\"${hook_cmd}\",\"async\":true}"
        has_hook=$(jq --arg cmd "$hook_cmd" \
            "[.hooks.${event}[]?.hooks[]? | select(.command == \$cmd)] | length" \
            "$SETTINGS_FILE" 2>/dev/null || echo "0")
        if [ "$has_hook" = "0" ]; then
            jq --argjson hook "$hook_json" \
                "if .hooks.${event} then .hooks.${event}[0].hooks += [\$hook] else .hooks.${event} = [{\"hooks\": [\$hook]}] end" \
                "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp"
            mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
            echo "✓ Added agent-indicator hook to ${event}"
        else
            echo "✓ Agent-indicator hook already exists in ${event}"
        fi
    done

    # macOS notifications via notify script for Notification and Stop events
    if [ "$(uname)" = "Darwin" ]; then
        notify_cmd="~/.config/claude/hooks/notify-macos.sh"
        for event in Notification Stop; do
            hook_json="{\"type\":\"command\",\"command\":\"${notify_cmd}\",\"async\":true}"
            has_hook=$(jq --arg cmd "$notify_cmd" \
                "[.hooks.${event}[]?.hooks[]? | select(.command == \$cmd)] | length" \
                "$SETTINGS_FILE" 2>/dev/null || echo "0")
            if [ "$has_hook" = "0" ]; then
                jq --argjson hook "$hook_json" \
                    "if .hooks.${event} then .hooks.${event}[0].hooks += [\$hook] else .hooks.${event} = [{\"hooks\": [\$hook]}] end" \
                    "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp"
                mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
                echo "✓ Added macOS notification hook to ${event}"
            else
                echo "✓ macOS notification hook already exists in ${event}"
            fi
        done
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

# --- 3. Install custom commands ---
COMMANDS_SRC="${SOURCE_DIR}/claude-code/commands"

if [ -n "$SOURCE_DIR" ] && [ -d "$COMMANDS_SRC" ]; then
    mkdir -p "$HOME/.claude/commands"
    for cmd_file in "$COMMANDS_SRC"/*.md; do
        [ -f "$cmd_file" ] || continue
        cp "$cmd_file" "$HOME/.claude/commands/"
        echo "✓ Installed command: /$(basename "$cmd_file" .md)"
    done
else
    echo "⚠ Commands source not found at $COMMANDS_SRC, skipping"
fi

echo "=== Claude Code configuration complete ==="
