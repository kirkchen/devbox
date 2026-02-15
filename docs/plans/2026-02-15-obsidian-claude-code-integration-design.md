# Claude Code + Obsidian 整合設計

## Background

目前使用 Claude Code + superpowers plugin 進行開發，plan 文件產生在各專案的 `docs/plans/` 下。需要一個知識管理系統來：

1. **知識庫** — 累積技術筆記、架構決策、debug 經驗，讓 Claude Code 可引用
2. **Plan 管理** — 追蹤各專案 plan 的完成狀態（Kanban + Dashboard）
3. **雙向整合** — Claude Code 讀知識庫、同步 plan 到 Obsidian

## Goals

- Obsidian 作為統一知識庫 + plan 管理介面
- Claude Code 透過 MCP Server 讀寫 vault
- Plan 從各專案同步到 vault（非 symlink），加上 frontmatter 供 Dataview 查詢
- Obsidian 未開啟時 Claude Code 仍可直接讀取 vault 檔案（fallback）

## Non-Goals (YAGNI)

- 不取代 Claude Code 的 `~/.claude/` memory 系統
- 不在 Obsidian 內嵌 Claude Code terminal（已有 Zellij + zcc）
- 不修改 superpowers plugin 原始路徑（避免升級覆蓋）
- 不做自動化雙向同步（先手動觸發，需求明確後再自動化）

## Architecture

### 整合架構

```
Claude Code 工作時：
  ├── 寫 plan → 專案內 docs/plans/（superpowers 原生行為）
  ├── 讀知識庫 → MCP Server → Obsidian vault Knowledge/
  └── /sync-plans → 複製 plan 到 vault Plans/ + 加 frontmatter

Obsidian 端：
  ├── Kanban plugin → Plans/_Kanban.md（手動拖拉管理狀態）
  ├── Dataview → Plans/_Dashboard.md（自動查詢所有 plan 狀態）
  └── obsidian-claude-code-mcp plugin → 提供 MCP 讀寫能力

Fallback（Obsidian 未開啟）：
  └── Claude Code → Read/Grep 直接讀取 ~/Obsidian/DevBrain/
```

### Vault 結構

```
~/Obsidian/DevBrain/
├── .obsidian/                          ← Obsidian 設定（自動產生）
├── CLAUDE.md                           ← Claude Code 讀取的 vault 指引
│
├── Knowledge/                          ← 知識庫（手動 + AI 輔助）
│   ├── Architecture/                   ← 架構決策、ADR
│   ├── Debugging/                      ← Debug 經驗筆記
│   ├── Tools/                          ← 工具使用筆記
│   └── Learning/                       ← 學習筆記
│
├── Plans/                              ← 從各專案同步來的 plans
│   ├── _Kanban.md                      ← Kanban 看板（Plans 總覽）
│   ├── _Dashboard.md                   ← Dataview Dashboard
│   └── <project-name>/                 ← 各專案獨立資料夾
│       └── YYYY-MM-DD-<topic>.md       ← 同步時加上 frontmatter
│
├── Daily/                              ← 日誌（可選）
│
└── Templates/                          ← 模板
    ├── Plan.md
    ├── Knowledge.md
    └── Debug-Log.md
```

### Plan 同步機制

同步時自動加上 frontmatter，讓 Dataview 和 Kanban 可查詢：

```yaml
---
project: devbox
source: docs/plans/2026-02-11-zellij-sessionizer-design.md
synced: 2026-02-15
status: in_progress
tags: [plan, devbox]
---
```

**兩個觸發方式**：

1. **`/sync-plans` Claude Code Skill** — 智慧同步
   - 掃描當前專案（或指定專案）的 `docs/plans/`
   - 比對 vault 中已有的檔案，只同步新增/變更的
   - 自動加上 frontmatter（project、source、synced、status、tags）
   - 保留 vault 中手動修改的 status（不覆蓋）

2. **`sync-plans` Shell Function** — 快速手動同步
   - 一鍵 rsync 所有專案的 plans 到 vault
   - 適合批量同步或 Obsidian 未開啟時使用

### MCP Server 配置

使用 `obsidian-claude-code-mcp` Obsidian plugin：

- **協定**: WebSocket (port 22360)
- **自動發現**: Claude Code 自動連接運行中的 Obsidian vault
- **功能**: 讀取/寫入/搜尋 vault 內容

Claude Code MCP 設定（`~/.claude.json`）：

```json
{
  "mcpServers": {
    "obsidian": {
      "type": "websocket",
      "url": "ws://localhost:22360"
    }
  }
}
```

### Obsidian Plugins

| Plugin | 用途 | 優先級 |
|--------|------|--------|
| **obsidian-claude-code-mcp** | MCP Server，讓 Claude Code 讀寫 vault | 必要 |
| **Kanban** (mgmeyers/obsidian-kanban) | Plan 看板管理，拖拉狀態 | 必要 |
| **Dataview** (blacksmithgu/obsidian-dataview) | Dashboard 查詢 + 自動化視圖 | 必要 |
| **Tasks** (obsidian-tasks-group/obsidian-tasks) | 進階 checkbox 任務管理 | 可選 |

### Dataview Dashboard 範例

```dataview
TABLE
  project AS "專案",
  status AS "狀態",
  synced AS "同步日期"
FROM "Plans"
WHERE tags AND contains(tags, "plan")
SORT synced DESC
```

### Kanban 看板格式

```markdown
---
kanban-plugin: basic
---

## Not Started

- [ ] [[devbox/2026-02-11-zcc-multi-project-dispatch-design|ZCC Multi-Project Dispatch]]

## In Progress

- [ ] [[devbox/2026-02-11-zellij-sessionizer-design|Zellij Sessionizer]]

## Done
```

## Implementation Stages

### Stage 1: Obsidian Vault 初始化
**Goal**: 建立 vault 結構和安裝核心 plugins
**Success Criteria**: Obsidian 可開啟 vault，Kanban/Dataview 可運作
**Status**: Not Started

### Stage 2: MCP Server 整合
**Goal**: Claude Code 可透過 MCP 讀寫 vault
**Success Criteria**: Claude Code 內可搜尋/讀取 vault 筆記
**Status**: Not Started

### Stage 3: Plan 同步工具
**Goal**: 建立 `/sync-plans` skill 和 `sync-plans` shell function
**Success Criteria**: 可從專案同步 plans 到 vault，含 frontmatter
**Status**: Not Started

### Stage 4: Dashboard 和 Kanban 設定
**Goal**: 建立 Dataview dashboard 和 Kanban 看板
**Success Criteria**: 可在 Obsidian 中視覺化管理所有 plans 狀態
**Status**: Not Started

### Stage 5: Chezmoi 整合（可選）
**Goal**: 將 Obsidian 設定和 templates 納入 chezmoi 管理
**Success Criteria**: 新環境可一鍵復原 Obsidian 設定
**Status**: Not Started

## References

- [obsidian-claude-code-mcp](https://github.com/iansinnott/obsidian-claude-code-mcp) — MCP Server plugin
- [Obsidian Kanban](https://github.com/mgmeyers/obsidian-kanban) — Kanban plugin
- [Obsidian Dataview](https://blacksmithgu.github.io/obsidian-dataview/) — Dataview plugin
- [Claudesidian](https://github.com/heyitsnoah/claudesidian) — 預配置 vault 參考
- [Kyle Gao: Using Claude Code with Obsidian](https://kyleygao.com/blog/2025/using-claude-code-with-obsidian/)
