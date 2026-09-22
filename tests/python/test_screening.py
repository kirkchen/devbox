# tests/python/test_screening.py
"""screening.py：把路由決策接上 Layer 1 的完成度分數。

review.py 原本只看 decisions.jsonl 與 transcript 用量，看不到產出品質。
這裡測的是分組與統計，不重測評分本身。
"""
import importlib.util
import json
import os
import tempfile
import unittest

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
MODULE_PATH = os.path.join(
    BASE, "chezmoi/private_dot_config/claude/model-router/screening.py")

_spec = importlib.util.spec_from_file_location("screening", MODULE_PATH)
screening = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(screening)


def _row(agent_id, addressed=0.5, incomplete=0.1, depth=1.0, needs=True):
    return {
        "agent_id": agent_id,
        "output_chars": 1000,
        "needs_layer2": needs,
        "screen": {
            "addressed_everything": {"noul": addressed},
            "signs_of_incompleteness": {"noul": incomplete},
            "refused_or_blocked": {"noul": 0.05},
            "output_depth": {"score": depth, "confidence": 0.9},
        },
    }


def _decision(agent_id, model_applied=None):
    return {"model_applied": model_applied, "outcome": {"agent_id": agent_id}}


class TestLoadCorpus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write(self, rows):
        path = os.path.join(self.tmp.name, "corpus.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")
        return path

    def test_groups_every_row_under_its_agent_id(self):
        # 一個 agent 交回多次就有多列，全部都要留著。
        path = self._write([_row("a1"), _row("a1"), _row("a2")])
        got = screening.load_corpus(path)
        self.assertEqual(len(got["a1"]), 2)
        self.assertEqual(len(got["a2"]), 1)

    def test_missing_file_is_empty_not_an_error(self):
        self.assertEqual(
            screening.load_corpus(os.path.join(self.tmp.name, "nope.jsonl")), {})

    def test_skips_malformed_lines(self):
        path = os.path.join(self.tmp.name, "broken.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json\n")
            fh.write(json.dumps(_row("a1")) + "\n")
        self.assertEqual(list(screening.load_corpus(path)), ["a1"])


class TestCompare(unittest.TestCase):
    """分組依據是「router 有沒有實際改掉模型」。"""

    def test_splits_changed_from_untouched(self):
        corpus = {"a1": [_row("a1")], "a2": [_row("a2")]}
        got = screening.compare([_decision("a1", "sonnet"), _decision("a2")], corpus)
        self.assertEqual(got["changed"]["n"], 1)
        self.assertEqual(got["untouched"]["n"], 1)

    def test_counts_every_handback_of_one_agent(self):
        corpus = {"a1": [_row("a1"), _row("a1"), _row("a1")]}
        got = screening.compare([_decision("a1", "haiku")], corpus)
        self.assertEqual(got["changed"]["n"], 3)

    def test_reports_decisions_with_no_layer1_row(self):
        got = screening.compare([_decision("missing", "sonnet")], {})
        self.assertEqual(got["unmatched"], 1)
        self.assertEqual(got["changed"]["n"], 0)

    def test_takes_the_median_of_each_signal(self):
        corpus = {"a1": [_row("a1", addressed=0.2, depth=1.0),
                         _row("a1", addressed=0.4, depth=2.0),
                         _row("a1", addressed=0.9, depth=3.0)]}
        got = screening.compare([_decision("a1", "sonnet")], corpus)
        self.assertAlmostEqual(got["changed"]["addressed_everything"], 0.4)
        self.assertAlmostEqual(got["changed"]["output_depth"], 2.0)

    def test_counts_how_many_were_flagged_for_layer2(self):
        corpus = {"a1": [_row("a1", needs=True), _row("a1", needs=False)]}
        got = screening.compare([_decision("a1", "sonnet")], corpus)
        self.assertEqual(got["changed"]["needs_layer2"], 1)

    def test_a_group_with_no_rows_reports_n_zero_without_dividing_by_zero(self):
        got = screening.compare([_decision("a1", "sonnet")], {"a1": [_row("a1")]})
        self.assertEqual(got["untouched"]["n"], 0)
        self.assertIsNone(got["untouched"]["output_depth"])

    def test_no_corpus_at_all_yields_both_groups_empty(self):
        got = screening.compare([_decision("a1", "sonnet"), _decision("a2")], {})
        self.assertEqual(got["changed"]["n"], 0)
        self.assertEqual(got["untouched"]["n"], 0)
        self.assertEqual(got["unmatched"], 2)


class TestDescribe(unittest.TestCase):
    """數字不能跟警語分家，不然表格會被當成證據讀。"""

    def _described(self, decisions, corpus):
        return "\n".join(screening.describe(screening.compare(decisions, corpus)))

    def test_always_carries_the_caveat_next_to_the_numbers(self):
        text = self._described([_decision("a1", "sonnet"), _decision("a2")],
                               {"a1": [_row("a1")], "a2": [_row("a2")]})
        self.assertIn("路由改過", text)
        self.assertIn("路由沒動", text)
        self.assertIn("這是敘述不是證據", text)
        self.assertIn("Layer 2 盲標", text)

    def test_says_so_plainly_when_nothing_joins(self):
        text = self._described([_decision("a1", "sonnet")], {})
        self.assertIn("corpus 接不到任何一筆決策", text)

    def test_an_empty_group_does_not_crash_the_render(self):
        text = self._described([_decision("a1", "sonnet")], {"a1": [_row("a1")]})
        self.assertIn("路由沒動：無", text)


if __name__ == "__main__":
    unittest.main()
