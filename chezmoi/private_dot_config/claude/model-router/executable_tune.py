#!/usr/bin/env python3
"""門檻自動調校：拿已標註的 corpus 重放決策，找更好的門檻組合。

不需要重新呼叫 Jev——決策紀錄存了原始答案，換門檻只是重算，零成本零延遲。

  tune.py                  # 只報告，不動任何東西
  tune.py --apply          # 通過閘門才寫入 thresholds.json

閘門（任一不過就拒絕套用，不會默默照跑）：
  1. 人工基準至少 MIN_HUMAN 筆
  2. judge 跟人工基準的一致率 >= MIN_AGREEMENT
  3. 人工基準不能太舊：自最後一筆人工標註以來，新增樣本不得超過 MAX_DRIFT
  4. 新門檻的錯誤降級率不得超過 MAX_BAD_DOWNGRADE
"""
import json, os, sys, argparse, itertools, collections, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import policy

HERE = os.path.dirname(os.path.abspath(__file__))
EVAL = os.path.expanduser(os.environ.get("EVAL_DIR", "~/.local/share/model-router-eval"))
LOG = os.path.expanduser(os.environ.get("ROUTER_LOG", "~/.config/claude/model-router/decisions.jsonl"))

MIN_HUMAN = 10
MIN_AGREEMENT = 0.70
MAX_DRIFT = 200
MAX_BAD_DOWNGRADE = 0.05

ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
ap.add_argument("--top", type=int, default=8)
ap.add_argument("--max-bad-downgrade", type=float, default=MAX_BAD_DOWNGRADE)
ap.add_argument("--allow-worse-downgrade", action="store_true",
                help="允許選擇錯誤降級率高於現行的組合（預設不允許）")
a = ap.parse_args()

def jsonl(p):
    if not os.path.exists(p): return []
    out = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if not line: continue
        try: out.append(json.loads(line))
        except Exception: pass
    return out

# --- 標註 ---
labels = collections.defaultdict(dict)
for r in jsonl(f"{EVAL}/labels.jsonl"):
    labels[r["agent_id"]][r["source"]] = r
human = {k: v["human"] for k, v in labels.items() if "human" in v}
judge = {k: v["judge"] for k, v in labels.items() if "judge" in v}

# --- 決策紀錄（含 Jev 原始答案），用 agent_id 接標註 ---
corpus_agent = {r["agent_id"]: r for r in jsonl(f"{EVAL}/corpus.jsonl") if r.get("agent_id")}
dec = [d for d in jsonl(LOG) if d.get("jev")]
# decisions.jsonl 有 tool_use_id、corpus.jsonl 有 agent_id，兩者的對應只存在於
# 主 transcript 的 toolUseResult.agentId，所以要從那裡接。
import outcomes
tid2aid = {v["tool_use_id"]: aid
           for aid, v in outcomes.by_agent_id(
               os.environ.get("ROUTER_PROJECTS", "~/.claude/projects/*")).items()
           if v.get("tool_use_id")}

samples = []
for d in dec:
    aid = d.get("agent_id") or tid2aid.get(d.get("tool_use_id"))
    lab = human.get(aid) or judge.get(aid)
    if aid and lab:
        samples.append({"jev": d["jev"], "expected": lab["expected_tier"],
                        "requested": d.get("requested_tier"),
                        "baseline": d.get("requested_tier") if d.get("requested_tier") is not None else 2,
                        "src": "human" if aid in human else "judge"})

print(f"決策紀錄 {len(dec)} 筆，其中有標註可比對的 {len(samples)} 筆"
      f"（人工 {sum(1 for s in samples if s['src']=='human')} / judge {sum(1 for s in samples if s['src']=='judge')}）")
if len(samples) < 20:
    sys.exit("\n樣本太少（<20），還不能調校。先讓 Layer 1 多收一陣子，再跑 /judge-backlog。")

GRID = {
    "SPEC_CHEAP":   [1.2, 1.3, 1.4, 1.5, 1.6],
    "DEPTH_MID":    [1.0, 1.15, 1.3, 1.45],
    "SPEC_MID":     [0.8, 1.0, 1.2, 1.4],
    "CONSEQ_FLOOR": [1.2, 1.4, 1.6],
    "DOWN_CONF":    [0.70, 0.80, 0.90],
}

def score(t):
    bad_down = bad_up = exact = 0
    saved = 0
    for s in samples:
        tier, _, _ = policy.decide_tier(s["jev"], t)
        e = s["expected"]
        if tier == e: exact += 1
        elif tier < e: bad_down += 1
        else: bad_up += 1
        saved += s["baseline"] - tier          # tier 級距差當成本代理
    n = len(samples)
    return {"bad_down": bad_down/n, "bad_up": bad_up/n, "exact": exact/n, "saved": saved/n}

