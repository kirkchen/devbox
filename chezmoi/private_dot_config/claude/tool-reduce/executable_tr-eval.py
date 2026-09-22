#!/usr/bin/env python3
"""Layer 1 eval：把每個墓碑分成三態。

  restored     墓碑被還原 —— 確定誤刪，但 agent 自己救回來了。精確訊號，
               直接看 restores.jsonl 記過沒有，沒有近似成分。
  silent_miss  沒被還原、但該段的獨有詞後來出現在 transcript —— 最嚴重
               的一類：agent 需要卻沒去拿。
  clean        兩者皆無 —— 大概是正確的裁切。

獨有詞比對是近似，兩個方向都會錯（巧合命中高估、沒複述特徵字低估），
所以 silent_miss 是趨勢指標，不是量測——拿它調門檻等於拿雜訊調門檻。
唯一無誤判的是 restored 那一列（還原是精確的遙測事件），也因此 restored
判定永遠贏過詞比對（同一個墓碑兩者都成立時，算 restored，不是
silent_miss）。

decisions.jsonl／restores.jsonl 都是 store._append 盡力而為寫出來的檔案
（見 store.py），跟 tr-stats 讀的是同一批、擔的是同一種風險：任一份沒寫
成功、被截斷，都不該讓這支工具吐 traceback 或印出看起來很有把握、其實
是漏算的數字。讀檔（read_jsonl）跟這裡的形狀防呆都跟 tr-stats 共用同一套
規則、同一個略過計數契約（task-8 定的規則，task-9 原樣繼承，讀檔那層
直接共用 jsonl_io.read_jsonl，見 jsonl_io.py 的說明）。

用法：
  tr-eval.py                      # 跑 Layer 1，印摘要
  tr-eval.py --batch out.jsonl    # 產出 Layer 2 盲標批次（含隨機對照組）
"""
import argparse
import collections
import glob
import hashlib
import json
import os
import re
import sys
from datetime import datetime

import descriptor
import store
from jsonl_io import filter_full_mode, read_jsonl

MIN_HITS = 2               # 獨有詞至少命中幾個才算「後來被用到」——別調，見上面的說明
CONTROL_RATE = 0.10        # 隨機對照組：抽多少比例「沒被刪」的段落一起判

# token 邊界要問的是「這個字元有沒有可能是同一個 distinctive token 的
# 延伸」，答案跟 descriptor.distinctive() 產生 token 時允許的字元集合
# 必須是同一份——直接組 descriptor.TOKEN_CHARS，不是在這裡另外寫一份
# 一樣的字元集合，兩邊才不會走鐘（task-9 fix-round 2）。
_TOKEN_CHAR_RE = re.compile("[" + descriptor.TOKEN_CHARS + "]")

# 墓碑標記本身的形狀（descriptor.make 的兩條分支，都長這樣）：
#   `[省略 N 行 · <該段首行的前 ~200 字> · tr-restore <handle>]`
#   `[省略 N 行 · tr-restore <handle>]`              （首行放不下時）
#
# 三個限制，每一個都是為了「只吃掉真的墓碑標記」：
#
# 1. 開頭要完整的 `[省略 <數字> 行 · `，不是只認 `[省略` 兩個字。
#    `[省略]` 是中文裡很常見的省略記號，log 跟這個 repo 自己的文字裡都
#    有；只認 `[省略` 的話，一個 `[省略]` 加上 400 字以內的任何一個真標記
#    ，中間的所有文字（包含 agent 真的複述的識別字）會被整段吃掉。實測
#    的形狀：「上一輪的輸出是 [省略] 的格式 / 我需要 <tokenA> ... <tokenB>
#    / [省略 4 行 · ... · tr-restore abc.4]」→ 命中數從 2 掉到 0，段落
#    從 silent_miss 變成 clean。過濾回音是為了不高估 silent_miss，吃掉
#    真的複述卻是往低估的方向偏 —— 那是更危險的那一邊。
# 2. 本體用 tempered dot `(?!\[省略)`：一次比對絕不跨過第二個 `[省略`，
#    所以兩個標記之間的文字不可能被當成某一個標記的本體。
# 3. 本體不跨行（`[^\n]`），長度封頂 400（標記本身封頂 250 字元，JSON
#    跳脫再膨脹也綽綽有餘）。
#
# 標記的前綴由 descriptor.make() 產生，兩邊要一起改；
# TestTombstoneEchoIsNotEvidence 有一條測試直接拿 descriptor.make() 的
# 輸出餵進來，形狀一旦漂開就會紅。
_TOMBSTONE_RE = re.compile(
    r"\[省略\s+\d+\s+行\s+·\s+(?:(?!\[省略)[^\n]){0,400}?"
    r"tr-restore\s+[A-Za-z0-9]+\.\d+\s*\]")


