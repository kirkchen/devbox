"""門檻與位置規則。線上 hook 與離線 tune 共用同一份，避免漂移。

起始值來自 200 筆語料的量測（spec 2.3、2.4 節）：
  noise>=0.7 + 不刪頭尾 → 省 7.9%、誤刪 3.7%、只有 2.5% 的 result 有誤刪
這是唯一「逐段還原」與「整份重讀」兩種情境都為正的操作點。
"""
import json, os

DEFAULTS = {
    "noise_min": 0.7,        # 這段重複別處已有的內容
    "uniq_max": 0.4,         # 這段的事實別處沒有 —— 高就不能刪
    "min_chunks": 3,         # 段數太少就整份放行
    "max_drop_ratio": 0.6,   # 單份最多刪掉的字元比例
}


def load(path=None):
    p = path or os.path.expanduser(
        os.environ.get("TOOL_REDUCE_THRESHOLDS",
                       "~/.config/claude/tool-reduce/thresholds.json"))
    t = dict(DEFAULTS)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as fh:
                t.update({k: v for k, v in json.load(fh).items() if k in DEFAULTS})
        except Exception:
            pass
    return t


def decide(scores, chunk_chars, t=None):
    """回傳與 scores 等長的布林清單，True 代表刪掉。"""
    t = t or load()
    n = len(scores)
    if n < t["min_chunks"] or n != len(chunk_chars):
        return [False] * n

    drop = []
    for i, s in enumerate(scores):
        noise, uniq = s.get("noise"), s.get("uniq")
        ok = (
            i != 0 and i != n - 1                       # 不刪頭尾
            and isinstance(noise, (int, float))          # 分數缺漏就留
            and isinstance(uniq, (int, float))
            and noise >= t["noise_min"]
            and uniq <= t["uniq_max"]
        )
        drop.append(bool(ok))

    # 單份上限：超過就從 noise 最低的開始留回來
    total = sum(chunk_chars) or 1
    order = sorted((i for i, d in enumerate(drop) if d),
                   key=lambda i: scores[i]["noise"])
    while sum(c for c, d in zip(chunk_chars, drop) if d) / total > t["max_drop_ratio"]:
        if not order:
            break
        drop[order.pop(0)] = False
    return drop
