# tests/python/test_hook_integration.py
import sys, os, io, re, json, subprocess, tempfile, time, importlib.util, unittest
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


class TestIsRestoreCallBounded(unittest.TestCase):
    """fix-round 3：`_reads_store_file` 對每個候選路徑都呼叫
    `os.path.realpath`（一次系統呼叫），沒有上限。這段跑在每個過了 size
    gate 的 tool result 前面、Jev 的 2.5s 預算之前 —— 量測：30,000 個
    帶斜線 token、每個都真的做 realpath，要 12 秒，會讓整個 session 卡住。
    套上三道防線（形狀過濾、解析次數封頂 32 次、掃描 blob 封頂 64 KB）
    後歸零，見 `_reads_store_file` 的 docstring。"""

    def test_large_edit_with_many_path_shaped_tokens_resolves_within_bound(self):
        # 刻意用絕對路徑形狀（/aN/bN），確保 fix-round 3 加的形狀過濾器
        # 不會直接把它們全部濾掉 —— 真正要測的是「realpath 呼叫次數有沒有
        # 封頂」，不是「形狀過濾擋掉了幾個」（那件事 old_string/new_string
        # 用一般程式碼片段就測得到，跟這裡的延遲測試是兩回事）。
        old_string = " ".join(f"/a{i}/b{i}" for i in range(30000))
        new_string = " ".join(f"/c{i}/d{i}" for i in range(30000))
        ev = {"tool_name": "Edit", "tool_input": {
            "file_path": "/Users/kirk/Code/devbox/somefile.py",
            "old_string": old_string, "new_string": new_string}}
        t0 = time.perf_counter()
        result = hook.is_restore_call(ev)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        self.assertLess(
            elapsed_ms, 100,
            f"is_restore_call took {elapsed_ms:.1f} ms on a 30,000-token "
            "Edit input, expected well under 100 ms")
        # 這些 token 沒有一個真的指到存放區，形狀過濾器讓它們通過候選、
        # 但解析後都不等於／不落在 _STORE_ROOT_REAL 底下。
        self.assertFalse(result)

    def test_exception_during_resolution_fails_safe_to_skip_filtering(self):
        """is_restore_call 的 fail-safe：解析過程（expanduser／realpath）
        只要丟例外就當作還原呼叫、整份放行不過濾 —— 誤放行頂多多送一次
        未過濾的原始輸出，誤過濾則會把 agent 剛還原回來的內容再刪一次，
        代價不對稱。用 mock 讓 os.path.realpath 直接丟例外來重現。"""
        ev = {"tool_name": "Bash", "tool_input": {"command": "cat /some/path"}}
        with mock.patch.object(os.path, "realpath", side_effect=OSError("boom")):
            self.assertTrue(hook.is_restore_call(ev))


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




# ---------------------------------------------------------------------------
# final review C1 / I1 / I3 / I6
# ---------------------------------------------------------------------------

HOOK_PATH = os.path.join(
    BASE, "chezmoi/private_dot_config/claude/hooks/executable_tool-reduce.py")

# 墓碑標記的形狀（descriptor.make）：`[省略 N 行 · <首行摘要> · tr-restore <handle>]`
MARKER_RE = re.compile(r"\[省略[^\n]*?tr-restore (\S+?)\]")


def mcp_envelope(payload=None):
    """一個 `mcp:*` 信封：外層是 JSON 物件，要過濾的文字在其中一個鍵裡。

    chunker.unwrap() 對這種形狀會回傳「裡面那個字串」當 payload，kind 是
    `mcp:log` —— chunk() 切的是 payload，不是整份 text。實測（最近 150 份
    transcript）過了 size gate 的 1,740 筆結果裡有 55 筆（3.2%）走這條路，
    而且正好是 10-21 KB 的大型結構化結果，也就是這個過濾器真正想處理的
    那一類。"""
    return json.dumps({"schemaVersion": 1, "log": payload or big_output()},
                      ensure_ascii=False)


def restore_every_marker(payload, st):
    """把 payload 裡每個墓碑標記換回存放區裡的原文，重建原始 payload。

    hook 寫出來的形狀是 `("\\n" if 原文不是以換行開頭 else "") + marker
    + "\\n"`，這裡照著反推，才能驗到「逐字還原」而不只是「大致還原」。"""
    out, pos = [], 0
    for m in MARKER_RE.finditer(payload):
        chunk = st.load_chunk(m.group(1))
        assert chunk is not None, f"tombstone points at nothing: {m.group(1)}"
        start, end = m.start(), m.end()
        if payload[end:end + 1] == "\n":
            end += 1
        if not chunk.startswith("\n") and start > 0 and payload[start - 1] == "\n":
            start -= 1
        out.append(payload[pos:start])
        out.append(chunk)
        pos = end
    out.append(payload[pos:])
    return "".join(out)


