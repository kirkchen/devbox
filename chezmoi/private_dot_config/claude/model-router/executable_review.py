#!/usr/bin/env python3
"""Model router 覆盤：把 hook 的決策紀錄跟 transcript 的實際結果接起來。

用法:
  python3 review.py                          # 全部
  python3 review.py --since 2026-09-20
  python3 review.py --log <path> --projects '~/.claude/projects/*myproject*'
"""
import json, os, sys, argparse, statistics, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import outcomes, policy

DEFAULT_LOG = os.path.expanduser("~/.config/claude/model-router/decisions.jsonl")
ap = argparse.ArgumentParser()
ap.add_argument("--log", default=DEFAULT_LOG)
ap.add_argument("--projects", default="~/.claude/projects/*")
ap.add_argument("--since")
args = ap.parse_args()

if not os.path.exists(args.log):
    sys.exit(f"找不到決策紀錄: {args.log}\nhook 還沒跑過，或 ROUTER_LOG 指到別的位置。")

dec = []
for line in open(args.log, encoding="utf-8"):
    line = line.strip()
    if not line: continue
    try: d = json.loads(line)
    except Exception: continue
    if args.since and d.get("ts", "") < args.since: continue
    dec.append(d)
if not dec:
    sys.exit("紀錄是空的（或都被 --since 濾掉了）")

out = outcomes.harvest(args.projects)
for d in dec:
    d["outcome"] = out.get(d.get("tool_use_id"), {})

T = lambda t: policy.TIERS[t] if t is not None else "—"
print(f"=== Model router 覆盤 ===")
print(f"紀錄 {len(dec)} 筆   {dec[0]['ts'][:16]} ~ {dec[-1]['ts'][:16]}")
print(f"接到 transcript 結果: {sum(1 for d in dec if d['outcome'].get('tool_uses') is not None)} 筆\n")

print("--- 執行模式 ---")
for k, v in collections.Counter(d.get("mode") for d in dec).most_common():
    print(f"  {k:<12} {v}")

lat = [d["jev_latency_ms"] for d in dec if d.get("jev_latency_ms")]
if lat:
    lat.sort()
    p = lambda q: lat[min(len(lat)-1, int(len(lat)*q))]
    print(f"\n--- Jev 延遲 --- p50={p(.5)}ms  p90={p(.9)}ms  max={lat[-1]}ms")
errs = [d for d in dec if d.get("error")]
if errs:
    print(f"  失敗 {len(errs)} 筆（已 fail-open，不影響 dispatch）:",
          dict(collections.Counter(d["error"][:40] for d in errs)))

print("\n--- 決策分布 ---")
for k, v in collections.Counter(d.get("action") for d in dec).most_common():
    print(f"  {k:<26} {v}")

# 基準線：各 (shape-ish, tier) 的歷史 tool_uses 中位數
base = collections.defaultdict(list)
for o in out.values():
    if o.get("tool_uses") is not None and o.get("model_resolved"):
        base[(o.get("subagent_type"), policy.tier_of(o["model_resolved"]))].append(o["tool_uses"])
base = {k: statistics.median(v) for k, v in base.items() if len(v) >= 3}

applied = [d for d in dec if d.get("model_applied")]
print(f"\n--- 實際生效的改動 ({len(applied)} 筆) ---")
if not applied:
    print("  無（shadow 模式，或全部 skip）")
for d in applied:
    o = d["outcome"]
    tu = o.get("tool_uses")
    b = base.get((d.get("subagent_type"), policy.tier_of(d["model_applied"])))
    cmp = ""
    if tu is not None and b:
        cmp = f"  (同層歷史中位數 {b:.0f}，{'高' if tu > b*1.5 else '低' if tu < b*0.7 else '相當'})"
    fix = o.get("needed_fix_round")
    print(f"  {d['ts'][:16]} {d.get('description','')[:40]:<40} "
          f"{T(d.get('requested_tier')):>7} -> {d['model_applied']:<7} "
          f"turns={tu if tu is not None else '?':<5}{cmp}"
          f"{'  ⚠ 需返工' if fix else ''}")

flag = [d for d in applied if d["outcome"].get("needed_fix_round")
        or (d["outcome"].get("tool_uses") and
            base.get((d.get("subagent_type"), policy.tier_of(d["model_applied"]))) and
            d["outcome"]["tool_uses"] > base[(d.get("subagent_type"), policy.tier_of(d["model_applied"]))] * 1.8)]
print(f"\n--- 要人工看的 ({len(flag)} 筆) ---")
for d in flag:
    print(f"  {d.get('description')}  action={d.get('action')}  why={d.get('why')}")
    print(f"    Jev: depth={d['jev']['reasoning_depth']['score']:.2f} "
          f"spec={d['jev']['spec_completeness']['score']:.2f} "
          f"conf={d.get('pred_conf',0):.2f}")
if not flag:
    print("  無")

shadow = [d for d in dec if d.get("mode") == "shadow" and d.get("action", "").startswith(("fill", "guard"))]
if shadow:
    print(f"\n--- shadow 模式下「本來會改」的 {len(shadow)} 筆 ---")
    for k, v in collections.Counter(
            (T(d.get("requested_tier")), T(d.get("pred_tier"))) for d in shadow).most_common():
        print(f"  {k[0]:>7} -> {k[1]:<7} {v}")
