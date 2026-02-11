# Zellij Sessionizer Design

## Goal

在 Zellij 內按 Ctrl+f 開啟 fzf 選單，快速切換到任意 session/tab/目錄。

## Data Sources

1. **現有 Zellij sessions + tabs** — `zellij list-sessions` + `zellij action query-tab-names`
2. **掃描目錄** — `~/Code` 底下的 git repo（maxdepth 2）

## Display Format

```
 ★ devbox:feat-lazygit        tab:claude    ← 當前 session
 ● backend:main               tab:main
 ● backend:feat-auth          tab:claude
 ○ ~/Code/frontend
 ○ ~/Code/mobile
```

排序：當前 session tabs → 其他 sessions → 未建立 session 的目錄。

## Selection Actions

| 選到的目標 | 動作 |
|-----------|------|
| 當前 session 的 tab | `zellij action go-to-tab-name` (瞬間) |
| 其他已存在的 session | 寫 flag file + `zellij action detach` |
| 新目錄 | 寫 flag file + `zellij action detach` |
| ESC 取消 | 什麼都不做 |

## Session Switch Mechanism

利用 zcc wrapper loop（與 Alt+e 同樣模式）：

1. sessionizer.sh 寫 `/tmp/zcc-switch-session-$ZELLIJ_SESSION_NAME`（目標 session name 或目錄路徑）
2. 執行 `zellij action detach`（原 session 背景繼續跑）
3. `zcc` wrapper 偵測 flag file：
   - 目標是 session name → `zellij attach "$target"`
   - 目標是目錄路徑 → `zcc -d "$target_dir"`（建新 session）

## Files

| 檔案 | 動作 |
|------|------|
| `chezmoi/private_dot_config/zellij/sessionizer.sh` | 新增 — fzf sessionizer script (~50 行) |
| `chezmoi/private_dot_config/zellij/config.kdl` | 修改 — 加 Ctrl+f keybinding |
| `chezmoi/private_dot_config/zsh/zellij.zsh` | 修改 — zcc() 加 session switch flag 偵測 |

## Keybinding

```kdl
bind "Ctrl f" {
    Run "bash" "$HOME/.config/zellij/sessionizer.sh" {
        floating true
        close_on_exit true
    }
}
```

## Out of Scope

- Pin 功能（未來可加）
- CLI 指令（只做 Zellij 內快捷鍵）
- WASM plugin（用 shell script + fzf 實現）
