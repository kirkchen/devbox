# tests/python/test_restore.py
import sys, os, json, tempfile, time, subprocess, importlib.util, importlib.machinery, unittest
from unittest import mock

BASE = os.path.join(os.path.dirname(__file__), "../..")
LIB = os.path.join(BASE, "chezmoi/private_dot_config/claude/tool-reduce")
sys.path.insert(0, LIB)
# Pin TOOL_REDUCE_LIB to the repo source before any of the hooks/CLI under
# test are loaded, mirroring test_hook_integration.py — a stale deployed
# copy under ~/.config/claude/tool-reduce would otherwise shadow the source
# under test for in-process imports.
os.environ["TOOL_REDUCE_LIB"] = LIB
import store

_spec = importlib.util.spec_from_file_location(
    "tr_guard", os.path.join(BASE, "chezmoi/private_dot_config/claude/hooks/executable_tr-guard.py"))
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)

_RESTORE_PATH = os.path.join(BASE, "chezmoi/dot_local/bin/executable_tr-restore")
# `executable_tr-restore` has no `.py` suffix (chezmoi's naming convention
# for a deployed executable), so spec_from_file_location can't infer a
# loader from the extension the way it does for the `.py` hook files above —
# it comes back with loader=None and module_from_spec raises. Pass the
# source loader explicitly instead.
_spec_restore = importlib.util.spec_from_file_location(
    "tr_restore", _RESTORE_PATH,
    loader=importlib.machinery.SourceFileLoader("tr_restore", _RESTORE_PATH))
tr_restore = importlib.util.module_from_spec(_spec_restore)
_spec_restore.loader.exec_module(tr_restore)

_spec_hook = importlib.util.spec_from_file_location(
    "tool_reduce_hook",
    os.path.join(BASE, "chezmoi/private_dot_config/claude/hooks/executable_tool-reduce.py"))
hook = importlib.util.module_from_spec(_spec_hook)
_spec_hook.loader.exec_module(hook)

RESTORE = os.path.join(BASE, "chezmoi/dot_local/bin/executable_tr-restore")


