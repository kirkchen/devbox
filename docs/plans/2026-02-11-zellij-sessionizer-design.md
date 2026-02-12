# Zellij Sessionizer Design

> **Status**: 基礎功能已完成（649abd2），Session Summary 功能已完成（375b17c）
> **後續擴展**: 見 [zcc-multi-project-dispatch-design.md](./2026-02-11-zcc-multi-project-dispatch-design.md)

## Goal

在 Zellij 內按 Ctrl+f 開啟 fzf 選單，快速切換到任意 session/tab，並顯示 Claude Code session 的任務摘要。

## Data Sources

1. **現有 Zellij tabs** — `zellij action query-tab-names`
2. **其他 Zellij sessions** — `zellij list-sessions -ns`
3. **Claude Code session summary** — `~/.claude/projects/*/sessions-index.json` 或 JSONL fallback

## Display Format

```
 * devbox:feat-lazygit        tab    claude
 + ai-agents                  ses    MarkItDown MCP 安裝與連線問題排查
 + infra-gitops:main          ses    ok
 + bill-analysis:main         ses    Cognito + Gmail Scope 可行性測試
```

排序：當前 session tabs → 其他 sessions（帶 summary）

## Summary Lookup

Session summary 取得邏輯（在 `_get_summaries()` 中實作）：

1. 從 session name 提取 project name（`devbox:feat-x` → `devbox`）
2. 在 `~/Code/`、`~/Code/Personal/` 下找到專案目錄
3. 編碼路徑為 Claude Code 格式（`/` 和 `.` → `-`）
4. **優先**：讀 `sessions-index.json`，匹配 `gitBranch` 或取最近 entry 的 `summary`
5. **Fallback**：解析最近 3 個 JSONL 檔案的第一個 user message

## Selection Actions

| 選到的目標 | 動作 |
|-----------|------|
| 當前 session 的 tab | `zellij action go-to-tab-name` (瞬間) |
| 其他已存在的 session | 寫 flag file + `zellij action detach` |
| ESC 取消 | 什麼都不做 |

## Session Switch Mechanism

利用 zcc wrapper loop（與 Alt+e 同樣模式）：

1. sessionizer.sh 寫 `/tmp/zcc-switch-session-$ZELLIJ_SESSION_NAME`（目標 session name）
2. 執行 `zellij action detach`（原 session 背景繼續跑）
3. `zcc` wrapper 偵測 flag file → `zellij attach "$target"`

## Files

| 檔案 | 說明 |
|------|------|
| `chezmoi/private_dot_config/zellij/executable_sessionizer.sh` | fzf sessionizer + summary lookup |
| `chezmoi/private_dot_config/zellij/config.kdl` | Ctrl+f keybinding |
| `chezmoi/private_dot_config/zsh/zellij.zsh` | zcc() session switch flag 偵測 |

## Keybinding

```kdl
bind "Ctrl f" {
    Run "bash" "$HOME/.config/zellij/sessionizer.sh" {
        floating true
        close_on_exit true
    }
}
```
