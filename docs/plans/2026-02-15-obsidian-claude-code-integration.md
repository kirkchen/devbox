# Claude Code + Obsidian 整合 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 建立 Obsidian vault（GitHub private repo）作為 Claude Code + OpenClaw 共享的知識庫和 plan 管理介面。三端（Obsidian GUI、Claude Code、OpenClaw）透過 git 同步，commit 只在有意義的寫入時觸發。

**Architecture:** Vault 是 `kirkchen/obsidian-vault` GitHub private repo，本機 clone 到 `~/Code/Personal/obsidian-vault/`。Obsidian 用 obsidian-git plugin 同步，Claude Code 用 MCP + 直接檔案讀寫，OpenClaw 用 git-vault-sync sidecar。各專案的 `docs/plans/` 透過 `sync-plans` 工具同步到 vault 並加上 frontmatter。

**Tech Stack:** Obsidian, obsidian-git, obsidian-claude-code-mcp, Kanban plugin, Dataview plugin, Chezmoi, Zsh, GitHub Private Repo

---

## Stage 1: Vault Git Repo + 結構初始化

### Task 1.1: 建立 GitHub Private Repo 並 Clone

**Step 1: 建立 GitHub private repo**

```bash
gh repo create kirkchen/obsidian-vault --private --description "Obsidian DevBrain vault - shared knowledge base for Claude Code and OpenClaw"
```

Expected: Repo 建立成功

**Step 2: Clone 到本機**

```bash
mkdir -p ~/Obsidian
gh repo clone kirkchen/obsidian-vault ~/Code/Personal/obsidian-vault
```

**Step 3: 驗證**

```bash
cd ~/Code/Personal/obsidian-vault && git remote -v
```

Expected: 看到 `origin` 指向 `kirkchen/obsidian-vault`

### Task 1.2: 建立 Vault 目錄結構

**Files:**
- Create: `~/Code/Personal/obsidian-vault/` 下的目錄結構和 .gitkeep 檔案

**Step 1: 建立目錄結構**

```bash
cd ~/Code/Personal/obsidian-vault
mkdir -p Knowledge/{Architecture,Debugging,Tools,Learning} Plans Daily Templates
touch Knowledge/Architecture/.gitkeep Knowledge/Debugging/.gitkeep Knowledge/Tools/.gitkeep Knowledge/Learning/.gitkeep Plans/.gitkeep Daily/.gitkeep Templates/.gitkeep
```

**Step 2: 建立 .gitignore**

```
# Obsidian workspace (dynamic, don't sync)
.obsidian/workspace.json
.obsidian/workspace-mobile.json

# Obsidian cache
.obsidian/cache/

# OS files
.DS_Store
Thumbs.db
```

**Step 3: Commit 並 Push**

```bash
cd ~/Code/Personal/obsidian-vault
git add -A
git commit -m "init: vault directory structure"
git push
```

### Task 1.3: 建立 Vault CLAUDE.md

**Files:**
- Create: `~/Code/Personal/obsidian-vault/CLAUDE.md`

**Step 1: 建立 CLAUDE.md**

```markdown
# DevBrain Vault

This is an Obsidian knowledge base shared by Claude Code (local) and OpenClaw (K8s).

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

## Writers

- **User**: Manual notes via Obsidian GUI
- **Claude Code**: Reads knowledge, syncs plans via `/sync-plans`
- **OpenClaw**: Saves link summaries, research notes via Telegram
```

**Step 2: Commit**

```bash
cd ~/Code/Personal/obsidian-vault
git add CLAUDE.md
git commit -m "docs: add vault CLAUDE.md for AI agents"
git push
```

### Task 1.4: 建立 Templates

**Files:**
- Create: `~/Code/Personal/obsidian-vault/Templates/Knowledge.md`
- Create: `~/Code/Personal/obsidian-vault/Templates/Debug-Log.md`

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

**Step 3: Commit**

```bash
cd ~/Code/Personal/obsidian-vault
git add Templates/
git commit -m "feat: add Knowledge and Debug-Log templates"
git push
```

---

## Stage 2: Obsidian Plugins + MCP Server 整合

### Task 2.1: 手動安裝 Obsidian Plugins

> **注意**: 此步驟需要手動操作 Obsidian GUI

**Step 1: 開啟 Obsidian 並選擇 vault**

打開 Obsidian → Open folder as vault → 選擇 `~/Code/Personal/obsidian-vault/`

**Step 2: 啟用 Community Plugins**

Settings → Community plugins → Turn on community plugins

**Step 3: 安裝必要 plugins**

Browse → 搜尋並安裝以下 plugins：
1. **Obsidian Git** (by Vinzent03) — Git sync
2. **Claude Code MCP** (by iansinnott) — MCP Server
3. **Kanban** (by mgmeyers) — 看板管理
4. **Dataview** (by Michael Brenan) — Dashboard 查詢

