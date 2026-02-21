#!/bin/bash
# macOS notification for Claude Code hooks
# Reads hook JSON from stdin and sends a rich notification
# Supports: Notification (needs-input) and Stop (done) events

INPUT=$(cat)
EVENT=$(echo "$INPUT" | jq -r '.hook_event_name // ""')
CWD=$(echo "$INPUT" | jq -r '.cwd // ""')
PROJECT=$(basename "$CWD")

case "$EVENT" in
    Notification)
        TITLE="Claude Code - ${PROJECT}"
        MSG=$(echo "$INPUT" | jq -r '.message // "Needs input"')
        ;;
    Stop)
        TITLE="Claude Code - ${PROJECT}"
        # Take first 100 chars of last assistant message as summary
        MSG=$(echo "$INPUT" | jq -r '.last_assistant_message // "Task completed"' | head -c 100)
        ;;
    *)
        TITLE="Claude Code"
        MSG="Event: ${EVENT}"
        ;;
esac

terminal-notifier -title "$TITLE" -message "$MSG" -sound default
