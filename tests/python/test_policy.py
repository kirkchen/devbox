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
    離線研究（另一份 chunker、200 筆語料）量到這條規則把誤刪率從 9.8% 壓到
    3.7%，代價 1.7 個百分點的節省。那幾個絕對值沒有被上線後的實測驗證過
    ——實測只驗了節省那一項（預估 7.9%、實際 2.2%）；這裡釘住的是規則本身
    （頭尾永遠不刪），不是那些數字。"""

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




class TestShippedSourceDoesNotStateTheSupersededFigure(unittest.TestCase):
    """M4：出貨的原始碼裡三處把已經被取代的 7.9% 當成事實在寫，而 README
    同一份 repo 裡寫的是實測 2.2%。那幾個數字全部來自 arm-A 的離線研究
    （另一份 chunker、200 筆語料），沒有一處加註。

    下一個讀這些 docstring 的人會照著它們判斷門檻該往哪調——這是「先在
    2.2% 上線、之後再從遙測重新推導」那個決定唯一寫在程式碼裡的依據，
    寫錯等於把決定的理由也寫錯了。"""

    def test_drop_policy_states_the_measured_figure_next_to_the_estimate(self):
        doc = policy.__doc__
        self.assertNotIn("省 7.9%、誤刪 3.7%", doc,
                         "the superseded arm-A figure is still stated as fact")
        self.assertIn("7.9%", doc)      # 保留歷史，但要標明是預估
        self.assertIn("2.2%", doc)      # 實測值要在同一段裡
        self.assertIn("離線", doc)
        self.assertIn("chunker", doc)

    def test_descriptor_qualifies_its_arm_a_numbers(self):
        import descriptor
        doc = descriptor.__doc__
        self.assertIn("+3.6% 掉到 −0.9%", doc)   # 結論（由正轉負）保留
        self.assertIn("離線", doc)
        self.assertIn("2.2%", doc)

    def test_this_files_own_docstring_is_qualified_too(self):
        doc = TestPositionFloor.__doc__
        self.assertNotIn("這條規則把誤刪率從 9.8% 壓到 3.7%，代價只有", doc)
        self.assertIn("離線研究", doc)
        self.assertIn("2.2%", doc)


if __name__ == "__main__":
    unittest.main()
