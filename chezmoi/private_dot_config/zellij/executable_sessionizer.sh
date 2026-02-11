#!/bin/bash
# Zellij Sessionizer - fzf-based session/tab switcher
# Triggered by Ctrl+f inside Zellij

CURRENT_SESSION="$ZELLIJ_SESSION_NAME"

if [[ -z "$CURRENT_SESSION" ]]; then
    echo "Error: Not inside a Zellij session." >&2
    read -n1
    exit 1
fi

# --- Collect candidates ---

TAB=$'\t'
candidates=""

# 1) Current session tabs
current_tabs="$(zellij action query-tab-names 2>/dev/null || true)"
if [[ -n "$current_tabs" ]]; then
    while IFS= read -r tab; do
        [[ -z "$tab" ]] && continue
        candidates+="${candidates:+$'\n'}"
        candidates+="* ${CURRENT_SESSION}${TAB}tab${TAB}${tab}"
    done <<< "$current_tabs"
fi

# 2) Other sessions
all_sessions="$(zellij list-sessions -ns 2>/dev/null || true)"
if [[ -n "$all_sessions" ]]; then
    while IFS= read -r session; do
        [[ -z "$session" ]] && continue
        [[ "$session" == "$CURRENT_SESSION" ]] && continue
        candidates+="${candidates:+$'\n'}"
        candidates+="+ ${session}${TAB}session${TAB}${session}"
    done <<< "$all_sessions"
fi

if [[ -z "$candidates" ]]; then
    echo "No other sessions or tabs found."
    read -n1
    exit 0
fi

# --- fzf selection ---
# Format: "ICON NAME\tTYPE\tTARGET"
# fzf shows only first field (display name)

selected="$(echo "$candidates" | fzf --prompt="switch> " --no-sort --delimiter="${TAB}" --with-nth=1)" || exit 0

# --- Parse selection and act ---

type="$(echo "$selected" | cut -d"${TAB}" -f2)"
target="$(echo "$selected" | cut -d"${TAB}" -f3)"

case "$type" in
    tab)
        zellij action go-to-tab-name "$target"
        ;;
    session)
        echo "$target" > "/tmp/zcc-switch-session-${CURRENT_SESSION}"
        zellij action detach
        ;;
esac
