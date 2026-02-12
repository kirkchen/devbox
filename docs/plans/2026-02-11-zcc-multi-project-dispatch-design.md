# ZCC Multi-Project AI Dispatch System Design

## Background

目前 zcc + zellij sessionizer 已支援：
- 以 `repo:branch` 命名 session，一鍵啟動 Claude Code
- Ctrl+f 在現有 session/tab 之間切換
- Ctrl+g lazygit、Ctrl+t shell split、Alt+e exec mode

但缺少三個關鍵能力：
1. **專案發現** — sessionizer 只列已存在的 session，無法發現新專案
2. **Plan dispatch** — 無法從 plan 文件一鍵啟動 autopilot agent
3. **任務記憶** — 多 session 間切換時忘記各 session 的目標和進度

## Core Insight

Claude Code 的 `~/.claude/projects/*/sessions-index.json` 已經自動維護每個 session 的 **summary**：

```json
{
  "sessionId": "92bc44ba-...",
  "firstPrompt": "幫我分析本月網路用量",
  "summary": "GCP網路成本分析與NAT用量追蹤",
  "gitBranch": "feat/cost-analysis",
  "projectPath": "/Users/kirk.chen/Code/ai-agents",
  "modified": "2026-01-07T09:31:22.066Z"
}
```

**零維護成本** — 不需要手動 memo、不需要 /rename、不需要 Obsidian。直接讀 Claude 已有的 summary。

## Goals

建立一個輕量的「多專案 AI 調度系統」：
- Sessionizer 顯示 Claude Code 自動產生的 session summary
- 支援從 `~/Code` 發現並啟動新專案 session
- 一鍵把 plan dispatch 到 autopilot agent session
- 從 sessionizer 鳥瞰所有 agent 狀態和任務

## Non-Goals (YAGNI)

- ❌ TUI dashboard（增強版 sessionizer 夠用）
- ❌ Agent 間通訊（各 agent 獨立工作）
- ❌ 自動 commit plan（由使用者決定）
- ❌ Obsidian/Heptabase 整合（Claude Code summary 足夠）
- ❌ WASM plugin（shell script + fzf 已夠用且更靈活）
- ❌ 自建 memo 系統（sessions-index.json 已有 summary）

---

## Design

### 1. Session Summary 讀取

從 Claude Code 的 sessions-index.json 讀取任務摘要，顯示在 sessionizer 裡。

**映射邏輯**：
```
zellij session name: "devbox:feat-lazygit"
    ↓ 從 session name 取專案名
project name: "devbox"
    ↓ 在 ~/Code 下找目錄
project path: "/Users/kirk.chen/Code/devbox"
    ↓ 編碼為 Claude Code 路徑格式
sessions-index: "~/.claude/projects/-Users-kirk-chen-Code-devbox/sessions-index.json"
    ↓ 找最近修改的 entry（或匹配 gitBranch）
summary: "增強 sessionizer 功能"
```

**Helper function**: `_zcc_get_summary()`
```bash
_zcc_get_summary() {
    local session_name="$1"
    local project_name="${session_name%%:*}"  # "devbox:feat-x" → "devbox"

    # 找專案目錄
    local project_dir
    for base in ~/Code ~/Code/Personal; do
        if [[ -d "$base/$project_name" ]]; then
            project_dir="$base/$project_name"
            break
        fi
    done
    [[ -z "$project_dir" ]] && return

    # 編碼為 Claude Code 路徑格式
    local encoded_path
    encoded_path=$(echo "$project_dir" | sed 's|/|-|g; s|^-||')
    local index_file="$HOME/.claude/projects/-${encoded_path}/sessions-index.json"

    [[ ! -f "$index_file" ]] && return

    # 取最近的 session summary
    python3 -c "
import json, sys
with open('$index_file') as f:
    data = json.load(f)
entries = sorted(data.get('entries', []), key=lambda e: e.get('modified', ''), reverse=True)
if entries:
    print(entries[0].get('summary', entries[0].get('firstPrompt', ''))[:40])
" 2>/dev/null
}
```

### 2. 增強 Sessionizer (Ctrl+f)

在現有的兩個來源（tabs + sessions）之外，加入：

**顯示格式**（加入 summary）：
```
Ctrl+f 顯示：
  * devbox:feat-lazygit    tab    claude
  + backend:main           ses    GCP網路成本分析     🟢
  + ai-agents              ses    Jira Priority 查詢   ✅
  ○ ~/Code/frontend        dir
  ○ ~/Code/mobile          dir
```

**新來源: 專案目錄**
- 掃描 `~/Code/` 下 maxdepth 1 的目錄
- 排除已有 session 的專案（避免重複）
- 顯示為 `○ path  dir` 格式

**Session summary 顯示**
- 從 `_zcc_get_summary()` 取得
- 截斷為 30-40 字元顯示在 fzf 列表
- fzf `--preview` 可顯示完整 summary + firstPrompt

**Agent 狀態 icon**（可選，第二版）
- 🟢 — session 內有 claude process 正在跑
- ✅ — session 存在但 claude 已結束
- 偵測方式：`pgrep -f "claude.*session_name"` 或簡單檢查 zellij pane

