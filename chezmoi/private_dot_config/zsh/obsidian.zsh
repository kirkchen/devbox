# === Obsidian Integration ===

OBSIDIAN_VAULT="$HOME/Code/Personal/obsidian-vault"
OBSIDIAN_PLANS_DIR="$OBSIDIAN_VAULT/Projects"

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
                _sync_plans_project "${plans_dir:h:h}"
            done
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

    # 從 Kanban 讀取手動拖拉的 status，反寫到 plan frontmatter
    _sync_kanban_status

    # 重建 Kanban 看板
    _rebuild_kanban

    # Commit & push if vault has changes
    if ! git -C "$OBSIDIAN_VAULT" diff --quiet Projects/ 2>/dev/null || \
       [[ -n "$(git -C "$OBSIDIAN_VAULT" ls-files --others --exclude-standard Projects/)" ]]; then
        local commit_msg
        if [[ "${1:-}" == "--all" ]]; then
            commit_msg="sync-plans: all projects"
        else
            local pname="$(basename "$(git rev-parse --show-toplevel 2>/dev/null || echo "${1:-unknown}")")"
            commit_msg="sync-plans: $pname"
        fi

        git -C "$OBSIDIAN_VAULT" add Projects/
        git -C "$OBSIDIAN_VAULT" commit -m "$commit_msg"
        git -C "$OBSIDIAN_VAULT" push --quiet
        echo "Committed and pushed to GitHub."
    else
        echo "No changes to sync."
    fi
}

# _sync_plans_project: 同步單一專案的 plans 到 vault
_sync_plans_project() {
    local project_root="$1"
    local project_name="$(basename "$project_root")"
    local source_dir="$project_root/docs/plans"
    local target_dir="$OBSIDIAN_PLANS_DIR/$project_name/plans"

    if [[ ! -d "$source_dir" ]]; then
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
        local plan_status="${existing_status:-backlog}"

        # 讀取原始內容（跳過已有的 frontmatter）
        local content
        if head -1 "$source_file" | grep -q '^---$'; then
            content="$(awk '/^---$/{c++} c==2{found=1; next} found{print}' "$source_file")"
        else
            content="$(cat "$source_file")"
        fi

        # 偵測對應的 design 檔
        local design_link=""
        local base_name="${filename%.md}"
        if [[ "$base_name" != *-design ]]; then
            local design_file="${base_name}-design.md"
            if [[ -f "$target_dir/$design_file" ]]; then
                design_link="\"[[${project_name}/plans/${base_name}-design|${design_file}]]\""
            fi
        fi

        # 寫入帶 frontmatter 的檔案
        cat > "$target_file" <<ENDOFPLAN
---
project: $project_name
source: docs/plans/$filename
synced: $today
status: $plan_status
${design_link:+design: $design_link
}tags: [plan, $project_name]
---

$content
ENDOFPLAN
        synced=$((synced + 1))
    done

    echo "Synced: $project_name ($synced files → $target_dir)"
}

# _sync_kanban_status: 從 Kanban 的 lane 位置反寫 status 到 plan frontmatter
_sync_kanban_status() {
    local kanban_file="$OBSIDIAN_PLANS_DIR/_Kanban.md"
    [[ ! -f "$kanban_file" ]] && return

    local current_lane=""
    while IFS= read -r line; do
        case "$line" in
            "## Backlog")      current_lane="backlog" ;;
            "## Not Started")  current_lane="not_started" ;;
            "## In Progress")  current_lane="in_progress" ;;
            "## Done")         current_lane="done" ;;
            "## Archived")     current_lane="archived" ;;
            *)
                # 檢查是否包含 [[ 連結
                [[ "$line" != *'[['* ]] && continue
                [[ -z "$current_lane" ]] && continue
                # 從 [[path|title]] 取出 path
                local link_path="${line#*\[\[}"
                link_path="${link_path%%|*}"
                link_path="${link_path%%\]\]*}"
                local plan_file="$OBSIDIAN_PLANS_DIR/${link_path}.md"
                [[ ! -f "$plan_file" ]] && continue
                # 反寫 status 到 implementation plan
                local old_status="$(awk '/^---$/{c++; next} c==1 && /^status:/{print $2; exit}' "$plan_file")"
                if [[ "$old_status" != "$current_lane" ]]; then
                    sed -i '' "s/^status: .*/status: $current_lane/" "$plan_file"
                fi
                # 同步 status 到對應的 design 檔
                local design_file="${plan_file%.md}-design.md"
                if [[ -f "$design_file" ]]; then
                    sed -i '' "s/^status: .*/status: $current_lane/" "$design_file"
                fi
                ;;
        esac
    done < "$kanban_file"
}

# _rebuild_kanban: 從 plan frontmatter 重建 Kanban 看板
_rebuild_kanban() {
    local kanban_file="$OBSIDIAN_PLANS_DIR/_Kanban.md"
    local backlog="" not_started="" in_progress="" done_cards=""

    for plan_file in "$OBSIDIAN_PLANS_DIR"/**/*.md(N); do
        local fname="$(basename "$plan_file")"
        [[ "$fname" == _* ]] && continue

        # 跳過 design 檔：如果對應的 implementation plan 存在
        if [[ "$fname" == *-design.md ]]; then
            local impl_file="${plan_file%-design.md}.md"
            [[ -f "$impl_file" ]] && continue
        fi

        local file_status="$(awk '/^---$/{c++; next} c==1 && /^status:/{print $2; exit}' "$plan_file")"
        local file_project="$(awk '/^---$/{c++; next} c==1 && /^project:/{print $2; exit}' "$plan_file")"
        [[ -z "$file_status" ]] && file_status="backlog"

        local rel_path="${plan_file#$OBSIDIAN_PLANS_DIR/}"
        local title="${fname%.md}"
        # 清理標題：移除 -design 後綴
        title="${title%-design}"
        local link="[[${rel_path%.md}|${file_project}: ${title}]]"

        case "$file_status" in
            backlog)     backlog="${backlog}- [ ] ${link}\n" ;;
            not_started) not_started="${not_started}- [ ] ${link}\n" ;;
            in_progress) in_progress="${in_progress}- [ ] ${link}\n" ;;
            done)        done_cards="${done_cards}- [x] ${link}\n" ;;
            archived)    ;;  # archived 不顯示在 Kanban，去 Dashboard 查看
        esac
    done

    cat > "$kanban_file" <<ENDOFKANBAN
---
kanban-plugin: basic
---

## Backlog

$(echo -e "${backlog:-}")
## Not Started

$(echo -e "${not_started:-}")
## In Progress

$(echo -e "${in_progress:-}")
## Done

$(echo -e "${done_cards:-}")
## Archived

%% kanban:settings
{"kanban-plugin":"basic","lane-width":250,"show-checkboxes":false}
%%
ENDOFKANBAN
}
