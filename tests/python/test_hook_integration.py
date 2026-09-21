# tests/python/test_hook_integration.py
import sys, os, json, tempfile, importlib.util, unittest

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


if __name__ == "__main__":
    unittest.main()