class TestMcpEnvelopeSurvivesFiltering(unittest.TestCase):
    """C1：chunker.chunk() 回的是 payload 的切片，`mcp:*` 信封的 payload 是
    「裡面那個字串」。hook 以前把 "".join(out_parts) 當成整份文字寫回去，
    外層 JSON 物件、它其他的鍵、以及所有跳脫全部消失，模型拿到的不是「少
    一點的內容」而是「錯的內容」—— 這是整輪 review 裡唯一一條會餵錯東西
    給模型的路徑。而且那個信封從來不是一個段落、沒被存進存放區，
    tr-restore 也救不回來。"""

    def setUp(self):
        os.environ["TOOL_REDUCE_MODE"] = "full"
        self.root = tempfile.mkdtemp()
        self.st = store.Store("sess-mcp", root=self.root)
        self.text = mcp_envelope()
        ev = {"tool_name": "Bash", "tool_response": {"stdout": self.text},
              "session_id": "sess-mcp"}
        self.out = hook.reduce_payload(ev, asker=DROP_MIDDLE, st=self.st)

    def test_chunker_really_takes_the_envelope_peel_path(self):
        _chunks, kind = hook.chunker.chunk(self.text)
        self.assertEqual(kind, "mcp:log")

    def test_filtered_result_still_parses_as_its_original_envelope(self):
        self.assertIsNotNone(self.out)
        stdout = self.out["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
        obj = json.loads(stdout)                       # 舊版在這裡就炸了
        self.assertEqual(obj["schemaVersion"], 1)      # 其他的鍵不能消失
        self.assertEqual(set(obj), {"schemaVersion", "log"})
        self.assertIn("tr-restore", obj["log"])        # 真的有過濾，不是原樣放行
        self.assertLess(len(obj["log"]), len(json.loads(self.text)["log"]))

    def test_restoring_every_tombstone_rebuilds_the_payload_byte_for_byte(self):
        stdout = self.out["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
        filtered_payload = json.loads(stdout)["log"]
        self.assertTrue(MARKER_RE.search(filtered_payload), "expected tombstones")
        self.assertEqual(restore_every_marker(filtered_payload, self.st),
                         json.loads(self.text)["log"])

    def test_broken_envelope_fails_open_instead_of_shipping_the_bare_payload(self):
        """rewrap 組不回信封時（kind 描述不了這份 text）要整份放行，不能
        退而求其次把裸 payload 送出去 —— 那正是 C1 的失效模式本身。"""
        with self.assertRaises(ValueError):
            hook.chunker.rewrap('{"log": 1}', "mcp:log", "x")
        with self.assertRaises(ValueError):
            hook.chunker.rewrap("not json", "mcp:log", "x")

    def test_raw_and_read_envelopes_are_identities(self):
        self.assertEqual(hook.chunker.rewrap("abc", "raw", "xyz"), "xyz")
        self.assertEqual(hook.chunker.rewrap("abc", "read", "xyz"), "xyz")


class TestModeIsOnTheRecord(unittest.TestCase):
    """I3：record_decision／record_tombstone 都跑在 `if mode == "shadow":
    return None` 之前，紀錄本身卻沒有任何欄位能分辨「真的刪了」跟「只是
    演練」。README 的上線流程就是先 shadow 再 full，兩種紀錄會混進同一份
    append-only 的 archive/，三支離線工具讀的都是它。"""

    def _record(self, mode, session):
        os.environ["TOOL_REDUCE_MODE"] = mode
        root = tempfile.mkdtemp()
        st = store.Store(session, root=root)
        ev = {"tool_name": "Bash", "tool_response": {"stdout": big_output()},
              "session_id": session}
        hook.reduce_payload(ev, asker=DROP_MIDDLE, st=st)
        with open(os.path.join(st.path, "decisions.jsonl"), encoding="utf-8") as fh:
            decision = json.loads(fh.readline())
        with open(os.path.join(st.path, "tombstones.jsonl"), encoding="utf-8") as fh:
            tombstone = json.loads(fh.readline())
        return decision, tombstone

    def test_shadow_records_are_labelled_shadow(self):
        decision, tombstone = self._record("shadow", "sess-mode-shadow")
        self.assertEqual(decision["mode"], "shadow")
        self.assertEqual(tombstone["mode"], "shadow")

    def test_full_records_are_labelled_full(self):
        decision, tombstone = self._record("full", "sess-mode-full")
        self.assertEqual(decision["mode"], "full")
        self.assertEqual(tombstone["mode"], "full")


def big_output_with_surrogate_in_the_middle():
    """把沒配對的 surrogate 放進一個「會被刪掉」的中間段，讓 save_chunk 在
    迴圈中途丟 UnicodeEncodeError —— 不是放尾端錨點段（那個永遠不會被刪，
    失敗點落在 print()，測的是另一件事）。"""
    return big_output().replace("## Section 5\n", "## Section 5\n" + LONE_SURROGATE, 1)


class TestMidLoopFailureLeavesNoOrphanRecords(unittest.TestCase):
    """I6：墓碑紀錄會同時被附加寫進 archive/，而 archive/ 永遠不會被清掉
    （tr-cleanup.sh 刻意不碰它，7 天掃除也排除它）。以前是邊算邊寫：迴圈
    中途失敗會留下一批指向「其實沒有發生的刪除」的孤兒墓碑紀錄，加上一個
    被 open(p,"w") 截斷成零位元組的段落檔案，而決策紀錄根本沒寫成。
    fail-open 有守住（輸出沒被改）、紀錄卻永久髒掉：tr-stats 從此把那幾百
    字元的墓碑成本算在零節省上。"""

    def setUp(self):
        os.environ["TOOL_REDUCE_MODE"] = "full"
        self.root = tempfile.mkdtemp()
        self.st = store.Store("sess-orphan", root=self.root)

    def _run(self):
        ev = {"tool_name": "Bash",
              "tool_response": {"stdout": big_output_with_surrogate_in_the_middle()},
              "session_id": "sess-orphan"}
        with self.assertRaises(UnicodeEncodeError):
            hook.reduce_payload(ev, asker=DROP_MIDDLE, st=self.st)

    def test_no_tombstone_record_lands_in_the_permanent_archive(self):
        self._run()
        for d in (self.st.path, self.st.archive):
            self.assertFalse(os.path.exists(os.path.join(d, "tombstones.jsonl")),
                             f"orphan tombstone records under {d}")
            self.assertFalse(os.path.exists(os.path.join(d, "decisions.jsonl")))

    def test_no_truncated_zero_byte_chunk_file_is_left_behind(self):
        self._run()
        if not os.path.isdir(self.st.path):
            return
        for name in os.listdir(self.st.path):
            if name.endswith(".txt"):
                p = os.path.join(self.st.path, name)
                self.assertGreater(os.path.getsize(p), 0,
                                   f"{name} is a tombstone pointing at nothing")

    def test_main_still_fails_open(self):
        ev = {"tool_name": "Bash",
              "tool_response": {"stdout": big_output_with_surrogate_in_the_middle()},
              "session_id": "sess-orphan-main"}
        buf = io.BytesIO()
        wrapper = io.TextIOWrapper(buf, encoding="utf-8", newline="\n")
        old_home = os.environ.get("TOOL_REDUCE_HOME")
        os.environ["TOOL_REDUCE_HOME"] = self.root
        try:
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(ev))), \
                 mock.patch.object(sys, "stdout", wrapper), \
                 mock.patch.object(hook.jev, "ask", DROP_MIDDLE):
                with self.assertRaises(SystemExit) as cm:
                    hook.main()
            wrapper.flush()
        finally:
            if old_home is None:
                os.environ.pop("TOOL_REDUCE_HOME", None)
            else:
                os.environ["TOOL_REDUCE_HOME"] = old_home
        self.assertEqual(cm.exception.code, 0)
        self.assertEqual(buf.getvalue().decode("utf-8", "replace"), "")


