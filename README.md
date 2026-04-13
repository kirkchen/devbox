# Universal DevContainer with Chezmoi Dotfiles

A minimal, robust development container setup with intelligent cross-platform dotfiles management using Chezmoi.

## Features

- 🐳 **DevContainer**: Pre-configured Ubuntu 22.04 environment with VS Code integration
- 📦 **Prebuilt Image**: Published to GitHub Container Registry for fast startup in other projects
- 🔧 **Chezmoi**: Smart dotfiles management with automatic environment detection
- 🚀 **Oh-My-Zsh**: Bullet-train theme with essential plugins
- 🛠️ **Modern CLI Tools**: fzf, eza, bat, ag, lazygit, delta, and more
- 🖥️ **Multi-Environment Support**: Automatic detection for macOS, Linux, and DevContainers
- ⚙️ **Minimal Configuration**: Only asks for name and email
- 🛡️ **Defensive Programming**: Robust error handling and fallback mechanisms
- 🤖 **Claude Code Integration**: Pre-configured settings, plugins, and MCP servers

## Quick Start

### Option 1: Use Prebuilt Image in Your Projects (Fastest)

For the fastest setup in your other projects, use the prebuilt image from GitHub Container Registry:

1. Copy the `.devcontainer/devcontainer.json` from this repo to your project
2. Replace the `build` section with:
   ```json
   "image": "ghcr.io/kirkchen/devbox-devcontainer:latest"
   ```
3. Keep only the features you need (most are already in the image):
   ```json
   "features": {
     "ghcr.io/schlich/devcontainer-features/playwright:0": {}
   }
   ```
4. Open in VS Code with Dev Containers extension

**Startup time: ~30 seconds** instead of 5-10 minutes!

### Option 2: Using This DevContainer (Development)

1. Open this folder in VS Code
2. Install the "Dev Containers" extension if not already installed
3. Press `Cmd/Ctrl + Shift + P` and select "Dev Containers: Reopen in Container"
4. After the container builds, run `setup-dotfiles` to configure your environment
5. Follow the prompts to enter your name and email

### Option 3: Local Setup (macOS/Linux)

1. Install Chezmoi:

   ```bash
   # macOS
   brew install chezmoi

   # Linux
   sh -c "$(curl -fsLS get.chezmoi.io)"
   ```

2. Initialize from this repository:

   ```bash
   # From the devbox directory
   chezmoi init --source="./chezmoi" --apply
   ```

3. Follow the interactive prompts to configure:
   - Your name
   - Your email
   - GitHub token (optional, for MCP server)

## Directory Structure

```
devbox/
├── .devcontainer/           # DevContainer configuration
│   ├── devcontainer.json    # Container settings
│   ├── Dockerfile           # Multi-arch container image
│   └── scripts/
│       ├── setup-dotfiles.sh # Interactive dotfiles setup
│       └── welcome.sh       # Welcome message
├── .github/
│   └── workflows/
│       └── build-devcontainer.yml # Automated image building
├── chezmoi/                 # Chezmoi-managed dotfiles
│   ├── .chezmoi.toml.tmpl   # Interactive configuration template
│   ├── .chezmoiignore       # Files to ignore
│   ├── .chezmoiscripts/     # One-time setup scripts
│   │   ├── run_once_01-install-oh-my-zsh.sh
│   │   ├── run_once_02-install-cli-tools.sh.tmpl
│   │   └── run_once_04-install-claude-plugins.sh
│   ├── dot_gitconfig.tmpl   # Git configuration
│   ├── dot_zshrc.tmpl       # Zsh configuration
│   ├── dot_claude.json.tmpl # Claude Code MCP servers
│   ├── dot_vimrc            # Vim configuration
│   ├── claude-code/         # Claude Code global config
│   │   ├── CLAUDE.md        # Development guidelines
│   │   ├── commands/        # Custom slash commands
│   │   └── rules/           # Modular rules (security, etc.)
│   ├── dot_local/bin/       # Scripts deployed to ~/.local/bin
│   │   └── claude-friction  # Transcript friction analyzer
│   └── private_dot_config/
│       ├── lazygit/
│       │   └── config.yml   # Lazygit config (delta pager)
│       ├── zsh/             # Modular Zsh configs
│       │   ├── oh-my-zsh.zsh
│       │   ├── core.zsh.tmpl
│       │   ├── tools.zsh      # macOS: Homebrew, rbenv, NVM, pnpm
│       │   ├── functions.zsh  # Cross-platform: now(), fixup()
│       │   ├── functions-macos.zsh # macOS: code()
│       │   ├── aliases.zsh    # Git, K8s, tools aliases
│       │   └── gitpod.zsh     # Gitpod environment management
│       └── raycast/
│           └── scripts/       # macOS Raycast scripts
└── install.sh               # Automated installation script
```

## Included Tools

### Shell & Terminal

- **Zsh**: Modern shell with Oh-My-Zsh framework
- **Theme**: Bullet-train theme with proper font support

### CLI Tools

- **fzf**: Fuzzy finder with intelligent fallback (ag → rg → find)
- **eza**: Modern replacement for ls (successor to exa)
- **bat**: Cat with syntax highlighting (multi-architecture support)
- **ag**: The Silver Searcher for fast code search
- **lazygit**: Git TUI (uses delta as pager)
- **delta**: Modern git diff viewer (side-by-side, line numbers)
- **htop**: Interactive process viewer
- **direnv**: Environment variable management

### Development

- **Git**: Version control with defensive aliases
- **Vim**: Text editor with essential plugins (NERDTree, fzf.vim, CoC)
- **VS Code**: Integrated with DevContainer
- **Claude Code**: Pre-configured with plugins and MCP servers

