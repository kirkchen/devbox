#!/usr/bin/env python3
"""對 eval_set.json 跑 Jev，套 policy，跟人工標註比對。

用法:
  python3 run_eval.py                # 只跑已標註的
  python3 run_eval.py --all          # 全跑（沒標註的只輸出預測，不計分）
  python3 run_eval.py --limit 20
  python3 run_eval.py --mode fill-only
需要 TYPESAFE_API_KEY。結果快取在 .cache.json，重跑不會重複付費。
"""
import json, os, sys, time, argparse, hashlib, collections
import urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.typesafe.ai/v1/systemone"

ap = argparse.ArgumentParser()
ap.add_argument("--all", action="store_true")
ap.add_argument("--limit", type=int)
ap.add_argument("--mode", default="full", choices=["full", "fill-only"])
ap.add_argument("--kind", choices=["fill", "guard"])
args = ap.parse_args()

key = os.environ.get("TYPESAFE_API_KEY")
if not key:
    sys.exit("需要 TYPESAFE_API_KEY（export 或寫進 ~/.config/claude/typesafe.env 再 source）")

spec = json.load(open(f"{HERE}/questions.json", encoding="utf-8"))
rows = json.load(open(f"{HERE}/eval_set.json", encoding="utf-8"))
cache_path = f"{HERE}/.cache.json"
cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}

sel = [r for r in rows if args.all or r["label"]["expected_tier"] is not None]
if args.kind: sel = [r for r in sel if r["kind"] == args.kind]
if args.limit: sel = sel[:args.limit]
print(f"跑 {len(sel)} 筆（mode={args.mode}）\n")

def ask(prompt, subagent_type):
    ck = hashlib.sha256((prompt + subagent_type + json.dumps(spec, sort_keys=True)).encode()).hexdigest()
    if ck in cache:
        return cache[ck], 0.0
    body = json.dumps({"model": spec["model"],
                       "state": {"agent_type": subagent_type, "task": prompt},
                       "questions": spec["questions"]}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    t0 = time.time()
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                res = json.loads(r.read())
            cache[ck] = res
            return res, time.time() - t0
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < 3:
                time.sleep(2 ** attempt); continue
            raise

lat, out = [], []
for i, r in enumerate(sel, 1):
    try:
        res, dt = ask(r["prompt"], r["subagent_type"] or "general-purpose")
    except Exception as e:
        print(f"[{i}/{len(sel)}] {r['id']} 失敗: {e}"); continue
    if dt: lat.append(dt)
    a = res["answers"]
    tier, conf, why = policy.decide_tier(a)
    final, action = policy.apply_mode(tier, conf, r["requested_tier"],
                                      a["is_retry_after_failure"]["noul"], args.mode)
    out.append({**r, "jev": a, "pred_tier": tier, "pred_conf": conf, "why": why,
                "final_tier": final, "action": action})
    if i % 10 == 0 or i == len(sel):
        print(f"  {i}/{len(sel)}")
        json.dump(cache, open(cache_path, "w"), ensure_ascii=False)

json.dump(cache, open(cache_path, "w"), ensure_ascii=False)
json.dump(out, open(f"{HERE}/eval_result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

if lat:
    lat.sort()
    print(f"\nJev 延遲: p50={lat[len(lat)//2]:.2f}s p90={lat[min(len(lat)-1,int(len(lat)*.9))]:.2f}s max={lat[-1]:.2f}s")
    print(f"（{len(lat)} 次實際呼叫，其餘來自快取）")

print("\n=== 決策分布 ===")
for k, v in collections.Counter(o["action"] for o in out).most_common():
    print(f"  {k:<26} {v}")

scored = [o for o in out if o["label"]["expected_tier"] is not None]
if not scored:
    print("\n（尚無人工標註，只輸出預測，不計分）")
    print("\n=== 預測 vs 當時實際用的模型 ===")
    for k, v in collections.Counter(
            (policy.TIERS[o['resolved_tier']] if o['resolved_tier'] is not None else '?',
             policy.TIERS[o['pred_tier']]) for o in out).most_common():
        print(f"  實際={k[0]:<8} -> Jev={k[1]:<8} {v}")
    sys.exit(0)

print(f"\n=== 對 {len(scored)} 筆已標註計分 ===")
cm = collections.Counter()
bad_down = bad_up = 0
for o in scored:
    exp = o["label"]["expected_tier"]
    got = o["final_tier"] if o["final_tier"] is not None else o["resolved_tier"]
    cm[(exp, got)] += 1
    if got is not None and got < exp: bad_down += 1
    if got is not None and got > exp: bad_up += 1
print(f"{'標註\\實際':<12}" + "".join(f"{t:>9}" for t in policy.TIERS))
for e in range(3):
    print(f"{policy.TIERS[e]:<12}" + "".join(f"{cm[(e,g)]:>9}" for g in range(3)))
n = len(scored)
print(f"\n正確        {sum(cm[(i,i)] for i in range(3))}/{n} = {sum(cm[(i,i)] for i in range(3))/n*100:.0f}%")
print(f"錯誤降級    {bad_down}/{n} = {bad_down/n*100:.0f}%   ← 關鍵指標")
print(f"錯誤升級    {bad_up}/{n} = {bad_up/n*100:.0f}%")
