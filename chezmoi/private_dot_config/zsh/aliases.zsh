# Git Aliases (from your original config)
alias gbr="git branch"
alias gcbr="git rev-parse --abbrev-ref HEAD"
alias gpsu="git push --set-upstream origin \$(git rev-parse --abbrev-ref HEAD)"
alias gcoi="git checkout \$(git branch | cut -c 3- | fzf || echo .)"
alias gmi="git merge \$(git branch | cut -c 3- | fzf || echo .)"
alias gmdb="f() { if [ -z \$1 ]; then echo 'Please assign branch namespace.'; else git branch | awk -F. '/'"\$1"'/{print}' | xargs -I {} git branch -D {}; fi }; f"
alias gdt="git difftool"
alias ,,="cd \$(git rev-parse --show-toplevel 2>/dev/null || echo .)"

# Tools
alias mux="tmuxinator"
alias t="tig"
alias ts="tig status"
alias ta="tig --all"

# Modern CLI tools
alias cat='bat --style=plain'
alias catn='bat --style=numbers'

# eza (modern ls replacement)
if command -v eza &> /dev/null; then
    alias ls='eza --icons --group-directories-first'
    alias ll='eza -lbaF --git --icons --group-directories-first'
    alias lt='eza --tree --level=2 --icons'
    alias la='eza -la --icons --group-directories-first'
    alias l='eza -l --icons --group-directories-first'
fi

# Editor
alias e="$EDITOR"

# Quick navigation
alias ..='cd ..'
alias ...='cd ../..'
alias ....='cd ../../..'
alias ~='cd ~'
alias -- -='cd -'

# Utility aliases
alias mkdir='mkdir -pv'
alias grep='grep --color=auto'
alias df='df -h'
alias du='du -h'
alias free='free -h'
alias top='htop'

# Safety nets
alias rm='rm -i'
alias cp='cp -i'
alias mv='mv -i'

# Reload shell configuration
alias reload='source ~/.zshrc'
alias zshconfig="$EDITOR ~/.zshrc"