class TestEnvKnobsAreParsedInsideTheGuardedPath(unittest.TestCase):
    """I1：SIZE_GATE／TIMEOUT／MAX_CHUNKS 以前在模組層級解析，跑在 import
    時、也就是 main() 的 try 之外。`TOOL_REDUCE_SIZE_GATE=2k` 這種手打錯誤
    會讓 hook 在這個 session 的「每一次工具呼叫」都非零結束、印出帶部署
    路徑的 traceback。這些是 README 明列、要人手編輯 typesafe.env 的旋鈕。

    走 subprocess，因為要測的正是「模組載入本身」會不會炸 —— 在同一個
    行程裡重用已經載入好的模組測不到那件事。"""

    def _run(self, env_overrides, stdin_text):
        env = dict(os.environ, TOOL_REDUCE_LIB=LIB,
                   TOOL_REDUCE_HOME=tempfile.mkdtemp(), TOOL_REDUCE_MODE="full")
        env.update(env_overrides)
        return subprocess.run([sys.executable, HOOK_PATH], input=stdin_text,
                              capture_output=True, text=True, env=env)

    def test_unparseable_size_gate_is_fail_open(self):
        ev = json.dumps({"tool_name": "Bash", "tool_response": {"stdout": "tiny"},
                         "session_id": "s"})
        r = self._run({"TOOL_REDUCE_SIZE_GATE": "2k"}, ev)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual(r.stderr, "")

    def test_unparseable_timeout_and_max_chunks_are_fail_open(self):
        ev = json.dumps({"tool_name": "Bash", "tool_response": {"stdout": "tiny"},
                         "session_id": "s"})
        r = self._run({"TOOL_REDUCE_TIMEOUT": "fast",
                       "TOOL_REDUCE_MAX_CHUNKS": ""}, ev)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")

    def test_a_valid_override_is_still_honoured(self):
        """退回預設值不能變成「忽略這個旋鈕」—— 合法的值要照用。"""
        gate = len(big_output()) + 1000
        ev = json.dumps({"tool_name": "Bash", "tool_response": {"stdout": big_output()},
                         "session_id": "s"})
        r = self._run({"TOOL_REDUCE_SIZE_GATE": str(gate)}, ev)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "")      # 被自訂的 size gate 擋下來，不判斷


if __name__ == "__main__":
    unittest.main()
