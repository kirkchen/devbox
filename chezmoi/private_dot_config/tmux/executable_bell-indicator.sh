#!/bin/bash
# Scan all sessions for windows with bell flag, output indicator for status line
current_session=$(tmux display-message -p '#S')
alerts=""

while IFS= read -r session; do
    if [ "$session" != "$current_session" ]; then
        # Deduplicate: only add if not already in alerts
        case "$alerts" in
            *" $session "*|*" $session") ;;
            *) alerts="${alerts} ${session}" ;;
        esac
    fi
done < <(tmux list-windows -a -F '#{session_name} #{window_bell_flag}' 2>/dev/null | grep ' 1$' | cut -d' ' -f1)

if [ -n "$alerts" ]; then
    echo "🔔${alerts} "
fi
