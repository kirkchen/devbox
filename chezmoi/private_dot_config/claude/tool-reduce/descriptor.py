"""墓碑描述詞。規則產生,不是 Jev 寫的 —— Jev 官方明言沒有被訓練來生成文字。

墓碑成本的量測:每多 100 字元約吃掉 0.5 到 1 個百分點的淨效益,所以 250 字元的
預算很充裕。寫得清楚才有逐段還原,而逐段還原是整個效益成立的前提
(整份重讀會讓淨效益從 +3.6% 掉到 −0.9%)。
"""
import re

TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_\-./]{5,}|\b\d{3,}\b')
STOP = set("""function return import export const class public private static string number
boolean default true false null undefined https http www com org index files result results
message content value object array length error errors status""".split())


def _first_meaningful_line(chunk):
    for line in chunk.split("\n"):
        s = line.strip()
        if len(s) >= 3 and s not in ("{", "}", "[", "]", "---"):
            return s
    return ""


def make(chunk, handle, max_chars=250):
    lines = chunk.count("\n") + 1
    head = re.sub(r"\s+", " ", _first_meaningful_line(chunk))
    tail = f" · tr-restore {handle}]"
    prefix = f"[省略 {lines} 行 · "
    room = max_chars - len(prefix) - len(tail)
    if room < 0:
        return f"[省略 {lines} 行{tail}"
    if len(head) > room:
        head = head[:max(0, room - 1)] + "…"
    return prefix + head + tail


def distinctive(chunk, others, limit=40):
    """這段有、同份 result 其他段沒有的識別字。給 Layer 1 的離線比對用。"""
    def toks(s):
        return {t for t in TOKEN.findall(s)
                if t.lower() not in STOP and not t.startswith("http")}
    mine = toks(chunk)
    for o in others:
        mine -= toks(o)
    return sorted(mine)[:limit]
