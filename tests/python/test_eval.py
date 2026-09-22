# tests/python/test_eval.py
import contextlib
import hashlib
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


class TestRecordsSkippedCount(unittest.TestCase):
    """task-8 fix-round 2：容錯不能變成無聲——一份被截斷的封存區（
    store._append 盡力而為的正常結果）算出來的總數要帶著『有東西被略過』
    的信號，不是看起來一樣自信的 0。"""

    def test_clean_input_reports_zero_skipped(self):
        r = stats.rollup(DECISIONS, TOMBSTONES, RESTORES)
        self.assertEqual(r["records_skipped"], 0)

    def test_mixed_good_and_bad_records_counts_every_skip(self):
        decisions = [
            "oops",                                        # 不是 dict：+1
            ["nested"],                                     # 不是 dict：+1
            {"decision_id": "d1", "tool": "Bash",            # chunks 缺欄位：+1
             "chars_before": 100},
            {"decision_id": "d2", "tool": "Bash",            # chunks 型別不對：+1
             "chars_before": 100, "chunks": "nope"},
            {"decision_id": "d3", "tool": "Bash", "chars_before": 100,  # 正常
             "chunks": [{"i": 0, "chars": 10, "dropped": True}]},
        ]
        tombstones = [
            None,                                            # 不是 dict：+1
            {"decision_id": "d3", "chars": 5},                # 缺 handle：+1
            {"handle": "d3.1", "decision_id": "d3", "chars": 10,  # 正常
             "descriptor": "xxxxx"},
        ]
        restores = [
            42,                                               # 不是 dict：+1
            {"handle": "d3.1", "via": "tr-restore"},          # 正常
        ]
        r = stats.rollup(decisions, tombstones, restores)
        # 2（decisions 非 dict）+ 2（chunks 缺／型別不對）
        # + 2（tombstones 非 dict／缺 handle）+ 1（restores 非 dict）= 7
        self.assertEqual(r["records_skipped"], 7)
        # 沒被略過的那幾筆算出來的數字要照常正確，不能被略過的紀錄拖累。
        self.assertEqual(r["decisions"], 3)
        self.assertEqual(r["gross_saved"], 10)
        self.assertEqual(r["restored_chars"], 10)

    def test_read_jsonl_without_counter_is_unchanged(self):
        # skip_counter 是選擇性參數，沒帶的呼叫端（既有測試／呼叫）行為
        # 必須跟 fix-round 2 之前完全一樣。
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "mixed.jsonl")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write('"oops"\n')
                fh.write(json.dumps({"decision_id": "d1"}) + "\n")
            self.assertEqual(stats.read_jsonl(p), [{"decision_id": "d1"}])

    def test_read_jsonl_skip_counter_counts_unparsable_and_non_dict_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "mixed.jsonl")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("not even json{\n")            # 解析失敗：+1
                fh.write('"a string"\n')                 # 不是 dict：+1
                fh.write("[1, 2]\n")                      # 不是 dict：+1
                fh.write(json.dumps({"decision_id": "d1"}) + "\n")  # 正常
            counter = [0]
            out = stats.read_jsonl(p, counter)
            self.assertEqual(out, [{"decision_id": "d1"}])
            self.assertEqual(counter[0], 3)

    def test_cli_json_always_includes_records_skipped_field(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        env = dict(os.environ, TOOL_REDUCE_HOME=home)
        r = subprocess.run([sys.executable, STATS_PATH, "--json"],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout)["records_skipped"], 0)

    def test_cli_human_readable_prints_nothing_extra_when_clean(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        with open(os.path.join(home, "archive", "decisions.jsonl"), "w",
                 encoding="utf-8") as fh:
            fh.write(json.dumps({"decision_id": "d1", "tool": "Bash",
                                "chars_before": 100, "chunks": []}) + "\n")
        env = dict(os.environ, TOOL_REDUCE_HOME=home)
        r = subprocess.run([sys.executable, STATS_PATH],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("略過", r.stdout)

    def test_cli_human_readable_and_json_surface_skips_from_a_truncated_archive(self):
        # 端對端：read_jsonl 那關（解析失敗的行）跟 rollup() 那關（收到
        # 的 dict 形狀不對）的略過筆數要合併成同一個總數，兩邊沒有誰算
        # 兩次、也沒有誰漏算。
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        with open(os.path.join(home, "archive", "decisions.jsonl"), "w",
                 encoding="utf-8") as fh:
            fh.write("truncated garbage not json{\n")           # read 關：+1
            fh.write(json.dumps({"decision_id": "d1", "tool": "Bash",
                                "chars_before": 100,
                                "chunks": [{"i": 0, "chars": 10,
                                           "dropped": True}]}) + "\n")
            fh.write(json.dumps({"decision_id": "d2", "tool": "Bash"}) + "\n")  # rollup 關（缺 chunks）：+1
        env = dict(os.environ, TOOL_REDUCE_HOME=home)

        r_json = subprocess.run([sys.executable, STATS_PATH, "--json"],
                                capture_output=True, text=True, env=env)
        self.assertEqual(r_json.returncode, 0)
        payload = json.loads(r_json.stdout)
        self.assertEqual(payload["records_skipped"], 2)
        self.assertEqual(payload["gross_saved"], 10)

        r_human = subprocess.run([sys.executable, STATS_PATH],
                                 capture_output=True, text=True, env=env)
        self.assertEqual(r_human.returncode, 0)
        self.assertIn("2 筆紀錄格式不對", r_human.stdout)


class TestNonStringDescriptorDoesNotCrash(unittest.TestCase):
    """task-8 fix-round 2：tomb_cost 之前用 `t.get("descriptor") or ""`——
    descriptor 是 123 這種非字串但仍是 truthy 的值時，`or` 不會被觸發，
    直接對 123 呼叫 len() 丟 TypeError。非字串 descriptor 一律當成 0 成本。
    """

    def test_numeric_descriptor_contributes_zero_cost(self):
        tombstones = [{"handle": "d1.1", "decision_id": "d1", "chars": 700,
                      "descriptor": 123}]
        r = stats.rollup(DECISIONS, tombstones, [])
        self.assertEqual(r["tombstone_cost"], 0)

    def test_mixed_string_and_non_string_descriptors(self):
        tombstones = [{"handle": "d1.1", "decision_id": "d1", "chars": 700,
                      "descriptor": "x" * 50},
                     {"handle": "d1.2", "decision_id": "d1", "chars": 620,
                      "descriptor": None},
                     {"handle": "d2.1", "decision_id": "d2", "chars": 420,
                      "descriptor": ["not", "a", "string"]}]
        r = stats.rollup(DECISIONS, tombstones, [])
        self.assertEqual(r["tombstone_cost"], 50)


# ---------------------------------------------------------------------------
# task-9: tr-eval, Layer 1 三態分類
# ---------------------------------------------------------------------------

tr_eval = load("tr_eval", "executable_tr-eval.py")

EVAL_PATH = os.path.join(TR, "executable_tr-eval.py")


class TestClassify(unittest.TestCase):
    """三態：
      墓碑被還原              -> restored     （確定誤刪，agent 自己救回來了）
      沒還原但獨有詞後來出現  -> silent_miss  （agent 需要卻沒去拿，最嚴重）
      兩者皆無                -> clean        （大概是正確的裁切）
    """

    def test_restored_wins_over_text_match(self):
        later = {"d1": "we later mention gone_b twice: gone_b"}
        rows = tr_eval.classify(DECISIONS, [{"handle": "d1.1"}], later)
        self.assertEqual(next(r for r in rows if r["handle"] == "d1.1")["state"], "restored")

    def test_silent_miss_needs_two_hits(self):
        later = {"d1": "gone_c appears once only"}
        rows = tr_eval.classify(DECISIONS, [], later)
        self.assertEqual(next(r for r in rows if r["handle"] == "d1.2")["state"], "clean")
        later = {"d1": "gone_c here and gone_c again"}
        rows = tr_eval.classify(DECISIONS, [], later)
        self.assertEqual(next(r for r in rows if r["handle"] == "d1.2")["state"], "silent_miss")

    def test_clean_when_nothing_matches(self):
        rows = tr_eval.classify(DECISIONS, [], {"d1": "unrelated text", "d2": ""})
        self.assertEqual(next(r for r in rows if r["handle"] == "d2.1")["state"], "clean")

    def test_only_dropped_chunks_are_classified(self):
        rows = tr_eval.classify(DECISIONS, [], {"d1": "", "d2": ""})
        self.assertEqual({r["handle"] for r in rows}, {"d1.1", "d1.2", "d2.1"})

    def test_summary_counts(self):
        rows = tr_eval.classify(DECISIONS, [{"handle": "d1.1"}],
                                {"d1": "gone_c and gone_c", "d2": ""})
        s = tr_eval.summarize(rows)
        self.assertEqual(s["restored"], 1)
        self.assertEqual(s["silent_miss"], 1)
        self.assertEqual(s["clean"], 1)
        self.assertAlmostEqual(s["silent_miss_rate"], 1 / 3)


class TestHitCountingRespectsTokenBoundaries(unittest.TestCase):
    """獨有詞比對如果是純子字串比對，`main` 會被 `remain`／`domain`／
    `maintenance` 巧合命中三次——silent_miss 是整個專案唯一在對抗的
    指標，灌水的巧合命中會把門檻往『什麼都不刪』的方向調，工具看起來
    還在跑、其實已經沒用（task-9 fix-round 1，coordinator review
    Important 1）。token 合法會帶 `_`、`-`、`.`、`/`（檔案路徑、識別字、
    錯誤字串常見），所以邊界不能用 `\\b`（只認字母數字／底線），要自己
    判斷『前後字元是不是也可能屬於同一個 token』。"""

    def test_coincidental_substring_inside_longer_words_scores_zero(self):
        self.assertEqual(
            tr_eval._count_token_occurrences(
                "main", "we remain in the domain of maintenance"),
            0)

    def test_path_like_token_with_dots_and_slash_counts_each_occurrence(self):
        text = "first saw it in src/main.py then again in src/main.py later"
        self.assertEqual(tr_eval._count_token_occurrences("src/main.py", text), 2)

    def test_token_at_very_start_and_very_end_both_count(self):
        text = "alpha in the middle somewhere ends with alpha"
        self.assertTrue(text.startswith("alpha") and text.endswith("alpha"))
        self.assertEqual(tr_eval._count_token_occurrences("alpha", text), 2)

    def test_token_followed_by_punctuation_not_part_of_it_counts(self):
        self.assertEqual(
            tr_eval._count_token_occurrences("main.py", "see main.py, then main.py)"),
            2)

    def test_classify_does_not_manufacture_silent_miss_from_coincidental_prose(self):
        # 端對端 before/after 案例：distinctive token 是 "main"，later text
        # 只有 remain／domain／maintenance 這種巧合子字串，子字串比對會數到
        # 3 次（>= MIN_HITS），但 token 邊界比對是 0 次——必須是 clean。
        decisions = [{"decision_id": "d9", "tool": "Bash",
                     "chunks": [{"i": 0, "chars": 10, "dropped": True,
                                "distinctive": ["main"]}]}]
        later = {"d9": "we remain in the domain of maintenance"}
        rows = tr_eval.classify(decisions, [], later)
        self.assertEqual(rows[0]["state"], "clean")

    def test_classify_still_detects_a_genuinely_repeated_token(self):
        # 對照組：同一個 token，這次是兩次真的獨立出現（前後都是空白邊界）
        # ——確保邊界判斷沒有矯枉過正到連真的複述都偵測不到。
        decisions = [{"decision_id": "d9", "tool": "Bash",
                     "chunks": [{"i": 0, "chars": 10, "dropped": True,
                                "distinctive": ["main"]}]}]
        later = {"d9": "check main again, still main here"}
        rows = tr_eval.classify(decisions, [], later)
        self.assertEqual(rows[0]["state"], "silent_miss")


class TestHitCountingTreatsCjkAsABoundary(unittest.TestCase):
    """中文不用空白斷詞——`修改main.py之後重跑` 是一句話裡包著 identifier
    `main.py`，不是一整個超長 token。舊版用 `ch.isalnum()` 判斷邊界，
    Python 的 isalnum() 對中文字一視同仁也回傳 True，於是緊貼 token 的
    中文字被誤判成『同一個 token 的延伸』，邊界檢查失敗、命中數少算。
    這個專案的 transcript 就是中文，所以這不是邊角案例，是常態；而且
    錯的方向是危險的：少算 silent_miss 會讓刪除看起來比實際安全（task-9
    fix-round 2，coordinator review）。這裡的字元類別直接引用
    descriptor.TOKEN_CHARS，跟 distinctive() 產生 token 用的是同一份
    定義，不會走鐘。"""

    def test_token_adjacent_to_cjk_with_space_counts(self):
        self.assertEqual(
            tr_eval._count_token_occurrences("main.py", "修改 main.py 之後重跑"), 1)

    def test_token_adjacent_to_cjk_without_space_counts(self):
        self.assertEqual(
            tr_eval._count_token_occurrences("main.py", "修改main.py之後重跑"), 1)

    def test_hyphenated_token_adjacent_to_cjk_without_space_counts(self):
        self.assertEqual(
            tr_eval._count_token_occurrences("JKO-33644", "這張票JKO-33644已經關了"), 1)

    def test_underscored_token_adjacent_to_cjk_without_space_counts(self):
        self.assertEqual(
            tr_eval._count_token_occurrences("uat_proxy", "設定uat_proxy的來源"), 1)

    def test_token_adjacent_to_fullwidth_comma_counts(self):
        self.assertEqual(
            tr_eval._count_token_occurrences("main.py", "main.py，之後"), 1)

    def test_token_wrapped_in_fullwidth_parentheses_counts(self):
        self.assertEqual(
            tr_eval._count_token_occurrences("main.py", "（main.py）"), 1)

    def test_coincidental_substring_inside_english_prose_still_scores_zero(self):
        # 回歸：修這個坑不能連原本就該擋掉的英文巧合子字串又放行回去。
        self.assertEqual(
            tr_eval._count_token_occurrences(
                "main", "we remain in the domain of maintenance"),
            0)

    def test_classify_detects_silent_miss_from_cjk_adjacent_reference(self):
        # 端對端：中文 transcript 裡緊貼中文字的 identifier 複述兩次，
        # 必須被判成 silent_miss，不是因為邊界誤判而變成 clean。
        decisions = [{"decision_id": "d10", "tool": "Bash",
                     "chunks": [{"i": 0, "chars": 10, "dropped": True,
                                "distinctive": ["uat_proxy"]}]}]
        later = {"d10": "設定uat_proxy的來源，之後又提到uat_proxy一次"}
        rows = tr_eval.classify(decisions, [], later)
        self.assertEqual(rows[0]["state"], "silent_miss")

    def test_token_char_class_matches_descriptor_token_chars(self):
        # 兩邊字元類別是同一份定義，不是各自維護一份一樣的字串——直接
        # 驗證 tr_eval 用來判斷邊界的 regex 是拿 descriptor.TOKEN_CHARS
        # 組出來的。
        import descriptor
        self.assertIn(descriptor.TOKEN_CHARS, tr_eval._TOKEN_CHAR_RE.pattern)


class TestBothViaValuesCountTheSame(unittest.TestCase):
    """restores.jsonl 的 via 只是『怎麼還原的』，不是兩種不同事件
    （task-9 correction 4）——tr-restore／direct-read 都要判成 restored，
    同一個 handle 被兩條路徑各記一次也只能算一次還原。"""

    def test_tr_restore_via_yields_restored(self):
        rows = tr_eval.classify(DECISIONS, [{"handle": "d1.1", "via": "tr-restore"}], {})
        self.assertEqual(next(r for r in rows if r["handle"] == "d1.1")["state"], "restored")

    def test_direct_read_via_yields_restored(self):
        rows = tr_eval.classify(
            DECISIONS, [{"handle": "d1.2", "via": "direct-read", "tool": "Bash"}], {})
        self.assertEqual(next(r for r in rows if r["handle"] == "d1.2")["state"], "restored")

    def test_same_handle_restored_via_both_routes_counts_once(self):
        restores = [{"handle": "d1.1", "via": "tr-restore"},
                    {"handle": "d1.1", "via": "direct-read", "tool": "Bash"}]
        rows = tr_eval.classify(DECISIONS, restores, {})
        restored_rows = [r for r in rows if r["handle"] == "d1.1"]
        self.assertEqual(len(restored_rows), 1)
        self.assertEqual(restored_rows[0]["state"], "restored")
        self.assertEqual(tr_eval.summarize(rows)["restored"], 1)


class TestClassifyToleratesMalformedRecords(unittest.TestCase):
    """decisions.jsonl／restores.jsonl 是同一批 store._append 盡力而為寫出來
    的檔案，跟 tr-stats.rollup() 面對的是同一種半寫壞風險——classify() 收到
    形狀不對的紀錄要退化成『這筆不算』並計進 skip_counter，不是丟例外。"""

    def test_decision_missing_chunks_key_is_skipped_not_crashed(self):
        rows = tr_eval.classify([{"decision_id": "x1", "tool": "Bash"}], [], {})
        self.assertEqual(rows, [])

    def test_decision_record_that_is_a_string_is_skipped(self):
        rows = tr_eval.classify(["oops"] + DECISIONS, [], {"d1": "", "d2": ""})
        self.assertEqual({r["handle"] for r in rows}, {"d1.1", "d1.2", "d2.1"})

    def test_chunks_not_a_list_is_skipped(self):
        decisions = [{"decision_id": "x1", "tool": "Bash", "chunks": "nope"}]
        rows = tr_eval.classify(decisions, [], {})
        self.assertEqual(rows, [])

    def test_restore_record_missing_handle_does_not_crash(self):
        rows = tr_eval.classify(DECISIONS, [{"via": "tr-restore"}, 42], {"d1": "", "d2": ""})
        self.assertEqual({r["handle"] for r in rows}, {"d1.1", "d1.2", "d2.1"})
        self.assertTrue(all(r["state"] != "restored" for r in rows))

    def test_skip_counter_accumulates_across_decisions_and_restores(self):
        decisions = ["oops", {"decision_id": "d1", "tool": "Bash", "chunks": "nope"}]
        counter = [0]
        tr_eval.classify(decisions, [None, 42], {}, skip_counter=counter)
        self.assertEqual(counter[0], 4)  # "oops" + chunks 型別不對 + None + 42

    def test_empty_store_does_not_crash(self):
        self.assertEqual(tr_eval.classify([], [], {}), [])
        self.assertEqual(tr_eval.summarize([])["total"], 0)
        self.assertEqual(tr_eval.summarize([])["silent_miss_rate"], 0)


class TestReadJsonlSharedWithStats(unittest.TestCase):
    """read_jsonl 搬進 jsonl_io.py 共用（task-9 correction 3）：tr-eval 跟
    tr-stats 讀的是同一批可能半寫壞的封存檔案，容錯規則跟略過計數的契約
    只能有一份實作，不是兩支各自維護、容易漂移。"""

    def test_read_jsonl_is_the_shared_implementation(self):
        import jsonl_io
        self.assertIs(tr_eval.read_jsonl, jsonl_io.read_jsonl)
        self.assertIs(stats.read_jsonl, jsonl_io.read_jsonl)

    def test_behaves_identically_to_stats_read_jsonl(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "mixed.jsonl")
            with open(p, "w", encoding="utf-8") as fh:
                fh.write("not even json{\n")
                fh.write('"a string"\n')
                fh.write(json.dumps({"decision_id": "d1"}) + "\n")
            c1, c2 = [0], [0]
            out1 = tr_eval.read_jsonl(p, c1)
            out2 = stats.read_jsonl(p, c2)
            self.assertEqual(out1, out2)
            self.assertEqual(c1, c2)

    def test_missing_file_returns_empty_list(self):
        self.assertEqual(tr_eval.read_jsonl("/no/such/archive/decisions.jsonl"), [])


def _iso(ms):
    from datetime import datetime, timezone
    return (datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
            .isoformat(timespec="milliseconds").replace("+00:00", "Z"))


def _write_transcript(root, project, session_id, rows):
    d = os.path.join(root, project)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{session_id}.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


class TestTranscriptAfter(unittest.TestCase):
    """transcript_after 要用 decision 的 ts_ms 當邊界，只收晚於它的訊息——
    不是整份檔案、也不是檔案最後 N 行。比對整份檔案（含 decision 之前，
    尤其是這次工具呼叫剛印出來、原文就在裡面的那一輪）會讓幾乎每個墓碑
    都被判成 silent_miss（task-9 傳送的『Traps』一節指出的坑）。"""

    def test_only_includes_messages_strictly_after_decision_ts(self):
        T = 1_700_000_000_000
        with tempfile.TemporaryDirectory() as root:
            _write_transcript(root, "proj1", "sess-a", [
                {"type": "user", "timestamp": _iso(T - 5000),
                 "message": {"content": [{"type": "text", "text": "BEFORE_TOKEN"}]}},
                {"type": "assistant", "timestamp": _iso(T + 5000),
                 "message": {"content": [{"type": "text", "text": "AFTER_TOKEN"}]}},
            ])
            by_id = {"d1": {"session_id": "sess-a", "ts_ms": T}}
            text = tr_eval.transcript_after("d1", by_id, transcript_dir=root)
        self.assertIn("AFTER_TOKEN", text)
        self.assertNotIn("BEFORE_TOKEN", text)

    def test_message_exactly_at_decision_ts_is_not_later(self):
        T = 1_700_000_000_000
        with tempfile.TemporaryDirectory() as root:
            _write_transcript(root, "proj1", "sess-a", [
                {"type": "user", "timestamp": _iso(T),
                 "message": {"content": [{"type": "text", "text": "EXACT_TOKEN"}]}},
            ])
            by_id = {"d1": {"session_id": "sess-a", "ts_ms": T}}
            text = tr_eval.transcript_after("d1", by_id, transcript_dir=root)
        self.assertNotIn("EXACT_TOKEN", text)

    def test_non_user_assistant_rows_are_excluded_even_if_later(self):
        T = 1_700_000_000_000
        with tempfile.TemporaryDirectory() as root:
            _write_transcript(root, "proj1", "sess-a", [
                {"type": "system", "timestamp": _iso(T + 5000),
                 "message": {"content": [{"type": "text", "text": "SYSTEM_TOKEN"}]}},
            ])
            by_id = {"d1": {"session_id": "sess-a", "ts_ms": T}}
            text = tr_eval.transcript_after("d1", by_id, transcript_dir=root)
        self.assertNotIn("SYSTEM_TOKEN", text)

    def test_matches_real_project_subdirectory_layout(self):
        # ~/.claude/projects/<project-dir>/<session-id>.jsonl —— glob 要
        # 對得上實際佈局（root/*/session.jsonl），不是 root/session.jsonl。
        T = 1_700_000_000_000
        with tempfile.TemporaryDirectory() as root:
            _write_transcript(root, "-Users-someone-Code-devbox", "sess-b", [
                {"type": "assistant", "timestamp": _iso(T + 1000),
                 "message": {"content": [{"type": "text", "text": "LAYOUT_TOKEN"}]}},
            ])
            by_id = {"d1": {"session_id": "sess-b", "ts_ms": T}}
            text = tr_eval.transcript_after("d1", by_id, transcript_dir=root)
        self.assertIn("LAYOUT_TOKEN", text)

    def test_missing_ts_ms_returns_empty_not_whole_file(self):
        # 沒有 ts_ms 就沒有邊界可畫——安全的預設是『沒有後來』，不是
        # 『整份都算後來』（否則工具輸出原文本身就會被誤判成後來的引用）。
        with tempfile.TemporaryDirectory() as root:
            _write_transcript(root, "proj1", "sess-c", [
                {"type": "user", "timestamp": _iso(1_700_000_000_000),
                 "message": {"content": [{"type": "text", "text": "ANY_TOKEN"}]}},
            ])
            by_id = {"d1": {"session_id": "sess-c"}}
            text = tr_eval.transcript_after("d1", by_id, transcript_dir=root)
        self.assertEqual(text, "")

    def test_unknown_decision_id_returns_empty(self):
        self.assertEqual(tr_eval.transcript_after("nope", {}, transcript_dir="/tmp"), "")

    def test_missing_session_id_returns_empty(self):
        by_id = {"d1": {"ts_ms": 1_700_000_000_000}}
        self.assertEqual(tr_eval.transcript_after("d1", by_id, transcript_dir="/tmp"), "")


class TestTranscriptAfterTimezoneHandling(unittest.TestCase):
    """真實 transcript 一律帶 `Z`，但 transcript_after 讀的是別人寫的檔案，
    不能假設每一行都乖乖照這個格式來——沒有時區資訊的 timestamp（naive）
    要當成不可解析而排除，不是靠 datetime.timestamp() 偷偷假設成『執行
    這支工具的機器所在時區』。這種錯不會拋例外，之前的 except Exception
    擋不住，是一個看起來正常、其實方向隨執行環境改變的數字（task-9
    fix-round 1，coordinator review Important 2）。"""

    def test_naive_timestamp_is_excluded_not_shifted(self):
        T = 1_700_000_000_000
        with tempfile.TemporaryDirectory() as root:
            # _iso() 回傳的字串固定以 "Z" 結尾；去掉它就變成沒有時區資訊
            # 的 naive timestamp——數字上仍然落在 ts_ms 之後，但因為沒有
            # 時區可判斷「之後」是相對哪個時區，必須整筆排除。
            naive_ts = _iso(T + 5000)[:-1]
            self.assertFalse(naive_ts.endswith("Z"))
            _write_transcript(root, "proj1", "sess-naive", [
                {"type": "user", "timestamp": naive_ts,
                 "message": {"content": [{"type": "text", "text": "NAIVE_TOKEN"}]}},
            ])
            by_id = {"d1": {"session_id": "sess-naive", "ts_ms": T}}
            text = tr_eval.transcript_after("d1", by_id, transcript_dir=root)
        self.assertNotIn("NAIVE_TOKEN", text)

    def test_explicit_non_utc_offset_is_converted_not_dropped(self):
        from datetime import datetime, timezone, timedelta
        T = 1_700_000_000_000
        # T + 5000ms in UTC，改用明確的 +08:00 位移表示（不是 Z）——必須
        # 正確換算成同一個 UTC 時間點、被認出「在 ts_ms 之後」，不能因為
        # 它不是 Z 結尾就被當成不可解析而丟掉。
        dt_utc = datetime.fromtimestamp((T + 5000) / 1000.0, tz=timezone.utc)
        offset_ts = dt_utc.astimezone(timezone(timedelta(hours=8))) \
                          .isoformat(timespec="milliseconds")
        self.assertTrue(offset_ts.endswith("+08:00"))
        with tempfile.TemporaryDirectory() as root:
            _write_transcript(root, "proj1", "sess-offset", [
                {"type": "user", "timestamp": offset_ts,
                 "message": {"content": [{"type": "text", "text": "OFFSET_TOKEN"}]}},
            ])
            by_id = {"d1": {"session_id": "sess-offset", "ts_ms": T}}
            text = tr_eval.transcript_after("d1", by_id, transcript_dir=root)
        self.assertIn("OFFSET_TOKEN", text)

    def test_row_ts_ms_rejects_naive_string_directly(self):
        self.assertIsNone(tr_eval._row_ts_ms("2026-09-21T04:32:27.142"))

    def test_row_ts_ms_converts_non_utc_offset_to_the_same_instant_as_z(self):
        # 2026-09-21T12:32:27+08:00 跟 2026-09-21T04:32:27Z 是同一個瞬間。
        ms_offset = tr_eval._row_ts_ms("2026-09-21T12:32:27+08:00")
        ms_utc = tr_eval._row_ts_ms("2026-09-21T04:32:27Z")
        self.assertIsNotNone(ms_offset)
        self.assertIsNotNone(ms_utc)
        self.assertAlmostEqual(ms_offset, ms_utc, delta=1)


class TestBuildBatchDeterminism(unittest.TestCase):
    """control 對照組用 handle 的 sha256 決定要不要收，不是 Python 內建
    hash()（受 PYTHONHASHSEED 影響、同一支程式兩次啟動可能不同）——重跑、
    換行程、換輸入順序都要挑到同一批（task-9 傳送的『Traps』一節）。"""

    def _control_decisions(self, n, decision_id="cd1"):
        chunks = [{"i": i, "chars": 10, "dropped": False, "distinctive": []}
                  for i in range(n)]
        return [{"decision_id": decision_id, "tool": "Bash", "chunks": chunks}]

    def _expected_handles(self, decisions):
        expected = set()
        for d in decisions:
            for c in d["chunks"]:
                handle = f"{d['decision_id']}.{c['i']}"
                if not c["dropped"]:
                    h = int(hashlib.sha256(handle.encode()).hexdigest()[:8], 16)
                    if (h % 1000) / 1000.0 >= tr_eval.CONTROL_RATE:
                        continue
                expected.add(handle)
        return expected

    def test_selection_matches_independent_hash_computation(self):
        decisions = self._control_decisions(500)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "batch.jsonl")
            tr_eval.build_batch(decisions, [], out)
            with open(out, encoding="utf-8") as fh:
                got = {json.loads(l)["handle"] for l in fh}
        self.assertEqual(got, self._expected_handles(decisions))
        self.assertTrue(got)  # 500 個裡抽 10% 不該抽到空集合

    def test_two_runs_in_same_process_pick_identical_set(self):
        decisions = self._control_decisions(300)
        with tempfile.TemporaryDirectory() as d:
            out1, out2 = os.path.join(d, "b1.jsonl"), os.path.join(d, "b2.jsonl")
            tr_eval.build_batch(decisions, [], out1)
            tr_eval.build_batch(decisions, [], out2)
            with open(out1, encoding="utf-8") as fh:
                got1 = {json.loads(l)["handle"] for l in fh}
            with open(out2, encoding="utf-8") as fh:
                got2 = {json.loads(l)["handle"] for l in fh}
        self.assertEqual(got1, got2)

    def test_independent_of_chunk_ordering(self):
        decisions = self._control_decisions(200)
        shuffled = [dict(decisions[0], chunks=list(reversed(decisions[0]["chunks"])))]
        with tempfile.TemporaryDirectory() as d:
            out1, out2 = os.path.join(d, "a.jsonl"), os.path.join(d, "b.jsonl")
            tr_eval.build_batch(decisions, [], out1)
            tr_eval.build_batch(shuffled, [], out2)
            with open(out1, encoding="utf-8") as fh:
                got1 = {json.loads(l)["handle"] for l in fh}
            with open(out2, encoding="utf-8") as fh:
                got2 = {json.loads(l)["handle"] for l in fh}
        self.assertEqual(got1, got2)

    def test_deterministic_across_fresh_processes_with_different_hash_seeds(self):
        # 反向證明沒有任何地方偷偷用了內建 hash()：PYTHONHASHSEED 兩個行程
        # 給不同值，選出來的對照組集合必須完全一樣。
        decisions = self._control_decisions(200)
        with tempfile.TemporaryDirectory() as d:
            fixture = os.path.join(d, "decisions.json")
            with open(fixture, "w", encoding="utf-8") as fh:
                json.dump(decisions, fh)
            script = (
                "import json, sys, importlib.util\n"
                f"sys.path.insert(0, {TR!r})\n"
                f"spec = importlib.util.spec_from_file_location('tr_eval', {EVAL_PATH!r})\n"
                "m = importlib.util.module_from_spec(spec)\n"
                "spec.loader.exec_module(m)\n"
                f"decisions = json.load(open({fixture!r}, encoding='utf-8'))\n"
                "m.build_batch(decisions, [], sys.argv[1])\n"
            )
            outs = []
            for seed in ("111", "222"):
                out = os.path.join(d, f"p-{seed}.jsonl")
                env = dict(os.environ, PYTHONHASHSEED=seed)
                r = subprocess.run([sys.executable, "-c", script, out],
                                   capture_output=True, text=True, env=env)
                self.assertEqual(r.returncode, 0, r.stderr)
                outs.append(out)
            handles = []
            for out in outs:
                with open(out, encoding="utf-8") as fh:
                    handles.append({json.loads(l)["handle"] for l in fh})
        self.assertEqual(handles[0], handles[1])

    def test_dropped_chunks_are_always_included_bypassing_the_hash(self):
        chunks = [{"i": i, "chars": 10, "dropped": True, "distinctive": []} for i in range(20)]
        decisions = [{"decision_id": "dd1", "tool": "Bash", "chunks": chunks}]
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "batch.jsonl")
            n = tr_eval.build_batch(decisions, [], out)
        self.assertEqual(n, 20)

    def test_batch_items_carry_no_state_or_score_fields(self):
        # 給 Layer 2 judge 的批次要拿掉『Layer 1 已經判過什麼』，不然標註
        # 只是在複述 classify() 的結論，不是獨立判斷。
        decisions = DECISIONS
        rows = tr_eval.classify(decisions, [], {"d1": "", "d2": ""})
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "batch.jsonl")
            tr_eval.build_batch(decisions, rows, out)
            with open(out, encoding="utf-8") as fh:
                items = [json.loads(l) for l in fh]
        for it in items:
            self.assertEqual(set(it.keys()), {"handle", "tool", "chars", "control"})

    def test_malformed_decision_in_batch_input_does_not_crash(self):
        decisions = ["oops", {"decision_id": "x1", "tool": "Bash", "chunks": "nope"}]
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "batch.jsonl")
            n = tr_eval.build_batch(decisions, [], out)
        self.assertEqual(n, 0)


