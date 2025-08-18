#!/bin/bash

# Automated installation script for Gitpod and similar environments
# This script assumes name and email are already set in environment variables

set -e  # Exit on error

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           🚀 Automated Dotfiles Installation                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Function to detect environment
detect_environment() {
    if [ -n "$GITPOD_WORKSPACE_ID" ]; then
        echo "gitpod"
    elif [ -n "$CODESPACES" ]; then
        echo "codespaces"
    elif [ -f "/.dockerenv" ]; then
        echo "docker"
    else
        echo "local"
    fi
}

# Function to get user info from environment or git config
get_user_info() {
    # Try environment variables first (Gitpod sets these)
    if [ -n "$GITPOD_GIT_USER_NAME" ]; then
        USER_NAME="$GITPOD_GIT_USER_NAME"
    elif [ -n "$GIT_AUTHOR_NAME" ]; then
        USER_NAME="$GIT_AUTHOR_NAME"
    elif [ -n "$DEVBOX_USER_NAME" ]; then
        USER_NAME="$DEVBOX_USER_NAME"
    else
        # Fallback to git config
        USER_NAME=$(git config --global user.name 2>/dev/null || echo "")
    fi

    if [ -n "$GITPOD_GIT_USER_EMAIL" ]; then
        USER_EMAIL="$GITPOD_GIT_USER_EMAIL"
    elif [ -n "$GIT_AUTHOR_EMAIL" ]; then
        USER_EMAIL="$GIT_AUTHOR_EMAIL"
    elif [ -n "$DEVBOX_USER_EMAIL" ]; then
        USER_EMAIL="$DEVBOX_USER_EMAIL"
    else
        # Fallback to git config
        USER_EMAIL=$(git config --global user.email 2>/dev/null || echo "")
    fi
}

# Detect environment
ENV_TYPE=$(detect_environment)
echo "🔍 Detected environment: $ENV_TYPE"
echo ""

# Get user information
get_user_info

# Validate we have required information
if [ -z "$USER_NAME" ] || [ -z "$USER_EMAIL" ]; then
    echo "⚠️  Could not detect user name or email from environment."
    echo "   Please run setup-dotfiles.sh for interactive setup."
    echo ""
    echo "   Or set environment variables:"
    echo "   export GITPOD_GIT_USER_NAME='Your Name'"
    echo "   export GITPOD_GIT_USER_EMAIL='your.email@example.com'"
    exit 1
fi

echo "📋 Configuration:"
echo "   Name:  $USER_NAME"
echo "   Email: $USER_EMAIL"
echo ""

# Install Chezmoi if needed
if ! command -v chezmoi &> /dev/null; then
    echo "📦 Installing Chezmoi..."
    sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$HOME/.local/bin"
    export PATH="$HOME/.local/bin:$PATH"
    echo "✅ Chezmoi installed"
    echo ""
fi

# Determine chezmoi source directory
if [ -n "$DEV_CHEZMOI_SOURCE_DIR" ]; then
    # Use explicitly specified directory
    if [ -d "$DEV_CHEZMOI_SOURCE_DIR" ]; then
        CHEZMOI_SOURCE_DIR="$DEV_CHEZMOI_SOURCE_DIR"
        echo "📍 Using specified chezmoi source directory"
    else
        echo "❌ Specified DEV_CHEZMOI_SOURCE_DIR does not exist: $DEV_CHEZMOI_SOURCE_DIR"
        exit 1
    fi
else
    # Get the directory where this script is located
    SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    CHEZMOI_SOURCE_DIR="${SCRIPT_DIR}/chezmoi"
    
    # Verify the chezmoi directory exists
    if [ ! -d "$CHEZMOI_SOURCE_DIR" ]; then
        echo "❌ Could not find chezmoi directory at: $CHEZMOI_SOURCE_DIR"
        echo ""
        echo "   Expected structure:"
        echo "   ${SCRIPT_DIR}/"
        echo "   ├── install.sh (this script)"
        echo "   └── chezmoi/"
        echo ""
        echo "   You can specify a different directory with:"
        echo "   export DEV_CHEZMOI_SOURCE_DIR=/path/to/chezmoi"
        exit 1
    fi
fi

echo "📂 Using chezmoi source: $CHEZMOI_SOURCE_DIR"
echo ""

# Check if already configured
if [ -f "$HOME/.config/chezmoi/chezmoi.toml" ]; then
    echo "🔄 Existing configuration found, updating..."
else
    echo "🔧 Initializing dotfiles..."
fi

# Create chezmoi config directory
mkdir -p "$HOME/.config/chezmoi"

# Create the configuration file with detected values
cat > "$HOME/.config/chezmoi/chezmoi.toml" << EOF
[data]
    name = "$USER_NAME"
    email = "$USER_EMAIL"
    is_devcontainer = $([ "$ENV_TYPE" = "docker" ] && echo "true" || echo "false")
EOF

echo "✅ Configuration file created"
echo ""

# Initialize chezmoi with the source directory (non-interactive)
echo "🔄 Initializing chezmoi..."
if chezmoi init --source="$CHEZMOI_SOURCE_DIR" --no-tty; then
    # Ensure source directory is properly set up
    if [ ! -d "$HOME/.local/share/chezmoi" ] || [ -z "$(ls -A $HOME/.local/share/chezmoi 2>/dev/null)" ]; then
        echo "📁 Setting up source directory..."
        mkdir -p "$HOME/.local/share/chezmoi"
        cp -r "$CHEZMOI_SOURCE_DIR"/* "$HOME/.local/share/chezmoi/" 2>/dev/null || true
        cp -r "$CHEZMOI_SOURCE_DIR"/.[^.]* "$HOME/.local/share/chezmoi/" 2>/dev/null || true
    fi
    
    # Apply the configuration
    echo "📝 Applying dotfiles..."
    if chezmoi apply --no-tty; then
        echo ""
        echo "✅ Dotfiles successfully installed!"
        echo ""
        
        # Source the new configuration if we're in an interactive shell
        if [ -n "$PS1" ]; then
            if [ -f "$HOME/.zshrc" ] && [ "$SHELL" = "/bin/zsh" ] || [ "$SHELL" = "/usr/bin/zsh" ]; then
                echo "🔄 Reloading shell configuration..."
                source "$HOME/.zshrc"
            elif [ -f "$HOME/.bashrc" ] && [ "$SHELL" = "/bin/bash" ] || [ "$SHELL" = "/usr/bin/bash" ]; then
                echo "🔄 Reloading shell configuration..."
                source "$HOME/.bashrc"
            fi
        else
            echo "💡 Please restart your shell or run: source ~/.zshrc"
        fi
        
        echo ""
        echo "🎉 Installation complete!"
        echo ""
        echo "📚 Quick reference:"
        echo "   • Managed files: chezmoi managed"
        echo "   • Update config: chezmoi apply"
        echo "   • Edit files:    chezmoi edit <file>"
    else
        echo "⚠️  Failed to apply dotfiles. Please check the error above."
        exit 1
    fi
else
    echo "⚠️  Failed to initialize Chezmoi. Please check the error above."
    exit 1
fi