base = dict(policy.DEFAULTS)
cur = score(base)
print(f"\n現行門檻: 正確 {cur['exact']*100:.0f}%  錯誤降級 {cur['bad_down']*100:.1f}%  "
      f"錯誤升級 {cur['bad_up']*100:.1f}%  平均省下 {cur['saved']:.2f} 級")

results = []
for combo in itertools.product(*GRID.values()):
    t = dict(base); t.update(dict(zip(GRID.keys(), combo)))
    results.append((score(t), t))

# 排序刻意不是「在上限內省最多」。那會為了一點成本把錯誤降級率推到天花板——
# 錯誤降級正是這個系統最貴的失誤（便宜模型在多步驟任務上會多跑 2-3 倍輪次）。
# 預設只考慮「錯誤降級不比現行差」的組合，在其中才去比省多少。
ceiling = a.max_bad_downgrade
safe_ceiling = cur["bad_down"] if not a.allow_worse_downgrade else ceiling
ok = [r for r in results if r[0]["bad_down"] <= min(ceiling, safe_ceiling + 1e-9)]
mode_note = ("錯誤降級率不得高於現行 %.1f%%" % (cur["bad_down"]*100)) if not a.allow_worse_downgrade \
            else ("錯誤降級率上限 %.0f%%（已允許比現行差）" % (ceiling*100))
ok.sort(key=lambda r: (-r[0]["saved"], r[0]["bad_down"]))
print(f"\n{len(results)} 種組合，符合「{mode_note}」的有 {len(ok)} 種")
if not ok:
    print("\n沒有組合能在不惡化錯誤降級率的前提下改善。")
    print("這通常代表現行門檻已在局部最佳，問題出在 questions.json 的 criteria 而不是門檻。")
    print("真的要拿安全性換成本，加 --allow-worse-downgrade 再跑一次。")
    sys.exit(0)

print(f"\n=== 前 {a.top} 名（先看省最多，再看錯誤降級低）===")
print(f"{'正確':>6}{'錯降':>7}{'錯升':>7}{'省級':>7}   門檻")
for sc, t in ok[:a.top]:
    diff = {k: v for k, v in t.items() if base[k] != v}
    print(f"{sc['exact']*100:>5.0f}%{sc['bad_down']*100:>6.1f}%{sc['bad_up']*100:>6.1f}%{sc['saved']:>7.2f}   "
          + (", ".join(f"{k}={v}" for k, v in diff.items()) or "(現行)"))

best_sc, best_t = ok[0]
if not a.apply:
    print("\n只報告，沒有改動。要套用加 --apply（會先過閘門）。")
    sys.exit(0)

print("\n=== 套用閘門 ===")
fails = []
if len(human) < MIN_HUMAN:
    fails.append(f"人工基準只有 {len(human)} 筆，需要 {MIN_HUMAN} 筆")
both = [(judge[k]["expected_tier"], human[k]["expected_tier"]) for k in human if k in judge]
if both:
    agree = sum(1 for j, h in both if j == h) / len(both)
    print(f"  人機一致率 {agree*100:.0f}%（{len(both)} 筆重疊）")
    if agree < MIN_AGREEMENT:
        fails.append(f"人機一致率 {agree*100:.0f}% < {MIN_AGREEMENT*100:.0f}%，judge 的標註還不可信")
else:
    fails.append("人工基準與 judge 沒有重疊，算不出一致率")
if human:
    last = max(v.get("judged_at", "") for v in human.values())
    newer = sum(1 for r in corpus_agent.values() if r.get("ts", "") > last)
    print(f"  最後人工標註 {last[:10]}，其後新增 {newer} 筆樣本")
    if newer > MAX_DRIFT:
        fails.append(f"人工基準之後已新增 {newer} 筆 > {MAX_DRIFT}，基準過期，先補標")
if best_sc["bad_down"] > a.max_bad_downgrade:
    fails.append(f"最佳組合錯誤降級率 {best_sc['bad_down']*100:.1f}% 超過上限")
if not a.allow_worse_downgrade and best_sc["bad_down"] > cur["bad_down"] + 1e-9:
    fails.append(f"最佳組合錯誤降級率 {best_sc['bad_down']*100:.1f}% 高於現行 {cur['bad_down']*100:.1f}%")
if best_sc["saved"] <= cur["saved"] + 1e-9:
    fails.append("最佳組合沒有比現行更好，不需要改")

if fails:
    print("\n拒絕套用：")
    for f in fails: print(f"  ✗ {f}")
    sys.exit(1)

out = f"{HERE}/thresholds.json"
if os.path.exists(out):
    os.replace(out, out + ".bak")
json.dump({**best_t, "_tuned_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
           "_samples": len(samples), "_score": best_sc},
          open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(f"\n✓ 已寫入 {out}（舊值備份為 thresholds.json.bak）")
