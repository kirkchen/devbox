# Claude Code + Obsidian 整合 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 建立 Obsidian vault 作為 Claude Code 的知識庫和 plan 管理介面，包含 MCP 整合、plan 同步工具、Kanban 看板和 Dataview dashboard。

**Architecture:** Obsidian vault (`~/Obsidian/DevBrain/`) 透過 MCP Server 讓 Claude Code 即時讀寫。各專案的 `docs/plans/` 透過自訂 skill + shell function 同步到 vault 並加上 frontmatter。Obsidian 未開啟時 Claude Code 可直接讀取 vault 檔案作為 fallback。

**Tech Stack:** Obsidian, obsidian-claude-code-mcp, Kanban plugin, Dataview plugin, Chezmoi (templates), Zsh (shell function)

---

## Stage 1: Vault 結構初始化

### Task 1.1: 建立 Vault 目錄結構

**Files:**
- Create: `~/Obsidian/DevBrain/Knowledge/Architecture/.gitkeep`
- Create: `~/Obsidian/DevBrain/Knowledge/Debugging/.gitkeep`
- Create: `~/Obsidian/DevBrain/Knowledge/Tools/.gitkeep`
- Create: `~/Obsidian/DevBrain/Knowledge/Learning/.gitkeep`
- Create: `~/Obsidian/DevBrain/Plans/.gitkeep`
- Create: `~/Obsidian/DevBrain/Daily/.gitkeep`
- Create: `~/Obsidian/DevBrain/Templates/.gitkeep`

**Step 1: 建立目錄結構**

```bash
mkdir -p ~/Obsidian/DevBrain/{Knowledge/{Architecture,Debugging,Tools,Learning},Plans,Daily,Templates}
```

**Step 2: 驗證結構**

```bash
ls -R ~/Obsidian/DevBrain/
```

Expected: 所有子目錄都已建立

### Task 1.2: 建立 Vault CLAUDE.md

**Files:**
- Create: `~/Obsidian/DevBrain/CLAUDE.md`

**Step 1: 建立 CLAUDE.md**

```markdown
# DevBrain Vault

This is an Obsidian knowledge base. Claude Code can read and search this vault via MCP or direct file access.

## Structure

- `Knowledge/` — Technical notes, architecture decisions, debug logs
  - `Architecture/` — ADR, system design notes
  - `Debugging/` — Debug experience and solutions
  - `Tools/` — Tool usage notes and tips
  - `Learning/` — Learning notes
- `Plans/` — Synced plans from development projects (managed by sync-plans)
  - `_Kanban.md` — Kanban board for plan tracking
  - `_Dashboard.md` — Dataview dashboard for all plans
  - `<project>/` — Plans organized by project name
- `Daily/` — Daily notes (optional)
- `Templates/` — Note templates

## Conventions

- All notes use YAML frontmatter for metadata
- Plans are synced from project `docs/plans/` directories, not authored here
- Knowledge notes should have tags in frontmatter for discoverability
- Use `[[wikilinks]]` for internal links
```

**Step 2: 驗證**

```bash
cat ~/Obsidian/DevBrain/CLAUDE.md
```

Expected: 檔案內容如上

### Task 1.3: 建立 Templates

**Files:**
- Create: `~/Obsidian/DevBrain/Templates/Knowledge.md`
- Create: `~/Obsidian/DevBrain/Templates/Debug-Log.md`

**Step 1: 建立 Knowledge 模板**

```markdown
---
tags: []
created: {{date:YYYY-MM-DD}}
---

# {{title}}

## Context

## Notes

## References
```

**Step 2: 建立 Debug-Log 模板**

```markdown
---
tags: [debugging]
created: {{date:YYYY-MM-DD}}
project:
---

# {{title}}

## Symptom

## Root Cause

## Solution

## Lessons Learned
```

**Step 3: 驗證**

```bash
ls ~/Obsidian/DevBrain/Templates/
```

Expected: `Knowledge.md`, `Debug-Log.md`

### Task 1.4: 手動安裝 Obsidian Plugins

> **注意**: 此步驟需要手動操作 Obsidian GUI

**Step 1: 開啟 Obsidian 並選擇 vault**