class TestEvalStoreRootResolvedFreshEachCall(unittest.TestCase):
    """main() 走 store.root()，且每次執行都重新解析，不能在模組載入當下
    凍結成常數——這正是本專案先前真的撞過的 bug 形狀（task-9 correction 2）。
    這裡不 mock，直接讓兩次呼叫在同一個 process 裡分別指向兩個不同的暫存
    目錄，反向證明沒有任何地方把根目錄快取住。

    命名刻意跟前面 tr-stats 那個同名測試類別（TestStoreRootResolvedFreshEachCall）
    區分開——兩個類別原本撞名，Python 對同一個模組裡重複定義的類別名稱
    直接靜默覆寫，後定義的整個蓋掉先定義的，先定義那個的測試方法從此
    再也不會被 unittest 收集到、也不會有任何錯誤或警告訊息。這是 fix-round 1
    自我複查時另外抓到的（不是 coordinator 這輪點名的兩個問題），順手一併
    修掉，見 task-9-report.md。"""

    def test_module_level_constant_is_not_frozen_at_import(self):
        self.assertFalse(hasattr(tr_eval, "HOME"),
                          "store root must not be frozen into a module-level "
                          "constant computed at import time")

    def test_two_calls_in_one_process_see_two_different_roots(self):
        root_a, root_b = tempfile.mkdtemp(), tempfile.mkdtemp()
        st_a = store.Store("sess-a", root=root_a)
        st_a.record_decision({"decision_id": "a1", "tool": "Bash",
                              "chars_before": 100,
                              "chunks": [{"i": 0, "chars": 10, "dropped": True,
                                         "distinctive": []}]})

        def _run(home):
            buf = io.StringIO()
            env = {"TOOL_REDUCE_HOME": home,
                   "TOOL_REDUCE_TRANSCRIPT_DIR": tempfile.mkdtemp()}
            with mock.patch.dict(os.environ, env), \
                 mock.patch.object(sys, "argv", ["tr-eval.py"]), \
                 contextlib.redirect_stdout(buf):
                rc = tr_eval.main()
            self.assertEqual(rc, 0)
            return buf.getvalue()

        out_a = _run(root_a)
        out_b = _run(root_b)
        self.assertIn("墓碑 1 個", out_a)
        self.assertIn("墓碑 0 個", out_b)


