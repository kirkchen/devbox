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
import re
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


# 還原指令本身，當一個獨立字詞比對，不是任何子字串都算（否則
# "echo tr-restored" 這種提都不算真的呼叫的字串也會誤判）。
_RESTORE_CMD_RE = re.compile(r"\btr-restore\b")

# Session 存放區根目錄，兩種寫法都比對：字面上的 "~/..."（使用者在指令裡
# 通常這樣打）與展開後的絕對路徑（某些工具已經把路徑解析過）。這個路徑
# 跟原始碼目錄（~/.config/claude/tool-reduce、chezmoi/.../tool-reduce）
# 完全不同，用它當前綴不會誤中提到原始碼路徑的指令。
_STORE_ROOT_TOKENS = tuple(
    root.rstrip("/") + "/"
    for root in {store.ROOT_DEFAULT, os.path.abspath(os.path.expanduser(store.ROOT_DEFAULT))}
)


def is_restore_call(ev):
    """還原讀進來的內容不能再被過濾，否則會繞圈。只比對兩種精確情況：
    呼叫 tr-restore 還原指令本身，或直接讀 session 存放區底下的檔案 ——
    不對整個 tool_input 做鬆散子字串比對（那樣連 `ls tool-reduce/` 這種
    只是提到原始碼路徑的呼叫都會被誤判成還原呼叫，見 fix-round 1）。"""
    blob = json.dumps(ev.get("tool_input") or {}, ensure_ascii=False)
    if _RESTORE_CMD_RE.search(blob):
        return True
    return any(tok in blob for tok in _STORE_ROOT_TOKENS)


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
