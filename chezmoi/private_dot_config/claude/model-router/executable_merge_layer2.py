#!/usr/bin/env python3
"""把 Layer 2 judge 的標註 append 進 labels.jsonl，並印出本輪摘要。

用法:
  merge_layer2.py judge-out-*.json
  merge_layer2.py --human my-labels.json     # 人工基準，source=human
  merge_layer2.py --report                   # 只看現況
"""
import json, os, sys, glob, argparse, collections, hashlib, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import outcomes, policy

EVAL = os.path.expanduser(os.environ.get("EVAL_DIR", "~/.local/share/model-router-eval"))
LAB = f"{EVAL}/labels.jsonl"
ap = argparse.ArgumentParser()
ap.add_argument("files", nargs="*")
ap.add_argument("--human", action="store_true")
ap.add_argument("--report", action="store_true")
ap.add_argument("--judge-model", default="opus")
ap.add_argument("--projects", default="~/.claude/projects/*")
a = ap.parse_args()

if not a.report:
    if not a.files: sys.exit("要給 judge 輸出的 json 檔")
    n = bad = 0
    with open(LAB, "a", encoding="utf-8") as fh:
        for pat in a.files:
            for f in glob.glob(pat):
                data = json.load(open(f, encoding="utf-8"))
                if isinstance(data, dict): data = data.get("labels") or data.get("items") or []
                for it in data:
                    aid, t = it.get("agent_id"), it.get("expected_tier")
                    if not aid or t not in (0, 1, 2): bad += 1; continue
                    fh.write(json.dumps({
                        "agent_id": aid, "expected_tier": t,
                        "confidence": it.get("confidence"), "note": it.get("note", ""),
                        "source": "human" if a.human else "judge",
                        "judge_model": None if a.human else a.judge_model,
                        "judged_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                    }, ensure_ascii=False) + "\n")
                    n += 1
    print(f"寫入 {n} 筆{'（人工基準）' if a.human else ''}" + (f"，略過 {bad} 筆格式不符" if bad else ""))

labels = collections.defaultdict(dict)
if os.path.exists(LAB):
    for line in open(LAB, encoding="utf-8"):
        try: r = json.loads(line)
        except Exception: continue
        labels[r["agent_id"]][r["source"]] = r

corpus = {}
cp = f"{EVAL}/corpus.jsonl"
if os.path.exists(cp):
    for line in open(cp, encoding="utf-8"):
        try: r = json.loads(line)
        except Exception: continue
        if r.get("agent_id"): corpus[r["agent_id"]] = r

print(f"\ncorpus {len(corpus)} 筆   已判 {len(labels)} 筆"
      f"（judge {sum(1 for v in labels.values() if 'judge' in v)}"
      f" / 人工 {sum(1 for v in labels.values() if 'human' in v)}）")

j = [v["judge"] for v in labels.values() if "judge" in v]
if j:
    print("judge tier 分布:", dict(collections.Counter(x["expected_tier"] for x in j)))
    print("judge 信心    :", dict(collections.Counter(x.get("confidence") for x in j)))

# Layer 1 篩檢 vs Layer 2 判定：量漏判率
oc = outcomes.by_agent_id(a.projects)
rows = [(aid, corpus.get(aid, {}), v["judge"]) for aid, v in labels.items() if "judge" in v]
flagged = [(aid, c, l) for aid, c, l in rows if c.get("needs_layer2")]
notflag = [(aid, c, l) for aid, c, l in rows if c and not c.get("needs_layer2")]
if notflag:
    o = oc
    miss = [x for x in notflag if x[2]["expected_tier"] > (policy.tier_of(o.get(x[0], {}).get("model_resolved")) or 0)]
    print(f"\n=== Layer 1 篩檢效果（對照組 {len(notflag)} 筆）===")
    print(f"  Layer 1 沒 flag、但 Layer 2 判定當時配置過低: {len(miss)}/{len(notflag)}"
          f" = {len(miss)/len(notflag)*100:.0f}%  ← Layer 1 漏判率")
if flagged:
    o = oc
    real = [x for x in flagged if x[2]["expected_tier"] > (policy.tier_of(o.get(x[0], {}).get("model_resolved")) or 0)]
    print(f"  Layer 1 flag 了 {len(flagged)} 筆，其中 Layer 2 也認為配置過低: {len(real)}"
          f" = {len(real)/len(flagged)*100:.0f}%  ← Layer 1 準確率")

both = [(aid, v["judge"], v["human"]) for aid, v in labels.items() if "judge" in v and "human" in v]
if both:
    agree = sum(1 for _, j_, h in both if j_["expected_tier"] == h["expected_tier"])
    print(f"\n=== 人機一致率（{len(both)} 筆重疊）===")
    print(f"  完全一致 {agree}/{len(both)} = {agree/len(both)*100:.0f}%")
    for aid, j_, h in both:
        if j_["expected_tier"] != h["expected_tier"]:
            print(f"  ✗ {aid} judge={j_['expected_tier']} 人工={h['expected_tier']} "
                  f"(信心={j_.get('confidence')}) {j_.get('note','')[:80]}")
    print("\n低於 70% 就先改 JUDGE.md 的分級定義再重跑，不要拿這批標註評 Jev。")
else:
    print("\n還沒有人工基準。手標 10 筆後跑：merge_layer2.py --human my-labels.json")
