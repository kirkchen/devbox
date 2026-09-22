#!/usr/bin/env python3
"""tool-reduce 的統計：實際省了多少、還原了多少、淨效益是多少。

用法：
  tr-stats.py                 # 封存區全部
  tr-stats.py --session <id>  # 只看一個 session

存放區根目錄一律走 store.root()（TOOL_REDUCE_HOME 優先，否則
store.ROOT_DEFAULT），且是 main() 每次執行時才呼叫，不在模組載入當下
就凍結成常數 —— 跟 tr-restore／tr-guard／PostToolUse hook 同一招
（task-7 統一的單一根目錄解析公式）。凍結成模組層級常數看起來一樣是
「走同一份公式」，但只算一次：同一個行程裡先讀早、後設
TOOL_REDUCE_HOME 的呼叫端（例如測試在呼叫前才設環境變數）會看到舊值，
這正是 task-7 review 抓到的那個 bug 的形狀。

rollup() 吃的三份輸入都是「別人寫的紀錄檔」——store._append 是盡力而為，
session 目錄跟封存區各自獨立寫、任一份失敗不影響另一份，也不保證
atomic；半寫壞的 decisions.jsonl 配上完整的 tombstones.jsonl（或反過來）
是這支最可能在真實環境撞到的形狀，偏偏又是最想看到數字的時候。所以
每一筆紀錄、每一個欄位在被讀取前都先確認形狀，缺欄位、型別不對、甚至
整筆紀錄本身不是 dict，都要退化成「這筆不算」而不是丟例外（task-8
fix-round 1）。"""
import argparse
import collections
import json
import os
import re
import sys

import store
from jsonl_io import filter_full_mode, read_jsonl

# session id 的字元集合刻意收緊：只認字母、數字、下底線、連字號，不含
# `.` 或 `/`——擋掉 `--session ../../../../etc` 這種路徑穿越寫法，不需要
# 先組出路徑再靠 containment 檢查善後。containment 檢查（見 main()）還是
# 留著當第二道防線，跟 store.load_chunk／tr-guard 驗證 handle 同一招：
# 光靠字元集合擋不住「session id 本身合法、但剛好是一個 symlink 指到
# 存放區外面」這種形狀。
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]+$")


# read_jsonl 搬進 jsonl_io.py 了（task-9）：tr-eval 讀的是同一批可能半寫壞
# 的封存檔案，容錯規則跟「skip_counter 累計略過筆數」的契約要保證只有一份
# 實作，不是兩支各養各的、容易漂移。這裡保留頂層名稱 read_jsonl，模組內其他
# 地方（含既有測試 stats.read_jsonl(...)）不用改呼叫方式。


def _num(x, default=0):
    """x 是不是一個能拿來加總的數字。True/False 也是 int 的子類別，但
    這裡的欄位（chars、chars_before）語意上不會是布林值，isinstance 排除
    bool 是防呆，不是預期會撞到。"""
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return x
    return default


def _chunks(d):
    """d["chunks"] 存在且是 list 才回傳；缺欄位、型別不對（字典、字串、
    數字）都當成沒有段落，不是丟例外。"""
    c = d.get("chunks")
    return c if isinstance(c, list) else []


def _dropped_chars(d):
    total = 0
    for c in _chunks(d):
        if isinstance(c, dict) and c.get("dropped"):
            total += _num(c.get("chars"))
    return total


def _descriptor_len(t):
    """墓碑成本只認字串長度的 descriptor；型別不對（例如 123 這種數字）
    當成 0 成本，不是讓 len() 對非字串丟 TypeError——跟其他欄位一樣，
    形狀不對就退化成『這個貢獻不算』，不是讓整條 rollup 中斷（task-8
    fix-round 2：這是 fix-round 1 補齊各種形狀防呆之後唯一還留著的一條
    crash path）。"""
    desc = t.get("descriptor")
    return len(desc) if isinstance(desc, str) else 0


