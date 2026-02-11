#!/bin/bash
# Plan Viewer - 快速瀏覽 docs/plans/*.md 檔案
# 觸發方式：Zellij Ctrl+p

# 尋找 git repo 根目錄
repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"
if [[ -z "$repo_root" ]]; then
    echo "Not inside a git repository."
    read -n1
    exit 1
fi

plans_dir="${repo_root}/docs/plans"
if [[ ! -d "$plans_dir" ]]; then
    echo "No docs/plans/ directory found."
    read -n1
    exit 1
fi

# 收集 .md 檔案（按修改時間排序，最新在前）
files=()
while IFS= read -r f; do
    [[ -n "$f" ]] && files+=("$f")
done < <(ls -t "$plans_dir"/*.md 2>/dev/null)

if [[ ${#files[@]} -eq 0 ]]; then
    echo "No plan files found in docs/plans/."
    read -n1
    exit 0
fi

if [[ ${#files[@]} -eq 1 ]]; then
    selected="${files[0]}"
else
    # 用 fzf 選擇，顯示檔名
    selected="$(printf '%s\n' "${files[@]}" | xargs -I{} basename {} | fzf --prompt="plan> " --no-sort)" || exit 0
    selected="${plans_dir}/${selected}"
fi

bat --style=plain --paging=always --theme=ansi "$selected"
