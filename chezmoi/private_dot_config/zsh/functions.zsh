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