**Step 4: 啟用所有剛安裝的 plugins**

Settings → Community plugins → 確認所有 plugins 都已 enabled

**Step 5: 配置 Obsidian Git**

Settings → Obsidian Git:
- Auto pull interval: `5` (分鐘，自動拉取遠端變更)
- Auto push: `OFF`（不自動 push，避免無意義 commit）
- Pull on startup: `ON`
- Commit on close: `ON`（關閉 Obsidian 時 commit 未儲存的變更）
- Commit message: `obsidian: {{hostname}} - {{numFiles}} files changed`

**Step 6: 配置 Claude Code MCP**

Settings → Claude Code MCP → 確認 port 為 22360（預設值）

**Step 7: 驗證 Git sync**

```bash
cd ~/Code/Personal/obsidian-vault && git log --oneline -3
```

Expected: 看到前面的 commits

**Step 8: 驗證 MCP WebSocket**

```bash
# Obsidian 必須開啟
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

**Step 3: Apply chezmoi 並驗證**

```bash
chezmoi diff --source="./chezmoi"
chezmoi apply --source="./chezmoi"
```

**Step 4: 驗證 MCP 設定**

```bash
cat ~/.claude.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(json.dumps(d.get('mcpServers',{}).get('obsidian',{}), indent=2))"
```

Expected: `{"type": "websocket", "url": "ws://localhost:22360"}`

**Step 5: Commit**

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

OBSIDIAN_VAULT="$HOME/Code/Personal/obsidian-vault"
OBSIDIAN_PLANS_DIR="$OBSIDIAN_VAULT/Plans"

# sync-plans: 同步專案的 docs/plans/ 到 Obsidian vault 並 commit + push
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

    # 先 pull 最新變更
    git -C "$OBSIDIAN_VAULT" pull --rebase --quiet 2>/dev/null

    local total_synced=0

    case "${1:-}" in
        -h|--help)
            echo "Usage: sync-plans [--all | /path/to/project]"
            echo ""
            echo "Sync docs/plans/ markdown files to Obsidian vault."
            echo "Adds frontmatter (project, source, synced, status, tags)."
            echo "Auto commits and pushes to GitHub after sync."
            echo ""
            echo "Options:"
            echo "  --all         Sync all projects under ~/Code"
            echo "  /path         Sync specific project"
            echo "  (no args)     Sync current git project"
            return 0
            ;;
        --all)
            for plans_dir in ~/Code/**/docs/plans(/N); do
                local project_root="${plans_dir:h:h}"
                local count
                count=$(_sync_plans_project "$project_root")
                ((total_synced += count))
            done
            ;;
        "")
            local project_root
            project_root="$(git rev-parse --show-toplevel 2>/dev/null)"
            if [[ -z "$project_root" ]]; then
                echo "Error: Not in a git repository. Specify a path or use --all." >&2
                return 1
            fi
            total_synced=$(_sync_plans_project "$project_root")
            ;;
        *)
            if [[ ! -d "$1" ]]; then
                echo "Error: Directory '$1' does not exist." >&2
                return 1
            fi
            total_synced=$(_sync_plans_project "$(cd "$1" && pwd)")
            ;;
    esac

    # Commit & push if there are changes
    if [[ $total_synced -gt 0 ]]; then
        local project_name
        if [[ "${1:-}" == "--all" ]]; then
            project_name="all projects"
        else
            project_name="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "${1:-unknown}")")"
        fi

        git -C "$OBSIDIAN_VAULT" add Plans/
        git -C "$OBSIDIAN_VAULT" commit -m "sync-plans: $project_name ($total_synced files)"
        git -C "$OBSIDIAN_VAULT" push --quiet
        echo "Committed and pushed to GitHub."
    else
        echo "No changes to sync."
    fi
}

# _sync_plans_project: 同步單一專案的 plans，回傳同步檔案數
_sync_plans_project() {
    local project_root="$1"
    local project_name="$(basename "$project_root")"
    local source_dir="$project_root/docs/plans"
    local target_dir="$OBSIDIAN_PLANS_DIR/$project_name"

    if [[ ! -d "$source_dir" ]]; then
        echo 0
        return
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

    echo >&2 "Synced: $project_name ($synced files → $target_dir)"
    echo $synced
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
cd ~/Code/Personal/devbox
sync-plans
```

Expected:
```
Synced: devbox (N files → ~/Code/Personal/obsidian-vault/Plans/devbox)
Committed and pushed to GitHub.
```

**Step 6: 驗證 frontmatter**

