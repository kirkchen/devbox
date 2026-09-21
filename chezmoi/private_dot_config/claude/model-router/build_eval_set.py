import json, re, os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy

SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
u = json.load(open(f"{SP}/agent_calls_enriched.json", encoding="utf-8"))

def shape(d):
    d = d or ""
    if re.match(r'^Implement Task', d):  return "implement-task"
    if re.match(r'^Review Task', d):     return "review-task"
    if re.match(r'^Re-review', d):       return "re-review"
    if "whole-branch" in d:              return "final-branch-review"
    if re.search(r'(Security|SDET|Staff|Spec) (review|audit|eng)', d, re.I): return "mr-role-review"
    if re.search(r'review|審|檢視', d, re.I): return "other-review"
    return "other"

# --- 返工偵測：同 session 內，某個 Task N 後續出現 Re-review/fix round ---
rework = collections.defaultdict(set)   # file -> {task numbers needing fixes}
for r in u:
    d = r["description"] or ""
    if re.match(r'^Re-review Task', d) or re.search(r'fix round', d, re.I):
        m = re.search(r'Task (\d+)', d)
        if m: rework[r["file"]].add(m.group(1))

rows = []
for i, r in enumerate(sorted(u, key=lambda x: x["ts"])):
    s = shape(r["description"])
    req_tier = policy.tier_of(r["model_requested"])
    res_tier = policy.tier_of(r["model_resolved"])
    tn = re.search(r'Task (\d+)', r["description"] or "")
    needed_fix = None
    if s == "implement-task" and tn:
        needed_fix = tn.group(1) in rework[r["file"]]

    tu = r["tool_uses"]
    if tu is None:                 pre = "無執行資料"
    elif res_tier == 2 and tu <= 12: pre = "疑似過度配置"
    elif res_tier == 2 and tu <= 20: pre = "偏過度配置"
    elif res_tier is not None and res_tier <= 1 and tu >= 45: pre = "疑似配置不足"
    else:                          pre = "看起來合理"

    # 優先標註：Guard 案例、疑似過度/不足、有返工訊號的
    prio = 1 if (req_tier is not None and pre.endswith("配置")) \
                or pre in ("疑似過度配置", "疑似配置不足") \
                or needed_fix else 2

    rows.append({
        "id": f"ev-{i+1:03d}",
        "kind": "guard" if req_tier is not None else "fill",
        "priority": prio,
        "ts": r["ts"], "session": r["file"][:8],
        "subagent_type": r["subagent_type"], "shape": s,
        "description": r["description"],
        "model_requested": r["model_requested"], "requested_tier": req_tier,
        "model_resolved": r["model_resolved"], "resolved_tier": res_tier,
        "outcome": {"tool_uses": tu, "subagent_tokens": r["subagent_tokens"],
                    "duration_s": round(r["duration_ms"]/1000) if r["duration_ms"] else None,
                    "needed_fix_round": needed_fix},
        "prelabel": pre,
        "label": {"expected_tier": None, "labeler_confidence": None, "note": ""},
        "prompt": r["prompt"],
    })

out = f"{SP}/eval/eval_set.json"
json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"eval set: {len(rows)} 筆 -> {out}\n")
print("kind      :", dict(collections.Counter(r['kind'] for r in rows)))
print("priority 1:", sum(1 for r in rows if r['priority']==1))
print("prelabel  :", dict(collections.Counter(r['prelabel'] for r in rows)))
print("\n=== implement-task：返工 vs 實際模型 ===")
g=collections.defaultdict(lambda: [0,0])
for r in rows:
    if r["outcome"]["needed_fix_round"] is not None:
        t = policy.TIERS[r["resolved_tier"]] if r["resolved_tier"] is not None else "?"
        g[t][1]+=1
        if r["outcome"]["needed_fix_round"]: g[t][0]+=1
for t,(fix,tot) in sorted(g.items()):
    print(f"  {t:<8} 需返工 {fix}/{tot}")
