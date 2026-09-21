#!/usr/bin/env python3
"""PreToolUse: agent 有時會直接 cat／Read 存放區的檔案，而不是照墓碑標記
上的指示跑 tr-restore。兩條路都要記，還原率才量得準 —— 那份 restores.jsonl
是 Task 9／10 評估的 ground truth，漏記等於漏掉一個確認的誤刪訊號。

這支永遠不阻擋任何事，只負責觀察、記錄。fail-open：任何例外都吞掉，
以 exit 0、不印任何東西收尾——PreToolUse hook 擋下它正在看的那次呼叫，
後果比漏記一次還原嚴重得多。
"""
import json
import os
import re
import shlex
import sys

sys.path.insert(0, os.path.expanduser(os.environ.get(
    "TOOL_REDUCE_LIB", "~/.config/claude/tool-reduce")))
import store

# "tool-reduce" 前面不能是英數字、底線或連字號 —— 否則 `mytool-reduce/`、
# `footool-reduce/`、`nottool-reduce/` 這種目錄名稱只是恰好以 tool-reduce
# 結尾／夾帶這個子字串，會被誤判成「讀了存放區的檔案」，明明跟這支 hook
# 認的存放區完全無關（同一類 fix-round 2 教訓：純子字串比對抓不準，見
# executable_tool-reduce.py 的 _invokes_restore_cli 用 basename 整詞比對
# 取代字詞邊界 regex 的理由）。用否定回顧斷言而不是要求前面一定是 `/`
# 或字串開頭，是因為合法的相對路徑（例如指令直接寫
# `cat tool-reduce/sess/x.1.txt`）前面是空白字元，不該被這道防線一併擋掉
# —— 只有「tool-reduce 是某個更長識別字的字尾」這一種情況才要擋。
HANDLE_IN_PATH = re.compile(
    r"(?<![A-Za-z0-9_-])tool-reduce/[^/\s\"']+/([A-Za-z0-9]+\.\d+)\.txt")


def _flatten_shell_tokens(text, _depth=0):
    """跟 executable_tool-reduce.py 的 _flatten_shell_tokens 是同一個演算法
    （`sh -c '...'` 這種巢狀殼層要再切一層才看得到真正呼叫的是什麼），
    刻意在這裡自己留一份而不是 import 那支 hook 模組 —— 那支模組載入時
    會連帶 import chunker／descriptor／drop_policy／jev，這支 PreToolUse
    hook 只需要判斷「這是不是一次 tr-restore 呼叫」，沒必要為此拖進一整條
    Jev 問答鏈的相依（也不該讓這支的 fail-open 保證去依賴另一支模組載入
    成不成功）。函式本體維持跟原版一致，封頂三層遞迴避免異常輸入造成
    無謂遞迴。"""
    try:
        parts = shlex.split(text)
    except ValueError:
        parts = text.split()
    if _depth >= 3:
        return parts
    out = []
    for p in parts:
        if p != text and any(ch.isspace() for ch in p):
            out.extend(_flatten_shell_tokens(p, _depth + 1))
        else:
            out.append(p)
    return out


def _invokes_restore_cli(command):
    """command 是不是以獨立殼層 token 的身分呼叫了 tr-restore（用 basename
    整詞比對，不是子字串——`grep tr-restore-helper` 或提到
    `my-tr-restore-notes.md` 都不該算）。涵蓋直接呼叫、`sh -c` 包一層、
    或帶完整路徑呼叫。"""
    if not isinstance(command, str) or not command:
        return False
    return any(os.path.basename(t) == "tr-restore"
               for t in _flatten_shell_tokens(command))


def detect(ev):
    """回傳 tool_input 裡出現的 handle。

    走 tr-restore 指令本身的不算——tr-restore 自己會記一筆
    `via: tr-restore`，這支只補「agent 繞過 tr-restore、直接讀存放區檔案」
    的那一半，兩邊各記各的、不重疊，還原率才不會被灌水。只看 Bash 的
    `command` 欄位判斷是不是在呼叫 tr-restore——這支 CLI 目前只會透過
    Bash 被叫動，不必為其他工具的 tool_input 形狀各寫一條特例。"""
    ti = ev.get("tool_input") or {}
    command = ti.get("command") if isinstance(ti, dict) else None
    if isinstance(command, str) and _invokes_restore_cli(command):
        return []
    blob = json.dumps(ti, ensure_ascii=False)
    return list(dict.fromkeys(HANDLE_IN_PATH.findall(blob)))


def main():
    try:
        ev = json.loads(sys.stdin.read())
        handles = detect(ev)
        if handles:
            st = store.Store(ev.get("session_id") or "unknown", root=store.root())
            for h in handles:
                st.record_restore({"handle": h, "via": "direct-read",
                                   "tool": ev.get("tool_name")})
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
