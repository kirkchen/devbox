"""Router policy — Jev 的答案 -> tier。

這支是唯一的決策實作：eval runner 跟 hook 都呼叫它，避免兩邊漂移。
tier: 0=haiku 1=sonnet 2=opus
"""
import json as _json, os as _os

TIERS = ["haiku", "sonnet", "opus"]

# --- 可調參數 ---
# 預設值。thresholds.json 存在就覆蓋，讓 tune.py 能改門檻而不動程式碼。
DEFAULTS = {
    "UP_CONF":      0.70,   # Guard: 升級所需信心
    "DOWN_CONF":    0.80,   # Guard: 降級所需信心（刻意較嚴）
    "FLOOR_CONF":   0.60,   # 低於此信心一律給 sonnet
    "LOOKUP_NOUL":  0.70,   # 判定為純唯讀查找的門檻
    "LOOKUP_DEPTH": 0.70,
    "SPEC_CHEAP":   1.40,   # 指示完整到可視為謄寫
    "CHEAP_DEPTH":  1.60,
    "DEPTH_MID":    1.30,   # 低於此推理需求給 sonnet
    "SPEC_MID":     1.00,   # 推理重但指示夠完整 -> sonnet
    "CONSEQ_FLOOR": 1.40,   # 高後果不下放到最便宜那級
}

def load(path=None):
    p = path or _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "thresholds.json")
    t = dict(DEFAULTS)
    if _os.path.exists(p):
        try:
            t.update({k: v for k, v in _json.load(open(p, encoding="utf-8")).items() if k in DEFAULTS})
        except Exception:
            pass
    return t

T = load()
UP_CONF, DOWN_CONF, FLOOR_CONF = T["UP_CONF"], T["DOWN_CONF"], T["FLOOR_CONF"]


def decide_tier(a, t=None):
    """a: {question_id: {"score"|"noul": v, "confidence": c}}"""
    t = t or T
    depth  = a["reasoning_depth"]["score"]
    spec   = a["spec_completeness"]["score"]
    lookup = a["is_readonly_lookup"]["noul"]
    conseq = a["consequence_of_miss"]["score"]
    conf   = min(a["reasoning_depth"]["confidence"],
                 a["spec_completeness"]["confidence"])

    if conf < t["FLOOR_CONF"]:
        return 1, conf, "信心不足"

    if lookup > t["LOOKUP_NOUL"] and depth < t["LOOKUP_DEPTH"]:
        tier, why = 0, "純唯讀查找"
    elif spec > t["SPEC_CHEAP"] and depth < t["CHEAP_DEPTH"]:
        tier, why = 0, "指示已寫完整"
    elif depth < t["DEPTH_MID"]:
        tier, why = 1, "推理需求中等"
    elif spec > t["SPEC_MID"]:
        tier, why = 1, "指示夠完整"
    else:
        tier, why = 2, "需自行拆解"

    # 漏掉問題後果嚴重的工作不下放到最便宜那級
    if conseq > t["CONSEQ_FLOOR"] and tier < 1:
        tier, why = 1, why + "+高後果下限"
    return tier, conf, why


def apply_mode(tier, conf, requested_tier, retry_prob, mode, t=None):
    """回傳 (final_tier or None, action)。None = 不動作。"""
    t = t or T
    if requested_tier is None:                      # Fill
        return tier, "fill"
    if mode == "fill-only":
        return None, "skip:fill-only"
    if tier > requested_tier:
        if conf < t["UP_CONF"]:
            return None, "skip:升級信心不足"
        return requested_tier + 1, "guard:up"
    if tier < requested_tier:
        if retry_prob > 0.5:
            return None, "skip:重試任務不降級"
        if conf < t["DOWN_CONF"]:
            return None, "skip:降級信心不足"
        return requested_tier - 1, "guard:down"
    return None, "skip:一致"


def tier_of(model_name):
    if not model_name:
        return None
    m = model_name.lower()
    if "haiku" in m:  return 0
    if "sonnet" in m: return 1
    if "opus" in m or "fable" in m: return 2
    return None
