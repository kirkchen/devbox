# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a dotfiles management repository using Chezmoi for cross-platform development environment configuration. It provides intelligent dotfiles that adapt to macOS, Linux, and DevContainer environments with automatic setup for modern CLI tools, Zsh/Oh-My-Zsh, and development utilities.

## Installation

### Automated Installation (Gitpod/CI)

```bash
# For Gitpod or environments with pre-configured git user
./install.sh
```

The install script automatically detects:
- Gitpod environment variables (`GITPOD_GIT_USER_NAME`, `GITPOD_GIT_USER_EMAIL`)
- DevContainer environment variables (`DEVBOX_USER_NAME`, `DEVBOX_USER_EMAIL`)
- Git global config as fallback

### Manual Installation (Interactive)

```bash
# For local setup or when user info is not pre-configured
.devcontainer/scripts/setup-dotfiles.sh
```

## Key Commands

### Installation & Setup

```bash
# Automated installation (when git user/email are pre-configured)
./install.sh

# Interactive installation (prompts for name/email)
.devcontainer/scripts/setup-dotfiles.sh
```

### Gitpod Environment Management

```bash
# Interactive Gitpod environment management
gpenv start   # Start a stopped environment and optionally SSH into it
gpenv stop    # Stop a running environment
gpenv ssh     # SSH into a running environment
gpenv open    # Open a running environment in browser
gpenv list    # List all environments

# Shortcut aliases
gps   # gpenv start
gpt   # gpenv stop  
gpsh  # gpenv ssh
gpo   # gpenv open
gpl   # gpenv list
```

The `gpenv` function uses fzf for interactive selection when starting, stopping, or connecting to environments.

### Chezmoi Dotfiles Management

```bash
# Apply dotfiles changes from the chezmoi directory
chezmoi apply --source="./chezmoi"

# Test changes without applying (dry run)
chezmoi apply --source="./chezmoi" --dry-run --verbose

# See what would change
chezmoi diff --source="./chezmoi"

# Add a new dotfile to management
chezmoi add ~/.newconfig --source="./chezmoi"

# Re-run initialization (prompts for name/email)
chezmoi init --source="./chezmoi" --apply
```

### Testing Configuration Changes

```bash
# Validate template syntax
chezmoi execute-template < chezmoi/dot_zshrc.tmpl

# Test specific template with data
echo '{"name": "Test", "email": "test@example.com", "is_devcontainer": false}' | chezmoi execute-template --init < chezmoi/dot_gitconfig.tmpl

# Check shell configuration syntax
zsh -n chezmoi/dot_zshrc.tmpl
bash -n chezmoi/private_dot_config/zsh/aliases.zsh
```

## Architecture

### Chezmoi Template System

The repository uses Chezmoi's templating system with Go templates for environment-specific configuration:

- **Template Files** (`*.tmpl`): Contain conditional logic for different environments
- **Template Variables**:
  - `.name` and `.email`: User-provided during init
  - `.chezmoi.os`: Operating system ("darwin", "linux", "windows")
  - `.is_devcontainer`: Custom variable for DevContainer detection
  - `.chezmoi.hostname`: System hostname

### Environment Detection Flow

1. **chezmoi/.chezmoi.toml.tmpl**: Interactive configuration that prompts for user data
2. **Environment Variables**: Automatically populated by Chezmoi:
   - OS detection via `.chezmoi.os`
   - DevContainer detection via environment variables
3. **Conditional Application**: Templates use `{{- if }}` blocks to apply platform-specific configs

### File Naming Conventions

Chezmoi uses special prefixes in filenames:

- `dot_` → becomes `.` (e.g., `dot_gitconfig` → `.gitconfig`)
- `private_` → sets file permissions to 600
- `executable_` → makes file executable
- `run_once_` → scripts that run once on first apply
- `.tmpl` suffix → processes file as template

### Configuration Hierarchy

```
1. chezmoi/.chezmoi.toml.tmpl    # User configuration (name, email)
2. chezmoi/dot_zshrc.tmpl        # Main shell entry point
   ├── ~/.config/zsh/oh-my-zsh.zsh  # Oh-My-Zsh configuration
   ├── ~/.config/zsh/core.zsh       # Core tools (fzf, direnv, etc.)
   ├── ~/.config/zsh/aliases.zsh    # Command aliases
   └── ~/.config/zsh/gitpod.zsh     # Gitpod environment management
3. ~/.zshrc.local                # Local overrides (not managed)
```

## Important Patterns

### Adding Platform-Specific Code

```go
{{- if eq .chezmoi.os "darwin" }}
# macOS specific configuration
{{- else if eq .chezmoi.os "linux" }}
# Linux specific configuration
{{- end }}
```

### Defensive Command Checking

```bash
# Check if command exists before creating alias
if command -v bat &> /dev/null; then
    alias cat='bat --style=plain'
fi
```

### Git Aliases with Safety

- Interactive operations use `fzf` with fallback to current state
- Destructive operations require confirmation
- Branch operations include namespace filtering

## DevContainer & CI/CD

### Prebuilt Image

The repository publishes a prebuilt Docker image to GitHub Container Registry:
- **Image**: `ghcr.io/kirkchen/devbox-devcontainer:latest`
- **Build Trigger**: Changes to `.devcontainer/Dockerfile` on main branch or manual workflow dispatch
- **Platforms**: linux/amd64, linux/arm64

### Using Prebuilt Image in Other Projects

1. Copy `.devcontainer/devcontainer.json` to your project
2. Replace the `build` section with:
   ```json
   "image": "ghcr.io/kirkchen/devbox-devcontainer:latest"
   ```
3. Keep only additional features needed:
   ```json
   "features": {
     "ghcr.io/schlich/devcontainer-features/playwright:0": {}
   }
   ```

## Development Workflow

When modifying dotfiles:

1. Edit files in `chezmoi/` directory (not home directory)
2. Test changes with `chezmoi diff --source="./chezmoi"`
3. Apply with `chezmoi apply --source="./chezmoi"`
4. Commit changes to git for version control

When adding new configurations:

1. Create file in home directory
2. Add to chezmoi: `chezmoi add ~/path/to/file --source="./chezmoi"`
3. Convert to template if needed for cross-platform support
4. Document any new dependencies in README.md

## Included Tools

The DevContainer and dotfiles include:

### Shell & Terminal
- **Zsh** with Oh-My-Zsh (bullet-train theme)
- **Tmux** with resurrect and continuum plugins
- **Vim** with NERDTree, fzf.vim, CoC

### CLI Tools
- **fzf**: Fuzzy finder (uses ag → rg → find fallback chain)
- **eza**: Modern ls replacement
- **bat**: Syntax-highlighted cat
- **ag**: The Silver Searcher
- **tig**: Git text-mode interface
- **diff-so-fancy**: Better git diffs
- **direnv**: Environment variable management
- **Claude Code CLI**: Installed automatically with global settings