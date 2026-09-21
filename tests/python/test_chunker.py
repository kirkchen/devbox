import sys, os, json, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "../../chezmoi/private_dot_config/claude/tool-reduce"))
import chunker


class TestNoContentLoss(unittest.TestCase):
    """最重要的不變式：段落接回來要跟輸入的 payload 一字不差。"""

    def test_plain_lines(self):
        t = "\n".join(f"line {i} with some filler text here" for i in range(200))
        cs, _ = chunker.chunk(t)
        self.assertEqual("".join(cs), t)

    def test_single_line_json(self):
        t = json.dumps({"result": "x" * 5000})
        cs, kind = chunker.chunk(t)
        self.assertTrue(kind.startswith("mcp:"))
        self.assertEqual("".join(cs), "x" * 5000)

    def test_short_text_is_one_chunk(self):
        t = "short"
        cs, _ = chunker.chunk(t)
        self.assertEqual(cs, ["short"])


class TestEnvelopeUnwrap(unittest.TestCase):
    def test_mcp_envelope_unwrapped(self):
        inner = "# Search Results\n" + "\n".join(f"### Result {i} of 20\nbody {i}" for i in range(20))
        t = json.dumps({"results": inner, "pagination_info": "none"})
        cs, kind = chunker.chunk(t)
        self.assertEqual(kind, "mcp:results")
        self.assertEqual("".join(cs), inner)

    def test_escaped_payload_beats_ratio_check(self):
        """逃逸序列會讓外層字串膨脹，不能用『內層 > 外層一半』當判準。"""
        inner = "中文內容 " * 400
        t = json.dumps({"results": inner}, ensure_ascii=True)
        self.assertGreater(len(t), len(inner) * 2)
        _, kind = chunker.chunk(t)
        self.assertEqual(kind, "mcp:results")

    def test_non_json_dict_like_text_not_unwrapped(self):
        t = "{ this is not json, just braces }\n" + "x" * 3000
        _, kind = chunker.chunk(t)
        self.assertEqual(kind, "raw")


class TestSeparators(unittest.TestCase):
    def test_diff_split_on_file_boundaries(self):
        files = ["diff --git a/f%d.py b/f%d.py\n" % (i, i) + "+line\n" * 60 for i in range(6)]
        cs, _ = chunker.chunk("".join(files))
        self.assertGreaterEqual(len(cs), 4)
        starts = sum(1 for c in cs if c.startswith("diff --git"))
        self.assertGreaterEqual(starts, 4)

    def test_read_line_number_prefix_does_not_block_headings(self):
        """Read 的輸出是 `123\\t內容`，標題偵測要看得穿這層前綴。"""
        body = []
        for i in range(1, 121):
            body.append(f"{i}\t## Section {i//20}" if i % 20 == 1 else f"{i}\tbody text line {i}")
        t = "\n".join(body)
        cs, kind = chunker.chunk(t)
        self.assertEqual(kind, "read")
        self.assertEqual("".join(cs), t)
        self.assertGreater(len(cs), 2)

    def test_grep_output_groups_by_file(self):
        lines = []
        for f in ("a.tf", "b.tf", "c.tf"):
            lines += [f"{f}:{n}:  resource block {n}" for n in range(1, 40)]
        cs, _ = chunker.chunk("\n".join(lines))
        self.assertGreaterEqual(len(cs), 3)


class TestBounds(unittest.TestCase):
    def test_never_exceeds_max_chunks(self):
        t = "\n".join(f"line {i}" for i in range(5000))
        cs, _ = chunker.chunk(t, max_chunks=16)
        self.assertLessEqual(len(cs), 16)

    def test_respects_min_chars_by_merging(self):
        t = "\n\n".join("x" for _ in range(400))   # 大量極小片段
        cs, _ = chunker.chunk(t, min_chars=300)
        self.assertTrue(all(len(c) >= 200 for c in cs[:-1]))


if __name__ == "__main__":
    unittest.main()