打開 Obsidian → Open folder as vault → 選擇 `~/Obsidian/DevBrain/`

**Step 2: 啟用 Community Plugins**

Settings → Community plugins → Turn on community plugins

**Step 3: 安裝必要 plugins**

Browse → 搜尋並安裝以下 plugins：
1. **Kanban** (by mgmeyers)
2. **Dataview** (by Michael Brenan)
3. **Tasks** (by Martin Schenck and Clare Macrae) — 可選

**Step 4: 啟用已安裝的 plugins**

Settings → Community plugins → 確認所有剛安裝的 plugins 都已 enabled

**Step 5: 驗證**

在 Obsidian 中建立一個測試 Kanban 檔案：
- 新增檔案 → 輸入 `---\nkanban-plugin: basic\n---\n\n## Test\n\n- [ ] test card`
- 確認看到 Kanban 視圖

驗證後刪除測試檔案。

---

## Stage 2: MCP Server 整合

### Task 2.1: 安裝 obsidian-claude-code-mcp Plugin

> **注意**: 此步驟需要手動操作 Obsidian GUI

**Step 1: 安裝 plugin**

Obsidian → Settings → Community plugins → Browse → 搜尋 "Claude Code MCP" → Install → Enable

**Step 2: 確認 plugin 設定**

Settings → Claude Code MCP → 確認 port 為 22360（預設值）

**Step 3: 驗證 WebSocket 啟動**

```bash
# 確認 port 22360 有在監聽（Obsidian 必須開啟）
lsof -i :22360
```

Expected: 看到 Obsidian 相關 process 在監聽

### Task 2.2: 配置 Claude Code MCP 連接

**Files:**
- Modify: `chezmoi/modify_dot_claude.json.tmpl`

**Step 1: 讀取現有的 modify script**

確認目前 `chezmoi/modify_dot_claude.json.tmpl` 的 DESIRED_MCP 結構。

**Step 2: 新增 obsidian MCP server 到 chezmoi 模板**

在 `DESIRED_MCP` JSON 中加入 obsidian 條目（僅 macOS，因 DevContainer 不會有 Obsidian）：

```json
{{- if eq .chezmoi.os "darwin" }},
  "obsidian": {
    "type": "websocket",
    "url": "ws://localhost:22360"
  }
{{- end }}
```

位置：加在 `sequential-thinking` 之後、`github` 條件判斷之前。

**Step 3: Apply chezmoi 更新**

```bash
chezmoi diff --source="./chezmoi"
```

Expected: 看到 `.claude.json` 會被更新，新增 obsidian MCP server

**Step 4: Apply 變更**

```bash
chezmoi apply --source="./chezmoi"
```

**Step 5: 驗證 MCP 設定**

```bash
cat ~/.claude.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('mcpServers',{}).get('obsidian',{}), indent=2))"
```

Expected: 看到 `{"type": "websocket", "url": "ws://localhost:22360"}`

**Step 6: 驗證 Claude Code 連接**

開啟新的 Claude Code session，檢查 MCP 連接：
```
claude /mcp
```

Expected: 看到 obsidian MCP server 在列表中（Obsidian 需開啟）

**Step 7: Commit**

```bash
cd ~/Code/Personal/devbox
git add chezmoi/modify_dot_claude.json.tmpl
git commit -m "feat(chezmoi): add obsidian MCP server config for macOS"
```

---

## Stage 3: Plan 同步工具

### Task 3.1: 建立 sync-plans Shell Function

**Files:**
- Create: `chezmoi/private_dot_config/zsh/obsidian.zsh`
- Modify: `chezmoi/dot_zshrc.tmpl` (source the new file, macOS only)

**Step 1: 查看 dot_zshrc.tmpl 了解 source 模式**

確認 zshrc 中 source 其他 zsh 檔案的 pattern。

**Step 2: 建立 obsidian.zsh**

