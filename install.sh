#!/bin/bash

# =============================================================================
# Dotfiles Auto-Installation Script
# =============================================================================
# This script is automatically executed by Gitpod when dotfiles repo is configured
# It also works with DevContainers and local environments
# =============================================================================

set -e  # Exit on error

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

log_error() {
    echo -e "${RED}❌ $1${NC}"
}

# Header
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           🚀 Dotfiles Auto-Installation                       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# =============================================================================
# Environment Detection
# =============================================================================
detect_environment() {
    if [ -n "$GITPOD_WORKSPACE_ID" ]; then
        echo "Gitpod"
    elif [ -n "$CODESPACES" ]; then
        echo "Codespaces"
    elif [ -f /.dockerenv ] || [ -n "$REMOTE_CONTAINERS" ]; then
        echo "DevContainer"
    else
        echo "Local"
    fi
}

ENVIRONMENT=$(detect_environment)
log_info "Environment detected: $ENVIRONMENT"

# =============================================================================
# Git Configuration Detection
# =============================================================================
detect_git_config() {
    local name=""
    local email=""
    local source=""
    
    # Priority 1: Gitpod environment variables
    if [ -n "$GITPOD_GIT_USER_NAME" ] && [ -n "$GITPOD_GIT_USER_EMAIL" ]; then
        name="$GITPOD_GIT_USER_NAME"
        email="$GITPOD_GIT_USER_EMAIL"
        source="Gitpod environment"
    
    # Priority 2: Standard environment variables (for DevContainer)
    elif [ -n "$GIT_USER_NAME" ] && [ -n "$GIT_USER_EMAIL" ]; then
        name="$GIT_USER_NAME"
        email="$GIT_USER_EMAIL"
        source="environment variables"
    
    # Priority 3: Existing git configuration
    elif command -v git &> /dev/null; then
        local existing_name=$(git config --global user.name 2>/dev/null || true)
        local existing_email=$(git config --global user.email 2>/dev/null || true)
        
        if [ -n "$existing_name" ] && [ -n "$existing_email" ]; then
            name="$existing_name"
            email="$existing_email"
            source="existing Git configuration"
        fi
    fi
    
    # Priority 4: GitHub Codespaces
    if [ -z "$name" ] && [ -n "$GITHUB_USER" ]; then
        name="$GITHUB_USER"
        email="$GITHUB_USER@users.noreply.github.com"
        source="GitHub Codespaces"
    fi
    
    # Priority 5: Default values
    if [ -z "$name" ] || [ -z "$email" ]; then
        name="${USER:-Developer}"
        email="${USER:-developer}@example.com"
        source="default values"
        log_warning "Using default values for Git configuration"
        log_warning "Set GITPOD_GIT_USER_NAME and GITPOD_GIT_USER_EMAIL in Gitpod settings"
        log_warning "Or set GIT_USER_NAME and GIT_USER_EMAIL environment variables"
    fi
    
    # Export for use in the script
    export GIT_USER_NAME="$name"
    export GIT_USER_EMAIL="$email"
    
    log_success "Git configuration detected from $source:"
    echo "  Name:  $GIT_USER_NAME"
    echo "  Email: $GIT_USER_EMAIL"
    echo ""
}

# =============================================================================
# Chezmoi Installation
# =============================================================================
install_chezmoi() {
    if command -v chezmoi &> /dev/null; then
        log_info "Chezmoi is already installed ($(chezmoi --version))"
    else
        log_info "Installing Chezmoi..."
        
        # Install to user's local bin
        export BINDIR="$HOME/.local/bin"
        mkdir -p "$BINDIR"
        
        # Download and install
        sh -c "$(curl -fsLS get.chezmoi.io)" -- -b "$BINDIR"
        
        # Add to PATH if not already there
        if [[ ":$PATH:" != *":$BINDIR:"* ]]; then
            export PATH="$BINDIR:$PATH"
            
            # Add to shell RC files for persistence
            for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
                if [ -f "$rc" ]; then
                    grep -q "export PATH=\"\$HOME/.local/bin:\$PATH\"" "$rc" || \
                        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$rc"
                fi
            done
        fi
        
        log_success "Chezmoi installed successfully"
    fi
}

# =============================================================================
# Dotfiles Installation
# =============================================================================
install_dotfiles() {
    local SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    local CHEZMOI_SOURCE_DIR="$SCRIPT_DIR/chezmoi"
    
    if [ ! -d "$CHEZMOI_SOURCE_DIR" ]; then
        log_error "Chezmoi source directory not found at $CHEZMOI_SOURCE_DIR"
        exit 1
    fi
    
    log_info "Initializing dotfiles from $CHEZMOI_SOURCE_DIR..."
    
    # Initialize chezmoi with the detected configuration
    # Using --promptString to pass values non-interactively
    if chezmoi init \
        --apply \
        --source="$CHEZMOI_SOURCE_DIR" \
        --promptString name="$GIT_USER_NAME" \
        --promptString email="$GIT_USER_EMAIL" \
        2>&1 | while read -r line; do echo "  $line"; done; then
        
        log_success "Dotfiles installed successfully!"
        
        # Verify git configuration was set
        if command -v git &> /dev/null; then
            local configured_name=$(git config --global user.name 2>/dev/null || true)
            local configured_email=$(git config --global user.email 2>/dev/null || true)
            
            if [ "$configured_name" = "$GIT_USER_NAME" ] && [ "$configured_email" = "$GIT_USER_EMAIL" ]; then
                log_success "Git configuration verified"
            fi
        fi
    else
        log_error "Failed to apply dotfiles"
        exit 1
    fi
}

# =============================================================================
# Post-installation tasks
# =============================================================================
post_install() {
    log_info "Running post-installation tasks..."
    
    # Install Oh My Zsh if not present and zsh is available
    if command -v zsh &> /dev/null && [ ! -d "$HOME/.oh-my-zsh" ]; then
        log_info "Installing Oh My Zsh..."
        # Non-interactive installation
        RUNZSH=no KEEP_ZSHRC=yes sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended
        log_success "Oh My Zsh installed"
    fi
    
    # Set zsh as default shell if available and not already set
    if command -v zsh &> /dev/null && [ "$SHELL" != "$(command -v zsh)" ]; then
        if command -v chsh &> /dev/null; then
            log_info "Setting zsh as default shell..."
            sudo chsh -s "$(command -v zsh)" "$USER" 2>/dev/null || true
        fi
    fi
    
    echo ""
    log_success "Dotfiles installation complete!"
    echo ""
    echo "💡 Tips:"
    echo "  • To see managed files: chezmoi managed"
    echo "  • To update dotfiles: chezmoi apply"
    echo "  • To edit a file: chezmoi edit <file>"
    echo "  • To see differences: chezmoi diff"
    echo ""
    
    # Source the new configuration if in an interactive shell
    if [[ $- == *i* ]]; then
        if [ -f "$HOME/.zshrc" ] && [ -n "$ZSH_VERSION" ]; then
            log_info "Reloading zsh configuration..."
            source "$HOME/.zshrc"
        elif [ -f "$HOME/.bashrc" ] && [ -n "$BASH_VERSION" ]; then
            log_info "Reloading bash configuration..."
            source "$HOME/.bashrc"
        fi
    else
        echo "🔄 Please restart your shell or run: source ~/.zshrc"
    fi
}

# =============================================================================
# Main Execution
# =============================================================================
main() {
    # Detect Git configuration
    detect_git_config
    
    # Install Chezmoi
    install_chezmoi
    
    # Install dotfiles
    install_dotfiles
    
    # Post-installation
    post_install
}

# Run main function
main "$@"