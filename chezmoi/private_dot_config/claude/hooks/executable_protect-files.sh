#!/bin/bash
# PreToolUse hook: Protect sensitive files from being written
# Input: JSON from stdin with tool_input.file_path or tool_input.path
# Output: exit 2 to block the operation if file matches protected pattern

set -euo pipefail

INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')

[[ -z "$FILE" ]] && exit 0

PROTECTED=(
  ".env"
  ".env.local"
  ".env.production"
  ".env.staging"
  "secrets/"
  ".git/"
  "id_rsa"
  "id_ed25519"
  ".aws/credentials"
  ".kube/config"
  "package-lock.json"
  "pnpm-lock.yaml"
)

for pattern in "${PROTECTED[@]}"; do
  if [[ "$FILE" == *"$pattern"* ]]; then
    echo "Protected file: cannot modify '$FILE' (matches '$pattern')" >&2
    exit 2
  fi
done

exit 0
