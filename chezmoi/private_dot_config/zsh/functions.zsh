# === Cross-platform Functions ===

# now: 輸出 UTC 時間戳記 (YYYYMMDDHHmmss)
function now {
    echo $(date -u '+%Y%m%d%H%M%S')
}

# fixup: 建立 fixup commit 並自動 rebase
# Usage: fixup <commit-message-to-fix>
function fixup {
    if [[ $# = 0 ]]; then
        echo "Usage: fixup <commit-message-to-fix>"
        echo "Creates a fixup commit and auto-rebases"
        return 1
    fi

    echo "Committing fixup..."
    git commit -m "fixup! ${1}" > /dev/null

    echo "Attempting to stash working directory..."
    local stashResult=$(git stash)

    echo "Rebasing on top of ${1}"
    git rebase -i "${1}^" --autosquash

    if [[ "$stashResult" != "No local changes to save" ]]; then
        echo "Popping from stash"
        git stash pop > /dev/null
    fi
}

# kt: K8s tunnel 管理 (via Cloudflare)
# Usage: kt [start|stop|status]
function kt {
    local proc="cloudflared access tcp.*k8s.kirkchen.dev"
    case "${1:-start}" in
        start)
            if pgrep -f "$proc" > /dev/null; then
                echo "✓ Already running (PID: $(pgrep -f "$proc"))"
            else
                cloudflared access tcp --hostname k8s.kirkchen.dev --url 127.0.0.1:16443 &
                echo "✓ Started (PID: $!)"
            fi ;;
        stop)
            pkill -f "$proc" && echo "✗ Stopped" || echo "Not running" ;;
        status)
            pgrep -f "$proc" > /dev/null \
                && echo "✓ Running (PID: $(pgrep -f "$proc"))" \
                || echo "✗ Not running" ;;
        *) echo "Usage: kt [start|stop|status]" ;;
    esac
}

# wt-init: 初始化 worktree 環境隔離設定
# Usage: wt-init
# 在當前目錄產生 .envrc + .worktreeinclude，讓 Claude Code worktree 自動獲得環境隔離
function wt-init {
    if [ ! -d .git ] && ! git rev-parse --git-dir &>/dev/null; then
        echo "Error: not in a git repository"
        return 1
    fi

    local created=()

    # ── .envrc ──
    if [ -f .envrc ]; then
        echo "⚠ .envrc already exists, skipping"
    else
        cat > .envrc << 'ENVRC'
# ── symlink 主 repo 的 .env 檔案 ──
MAIN_REPO=$(git worktree list --porcelain | head -1 | sed 's/worktree //')
for f in .env .env.local .env.development .env.development.local; do
  if [ -f "${MAIN_REPO}/${f}" ] && [ ! -e "${f}" ]; then
    ln -sf "${MAIN_REPO}/${f}" "${f}"
  fi
done

# ── 共用設定（透過 symlink 讀取）──
dotenv_if_exists .env
dotenv_if_exists .env.local
dotenv_if_exists .env.development
dotenv_if_exists .env.development.local

# ── worktree 隔離值（如果有外部工具產生，最高優先）──
dotenv_if_exists .env.worktree

# ── 工具環境（偵測到對應 lockfile 才啟用）──
if [ -f pyproject.toml ]; then
  export UV_PROJECT_ENVIRONMENT="$PWD/.venv"
  PATH_add .venv/bin
fi
if [ -d node_modules ] || [ -f pnpm-lock.yaml ]; then
  PATH_add node_modules/.bin
fi
ENVRC
        created+=(".envrc")
    fi

    # ── .worktreeinclude ──
    if [ -f .worktreeinclude ]; then
        echo "⚠ .worktreeinclude already exists, skipping"
    else
        cat > .worktreeinclude << 'WTI'
# direnv 設定（必須複製，direnv 只讀當前目錄的 .envrc）
.envrc

# Claude Code 本地設定
**/.claude/settings.local.json
CLAUDE.local.md
WTI
        created+=(".worktreeinclude")
    fi

    # ── 更新 .gitignore ──
    local gi_additions=()
    for pattern in ".direnv/" ".env.worktree"; do
        if [ -f .gitignore ] && grep -qF "$pattern" .gitignore; then
            continue
        fi
        gi_additions+=("$pattern")
    done
    if [ ${#gi_additions[@]} -gt 0 ]; then
        printf '\n# Worktree isolation\n' >> .gitignore
        printf '%s\n' "${gi_additions[@]}" >> .gitignore
        created+=(".gitignore (updated)")
    fi

    # ── direnv allow ──
    if [ -f .envrc ] && command -v direnv &>/dev/null; then
        direnv allow .
    fi

    if [ ${#created[@]} -gt 0 ]; then
        echo "✓ Created: ${created[*]}"
        echo "  Worktree isolation is now enabled for this project."
    else
        echo "Nothing to do — all files already exist."
    fi
}
