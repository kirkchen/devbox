# Universal DevContainer with Chezmoi Dotfiles

This repository contains a universal development container setup with cross-platform dotfiles management using Chezmoi.

## Features

- 🐳 **DevContainer**: Pre-configured development environment with VS Code integration
- 🔧 **Chezmoi**: Cross-platform dotfiles management with templating support
- 🚀 **Oh-My-Zsh**: Pre-configured with bullet-train theme and useful plugins
- 🛠️ **Modern CLI Tools**: fzf, eza, bat, ag, tig, and more
- 🖥️ **Multi-Environment Support**: Works on macOS, Linux, and DevContainers
- ⚙️ **Interactive Configuration**: Per-computer settings (email, work/personal)

## Quick Start

### Using DevContainer (Recommended)

1. Open this folder in VS Code
2. Install the "Dev Containers" extension if not already installed
3. Press `Cmd/Ctrl + Shift + P` and select "Dev Containers: Reopen in Container"
4. The container will build and automatically set up your dotfiles

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
   - Computer type (personal/work/devcontainer)

## Directory Structure

```
devbox/
├── .devcontainer/           # DevContainer configuration
│   ├── devcontainer.json    # Container settings
│   ├── Dockerfile           # Container image definition
│   └── scripts/
│       └── setup-dotfiles.sh # Dotfiles setup script
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
- **Tmux**: Terminal multiplexer with plugins (resurrect, continuum, etc.)
- **Themes**: Bullet-train and Powerlevel10k

### CLI Tools
- **fzf**: Fuzzy finder for files and commands
- **eza**: Modern replacement for ls
- **bat**: Cat with syntax highlighting
- **ag**: The Silver Searcher for fast code search
- **tig**: Text-mode interface for Git
- **diff-so-fancy**: Better git diffs
- **htop**: Interactive process viewer
- **direnv**: Environment variable management

### Development
- **Git**: Version control with custom aliases
- **Vim**: Text editor with plugins (NERDTree, fzf.vim, CoC, etc.)
- **VS Code**: Integrated with DevContainer

## Configuration

### Interactive Setup

When you first run `chezmoi init`, you'll be prompted for:
- **Name**: Used in Git commits
- **Email**: Used in Git configuration
- **Computer Type**: Determines which features to enable
  - `personal`: Full features for personal development
  - `work`: Work-appropriate configuration
  - `devcontainer`: Optimized for container environments

### Custom Aliases

Common Git aliases included:
- `gs` - git status
- `gd` - git diff with fancy output
- `gcoi` - interactive checkout
- `gmi` - interactive merge
- `gpsu` - push with upstream tracking

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

## License

MIT

## Contributing

Feel free to submit issues and pull requests to improve this setup!