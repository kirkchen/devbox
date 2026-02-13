# === Git Aliases ===
alias gbr="git branch"                                                            # 列出分支
alias gcbr="git rev-parse --abbrev-ref HEAD"                                      # 顯示目前分支名稱
alias gpsu="git push --set-upstream origin \$(git rev-parse --abbrev-ref HEAD)"   # 推送並設定 upstream
alias gcoi="git checkout \$(git branch | cut -c 3- | fzf --height 40% --reverse || echo .)"  # 互動式切換分支
alias gmi="git merge \$(git branch | cut -c 3- | fzf --height 40% --reverse || echo .)"      # 互動式合併分支
alias gdt="git difftool"                                                          # 開啟 diff 工具
alias ,,="cd \$(git rev-parse --show-toplevel 2>/dev/null || echo .)"             # 跳到 git repo 根目錄

# gmdb: 刪除指定 namespace 的所有分支 (e.g., gmdb feature)
alias gmdb="f() { \
  if [ -z \$1 ]; then \
    echo 'Please assign branch namespace.'; \
  else \
    local branches=\$(git branch | awk -F. '/'\"\$1\"'/{print}'); \
    if [ -z \"\$branches\" ]; then \
      echo 'No branches found with namespace: '\$1; \
    else \
      echo \"Will delete:\n\$branches\"; \
      echo -n 'Continue? [y/N] '; \
      read confirm; \
      [ \"\$confirm\" = 'y' ] || [ \"\$confirm\" = 'Y' ] && echo \"\$branches\" | xargs -I {} git branch -D {}; \
    fi; \
  fi; \
}; f"

# === Tools ===
alias mux="tmuxinator"
alias t="tig"
alias ts="tig status"
alias ta="tig --all"
alias e="\$EDITOR"

# === Terminal Multiplexer & Git TUI ===
if command -v lazygit &>/dev/null; then
    alias lg='lazygit'
fi

# === Modern CLI (loads if installed) ===
if command -v bat &>/dev/null; then
    alias cat='bat --style=plain'
    alias catn='bat --style=numbers'
fi

if command -v eza &>/dev/null; then
    alias ls='eza --icons --group-directories-first'
    alias ll='eza -lbaF --git --icons --group-directories-first'
    alias lt='eza --tree --level=2 --icons'
    alias la='eza -la --icons --group-directories-first'
    alias l='eza -l --icons --group-directories-first'
fi

# === Kubernetes (loads if installed) ===
if command -v kubectl &>/dev/null; then
    alias kctxi="kubectl config use-context \$(kubectl config get-contexts -o name | fzf --height 40% --reverse)"  # 互動式切換 context
    alias knsi="kubectl config set-context --current --namespace=\$(kubectl get ns -o name | cut -d/ -f2 | fzf --height 40% --reverse)"  # 互動式切換 namespace
fi
