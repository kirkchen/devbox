"""存放區與紀錄。

段落原文放 session 存放區（700，隨 session 清除）。紀錄同時寫一份到封存區供離線分析，
封存區只存紀錄、不存原文 —— Layer 1 的比對改用獨有詞集合（見 descriptor.distinctive）。
"""
import json, os, re, tempfile, time

ROOT_DEFAULT = "~/.claude/tool-reduce"
HANDLE_RE = re.compile(r"^[A-Za-z0-9]+\.\d+$")
# session id 走跟 tr-stats --session 同一組字元（字母、數字、`_`、`-`），
# 不含 `.` 或路徑分隔符。見 Store.__init__ 對 containment 的說明。
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]+$")

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
        """session_id 的 containment 在這裡就擋住，不留給呼叫端。

        存放區裡每一個「拿外來字串組路徑」的地方都先驗證再組：load_chunk
        驗 handle、tr-guard 驗 handle、tr-stats 驗 --session、tr-cleanup.sh
        驗 session id。唯一的例外是這裡 —— 真正寫檔案的那一端。
        `Store("../escaped-session")` 會寫到存放區外面，`Store("/tmp/x")`
        會寫到 /tmp（os.path.join 碰到絕對路徑會整段丟掉前面的 root）。
        今天 session_id 來自 harness 的 UUID，不是攻擊者控制的，所以這不是
        一條現成的攻擊路徑；但「路徑一律驗證」這條不變量在整個模組裡只有
        這一個缺口，而缺口在寫入端比在讀取端更貴。

        不合格就丟 ValueError：三個呼叫端（PostToolUse hook、tr-guard、
        tr-restore）都在 try 裡面，fail-open 契約不受影響。"""
        self.root = (os.path.abspath(os.path.expanduser(root))
                     if root else _resolve_root())
        # "archive" 另外擋掉：它字元集合合法，但封存區只存紀錄、不存原文
        # （段落原文可能帶密鑰，archive/ 從不被清掉），一個叫 archive 的
        # session 會把原文寫進去。
        if (not isinstance(session_id, str) or not SESSION_RE.match(session_id)
                or session_id == "archive"):
            raise ValueError(f"invalid session id: {session_id!r}")
        self.path = os.path.join(self.root, session_id)
        self.archive = os.path.join(self.root, "archive")

    def _ensure(self, d):
        os.makedirs(d, mode=0o700, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass

    def save_chunk(self, handle, text):
        """段落原文落地。先寫同目錄的暫存檔再 os.replace，不直接 open(p,"w")。

        open(p,"w") 會先截斷再寫：寫到一半失敗（例如 text 帶了單獨的
        UTF-16 surrogate，UTF-8 編碼會丟 UnicodeEncodeError）會留下一個
        零位元組的 `<handle>.txt`。那個檔案存在、load_chunk 讀得到、回傳
        空字串 —— 一個指向空氣的墓碑，直接打穿「刪掉的東西一定救得回來」。
        os.replace 在同一個檔案系統上是原子操作：要嘛沒有這個檔案，要嘛是
        完整的內容，不存在中間狀態。（tr-tune 寫 thresholds.json 用的是
        同一招。）"""
        if not HANDLE_RE.match(handle):
            return
        self._ensure(self.path)
        p = os.path.join(self.path, handle + ".txt")
        fd, tmp = tempfile.mkstemp(dir=self.path, prefix=".tr-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, p)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

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
        except (OSError, UnicodeDecodeError):
            # save_chunk 只寫 Python str，正常情況下寫出來的一定是合法
            # UTF-8；只有直接竄改存放區底下的檔案才會塞進非 UTF-8 位元組。
            # 但呼叫端（tr-restore、tr-guard）都預期「查不到就回傳 None」
            # 這個單一失敗形狀，不是讓 UnicodeDecodeError 逸出——那會在
            # tr-restore 印出帶內部路徑的完整 traceback，違反「錯誤訊息
            # 不能洩漏內部路徑／stack trace」的規則（task-7 fix-round 2）。
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