class TestEvalFreshOrAbsentStoreDoesNotCrash(unittest.TestCase):
    """全新安裝、還沒發生過任何一次 reduce 的環境——連存放區根目錄都不
    存在——tr-eval 必須印出全 0，不是 traceback（task-9 global constraint）。
    走 subprocess 驗證連 main() 之外、argparse／print 那段實際印出來的東西
    也一起驗證到。命名跟 tr-stats 那個同名類別區分開，理由見
    TestEvalStoreRootResolvedFreshEachCall 的說明。"""

    def _run(self, home, extra_args=(), transcript_dir=None):
        env = dict(os.environ, TOOL_REDUCE_HOME=home,
                   TOOL_REDUCE_TRANSCRIPT_DIR=transcript_dir or tempfile.mkdtemp())
        return subprocess.run([sys.executable, EVAL_PATH, *extra_args],
                              capture_output=True, text=True, env=env)

    def test_missing_store_root_prints_zeros_not_a_traceback(self):
        home = os.path.join(tempfile.mkdtemp(), "does-not-exist-yet")
        r = self._run(home)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertNotIn("Traceback", r.stdout)
        self.assertIn("墓碑 0 個", r.stdout)

    def test_empty_archive_dir_prints_zeros(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        r = self._run(home)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("墓碑 0 個", r.stdout)

    def test_batch_flag_with_empty_store_writes_empty_file(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        out = os.path.join(tempfile.mkdtemp(), "batch.jsonl")
        r = self._run(home, extra_args=("--batch", out))
        self.assertEqual(r.returncode, 0)
        self.assertTrue(os.path.exists(out))
        self.assertEqual(open(out, encoding="utf-8").read(), "")


class TestRecordsSkippedSurfacedByCli(unittest.TestCase):
    """一份被截斷的封存區（store._append 盡力而為設計下的正常結果）算出來
    的三態分佈要帶著『有東西被略過』的信號，不是看起來一樣自信的 0
    （task-9 correction 3：inherit tr-stats 的略過計數契約）。"""

    def test_truncated_archive_is_reported_not_silently_dropped(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        with open(os.path.join(home, "archive", "decisions.jsonl"), "w",
                 encoding="utf-8") as fh:
            fh.write("truncated garbage not json{\n")
            fh.write(json.dumps({"decision_id": "d1", "session_id": "s1", "tool": "Bash",
                                "chars_before": 100,
                                "chunks": [{"i": 0, "chars": 10, "dropped": True,
                                           "distinctive": []}]}) + "\n")
        env = dict(os.environ, TOOL_REDUCE_HOME=home,
                   TOOL_REDUCE_TRANSCRIPT_DIR=tempfile.mkdtemp())
        r = subprocess.run([sys.executable, EVAL_PATH], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertIn("1 筆紀錄格式不對", r.stdout)
        self.assertIn("墓碑 1 個", r.stdout)

    def test_clean_archive_prints_nothing_extra(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        with open(os.path.join(home, "archive", "decisions.jsonl"), "w",
                 encoding="utf-8") as fh:
            fh.write(json.dumps({"decision_id": "d1", "session_id": "s1", "tool": "Bash",
                                "chars_before": 100, "chunks": []}) + "\n")
        env = dict(os.environ, TOOL_REDUCE_HOME=home,
                   TOOL_REDUCE_TRANSCRIPT_DIR=tempfile.mkdtemp())
        r = subprocess.run([sys.executable, EVAL_PATH], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("略過", r.stdout)


class TestMainEndToEnd(unittest.TestCase):
    """main() 的接線：restores.jsonl 真的會影響印出來的還原率、--batch
    真的會寫出可讀的檔案，不只是單元層級的 classify()／build_batch() 本身
    正確。"""

    def test_restore_record_flows_through_main(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        with open(os.path.join(home, "archive", "decisions.jsonl"), "w",
                 encoding="utf-8") as fh:
            fh.write(json.dumps({"decision_id": "d1", "session_id": "s1", "tool": "Bash",
                                "chars_before": 100,
                                "chunks": [{"i": 0, "chars": 10, "dropped": True,
                                           "distinctive": ["only_once"]}]}) + "\n")
        with open(os.path.join(home, "archive", "restores.jsonl"), "w",
                 encoding="utf-8") as fh:
            fh.write(json.dumps({"handle": "d1.0", "via": "direct-read",
                                "tool": "Bash"}) + "\n")
        env = dict(os.environ, TOOL_REDUCE_HOME=home,
                   TOOL_REDUCE_TRANSCRIPT_DIR=tempfile.mkdtemp())
        r = subprocess.run([sys.executable, EVAL_PATH], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("墓碑 1 個", r.stdout)
        self.assertIn("100.0%", r.stdout)  # 唯一一個墓碑被還原，還原率 100%

    def test_batch_flag_writes_file_and_reports_count(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        with open(os.path.join(home, "archive", "decisions.jsonl"), "w",
                 encoding="utf-8") as fh:
            fh.write(json.dumps({"decision_id": "d1", "session_id": "s1", "tool": "Bash",
                                "chars_before": 100,
                                "chunks": [{"i": 0, "chars": 10, "dropped": True,
                                           "distinctive": []},
                                          {"i": 1, "chars": 10, "dropped": False,
                                           "distinctive": []}]}) + "\n")
        out = os.path.join(tempfile.mkdtemp(), "batch.jsonl")
        env = dict(os.environ, TOOL_REDUCE_HOME=home,
                   TOOL_REDUCE_TRANSCRIPT_DIR=tempfile.mkdtemp())
        r = subprocess.run([sys.executable, EVAL_PATH, "--batch", out],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0)
        with open(out, encoding="utf-8") as fh:
            lines = [json.loads(l) for l in fh]
        # 唯一一個被刪的段落 (d1.0) 一定在；唯一一個對照組候選 (d1.1) 依
        # sha256("d1.1") 算出來的分位數是 0.236，落在 10% 抽樣門檻之外。
        self.assertEqual({l["handle"] for l in lines}, {"d1.0"})
        self.assertIn("1 筆", r.stdout)


# ---------------------------------------------------------------------------
# task-10: tr-tune, 門檻重放與調校
# ---------------------------------------------------------------------------

tr_tune = load("tr_tune", "executable_tr-tune.py")

TUNE_PATH = os.path.join(TR, "executable_tr-tune.py")

SCORED = [
    {"decision_id": "s1", "tool": "Bash", "chars_before": 4000, "ts_ms": 1,
     "chunks": [
        {"i": 0, "chars": 1000, "dropped": False, "distinctive": [], "scores": {"noise": 0.9, "uniq": 0.1}},
        {"i": 1, "chars": 1000, "dropped": True,  "distinctive": ["x1"], "scores": {"noise": 0.9, "uniq": 0.1}},
        {"i": 2, "chars": 1000, "dropped": False, "distinctive": ["x2"], "scores": {"noise": 0.55, "uniq": 0.2}},
        {"i": 3, "chars": 1000, "dropped": False, "distinctive": [], "scores": {"noise": 0.9, "uniq": 0.1}}]},
]


class TestReplay(unittest.TestCase):
    def test_position_floor_survives_replay(self):
        """重放要走同一份 drop_policy.decide，頭尾規則不能在離線消失。"""
        r = tr_tune.replay(SCORED, {"noise_min": 0.5, "uniq_max": 0.9,
                                    "min_chunks": 3, "max_drop_ratio": 0.6})
        self.assertEqual(r["dropped"], 2)          # 只有 i=1、i=2，頭尾不動
        self.assertEqual(r["saved"], 2000)

    def test_higher_threshold_saves_less(self):
        lo = tr_tune.replay(SCORED, {"noise_min": 0.5, "uniq_max": 0.9,
                                     "min_chunks": 3, "max_drop_ratio": 0.6})
        hi = tr_tune.replay(SCORED, {"noise_min": 0.95, "uniq_max": 0.9,
                                     "min_chunks": 3, "max_drop_ratio": 0.6})
        self.assertLess(hi["saved"], lo["saved"])


class TestSearchSafety(unittest.TestCase):
    def test_rejects_candidates_worse_than_baseline(self):
        """先鎖死危險的錯誤：沉默誤刪率不得高於現行，才在子集合裡比節省。"""
        cands = tr_tune.search(SCORED, baseline_silent_miss=0.0,
                               later_text={"s1": "x2 and x2 again"})
        self.assertTrue(all(c["silent_miss_rate"] <= 0.0 for c in cands))

    def test_sorted_by_saving_within_safe_set(self):
        cands = tr_tune.search(SCORED, baseline_silent_miss=1.0, later_text={"s1": ""})
        self.assertTrue(cands)
        saves = [c["saved"] for c in cands]
        self.assertEqual(saves, sorted(saves, reverse=True))

    def test_refuses_without_human_baseline(self):
        with self.assertRaises(tr_tune.BaselineTooThin):
            tr_tune.check_baseline({"labelled": 3, "agreement": 0.9, "new_since": 0})
        with self.assertRaises(tr_tune.BaselineTooThin):
            tr_tune.check_baseline({"labelled": 50, "agreement": 0.4, "new_since": 0})
        with self.assertRaises(tr_tune.BaselineTooThin):
            tr_tune.check_baseline({"labelled": 50, "agreement": 0.9, "new_since": 900})
        tr_tune.check_baseline({"labelled": 50, "agreement": 0.9, "new_since": 10})


class TestSearchGridWithNoQualifyingCandidateIsEmpty(unittest.TestCase):
    """網格裡每個組合都超標時，search() 要老實回傳空清單，不是硬湊一個
    「反正分數最低」的候選出來——呼叫端（main()）靠這個空清單決定要不要
    寫檔，回傳非空清單等於製造一個假的安全候選。"""

    def test_impossible_ceiling_yields_no_candidates(self):
        cands = tr_tune.search(SCORED, baseline_silent_miss=-1.0,
                               later_text={"s1": "x1 and x1 again"})
        self.assertEqual(cands, [])

    def test_explicit_grid_with_only_unsafe_entries_is_empty(self):
        grid = [{"noise_min": 0.5, "uniq_max": 0.9, "min_chunks": 3, "max_drop_ratio": 0.6}]
        cands = tr_tune.search(SCORED, baseline_silent_miss=0.0,
                               later_text={"s1": "x1 and x1 again"}, grid=grid)
        self.assertEqual(cands, [])


class TestReplayTeleratesMalformedRecords(unittest.TestCase):
    """decisions.jsonl 是 store._append 盡力而為寫出來的檔案，跟 tr-eval／
    tr-stats 面對的是同一種半寫壞風險——重放遇到形狀不對的紀錄要跳過，
    不能讓一筆壞紀錄中斷整批重算。"""

    def test_missing_chunks_key_does_not_crash(self):
        r = tr_tune.replay([{"decision_id": "x1", "tool": "Bash"}],
                           {"noise_min": 0.5, "uniq_max": 0.9,
                            "min_chunks": 3, "max_drop_ratio": 0.6})
        self.assertEqual(r, {"saved": 0, "dropped": 0})

    def test_chunks_not_a_list_does_not_crash(self):
        r = tr_tune.replay([{"decision_id": "x1", "tool": "Bash", "chunks": "nope"}],
                           {"noise_min": 0.5, "uniq_max": 0.9,
                            "min_chunks": 3, "max_drop_ratio": 0.6})
        self.assertEqual(r, {"saved": 0, "dropped": 0})

    def test_non_dict_decision_is_skipped(self):
        r = tr_tune.replay(["oops"] + SCORED,
                           {"noise_min": 0.5, "uniq_max": 0.9,
                            "min_chunks": 3, "max_drop_ratio": 0.6})
        self.assertEqual(r, {"saved": 2000, "dropped": 2})


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


class TestTuneMainEndToEnd(unittest.TestCase):
    """search()／check_baseline() 的單元測試證明了規則本身正確；這裡走
    subprocess 執行 main()，驗證兩道閘門真的接在一起：沒有 --apply 什麼都
    不寫、有 --apply 但基準不合格會拒絕並回傳非零、基準合格但候選是空集合
    也不寫、基準合格且有候選才寫檔。"""

    def _run(self, home, thresholds_path, extra_args=(), transcript_dir=None):
        env = dict(os.environ, TOOL_REDUCE_HOME=home,
                   TOOL_REDUCE_THRESHOLDS=thresholds_path,
                   TOOL_REDUCE_TRANSCRIPT_DIR=transcript_dir or tempfile.mkdtemp())
        return subprocess.run([sys.executable, TUNE_PATH, *extra_args],
                              capture_output=True, text=True, env=env)

    def test_missing_store_root_does_not_crash(self):
        home = os.path.join(tempfile.mkdtemp(), "does-not-exist-yet")
        thresholds = os.path.join(tempfile.mkdtemp(), "thresholds.json")
        r = self._run(home, thresholds)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse(os.path.exists(thresholds))

    def test_without_apply_writes_nothing_even_with_valid_baseline(self):
        home = tempfile.mkdtemp()
        archive = os.path.join(home, "archive")
        os.makedirs(archive, exist_ok=True)
        _write_jsonl(os.path.join(archive, "decisions.jsonl"), SCORED)
        with open(os.path.join(archive, "human_baseline.json"), "w", encoding="utf-8") as fh:
            json.dump({"labelled": 50, "agreement": 0.9, "new_since": 10}, fh)
        thresholds = os.path.join(tempfile.mkdtemp(), "thresholds.json")
        r = self._run(home, thresholds)
        self.assertEqual(r.returncode, 0)
        self.assertIn("只是列出候選", r.stdout)
        self.assertFalse(os.path.exists(thresholds))

    def test_apply_without_baseline_file_refuses_and_writes_nothing(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        thresholds = os.path.join(tempfile.mkdtemp(), "thresholds.json")
        r = self._run(home, thresholds, extra_args=("--apply",))
        self.assertEqual(r.returncode, 1)
        self.assertIn("拒絕套用", r.stdout)
        self.assertIn("人工基準只有 0 筆", r.stdout)
        self.assertFalse(os.path.exists(thresholds))

    def test_apply_with_thin_baseline_refuses_with_reason(self):
        home = tempfile.mkdtemp()
        archive = os.path.join(home, "archive")
        os.makedirs(archive, exist_ok=True)
        with open(os.path.join(archive, "human_baseline.json"), "w", encoding="utf-8") as fh:
            json.dump({"labelled": 50, "agreement": 0.4, "new_since": 0}, fh)
        thresholds = os.path.join(tempfile.mkdtemp(), "thresholds.json")
        r = self._run(home, thresholds, extra_args=("--apply",))
        self.assertEqual(r.returncode, 1)
        self.assertIn("拒絕套用", r.stdout)
        self.assertIn("一致率", r.stdout)
        self.assertFalse(os.path.exists(thresholds))

    def test_apply_with_no_qualifying_candidate_leaves_thresholds_untouched(self):
        # 中間段 i=1 在任何網格組合下都會被刪（noise=1.0、uniq=0.0 蓋過整
        # 個網格範圍），而且它的獨有詞在 later transcript 裡出現兩次——
        # 每個候選的沉默誤刪率都會 > 0，現行（production）紀錄裡這段卻沒被
        # 刪過（dropped=False），現行沉默誤刪率是 0，於是沒有任何候選能
        # 通過「不得高於現行」的篩選。
        home = tempfile.mkdtemp()
        archive = os.path.join(home, "archive")
        os.makedirs(archive, exist_ok=True)
        decision = {"decision_id": "e1", "session_id": "sess-e1", "tool": "Bash",
                    "chars_before": 300, "ts_ms": 1_700_000_000_000,
                    "chunks": [
                        {"i": 0, "chars": 100, "dropped": False, "distinctive": [],
                         "scores": {"noise": 0.1, "uniq": 0.9}},
                        {"i": 1, "chars": 100, "dropped": False, "distinctive": ["kaboom"],
                         "scores": {"noise": 1.0, "uniq": 0.0}},
                        {"i": 2, "chars": 100, "dropped": False, "distinctive": [],
                         "scores": {"noise": 0.1, "uniq": 0.9}}]}
        _write_jsonl(os.path.join(archive, "decisions.jsonl"), [decision])
        with open(os.path.join(archive, "human_baseline.json"), "w", encoding="utf-8") as fh:
            json.dump({"labelled": 50, "agreement": 0.9, "new_since": 10}, fh)

        transcript_dir = tempfile.mkdtemp()
        _write_transcript(transcript_dir, "proj1", "sess-e1", [
            {"type": "assistant", "timestamp": _iso(1_700_000_000_000 + 1000),
             "message": {"content": [{"type": "text",
                                      "text": "kaboom appears here and again kaboom"}]}}])

        thresholds = os.path.join(tempfile.mkdtemp(), "thresholds.json")
        r = self._run(home, thresholds, extra_args=("--apply",), transcript_dir=transcript_dir)
        self.assertEqual(r.returncode, 0)
        self.assertIn("沒有合格的候選", r.stdout)
        self.assertFalse(os.path.exists(thresholds))

    def test_apply_with_qualifying_candidate_writes_thresholds(self):
        home = tempfile.mkdtemp()
        archive = os.path.join(home, "archive")
        os.makedirs(archive, exist_ok=True)
        decision = {"decision_id": "g1", "session_id": "sess-g1", "tool": "Bash",
                    "chars_before": 1100, "ts_ms": 1_700_000_000_000,
                    "chunks": [
                        {"i": 0, "chars": 50, "dropped": False, "distinctive": [],
                         "scores": {"noise": 0.1, "uniq": 0.9}},
                        {"i": 1, "chars": 500, "dropped": True, "distinctive": ["safe1"],
                         "scores": {"noise": 0.9, "uniq": 0.05}},
                        {"i": 2, "chars": 500, "dropped": True, "distinctive": ["safe2"],
                         "scores": {"noise": 0.85, "uniq": 0.1}},
                        {"i": 3, "chars": 50, "dropped": False, "distinctive": [],
                         "scores": {"noise": 0.1, "uniq": 0.9}}]}
        _write_jsonl(os.path.join(archive, "decisions.jsonl"), [decision])
        with open(os.path.join(archive, "human_baseline.json"), "w", encoding="utf-8") as fh:
            json.dump({"labelled": 50, "agreement": 0.9, "new_since": 10}, fh)

        thresholds = os.path.join(tempfile.mkdtemp(), "thresholds.json")
        r = self._run(home, thresholds, extra_args=("--apply",))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("已套用", r.stdout)
        self.assertTrue(os.path.exists(thresholds))
        with open(thresholds, encoding="utf-8") as fh:
            written = json.load(fh)
        self.assertEqual(set(written.keys()),
                         {"noise_min", "uniq_max", "min_chunks", "max_drop_ratio"})

    def test_allow_worse_is_loud_in_output(self):
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, "archive"), exist_ok=True)
        thresholds = os.path.join(tempfile.mkdtemp(), "thresholds.json")
        r = self._run(home, thresholds, extra_args=("--allow-worse",))
        self.assertEqual(r.returncode, 0)
        self.assertIn("--allow-worse", r.stdout)
        self.assertIn("已解除", r.stdout)
        self.assertIn("更危險", r.stdout)
        self.assertFalse(os.path.exists(thresholds))


if __name__ == "__main__":
    unittest.main()