def strip_tombstones(text):
    """把 hook 自己寫的墓碑標記從比對視窗裡拿掉。

    descriptor.make() 會把被刪段落首行的前 ~200 字元放進標記，而那個標記
    就在改寫後的輸出裡、由 harness 在 hook 跑完之後寫進 transcript ——
    也就是說它「無條件」落在 transcript_after 的視窗裡。段落的獨有詞按
    定義不出現在同一份 result 的其他段落，所以標記常常是這些詞唯一出現
    的地方，而 MIN_HITS 只要 2 個。結果：一份除了 hook 自己寫的那行墓碑
    以外什麼都沒有的 transcript，也會讓這個段落被判成 silent_miss。
    agent 什麼都沒做。

    連帶影響 tr-tune：main() 拿 current["silent_miss_rate"] 當每個候選
    必須打敗的上限。現行紀錄有墓碑、被回音灌水；候選是重新標註出來的，
    它們刪的段落在 transcript 裡沒有對應的標記，所以量到的是沒有回音的
    版本。上限系統性偏鬆，候選系統性看起來比現行安全。

    真的被還原的段落不受影響：那走 restores.jsonl 的精確比對，而且
    restored 判定永遠贏過詞比對。"""
    return _TOMBSTONE_RE.sub(" ", text)


def _mark_skip(skip_counter):
    if skip_counter is not None:
        skip_counter[0] += 1


def _valid_chunks(d, skip_counter=None):
    """d["chunks"] 存在且是 list 才回傳裡面是 dict 的段落；缺欄位、型別
    不對（字典、字串、數字、或整份 chunks 底下混進非 dict 元素）都退化成
    『這筆不算』而不是丟例外，跟 tr-stats.rollup() 對 decisions.jsonl 的
    容錯同一招（task-8）。"""
    if not isinstance(d, dict) or not isinstance(d.get("decision_id"), str):
        _mark_skip(skip_counter)
        return []
    chunks = d.get("chunks")
    if not isinstance(chunks, list):
        _mark_skip(skip_counter)
        return []
    out = []
    for c in chunks:
        if isinstance(c, dict) and isinstance(c.get("i"), int):
            out.append(c)
        else:
            _mark_skip(skip_counter)
    return out


def _is_token_char(ch):
    """distinctive token 合法會包含字母、數字、`_`、`-`、`.`、`/`（檔案
    路徑、識別字、錯誤字串常見），所以 Python 的 `\\b`（只認字母數字／
    底線的邊界）是錯的工具——用它會把 `main.py` 這種 token 從中間的
    `.` 切斷。邊界自己判斷：只要不是這些字元，就不可能是同一個 token
    的延伸。

    刻意不用 `ch.isalnum()`——Python 的 `isalnum()` 對 Unicode 字母一視
    同仁，中文字（例如「維」)也算 alnum、回傳 True。這支工具的 transcript
    是中文，中文不像英文用空白斷詞：`修改main.py之後重跑` 是一句話裡包著
    identifier `main.py`，不是一個字元都不能拆的超長 token。用 isalnum()
    會把緊貼在 token 兩側的中文字誤判成『同一個 token 的延伸』，邊界檢查
    因此失敗、命中數少算——而且是往危險的方向少算：silent_miss 低估會讓
    刪除看起來比實際安全，門檻會被調成刪更多（task-9 fix-round 2，
    coordinator review）。沒有任何合法的 distinctive token 會包含 CJK
    字元（都是檔案路徑、識別字、錯誤字串、數字），所以直接排除 ASCII
    英數字＋`_-./` 以外的所有字元——包含 CJK、標點（含全形標點）、空白、
    全形英數——一律當邊界，跟 descriptor.TOKEN_CHARS 用同一份定義。"""
    return bool(_TOKEN_CHAR_RE.match(ch))


