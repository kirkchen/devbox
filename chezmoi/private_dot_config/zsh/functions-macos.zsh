# === macOS-specific Functions ===

# code: 用 VS Code 開啟檔案或目錄
# Usage: code [path]
function code {
    if [[ $# = 0 ]]; then
        open -a "Visual Studio Code"
    else
        local argPath="$1"
        [[ $1 = /* ]] && argPath="$1" || argPath="$PWD/${1#./}"
        open -a "Visual Studio Code" "$argPath"
    fi
}
