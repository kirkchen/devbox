#!/bin/bash
# Select a project directory with fzf and create/switch to a tmux session
selected=$(~/.config/tmux/list-projects.sh | fzf --tmux 75%,75% --prompt " " --preview "ls {}")

if [[ -z "$selected" ]]; then
    exit 0
fi

session_name=$(basename "$selected" | tr '.' '_')

if ! tmux has-session -t="$session_name" 2>/dev/null; then
    tmux new-session -d -s "$session_name" -c "$selected"
fi

tmux switch-client -t "$session_name"