def rollup(decisions, tombstones, restores):
    # 三份輸入各自過濾掉不是字典的紀錄——不管是呼叫端直接塞了字串／
    # list／None 進來，還是 read_jsonl 之前版本沒濾掉就傳進來的殘留。
    # 同時數有幾筆被濾掉：跟 read_jsonl 那關的計數（見 main()）合起來，
    # 才是「這次統計實際上略過了多少筆紀錄」的完整數字——一份半寫壞的
    # 封存區是 store._append 盡力而為設計下的常態，不是例外，這個數字
    # 只驗證「沒有丟例外」還不夠，總得讓人看得到「有東西被略過」。
    skipped = 0

    valid_decisions = []
    for d in decisions:
        if isinstance(d, dict):
            valid_decisions.append(d)
        else:
            skipped += 1
    decisions = valid_decisions

    valid_tombstones = []
    for t in tombstones:
        if isinstance(t, dict) and isinstance(t.get("handle"), str):
            valid_tombstones.append(t)
        else:
            skipped += 1
    tombstones = valid_tombstones

    valid_restores = []
    for r in restores:
        if isinstance(r, dict):
            valid_restores.append(r)
        else:
            skipped += 1
    restores = valid_restores

    # 決策紀錄本身是 dict（前面那關過了），但 "chunks" 缺欄位或型別不對
    # ——這筆決策還是算進 r["decisions"]（它確實是一筆有效的決策紀錄），
    # 但它對 gross_saved／by_tool／score_hist 的貢獻全部是 0，這件事一樣
    # 要算進略過總數，不然一份「decisions.jsonl 每筆都在、但 chunks 那段
    # 被截斷」的封存區會算出一個看似正常、其實是 0 的毛省，卻沒有任何
    # 信號說發生了什麼事。
    skipped += sum(1 for d in decisions if not isinstance(d.get("chunks"), list))

    tomb_by_handle = {t["handle"]: t for t in tombstones}
    decision_by_id = {d["decision_id"]: d for d in decisions
                      if isinstance(d.get("decision_id"), str)}

    # 用集合去重複：一個 handle 不管被記了幾筆 restore（tr-restore 跟
    # direct-read 各記一次、或同一條路徑被記了兩次），對「這個墓碑被還原
    # 過」這件事只算一次——restored_chars／restore_rate／
    # results_with_restore 都建立在這個去重複過的集合上，才不會讓同一次
    # 還原的字元被拉回去扣兩次。
    restored = {r.get("handle") for r in restores if r.get("handle") in tomb_by_handle}

    gross = sum(_dropped_chars(d) for d in decisions)
    tomb_cost = sum(_descriptor_len(t) for t in tombstones)
    restored_chars = sum(_num(tomb_by_handle[h].get("chars")) for h in restored)

    # 一個 restore 指到的 decision_id 有可能查不到對應的 decision 紀錄
    # （tombstone 那份還在、decisions.jsonl 那份沒寫成功或被截斷）——
    # 孤兒還原仍然是一次確認的還原，restored_chars／restore_rate 已經
    # 算過了；只有「這筆算進哪個 decision／哪個 tool」查不到對象，不能
    # 因此讓整條 rollup 中斷（StopIteration），也不能讓它偷偷灌進
    # results_with_restore 的分子（那裡只認真的存在於 decisions 裡的
    # id，用集合交集擋，見下方）。
    restored_decision_ids = {tomb_by_handle[h].get("decision_id") for h in restored}
    decisions_with_restore = restored_decision_ids & set(decision_by_id.keys())

    by_tool = collections.defaultdict(
        lambda: {"n": 0, "gross_saved": 0, "restored": 0, "chars_before": 0})
    for d in decisions:
        tool = d.get("tool")
        tool = tool if isinstance(tool, str) and tool else "unknown"
        b = by_tool[tool]
        b["n"] += 1
        b["chars_before"] += _num(d.get("chars_before"))
        b["gross_saved"] += _dropped_chars(d)
    for h in restored:
        did = tomb_by_handle[h].get("decision_id")
        d = decision_by_id.get(did)
        tool = d.get("tool") if d else None
        tool = tool if isinstance(tool, str) and tool else "unknown"
        by_tool[tool]["restored"] += 1

    # noise 分數的十格直方圖。決策全擠在門檻邊緣，就代表門檻沒有鑑別力。
    # 涵蓋每個「有算過分」的段落（不論最後被丟還是被留），缺分數
    # （缺鍵、值是 None、或 scores 本身形狀不對）的段落直接跳過，不當成
    # 0 分硬塞進第 0 格。
    hist = [0] * 10
    for d in decisions:
        for c in _chunks(d):
            if not isinstance(c, dict):
                continue
            scores = c.get("scores")
            v = scores.get("noise") if isinstance(scores, dict) else None
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                hist[min(9, max(0, int(v * 10)))] += 1

    total_before = sum(_num(d.get("chars_before")) for d in decisions)
    net_saved = gross - tomb_cost - restored_chars
    # 分母全部欄位缺失或全是 0 時，比例本身沒有意義——印一個「用 1 頂替
    # 分母」算出來的數字看起來像真的有算過，卻是灌水的百分比，比直接說
    # 「算不出來」更容易誤導人（"a rollup that lies is worse than one
    # that admits it cannot tell"）。None 交給呼叫端（CLI／--json）自己
    # 決定要印「N/A」還是留白，rollup() 本身不編故事。
    net_ratio = (net_saved / total_before) if total_before else None

    return {
        "score_hist": hist,
        "records_skipped": skipped,
        "decisions": len(decisions),
        "tombstones": len(tombstones),
        "restores": len(restores),
        "gross_saved": gross,
        "tombstone_cost": tomb_cost,
        "restored_chars": restored_chars,
        "net_saved": net_saved,
        "net_ratio": net_ratio,
        "restore_rate": (len(restored) / len(tombstones)) if tombstones else 0.0,
        "results_with_restore": (len(decisions_with_restore) / len(decisions))
                                if decisions else 0.0,
        "by_tool": dict(by_tool),
    }


