#!/usr/bin/env python3
"""PostToolUse: 用 Jev 判斷 tool output 的哪些段落是冗餘的，換成可還原的墓碑。

判斷邏輯全部在 ~/.config/claude/tool-reduce/ 的模組裡，eval 與 tune 匯入同一份，
避免線上跟離線漂移。這支只負責：取輸入 -> 切段 -> 問 Jev -> 套 policy -> 寫存放區
-> 輸出 updatedToolOutput -> 記紀錄。

任何異常都 fail-open（不輸出，原輸出照常送給模型）。
模式由 TOOL_REDUCE_MODE 決定：off（預設）| shadow | full
"""
import hashlib
import json
import os
import shlex
import sys

TR = os.path.expanduser(os.environ.get(
    "TOOL_REDUCE_LIB", "~/.config/claude/tool-reduce"))
sys.path.insert(0, TR)

import chunker
import descriptor
import drop_policy
import jev
import shapes
import store

SIZE_GATE = int(os.environ.get("TOOL_REDUCE_SIZE_GATE", "2000"))
TIMEOUT = float(os.environ.get("TOOL_REDUCE_TIMEOUT", "2.5"))
MAX_CHUNKS = int(os.environ.get("TOOL_REDUCE_MAX_CHUNKS", "16"))


def _store_root_real():
    """Session 存放區根目錄的正規化絕對路徑，每次呼叫都重算，不在模組
    載入當下就凍結成常數。

    跟 store.load_chunk 驗證 handle 用的是同一招（realpath +
    startswith 前綴），不是字串比對 —— 這樣才能正確處理 `..`、結尾斜線、
    symlink，不用為每種寫法各寫一條特例（見 fix-round 2：字串比對版本
    抓不到 `..` 正規化後落進存放區的路徑）。

    根目錄本身走 store.root()（TOOL_REDUCE_HOME 優先，否則
    store.ROOT_DEFAULT），不是重新硬寫一份只認 ROOT_DEFAULT 的公式 ——
    先前這裡直接寫死 store.ROOT_DEFAULT，完全沒看 TOOL_REDUCE_HOME，
    設了這個環境變數會搬動 store.Store 實際落地的目錄、卻搬不動這裡的
    比對基準，變成「存放區搬家了，這道還原偵測閘門沒跟著搬」（task-7
    review 抓到）。改成每次呼叫都重新解析，才能跟 store.Store 每次建構
    都重新讀一次環境變數的行為對齊 —— 凍結成模組層級常數的話，同一個
    行程裡先讀早、後設 TOOL_REDUCE_HOME 的呼叫端（例如測試在 setUp 裡
    設環境變數）一樣看不到新值。"""
    return os.path.realpath(store.root())

# _reads_store_file 的三道防線，見 fix-round 3：這段跑在每個過了 size
# gate 的 tool result 前面、Jev 的 2.5s 預算之前，realpath 是系統呼叫，
# 沒有上限的話一個帶大量像路徑片段的 Edit（例如 old_string/new_string
# 裡有幾萬個帶斜線的片段）會讓整個 session 卡住好幾秒。量測：30,000 個
# 帶斜線 token、每個都真的做 realpath，要 12 秒；套上這三道防線後歸零。
_MAX_STORE_CHECK_BLOB_CHARS = 64 * 1024   # 掃描前先砍斷，切 token 這步本身就不會被巨大酬載拖慢
_MAX_STORE_CHECK_TOKENS = 32              # 最多真的呼叫 realpath 幾次


def _flatten_shell_tokens(text, _depth=0):
    """shlex.split 只切最外層的殼層語法。`sh -c '...'`／`bash -c "..."`
    這種寫法，裡面那個被單一引號包起來的字串本身還是一整條指令，
    shlex.split 只會把它當成『一個 token』（保留內部空白），不會再往下切。
    對每個切出來、自己還帶空白的 token 再遞迴切一次，才看得到真正呼叫的
    是什麼程式；封頂三層，避免異常輸入（例如刻意塞一堆空白的字串）
    造成無謂的遞迴。shlex.split 遇到括號不對稱的引號會丟 ValueError，
    退回單純按空白切。"""
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


