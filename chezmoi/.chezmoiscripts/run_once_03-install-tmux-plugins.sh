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
else
    echo "✅ TPM already installed"
fi

# Automatically install all tmux plugins
echo "📦 Installing tmux plugins..."
if [ -f "$HOME/.tmux/plugins/tpm/bin/install_plugins" ]; then
    "$HOME/.tmux/plugins/tpm/bin/install_plugins"
    echo "✅ All tmux plugins installed successfully"
else
    echo "⚠️ TPM install script not found. Plugins will be installed on first tmux launch."
fi

echo "✅ Tmux plugin setup complete!"