**選到目錄的動作**：
- 寫 flag file（type=dir, target=路徑）
- detach → zcc wrapper 偵測 → `zcc -d "$target_dir"`

### 3. Plan Dispatch (zcc -p)

新增 `-p` 參數，從 plan 文件啟動 autopilot agent：

```bash
# 基本用法
zcc -p ~/path/to/plan.md

# 指定目錄
zcc -p plan.md -d ~/Code/project-a
```

**執行流程**：
```
1. 讀取 plan 文件內容
2. 決定專案目錄：
   a. 有 -d → 用指定目錄
   b. 無 -d → 用當前目錄
3. 組合 session name: "{project}:{branch}:exec"
4. 用 wrapper script 啟動 claude
5. Claude 帶 --dangerously-skip-permissions -p "plan 內容"
```

**Wrapper script**: `~/.config/zellij/claude-with-plan.sh`
```bash
#!/bin/bash
# 由 zcc -p 呼叫，讀取 plan 檔案並啟動 autopilot claude
PLAN_FILE="$1"
if [[ -f "$PLAN_FILE" ]]; then
    PLAN_CONTENT="$(cat "$PLAN_FILE")"
    exec claude --dangerously-skip-permissions -p "Execute this implementation plan:

$PLAN_CONTENT"
else
    echo "Error: Plan file not found: $PLAN_FILE" >&2
    exec claude --dangerously-skip-permissions
fi
```

**Layout**: 複用現有 `claude-exec.kdl`，透過 `zellij run` 動態建 pane 執行 wrapper script。

### 4. Flag File 機制改善

統一 flag 檔案格式：

```
目錄：/tmp/zcc/
格式：/tmp/zcc/{session-name}.flag
內容：
  type=session|dir|exec
  target=值
```

**改善**：
- 統一用 `/tmp/zcc/` 目錄
- zcc 啟動時清理超過 1 小時的 stale flags
- 向後相容：讀取時同時檢查舊格式

### 5. 完成通知（可選）

Agent 完成後：
- macOS: `osascript -e 'display notification "done" with title "zcc: project"'`
- Terminal bell: `echo -e '\a'`
- 在 wrapper script 的 claude 退出後觸發

---

## Implementation Stages

### Stage 1: Sessionizer 顯示 Summary ✅
**Goal**: Ctrl+f 列表顯示 Claude Code session 的任務摘要
**Status**: 已完成（merged to main: 375b17c）
**實際實作**:
- 在 `sessionizer.sh` 加入 `_get_summaries()` — 批次查詢 session summary
- 支援兩種來源：sessions-index.json（優先）、JSONL fallback
- 支援 gitBranch 匹配，fallback 到最近的 entry
- 效能：5 個 session < 80ms
**驗證**: Ctrl+f 看到 `+ ai-agents  MarkItDown MCP 安裝與連線問題排查`

### Stage 2: Sessionizer 專案發現
**Goal**: Ctrl+f 能看到未開啟的專案並一鍵建 session
**Changes**:
- `sessionizer.sh` 加入 `~/Code` 目錄掃描
- `zellij.zsh` zcc() 加入 dir flag 支援
**驗證**: Ctrl+f 選到新目錄 → 自動建 session

### Stage 3: Plan Dispatch (zcc -p)
**Goal**: 一鍵從 plan 啟動 autopilot agent
**Changes**:
- 新增 `claude-with-plan.sh` wrapper script
- `zellij.zsh` zcc() 加入 `-p` 參數
**驗證**: `zcc -p plan.md` → 啟動 exec mode + plan 內容作為 prompt

### Stage 4: 狀態監控 + 通知（可選）
**Goal**: sessionizer 顯示 agent 狀態，完成時通知
**Changes**:
- `sessionizer.sh` 加入 🟢/✅ 狀態 icon
- `claude-with-plan.sh` 加入完成通知
**驗證**: Ctrl+f 能看到狀態 icon + agent 完成時收到通知

---

## Files to Modify/Create

| 檔案 | 動作 | Stage |
|------|------|-------|
| `chezmoi/private_dot_config/zsh/zellij.zsh` | 修改 — 加 `-p` 參數、dir switch | 2, 3 |
| `chezmoi/private_dot_config/zellij/executable_sessionizer.sh` | 修改 — ✅ summary 顯示完成、待加目錄掃描、狀態 icon | ✅1, 2, 4 |
| `chezmoi/private_dot_config/zellij/executable_claude-with-plan.sh` | 新增 — plan wrapper script | 3 |

## Open Questions

1. **`~/Code` 掃描範圍**：只掃 maxdepth 1？還是也包含 `~/Code/Personal/`？
2. ~~**sessions-index.json 格式穩定性**~~：已加 JSONL fallback 解決
3. ~~**Branch 匹配**~~：已實作 — 優先匹配 gitBranch，fallback 到最新 entry
4. **Worktree 整合**：`zcc -p plan.md -w branch-name` 要在哪個 stage 加？
