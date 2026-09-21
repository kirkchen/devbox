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


class TestWhitespaceFold(unittest.TestCase):
    """Regression tests for the fold-not-drop fix in chunk()'s tail.

    The fixed-width fallback tier (last resort, used when nothing in the
    separator ladder matches) can land a cut boundary entirely inside a long
    run of whitespace -- e.g. markdown table column padding -- producing a
    piece that strips to empty but still holds real payload characters.
    An earlier version dropped such pieces with `[c for c in merged if
    c.strip()]`, which silently broke ''.join(chunks) == payload because the
    invariant assert ran on the list *before* that filter. These fixtures
    are built to have no separator ladder match at all (no headings, hr
    lines, diff/commit markers, blank-line runs, or grep-style `path:line:`
    prefixes), so `_split` is forced into the fixed-width fallback and its
    cuts land inside the whitespace runs deterministically -- not fished
    from a real transcript.
    """

    def test_whitespace_run_forces_fixed_width_cut_fold(self):
        """Markdown-table-padding shape: short cell markers separated by
        wide space-padding, so a fixed-width cut lands inside the padding."""
        t = "\n".join(f"| cell{i} |" + " " * 3000 for i in range(5))
        cs, kind = chunker.chunk(t)
        self.assertEqual("".join(cs), t)

    def test_consecutive_whitespace_pieces_fold_into_one_neighbour(self):
        """A single wide gap spans many fixed-width pieces in a row, so the
        `for c in merged: if not c.strip() and final: final[-1] += c` loop
        must fold more than one consecutive blank piece into the same
        neighbour, not just one."""
        t = "HEAD" + " " * 6000 + "TAIL"
        cs, kind = chunker.chunk(t)
        self.assertEqual("".join(cs), t)
        self.assertTrue(all(c.strip() for c in cs),
                         "a whitespace-only piece survived as its own chunk")

    def test_leading_whitespace_piece_folds_forward(self):
        """Payload starts with a long whitespace run before any real
        content, so `final[0]` is blank when the first loop finishes and the
        `while len(final) > 1 and not final[0].strip()` loop must fold it
        forward onto the next chunk."""
        t = " " * 6000 + "TAIL"
        cs, kind = chunker.chunk(t)
        self.assertEqual("".join(cs), t)

    def test_entirely_whitespace_payload_not_dropped(self):
        t = " " * 5000
        cs, kind = chunker.chunk(t)
        self.assertEqual("".join(cs), t)
        self.assertEqual(cs, [t])

    def test_max_chunks_bound_holds_after_whitespace_fold(self):
        """A wide gap forces multiple whitespace-only pieces that must fold
        away; the post-fold chunk count still must not exceed max_chunks."""
        t = "HEAD" + " " * 30000 + "TAIL"
        cs, kind = chunker.chunk(t, max_chunks=4, min_chars=300)
        self.assertEqual("".join(cs), t)
        self.assertLessEqual(len(cs), 4)


if __name__ == "__main__":
    unittest.main()
