# tests/python/test_hook_integration.py
import sys, os, io, re, json, tempfile, importlib.util, unittest
from unittest import mock

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
LIB = os.path.join(BASE, "chezmoi/private_dot_config/claude/tool-reduce")
# Pin TOOL_REDUCE_LIB to the repo source *before* the hook module is loaded.
# The hook does `sys.path.insert(0, TR)` where TR defaults to the deployed
# path ~/.config/claude/tool-reduce; a stale deployed copy there would
# otherwise shadow the source under test.
os.environ["TOOL_REDUCE_LIB"] = LIB
sys.path.insert(0, LIB)
_spec = importlib.util.spec_from_file_location(
    "tool_reduce_hook",
    os.path.join(BASE, "chezmoi/private_dot_config/claude/hooks/executable_tool-reduce.py"))
hook = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(hook)
import store


def big_output(n_sections=12):
    """12 段：頭尾是錨點，中間 10 段重複的噪音。"""
    parts = ["## Command: terraform plan -target=uat\npath /Users/kirk/Code/sre-iac/uat"]
    for i in range(n_sections - 2):
        parts.append("## Section %d\n" % i + "\n".join(
            "  refreshing state... still refreshing" for _ in range(30)))
    parts.append("## Result\nPlan: 3 to add, 0 to change, 0 to destroy.")
    return "\n\n".join(parts)


def fake_asker(scores):
    def ask(state, questions, timeout=None):
        n = len(state["chunks"])
        out = {}
        for i in range(n):
            noise, uniq = scores(i, n)
            out[f"noise_c{i}"] = {"noul": noise}
            out[f"uniq_c{i}"] = {"noul": uniq}
        return out
    return ask


# 「頭尾不刪」的分數分布：中間段高 noise 低 uniq，頭尾相反。多個新測試
# 都要重現一定會產生刪除的情境，抽出來共用。
DROP_MIDDLE = fake_asker(lambda i, n: (0.95, 0.05) if 0 < i < n - 1 else (0.1, 0.9))

# 一個沒配對的 UTF-16 high surrogate。合法的 Python str 可以裝，但用
# strict errors 編碼成 UTF-8（stdout 的預設行為）會丟 UnicodeEncodeError。
# 用 json.dumps(ensure_ascii=True)（Python 內建的預設值）包出的酬載一樣會
# 把它跳脫成 \ud800 這個六字元序列，跟真實世界裡格式錯誤的 tool output
# 經過 JSON 编碼後可能出現的樣子一致。
LONE_SURROGATE = "\ud800"


def big_output_with_surrogate():
    """在尾端錨點段（最後一段，位置下限永遠不刪）裡混入一個沒配對的
    surrogate，確保它一定會被留在最終輸出裡，不受評分影響。

    刻意放在尾端而不是開頭：decision_id 的雜湊只取 text[:200]，放在開頭
    會在雜湊那行就先丟例外 —— 那行本來就在 reduce_payload() 自己的呼叫
    路徑上，main() 舊版的第二個 try/except（包住 reduce_payload() 呼叫）
    已經會接住它，不會重現 Important 2 描述的「print() 在 try 之外」那個
    問題。放在尾端能讓例外真的發生在 print() 那一步。"""
    return big_output().replace(
        "Plan: 3 to add, 0 to change, 0 to destroy.",
        "Plan: 3 to add, 0 to change, 0 to destroy. " + LONE_SURROGATE, 1)


