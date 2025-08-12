#!/bin/bash
set -e

echo "🚀 Installing Oh-My-Zsh..."

# Install Oh-My-Zsh if not already installed
if [ ! -d "$HOME/.oh-my-zsh" ]; then
    echo "Installing Oh-My-Zsh..."
    sh -c "$(curl -fsSL https://raw.github.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended --keep-zshrc
else
    echo "Oh-My-Zsh is already installed"
fi

# Set up custom plugins directory
ZSH_CUSTOM=${ZSH_CUSTOM:-~/.oh-my-zsh/custom}

echo "📦 Installing Zsh plugins..."

# Install zsh-autosuggestions
if [ ! -d "$ZSH_CUSTOM/plugins/zsh-autosuggestions" ]; then
    echo "Installing zsh-autosuggestions..."
    git clone https://github.com/zsh-users/zsh-autosuggestions $ZSH_CUSTOM/plugins/zsh-autosuggestions
else
    echo "zsh-autosuggestions already installed"
fi

# Install alias-tips
if [ ! -d "$ZSH_CUSTOM/plugins/alias-tips" ]; then
    echo "Installing alias-tips..."
    git clone https://github.com/djui/alias-tips.git $ZSH_CUSTOM/plugins/alias-tips
else
    echo "alias-tips already installed"
fi

# Install zsh-syntax-highlighting (optional but useful)
if [ ! -d "$ZSH_CUSTOM/plugins/zsh-syntax-highlighting" ]; then
    echo "Installing zsh-syntax-highlighting..."
    git clone https://github.com/zsh-users/zsh-syntax-highlighting $ZSH_CUSTOM/plugins/zsh-syntax-highlighting
else
    echo "zsh-syntax-highlighting already installed"
fi

echo "🎨 Installing themes..."

# Install bullet-train theme
if [ ! -d "$ZSH_CUSTOM/themes/bullet-train" ]; then
    echo "Installing bullet-train theme..."
    git clone https://github.com/caiogondim/bullet-train.zsh $ZSH_CUSTOM/themes/bullet-train
else
    echo "bullet-train theme already installed"
fi

# Install Powerlevel10k theme (as an alternative)
if [ ! -d "$ZSH_CUSTOM/themes/powerlevel10k" ]; then
    echo "Installing Powerlevel10k theme..."
    git clone --depth=1 https://github.com/romkatv/powerlevel10k.git $ZSH_CUSTOM/themes/powerlevel10k
else
    echo "Powerlevel10k theme already installed"
fi

echo "✅ Oh-My-Zsh setup complete!"