### macOS Specific

- **Homebrew**: Package manager integration
- **rbenv**: Ruby version management (if installed)
- **NVM**: Node.js version management (if installed)
- **pnpm**: Fast package manager (if installed)
- **Raycast**: WiFi management scripts

## Configuration

### Interactive Setup

When you first run `chezmoi init` or `setup-dotfiles`, you'll be prompted for:

- **Name**: Used in Git commits and configurations
- **Email**: Used in Git configuration
- **GitHub Token**: Optional, for Claude Code MCP server

The system automatically detects your environment (macOS, Linux, or DevContainer) and configures accordingly.

### Shell Aliases

#### Git Aliases (with comments)

| Alias | Command | Description |
|-------|---------|-------------|
| `gbr` | `git branch` | 列出分支 |
| `gcbr` | `git rev-parse --abbrev-ref HEAD` | 顯示目前分支名稱 |
| `gpsu` | `git push --set-upstream origin $(gcbr)` | 推送並設定 upstream |
| `gcoi` | Interactive checkout with fzf | 互動式切換分支 |
| `gmi` | Interactive merge with fzf | 互動式合併分支 |
| `gmdb` | Delete branches by namespace | 刪除指定 namespace 的分支 |
| `gdt` | `git difftool` | 開啟 diff 工具 |
| `,,` | `cd $(git rev-parse --show-toplevel)` | 跳到 git repo 根目錄 |

#### Kubernetes Aliases

| Alias | Description |
|-------|-------------|
| `kctxi` | 互動式切換 Kubernetes context |
| `knsi` | 互動式切換 Kubernetes namespace |

#### Tool Aliases

| Alias | Description |
|-------|-------------|
| `lg` | lazygit |
| `cat` | bat (if installed) |
| `ls/ll/lt` | eza with icons (if installed) |

### Shell Functions

| Function | Description |
|----------|-------------|
| `now` | 輸出 UTC 時間戳記 (YYYYMMDDHHmmss) |
| `fixup <msg>` | 建立 fixup commit 並自動 rebase |
| `code [path]` | 用 VS Code 開啟檔案或目錄 (macOS) |

### Gitpod Environment Management (Linux/DevContainer)

```bash
gpenv start   # Start a stopped environment and optionally SSH into it
gpenv stop    # Stop a running environment
gpenv ssh     # SSH into a running environment
gpenv open    # Open a running environment in browser
gpenv list    # List all environments

# Shortcut aliases
gps / gpt / gpsh / gpo / gpl
```

### Claude Code Configuration

Pre-configured with:

- **Plugins**: code-simplifier, superpowers, skill-creator
- **Language**: Traditional Chinese (zh-TW)
- **Sandbox**: enabled with auto-allow, filesystem/network allowlists for pnpm/uv/OrbStack
- **Hooks**: `security-guard` (blocks dangerous bash), `protect-files` (guards sensitive writes), PreCompact transcript backup
- **Helpers**: `claude-friction <project>` — analyze transcripts for sandbox/permission friction
- **MCP Servers**: sequential-thinking, context7, github (if token provided)

## Prebuilt Image

This repository automatically publishes a prebuilt Docker image to GitHub Container Registry, perfect for use in other projects.

### Available Image

- `ghcr.io/kirkchen/devbox-devcontainer:latest`

### Automatic Updates

GitHub Actions automatically builds and publishes new images when:

- `.devcontainer/Dockerfile` is modified (pushed to main branch)
- Manually triggered via GitHub Actions

## Updating Dotfiles

### Modify Templates

1. Edit files in the `chezmoi/` directory
2. Apply changes: `chezmoi apply --source="./chezmoi"`

### Add New Files

1. Add to chezmoi: `chezmoi add ~/.config/newfile --source="./chezmoi"`
2. Commit changes to repository

### Sync Across Machines

```bash
# Pull latest changes
cd ~/Code/devbox
git pull

# Apply to current machine
chezmoi apply --source="./chezmoi"
```

## Key Features

### Defensive Programming

- **Command existence checks**: Aliases only created if commands exist
- **Intelligent fallbacks**: FZF uses ag → rg → find chain
- **Confirmation prompts**: Destructive operations require confirmation
- **Error handling**: Proper error suppression and handling
- **Platform detection**: Automatic environment adaptation

### Environment Detection

The configuration automatically detects and adapts to:

- **macOS**: Homebrew paths, version managers, Raycast scripts
- **Linux**: APT/DNF package managers, Linux paths
- **DevContainer**: Container-optimized settings, Gitpod management

## Troubleshooting

### Font Issues

If Powerline symbols don't align:

1. Install a Nerd Font (see Fonts section)
2. Set terminal font to the Mono variant
3. Restart terminal

### Permission Issues

```bash
# Fix script permissions
chmod +x .devcontainer/scripts/*.sh
chmod +x chezmoi/.chezmoiscripts/*.sh
```

### Chezmoi Not Found

```bash
# Install manually
curl -fsLS get.chezmoi.io | sh
export PATH="$HOME/.local/bin:$PATH"
```

### Tool Not Available

The configuration includes fallbacks for missing tools:

- If `bat` is not available, `cat` works normally
- If `eza` is not available, `ls` is used
- If `ag` is not available, `rg` or `find` is used for FZF

## Fonts

For the best terminal experience, install a Nerd Font:

- [SauceCodePro Nerd Font](https://github.com/ryanoasis/nerd-fonts/tree/master/patched-fonts/SourceCodePro)
- [MesloLGS NF](https://github.com/romkatv/powerlevel10k#meslo-nerd-font-patched-for-powerlevel10k)

## License

MIT

## Contributing

Feel free to submit issues and pull requests to improve this setup!
