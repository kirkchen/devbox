#!/bin/bash
# Configure Claude Code settings, CLAUDE.md, and custom skills
# This script:
# 1. Merges base settings (defaultMode, sandbox, permissions) into ~/.claude/settings.json
# 2. Ensures hooks are present (agent indicator, security, notifications, backup, prompt)
# 3. Copies CLAUDE.md from chezmoi source to ~/.claude/CLAUDE.md
# 4. Installs custom commands to ~/.claude/commands/
#
# run_onchange_: re-runs when this script's content changes
# hash: {{ include ".chezmoiscripts/run_onchange_05-configure-claude-settings.sh" | sha256sum }}

set -e

echo "=== Configuring Claude Code ==="

mkdir -p "$HOME/.claude"

SETTINGS_FILE="$HOME/.claude/settings.json"

# ============================================================
# Helper Functions (idempotent hook management)
# ============================================================

# Add a command hook to an event's first group (no matcher)
ensure_hook() {
    local event="$1"
    local hook_cmd="$2"
    local hook_json="$3"

    local has_hook
    has_hook=$(jq --arg cmd "$hook_cmd" \
        "[.hooks.${event}[]?.hooks[]? | select(.command == \$cmd)] | length" \
        "$SETTINGS_FILE" 2>/dev/null || echo "0")

    if [ "$has_hook" = "0" ]; then
        jq --argjson hook "$hook_json" \
            "if .hooks.${event} then .hooks.${event}[0].hooks += [\$hook] else .hooks.${event} = [{\"hooks\": [\$hook]}] end" \
            "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp"
        mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
        echo "✓ Added hook to ${event}"
    else
        echo "✓ Hook already exists in ${event}"
    fi
}

# Add a command hook to an event group with a specific matcher
ensure_hook_with_matcher() {
    local event="$1"
    local matcher="$2"
    local hook_cmd="$3"
    local hook_json="$4"

    local has_hook
    has_hook=$(jq --arg cmd "$hook_cmd" --arg matcher "$matcher" \
        "[.hooks.${event}[]? | select(.matcher == \$matcher) | .hooks[]? | select(.command == \$cmd)] | length" \
        "$SETTINGS_FILE" 2>/dev/null || echo "0")

    if [ "$has_hook" = "0" ]; then
        local has_group
        has_group=$(jq --arg matcher "$matcher" \
            "[.hooks.${event}[]? | select(.matcher == \$matcher)] | length" \
            "$SETTINGS_FILE" 2>/dev/null || echo "0")

        if [ "$has_group" = "0" ]; then
            jq --arg matcher "$matcher" --argjson hook "$hook_json" \
                ".hooks.${event} = (.hooks.${event} // []) + [{\"matcher\": \$matcher, \"hooks\": [\$hook]}]" \
                "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp"
        else
            jq --arg matcher "$matcher" --argjson hook "$hook_json" \
                "(.hooks.${event}[] | select(.matcher == \$matcher)).hooks += [\$hook]" \
                "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp"
        fi
        mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
        echo "✓ Added hook to ${event} (matcher: ${matcher})"
    else
        echo "✓ Hook already exists in ${event} (matcher: ${matcher})"
    fi
}

# Add a prompt-type hook to an event (dedup by type, not command)
ensure_prompt_hook() {
    local event="$1"
    local prompt_text="$2"
    local timeout="${3:-30}"

    local has_hook
    has_hook=$(jq \
        "[.hooks.${event}[]?.hooks[]? | select(.type == \"prompt\")] | length" \
        "$SETTINGS_FILE" 2>/dev/null || echo "0")

    if [ "$has_hook" = "0" ]; then
        local hook_json
        hook_json=$(jq -n --arg prompt "$prompt_text" --argjson timeout "$timeout" \
            '{"type":"prompt","prompt":$prompt,"timeout":$timeout}')
        jq --argjson hook "$hook_json" \
            "if .hooks.${event} then .hooks.${event}[0].hooks += [\$hook] else .hooks.${event} = [{\"hooks\": [\$hook]}] end" \
            "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp"
        mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
        echo "✓ Added prompt hook to ${event}"
    else
        echo "✓ Prompt hook already exists in ${event}"
    fi
}

# ============================================================
# 1. Base Settings (deep merge)
# ============================================================

