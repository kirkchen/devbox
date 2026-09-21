#!/usr/bin/env python3
"""挑出要送 Layer 2 真模型 judge 的案例，產生盲標批次。

三種來源：
  1. Layer 1 標了 needs_layer2 的
  2. 事後出現返工訊號的（needed_fix_round）
  3. 隨機對照組（預設 10%）— 沒有它就量不到 Layer 1 的漏判率

用 agent_id 雜湊決定對照組，所以重跑會挑到同一批。
"""
import json, os, sys, glob, argparse, hashlib, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import outcomes

EVAL = os.path.expanduser(os.environ.get("EVAL_DIR", "~/.local/share/model-router-eval"))
ap = argparse.ArgumentParser()
ap.add_argument("--size", type=int, default=8, help="每批幾筆")
ap.add_argument("--control-pct", type=int, default=10)
ap.add_argument("--max", type=int, default=64, help="單輪上限，避免一次派太多")
ap.add_argument("--projects", default="~/.claude/projects/*")
ap.add_argument("--max-prompt", type=int, default=6000)
ap.add_argument("--max-output", type=int, default=8000)
a = ap.parse_args()

corpus = f"{EVAL}/corpus.jsonl"
if not os.path.exists(corpus):
    sys.exit(f"找不到 {corpus}\nLayer 1 還沒跑過（JUDGE_SUBAGENT_OUTPUT=1 開了嗎？）")

rows = {}
for line in open(corpus, encoding="utf-8"):
    line = line.strip()
    if not line: continue
    try: r = json.loads(line)
    except Exception: continue
    if r.get("agent_id"): rows[r["agent_id"]] = r          # 後寫的覆蓋前面

judged = set()
lab = f"{EVAL}/labels.jsonl"
if os.path.exists(lab):
    for line in open(lab, encoding="utf-8"):
        try: judged.add(json.loads(line)["agent_id"])
        except Exception: pass

oc = outcomes.by_agent_id(a.projects)
reports = {}
rd = f"{EVAL}/reports"
if os.path.isdir(rd):
    for f in glob.glob(f"{rd}/*.json"):
        try:
            d = json.load(open(f, encoding="utf-8"))
            reports[d["agent_id"]] = d.get("report", "")
        except Exception: pass

def in_control(aid):
    return int(hashlib.sha256(aid.encode()).hexdigest()[:8], 16) % 100 < a.control_pct

picked, why = [], {}
for aid, r in rows.items():
    if aid in judged: continue
    o = oc.get(aid, {})
    reasons = []
    if r.get("needs_layer2"):        reasons.append("layer1-flag")
    if o.get("needed_fix_round"):    reasons.append("rework")
    if in_control(aid):              reasons.append("control")
    if reasons:
        picked.append((aid, r, o)); why[aid] = reasons

picked.sort(key=lambda x: x[1].get("ts", ""))
picked = picked[:a.max]
print(f"corpus {len(rows)} 筆，已判 {len(judged)} 筆，本輪挑出 {len(picked)} 筆")
print("  來源:", dict(collections.Counter(x for r in why.values() for x in r)))
if not picked:
    sys.exit(0)

out = f"{EVAL}/batches"
os.makedirs(out, exist_ok=True)
for f in glob.glob(f"{out}/batch-*.json"): os.remove(f)

batches = [picked[i:i+a.size] for i in range(0, len(picked), a.size)]
for bi, b in enumerate(batches, 1):
    items = []
    for aid, r, o in b:
        tp = f"{EVAL}/reports/{aid}.json"
        req = ""
        if os.path.exists(tp):
            try: req = json.load(open(tp, encoding="utf-8")).get("request", "")
            except Exception: pass
        # 盲標：不放 model_*、不放 Layer 1 分數、不放 needs_layer2
        items.append({
            "agent_id": aid,
            "subagent_type": r.get("agent_type"),
            "task_prompt": (req or o.get("description") or "")[:a.max_prompt],
            "actual_output": reports.get(aid, "")[:a.max_output],
            "evidence": {
                "tool_calls_used": o.get("tool_uses"),
                "wall_clock_s": round(o["duration_ms"]/1000) if o.get("duration_ms") else None,
                "needed_fix_round_afterwards": o.get("needed_fix_round"),
            },
        })
    json.dump({"instructions": os.path.expanduser("~/.config/claude/model-router/JUDGE.md"),
               "items": items},
              open(f"{out}/batch-{bi:02d}.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)

print(f"-> {len(batches)} 個批次在 {out}/")
print(f"   有實際產出可讀: {sum(1 for aid,_,_ in picked if reports.get(aid))}/{len(picked)}")
missing = [aid for aid,_,_ in picked if not reports.get(aid)]
if missing:
    print(f"   ⚠ {len(missing)} 筆沒有產出（ARCHIVE_SUBAGENT_REPORTS 沒開？）judge 只能靠 prompt + evidence 判")
