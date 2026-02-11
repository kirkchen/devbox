#!/bin/bash
# Zellij Sessionizer - fzf-based session/tab switcher
# Triggered by Ctrl+f inside Zellij

CURRENT_SESSION="$ZELLIJ_SESSION_NAME"

if [[ -z "$CURRENT_SESSION" ]]; then
    echo "Error: Not inside a Zellij session." >&2
    read -n1
    exit 1
fi

# --- Session summary lookup ---
# 從 Claude Code 的 sessions-index.json 取得各 session 的任務摘要

_get_summaries() {
    command -v python3 &>/dev/null || return
    python3 - "$@" <<'PYEOF'
import json, os, sys, re, glob

home = os.path.expanduser("~")
code_dirs = [os.path.join(home, "Code"), os.path.join(home, "Code", "Personal")]
claude_projects = os.path.join(home, ".claude", "projects")

def truncate(s, n=35):
    return s[:n-1] + "…" if len(s) > n else s

def find_project_dir(project_name):
    for base in code_dirs:
        candidate = os.path.join(base, project_name)
        if os.path.isdir(candidate):
            return candidate
    return None

def encode_path(path):
    """編碼為 Claude Code 路徑格式（/ 和 . 替換為 -）"""
    return "-" + re.sub(r'[/.]', '-', path).lstrip('-')

def from_sessions_index(claude_dir, branch_slug):
    """從 sessions-index.json 取得 summary"""
    index_file = os.path.join(claude_dir, "sessions-index.json")
    if not os.path.isfile(index_file):
        return None
    try:
        with open(index_file) as f:
            data = json.load(f)
    except Exception:
        return None

    entries = data.get("entries", [])
    if not entries:
        return None

    # 嘗試匹配 gitBranch
    if branch_slug:
        matched = None
        for e in entries:
            gb = e.get("gitBranch", "").replace("/", "-")
            if gb == branch_slug:
                if not matched or e.get("modified", "") > matched.get("modified", ""):
                    matched = e
        if matched:
            return matched.get("summary") or matched.get("firstPrompt")

    # Fallback: 最近的 entry
    entries.sort(key=lambda e: e.get("modified", ""), reverse=True)
    return entries[0].get("summary") or entries[0].get("firstPrompt")

def from_jsonl_files(claude_dir, branch_slug):
    """Fallback: 從 JSONL 檔案取得最近 session 的第一個 user message"""
    jsonl_files = glob.glob(os.path.join(claude_dir, "*.jsonl"))
    if not jsonl_files:
        return None

    # 按修改時間排序，取最近的
    jsonl_files.sort(key=lambda f: os.path.getmtime(f), reverse=True)

    # 嘗試前 3 個最近的檔案
    for jf in jsonl_files[:3]:
        try:
            with open(jf) as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    if d.get("type") != "user":
                        continue
                    if d.get("isMeta", False):
                        continue
                    # 檢查 branch 是否匹配
                    gb = d.get("gitBranch", "").replace("/", "-")
                    if branch_slug and gb and gb != branch_slug:
                        continue
                    msg = d.get("message", {})
                    content = msg.get("content", "")
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                content = item["text"]
                                break
                        else:
                            continue
                    if not isinstance(content, str) or not content.strip():
                        continue
                    # 跳過系統/指令訊息
                    if content.startswith("<") or content.startswith("Base directory"):
                        continue
                    return content.split("\n")[0]
        except Exception:
            continue
    return None

for session_name in sys.argv[1:]:
    parts = session_name.split(":")
    project_name = parts[0]
    branch_slug = parts[1] if len(parts) > 1 else ""
    # 去除 :exec 後綴
    if len(parts) > 2 and parts[-1] == "exec":
        branch_slug = parts[1]

    project_dir = find_project_dir(project_name)
    if not project_dir:
        continue

    claude_dir = os.path.join(claude_projects, encode_path(project_dir))
    if not os.path.isdir(claude_dir):
        continue

    # 優先用 sessions-index.json，fallback 到 JSONL
    summary = from_sessions_index(claude_dir, branch_slug)
    if not summary:
        summary = from_jsonl_files(claude_dir, branch_slug)

    if summary:
        print(f"{session_name}\t{truncate(summary)}")
PYEOF
}

# --- Collect candidates ---

TAB=$'\t'
candidates=""

# 1) Current session tabs
current_tabs="$(zellij action query-tab-names 2>/dev/null || true)"
if [[ -n "$current_tabs" ]]; then
    while IFS= read -r tab; do
        [[ -z "$tab" ]] && continue
        candidates+="${candidates:+$'\n'}"
        candidates+="* ${CURRENT_SESSION}${TAB}tab${TAB}${tab}"
    done <<< "$current_tabs"
fi

# 2) Other sessions（帶 summary）
all_sessions="$(zellij list-sessions -ns 2>/dev/null || true)"
if [[ -n "$all_sessions" ]]; then
    # 收集非當前 session
    session_list=()
    while IFS= read -r session; do
        [[ -z "$session" ]] && continue
        [[ "$session" == "$CURRENT_SESSION" ]] && continue
        session_list+=("$session")
    done <<< "$all_sessions"

    if [[ ${#session_list[@]} -gt 0 ]]; then
        # 批次取得 summary，存為 "name\tsummary" 到暫存
        summary_data="$(_get_summaries "${session_list[@]}")"

        for session in "${session_list[@]}"; do
            # 從 summary_data 中查找對應的 summary
            local_summary=""
            if [[ -n "$summary_data" ]]; then
                local_summary="$(echo "$summary_data" | awk -F'\t' -v name="$session" '$1 == name { print $2; exit }')"
            fi
            display="+ ${session}"
            if [[ -n "$local_summary" ]]; then
                display="+ ${session}  ${local_summary}"
            fi
            candidates+="${candidates:+$'\n'}"
            candidates+="${display}${TAB}session${TAB}${session}"
        done
    fi
fi

if [[ -z "$candidates" ]]; then
    echo "No other sessions or tabs found."
    read -n1
    exit 0
fi

# --- fzf selection ---
# Format: "DISPLAY\tTYPE\tTARGET"
# fzf shows only first field (display name with summary)

selected="$(echo "$candidates" | fzf --prompt="switch> " --no-sort --delimiter="${TAB}" --with-nth=1)" || exit 0

# --- Parse selection and act ---

type="$(echo "$selected" | cut -d"${TAB}" -f2)"
target="$(echo "$selected" | cut -d"${TAB}" -f3)"

case "$type" in
    tab)
        zellij action go-to-tab-name "$target"
        ;;
    session)
        echo "$target" > "/tmp/zcc-switch-session-${CURRENT_SESSION}"
        zellij action detach
        ;;
esac