def _invokes_restore_cli(ev):
    """tr-restore 是不是以獨立殼層 token 的身分被呼叫（用 basename 比對
    整個 token，不是子字串／不是 regex word-boundary —— `\\btr-restore\\b`
    這種寫法在 `-` 兩側都算邊界，`tr-restore-helper` 跟
    `my-tr-restore-notes.md` 都會誤判，見 fix-round 2）。涵蓋直接呼叫、
    透過 `sh -c` 包一層、或帶完整路徑呼叫。"""
    ti = ev.get("tool_input")
    command = ti.get("command") if isinstance(ti, dict) else None
    if not isinstance(command, str) or not command:
        return False
    return any(os.path.basename(t) == "tr-restore"
               for t in _flatten_shell_tokens(command))


def _path_tokens(blob):
    """從 tool_input 的 JSON 字串裡挑出看起來像路徑的片段，去掉包住它的
    引號跟常見 JSON 標點。不管是哪個工具、欄位名稱叫什麼都適用（Bash 的
    command、Read 的 file_path、其他工具的任何欄位），不用為每個工具的
    tool_input 形狀各寫一條特例。

    只認「開頭長得像路徑」的 token（`/`、`~/`、`./`、`../`），不是任何
    含 `/` 的片段都算 —— 存放區根目錄本身是絕對路徑，一個真的指到存放區
    的還原呼叫一定會用絕對路徑或 `~` 開頭的路徑，不可能是日期
    （`2024/01/15`）、分數（`3/4`）或程式碼片段裡的 `a/b` 這種寫法（見
    fix-round 3：舊版只看「含不含 `/`」，這些統統會被當成路徑候選，白白
    浪費一次 realpath 呼叫）。"""
    for raw in blob.split():
        tok = raw.strip("\"',{}[]:;")
        if tok.startswith(("/", "~/", "./", "../")):
            yield tok


def _reads_store_file(ev):
    """把 tool_input 裡看起來像路徑的片段展開、正規化（expanduser +
    realpath），測是不是等於或落在 session 存放區底下 —— 跟
    store.load_chunk 驗證 handle 同一招，天生就處理得了 `..`、結尾斜線、
    symlink（realpath 對不存在的路徑一樣會正規化，不需要檔案真的存在）。

    三道防線界住成本（見 fix-round 3，量測見模組開頭常數旁的註解）：
    先把要掃描的 blob 砍到 _MAX_STORE_CHECK_BLOB_CHARS，讓切 token 這步
    本身不會被巨大酬載（例如帶超大 old_string/new_string 的 Edit）拖慢；
    候選路徑用 _path_tokens 先做形狀過濾；真正呼叫 realpath（syscall）
    的次數封頂在 _MAX_STORE_CHECK_TOKENS，一比對到就立刻回傳，不用等
    掃完。

    取捨：如果存放區路徑出現在被砍斷的 blob 之後、或第 32 個以後的候選
    路徑，這次呼叫會被漏掉，內容可能被再過濾一次。可接受，因為墓碑標記
    要 agent 打的是 `tr-restore <handle>`，走 _invokes_restore_cli 那條
    完全不碰檔案系統的路徑；真的直接 `cat` 存放區檔案的指令，路徑通常
    就在指令最前面，遠遠排不到第 32 個。"""
    store_root_real = _store_root_real()
    store_root_prefix = store_root_real + os.sep
    blob = json.dumps(ev.get("tool_input") or {},
                      ensure_ascii=False)[:_MAX_STORE_CHECK_BLOB_CHARS]
    for i, tok in enumerate(_path_tokens(blob)):
        if i >= _MAX_STORE_CHECK_TOKENS:
            break
        real = os.path.realpath(os.path.expanduser(tok))
        if real == store_root_real or real.startswith(store_root_prefix):
            return True
    return False


def is_restore_call(ev):
    """還原讀進來的內容不能再被過濾，否則會繞圈。只比對兩種精確情況：
    呼叫 tr-restore 還原指令本身（當獨立殼層 token），或任何工具的輸入裡
    有路徑正規化後落在 session 存放區底下（含 Read 直接讀墓碑對應檔案）。
    fail-safe：解析過程只要丟例外就當作還原呼叫、整份放行不過濾 ——
    誤放行頂多多送一次未過濾的原始輸出，誤過濾則會把 agent 剛還原回來
    的內容再刪一次，代價不對稱。"""
    try:
        if _invokes_restore_cli(ev):
            return True
        return _reads_store_file(ev)
    except Exception:
        return True


def has_persisted_output(tool_response):
    """帶 persistedOutputPath 的結果已經有自己的離線還原路徑；改寫 stdout 會讓
    persistedOutputSize 描述一份已經不存在的文字，整份放行不過濾。"""
    return isinstance(tool_response, dict) and "persistedOutputPath" in tool_response