synced_fields=$(cat <<'SETTINGS_EOF'
{
  "defaultMode": "acceptEdits",
  "sandbox": {
    "enabled": true,
    "permissions": "auto-allow"
  },
  "permissions": {
    "allow": [
      "Glob", "Grep", "LS", "Task",
      "mcp__context7__resolve-library-id",
      "mcp__context7__query-docs",
      "mcp__sequential-thinking__sequentialthinking",
      "WebFetch(domain:github.com)",
      "WebFetch(domain:raw.githubusercontent.com)",
      "WebFetch(domain:registry.npmjs.org)",
      "WebFetch(domain:nodejs.org)",
      "WebFetch(domain:developer.mozilla.org)",

      "Bash(git status)", "Bash(git diff *)", "Bash(git log *)",
      "Bash(git add *)", "Bash(git commit *)", "Bash(git checkout *)",
      "Bash(git switch *)", "Bash(git stash *)", "Bash(git branch *)",
      "Bash(git fetch *)", "Bash(git pull *)", "Bash(git rebase *)",
      "Bash(git cherry-pick *)", "Bash(git worktree *)",
      "Bash(git show *)", "Bash(git blame *)", "Bash(git rev-parse *)",

      "Bash(ls *)", "Bash(cat *)", "Bash(head *)", "Bash(tail *)",
      "Bash(find *)", "Bash(grep *)", "Bash(rg *)", "Bash(fd *)",
      "Bash(wc *)", "Bash(sort *)", "Bash(uniq *)", "Bash(diff *)",
      "Bash(echo *)", "Bash(printf *)", "Bash(jq *)", "Bash(yq *)",
      "Bash(tree *)", "Bash(which *)",
      "Bash(basename *)", "Bash(dirname *)", "Bash(realpath *)",
      "Bash(date *)", "Bash(uname *)", "Bash(whoami)", "Bash(pwd)", "Bash(id)",

      "Bash(mkdir *)", "Bash(touch *)", "Bash(cp *)", "Bash(mv *)",
      "Bash(sed *)", "Bash(awk *)", "Bash(cut *)", "Bash(tr *)",
      "Bash(tee *)", "Bash(xargs *)", "Bash(chmod *)",

      "Bash(python *)", "Bash(python3 *)", "Bash(node *)",

      "Bash(kubectl get *)", "Bash(kubectl describe *)",
      "Bash(kubectl logs *)", "Bash(kubectl config *)",
      "Bash(kubectl top *)", "Bash(kubectl explain *)"
    ],

    "ask": [
      "Bash(git push *)", "Bash(git merge *)", "Bash(git reset *)",
      "Bash(git revert *)", "Bash(git tag *)",

      "Bash(pnpm install *)", "Bash(pnpm add *)", "Bash(pnpm remove *)",
      "Bash(pnpm run *)", "Bash(pnpm start *)", "Bash(pnpm dev *)",
      "Bash(pnpm exec *)",
      "Bash(npm install *)", "Bash(npm run *)",

      "Bash(curl *)", "Bash(wget *)",
      "Bash(docker *)", "Bash(helm *)",
      "Bash(kubectl get secret*)", "Bash(kubectl describe secret*)",
      "Bash(kubectl apply *)", "Bash(kubectl delete *)",
      "Bash(kubectl exec *)", "Bash(kubectl scale *)",
      "Bash(kubectl rollout *)", "Bash(kubectl patch *)",
      "Bash(kubectl edit *)", "Bash(kubectl create *)",

      "Bash(rm *)", "Bash(rmdir *)"
    ],

    "deny": [
      "Read(.env*)",
      "Read(**/secrets/**)",
      "Write(.env*)",


      "Bash(sudo *)", "Bash(sudo)",
      "Bash(git push --force *)", "Bash(git push -f *)",
      "Bash(git push --force-with-lease *)",
      "Bash(git reset --hard *)",
      "Bash(git clean -fd *)",
      "Bash(git commit -a *)", "Bash(git commit --all *)",
      "Bash(git commit --no-verify *)",
      "Bash(git commit -n *)", "Bash(git commit -n)",
      "Bash(git add -A *)", "Bash(git add -A)",
      "Bash(git add .)", "Bash(git add . *)",
      "Bash(git add --all *)", "Bash(git add --all)",
      "Bash(rm -rf /)", "Bash(rm -rf / *)",
      "Bash(rm -rf ~)", "Bash(rm -rf ~ *)",
      "Bash(mkfs *)", "Bash(mkfs.*)",
      "Bash(dd if= *)", "Bash(dd if=*)",
      "Bash(chmod -R 777 *)", "Bash(chmod -R 777)",
      "Bash(pnpm publish *)", "Bash(npm publish *)"
    ]
  }
}
SETTINGS_EOF
)

