"""門檻與位置規則。線上 hook 與離線 tune 共用同一份，避免漂移。

起始值來自 200 筆語料的離線研究（spec 2.3、2.4 節），那份研究預估
noise>=0.7 + 不刪頭尾 會省 7.9%。那個數字已經被實測取代：拿真正上線的
pipeline（含實際 chunker）跑 120 筆真實 tool result，同一組門檻量到的是
省 2.2%。差距來自離線研究用的是另一份 chunker，切法不同、段落分佈跟著
不同（README「目前的操作點」那一節有完整的比較）。

照樣用這組門檻上線的理由不是那個省下的數字，是它是離線研究裡唯一
「逐段還原」與「整份重讀」兩種情境都為正的操作點。真的要調，要等
restores.jsonl 累積出真實的還原遙測，再用 tr-tune 從實測重新推導，
不是照離線預估往下調。
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
    if t is None:
        t = load()
    else:
        t = dict(DEFAULTS, **t)
    n = len(scores)
    if n < t["min_chunks"] or n != len(chunk_chars):
        return [False] * n

    drop = []
    for i, s in enumerate(scores):
        if not isinstance(s, dict):
            drop.append(False)
            continue
        noise, uniq = s.get("noise"), s.get("uniq")
        # `not isinstance(..., bool)`：bool 是 int 的子類別，`True` 會通過
        # isinstance(x, (int, float)) 並當成 1.0 比大小。jev.scores() 現在
        # 也擋了一次，這裡是第二道——這是整條流程裡唯一「後果是刪掉文字」
        # 的判斷，不該只靠上游一層。
        ok = (
            i != 0 and i != n - 1                       # 不刪頭尾
            and isinstance(noise, (int, float)) and not isinstance(noise, bool)
            and isinstance(uniq, (int, float)) and not isinstance(uniq, bool)
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
