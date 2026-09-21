"""存放區與紀錄。

段落原文放 session 存放區（700，隨 session 清除）。紀錄同時寫一份到封存區供離線分析，
封存區只存紀錄、不存原文 —— Layer 1 的比對改用獨有詞集合（見 descriptor.distinctive）。
"""
import json, os, re, time

ROOT_DEFAULT = "~/.claude/tool-reduce"
HANDLE_RE = re.compile(r"^[A-Za-z0-9]+\.\d+$")

# 常見密鑰樣式。獨有詞集合可能夾帶金鑰片段（長 token 會被當識別字），封存前過濾掉。
SECRET_RE = re.compile(
    r"^(sk-|pk-|ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|xox[baprs]-|apikey|AKIA|ASIA)"
    r"|^[A-Za-z0-9+/]{40,}={0,2}$",
    re.I)


def scrub(tokens):
    """丟掉看起來像密鑰的詞。"""
    return [t for t in tokens if not SECRET_RE.search(t)]


def now_ms():
    """BSD date 不支援 %3N 而且不報錯，毫秒時戳一律走 Python。"""
    return int(time.time() * 1000)


def _resolve_root():
    """存放區根目錄的單一算法：TOOL_REDUCE_HOME 優先，否則 ROOT_DEFAULT。
    跟 Store.__init__ 沒帶 root 參數時用的算法完全一樣（下面 Store.__init__
    直接呼叫這支，不是各自重算一遍）。

    tr-restore、tr-guard 跟這個模組的 PostToolUse hook（見
    ../hooks/executable_tool-reduce.py）過去各自用自己的一份公式決定存放區
    根目錄在哪，其中 hook 那份甚至沒看 TOOL_REDUCE_HOME —— 設了這個環境
    變數會搬動存放區、卻搬不動 hook 的比對基準。三邊現在都改呼叫這支，
    公式只有一份。

    刻意用 abspath 不用 realpath：Store 實際寫檔案／讀檔案走的就是這個值，
    要是換成 realpath，在 root 本身是符號連結底下的路徑時（例如 macOS 的
    tempfile.mkdtemp() 落在 /var/folders/...，而 /var 是指到 /private/var
    的符號連結），這支函式算出來的目錄會跟 Store 實際建立的目錄岔開 ——
    同一個 root 字串，abspath 後兩次呼叫得到同一個路徑，realpath 後可能
    因為當下檔案系統狀態而得到不同路徑。只有需要判斷「某個路徑是否落在
    存放區底下」的呼叫端（見 hook 的 _reads_store_file）才自己在這支的
    回傳值外面再包一層 realpath，那是它們自己驗證邏輯的需求，不該滲進
    這支公用的解析函式裡。
    """
    return os.path.abspath(os.path.expanduser(
        os.environ.get("TOOL_REDUCE_HOME", ROOT_DEFAULT)))


# 公開名稱給 tr-restore／tr-guard／PostToolUse hook 呼叫：store.root()。
# 定義成 _resolve_root 的別名而不是直接命名為 `root`，是因為 Store.__init__
# 底下有一個同名的 `root` 參數 —— Python 沒有區塊作用域，函式本體裡
# `root` 這個名字從進入函式那一刻起就固定指向參數，沒辦法在同一個函式體
# 內又拿它呼叫模組層級同名的函式。
root = _resolve_root


class Store:
    def __init__(self, session_id, root=None):
        self.root = (os.path.abspath(os.path.expanduser(root))
                     if root else _resolve_root())
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
        """盡力而為、不保證原子性：兩份目的地各自獨立嘗試，任一份失敗不影響
        另一份，也絕不讓例外逸出——呼叫端是 fail-open 的 hook，這裡丟例外
        會讓整個過濾流程中斷，而紀錄遺失一份的代價遠比中斷整條流程小。
        序列化失敗（rec 帶了 json 無法處理的值）視同兩份都失敗，整筆跳過。
        """
        rec.setdefault("ts_ms", now_ms())
        try:
            line = json.dumps(rec, ensure_ascii=False) + "\n"
        except (TypeError, ValueError):
            return
        for d in (self.path, self.archive):
            try:
                self._ensure(d)
                with open(os.path.join(d, name), "a", encoding="utf-8") as fh:
                    fh.write(line)
            except OSError:
                pass

    def record_decision(self, rec):
        self._append("decisions.jsonl", rec)

    def record_tombstone(self, rec):
        self._append("tombstones.jsonl", rec)

    def record_restore(self, rec):
        self._append("restores.jsonl", rec)
