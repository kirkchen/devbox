#!/bin/bash
# Claude Code status line: <project>[ 🌲] | ctx ▮▮▯▯▯▯▯▯▯▯ NN% | 🌿 <branch> | <model>
# Input: status JSON on stdin (workspace.current_dir, context_window, model)
# No set -e: the status line must fail open and still print something useful.

input=$(cat)
cwd=$(echo "$input" | jq -r '.workspace.current_dir')

branch=$(git -C "$cwd" symbolic-ref --short HEAD 2>/dev/null || echo 'no-git')

# Project name: main repo name; add 🌲 when inside a linked worktree
common_dir=$(git -C "$cwd" rev-parse --git-common-dir 2>/dev/null)
if [ -n "$common_dir" ]; then
    common_abs=$(cd "$cwd" && realpath "$common_dir" 2>/dev/null)
    main_path=$(dirname "$common_abs")
    main_repo=$(basename "$main_path")
    toplevel=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)
    if [ "$toplevel" = "$main_path" ]; then
        project="$main_repo"
    else
        project="$main_repo 🌲"
    fi
else
    project=$(basename "$cwd")
fi

# Context usage bar (10 cells, rounded to nearest cell)
remaining=$(echo "$input" | jq -r '.context_window.remaining_percentage // empty')
ctx_str=''
if [ -n "$remaining" ]; then
    used=$(awk -v r="$remaining" 'BEGIN{printf "%.0f", 100-r}')
    bar=$(awk -v u="$used" 'BEGIN{f=int((u+5)/10); if(f>10)f=10; for(i=0;i<f;i++)printf "▮"; for(i=f;i<10;i++)printf "▯"}')
    ctx_str=" | ctx ${bar} ${used}%"
fi

# "Fable 5 (1M context)" -> "Fable 5"
model_full=$(echo "$input" | jq -r '.model.display_name')
model="${model_full% (*}"

echo "${project}${ctx_str} | 🌿 ${branch} | ${model}"