def _resolve_base(home, session):
    """--session 沒帶就是封存區；帶了就驗證這個 session id：字元集合先
    擋掉 `../` 這種寫法本身，containment 檢查（跟 store.load_chunk、
    tr-guard 驗證 handle 同一招）再擋一次「session id 本身合法、但解析
    出來的路徑不落在存放區底下」的形狀（例如透過 symlink）。回傳
    (base_path, error_message)；error_message 非 None 時 base_path 必為
    None，呼叫端據此印錯誤、非零結束，不能悄悄退回封存區——一個打錯的
    session 名字如果安靜地印出封存區全部的統計，會被誤讀成那個 session
    真的沒有任何紀錄。"""
    if session is None:
        return os.path.join(home, "archive"), None
    if not SESSION_RE.match(session):
        return None, f"invalid session id: {session}"
    candidate = os.path.join(home, session)
    real_home = os.path.realpath(home)
    real_candidate = os.path.realpath(candidate)
    if real_candidate != real_home and not real_candidate.startswith(real_home + os.sep):
        return None, f"invalid session id: {session}"
    if not os.path.isdir(candidate):
        return None, f"no such session: {session}"
    return candidate, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    home = store.root()
    base, err = _resolve_base(home, a.session)
    if err:
        print(f"tr-stats: {err}", file=sys.stderr)
        return 1
    # 讀檔這一關的略過筆數（解析失敗的行、解析成功但不是 dict 的行）跟
    # rollup() 自己那關（收到的 dict 形狀不對）的略過筆數合併成一個總數
    # ——兩關各自算各自的，沒有誰算兩次：read_jsonl 只數「根本沒進
    # rollup() 的那些行」，rollup() 只數「進去了、但形狀不合格被退回」
    # 的那些紀錄。
    read_skip = [0]
    # shadow 模式的紀錄在這一層就濾掉（見 jsonl_io.is_full_mode）。決策跟
    # 墓碑兩份都要濾：墓碑成本是獨立加總的，只濾決策的話 shadow 的墓碑
    # 成本還是會被算在 full 的節省上。restores.jsonl 沒有 mode 欄位，
    # 一次還原就是一次還原，不分模式。
    shadow_skip = [0]
    r = rollup(filter_full_mode(
                   read_jsonl(os.path.join(base, "decisions.jsonl"), read_skip),
                   shadow_skip),
               filter_full_mode(
                   read_jsonl(os.path.join(base, "tombstones.jsonl"), read_skip),
                   shadow_skip),
               read_jsonl(os.path.join(base, "restores.jsonl"), read_skip))
    r["records_skipped"] += read_skip[0]
    r["shadow_records_excluded"] = shadow_skip[0]
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    ratio_str = f"{r['net_ratio']:.1%}" if r["net_ratio"] is not None else "N/A"
    print(f"決策 {r['decisions']} 筆、墓碑 {r['tombstones']} 個、還原 {r['restores']} 次\n")
    if r["records_skipped"]:
        print(f"  注意：{r['records_skipped']} 筆紀錄格式不對，已略過、"
             f"未列入以下統計（可能是半寫壞的紀錄檔）\n")
    if r["shadow_records_excluded"]:
        print(f"  注意：{r['shadow_records_excluded']} 筆 shadow 模式的紀錄"
             f"未列入以下統計（那些判斷沒有真的改動任何輸出）\n")
    print(f"  毛省      {r['gross_saved']:>12,} 字元")
    print(f"  墓碑成本  {r['tombstone_cost']:>12,}")
    print(f"  還原拉回  {r['restored_chars']:>12,}")
    print(f"  淨省      {r['net_saved']:>12,}  ({ratio_str} of chars before)")
    print(f"\n  還原率            {r['restore_rate']:.1%}")
    print(f"  有還原的 result   {r['results_with_restore']:.1%}")
    print(f"\n  {'tool':<28}{'n':>6}{'毛省':>12}{'還原':>7}")
    for t, b in sorted(r["by_tool"].items(), key=lambda kv: -kv[1]["gross_saved"]):
        print(f"  {t[:27]:<28}{b['n']:>6}{b['gross_saved']:>12,}{b['restored']:>7}")

    peak = max(r["score_hist"]) or 1
    print("\n  noise 分數分佈（擠在門檻邊緣代表門檻沒有鑑別力）")
    for i, n in enumerate(r["score_hist"]):
        print(f"    {i/10:.1f}-{(i+1)/10:.1f}  {'#' * int(n * 30 / peak):<30} {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
