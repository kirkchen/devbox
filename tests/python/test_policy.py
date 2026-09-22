import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "../../chezmoi/private_dot_config/claude/tool-reduce"))
import drop_policy as policy


def sc(*pairs):
    return [{"noise": n, "uniq": u} for n, u in pairs]


class TestThresholds(unittest.TestCase):
    def test_drops_when_noisy_and_not_unique(self):
        s = sc((0.2, 0.9), (0.9, 0.1), (0.9, 0.1), (0.9, 0.1), (0.2, 0.9))
        d = policy.decide(s, [100] * 5)
        self.assertEqual(d, [False, True, True, True, False])

    def test_keeps_when_unique_even_if_noisy(self):
        s = sc((0.2, 0.9), (0.9, 0.8), (0.2, 0.9))
        self.assertEqual(policy.decide(s, [100] * 3), [False, False, False])

    def test_keeps_when_not_noisy(self):
        s = sc((0.2, 0.9), (0.5, 0.1), (0.2, 0.9))
        self.assertEqual(policy.decide(s, [100] * 3), [False, False, False])


class TestPositionFloor(unittest.TestCase):
    """第一段的 later-referenced 率 42%（中間段 20.3%），卻拿到最高的 noise 分數。
    這條規則把誤刪率從 9.8% 壓到 3.7%，代價只有 1.7 個百分點的節省。"""

    def test_never_drops_first_chunk(self):
        s = sc((0.99, 0.01), (0.99, 0.01), (0.99, 0.01), (0.99, 0.01))
        self.assertFalse(policy.decide(s, [100] * 4)[0])

    def test_never_drops_last_chunk(self):
        s = sc((0.99, 0.01), (0.99, 0.01), (0.99, 0.01), (0.99, 0.01))
        self.assertFalse(policy.decide(s, [100] * 4)[-1])


class TestGuards(unittest.TestCase):
    def test_too_few_chunks_drops_nothing(self):
        s = sc((0.99, 0.01), (0.99, 0.01))
        self.assertEqual(policy.decide(s, [100] * 2), [False, False])

    def test_missing_score_is_never_dropped(self):
        s = [{"noise": 0.2, "uniq": 0.9}, {"noise": None, "uniq": 0.1},
             {"noise": 0.99, "uniq": 0.01}, {"noise": 0.2, "uniq": 0.9}]
        d = policy.decide(s, [100] * 4)
        self.assertFalse(d[1])
        self.assertTrue(d[2])

    def test_respects_max_drop_ratio(self):
        """單份最多刪 60%：超過就從分數最低的那些開始留回來。"""
        s = sc((0.1, 0.9)) + sc(*[(0.99, 0.01)] * 8) + sc((0.1, 0.9))
        chars = [100] * 10
        d = policy.decide(s, chars)
        dropped = sum(c for c, x in zip(chars, d) if x)
        self.assertLessEqual(dropped / sum(chars), policy.DEFAULTS["max_drop_ratio"])

    def test_threshold_override(self):
        s = sc((0.2, 0.9), (0.55, 0.1), (0.2, 0.9), (0.2, 0.9))
        self.assertFalse(policy.decide(s, [100] * 4)[1])
        t = dict(policy.DEFAULTS, noise_min=0.5)
        self.assertTrue(policy.decide(s, [100] * 4, t)[1])

    def test_partial_threshold_dict_merges_onto_defaults(self):
        """Passing partial threshold dict should merge, not raise KeyError."""
        s = sc((0.2, 0.9), (0.55, 0.1), (0.2, 0.9), (0.2, 0.9))
        t = {"noise_min": 0.5}  # Missing min_chunks, max_drop_ratio, uniq_max
        d = policy.decide(s, [100] * 4, t)
        self.assertTrue(d[1])  # Should use merged defaults for other keys

    def test_non_dict_score_entry_is_never_dropped(self):
        """Non-dict entry in scores should degrade to keep, not crash."""
        s = [{"noise": 0.2, "uniq": 0.9}, "not a dict",
             {"noise": 0.99, "uniq": 0.01}, {"noise": 0.2, "uniq": 0.9}]
        d = policy.decide(s, [100] * 4)
        self.assertFalse(d[1])  # Non-dict entry should be kept
        self.assertTrue(d[2])  # Real dict with high noise should be dropped




class TestBooleanScoresNeverDelete(unittest.TestCase):
    """I5：Python 的 bool 是 int 的子類別，所以 isinstance(True, (int, float))
    是 True。`{"noise": True, "uniq": False}` 會被當成 noise=1.0、uniq=0.0
    一路刪下去。每一支離線工具（tr-stats、tr-eval、tr-tune）都明確排除
    bool；唯獨這條線上路徑沒有——而這是三條路徑裡唯一的後果是「刪掉文字」
    而不是「算錯數字」的。這也是整個 fail-open 契約唯一會反轉的地方：
    上游給垃圾，結果是刪除而不是放行。"""

    def test_boolean_scores_drop_nothing(self):
        s = [{"noise": True, "uniq": False} for _ in range(5)]
        self.assertEqual(policy.decide(s, [100] * 5), [False] * 5)

    def test_one_boolean_field_is_enough_to_keep_the_chunk(self):
        s = sc((0.2, 0.9), (0.9, 0.1), (0.9, 0.1), (0.2, 0.9))
        s[1]["noise"] = True
        s[2]["uniq"] = False
        self.assertEqual(policy.decide(s, [100] * 4), [False] * 4)


if __name__ == "__main__":
    unittest.main()