```bash
# === Obsidian Integration ===

OBSIDIAN_VAULT="$HOME/Obsidian/DevBrain"
OBSIDIAN_PLANS_DIR="$OBSIDIAN_VAULT/Plans"

# sync-plans: 同步專案的 docs/plans/ 到 Obsidian vault
#
# Usage:
#   sync-plans              # 同步當前專案
#   sync-plans /path/to/project   # 同步指定專案
#   sync-plans --all        # 同步 ~/Code 下所有專案
#   sync-plans -h           # 說明
sync-plans() {
    if [[ ! -d "$OBSIDIAN_VAULT" ]]; then
        echo "Error: Obsidian vault not found at $OBSIDIAN_VAULT" >&2
        return 1
    fi

    case "${1:-}" in
        -h|--help)
            echo "Usage: sync-plans [--all | /path/to/project]"
            echo ""
            echo "Sync docs/plans/ markdown files to Obsidian vault."
            echo "Adds frontmatter (project, source, synced, status, tags)."
            echo ""
            echo "Options:"
            echo "  --all         Sync all projects under ~/Code"
            echo "  /path         Sync specific project"
            echo "  (no args)     Sync current git project"
            return 0
            ;;
        --all)
            local count=0
            for plans_dir in ~/Code/**/docs/plans(/N); do
                local project_root="${plans_dir:h:h}"
                _sync_plans_project "$project_root" && ((count++))
            done
            echo "Synced plans from $count project(s)"
            ;;
        "")
            local project_root
            project_root="$(git rev-parse --show-toplevel 2>/dev/null)"
            if [[ -z "$project_root" ]]; then
                echo "Error: Not in a git repository. Specify a path or use --all." >&2
                return 1
            fi
            _sync_plans_project "$project_root"
            ;;
        *)
            if [[ ! -d "$1" ]]; then
                echo "Error: Directory '$1' does not exist." >&2
                return 1
            fi
            _sync_plans_project "$(cd "$1" && pwd)"
            ;;
    esac
}

# _sync_plans_project: 同步單一專案的 plans
_sync_plans_project() {
    local project_root="$1"
    local project_name="$(basename "$project_root")"
    local source_dir="$project_root/docs/plans"
    local target_dir="$OBSIDIAN_PLANS_DIR/$project_name"

    if [[ ! -d "$source_dir" ]]; then
        echo "Skip: $project_name (no docs/plans/)"
        return 1
    fi

    mkdir -p "$target_dir"

    local synced=0
    local today="$(date +%Y-%m-%d)"

    for source_file in "$source_dir"/*.md(N); do
        local filename="$(basename "$source_file")"
        local target_file="$target_dir/$filename"

        # 如果 vault 中已有此檔，保留手動修改的 status
        local existing_status=""
        if [[ -f "$target_file" ]]; then
            existing_status="$(sed -n 's/^status: *//p' "$target_file" | head -1)"
        fi

        local status="${existing_status:-not_started}"

        # 讀取原始內容（跳過已有的 frontmatter）
        local content
        if head -1 "$source_file" | grep -q '^---$'; then
            # 原始檔案有 frontmatter，取 frontmatter 結束後的內容
            content="$(awk '/^---$/{c++} c==2{found=1; next} found{print}' "$source_file")"
        else
            content="$(cat "$source_file")"
        fi

        # 寫入帶 frontmatter 的檔案
        cat > "$target_file" <<EOF
---
project: $project_name
source: docs/plans/$filename
synced: $today
status: $status
tags: [plan, $project_name]
---

$content
EOF
        ((synced++))
    done

    echo "Synced: $project_name ($synced files → $target_dir)"
}
```

**Step 3: 在 dot_zshrc.tmpl 中 source obsidian.zsh（macOS only）**

在 `dot_zshrc.tmpl` 中找到 source 其他 zsh 設定的區塊，加入：

```bash
{{- if eq .chezmoi.os "darwin" }}
source ~/.config/zsh/obsidian.zsh
{{- end }}
```

**Step 4: Apply chezmoi 並測試**

```bash
chezmoi diff --source="./chezmoi"
chezmoi apply --source="./chezmoi"
source ~/.zshrc
```

**Step 5: 測試 sync-plans function**

```bash
# 在 devbox 專案內測試
cd ~/Code/Personal/devbox
sync-plans
```

Expected:
```
Synced: devbox (3 files → ~/Obsidian/DevBrain/Plans/devbox)
```

