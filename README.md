# Universal DevContainer with Chezmoi Dotfiles

A minimal, robust development container setup with intelligent cross-platform dotfiles management using Chezmoi.

## Features

- 🐳 **DevContainer**: Pre-configured Ubuntu 22.04 environment with VS Code integration
- 🔧 **Chezmoi**: Smart dotfiles management with automatic environment detection
- 🚀 **Oh-My-Zsh**: Bullet-train theme with essential plugins
- 🛠️ **Modern CLI Tools**: fzf, eza, bat, ag, tig, and more
- 🖥️ **Multi-Environment Support**: Automatic detection for macOS, Linux, and DevContainers
- ⚙️ **Minimal Configuration**: Only asks for name and email
- 🛡️ **Defensive Programming**: Robust error handling and fallback mechanisms

## Quick Start

### Using DevContainer (Recommended)

1. Open this folder in VS Code
2. Install the "Dev Containers" extension if not already installed
3. Press `Cmd/Ctrl + Shift + P` and select "Dev Containers: Reopen in Container"
4. After the container builds, run `setup-dotfiles` to configure your environment
5. Follow the prompts to enter your name and email

### Local Setup (macOS/Linux)

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

## Directory Structure

```
devbox/
├── .devcontainer/           # DevContainer configuration
│   ├── devcontainer.json    # Container settings
│   ├── Dockerfile           # Multi-arch container image
│   └── scripts/
│       ├── setup-dotfiles.sh # Interactive dotfiles setup
│       └── welcome.sh       # Welcome message
├── chezmoi/                 # Chezmoi-managed dotfiles
│   ├── .chezmoi.toml.tmpl   # Interactive configuration template
│   ├── .chezmoiignore       # Files to ignore
│   ├── .chezmoiscripts/     # One-time setup scripts
│   │   ├── run_once_01-install-oh-my-zsh.sh
│   │   └── run_once_02-install-cli-tools.sh.tmpl
│   ├── dot_gitconfig.tmpl   # Git configuration
│   ├── dot_zshrc.tmpl       # Zsh configuration
│   ├── dot_tmux.conf        # Tmux configuration
│   ├── dot_vimrc            # Vim configuration
│   ├── dot_tigrc            # Tig configuration
│   └── private_dot_config/
│       └── zsh/             # Modular Zsh configs
│           ├── aliases.zsh
│           ├── core.zsh.tmpl
│           └── oh-my-zsh.zsh
└── setup_zsh.sh             # Legacy setup script (fallback)
```

## Included Tools

### Shell & Terminal
- **Zsh**: Modern shell with Oh-My-Zsh framework
- **Tmux**: Terminal multiplexer with resurrect and continuum plugins
- **Theme**: Bullet-train theme with proper font support

### CLI Tools
- **fzf**: Fuzzy finder with intelligent fallback (ag → rg → find)
- **eza**: Modern replacement for ls (successor to exa)
- **bat**: Cat with syntax highlighting (multi-architecture support)
- **ag**: The Silver Searcher for fast code search
- **tig**: Text-mode interface for Git
- **diff-so-fancy**: Better git diffs
- **htop**: Interactive process viewer
- **direnv**: Environment variable management

### Development
- **Git**: Version control with defensive aliases
- **Vim**: Text editor with essential plugins (NERDTree, fzf.vim, CoC)
- **VS Code**: Integrated with DevContainer

## Configuration

### Interactive Setup

When you first run `chezmoi init` or `setup-dotfiles`, you'll be prompted for:
- **Name**: Used in Git commits and configurations
- **Email**: Used in Git configuration

The system automatically detects your environment (macOS, Linux, or DevContainer) and configures accordingly.

### Custom Aliases

Common Git aliases with defensive programming:
- `gs` - git status
- `gd` - git diff with fancy output (fallback to standard diff)
- `gcoi` - interactive checkout with fzf
- `gmi` - interactive merge with fzf
- `gpsu` - push with upstream tracking
- `gmdb` - delete branches with confirmation prompt
- `cat` - uses bat with color when available

### Vim Configuration

Pre-configured with:
- Sonokai color scheme
- File explorer (NERDTree)
- Fuzzy search (fzf.vim)
- Language support (CoC)
- Git integration (fugitive)

## Fonts

For the best terminal experience, install a Nerd Font:
- [SauceCodePro Nerd Font](https://github.com/ryanoasis/nerd-fonts/tree/master/patched-fonts/SourceCodePro)
- [MesloLGS NF](https://github.com/romkatv/powerlevel10k#meslo-nerd-font-patched-for-powerlevel10k)

## Updating Dotfiles

### Modify Templates
1. Edit files in the `chezmoi/` directory
2. Apply changes: `chezmoi apply`

### Add New Files
1. Add to chezmoi: `chezmoi add ~/.config/newfile`
2. Commit changes to repository

### Sync Across Machines
```bash
# Pull latest changes
cd ~/Code/Temp/devbox
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
- **macOS**: Homebrew paths, macOS-specific tools
- **Linux**: APT/DNF package managers, Linux paths
- **DevContainer**: Container-optimized settings

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

## License

MIT

## Contributing

Feel free to submit issues and pull requests to improve this setup!