def _count_token_occurrences(token, text):
    """token 在 text 裡『整個 token』出現幾次，不是子字串出現幾次。

    單純的 `text.count(token)` 是子字串比對：token `"main"`會在
    `"we remain in the domain of maintenance"` 裡數到三次（remain／
    domain／maintenance 各吃一次），全部都是巧合、不是真的複述。
    silent_miss 是整個專案唯一在對抗的指標，灌水的巧合命中會把門檻
    往『什麼都不刪』的方向調，工具看起來還在跑、其實已經沒用（見
    task-9 fix-round 1）。

    邊界規則：token 前一個字元跟後一個字元都不能是「可能屬於 token
    的字元」（見 _is_token_char），字串開頭／結尾本身算邊界。逐一用
    `str.find` 找候選位置、每個都驗證前後邊界，一次只前進一個字元，
    不會漏掉緊鄰彼此的兩個合法出現。"""
    if not token:
        return 0
    count = 0
    start = 0
    tlen = len(token)
    tail = len(text)
    while True:
        idx = text.find(token, start)
        if idx == -1:
            break
        before_ok = idx == 0 or not _is_token_char(text[idx - 1])
        after = idx + tlen
        after_ok = after >= tail or not _is_token_char(text[after])
        if before_ok and after_ok:
            count += 1
        start = idx + 1
    return count


def classify(decisions, restores, later_text_by_decision, skip_counter=None):
    """每個「被刪」的段落分成三態。restored 用精確比對（handle 有沒有
    出現在 restores），且贏過詞比對——同一個 handle 兩者都成立時判
    restored，不是 silent_miss。restores.jsonl 的 via 欄位（"tr-restore"
    或 "direct-read"）只是還原走的路徑，不是兩種不同事件，這裡完全不看
    via，靠 set 天生去重複，同一個 handle 記幾次都只算一次還原（見
    store.py 對 record_restore 的說明、tr-stats 對 via 的同一套處理）。

    decisions／restores 保證是「解析成功的 JSON 值」（read_jsonl 只濾掉
    解析失敗跟非 dict），不保證每個欄位形狀都對——跟 tr-stats.rollup()
    面對的是同一批可能半寫壞的封存檔案，這裡的防呆同一招：形狀不對就算
    skip_counter 一次、這筆不算，不丟例外。"""
    restored = set()
    for r in restores:
        if isinstance(r, dict) and isinstance(r.get("handle"), str):
            restored.add(r["handle"])
        else:
            _mark_skip(skip_counter)

    rows = []
    for d in decisions:
        chunks = _valid_chunks(d, skip_counter)
        if not chunks:
            continue
        decision_id = d["decision_id"]
        tool = d.get("tool")
        tool = tool if isinstance(tool, str) and tool else "unknown"
        # 先把 hook 自己寫的墓碑標記從比對視窗裡拿掉（見 strip_tombstones）
        # ——標記裡就帶著被刪段落的首行，不濾掉的話等於拿自己的輸出當作
        # 「agent 需要這段」的證據。在這裡濾而不是在 transcript_after 裡
        # 濾：所有呼叫端（含 tr-tune 的 _relabel，它直接餵 later_text）
        # 都會經過這一行。
        later = strip_tombstones(later_text_by_decision.get(decision_id) or "")
        for c in chunks:
            if not c.get("dropped"):
                continue
            handle = f"{decision_id}.{c['i']}"
            chars = c.get("chars")
            chars = chars if isinstance(chars, (int, float)) and not isinstance(chars, bool) else 0
            scores = c.get("scores")
            scores = scores if isinstance(scores, dict) else {}
            if handle in restored:
                state = "restored"
            else:
                dist = c.get("distinctive")
                dist = dist if isinstance(dist, list) else []
                # 命中數是「出現次數的總和」，不是「有出現過的獨有詞
                # 種類數」——只有一個獨有詞、但那個詞後來被複述兩次，一樣
                # 算兩次命中。若改成只數「有沒有出現過」（每個詞最多算 1
                # 次），單一獨有詞的段落無論後面重複幾次都拿不到第 2 次
                # 命中，MIN_HITS=2 的門檻對這類段落永遠打不開。用
                # _count_token_occurrences 而不是 str.count：後者是子
                # 字串比對，`main` 會被 `remain`／`domain`／`maintenance`
                # 巧合命中三次（task-9 fix-round 1）。
                hits = sum(_count_token_occurrences(t, later)
                          for t in dist if isinstance(t, str) and t)
                state = "silent_miss" if hits >= MIN_HITS else "clean"
            rows.append({"handle": handle, "decision_id": decision_id,
                         "tool": tool, "chars": chars,
                         "scores": scores, "state": state})
    return rows


