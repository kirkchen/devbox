#!/bin/bash
# Install Claude Code plugins
# This script runs once when chezmoi apply is executed

set -e

echo "=== Claude Code Plugins Installation ==="

CLAUDE_BIN=""
if command -v claude &>/dev/null; then
    CLAUDE_BIN="claude"
elif [[ -x "$HOME/.local/bin/claude" ]]; then
    CLAUDE_BIN="$HOME/.local/bin/claude"
else
    echo "Claude Code CLI not found, skipping plugin installation."
    echo "Install it with: curl -fsSL https://claude.ai/install.sh | bash"
    exit 0
fi

echo "Installing Claude Code plugins..."

# Add superpowers marketplace (includes code-review and superpowers plugins)
if ! $CLAUDE_BIN plugin marketplace list 2>/dev/null | grep -q "superpowers-marketplace"; then
    echo "Adding superpowers marketplace..."
    $CLAUDE_BIN plugin marketplace add obra/superpowers-marketplace 2>/dev/null || \
        echo "⚠ Failed to add superpowers marketplace"
fi

# Install superpowers plugin (includes code-review skills)
if $CLAUDE_BIN plugin install superpowers@superpowers-marketplace 2>/dev/null; then
    echo "✓ superpowers plugin installed"
else
    echo "⚠ superpowers plugin installation failed (may already be installed)"
fi

echo "=== Claude Code plugins setup complete ==="
