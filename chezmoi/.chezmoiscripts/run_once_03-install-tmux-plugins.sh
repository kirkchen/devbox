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
    # Set the TMUX_PLUGIN_MANAGER_PATH if not already set
    export TMUX_PLUGIN_MANAGER_PATH="$HOME/.tmux/plugins/"
    
    # Try to install plugins, but don't fail if tmux config isn't loaded yet
    if "$HOME/.tmux/plugins/tpm/bin/install_plugins" 2>/dev/null; then
        echo "✅ All tmux plugins installed successfully"
    else
        echo "⚠️ Plugins will be installed on first tmux launch (press prefix + I inside tmux)"
        echo "   This is normal when tmux config hasn't been loaded yet."
    fi
else
    echo "⚠️ TPM install script not found. Plugins will be installed on first tmux launch."
fi

echo "✅ Tmux plugin setup complete!"