def summarize(rows):
    c = collections.Counter(r["state"] for r in rows)
    n = len(rows) or 1
    return {"total": len(rows), "restored": c["restored"],
            "silent_miss": c["silent_miss"], "clean": c["clean"],
            "restored_rate": c["restored"] / n,
            "silent_miss_rate": c["silent_miss"] / n}


def _row_ts_ms(ts_str):
    """transcript 每行的 timestamp 是 ISO 8601 UTC（`...Z` 結尾），轉成
    跟 decision["ts_ms"]（store.now_ms()，epoch 毫秒）同單位，才能比較
    先後。格式不對、缺欄位都回 None——呼叫端把 None 當成『排不進時間軸，
    不算後來』，不是預設放行（見 transcript_after 的說明：預設放行正是
    這支工具原本會把整份 transcript 都算成『後來』的那個坑）。

    沒有時區資訊的 timestamp（naive）一樣回 None，不是解析成功後直接
    呼叫 .timestamp()——naive datetime 的 .timestamp() 會假設它是「本機
    時區」，同一份 transcript 在不同時區的機器上跑出不同的 epoch ms、
    進而跑出不同的 silent_miss 判定，而且這個錯不會被 except 擋下來
    （fromisoformat 對 naive 字串解析成功，不丟例外）——這是比『格式
    不對，排除』更危險的一種錯，因為它悄悄給了一個看似合理、方向卻
    隨執行環境改變的數字。真實 transcript 一律帶 Z，這裡保守處理：
    沒有時區就當成不可解析，跟缺欄位／格式錯誤同一個下場（task-9
    fix-round 1）。"""
    if not isinstance(ts_str, str) or not ts_str:
        return None
    s = ts_str[:-1] + "+00:00" if ts_str.endswith("Z") else ts_str
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        return None
    return dt.timestamp() * 1000


