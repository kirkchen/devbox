#!/usr/bin/env python3
"""把 judge 產出的標註寫回 eval_set.json，並跟人工標註比對一致率。

用法:
  python3 merge_labels.py judge-out-*.json                # judge 標註
  python3 merge_labels.py --human human-labels.json       # 人工標註（當基準）
  python3 merge_labels.py --agreement                     # 只看人機一致率
"""
import json, os, sys, glob, argparse, collections

EVAL = os.path.expanduser("~/.local/share/model-router-eval")
SET = f"{EVAL}/eval_set.json"
ap = argparse.ArgumentParser()
ap.add_argument("files", nargs="*")
ap.add_argument("--human", action="store_true", help="這批視為人工基準，寫進 label_human")
ap.add_argument("--agreement", action="store_true")
a = ap.parse_args()

rows = json.load(open(SET, encoding="utf-8"))
by_id = {r["id"]: r for r in rows}

if not a.agreement:
    if not a.files:
        sys.exit("要給 judge 輸出的 json 檔")
    n = skipped = 0
    for pat in a.files:
        for f in glob.glob(pat):
            data = json.load(open(f, encoding="utf-8"))
            if isinstance(data, dict):
                data = data.get("labels") or data.get("items") or []
            for it in data:
                r = by_id.get(it.get("id"))
                if not r:
                    skipped += 1; continue
                t = it.get("expected_tier")
                if t not in (0, 1, 2):
                    skipped += 1; continue
                slot = "label_human" if a.human else "label"
                r.setdefault(slot, {})
                r[slot] = {"expected_tier": t,
                           "labeler_confidence": it.get("confidence"),
                           "note": it.get("note", ""),
                           "source": "human" if a.human else "judge"}
                n += 1
    json.dump(rows, open(SET, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"寫入 {n} 筆{'（人工基準）' if a.human else ''}，略過 {skipped} 筆")

lab = [r for r in rows if r.get("label", {}).get("expected_tier") is not None]
hum = [r for r in rows if r.get("label_human", {}).get("expected_tier") is not None]
print(f"\njudge 已標 {len(lab)}/{len(rows)}   人工已標 {len(hum)}")
if lab:
    print("judge 標註分布:", dict(collections.Counter(
        (r['label']['expected_tier'], r['label'].get('labeler_confidence')) for r in lab)))

both = [r for r in rows if r.get("label", {}).get("expected_tier") is not None
        and r.get("label_human", {}).get("expected_tier") is not None]
if not both:
    print("\n（還沒有同時被人工與 judge 標過的列，無法算一致率）")
    print("先人工標 10 筆左右當基準：merge_labels.py --human my-labels.json")
    sys.exit(0)

agree = sum(1 for r in both if r["label"]["expected_tier"] == r["label_human"]["expected_tier"])
off1 = sum(1 for r in both if abs(r["label"]["expected_tier"] - r["label_human"]["expected_tier"]) == 1)
print(f"\n=== 人機一致率（{len(both)} 筆重疊）===")
print(f"  完全一致 {agree}/{len(both)} = {agree/len(both)*100:.0f}%")
print(f"  差一級   {off1}/{len(both)}")
print(f"  差兩級   {len(both)-agree-off1}/{len(both)}")
print("\n--- 不一致的列 ---")
for r in both:
    j, h = r["label"]["expected_tier"], r["label_human"]["expected_tier"]
    if j != h:
        print(f"  {r['id']} {r['description'][:44]:<44} judge={j} 人工={h} "
              f"(judge信心={r['label'].get('labeler_confidence')})")
        print(f"     judge 理由: {r['label'].get('note','')[:110]}")
print("\n判讀：完全一致 <70% 就不要用 judge 標剩下的，先改 JUDGE.md 的分級定義再重跑。")
