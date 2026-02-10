# === Zellij + Claude Code Session Management ===

# zcc: 啟動或附加到以 project/branch 命名的 Zellij + Claude Code session
#
# Usage:
#   zcc              # 一般模式（當前 repo + branch）
#   zcc -e           # 執行模式（--dangerously-skip-permissions）
#   zcc -d /path     # 指定工作目錄
#   zcc -h           # 說明

zcc() {
    if ! command -v zellij &>/dev/null; then
        echo "Error: zellij is not installed." >&2
        return 1
    fi

    if ! command -v claude &>/dev/null; then
        echo "Error: claude is not installed." >&2
        return 1
    fi

    if [[ -n "$ZELLIJ" ]]; then
        echo "Error: Already inside a Zellij session ($ZELLIJ_SESSION_NAME)." >&2
        echo "Use the session manager (Alt+o, w) to switch sessions." >&2
        return 1
    fi

    local exec_mode=false
    local target_dir=""

    while [[ $# -gt 0 ]]; do
        case "$1" in
            -e|--exec)
                exec_mode=true
                shift
                ;;
            -d|--dir)
                if [[ -z "$2" || "$2" == -* ]]; then
                    echo "Error: -d requires a directory path." >&2
                    return 1
                fi
                target_dir="$2"
                shift 2
                ;;
            -h|--help)
                echo "Usage: zcc [-e|--exec] [-d|--dir <path>] [-h|--help]"
                echo ""
                echo "Launch or attach to a Zellij + Claude Code session."
                echo "Sessions are named as 'project:branch' for easy identification."
                echo ""
                echo "Options:"
                echo "  -e, --exec    Execution mode (--dangerously-skip-permissions)"
                echo "  -d, --dir     Specify working directory (default: current dir)"
                echo "  -h, --help    Show this help message"
                echo ""
                echo "Inside Zellij:"
                echo "  Alt+e         Switch to exec mode (quit & restart as zcc -e)"
                echo "  Alt+o, w      Session manager (search & switch)"
                echo "  Alt+o, d      Detach from session"
                return 0
                ;;
            *)
                echo "Error: Unknown option '$1'. Use -h for help." >&2
                return 1
                ;;
        esac
    done

    if [[ -n "$target_dir" ]]; then
        if [[ ! -d "$target_dir" ]]; then
            echo "Error: Directory '$target_dir' does not exist." >&2
            return 1
        fi
        target_dir="$(cd "$target_dir" && pwd)"
    else
        target_dir="$(pwd)"
    fi

    local session_name
    session_name=$(_zcc_session_name "$target_dir")

    local layout="claude"
    if [[ "$exec_mode" == true ]]; then
        session_name="${session_name}:exec"
        layout="claude-exec"
    fi

    (cd "$target_dir" && zellij --layout "$layout" attach --create "$session_name")

    # Alt+e creates flag file and quits zellij; detect and restart as exec mode
    if [[ -f "/tmp/zcc-switch-exec-${session_name}" ]]; then
        rm -f "/tmp/zcc-switch-exec-${session_name}"
        if [[ "$exec_mode" != true ]]; then
            zcc -e -d "$target_dir"
        fi
    fi
}

# _zcc_session_name: 從 git repo + branch 組合 session 名稱
_zcc_session_name() {
    local dir="$1"
    local project_name branch_name

    if git -C "$dir" rev-parse --is-inside-work-tree &>/dev/null; then
        project_name="$(basename "$(git -C "$dir" rev-parse --show-toplevel)")"
        branch_name="$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null)"
        if [[ "$branch_name" == "HEAD" ]]; then
            branch_name="$(git -C "$dir" rev-parse --short HEAD 2>/dev/null)"
        fi
        # Zellij session names cannot contain '/'
        echo "${project_name}:${branch_name//\//-}"
    else
        echo "$(basename "$dir")"
    fi
}
