"""存放區與紀錄。

段落原文放 session 存放區(700,隨 session 清除)。紀錄同時寫一份到封存區供離線分析,
封存區只存紀錄、不存原文 —— Layer 1 的比對改用獨有詞集合(見 descriptor.distinctive)。
"""
import json, os, re, time

ROOT_DEFAULT = "~/.claude/tool-reduce"
HANDLE_RE = re.compile(r"^[A-Za-z0-9]+\.\d+$")

# 常見密鑰樣式。獨有詞集合可能夾帶金鑰片段(長 token 會被當識別字),封存前過濾掉。
SECRET_RE = re.compile(
    r"^(sk-|pk-|ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|xox[baprs]-|apikey|AKIA|ASIA)"
    r"|^[A-Za-z0-9+/]{40,}={0,2}$",
    re.I)


def scrub(tokens):
    """丟掉看起來像密鑰的詞。"""
    return [t for t in tokens if not SECRET_RE.search(t)]


def now_ms():
    """BSD date 不支援 %3N 而且不報錯,毫秒時戳一律走 Python。"""
    return int(time.time() * 1000)


class Store:
    def __init__(self, session_id, root=None):
        self.root = os.path.expanduser(
            root or os.environ.get("TOOL_REDUCE_HOME", ROOT_DEFAULT))
        self.path = os.path.join(self.root, session_id)
        self.archive = os.path.join(self.root, "archive")

    def _ensure(self, d):
        os.makedirs(d, mode=0o700, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass

    def save_chunk(self, handle, text):
        if not HANDLE_RE.match(handle):
            return
        self._ensure(self.path)
        p = os.path.join(self.path, handle + ".txt")
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)
        try:
            os.chmod(p, 0o600)
        except OSError:
            pass

    def load_chunk(self, handle):
        if not HANDLE_RE.match(handle):
            return None
        p = os.path.realpath(os.path.join(self.path, handle + ".txt"))
        if not p.startswith(os.path.realpath(self.path) + os.sep):
            return None
        if not os.path.exists(p):
            return None
        try:
            with open(p, encoding="utf-8") as fh:
                return fh.read()
        except OSError:
            return None

    def _append(self, name, rec):
        rec.setdefault("ts_ms", now_ms())
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        for d in (self.path, self.archive):
            self._ensure(d)
            with open(os.path.join(d, name), "a", encoding="utf-8") as fh:
                fh.write(line)

    def record_decision(self, rec):
        self._append("decisions.jsonl", rec)

    def record_tombstone(self, rec):
        self._append("tombstones.jsonl", rec)

    def record_restore(self, rec):
        self._append("restores.jsonl", rec)
