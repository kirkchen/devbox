"""墓碑描述詞。規則產生，不是 Jev 寫的 —— Jev 官方明言沒有被訓練來生成文字。

墓碑成本的量測：每多 100 字元約吃掉 0.5 到 1 個百分點的淨效益，所以 250 字元的
預算很充裕。寫得清楚才有逐段還原，而逐段還原是整個效益成立的前提
（整份重讀會讓淨效益從 +3.6% 掉到 −0.9%）。
"""
import re

from store import SECRET_RE

# token 本體允許的字元類別，抽成獨立常數而不是寫死在 TOKEN 的 pattern
# 字串裡——tr-eval 判斷「獨有詞邊界」（見 executable_tr-eval.py 的
# _is_token_char）要用同一組字元，兩邊都從這裡組出各自的 regex，才不會
# 走鐘成兩份定義（task-9 fix-round 2）。
TOKEN_CHARS = r'A-Za-z0-9_\-./'
TOKEN = re.compile(r'[A-Za-z_][' + TOKEN_CHARS + r']{5,}|\b\d{3,}\b')
URL_RE = re.compile(r'https?://\S+')
STOP = set("""function return import export const class public private static string number
boolean default true false null undefined https http www com org index files result results
message content value object array length error errors status""".split())

REDACTED = "[REDACTED]"


def _first_meaningful_line(chunk):
    for line in chunk.split("\n"):
        s = line.strip()
        if len(s) >= 3 and s not in ("{", "}", "[", "]", "---"):
            return s
    return ""


def _scrub_secrets(text):
    """把長得像密鑰的 token 換成佔位字串，避免墓碑描述詞把密鑰帶進封存區。

    在產生描述詞的當下做，跟輸出裡的墓碑走同一份文字，只有這一條路徑。
    """
    return TOKEN.sub(
        lambda m: REDACTED if SECRET_RE.search(m.group(0)) else m.group(0), text)


def make(chunk, handle, max_chars=250):
    lines = chunk.count("\n") + 1
    head = re.sub(r"\s+", " ", _first_meaningful_line(chunk))
    head = _scrub_secrets(head)
    handle = re.sub(r"\s+", " ", handle)
    tail = f" · tr-restore {handle}]"
    prefix = f"[省略 {lines} 行 · "
    room = max_chars - len(prefix) - len(tail)
    if room <= 0:
        # Not enough budget for the head decoration at all. Drop it and,
        # as a last-resort backstop, hard-truncate below so max_chars is
        # honoured even when the handle itself is unexpectedly long.
        result = f"[省略 {lines} 行{tail}"
    else:
        if len(head) > room:
            head = head[:room - 1] + "…"
        result = prefix + head + tail
    # max(0, ...): a negative max_chars must clamp to "nothing", not slice
    # off the tail of the string (Python's [:-10] semantics).
    return result[:max(0, max_chars)]


def distinctive(chunk, others, limit=40):
    """這段有、同份 result 其他段沒有的識別字。給 Layer 1 的離線比對用。"""
    def toks(s):
        s = URL_RE.sub(" ", s)
        return {t for t in TOKEN.findall(s) if t.lower() not in STOP}
    mine = toks(chunk)
    for o in others:
        mine -= toks(o)
    return sorted(mine)[:limit]
