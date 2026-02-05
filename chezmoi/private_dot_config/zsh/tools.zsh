# === macOS Language Version Managers ===
# This file is only loaded on macOS (see .zshrc)
# Each tool only loads if installed

# === Homebrew ===
if [[ -f "/opt/homebrew/bin/brew" ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [[ -f "/usr/local/bin/brew" ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi

# === Ruby (rbenv) ===
if [[ -d "$HOME/.rbenv" ]]; then
    export PATH="$HOME/.rbenv/bin:$PATH"
    eval "$(rbenv init -)"
fi

# === Node.js (NVM) ===
export NVM_DIR="$HOME/.nvm"
[[ -f "/opt/homebrew/opt/nvm/nvm.sh" ]] && source "/opt/homebrew/opt/nvm/nvm.sh"
[[ -f "/usr/local/opt/nvm/nvm.sh" ]] && source "/usr/local/opt/nvm/nvm.sh"

# === pnpm ===
export PNPM_HOME="$HOME/Library/pnpm"
[[ -d "$PNPM_HOME" ]] && export PATH="$PNPM_HOME:$PATH"

# === JetBrains Toolbox ===
[[ -d "$HOME/.jetbrains" ]] && export PATH="$HOME/.jetbrains:$PATH"

# === .NET ===
[[ -d "$HOME/.dotnet" ]] && export PATH="$HOME/.dotnet:$PATH"
