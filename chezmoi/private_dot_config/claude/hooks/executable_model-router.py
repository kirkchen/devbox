#!/usr/bin/env python3
"""PreToolUse(Agent): 依任務內容決定 subagent 要跑哪個模型。

決策邏輯不在這裡——全部在 ~/.config/claude/model-router/policy.py，
eval 與 tune 共用同一份實作，避免線上跟離線漂移。

這支只負責：取輸入 -> 問 Jev -> 套 policy -> 輸出 updatedInput -> 寫紀錄。
任何異常都 fail-open（不輸出，dispatch 照原樣進行）。

模式由 ROUTER_MODE 決定：off（預設）| shadow | fill-only | full
"""
import json, os, sys, time, hashlib, datetime
import urllib.request, urllib.error

R = os.path.expanduser(os.environ.get("ROUTER_HOME", "~/.config/claude/model-router"))
LOG = os.path.expanduser(os.environ.get("ROUTER_LOG", f"{R}/decisions.jsonl"))
API = os.environ.get("ROUTER_API", "https://api.typesafe.ai/v1/systemone")
TIMEOUT = float(os.environ.get("ROUTER_TIMEOUT", "2.5"))
MAX_PROMPT = 16000           # 送進 Jev 的上限，避開 state 過大掉準
ROUTABLE = {"general-purpose", "claude", "Explore", "Plan"}


def bail():
    sys.exit(0)


def load_env(path):
    """讀 KEY=VALUE 檔，不 source shell（避免執行任意內容）。"""
    if not os.path.exists(path):
        return
    try:
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception:
        pass


def main():
    load_env(os.path.expanduser("~/.config/claude/typesafe.env"))
    mode = os.environ.get("ROUTER_MODE", "off")
    if mode not in ("shadow", "fill-only", "full"):
        bail()
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        bail()

    try:
        inp = json.load(sys.stdin)
    except Exception:
        bail()

    ti = inp.get("tool_input") or {}
    subagent = ti.get("subagent_type")
    prompt = ti.get("prompt") or ""
    requested = ti.get("model")
    tool_use_id = inp.get("tool_use_id")

    # eval-judge 由 /judge-backlog 派、模型固定在 frontmatter，不路由
    if subagent == "eval-judge" or subagent not in ROUTABLE or not prompt:
        bail()

    sys.path.insert(0, R)
    try:
        import policy
    except Exception:
        bail()

    req_tier = policy.tier_of(requested)
    if requested and req_tier is None:      # 認不得的 model id，不碰
        bail()

    try:
        spec = json.load(open(f"{R}/questions.json", encoding="utf-8"))
    except Exception:
        bail()

    body = json.dumps({
        "model": spec["model"],
        "state": {"agent_type": subagent, "task": prompt[:MAX_PROMPT]},
        "questions": spec["questions"],
    }).encode()

    t0 = time.time()
    err = None
    answers = None
    try:
        rq = urllib.request.Request(API, data=body, headers={
            "Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        with urllib.request.urlopen(rq, timeout=TIMEOUT) as r:
            answers = json.loads(r.read()).get("answers")
    except Exception as e:
        err = f"{type(e).__name__}: {e}"[:200]
    latency = int((time.time() - t0) * 1000)

    rec = {
        "ts": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "session_id": inp.get("session_id"), "tool_use_id": tool_use_id,
        "cwd": inp.get("cwd"), "subagent_type": subagent,
        "description": ti.get("description"), "prompt_chars": len(prompt),
        "prompt_sha": hashlib.sha256(prompt.encode()).hexdigest()[:16],
        "mode": mode, "model_requested": requested, "requested_tier": req_tier,
        "jev_latency_ms": latency, "error": err,
    }

    applied = None
    if answers and not err:
        try:
            tier, conf, why = policy.decide_tier(answers)
            final, action = policy.apply_mode(
                tier, conf, req_tier,
                answers.get("is_retry_after_failure", {}).get("noul", 0.0),
                "fill-only" if mode == "fill-only" else "full")
            rec.update({"jev": answers, "pred_tier": tier, "pred_conf": conf,
                        "why": why, "action": action})
            if final is not None and mode != "shadow":
                applied = policy.TIERS[final]
        except Exception as e:
            rec["error"] = f"policy: {type(e).__name__}: {e}"[:200]
    rec["model_applied"] = applied

    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

    # --- 可見度 ---
    # off     完全靜默
    # applied 只有實際改動、以及 shadow 模式下「本來會改」時出聲（預設）
    # all     連維持原樣與 Jev 失敗都出聲
    notify = os.environ.get("ROUTER_NOTIFY", "applied")
    frm = requested or "inherit"
    conf_s = f"{rec['pred_conf']:.2f}" if rec.get("pred_conf") is not None else "?"
    would = rec.get("action", "").startswith(("fill", "guard"))

    msg = None
    if rec.get("error"):
        if notify == "all":
            msg = f"router · Jev 無回應，維持原設定"
    elif applied:
        msg = f"router · {subagent} · {frm} → {applied} · {rec.get('why','')} ({conf_s})"
    elif mode == "shadow" and would:
        msg = (f"router[shadow] · {subagent} · {frm} ⇢ "
               f"{policy.TIERS[rec['pred_tier']]} · {rec.get('why','')} ({conf_s})")
    elif notify == "all":
        msg = f"router · {subagent} · {frm} 維持 · {rec.get('action','')}"

    out = {}
    if applied:
        # updatedInput 是整份取代而非合併（實測；官方文件寫錯），
        # 必須回傳完整 tool_input 再改 model，否則 Agent 呼叫會 schema 驗證失敗。
        out["hookSpecificOutput"] = {
            "hookEventName": "PreToolUse",
            "updatedInput": {**ti, "model": applied},
        }
    if msg and notify != "off":
        out["systemMessage"] = msg
    if out:
        print(json.dumps(out, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        pass   # fail-open：任何未預期錯誤都不影響 dispatch
    sys.exit(0)
