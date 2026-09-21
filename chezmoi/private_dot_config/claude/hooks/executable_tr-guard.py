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
import shlex
import sys

sys.path.insert(0, os.path.expanduser(os.environ.get(
    "TOOL_REDUCE_LIB", "~/.config/claude/tool-reduce")))
import store

# 這段跑在每一次 Bash／Read 呼叫之前（PreToolUse，沒有 Task 6 那道
# SIZE_GATE 先篩過），比 PostToolUse hook 更熱，所以候選路徑數量跟掃描的
# blob 大小都要封頂 —— 跟 executable_tool-reduce.py 的 fix-round 3 同一招。
_MAX_CHECK_BLOB_CHARS = 64 * 1024
_MAX_CHECK_TOKENS = 32


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


def _store_root_real():
    """存放區根目錄的正規化絕對路徑，每次呼叫都重算，不在模組載入當下
    凍結成常數 —— 跟 executable_tool-reduce.py 的 _store_root_real 同一招
    （見該檔案該函式的 docstring）：store.Store 每次建構都重新讀一次
    TOOL_REDUCE_HOME，這裡凍結成模組常數的話，同一個行程裡先讀早、後設
    環境變數的呼叫端一樣看不到新值。realpath 疊在 store.root() 的 abspath
    結果外面，處理 symlink，跟 store.load_chunk 驗證 handle 同一招。"""
    return os.path.realpath(store.root())


def _path_tokens(blob):
    """跟 executable_tool-reduce.py 的同名函式是同一個演算法：只認「開頭
    長得像路徑」的 token（`/`、`~/`、`./`、`../`），不是任何含 `/` 的片段
    都算——存放區根目錄本身一定是絕對路徑，一個真的指到存放區的直接讀取
    一定會用絕對路徑或 `~` 開頭的路徑，不可能是日期、分數或程式碼片段
    （見 Task 6 fix-round 3）。這個形狀過濾器的代價：完全沒有路徑前綴的
    相對寫法（例如指令直接寫 `cat sess/x.1.txt`，不是
    `cat ./sess/x.1.txt`）不會被當成候選——跟 Task 6 接受的取捨一樣。"""
    for raw in blob.split():
        tok = raw.strip("\"',{}[]:;")
        if tok.startswith(("/", "~/", "./", "../")):
            yield tok


def _handle_under_store_root(tok, store_root_real):
    """token 展開、正規化後是不是真的落在目前設定的存放區根目錄底下——
    跟 store.load_chunk 驗證 handle、Task 6 的 _reads_store_file 同一招：
    用路徑正規化 + containment 比對，不是死認目錄字面上叫不叫
    "tool-reduce"。這樣 TOOL_REDUCE_HOME 指到任何名稱的目錄都認得出來
    （fix-round 1 抓到：字面比對版本在存放區目錄名稱不叫 tool-reduce 時
    會整批漏記，而這支是「繞過 tr-restore 直接讀存放區檔案」這條路徑
    唯一的守衛，漏記是永久漏記），也天生不會被 `mytool-reduce/`、
    `footool-reduce/` 這類恰好同字尾的無關目錄名稱騙到——它們正規化後
    不會落在真正設定的存放區底下，不需要再另外寫一條字詞邊界規則去擋。

    檔名不是 `<handle>.txt`（例如落在存放區底下的其他檔案、或
    decisions.jsonl 這類紀錄檔）就回傳 None，不硬湊一個 handle 出來。"""
    real = os.path.realpath(os.path.expanduser(tok))
    if real != store_root_real and not real.startswith(store_root_real + os.sep):
        return None
    base = os.path.basename(real)
    if not base.endswith(".txt"):
        return None
    handle = base[:-len(".txt")]
    if not store.HANDLE_RE.match(handle):
        return None
    return handle


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
    store_root_real = _store_root_real()
    blob = json.dumps(ti, ensure_ascii=False)[:_MAX_CHECK_BLOB_CHARS]
    handles = []
    for i, tok in enumerate(_path_tokens(blob)):
        if i >= _MAX_CHECK_TOKENS:
            break
        h = _handle_under_store_root(tok, store_root_real)
        if h is not None:
            handles.append(h)
    return list(dict.fromkeys(handles))


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