def reduce_payload(ev, asker=None, st=None):
    """回傳要印出去的 hook 輸出；不該改就回 None。"""
    if os.environ.get("TOOL_REDUCE_MODE") not in ("shadow", "full"):
        return None
    tool = ev.get("tool_name") or ""
    tool_response = ev.get("tool_response")
    if has_persisted_output(tool_response):
        return None
    text = shapes.extract(tool, tool_response)
    if not text or len(text) < SIZE_GATE or is_restore_call(ev):
        return None

    chunks, kind = chunker.chunk(text, max_chunks=MAX_CHUNKS)
    if len(chunks) < drop_policy.DEFAULTS["min_chunks"]:
        return None

    ask = asker or jev.ask
    try:
        answers = ask({"tool": tool,
                       "tool_input": ev.get("tool_input") or {},
                       "chunks": {f"c{i}": c for i, c in enumerate(chunks)}},
                      jev.build_questions(len(chunks)), timeout=TIMEOUT)
    except Exception:
        return None

    scores = jev.scores(answers, len(chunks))
    thresholds = drop_policy.load()
    drop = drop_policy.decide(scores, [len(c) for c in chunks], thresholds)
    if not any(drop):
        return None

    session = ev.get("session_id") or "unknown"
    st = st or store.Store(session)
    # os.urandom 混入隨機位元組：同 session、同 tool、文字前 200 字元、
    # 同一毫秒時戳過去會雜湊出同一個 decision_id，第二次呼叫的 save_chunk
    # 會悄悄覆寫第一次已經現身在模型輸出裡的墓碑對應檔案，且不丟例外
    # （見 fix-round 1 minor）。這個 id 不需要可重現，只需要不撞名。
    decision_id = hashlib.sha256(
        (session + tool + text[:200] + str(store.now_ms())).encode() + os.urandom(4)
    ).hexdigest()[:10]

    out_parts, rec_chunks, saved = [], [], 0
    for i, (c, d) in enumerate(zip(chunks, drop)):
        others = [x for j, x in enumerate(chunks) if j != i]
        toks = store.scrub(descriptor.distinctive(c, others))
        rec_chunks.append({"i": i, "chars": len(c), "scores": scores[i],
                           "dropped": bool(d), "distinctive": toks})
        if not d:
            out_parts.append(c)
            continue
        handle = f"{decision_id}.{i}"
        st.save_chunk(handle, c)
        marker = descriptor.make(c, handle)
        out_parts.append(("\n" if not c.startswith("\n") else "") + marker + "\n")
        saved += len(c) - len(marker)
        st.record_tombstone({"handle": handle, "decision_id": decision_id,
                             "chars": len(c), "descriptor": marker})

    st.record_decision({"decision_id": decision_id, "session_id": session,
                        "tool": tool, "kind": kind,
                        "chars_before": len(text), "chars_after": sum(map(len, out_parts)),
                        "chars_saved": saved, "thresholds": thresholds,
                        "chunks": rec_chunks})

    if os.environ.get("TOOL_REDUCE_MODE") == "shadow":
        return None
    return {"hookSpecificOutput": {
        "hookEventName": "PostToolUse",
        "updatedToolOutput": shapes.rewrite(tool, tool_response,
                                            "".join(out_parts))}}


def main():
    jev.load_env(os.path.expanduser("~/.config/claude/typesafe.env"))
    # 整條流程（含 print）都包在同一個 try 裡：json.loads 可能因輸入不是
    # JSON 而丟例外，reduce_payload 內部已經 fail-open 但呼叫端仍可能因
    # 未預期輸入而丟例外，print 本身也可能丟例外 —— 原始輸出裡一個沒配對
    # 的 UTF-16 surrogate（json.loads 不驗證 surrogate pair 合不合法）
    # 經過 json.dumps(ensure_ascii=False) 後，會在 print 把字串編碼成
    # stdout 的 UTF-8 位元組時讓 UnicodeEncodeError 逸出，之前這段沒被
    # try 包住，會讓整個 hook 非零結束、印出 traceback，違反「不輸出、
    # exit 0」的 fail-open 契約（見 fix-round 1 Important 2）。
    try:
        ev = json.loads(sys.stdin.read())
        out = reduce_payload(ev)
        if out:
            print(json.dumps(out, ensure_ascii=False))
    except Exception:
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