```bash
head -8 ~/Code/Personal/obsidian-vault/Plans/devbox/2026-02-11-zellij-sessionizer-design.md
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
sed -i '' 's/status: not_started/status: in_progress/' ~/Code/Personal/obsidian-vault/Plans/devbox/2026-02-11-zellij-sessionizer-design.md

# 再次同步
sync-plans

# 確認 status 被保留
head -8 ~/Code/Personal/obsidian-vault/Plans/devbox/2026-02-11-zellij-sessionizer-design.md
```

Expected: `status: in_progress`（不被覆蓋）

**Step 8: Commit**

```bash
cd ~/Code/Personal/devbox
git add chezmoi/private_dot_config/zsh/obsidian.zsh chezmoi/dot_zshrc.tmpl
git commit -m "feat(zsh): add sync-plans function for Obsidian plan sync"
```

### Task 3.2: 建立 /sync-plans Claude Code Skill（可選進階）

> 如果 shell function 已滿足需求，可跳過此 task。

**Files:**
- Create: `chezmoi/private_dot_claude/skills/sync-plans/SKILL.md`

**Step 1: 建立 SKILL.md**

```markdown
---
name: sync-plans
description: Sync project plans to Obsidian vault with frontmatter metadata
user_invocable: true
---

# Sync Plans to Obsidian

Sync the current project's `docs/plans/` files to the Obsidian vault at `~/Code/Personal/obsidian-vault/Plans/`.

## Process

1. Run the `sync-plans` shell function via Bash tool
2. Report the sync results to the user

## Steps

**Step 1: Run sync**

\```bash
sync-plans
\```

**Step 2: Report results**

Tell the user which plans were synced and remind them to check the Obsidian Kanban board if they want to update statuses.
```

**Step 2: Apply chezmoi**

```bash
chezmoi diff --source="./chezmoi"
chezmoi apply --source="./chezmoi"
```

**Step 3: 驗證 skill 可用**

開啟新 Claude Code session，輸入 `/sync-plans`，確認 skill 被觸發。

**Step 4: Commit**

```bash
cd ~/Code/Personal/devbox
git add chezmoi/private_dot_claude/skills/sync-plans/SKILL.md
git commit -m "feat(claude): add /sync-plans skill for Obsidian plan sync"
```

---

## Stage 4: Dashboard 和 Kanban 設定

### Task 4.1: 建立 Kanban 看板

**Files:**
- Create: `~/Code/Personal/obsidian-vault/Plans/_Kanban.md`

**Step 1: 確保 plans 已同步**

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
{"kanban-plugin":"basic","lane-width":280,"show-checkboxes":false}
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
- Create: `~/Code/Personal/obsidian-vault/Plans/_Dashboard.md`

**Step 1: 啟用 Dataview 設定**

Obsidian → Settings → Dataview → Enable JavaScript Queries → ON

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

**Step 3: Commit vault 變更**

```bash
cd ~/Code/Personal/obsidian-vault
git add Plans/_Kanban.md Plans/_Dashboard.md
git commit -m "feat: add Kanban board and Dataview dashboard for plan tracking"
git push
```

**Step 4: 驗證**

在 Obsidian 中開啟 `Plans/_Dashboard.md`，確認表格顯示所有同步的 plans 及其 metadata。

---

## Stage 5: OpenClaw Vault 整合

### Task 5.1: 更新 OpenClaw git-vault-sync 策略

> **注意**: 此 task 在 `personal-gitops` repo 的 `feat/openclaw-obsidian-vault` branch 上操作。

**Files:**
- Modify: `kubernetes/apps/apps/openclaw/values.yaml` (在 personal-gitops repo)

**Step 1: 切換到 personal-gitops repo 的 feature branch**

```bash
cd ~/Code/Personal/personal-gitops
git checkout feat/openclaw-obsidian-vault
git pull
```

**Step 2: 更新 git-vault-sync 配置**

將 sync 策略從「定時 5 分鐘輪詢 commit」改為「只 pull，寫入由 OpenClaw agent 觸發」：

git-vault-sync sidecar 改為只負責 pull（每 5 分鐘拉取遠端變更）。
commit & push 改由 OpenClaw agent 的 skill 在寫入後執行。

**Step 3: 更新 OpenClaw link-summarizer skill**

在 skill 的寫入步驟後加入 git commit & push：

```bash
cd /vault
git add -A
git commit -m "openclaw: save link summary - <title>"
git push
```

**Step 4: Commit 並 Push**

```bash
cd ~/Code/Personal/personal-gitops
git add -A
git commit -m "feat(openclaw): change vault sync to commit-on-write strategy"
git push
```

**Step 5: 驗證**

透過 Telegram 發一個連結給 OpenClaw，確認：
1. OpenClaw 產生摘要並寫入 vault
2. Commit message 是有意義的（不是 auto-sync）
3. Obsidian 在下次 pull 時看到新筆記