class TestRestoreCli(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.st = store.Store("sess-r", root=self.root)
        self.st.save_chunk("abc123.4", "the original chunk text")
        self.env = dict(os.environ, TOOL_REDUCE_HOME=self.root,
                        TOOL_REDUCE_SESSION="sess-r",
                        TOOL_REDUCE_LIB=os.path.join(
                            BASE, "chezmoi/private_dot_config/claude/tool-reduce"))

    def run_cli(self, *args):
        return subprocess.run([sys.executable, RESTORE, *args],
                              capture_output=True, text=True, env=self.env)

    def test_prints_original_text(self):
        r = self.run_cli("abc123.4")
        self.assertEqual(r.returncode, 0)
        self.assertIn("the original chunk text", r.stdout)

    def test_logs_the_restore(self):
        self.run_cli("abc123.4")
        p = os.path.join(self.root, "archive", "restores.jsonl")
        rec = json.loads(open(p, encoding="utf-8").readline())
        self.assertEqual(rec["handle"], "abc123.4")
        self.assertEqual(rec["via"], "tr-restore")

    def test_unknown_handle_exits_nonzero(self):
        r = self.run_cli("nope.9")
        self.assertNotEqual(r.returncode, 0)

    def test_rejects_traversal(self):
        r = self.run_cli("../../etc/passwd")
        self.assertNotEqual(r.returncode, 0)


class TestGuard(unittest.TestCase):
    def test_detects_handle_in_bash_command(self):
        ev = {"tool_name": "Bash",
              "tool_input": {"command": "cat ~/.claude/tool-reduce/sess/abc123.4.txt"}}
        self.assertEqual(guard.detect(ev), ["abc123.4"])

    def test_detects_handle_in_read_path(self):
        ev = {"tool_name": "Read",
              "tool_input": {"file_path": "/Users/x/.claude/tool-reduce/s/dd99.12.txt"}}
        self.assertEqual(guard.detect(ev), ["dd99.12"])

    def test_ignores_unrelated_calls(self):
        self.assertEqual(guard.detect({"tool_name": "Bash",
                                       "tool_input": {"command": "ls -la"}}), [])

    def test_does_not_double_count_tr_restore(self):
        """tr-restore 自己會記，守衛不要再記一次。"""
        ev = {"tool_name": "Bash", "tool_input": {"command": "tr-restore abc123.4"}}
        self.assertEqual(guard.detect(ev), [])


class TestGuardDoesNotDoubleCount(unittest.TestCase):
    """task-7 修正 3：tr-restore 是一次 Bash 呼叫，tool_input 裡一定會提到
    `tr-restore`，而 tr-restore 自己已經會記一筆 restore —— 守衛絕對不能
    對同一次還原再記第二筆，兩條路徑（`sh -c` 包一層、直接讀存放區檔案）
    都要驗證過。"""

    def test_bare_invocation_is_not_double_counted(self):
        ev = {"tool_name": "Bash", "tool_input": {"command": "tr-restore a3f2.7"}}
        self.assertEqual(guard.detect(ev), [])

    def test_sh_dash_c_wrapped_invocation_is_not_double_counted(self):
        # `sh -c '...'` 包起來的那個字串本身還是一整條指令；shlex.split
        # 只切最外層，要再切一層才看得到裡面真正呼叫的是 tr-restore。
        ev = {"tool_name": "Bash",
              "tool_input": {"command": "sh -c 'tr-restore a3f2.7'"}}
        self.assertEqual(guard.detect(ev), [])

    def test_full_path_invocation_is_not_double_counted(self):
        ev = {"tool_name": "Bash",
              "tool_input": {"command": "/usr/local/bin/tr-restore a3f2.7"}}
        self.assertEqual(guard.detect(ev), [])

    def test_path_based_bash_read_is_still_detected(self):
        # 對照組：這不是在呼叫 tr-restore，是直接 cat 存放區檔案 —— 這條
        # 路徑不該被前面的雙重計算防線連帶擋掉。
        ev = {"tool_name": "Bash", "tool_input": {
            "command": "cat ~/.claude/tool-reduce/sess/abc123.4.txt"}}
        self.assertEqual(guard.detect(ev), ["abc123.4"])

    def test_path_based_read_tool_is_still_detected(self):
        # 對照組的另一半：Read 工具直接讀墓碑對應檔案，tool_input 裡完全
        # 沒有 command 欄位、也沒有提到 tr-restore，一樣要被抓到。
        ev = {"tool_name": "Read", "tool_input": {
            "file_path": "/Users/x/.claude/tool-reduce/s/dd99.12.txt"}}
        self.assertEqual(guard.detect(ev), ["dd99.12"])

    def test_helper_binary_with_similar_name_is_not_mistaken_for_tr_restore(self):
        # regression guard，跟 executable_tool-reduce.py 的
        # test_tr_restore_helper_is_not_a_restore_call 同一類：basename
        # 整詞比對不會被 `tr-restore-helper` 誤判成 tr-restore 本身，這裡
        # 反過來確認它不會被誤判成「已經還原過」而漏記一筆直接讀取。
        ev = {"tool_name": "Bash", "tool_input": {
            "command": "cat ~/.claude/tool-reduce/sess/abc123.4.txt && "
                       "/usr/bin/tr-restore-helper --list"}}
        self.assertEqual(guard.detect(ev), ["abc123.4"])


class TestGuardCannotBeFooledByUnrelatedPaths(unittest.TestCase):
    """task-7 陷阱提示：「guard 從路徑抽 handle，確認不會被騙去記一個根本
    不在存放區裡的檔案」。目錄名稱只是恰好以 tool-reduce 結尾／夾帶這個
    子字串，跟這支 hook 認的存放區完全無關。"""

    def test_directory_name_ending_in_tool_reduce_is_not_matched(self):
        ev = {"tool_name": "Bash", "tool_input": {
            "command": "cat /home/user/notes/mytool-reduce/sess/abc123.4.txt"}}
        self.assertEqual(guard.detect(ev), [])

    def test_directory_name_containing_tool_reduce_mid_word_is_not_matched(self):
        ev = {"tool_name": "Read", "tool_input": {
            "file_path": "/tmp/footool-reduce/x/y.1.txt"}}
        self.assertEqual(guard.detect(ev), [])

    def test_relative_tool_reduce_path_is_still_matched(self):
        # 反面確認：不是每個「tool-reduce 前面不是 `/`」的情況都該被擋 ——
        # 合法的相對路徑（前面是空白字元，不是英數字／底線／連字號）要
        # 繼續被認得出來，這道防線只擋「tool-reduce 是某個更長識別字的
        # 字尾」這一種情況。
        ev = {"tool_name": "Bash", "tool_input": {
            "command": "cat tool-reduce/sess/abc123.4.txt"}}
        self.assertEqual(guard.detect(ev), ["abc123.4"])

    def test_handle_shaped_text_outside_the_store_layout_is_not_matched(self):
        ev = {"tool_name": "Bash", "tool_input": {
            "command": "echo 'the handle is abc123.4, see docs'"}}
        self.assertEqual(guard.detect(ev), [])


class TestGuardMainFailOpen(unittest.TestCase):
    """main() 本身：任何例外都吞掉、永遠 exit 0、不印任何東西 —— PreToolUse
    hook 擋下正在觀察的那次呼叫，代價遠比漏記一次還原嚴重。"""

    def _run(self, stdin_text, env_extra=None):
        env = dict(os.environ, TOOL_REDUCE_LIB=LIB)
        if env_extra:
            env.update(env_extra)
        return subprocess.run(
            [sys.executable,
             os.path.join(BASE, "chezmoi/private_dot_config/claude/hooks/executable_tr-guard.py")],
            input=stdin_text, capture_output=True, text=True, env=env)

    def test_non_json_stdin_is_fail_open(self):
        r = self._run("not json{")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")

    def test_empty_stdin_is_fail_open(self):
        r = self._run("")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")

    def test_unrelated_event_prints_nothing_and_exits_zero(self):
        ev = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls -la"}})
        r = self._run(ev)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")

    def test_direct_read_records_a_restore(self):
        # HANDLE_IN_PATH 認的是「路徑裡有沒有一段字面上叫 tool-reduce 的
        # 目錄」，所以這裡把 TOOL_REDUCE_HOME 設成一個確實以 tool-reduce
        # 結尾的暫存目錄，跟 store.ROOT_DEFAULT（~/.claude/tool-reduce）
        # 一樣的形狀，而不是隨便一個暫存目錄名稱。
        root = os.path.join(tempfile.mkdtemp(), "tool-reduce")
        ev = json.dumps({"tool_name": "Bash", "session_id": "sess-g",
                         "tool_input": {"command":
                             f"cat {root}/sess-g/abc123.4.txt"}})
        r = self._run(ev, env_extra={"TOOL_REDUCE_HOME": root})
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        p = os.path.join(root, "archive", "restores.jsonl")
        rec = json.loads(open(p, encoding="utf-8").readline())
        self.assertEqual(rec["handle"], "abc123.4")
        self.assertEqual(rec["via"], "direct-read")
        self.assertEqual(rec["tool"], "Bash")


class TestSessionIdFallback(unittest.TestCase):
    """tr-restore 的 session_id()：TOOL_REDUCE_SESSION 沒設時退而求其次找
    存放區底下最新異動的 session 目錄。兩個陷阱：archive/ 不能被選中
    （它只存 jsonl 紀錄，從不存墓碑原文），存放區根目錄本身不存在時要
    好好回傳空字串，不能讓例外逸出。"""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self._env_patch = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        os.environ.pop("TOOL_REDUCE_SESSION", None)
        os.environ["TOOL_REDUCE_HOME"] = self.root

    def tearDown(self):
        self._env_patch.stop()

    def _mkdir(self, name, mtime_offset):
        p = os.path.join(self.root, name)
        os.makedirs(p, exist_ok=True)
        t = time.time() + mtime_offset
        os.utime(p, (t, t))
        return p

    def test_picks_most_recently_modified_session_dir(self):
        self._mkdir("sess-old", -100)
        self._mkdir("sess-new", 0)
        self.assertEqual(tr_restore.session_id(), "sess-new")

    def test_archive_dir_is_excluded_even_when_newest(self):
        self._mkdir("sess-real", -100)
        self._mkdir("archive", 0)  # newer mtime than the real session dir
        self.assertEqual(tr_restore.session_id(), "sess-real")

    def test_only_archive_dir_present_returns_empty(self):
        self._mkdir("archive", 0)
        self.assertEqual(tr_restore.session_id(), "")

    def test_missing_store_root_returns_empty(self):
        os.environ["TOOL_REDUCE_HOME"] = os.path.join(self.root, "does-not-exist")
        self.assertEqual(tr_restore.session_id(), "")

    def test_explicit_session_env_wins_over_fallback(self):
        os.environ["TOOL_REDUCE_SESSION"] = "sess-explicit"
        self._mkdir("sess-newer", 0)
        self.assertEqual(tr_restore.session_id(), "sess-explicit")


class TestHandleValidationBeforeFilesystemAccess(unittest.TestCase):
    """一個沒過 store.HANDLE_RE 格式檢查的 handle，必須在任何檔案系統存取
    之前就被拒絕、以非零結束 —— 不能先列了 session 目錄、建了 Store
    物件，才在 load_chunk 內部才發現格式不對。用 mock 讓 os.listdir 和
    store.Store 一被呼叫就丟例外，反向證明它們真的沒被呼叫到。"""

    def test_invalid_handle_never_touches_the_filesystem(self):
        with mock.patch.object(
                os, "listdir",
                side_effect=AssertionError("must not list any directory")), \
             mock.patch.object(
                store, "Store",
                side_effect=AssertionError("must not construct a Store")), \
             mock.patch.object(sys, "argv", ["tr-restore", "../../etc/passwd"]):
            rc = tr_restore.main()
        self.assertEqual(rc, 1)

    def test_wrong_shape_handle_is_rejected_before_filesystem_access(self):
        # 不只是路徑穿越——任何不合 HANDLE_RE 形狀的字串都一樣。
        with mock.patch.object(
                os, "listdir",
                side_effect=AssertionError("must not list any directory")), \
             mock.patch.object(
                store, "Store",
                side_effect=AssertionError("must not construct a Store")), \
             mock.patch.object(sys, "argv", ["tr-restore", "not-a-handle"]):
            rc = tr_restore.main()
        self.assertEqual(rc, 1)


class TestStoreRootHelper(unittest.TestCase):
    """store.root()：tr-restore／tr-guard／PostToolUse hook 共用的單一
    存放區根目錄解析公式（task-7 修正 2）。"""

    def setUp(self):
        self._env_patch = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_defaults_to_root_default_when_env_unset(self):
        os.environ.pop("TOOL_REDUCE_HOME", None)
        expected = os.path.abspath(os.path.expanduser(store.ROOT_DEFAULT))
        self.assertEqual(store.root(), expected)

    def test_respects_tool_reduce_home_override(self):
        os.environ["TOOL_REDUCE_HOME"] = "/tmp/custom-tr-root"
        self.assertEqual(store.root(), os.path.abspath("/tmp/custom-tr-root"))

    def test_store_without_explicit_root_matches_the_shared_helper(self):
        os.environ["TOOL_REDUCE_HOME"] = tempfile.mkdtemp()
        st = store.Store("sess-x")
        self.assertEqual(st.root, store.root())

    def test_store_with_explicit_root_is_unaffected(self):
        # 明講 root 參數的呼叫端（例如所有測試檔案自己建的 Store）不該被
        # 這支共用 helper 影響——它們要的就是那個確切的目錄，不是環境
        # 變數解析出來的值。
        explicit = tempfile.mkdtemp()
        os.environ["TOOL_REDUCE_HOME"] = tempfile.mkdtemp()  # a different dir
        st = store.Store("sess-y", root=explicit)
        self.assertEqual(st.root, os.path.abspath(os.path.expanduser(explicit)))
        self.assertNotEqual(st.root, store.root())


class TestHookRootConsistency(unittest.TestCase):
    """task-7 修正 2 的回歸測試：executable_tool-reduce.py 的
    is_restore_call 過去只認 store.ROOT_DEFAULT（模組載入當下就凍結成
    常數，完全沒看 TOOL_REDUCE_HOME）。設了 TOOL_REDUCE_HOME 會讓
    store.Store 真正落地的目錄搬家，這道還原偵測閘門卻留在原地 —— 還原
    出來的內容在同一個 hook 呼叫裡原地又被過濾一次。"""

    def setUp(self):
        self.custom_root = tempfile.mkdtemp()
        self._env_patch = mock.patch.dict(
            os.environ, {"TOOL_REDUCE_HOME": self.custom_root}, clear=False)
        self._env_patch.start()

    def tearDown(self):
        self._env_patch.stop()

    def test_read_under_custom_tool_reduce_home_is_recognised_as_restore(self):
        path = os.path.join(self.custom_root, "sess-1", "a3f2.7.txt")
        ev = {"tool_name": "Bash", "tool_input": {"command": f"cat {path}"}}
        self.assertTrue(hook.is_restore_call(ev))

    def test_default_root_path_is_not_mistaken_for_the_relocated_store(self):
        # 反向確認：TOOL_REDUCE_HOME 指到別處時，預設路徑底下的檔案不該
        # 被誤判成落在（已經搬家的）存放區底下。
        ev = {"tool_name": "Bash", "tool_input": {
            "command": "cat ~/.claude/tool-reduce/sess-1/a3f2.7.txt"}}
        self.assertFalse(hook.is_restore_call(ev))


if __name__ == "__main__":
    unittest.main()
