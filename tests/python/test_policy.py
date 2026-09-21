import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "../../chezmoi/private_dot_config/claude/tool-reduce"))
import policy


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


if __name__ == "__main__":
    unittest.main()
