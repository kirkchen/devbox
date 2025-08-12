#!/bin/bash

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           🚀 DevContainer Dotfiles Setup                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Check if already configured
if [ -f "$HOME/.config/chezmoi/chezmoi.toml" ]; then
    echo "✅ Dotfiles already configured!"
    echo ""
    echo "To reconfigure, run:"
    echo "  chezmoi init --source='/workspaces/devbox/chezmoi' --apply"
    echo ""
    exit 0
fi

echo "This script will set up your personal dotfiles configuration."
echo "You'll be asked a few questions to customize your environment."
echo ""
echo "Press Enter to continue or Ctrl+C to cancel..."
read

# Install Chezmoi if needed
if ! command -v chezmoi &> /dev/null; then
    echo "📦 Installing Chezmoi..."
    sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin"
    export PATH="$HOME/.local/bin:$PATH"
    echo "✅ Chezmoi installed!"
    echo ""
fi

# Initialize Chezmoi with local dotfiles
WORKSPACE_DIR="/workspaces/devbox"
CHEZMOI_SOURCE_DIR="$WORKSPACE_DIR/chezmoi"

if [ -d "$CHEZMOI_SOURCE_DIR" ]; then
    echo "🔧 Initializing your dotfiles..."
    echo ""
    
    # Initialize with interactive prompts
    if chezmoi init --source="$CHEZMOI_SOURCE_DIR"; then
        echo ""
        echo "📝 Configuration saved! Now applying dotfiles..."
        
        # Ensure source directory exists and has content
        if [ ! -d "$HOME/.local/share/chezmoi" ] || [ -z "$(ls -A $HOME/.local/share/chezmoi 2>/dev/null)" ]; then
            echo "🔄 Setting up source directory..."
            mkdir -p "$HOME/.local/share/chezmoi"
            cp -r "$CHEZMOI_SOURCE_DIR"/* "$HOME/.local/share/chezmoi/" 2>/dev/null || true
            cp -r "$CHEZMOI_SOURCE_DIR"/.[^.]* "$HOME/.local/share/chezmoi/" 2>/dev/null || true
        fi
        
        # Apply the configuration
        if chezmoi apply; then
            echo ""
            echo "✅ Dotfiles successfully installed!"
            echo ""
            echo "🎉 Setup complete! Please restart your terminal or run:"
            echo "   source ~/.zshrc"
            echo ""
            echo "💡 Tips:"
            echo "  • To see what files are managed: chezmoi managed"
            echo "  • To update dotfiles later: chezmoi apply"
            echo "  • To edit configuration: chezmoi edit ~/.zshrc"
        else
            echo "⚠️ Failed to apply dotfiles. Please check the error above."
            exit 1
        fi
    else
        echo "⚠️ Failed to initialize Chezmoi. Please check the error above."
        exit 1
    fi
else
    echo "❌ Chezmoi source directory not found at $CHEZMOI_SOURCE_DIR"
    echo ""
    echo "Please ensure you're running this from the DevContainer."
    exit 1
fi