# tests/python/test_eval.py
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

BASE = os.path.join(os.path.dirname(__file__), "../..")
TR = os.path.join(BASE, "chezmoi/private_dot_config/claude/tool-reduce")
sys.path.insert(0, TR)
import store


def load(name, fname):
    spec = importlib.util.spec_from_file_location(name, os.path.join(TR, fname))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


stats = load("tr_stats", "executable_tr-stats.py")

STATS_PATH = os.path.join(TR, "executable_tr-stats.py")

DECISIONS = [
    {"decision_id": "d1", "tool": "Bash", "chars_before": 10000, "chars_after": 8800,
     "chars_saved": 1200,
     "chunks": [{"i": 0, "chars": 1000, "dropped": False, "distinctive": ["keep_a"]},
                {"i": 1, "chars": 700, "dropped": True, "distinctive": ["gone_b"]},
                {"i": 2, "chars": 620, "dropped": True, "distinctive": ["gone_c"]},
                {"i": 3, "chars": 900, "dropped": False, "distinctive": ["keep_d"]}]},
    {"decision_id": "d2", "tool": "Read", "chars_before": 5000, "chars_after": 4700,
     "chars_saved": 300,
     "chunks": [{"i": 0, "chars": 900, "dropped": False, "distinctive": []},
                {"i": 1, "chars": 420, "dropped": True, "distinctive": ["gone_e"]},
                {"i": 2, "chars": 800, "dropped": False, "distinctive": []}]},
]
TOMBSTONES = [{"handle": "d1.1", "decision_id": "d1", "chars": 700, "descriptor": "x" * 120},
              {"handle": "d1.2", "decision_id": "d1", "chars": 620, "descriptor": "x" * 120},
              {"handle": "d2.1", "decision_id": "d2", "chars": 420, "descriptor": "x" * 120}]
RESTORES = [{"handle": "d1.1", "via": "tr-restore"}]


class TestRollup(unittest.TestCase):
    def setUp(self):
        self.r = stats.rollup(DECISIONS, TOMBSTONES, RESTORES)

    def test_gross_saved_sums_dropped_chunks(self):
        self.assertEqual(self.r["gross_saved"], 700 + 620 + 420)

    def test_tombstone_cost(self):
        self.assertEqual(self.r["tombstone_cost"], 360)

    def test_restored_chars_counted_once(self):
        self.assertEqual(self.r["restored_chars"], 700)

    def test_net_saved(self):
        self.assertEqual(self.r["net_saved"], 1740 - 360 - 700)

    def test_restore_rate(self):
        self.assertAlmostEqual(self.r["restore_rate"], 1 / 3)

    def test_results_with_restore(self):
        self.assertAlmostEqual(self.r["results_with_restore"], 1 / 2)

    def test_by_tool_breakdown(self):
        self.assertEqual(self.r["by_tool"]["Bash"]["gross_saved"], 1320)
        self.assertEqual(self.r["by_tool"]["Read"]["gross_saved"], 420)

    def test_empty_input_does_not_divide_by_zero(self):
        r = stats.rollup([], [], [])
        self.assertEqual(r["net_saved"], 0)
        self.assertEqual(r["restore_rate"], 0.0)

    def test_score_histogram_has_ten_buckets(self):
        d = [{"decision_id": "h1", "tool": "Bash", "chars_before": 100, "chars_after": 100,
              "chars_saved": 0,
              "chunks": [{"i": 0, "chars": 10, "dropped": False, "distinctive": [],
                          "scores": {"noise": 0.05, "uniq": 0.5}},
                         {"i": 1, "chars": 10, "dropped": True, "distinctive": [],
                          "scores": {"noise": 0.95, "uniq": 0.1}},
                         {"i": 2, "chars": 10, "dropped": False, "distinctive": [],
                          "scores": {"noise": 0.95, "uniq": 0.9}}]}]
        h = stats.rollup(d, [], [])["score_hist"]
        self.assertEqual(len(h), 10)
        self.assertEqual(h[0], 1)     # 0.05 落在第 0 格
        self.assertEqual(h[9], 2)     # 兩個 0.95 落在第 9 格

    def test_score_histogram_ignores_missing_scores(self):
        d = [{"decision_id": "h2", "tool": "Bash", "chars_before": 10, "chars_after": 10,
              "chars_saved": 0,
              "chunks": [{"i": 0, "chars": 10, "dropped": False, "distinctive": []}]}]
        self.assertEqual(sum(stats.rollup(d, [], [])["score_hist"]), 0)

    def test_score_histogram_ignores_null_score_value(self):
        # 真實紀錄裡每個段落都有 "scores" 鍵（jev.scores 攤平後的結果），
        # 但問答失敗時值會是 None，不是缺鍵 —— 兩種「沒有分數」的形狀都
        # 不該被當成 0 分落進第 0 格。
        d = [{"decision_id": "h3", "tool": "Bash", "chars_before": 10, "chars_after": 10,
              "chars_saved": 0,
              "chunks": [{"i": 0, "chars": 10, "dropped": False, "distinctive": [],
                          "scores": {"noise": None, "uniq": None}}]}]
        self.assertEqual(sum(stats.rollup(d, [], [])["score_hist"]), 0)


