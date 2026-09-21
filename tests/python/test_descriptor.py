# tests/python/test_descriptor.py
import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "../../chezmoi/private_dot_config/claude/tool-reduce"))
import descriptor


class TestMake(unittest.TestCase):
    def test_includes_line_count_and_handle(self):
        chunk = "\n".join(f"line {i}" for i in range(42))
        d = descriptor.make(chunk, "a3f2.7")
        self.assertIn("42", d)
        self.assertIn("tr-restore a3f2.7", d)
        self.assertTrue(d.startswith("[") and d.endswith("]"))

    def test_uses_first_meaningful_line(self):
        chunk = "\n\n   \n/Users/kirk/Code/x/main.tf:36:# Internal LB\nmore\n"
        self.assertIn("main.tf", descriptor.make(chunk, "h.1"))

    def test_respects_max_chars(self):
        chunk = "x" * 5000 + "\n" + "y" * 5000
        self.assertLessEqual(len(descriptor.make(chunk, "h.1", max_chars=250)), 250)

    def test_is_single_line(self):
        chunk = "a\nb\nc\n" * 30
        self.assertNotIn("\n", descriptor.make(chunk, "h.1"))

    def test_honours_max_chars_when_handle_alone_blows_the_budget(self):
        # room < 0: prefix + tail already exceed max_chars before any head
        # text is added. The fallback must still be hard-capped.
        d = descriptor.make("hello world", "h" * 300, max_chars=250)
        self.assertLessEqual(len(d), 250)

    def test_honours_max_chars_on_small_budget(self):
        # room < 0 also fires with an ordinary handle once max_chars is
        # small — this is the realistic trigger, not just an adversarial
        # giant handle.
        d = descriptor.make("hello world", "h.1", max_chars=10)
        self.assertLessEqual(len(d), 10)

    def test_room_exactly_zero_does_not_overflow_by_one(self):
        # room == 0: the old code appended an ellipsis unconditionally,
        # overflowing max_chars by exactly one character.
        d = descriptor.make("hello world", "h.1", max_chars=28)
        self.assertLessEqual(len(d), 28)

    def test_handle_with_newline_does_not_break_single_line_guarantee(self):
        d = descriptor.make("x", "evil\nhandle.1")
        self.assertNotIn("\n", d)

    def test_scrubs_secret_shaped_tokens_from_the_descriptor(self):
        chunk = "token sk-abcdefghijklmnopqrstuvwxyz012345 leaked here"
        d = descriptor.make(chunk, "h.1")
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz012345", d)


class TestDistinctive(unittest.TestCase):
    def test_returns_tokens_absent_from_other_chunks(self):
        c = "resource google_compute_target_https_proxy uat_proxy_8821"
        others = ["resource google_compute_address prod_addr"]
        toks = descriptor.distinctive(c, others)
        self.assertIn("uat_proxy_8821", toks)
        self.assertNotIn("resource", toks)

    def test_respects_limit(self):
        c = " ".join(f"identifier_{i}" for i in range(200))
        self.assertLessEqual(len(descriptor.distinctive(c, [], limit=40)), 40)

    def test_drops_urls_and_short_tokens(self):
        toks = descriptor.distinctive("see https://example.com/page and ab cd", [])
        self.assertFalse(any(t.startswith("http") for t in toks))
        self.assertNotIn("ab", toks)
        # The domain/path after "://" is captured by TOKEN even though
        # "https" itself is too short to match — the startswith("http")
        # guard alone never catches this. The whole URL must be gone.
        self.assertNotIn("example.com/page", toks)


if __name__ == "__main__":
    unittest.main()
