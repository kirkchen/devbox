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