class TestRestoreDoubleCountingIsCollapsed(unittest.TestCase):
    """restores.jsonl 的 via 只是「怎麼還原的」，不是兩種不同事件——同一個
    handle 不管被 tr-restore 跟 direct-read 各記一次，還是同一條路徑記了
    兩次，對 restored_chars／restore_rate／results_with_restore 都只能算
    一次。"""

    def test_same_handle_restored_via_both_routes_counts_once(self):
        restores = [{"handle": "d1.1", "via": "tr-restore"},
                     {"handle": "d1.1", "via": "direct-read", "tool": "Bash"}]
        r = stats.rollup(DECISIONS, TOMBSTONES, restores)
        self.assertEqual(r["restored_chars"], 700)
        self.assertAlmostEqual(r["restore_rate"], 1 / 3)

    def test_same_handle_restored_twice_by_same_route_counts_once(self):
        restores = [{"handle": "d1.1", "via": "tr-restore"},
                     {"handle": "d1.1", "via": "tr-restore"}]
        r = stats.rollup(DECISIONS, TOMBSTONES, restores)
        self.assertEqual(r["restored_chars"], 700)
        self.assertAlmostEqual(r["restore_rate"], 1 / 3)

    def test_two_distinct_handles_each_still_count(self):
        restores = [{"handle": "d1.1", "via": "tr-restore"},
                     {"handle": "d1.1", "via": "direct-read", "tool": "Bash"},
                     {"handle": "d1.2", "via": "direct-read", "tool": "Read"}]
        r = stats.rollup(DECISIONS, TOMBSTONES, restores)
        self.assertEqual(r["restored_chars"], 700 + 620)
        self.assertAlmostEqual(r["restore_rate"], 2 / 3)


class TestStoreRootResolvedFreshEachCall(unittest.TestCase):
    """main() 要跟 tr-restore／tr-guard／PostToolUse hook 一樣，走
    store.root()、且每次執行都重新解析，不能在模組載入當下就把根目錄
    凍結成常數——否則同一個行程裡先讀早、後設 TOOL_REDUCE_HOME 的呼叫端
    會看到舊值（task-7 抓到的同一種 bug 的形狀）。這裡不 mock，直接讓兩次
    呼叫在同一個 process 裡分別指向兩個不同的暫存目錄，反向證明沒有任何
    地方把根目錄快取住。"""

    def setUp(self):
        self._env_patch = mock.patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        self.addCleanup(self._env_patch.stop)

    def _run_json(self):
        buf = io.StringIO()
        with mock.patch.object(sys, "argv", ["tr-stats.py", "--json"]), \
             contextlib.redirect_stdout(buf):
            rc = stats.main()
        self.assertEqual(rc, 0)
        return json.loads(buf.getvalue())

    def test_module_level_constant_is_not_frozen_at_import(self):
        self.assertFalse(hasattr(stats, "HOME"),
                          "store root must not be frozen into a module-level "
                          "constant computed at import time")

    def test_two_calls_in_one_process_see_two_different_roots(self):
        root_a = tempfile.mkdtemp()
        root_b = tempfile.mkdtemp()
        st_a = store.Store("sess-a", root=root_a)
        st_a.record_decision({"decision_id": "a1", "tool": "Bash",
                              "chars_before": 100, "chunks": []})

        os.environ["TOOL_REDUCE_HOME"] = root_a
        first = self._run_json()
        self.assertEqual(first["decisions"], 1)

        os.environ["TOOL_REDUCE_HOME"] = root_b
        second = self._run_json()
        self.assertEqual(second["decisions"], 0)


class TestFreshOrAbsentStoreDoesNotCrash(unittest.TestCase):
    """一個全新安裝、還沒發生過任何一次 reduce 的環境沒有任何紀錄檔，
    甚至存放區根目錄本身都不存在——tr-stats 這時必須印出全 0，不是
    traceback、也不是除以零。走 subprocess 是為了連 main() 之外、
    argparse／print 那段實際印出來的東西也一起驗證到，跟部署後真的被
    執行時的路徑一致。"""

    def _run(self, home, extra_args=()):
        env = dict(os.environ, TOOL_REDUCE_HOME=home)
        return subprocess.run([sys.executable, STATS_PATH, *extra_args],
                              capture_output=True, text=True, env=env)

    def test_missing_store_root_prints_zeros_not_a_traceback(self):
        home = os.path.join(tempfile.mkdtemp(), "does-not-exist-yet")
        r = self._run(home)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn("Traceback", r.stdout)
        self.assertIn("決策 0 筆", r.stdout)

    def test_empty_archive_dir_prints_zeros_as_json(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        r = self._run(home, extra_args=("--json",))
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        payload = json.loads(r.stdout)
        self.assertEqual(payload["decisions"], 0)
        self.assertEqual(payload["net_saved"], 0)
        self.assertEqual(payload["restore_rate"], 0.0)
        self.assertEqual(payload["results_with_restore"], 0.0)
        self.assertEqual(payload["score_hist"], [0] * 10)


if __name__ == "__main__":
    unittest.main()
