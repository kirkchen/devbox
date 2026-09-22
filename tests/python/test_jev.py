import sys, os, json, io, unittest, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "../../chezmoi/private_dot_config/claude/tool-reduce"))
import jev


class FakeResponse(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False


class TestLoadEnv(unittest.TestCase):
    def test_parses_key_value_and_strips_quotes(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:
            fh.write('# comment\nFOO="bar"\nBAZ=qux\n\nBAD_LINE\n')
            p = fh.name
        os.environ.pop("FOO", None); os.environ.pop("BAZ", None)
        jev.load_env(p)
        self.assertEqual(os.environ["FOO"], "bar")
        self.assertEqual(os.environ["BAZ"], "qux")
        os.unlink(p)

    def test_does_not_override_existing(self):
        os.environ["ALREADY"] = "kept"
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:
            fh.write("ALREADY=overwritten\n"); p = fh.name
        jev.load_env(p)
        self.assertEqual(os.environ["ALREADY"], "kept")
        os.unlink(p)

    def test_missing_file_is_silent(self):
        jev.load_env("/nonexistent/path.env")   # 不可丟例外


class TestBuildQuestions(unittest.TestCase):
    def test_two_questions_per_chunk(self):
        qs = jev.build_questions(3)
        self.assertEqual(len(qs), 6)
        self.assertIn("noise_c0", qs)
        self.assertIn("uniq_c2", qs)
        self.assertEqual(qs["noise_c1"]["type"], "noul")
        self.assertIn("`chunks.c1`", qs["noise_c1"]["instructions"])


class TestAsk(unittest.TestCase):
    def test_parses_answers(self):
        body = json.dumps({"answers": {"noise_c0": {"noul": 0.8}}}).encode()
        def opener(req, timeout=None): return FakeResponse(body)
        out = jev.ask({"chunks": {}}, {"noise_c0": {}}, opener=opener)
        self.assertEqual(out["noise_c0"]["noul"], 0.8)

    def test_raises_on_missing_answers(self):
        def opener(req, timeout=None): return FakeResponse(b'{"detail": "boom"}')
        with self.assertRaises(RuntimeError):
            jev.ask({}, {}, opener=opener)

    def test_raises_on_malformed_json(self):
        def opener(req, timeout=None): return FakeResponse(b"not json")
        with self.assertRaises(RuntimeError):
            jev.ask({}, {}, opener=opener)

    def test_api_key_never_appears_in_error(self):
        os.environ["TYPESAFE_API_KEY"] = "apikey-SECRET-VALUE"
        def opener(req, timeout=None): raise OSError("connection reset")
        try:
            jev.ask({}, {}, opener=opener)
        except RuntimeError as e:
            self.assertNotIn("SECRET", str(e))
        else:
            self.fail("expected RuntimeError")


class TestScores(unittest.TestCase):
    def test_maps_answers_to_per_chunk_scores(self):
        a = {"noise_c0": {"noul": 0.9}, "uniq_c0": {"noul": 0.1},
             "noise_c1": {"noul": 0.2}}
        s = jev.scores(a, 2)
        self.assertEqual(s[0], {"noise": 0.9, "uniq": 0.1})
        self.assertEqual(s[1], {"noise": 0.2, "uniq": None})




class TestBooleanAnswersAreNotScores(unittest.TestCase):
    """I5 的上游那一半：Jev 回 `{"noul": true}` 時 scores() 以前會原樣
    保留 True，下游的 isinstance(x, (int, float)) 檢查放行、當成 1.0。
    一次完全沒有分數的回應會造成三段被刪。"""

    def test_boolean_noul_becomes_none(self):
        answers = {}
        for i in range(3):
            answers[f"noise_c{i}"] = {"noul": True}
            answers[f"uniq_c{i}"] = {"noul": False}
        rows = jev.scores(answers, 3)
        for row in rows:
            self.assertIsNone(row["noise"])
            self.assertIsNone(row["uniq"])

    def test_real_numbers_still_pass_through(self):
        answers = {"noise_c0": {"noul": 0.9}, "uniq_c0": {"noul": 0}}
        rows = jev.scores(answers, 1)
        self.assertEqual(rows[0]["noise"], 0.9)
        self.assertEqual(rows[0]["uniq"], 0)


if __name__ == "__main__":
    unittest.main()
