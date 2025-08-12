#!/bin/bash

# This script is executed when the container starts to show a welcome message

cat << 'EOF'

╔══════════════════════════════════════════════════════════════╗
║          🎉 Welcome to your DevContainer!                     ║
╚══════════════════════════════════════════════════════════════╝

To set up your personal dotfiles configuration, run:

  setup-dotfiles

This will:
  • Install Oh-My-Zsh with bullet-train theme
  • Configure Git with your personal settings
  • Set up modern CLI tools (fzf, eza, bat, etc.)
  • Apply your custom aliases and configurations

EOF