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


class TestReadJsonlYieldsOnlyDicts(unittest.TestCase):
    """task-8 fix-round 1，第一層防線：read_jsonl 之前只濾掉解析失敗的
    行，任何解析成功但不是字典的 JSON 值（裸字串、list、數字、null）都
    會被傳給 rollup()——store._append 是盡力而為、不保證 atomic，一份
    被截斷的 jsonl 完全可能有一行只剩半截、或整份被別的程式蓋成一個
    純數字，這些形狀要在讀檔這一層就濾掉，rollup() 才能放心假設收到的
    都是字典。"""

    def test_non_dict_lines_are_dropped(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "mixed.jsonl")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write('"just a string"\n')
                fh.write('[1, 2, 3]\n')
                fh.write('42\n')
                fh.write('null\n')
                fh.write('not even json{\n')
                fh.write(json.dumps({"decision_id": "d1", "tool": "Bash"}) + "\n")
            self.assertEqual(stats.read_jsonl(p),
                             [{"decision_id": "d1", "tool": "Bash"}])


class TestRollupToleratesMalformedRecords(unittest.TestCase):
    """task-8 fix-round 1：八條被回報的 crash path，每條都各自對應一筆
    測試，直接餵給 rollup() 而不是先過 read_jsonl——這樣就算未來
    read_jsonl 的過濾邏輯改了，rollup() 本身對「收到形狀不對的紀錄」
    這件事的容錯不會被這層濾網悄悄蓋過去、失去覆蓋。"""

    def test_orphan_restore_with_missing_decision_does_not_crash(self):
        # tombstone／restore 都存在，但那筆 decision 紀錄不見了（decisions
        # .jsonl 沒寫成功、或這次只拿到 archive 的其中一份）。舊版在
        # by_tool 的還原歸屬那段用 next(...) 沒給預設值，找不到就是
        # StopIteration。
        decisions = [{"decision_id": "other", "tool": "Bash",
                     "chars_before": 100, "chunks": []}]
        tombstones = [{"handle": "orphan.1", "decision_id": "ghost",
                      "chars": 500, "descriptor": "d" * 10}]
        restores = [{"handle": "orphan.1", "via": "tr-restore"}]
        r = stats.rollup(decisions, tombstones, restores)
        self.assertEqual(r["restored_chars"], 500)
        self.assertEqual(r["by_tool"]["unknown"]["restored"], 1)
        # 孤兒的 decision_id 不是 decisions 裡真的存在的那一個，不該
        # 灌進 results_with_restore 的分子。
        self.assertEqual(r["results_with_restore"], 0.0)

    def test_decision_missing_chunks_key_does_not_crash(self):
        decisions = [{"decision_id": "d1", "tool": "Bash", "chars_before": 100}]
        r = stats.rollup(decisions, [], [])
        self.assertEqual(r["gross_saved"], 0)
        self.assertEqual(r["decisions"], 1)

    def test_chunks_not_a_list_does_not_crash(self):
        decisions = [{"decision_id": "d1", "tool": "Bash",
                     "chars_before": 100, "chunks": "not-a-list"}]
        r = stats.rollup(decisions, [], [])
        self.assertEqual(r["gross_saved"], 0)

    def test_decision_record_that_is_a_string_is_skipped(self):
        good = {"decision_id": "d1", "tool": "Bash", "chars_before": 100,
                "chunks": [{"i": 0, "chars": 10, "dropped": True}]}
        r = stats.rollup(["oops", good], [], [])
        self.assertEqual(r["decisions"], 1)
        self.assertEqual(r["gross_saved"], 10)

    def test_decision_record_that_is_a_list_is_skipped(self):
        good = {"decision_id": "d1", "tool": "Bash", "chars_before": 100,
                "chunks": [{"i": 0, "chars": 10, "dropped": True}]}
        r = stats.rollup([["nested", "list"], good], [], [])
        self.assertEqual(r["decisions"], 1)
        self.assertEqual(r["gross_saved"], 10)

    def test_tombstone_record_that_is_null_is_skipped(self):
        good_tomb = {"handle": "d1.1", "decision_id": "d1", "chars": 700,
                    "descriptor": "x" * 10}
        r = stats.rollup(DECISIONS, [None, good_tomb], RESTORES)
        self.assertEqual(r["tombstones"], 1)
        self.assertEqual(r["restored_chars"], 700)

    def test_restore_record_that_is_a_number_is_skipped(self):
        r = stats.rollup(DECISIONS, TOMBSTONES,
                         [42, {"handle": "d1.1", "via": "tr-restore"}])
        self.assertEqual(r["restores"], 1)
        self.assertEqual(r["restored_chars"], 700)

    def test_every_record_missing_chars_before_does_not_crash(self):
        # 欄位是 None（不是缺鍵）：.get(key, 0) 的預設值只在缺鍵時生效，
        # 值本身是 None 一樣要被當成「沒有這個數字」，不能讓 None + 0
        # 逸出 TypeError。
        decisions = [{"decision_id": "d1", "tool": "Bash", "chars_before": None,
                     "chunks": [{"i": 0, "chars": 50, "dropped": True}]},
                    {"decision_id": "d2", "tool": "Bash",
                     "chunks": [{"i": 0, "chars": 30, "dropped": True}]}]
        r = stats.rollup(decisions, [], [])
        self.assertEqual(r["gross_saved"], 80)
        self.assertEqual(r["by_tool"]["Bash"]["chars_before"], 0)
        self.assertIsNone(r["net_ratio"])


