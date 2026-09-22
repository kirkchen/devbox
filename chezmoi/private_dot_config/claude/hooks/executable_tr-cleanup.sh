#!/usr/bin/env bash
# SessionEnd: 清掉這個 session 的段落原文。紀錄留在 archive/ 不動。
#
# 段落原文只活在 session 生命週期內；tool output 可能含密鑰，不跨 session
# 保留。封存的紀錄（decisions/tombstones/restores 三份 jsonl）在 archive/
# 底下，只存紀錄不存原文，這支絕不動它。
#
# 安全前提：只清掉「正規化後真的落在存放區根目錄底下、且不是根目錄本身、
# 也不是 archive/」的那一個目錄——跟 store.py／executable_tool-reduce.py／
# executable_tr-guard.py 判斷「一個路徑是不是落在存放區底下」同一招
# （os.path.realpath + 前綴比對），不是對還沒展開 `..` 的字面字串做 glob
# 前綴比對。`case "$DIR" in "$ROOT"/*)` 這種寫法擋不住 session id 帶
# `../../etc` 之類的字串：字面上 "$ROOT/../../etc" 就是以 "$ROOT/" 開頭，
# glob 一樣會匹配，但那個路徑正規化之後其實在存放區外面。macOS 內建的
# /bin/realpath 沒有 GNU coreutils 才有的 -m／-e 旗標，所以正規化這一步
# 交給 python3 做，跟其餘模組共用同一份演算法，不在 bash 裡另外重寫一份
# 容易漏邊界情況的版本。
set -euo pipefail

ROOT="${TOOL_REDUCE_HOME:-$HOME/.claude/tool-reduce}"

# 一次呼叫 python3：讀 SessionEnd 送進這支腳本 stdin 的 JSON 取
# session_id，正規化 ROOT 跟 "$ROOT/$SID"，判斷是不是安全可刪。安全就印
# 兩行（root_real、dir_real）給下面的 bash 用；任何一關不過（stdin 不是
# 合法 JSON、session_id 缺漏／不是字串／空字串、ROOT 不存在、正規化後的
# 目錄不在 ROOT 底下、正規化後等於 ROOT 本身、或正規化後的 basename 是
# archive）都不印任何東西，讓 python3 以 exit 0 收尾。
#
# bash 這邊只看「有沒有印出兩行」來決定要不要刪，不看 python3 的結束碼
# ——`|| true` 吞掉 python3 not found／heredoc 以外的任何非零結束，這樣
# 環境異常不會被 `set -e` 放大成整支清理腳本非零結束，讓 SessionEnd 的
# 呼叫端誤以為清理失敗。
#
# 用 -c 而不是 `python3 - <<'PY'`：後者會讓 heredoc 內容變成 python3 的
# 程式原始碼本身（因為 "python3 -" 是「從 stdin 讀程式」），這支腳本自己
# 的 stdin（SessionEnd 送來的 JSON payload）反而被吃光，json.load(stdin)
# 在程式裡只會讀到 EOF。用 -c 把程式碼放進命令列參數，stdin 才會原封不動
# 傳給 python3 行程內的 sys.stdin。
PLAN="$(ROOT_ENV="$ROOT" python3 -c '
import json, os, sys

root = os.environ.get("ROOT_ENV", "")
try:
    payload = json.load(sys.stdin)
except Exception:
    payload = {}
sid = payload.get("session_id") if isinstance(payload, dict) else None
if not isinstance(sid, str) or not sid:
    sys.exit(0)

root_real = os.path.realpath(os.path.expanduser(root))
if not os.path.isdir(root_real):
    sys.exit(0)

dir_real = os.path.realpath(os.path.join(root_real, sid))
if dir_real != root_real and not dir_real.startswith(root_real + os.sep):
    sys.exit(0)          # session id 正規化後跑到存放區外面（例如帶 `..`）
if dir_real == root_real:
    sys.exit(0)          # session id 正規化後等於根目錄本身
if os.path.basename(dir_real) == "archive":
    sys.exit(0)          # 絕不清封存區

print(root_real)
print(dir_real)
' 2>/dev/null)" || true

[[ -n "$PLAN" ]] || exit 0
ROOT_REAL="$(sed -n '1p' <<<"$PLAN")"
DIR_REAL="$(sed -n '2p' <<<"$PLAN")"
[[ -n "$ROOT_REAL" && -n "$DIR_REAL" ]] || exit 0

if [[ -d "$DIR_REAL" ]]; then
  rm -rf -- "$DIR_REAL"
fi

# 保險：超過 7 天的殘留 session 目錄一併清掉。-maxdepth/-mindepth 1 只列
# ROOT_REAL 底下的直接子項，不遞迴進任何子目錄去找；明確排除 archive/；
# -type d 只認真正的目錄——find 預設不跟隨符號連結判斷型別（沒有 -L），
# 一個 symlink 的型別是 l 不是 d，天生被排除。就算存放區底下混進一個指到
# 存放區外面的符號連結，也不會被這條規則選中，更不會把 rm -rf 的目標帶出
# ROOT_REAL。
find "$ROOT_REAL" -maxdepth 1 -mindepth 1 -type d ! -name archive -mtime +7 \
  -exec rm -rf -- {} + 2>/dev/null || true

exit 0
