#!/bin/bash
set -e

echo "🚀 Installing TPM (Tmux Plugin Manager)..."

# Check if tmux is available
if ! command -v tmux &> /dev/null; then
    echo "⚠️ tmux is not installed. Skipping TPM installation."
    exit 0
fi

# Install TPM if not already installed
if [ ! -d "$HOME/.tmux/plugins/tpm" ]; then
    echo "Installing TPM..."
    git clone https://github.com/tmux-plugins/tpm "$HOME/.tmux/plugins/tpm"
    echo "✅ TPM installed successfully"
    echo "💡 To install tmux plugins, start tmux and press prefix + I (Ctrl-a + I)"
else
    echo "✅ TPM already installed"
fi

echo "✅ Tmux plugin setup complete!"