def transcript_after(decision_id, decisions_by_id, transcript_dir=None):
    """decision 之後的 transcript 文字：只收 timestamp 晚於
    decision["ts_ms"] 的 assistant／user 訊息，不是整份檔案、也不是檔案
    最後 N 行。

    這一點刻意強調：如果拿整份 transcript（含 decision 之前、甚至墓碑
    工具輸出本身所在的那一輪）去比對獨有詞，會把「這次工具呼叫剛印出來
    的原文」算成「後來的引用」，幾乎每個墓碑都會被判成 silent_miss——
    這個函式存在的唯一理由就是畫出這條時間邊界，畫不對整支 eval 就沒有
    意義。找不到 decision、session_id、或這個 session 完全沒有 ts_ms
    可比對，回傳空字串（沒有邊界資訊時，安全的預設是『沒有後來』，不是
    『全部都算後來』——寧可低估 silent_miss，也不要把近似指標的雜訊
    往高估那個方向偏，見模組開頭的說明）。"""
    d = decisions_by_id.get(decision_id)
    if not isinstance(d, dict):
        return ""
    session_id = d.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return ""
    ts = d.get("ts_ms")
    ts = ts if isinstance(ts, (int, float)) and not isinstance(ts, bool) else None
    if ts is None:
        return ""

    root = transcript_dir or os.path.expanduser("~/.claude/projects")
    buf = []
    for f in glob.glob(os.path.join(root, "*", f"{session_id}.jsonl")):
        try:
            fh = open(f, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if not isinstance(row, dict) or row.get("type") not in ("assistant", "user"):
                    continue
                row_ms = _row_ts_ms(row.get("timestamp"))
                if row_ms is None or row_ms <= ts:
                    continue
                message = row.get("message")
                content = message.get("content") if isinstance(message, dict) else None
                if content:
                    buf.append(json.dumps(content, ensure_ascii=False))
    return "\n".join(buf)


def build_batch(decisions, rows, out_path):
    """Layer 2 盲標批次：被刪的段落 + 10% 沒被刪的對照組。

    給 judge 的資料要拿掉『當初做了什麼決定』——看得到的話標註只是在複述
    那個決定，所以這裡刻意不寫 state／scores，`rows`（Layer 1 的分類結果）
    參數留著只是介面一致（呼叫端已經算出來、順手傳進來），函式本體不讀它
    半個欄位。

    抽樣用 handle 的雜湊決定，重跑會挑到同一批：用 hashlib.sha256 而不是
    內建 hash()，因為 hash() 對字串的雜湊值受 PYTHONHASHSEED 影響、同一
    支程式兩次啟動可能給同一個字串不同的值（除非關掉雜湊隨機化）；
    sha256 純粹是輸入位元組的函式，不受行程、字典插入順序、或任何執行期
    狀態影響，同一個 handle 字串在任何時候、任何行程裡都雜湊出同一個值。
    """
    items = []
    for d in decisions:
        for c in _valid_chunks(d):
            handle = f"{d['decision_id']}.{c['i']}"
            is_control = not c.get("dropped")
            if is_control:
                h = int(hashlib.sha256(handle.encode()).hexdigest()[:8], 16)
                if (h % 1000) / 1000.0 >= CONTROL_RATE:
                    continue
            tool = d.get("tool")
            tool = tool if isinstance(tool, str) and tool else "unknown"
            chars = c.get("chars")
            chars = chars if isinstance(chars, (int, float)) and not isinstance(chars, bool) else 0
            items.append({"handle": handle, "tool": tool,
                          "chars": chars, "control": is_control})
    with open(out_path, "w", encoding="utf-8") as fh:
        for it in items:
            fh.write(json.dumps(it, ensure_ascii=False) + "\n")
    return len(items)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch")
    a = ap.parse_args()
    # 存放區根目錄一律走 store.root()，且是 main() 每次執行時才呼叫，不在
    # 模組載入當下凍結成常數——跟 tr-restore／tr-guard／PostToolUse hook／
    # tr-stats 同一招（task-7 統一的公式、task-8 沿用、這裡同樣沿用）。
    # transcript 根目錄同理：透過環境變數在每次呼叫時重新讀取，不凍結，
    # 這樣測試才能在同一個行程裡指向不同的暫存 transcript 目錄。
    home = store.root()
    transcript_dir = os.environ.get("TOOL_REDUCE_TRANSCRIPT_DIR") or None
    base = os.path.join(home, "archive")

    read_skip = [0]
    shadow_skip = [0]
    # shadow 模式的紀錄在這一層就濾掉（見 jsonl_io.is_full_mode）。這支
    # 受 shadow 汙染最重：shadow 模式下 agent 看得到全文，獨有詞自然會
    # 再出現，每一段都會被算成沉默誤刪。
    decisions = filter_full_mode(
        read_jsonl(os.path.join(base, "decisions.jsonl"), read_skip), shadow_skip)
    restores = read_jsonl(os.path.join(base, "restores.jsonl"), read_skip)
    by_id = {d["decision_id"]: d for d in decisions
             if isinstance(d, dict) and isinstance(d.get("decision_id"), str)}
    later = {did: transcript_after(did, by_id, transcript_dir) for did in by_id}

    classify_skip = [0]
    rows = classify(decisions, restores, later, skip_counter=classify_skip)
    total_skipped = read_skip[0] + classify_skip[0]

    s = summarize(rows)
    print(f"墓碑 {s['total']} 個")
    if total_skipped:
        print(f"  注意：{total_skipped} 筆紀錄格式不對，已略過、"
             f"未列入以下統計（可能是半寫壞的紀錄檔）\n")
    if shadow_skip[0]:
        print(f"  注意：{shadow_skip[0]} 筆 shadow 模式的決策未列入以下分類"
             f"（那些段落沒有真的從 tool output 消失）\n")
    print(f"  還原       {s['restored']:>6}  ({s['restored_rate']:.1%})  確定誤刪，已救回")
    print(f"  沉默誤刪   {s['silent_miss']:>6}  ({s['silent_miss_rate']:.1%})  "
         f"需要卻沒去拿——近似指標，不是精確量測")
    print(f"  乾淨       {s['clean']:>6}")
    if a.batch:
        n = build_batch(decisions, rows, a.batch)
        print(f"\nLayer 2 批次寫入 {a.batch}（{n} 筆，含 {int(CONTROL_RATE*100)}% 對照組）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
