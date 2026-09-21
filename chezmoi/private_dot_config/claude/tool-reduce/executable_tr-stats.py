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
"""
import argparse
import collections
import json
import os
import sys

import store


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def rollup(decisions, tombstones, restores):
    tomb_by_handle = {t["handle"]: t for t in tombstones}
    # 用集合去重複：一個 handle 不管被記了幾筆 restore（tr-restore 跟
    # direct-read 各記一次、或同一條路徑被記了兩次），對「這個墓碑被還原
    # 過」這件事只算一次 —— restored_chars／restore_rate／
    # results_with_restore 都建立在這個去重複過的集合上，才不會讓同一次
    # 還原的字元被拉回去扣兩次。
    restored = {r["handle"] for r in restores if r.get("handle") in tomb_by_handle}

    gross = sum(c["chars"] for d in decisions for c in d["chunks"] if c["dropped"])
    tomb_cost = sum(len(t.get("descriptor", "")) for t in tombstones)
    restored_chars = sum(tomb_by_handle[h]["chars"] for h in restored)

    decisions_with_restore = {tomb_by_handle[h]["decision_id"] for h in restored}
    by_tool = collections.defaultdict(
        lambda: {"n": 0, "gross_saved": 0, "restored": 0, "chars_before": 0})
    for d in decisions:
        b = by_tool[d["tool"]]
        b["n"] += 1
        b["chars_before"] += d.get("chars_before", 0)
        b["gross_saved"] += sum(c["chars"] for c in d["chunks"] if c["dropped"])
    for h in restored:
        b = by_tool[next(d["tool"] for d in decisions
                         if d["decision_id"] == tomb_by_handle[h]["decision_id"])]
        b["restored"] += 1

    # noise 分數的十格直方圖。決策全擠在門檻邊緣，就代表門檻沒有鑑別力。
    # 涵蓋每個「有算過分」的段落（不論最後被丟還是被留），缺分數的段落
    # 直接跳過，不當成 0 分硬塞進第 0 格。
    hist = [0] * 10
    for d in decisions:
        for c in d["chunks"]:
            v = (c.get("scores") or {}).get("noise")
            if isinstance(v, (int, float)):
                hist[min(9, max(0, int(v * 10)))] += 1

    total_before = sum(d.get("chars_before", 0) for d in decisions) or 1
    return {
        "score_hist": hist,
        "decisions": len(decisions),
        "tombstones": len(tombstones),
        "restores": len(restores),
        "gross_saved": gross,
        "tombstone_cost": tomb_cost,
        "restored_chars": restored_chars,
        "net_saved": gross - tomb_cost - restored_chars,
        "net_ratio": (gross - tomb_cost - restored_chars) / total_before,
        "restore_rate": (len(restored) / len(tombstones)) if tombstones else 0.0,
        "results_with_restore": (len(decisions_with_restore) / len(decisions))
                                if decisions else 0.0,
        "by_tool": dict(by_tool),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    home = store.root()
    base = os.path.join(home, a.session) if a.session else os.path.join(home, "archive")
    r = rollup(read_jsonl(os.path.join(base, "decisions.jsonl")),
               read_jsonl(os.path.join(base, "tombstones.jsonl")),
               read_jsonl(os.path.join(base, "restores.jsonl")))
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
        return 0
    print(f"決策 {r['decisions']} 筆、墓碑 {r['tombstones']} 個、還原 {r['restores']} 次\n")
    print(f"  毛省      {r['gross_saved']:>12,} 字元")
    print(f"  墓碑成本  {r['tombstone_cost']:>12,}")
    print(f"  還原拉回  {r['restored_chars']:>12,}")
    print(f"  淨省      {r['net_saved']:>12,}  ({r['net_ratio']:.1%} of chars before)")
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
