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
    """fix-round 1 Important 1：舊版對整個 tool_input 做鬆散子字串比對
    （"tr-restore" in blob or "tool-reduce/" in blob），任何提到原始碼路徑
    的指令都會被誤判成還原呼叫、整份放行不過濾。修正後只比對兩種精確
    情況：tr-restore 指令本身（當獨立字詞），或直接讀 session 存放區
    （~/.claude/tool-reduce，跟原始碼目錄是不同路徑）。"""

    def _ev(self, command):
        return {"tool_name": "Bash", "tool_input": {"command": command}}

    def test_ls_of_source_dir_is_not_a_restore_call(self):
        # 舊版誤判：只是列出原始碼目錄，不是還原呼叫。
        self.assertFalse(hook.is_restore_call(
            self._ev("ls chezmoi/private_dot_config/claude/tool-reduce/")))

    def test_grep_of_source_dir_is_not_a_restore_call(self):
        # 舊版誤判：只是在原始碼目錄裡 grep，不是還原呼叫。
        self.assertFalse(hook.is_restore_call(self._ev(
            "grep -rn noise chezmoi/private_dot_config/claude/tool-reduce/*.py")))

    def test_tr_restore_invocation_is_a_restore_call(self):
        self.assertTrue(hook.is_restore_call(self._ev("tr-restore a3f2.7")))

    def test_cat_of_session_store_is_a_restore_call(self):
        self.assertTrue(hook.is_restore_call(
            self._ev("cat ~/.claude/tool-reduce/sess/a3f2.7.txt")))

    def test_tr_restore_as_substring_of_another_word_is_not_a_restore_call(self):
        # "獨立字詞" 的邊界測試：不是子字串就算數。
        self.assertFalse(hook.is_restore_call(self._ev("echo tr-restored already")))

    def test_reduce_payload_now_filters_the_previously_false_positive_commands(self):
        """舊版的兩個誤判案例（ls/grep 原始碼目錄）過去會讓 reduce_payload
        整份放行；修正後要真的走完整個過濾流程並產生輸出。"""
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
