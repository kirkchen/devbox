#!/usr/bin/env python3
"""把 eval set 切成「盲標批次」交給 judge subagent。

盲標 = judge 看不到當時用了哪個模型、也看不到 prelabel。
看得到就會被錨定，標出來的東西只是在複述當初的決定。

用法:
  python3 make_label_batches.py --priority 1 --size 8
  python3 make_label_batches.py --ids ev-050,ev-051
"""
import json, os, argparse, textwrap

EVAL = os.path.expanduser("~/.local/share/model-router-eval")
ap = argparse.ArgumentParser()
ap.add_argument("--priority", type=int)
ap.add_argument("--kind", choices=["fill", "guard"])
ap.add_argument("--ids")
ap.add_argument("--size", type=int, default=8)
ap.add_argument("--max-prompt", type=int, default=6000)
ap.add_argument("--out", default=f"{EVAL}/batches")
a = ap.parse_args()

rows = json.load(open(f"{EVAL}/eval_set.json", encoding="utf-8"))
reports = {}
rp = f"{EVAL}/reports_by_tooluse.json"
if os.path.exists(rp):
    reports = json.load(open(rp, encoding="utf-8"))

sel = [r for r in rows if r["label"]["expected_tier"] is None]
if a.priority: sel = [r for r in sel if r["priority"] == a.priority]
if a.kind:     sel = [r for r in sel if r["kind"] == a.kind]
if a.ids:      sel = [r for r in rows if r["id"] in set(a.ids.split(","))]

os.makedirs(a.out, exist_ok=True)
batches = [sel[i:i+a.size] for i in range(0, len(sel), a.size)]
for bi, b in enumerate(batches, 1):
    items = []
    for r in b:
        o = r["outcome"]
        # 盲標：不放 model_requested / model_resolved / prelabel
        item = {
            "id": r["id"],
            "subagent_type": r["subagent_type"],
            "task_prompt": r["prompt"][:a.max_prompt],
            "prompt_truncated": len(r["prompt"]) > a.max_prompt,
            "evidence": {
                "tool_calls_used": o["tool_uses"],
                "wall_clock_s": o["duration_s"],
                "needed_fix_round_afterwards": o["needed_fix_round"],
            },
        }
        rep = reports.get(r.get("tool_use_id", ""))
        if rep:
            item["actual_output"] = rep[:8000]
        items.append(item)
    p = f"{a.out}/batch-{bi:02d}.json"
    json.dump({"instructions_file": os.path.expanduser("~/.config/claude/model-router/JUDGE.md"), "items": items},
              open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"{len(sel)} 筆 -> {len(batches)} 個批次，寫到 {a.out}/")
print(f"有實際產出可讀的: {sum(1 for r in sel if reports.get(r.get('tool_use_id','')))}/{len(sel)}")