**Step 6: 驗證 frontmatter**

```bash
head -8 ~/Obsidian/DevBrain/Plans/devbox/2026-02-11-zellij-sessionizer-design.md
```

Expected:
```yaml
---
project: devbox
source: docs/plans/2026-02-11-zellij-sessionizer-design.md
synced: 2026-02-15
status: not_started
tags: [plan, devbox]
---
```

**Step 7: 測試 status 保留**

```bash
# 手動修改 vault 中的 status
sed -i '' 's/status: not_started/status: in_progress/' ~/Obsidian/DevBrain/Plans/devbox/2026-02-11-zellij-sessionizer-design.md

# 再次同步
sync-plans

# 確認 status 被保留
head -8 ~/Obsidian/DevBrain/Plans/devbox/2026-02-11-zellij-sessionizer-design.md
```

Expected: `status: in_progress`（不被覆蓋）

**Step 8: Commit**

```bash
cd ~/Code/Personal/devbox
git add chezmoi/private_dot_config/zsh/obsidian.zsh chezmoi/dot_zshrc.tmpl
git commit -m "feat(zsh): add sync-plans function for Obsidian plan sync"
```

### Task 3.2: 建立 /sync-plans Claude Code Skill（可選進階）

> **注意**: 此 task 建立一個 Claude Code custom skill，讓 Claude Code 在 session 內呼叫 `/sync-plans` 來同步 plans 到 Obsidian vault。如果 shell function 已滿足需求，可跳過此 task。

**Files:**
- Create: `chezmoi/private_dot_claude/skills/sync-plans/SKILL.md`

**Step 1: 確認 custom skills 放置位置**

Claude Code custom skills 放在 `~/.claude/skills/<skill-name>/SKILL.md`。Chezmoi 管理路徑為 `chezmoi/private_dot_claude/skills/sync-plans/SKILL.md`。

**Step 2: 建立 SKILL.md**

```markdown
---
name: sync-plans
description: Sync project plans to Obsidian vault with frontmatter metadata
user_invocable: true
---

# Sync Plans to Obsidian

Sync the current project's `docs/plans/` files to the Obsidian vault at `~/Obsidian/DevBrain/Plans/`.

## Process

1. Run the `sync-plans` shell function via Bash tool
2. Report the sync results to the user

## Steps

**Step 1: Run sync**

```bash
sync-plans
```

**Step 2: Report results**

Tell the user which plans were synced and remind them to check the Obsidian Kanban board if they want to update statuses.
```

**Step 3: Apply chezmoi**

```bash
chezmoi diff --source="./chezmoi"
chezmoi apply --source="./chezmoi"
```

**Step 4: 驗證 skill 可用**

開啟新 Claude Code session，輸入 `/sync-plans`，確認 skill 被觸發。

**Step 5: Commit**

```bash
cd ~/Code/Personal/devbox
git add chezmoi/private_dot_claude/skills/sync-plans/SKILL.md
git commit -m "feat(claude): add /sync-plans skill for Obsidian plan sync"
```

---

## Stage 4: Dashboard 和 Kanban 設定

### Task 4.1: 建立 Kanban 看板

**Files:**
- Create: `~/Obsidian/DevBrain/Plans/_Kanban.md`

**Step 1: 同步現有 plans 到 vault**

```bash
sync-plans --all
```

**Step 2: 建立 Kanban 檔案**

```markdown
---
kanban-plugin: basic
---

## Not Started

## In Progress

## Done

%% kanban:settings
```json
{"kanban-plugin":"basic","lane-width":280,"show-checkboxes":false}
```
%%
```

**Step 3: 在 Obsidian 中手動加入卡片**

開啟 Obsidian → 開啟 `Plans/_Kanban.md` → 應顯示 Kanban 視圖 → 在各 lane 中加入對應的 plan 連結：

- Not Started lane: 點 "+" 加卡片，輸入 `[[devbox/2026-02-11-zcc-multi-project-dispatch-design|ZCC Multi-Project Dispatch]]`
- In Progress lane: `[[devbox/2026-02-15-obsidian-claude-code-integration|Obsidian Integration]]`

