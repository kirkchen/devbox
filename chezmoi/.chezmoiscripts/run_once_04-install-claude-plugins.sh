#!/bin/bash
# Install Claude Code plugins
# This script runs once when chezmoi apply is executed

set -e

echo "=== Claude Code Plugins Installation ==="

if ! command -v claude &>/dev/null; then
    echo "Claude Code CLI not found, skipping plugin installation."
    echo "Install it with: npm install -g @anthropic-ai/claude-code"
    exit 0
fi

echo "Installing Claude Code plugins..."

# Install code-review plugin
if claude plugins:install code-review@claude-plugins-official 2>/dev/null; then
    echo "✓ code-review plugin installed"
else
    echo "⚠ code-review plugin installation failed (may already be installed)"
fi

# Install superpowers plugin
if claude plugins:install superpowers@claude-plugins-official 2>/dev/null; then
    echo "✓ superpowers plugin installed"
else
    echo "⚠ superpowers plugin installation failed (may already be installed)"
fi

echo "=== Claude Code plugins setup complete ==="
