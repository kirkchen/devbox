#!/bin/bash
# PreToolUse hook: Block dangerous Bash commands via pattern matching
# Input: JSON from stdin with tool_input.command
# Output: JSON with permissionDecision:"deny" if dangerous pattern detected

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

[[ -z "$COMMAND" ]] && exit 0

PATTERNS=(
  'rm\s+-rf\s+/($|\s|\*|(usr|etc|bin|sbin|var|root|System|Library|Applications|opt|boot|dev|proc|sys|lib|lib64)([ /]|$))'
  'rm\s+-rf\s+~($|[ /])'
  'rm\s+-rf\s+\$HOME'
  'mkfs\.'
  'dd\s+if='
  'chmod\s+-R\s+777\s+/'
  'curl.*\|\s*(ba)?sh'
  'wget.*\|\s*(ba)?sh'
  '>\s*/dev/sd[a-z]'
  'DROP\s+TABLE'
  'DROP\s+DATABASE'
  'TRUNCATE\s+TABLE'
)

for p in "${PATTERNS[@]}"; do
  if echo "$COMMAND" | grep -qiE "$p"; then
    jq -n --arg reason "Blocked: dangerous pattern '$p' detected in: $COMMAND" \
      '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$reason}}'
    exit 0
  fi
done

exit 0