**Step 4: 驗證**

確認在 Obsidian 中可以拖拉卡片在 lanes 之間移動。

### Task 4.2: 建立 Dataview Dashboard

**Files:**
- Create: `~/Obsidian/DevBrain/Plans/_Dashboard.md`

**Step 1: 啟用 Dataview JavaScript Queries（如需要）**

Obsidian → Settings → Dataview → Enable JavaScript Queries → ON
Obsidian → Settings → Dataview → Enable Inline JavaScript Queries → ON

**Step 2: 建立 Dashboard 檔案**

````markdown
# Plans Dashboard

## All Plans by Status

```dataview
TABLE
  project AS "專案",
  status AS "狀態",
  synced AS "同步日期"
FROM "Plans"
WHERE file.name != "_Kanban" AND file.name != "_Dashboard"
SORT status ASC, synced DESC
```

## In Progress

```dataview
LIST
FROM "Plans"
WHERE status = "in_progress"
SORT synced DESC
```

## Not Started

```dataview
LIST
FROM "Plans"
WHERE status = "not_started"
SORT synced DESC
```

## Completed

```dataview
LIST
FROM "Plans"
WHERE status = "done"
SORT synced DESC
```
````

**Step 3: 驗證**

在 Obsidian 中開啟 `Plans/_Dashboard.md`，確認：
- 表格顯示所有同步的 plans 及其 metadata
- 各 status 區塊正確分類

---

## Stage 5: Chezmoi 整合（可選）

### Task 5.1: 將 Obsidian Templates 納入 Chezmoi 管理

**Files:**
- Create: `chezmoi/Obsidian/DevBrain/Templates/Knowledge.md` (exact path TBD based on chezmoi external_ support)

> **注意**: Chezmoi 預設管理 `~` 下的 dotfiles。管理 `~/Obsidian/` 需要用 chezmoi 的 `exact_` prefix 或 external source。此 task 需先確認 chezmoi 的 target 路徑配置。

**Step 1: 確認 chezmoi 是否支援管理 vault 路徑**

```bash
chezmoi target-path --source="./chezmoi"
```

如果 chezmoi target 是 `~`，則可以用 `chezmoi/Obsidian/DevBrain/Templates/` 來管理。

**Step 2: 加入 templates**

將 Task 1.3 建立的 templates 加入 chezmoi：

```bash
chezmoi add ~/Obsidian/DevBrain/Templates/Knowledge.md --source="./chezmoi"
chezmoi add ~/Obsidian/DevBrain/Templates/Debug-Log.md --source="./chezmoi"
chezmoi add ~/Obsidian/DevBrain/CLAUDE.md --source="./chezmoi"
```

**Step 3: 驗證**

```bash
chezmoi diff --source="./chezmoi"
```

Expected: 無差異（因為檔案已經是最新的）

**Step 4: Commit**

```bash
cd ~/Code/Personal/devbox
git add chezmoi/Obsidian/
git commit -m "feat(chezmoi): add Obsidian vault templates and CLAUDE.md"
```

### Task 5.2: 將 Obsidian 基礎設定納入 Chezmoi（可選）

> **注意**: `.obsidian/` 目錄包含大量 plugin 資料和 cache，不適合全部納入。只管理核心設定。

**Step 1: 識別需要管理的設定檔**

```bash
ls ~/Obsidian/DevBrain/.obsidian/
```

需管理的：`app.json`, `appearance.json`, `community-plugins.json`, `hotkeys.json`
不需管理的：`plugins/` (太大), `workspace.json` (動態), `cache/`

**Step 2: 加入核心設定**

```bash
chezmoi add ~/Obsidian/DevBrain/.obsidian/app.json --source="./chezmoi"
chezmoi add ~/Obsidian/DevBrain/.obsidian/appearance.json --source="./chezmoi"
chezmoi add ~/Obsidian/DevBrain/.obsidian/community-plugins.json --source="./chezmoi"
```

**Step 3: Commit**

```bash
cd ~/Code/Personal/devbox
git add chezmoi/Obsidian/
git commit -m "feat(chezmoi): add Obsidian core settings for backup"
```