class TestGates(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.environ["TOOL_REDUCE_MODE"] = "full"

    def _st(self):
        return store.Store("sess-test", root=self.root)

    def test_mode_off_returns_none(self):
        os.environ["TOOL_REDUCE_MODE"] = "off"
        ev = {"tool_name": "Bash", "tool_response": {"stdout": big_output()},
              "session_id": "s"}
        self.assertIsNone(hook.reduce_payload(ev, asker=fake_asker(lambda i, n: (0.9, 0.1)),
                                              st=self._st()))

    def test_small_output_returns_none(self):
        ev = {"tool_name": "Bash", "tool_response": {"stdout": "tiny"}, "session_id": "s"}
        self.assertIsNone(hook.reduce_payload(ev, asker=fake_asker(lambda i, n: (0.9, 0.1)),
                                              st=self._st()))

    def test_restore_read_is_exempt(self):
        """被還原的內容不能再被過濾，否則會繞圈。"""
        ev = {"tool_name": "Bash",
              "tool_input": {"command": "tr-restore d1.3"},
              "tool_response": {"stdout": big_output()}, "session_id": "s"}
        self.assertIsNone(hook.reduce_payload(ev, asker=fake_asker(lambda i, n: (0.9, 0.1)),
                                              st=self._st()))

    def test_jev_failure_returns_none(self):
        def boom(state, questions, timeout=None):
            raise RuntimeError("jev http 500")
        ev = {"tool_name": "Bash", "tool_response": {"stdout": big_output()},
              "session_id": "s"}
        self.assertIsNone(hook.reduce_payload(ev, asker=boom, st=self._st()))

    def test_persisted_output_path_is_exempt(self):
        """persistedOutputPath 代表結果已經有自己的離線還原路徑；改寫 stdout
        會讓 persistedOutputSize 描述一份已經不存在的文字，整份放行不過濾。"""
        ev = {"tool_name": "Bash",
              "tool_response": {"stdout": big_output(),
                                "persistedOutputPath": "/tmp/whatever-output.txt",
                                "persistedOutputSize": 999999},
              "session_id": "s"}
        self.assertIsNone(hook.reduce_payload(ev, asker=fake_asker(lambda i, n: (0.9, 0.1)),
                                              st=self._st()))


class TestRewrite(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.environ["TOOL_REDUCE_MODE"] = "full"
        self.st = store.Store("sess-rw", root=self.root)
        ev = {"tool_name": "Bash", "tool_response": {"stdout": big_output(), "stderr": "w"},
              "session_id": "sess-rw"}
        # 中間段高 noise 低 uniq，頭尾相反
        self.out = hook.reduce_payload(
            ev, asker=fake_asker(lambda i, n: (0.95, 0.05) if 0 < i < n - 1 else (0.1, 0.9)),
            st=self.st)

    def test_produces_hook_output(self):
        self.assertIsNotNone(self.out)
        h = self.out["hookSpecificOutput"]
        self.assertEqual(h["hookEventName"], "PostToolUse")
        self.assertIn("updatedToolOutput", h)

    def test_preserves_shape(self):
        o = self.out["hookSpecificOutput"]["updatedToolOutput"]
        self.assertIsInstance(o, dict)
        self.assertEqual(o["stderr"], "w")
        self.assertIn("stdout", o)

    def test_shorter_than_original(self):
        o = self.out["hookSpecificOutput"]["updatedToolOutput"]
        self.assertLess(len(o["stdout"]), len(big_output()))

    def test_first_and_last_survive(self):
        o = self.out["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
        self.assertIn("terraform plan -target=uat", o)
        self.assertIn("Plan: 3 to add", o)

    def test_tombstones_present_and_restorable(self):
        o = self.out["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
        self.assertIn("tr-restore", o)
        import re
        handles = re.findall(r"tr-restore (\S+)\]", o)
        self.assertTrue(handles)
        for h in handles:
            self.assertIsNotNone(self.st.load_chunk(h))

    def test_decision_record_keeps_raw_scores(self):
        p = os.path.join(self.st.path, "decisions.jsonl")
        rec = json.loads(open(p, encoding="utf-8").readline())
        self.assertIn("chunks", rec)
        self.assertIn("noise", rec["chunks"][0]["scores"])
        self.assertIn("distinctive", rec["chunks"][0])
        self.assertIn("thresholds", rec)


class TestIsRestoreCall(unittest.TestCase):
    """fix-round 2：fix-round 1 換成的 `\\btr-restore\\b` regex 用「字詞邊界」
    比對還原指令，但 `-` 在 regex 眼中是非字元，邊界兩側都成立 ——
    `tr-restore-helper`、`my-tr-restore-notes.md` 都會被誤判成呼叫還原
    指令。而存放區那一半換成前綴比對兩種固定寫法（原樣 "~/..." 跟展開後
    的絕對路徑）的子字串比對，`..` 正規化後才會落進存放區的路徑（例如
    `~/.claude/x/../tool-reduce/...`）完全比對不到，等於「還原的內容又
    被再過濾一次」的回歸。

    這一版換成解析而不是字串比對：
    - tr-restore 呼叫比對 shlex 切出來的殼層 token 的 basename（涵蓋
      `sh -c '...'` 這種巢狀殼層寫法，見 hook._flatten_shell_tokens）。
    - 存放區讀取比對 os.path.realpath 正規化後的路徑是否等於或落在
      存放區底下 —— 跟 store.load_chunk 驗證 handle 同一招，天生處理
      得了 `..`、結尾斜線、symlink，且套用在任何工具的 tool_input 上
      （不只 Bash，Read 直接讀墓碑檔案也要抓到）。

    測試矩陣對應 fix-round 2 的 review 表格，一列一個測試方法。"""

    def _bash(self, command):
        return {"tool_name": "Bash", "tool_input": {"command": command}}

    # --- tr-restore CLI 呼叫：獨立殼層 token 才算 ---

    def test_direct_tr_restore_invocation_is_a_restore_call(self):
        self.assertTrue(hook.is_restore_call(self._bash("tr-restore a3f2.7")))

    def test_tr_restore_via_sh_dash_c_is_a_restore_call(self):
        # `sh -c '...'` 那個被引號包住的字串本身還是一整條指令；
        # shlex.split 只切最外層，會把它當成一個（帶內部空白的）token，
        # 要再切一層才看得到裡面真正呼叫的是 tr-restore。
        self.assertTrue(hook.is_restore_call(
            self._bash("sh -c 'tr-restore a3f2.7'")))

    def test_tr_restore_with_full_path_is_a_restore_call(self):
        self.assertTrue(hook.is_restore_call(
            self._bash("/usr/local/bin/tr-restore a3f2.7")))

    def test_tr_restore_helper_is_not_a_restore_call(self):
        # regression guard：上一輪的 \btr-restore\b word-boundary 版本會
        # 誤判這個 —— "-" 兩側都算邊界；basename 整詞比對不會。
        self.assertFalse(hook.is_restore_call(
            self._bash("/usr/bin/tr-restore-helper --list")))

    def test_filename_mentioning_tr_restore_is_not_a_restore_call(self):
        # regression guard：同一個 word-boundary 問題的另一種寫法。
        self.assertFalse(hook.is_restore_call(
            self._bash("cat my-tr-restore-notes.md")))

    # --- 直接讀 session 存放區底下的檔案 ---

    def test_cat_of_session_store_is_a_restore_call(self):
        self.assertTrue(hook.is_restore_call(
            self._bash("cat ~/.claude/tool-reduce/s/a3f2.7.txt")))

    def test_cat_of_session_store_with_trailing_slash_is_a_restore_call(self):
        self.assertTrue(hook.is_restore_call(
            self._bash("cat ~/.claude/tool-reduce/s/a3f2.7.txt/")))

    def test_dotdot_normalising_into_the_store_is_a_restore_call(self):
        # regression：fix-round 1 的字串比對版本抓不到這個 —— `..` 正規化
        # 前的字面文字裡沒有任何一段完整比對得到 "~/.claude/tool-reduce/"。
        self.assertTrue(hook.is_restore_call(
            self._bash("cat ~/.claude/x/../tool-reduce/s/a3f2.7.txt")))

    def test_symlink_into_the_store_is_a_restore_call(self):
        # realpath 天生會把 symlink 解到真正的目標，不用為 symlink 另外
        # 寫特例。目標不需要真的存在，只有 symlink 本身要存在。
        d = tempfile.mkdtemp()
        link = os.path.join(d, "myslink")
        target = os.path.expanduser("~/.claude/tool-reduce/sess-x/a1.1.txt")
        os.symlink(target, link)
        self.assertTrue(hook.is_restore_call(self._bash(f"cat {link}")))

    def test_read_of_a_store_file_is_a_restore_call(self):
        # 存放區檢查要套用在任何工具的輸入上，不只是 Bash —— Read 直接讀
        # 墓碑對應的檔案也要被認出來，否則還原出來的內容原地又被濾掉。
        ev = {"tool_name": "Read",
              "tool_input": {"file_path": os.path.expanduser(
                  "~/.claude/tool-reduce/s/a3f2.7.txt")}}
        self.assertTrue(hook.is_restore_call(ev))

    # --- 不該被誤判的案例：只是提到原始碼路徑，或完全無關 ---

    def test_ls_of_repo_source_dir_is_not_a_restore_call(self):
        self.assertFalse(hook.is_restore_call(
            self._bash("ls chezmoi/private_dot_config/claude/tool-reduce/")))

    def test_grep_of_repo_source_dir_is_not_a_restore_call(self):
        self.assertFalse(hook.is_restore_call(self._bash(
            "grep -rn x chezmoi/private_dot_config/claude/tool-reduce/*.py")))

    def test_cat_of_deployed_source_dir_is_not_a_restore_call(self):
        # 部署路徑 ~/.config/claude/tool-reduce 跟 session 存放區
        # ~/.claude/tool-reduce 是不同路徑，不該互相誤判。
        self.assertFalse(hook.is_restore_call(
            self._bash("cat ~/.config/claude/tool-reduce/jev.py")))

    def test_unrelated_command_is_not_a_restore_call(self):
        self.assertFalse(hook.is_restore_call(self._bash("git log --stat -50")))

    def test_reduce_payload_still_filters_the_source_path_mentions(self):
        """兩個誤判案例（ls/grep 原始碼目錄）過去會讓 reduce_payload 整份
        放行；這裡在 reduce_payload 這個層級再確認一次，不只是
        is_restore_call 回傳對的布林值。"""
        for command in (
            "ls chezmoi/private_dot_config/claude/tool-reduce/",
            "grep -rn noise chezmoi/private_dot_config/claude/tool-reduce/*.py",
        ):
            os.environ["TOOL_REDUCE_MODE"] = "full"
            ev = {"tool_name": "Bash", "tool_input": {"command": command},
                  "tool_response": {"stdout": big_output()}, "session_id": "s"}
            out = hook.reduce_payload(
                ev, asker=DROP_MIDDLE,
                st=store.Store("sess-fp", root=tempfile.mkdtemp()))
            self.assertIsNotNone(out, f"expected filtering for command={command!r}")


class TestShadowMode(unittest.TestCase):
    def test_shadow_mode_returns_none_but_still_records_decision(self):
        """fix-round 1 Important 3：shadow 模式的順序本來就對（先寫紀錄再
        提早回傳 None），但先前沒有任何測試釘住它 —— 順序一旦反過來，
        shadow 模式就完全失去驗證用途卻不會有任何測試失敗。"""
        os.environ["TOOL_REDUCE_MODE"] = "shadow"
        root = tempfile.mkdtemp()
        st = store.Store("sess-shadow", root=root)
        ev = {"tool_name": "Bash", "tool_response": {"stdout": big_output()},
              "session_id": "sess-shadow"}
        out = hook.reduce_payload(ev, asker=DROP_MIDDLE, st=st)
        self.assertIsNone(out)

        p = os.path.join(st.path, "decisions.jsonl")
        self.assertTrue(os.path.exists(p), "shadow mode must still write a decision record")
        rec = json.loads(open(p, encoding="utf-8").readline())
        self.assertIn("decision_id", rec)
        self.assertTrue(any(c["dropped"] for c in rec["chunks"]))


class TestDecisionIdEntropy(unittest.TestCase):
    def test_same_millisecond_still_yields_distinct_decision_ids(self):
        """fix-round 1 Minor：同 session、同 tool、文字前 200 字元、同一
        毫秒時戳過去會雜湊出同一個 decision_id，第二次呼叫的 save_chunk 會
        悄悄覆寫第一次已經現身在模型輸出裡的墓碑對應檔案，且不丟例外。
        用 mock 把 store.now_ms() 釘在同一毫秒，重現這個碰撞情境。"""
        os.environ["TOOL_REDUCE_MODE"] = "full"
        root = tempfile.mkdtemp()
        st = store.Store("sess-collide", root=root)
        ev = {"tool_name": "Bash", "tool_response": {"stdout": big_output()},
              "session_id": "sess-collide"}
        with mock.patch.object(store, "now_ms", return_value=1234567890000):
            out1 = hook.reduce_payload(ev, asker=DROP_MIDDLE, st=st)
            out2 = hook.reduce_payload(ev, asker=DROP_MIDDLE, st=st)
        self.assertIsNotNone(out1)
        self.assertIsNotNone(out2)
        o1 = out1["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
        o2 = out2["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
        d1 = re.findall(r"tr-restore (\S+)\.\d+\]", o1)[0]
        d2 = re.findall(r"tr-restore (\S+)\.\d+\]", o2)[0]
        self.assertNotEqual(d1, d2)


class TestMain(unittest.TestCase):
    """fix-round 1 Important 2: main() 本身完全沒有測試覆蓋，且原本的
    print() 在 try/except 之外 —— 一個沒配對的 UTF-16 surrogate 經過
    json.dumps(ensure_ascii=False) 後，會在 print 把字串編碼成 stdout 的
    UTF-8 位元組時讓 UnicodeEncodeError 逸出，讓整個 hook 非零結束、印出
    traceback，違反「不輸出、exit 0」的 fail-open 契約。"""

    def setUp(self):
        os.environ["TOOL_REDUCE_MODE"] = "full"
        self._old_home = os.environ.get("TOOL_REDUCE_HOME")
        os.environ["TOOL_REDUCE_HOME"] = tempfile.mkdtemp()

    def tearDown(self):
        if self._old_home is None:
            os.environ.pop("TOOL_REDUCE_HOME", None)
        else:
            os.environ["TOOL_REDUCE_HOME"] = self._old_home

    def _run_main(self, stdin_text):
        """用真的會做 UTF-8 編碼的 stdout（TextIOWrapper 包 BytesIO），
        而不是 io.StringIO —— StringIO 只存字串,不編碼,不會重現
        UnicodeEncodeError 那個失效模式。"""
        buf = io.BytesIO()
        stdout_wrapper = io.TextIOWrapper(buf, encoding="utf-8", newline="\n")
        code = "not-called"
        with mock.patch.object(sys, "stdin", io.StringIO(stdin_text)), \
             mock.patch.object(sys, "stdout", stdout_wrapper):
            try:
                hook.main()
            except SystemExit as e:
                code = e.code
            finally:
                try:
                    stdout_wrapper.flush()
                except Exception:
                    pass
        return code, buf.getvalue().decode("utf-8", errors="replace")

    def test_empty_stdin_is_fail_open(self):
        code, out = self._run_main("")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_non_json_stdin_is_fail_open(self):
        code, out = self._run_main("not json{")
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_valid_input_with_no_rewrite_prints_nothing(self):
        payload = json.dumps({"tool_name": "Bash",
                              "tool_response": {"stdout": "tiny"},
                              "session_id": "s"})
        code, out = self._run_main(payload)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")

    def test_valid_input_with_rewrite_prints_hook_output(self):
        ev = {"tool_name": "Bash", "tool_response": {"stdout": big_output()},
              "session_id": "sess-main"}
        with mock.patch.object(hook.jev, "ask", DROP_MIDDLE):
            code, out = self._run_main(json.dumps(ev))
        self.assertEqual(code, 0)
        printed = json.loads(out)
        self.assertIn("hookSpecificOutput", printed)
        self.assertIn("tr-restore",
                      printed["hookSpecificOutput"]["updatedToolOutput"]["stdout"])

    def test_lone_surrogate_in_payload_is_fail_open(self):
        ev = {"tool_name": "Bash",
              "tool_response": {"stdout": big_output_with_surrogate()},
              "session_id": "sess-main"}
        # json.dumps 內建預設 ensure_ascii=True，會把 LONE_SURROGATE 跳脫成
        # \ud800 這個六字元序列 —— 這正是題目描述的「原始輸出裡格式錯誤的
        # \uXXXX escape」，語法上是合法 JSON，json.loads 不會驗證它配不配對。
        payload = json.dumps(ev)
        self.assertIn("\\ud800", payload)
        with mock.patch.object(hook.jev, "ask", DROP_MIDDLE):
            code, out = self._run_main(payload)
        self.assertEqual(code, 0)
        self.assertEqual(out, "")


if __name__ == "__main__":
    unittest.main()