if command -v jq &>/dev/null; then
    if [ ! -f "$SETTINGS_FILE" ]; then
        echo "$synced_fields" | jq '.' > "$SETTINGS_FILE"
        echo "✓ Created $SETTINGS_FILE"
    else
        existing=$(cat "$SETTINGS_FILE")
        echo "$existing" | jq --argjson sync "$synced_fields" '. * $sync' > "${SETTINGS_FILE}.tmp"
        mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
        echo "✓ Updated $SETTINGS_FILE (merged base settings)"
    fi

    # ============================================================
    # 2. Hooks (idempotent additions)
    # ============================================================

    agent_state_cmd="~/.tmux/plugins/tmux-agent-indicator/scripts/agent-state.sh"
    notify_cmd="~/.config/claude/hooks/notify-macos.sh"
    security_guard_cmd="~/.config/claude/hooks/security-guard.sh"
    protect_files_cmd="~/.config/claude/hooks/protect-files.sh"

    # -- Agent indicator hooks (tmux state tracking) --
    for pair in \
        "UserPromptSubmit:${agent_state_cmd} --agent claude --state running" \
        "Notification:${agent_state_cmd} --agent claude --state needs-input" \
        "Stop:${agent_state_cmd} --agent claude --state done"; do
        event="${pair%%:*}"
        hook_cmd="${pair#*:}"
        hook_json=$(jq -n --arg cmd "$hook_cmd" '{"type":"command","command":$cmd,"async":true}')
        ensure_hook "$event" "$hook_cmd" "$hook_json"
    done

    # -- macOS notifications (Darwin only) --
    if [ "$(uname)" = "Darwin" ]; then
        for event in Notification Stop; do
            hook_json=$(jq -n --arg cmd "$notify_cmd" '{"type":"command","command":$cmd,"async":true}')
            ensure_hook "$event" "$notify_cmd" "$hook_json"
        done
    fi

    # -- Security: PreToolUse hooks --
    sg_json=$(jq -n --arg cmd "$security_guard_cmd" '{"type":"command","command":$cmd}')
    ensure_hook_with_matcher "PreToolUse" "Bash" "$security_guard_cmd" "$sg_json"

    pf_json=$(jq -n --arg cmd "$protect_files_cmd" '{"type":"command","command":$cmd}')
    ensure_hook_with_matcher "PreToolUse" "Write|Edit|MultiEdit" "$protect_files_cmd" "$pf_json"

    # -- PreCompact: transcript backup --
    backup_cmd='mkdir -p .claude/backups && cp "$CLAUDE_TRANSCRIPT_PATH" ".claude/backups/$(date +%Y%m%d-%H%M%S)-transcript.jsonl" 2>/dev/null || true'
    backup_json=$(jq -n --arg cmd "$backup_cmd" '{"type":"command","command":$cmd,"async":true,"timeout":10}')
    ensure_hook "PreCompact" "$backup_cmd" "$backup_json"

else
    echo "⚠ jq not found, skipping settings.json configuration"
fi

# ============================================================
# 3. Copy CLAUDE.md
# ============================================================

SOURCE_DIR="${CHEZMOI_SOURCE_DIR:-$(chezmoi source-path 2>/dev/null || echo "")}"
CLAUDE_MD_SRC="${SOURCE_DIR}/claude-code/CLAUDE.md"

if [ -n "$SOURCE_DIR" ] && [ -f "$CLAUDE_MD_SRC" ]; then
    cp "$CLAUDE_MD_SRC" "$HOME/.claude/CLAUDE.md"
    echo "✓ Copied CLAUDE.md to ~/.claude/"
else
    echo "⚠ CLAUDE.md source not found at $CLAUDE_MD_SRC, skipping"
fi

# ============================================================
# 4. Install rules
# ============================================================

RULES_SRC="${SOURCE_DIR}/claude-code/rules"

if [ -n "$SOURCE_DIR" ] && [ -d "$RULES_SRC" ]; then
    mkdir -p "$HOME/.claude/rules"
    for rule_file in "$RULES_SRC"/*.md; do
        [ -f "$rule_file" ] || continue
        cp "$rule_file" "$HOME/.claude/rules/"
        echo "✓ Installed rule: $(basename "$rule_file")"
    done
else
    echo "⚠ Rules source not found at $RULES_SRC, skipping"
fi

# ============================================================
# 5. Install custom commands
# ============================================================

COMMANDS_SRC="${SOURCE_DIR}/claude-code/commands"

if [ -n "$SOURCE_DIR" ] && [ -d "$COMMANDS_SRC" ]; then
    mkdir -p "$HOME/.claude/commands"
    for cmd_file in "$COMMANDS_SRC"/*.md; do
        [ -f "$cmd_file" ] || continue
        cp "$cmd_file" "$HOME/.claude/commands/"
        echo "✓ Installed command: /$(basename "$cmd_file" .md)"
    done
else
    echo "⚠ Commands source not found at $COMMANDS_SRC, skipping"
fi

echo "=== Claude Code configuration complete ==="
