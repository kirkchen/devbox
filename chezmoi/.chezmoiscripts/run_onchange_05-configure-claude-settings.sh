#!/bin/bash
# Configure Claude Code settings, CLAUDE.md, and custom skills
# This script:
# 1. Merges base settings (permissions, status line, output style) into ~/.claude/settings.json,
#    disables sandbox (auto mode classifier handles day-to-day approvals; deny rules
#    + hooks are the hard lines)
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

# outputStyle: built-in Concise style (v2.1.237+) — leads with the result,
#              skips preamble, keeps responses short; work depth unchanged
# Auto mode: the classifier auto-approves safe commands, so no big allow list.
# allow  = things the classifier can't pre-approve (MCP tools, known doc domains),
#          plus git commit: local-only and reversible, and the dangerous variants
#          (-a, --no-verify, add -A/.) are denied below; push still asks
# ask    = forced confirmation for outward-facing / cluster-mutating actions
# deny   = hard lines: credentials, secrets, destructive git, publish
synced_fields=$(cat <<'SETTINGS_EOF'
{
  "outputStyle": "Concise",

  "permissions": {
    "defaultMode": "auto",

    "allow": [
      "mcp__context7__resolve-library-id",
      "mcp__context7__query-docs",
      "mcp__sequential-thinking__sequentialthinking",
      "WebFetch(domain:github.com)",
      "WebFetch(domain:raw.githubusercontent.com)",
      "WebFetch(domain:registry.npmjs.org)",
      "WebFetch(domain:nodejs.org)",
      "WebFetch(domain:developer.mozilla.org)",

      "Bash(git commit *)"
    ],

    "ask": [
      "Bash(git push *)",

      "Bash(kubectl apply *)", "Bash(kubectl delete *)",
      "Bash(kubectl exec *)", "Bash(kubectl patch *)",
      "Bash(kubectl scale *)", "Bash(kubectl rollout *)",
      "Bash(kubectl get secret*)", "Bash(kubectl describe secret*)",

      "Bash(helm install *)", "Bash(helm upgrade *)",
      "Bash(helm uninstall *)", "Bash(helm rollback *)"
    ],

    "deny": [
      "Read(**/.env)",
      "Read(**/.env.local)",
      "Read(**/.env.production*)",
      "Read(**/.env.staging)",
      "Read(**/secrets/**)",
      "Read(~/.ssh/**)",
      "Read(~/.aws/**)",
      "Read(~/.kube/**)",
      "Read(~/.config/gh/**)",
      "Read(~/.config/glab-cli/**)",
      "Edit(**/.env*)",

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
  },

  "statusLine": {
    "type": "command",
    "command": "~/.config/claude/statusline.sh"
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

    # -- Sandbox: explicitly disabled --
    # Network isolation prompts on every new domain per session and cannot be
    # opened up, so the sandbox is off. File protection falls back to the
    # permissions.deny Read rules above (cover ~/.ssh, ~/.aws, .env, ...) plus
    # the protect-files / security-guard hooks. Overwrite (not merge) so legacy
    # filesystem/network/excludedCommands keys are dropped.
    jq '.sandbox = {"enabled": false}' "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp"
    mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
    echo "✓ Sandbox disabled (auto mode classifier + deny rules + hooks)"

    # ============================================================
    # 2. Hooks (idempotent additions)
    # ============================================================

    security_guard_cmd="~/.config/claude/hooks/security-guard.sh"
    protect_files_cmd="~/.config/claude/hooks/protect-files.sh"

    # -- Remove deprecated hooks (agent indicator + macOS notifications) --
    # These were disabled when switching to cmux
    for event in Notification Stop UserPromptSubmit; do
        if jq -e ".hooks.${event}" "$SETTINGS_FILE" &>/dev/null; then
            jq "del(.hooks.${event})" "$SETTINGS_FILE" > "${SETTINGS_FILE}.tmp"
            mv "${SETTINGS_FILE}.tmp" "$SETTINGS_FILE"
            echo "✓ Removed deprecated hook: ${event}"
        fi
    done

    # -- Security: PreToolUse hooks --
    sg_json=$(jq -n --arg cmd "$security_guard_cmd" '{"type":"command","command":$cmd}')
    ensure_hook_with_matcher "PreToolUse" "Bash" "$security_guard_cmd" "$sg_json"

    pf_json=$(jq -n --arg cmd "$protect_files_cmd" '{"type":"command","command":$cmd}')
    ensure_hook_with_matcher "PreToolUse" "Write|Edit|MultiEdit" "$protect_files_cmd" "$pf_json"

    # -- PreToolUse(Agent): model router --
    # 預設不作用：要在 ~/.config/claude/typesafe.env 設 ROUTER_MODE（shadow/fill-only/full）
    router_cmd="~/.config/claude/hooks/model-router.py"
    router_json=$(jq -n --arg cmd "$router_cmd" '{"type":"command","command":$cmd,"timeout":6}')
    ensure_hook_with_matcher "PreToolUse" "Agent|Task" "$router_cmd" "$router_json"

    # -- SubagentStop: 保存 subagent 報告（供 model router 覆盤/標註） --
    # 預設不作用：要在 ~/.config/claude/typesafe.env 設 ARCHIVE_SUBAGENT_REPORTS=1
    archive_cmd="~/.config/claude/hooks/archive-subagent-report.sh"
    archive_json=$(jq -n --arg cmd "$archive_cmd" '{"type":"command","command":$cmd,"timeout":10}')
    ensure_hook "SubagentStop" "$archive_cmd" "$archive_json"

    # -- SubagentStop: Layer 1 完成度篩檢（async，不阻塞 handback） --
    # 預設不作用：要設 JUDGE_SUBAGENT_OUTPUT=1
    judge_cmd="~/.config/claude/hooks/judge-subagent-output.sh"
    judge_json=$(jq -n --arg cmd "$judge_cmd" '{"type":"command","command":$cmd,"async":true}')
    ensure_hook "SubagentStop" "$judge_cmd" "$judge_json"

    # -- PostToolUse: tool-reduce（用 Jev 把冗餘段落換成可還原的墓碑） --
    # 預設不作用：要在 ~/.config/claude/typesafe.env 設 TOOL_REDUCE_MODE（shadow/full）。
    # 阻塞式：async hook 的 stdout 不會被採用，而這支要回傳 updatedToolOutput。
    # 自帶 2.5 秒硬性 timeout，任何異常都 fail-open（不輸出、exit 0）。
    reduce_cmd="~/.config/claude/hooks/tool-reduce.py"
    reduce_json=$(jq -n --arg cmd "$reduce_cmd" '{"type":"command","command":$cmd,"timeout":6}')
    ensure_hook_with_matcher "PostToolUse" "*" "$reduce_cmd" "$reduce_json"

    # -- PreToolUse: tool-reduce 的直接讀取守衛 --
    # 只觀察不阻擋：agent 不走 tr-restore 而直接讀存放區檔案時補記一筆還原遙測。
    # 那份遙測是 tr-eval / tr-tune 的地面真值，漏掉等於少一半訊號。
    guard_cmd="~/.config/claude/hooks/tr-guard.py"
    guard_json=$(jq -n --arg cmd "$guard_cmd" '{"type":"command","command":$cmd,"timeout":5}')
    ensure_hook_with_matcher "PreToolUse" "Bash|Read" "$guard_cmd" "$guard_json"

    # -- SessionEnd: 清掉這個 session 的段落原文 --
    # 原文只活在 session 生命週期內；archive/ 的紀錄不受影響。
    cleanup_cmd="~/.config/claude/hooks/tr-cleanup.sh"
    cleanup_json=$(jq -n --arg cmd "$cleanup_cmd" '{"type":"command","command":$cmd,"async":true,"timeout":10}')
    ensure_hook "SessionEnd" "$cleanup_cmd" "$cleanup_json"

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
# 5. Install subagent definitions
# ============================================================

AGENTS_SRC="${SOURCE_DIR}/claude-code/agents"

if [ -n "$SOURCE_DIR" ] && [ -d "$AGENTS_SRC" ]; then
    mkdir -p "$HOME/.claude/agents"
    for agent_file in "$AGENTS_SRC"/*.md; do
        [ -f "$agent_file" ] || continue
        cp "$agent_file" "$HOME/.claude/agents/"
        echo "✓ Installed agent: $(basename "$agent_file" .md)"
    done
else
    echo "⚠ Agents source not found at $AGENTS_SRC, skipping"
fi

# ============================================================
# 6. Install custom commands
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
