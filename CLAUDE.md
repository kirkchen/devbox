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
chezmoi init --source="./chezmoi" --apply
```

## Key Commands

### Chezmoi Dotfiles Management

```bash
# Apply dotfiles changes from the chezmoi directory
chezmoi apply --source="./chezmoi"

# Test changes without applying (dry run)
chezmoi diff --source="./chezmoi"

# Re-run initialization (prompts for name/email/github_token)
chezmoi init --source="./chezmoi" --apply

# Add a new dotfile to management
chezmoi add ~/.newconfig --source="./chezmoi"
```

### Gitpod Environment Management (Linux/DevContainer only)

```bash
gpenv start   # Start a stopped environment and optionally SSH into it
gpenv stop    # Stop a running environment
gpenv ssh     # SSH into a running environment
gpenv open    # Open a running environment in browser
gpenv list    # List all environments

# Shortcut aliases: gps, gpt, gpsh, gpo, gpl
```

## Architecture

### Chezmoi Template System

The repository uses Chezmoi's templating system with Go templates for environment-specific configuration:

- **Template Files** (`*.tmpl`): Contain conditional logic for different environments
- **Template Variables**:
  - `.name` and `.email`: User-provided during init
  - `.github_token`: Optional, for Claude Code MCP server
  - `.chezmoi.os`: Operating system ("darwin", "linux")
  - `.is_devcontainer`: Custom variable for DevContainer detection

### File Naming Conventions

Chezmoi uses special prefixes in filenames:

- `dot_` → becomes `.` (e.g., `dot_gitconfig` → `.gitconfig`)
- `private_` → sets file permissions to 600
- `executable_` → makes file executable
- `run_once_` → scripts that run once on first apply
- `.tmpl` suffix → processes file as template

### Configuration Hierarchy

```
chezmoi/.chezmoi.toml.tmpl       # User configuration (name, email, github_token)
chezmoi/dot_zshrc.tmpl           # Main shell entry point
├── ~/.config/zsh/oh-my-zsh.zsh  # Oh-My-Zsh configuration
├── ~/.config/zsh/core.zsh       # Core tools (fzf, direnv)
├── ~/.config/zsh/tools.zsh      # macOS: Homebrew, rbenv, NVM, pnpm
├── ~/.config/zsh/functions.zsh  # Cross-platform: now(), fixup()
├── ~/.config/zsh/functions-macos.zsh  # macOS: code()
├── ~/.config/zsh/aliases.zsh    # Git, K8s, tools aliases
└── ~/.config/zsh/gitpod.zsh     # Linux: Gitpod environment management
~/.zshrc.local                   # Local overrides (not managed)
```

### Platform-Specific Loading

```
macOS (.chezmoi.os == "darwin"):
├── tools.zsh           ✓ (Homebrew, rbenv, NVM, pnpm)
├── functions-macos.zsh ✓ (code function)
├── raycast/scripts/    ✓ (wifi scripts)
└── gitpod.zsh          ✗

Linux/DevContainer:
├── tools.zsh           ✗
├── functions-macos.zsh ✗
├── raycast/scripts/    ✗
└── gitpod.zsh          ✓
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
if command -v bat &>/dev/null; then
    alias cat='bat --style=plain'
fi

# Check if directory exists before sourcing
[[ -d "$HOME/.rbenv" ]] && eval "$(rbenv init -)"
```

### Git Aliases

All git aliases include Traditional Chinese comments:

```bash
alias gbr="git branch"     # 列出分支
alias gcbr="..."           # 顯示目前分支名稱
alias gcoi="..."           # 互動式切換分支
```

## DevContainer & CI/CD

### Prebuilt Image

- **Image**: `ghcr.io/kirkchen/devbox-devcontainer:latest`
- **Build Trigger**: Changes to `.devcontainer/Dockerfile` on main branch
- **Platforms**: linux/amd64, linux/arm64

### Using Prebuilt Image in Other Projects

1. Copy `.devcontainer/devcontainer.json` to your project
2. Replace the `build` section with:
   ```json
   "image": "ghcr.io/kirkchen/devbox-devcontainer:latest"
   ```

## Claude Code Configuration

### Settings (`~/.claude/settings.json`)

- **statusLine**: Shows `🌿 branch | model | directory`
- **enabledPlugins**: code-review, superpowers
- **language**: Traditional Chinese (zh-TW)
- **permissions.deny**: Blocks `.env*`, `secrets/`, `rm -rf /`

### MCP Servers (`~/.claude.json`)

- **sequential-thinking**: For complex reasoning
- **playwright**: Browser automation
- **context7**: Context management
- **github**: GitHub integration (requires `github_token`)

### Installation Scripts

1. `run_once_01-install-oh-my-zsh.sh` - Oh-My-Zsh and plugins
2. `run_once_02-install-cli-tools.sh` - CLI tools via Homebrew/apt (includes zellij, lazygit, delta)
3. `run_once_04-install-claude-plugins.sh` - Claude Code plugins

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

### Shell & Terminal
- **Zsh** with Oh-My-Zsh (bullet-train theme)
- **Zellij**: Terminal multiplexer (keybindings remapped to Alt+t/o/g to avoid Claude Code conflicts)
- **Vim** with NERDTree, fzf.vim, CoC

### CLI Tools
- **fzf**: Fuzzy finder (uses ag → rg → find fallback chain)
- **eza**: Modern ls replacement
- **bat**: Syntax-highlighted cat
- **ag**: The Silver Searcher
- **lazygit**: Git TUI (uses delta as pager)
- **delta**: Modern git diff viewer (side-by-side, line numbers)
- **direnv**: Environment variable management
- **Claude Code CLI**: Installed automatically with global settings

### macOS Specific
- **Homebrew**: Package manager
- **rbenv/NVM/pnpm**: Language version managers (if installed)
- **Raycast scripts**: WiFi management