class TestZeroDenominatorRatioIsUnavailable(unittest.TestCase):
    """total_before 是 0（沒有任何一筆紀錄帶 chars_before，或全部都是 0）
    時，net_ratio 要回報成「算不出來」（None），不是拿 1 頂替分母印出一個
    看起來很精確、其實是灌水的百分比。"""

    def test_empty_input_ratio_is_none(self):
        r = stats.rollup([], [], [])
        self.assertIsNone(r["net_ratio"])
        self.assertEqual(r["net_saved"], 0)

    def test_nonzero_savings_with_zero_denominator_ratio_is_none(self):
        decisions = [{"decision_id": "d1", "tool": "Bash",
                     "chunks": [{"i": 0, "chars": 500, "dropped": True}]}]
        r = stats.rollup(decisions, [], [])
        self.assertEqual(r["gross_saved"], 500)
        self.assertIsNone(r["net_ratio"])


class TestSessionArgumentRejectsTraversal(unittest.TestCase):
    """--session 直接跟存放區根目錄 os.path.join，舊版完全沒驗證就拿去
    讀檔——`--session ../../../../etc` 會被正規化到存放區外面，讀出
    存放區以外的內容還 exit 0。字元集合先擋掉 `.`／`/`，containment
    檢查再擋 symlink 這種字元集合擋不住的形狀（跟 store.load_chunk、
    tr-guard 驗證 handle 同一招）。"""

    def _run(self, home, *extra_args):
        env = dict(os.environ, TOOL_REDUCE_HOME=home)
        return subprocess.run([sys.executable, STATS_PATH, *extra_args],
                              capture_output=True, text=True, env=env)

    def test_traversal_session_id_is_rejected(self):
        home = tempfile.mkdtemp()
        r = self._run(home, "--session", "../../../../etc")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("invalid session id", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_session_id_with_slash_is_rejected(self):
        home = tempfile.mkdtemp()
        r = self._run(home, "--session", "sess/../../outside")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("invalid session id", r.stderr)

    def test_named_session_that_does_not_exist_reports_error_not_archive_fallback(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        with open(os.path.join(home, "archive", "decisions.jsonl"), "w",
                 encoding="utf-8") as fh:
            fh.write(json.dumps({"decision_id": "d1", "tool": "Bash",
                                "chars_before": 100, "chunks": []}) + "\n")
        r = self._run(home, "--session", "does-not-exist")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no such session", r.stderr)
        # 錯誤結束就不該再印任何統計數字（尤其不能是封存區的那 1 筆）。
        self.assertEqual(r.stdout, "")

    def test_valid_session_name_still_works(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "sess-1"), exist_ok=True)
        with open(os.path.join(home, "sess-1", "decisions.jsonl"), "w",
                 encoding="utf-8") as fh:
            fh.write(json.dumps({"decision_id": "d1", "tool": "Bash",
                                "chars_before": 100, "chunks": []}) + "\n")
        r = self._run(home, "--session", "sess-1", "--json")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["decisions"], 1)


if __name__ == "__main__":
    unittest.main()
