import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "../../chezmoi/private_dot_config/claude/tool-reduce"))
import shapes


class TestExtract(unittest.TestCase):
    def test_bash_reads_stdout(self):
        r = {"stdout": "hello", "stderr": "", "interrupted": False}
        self.assertEqual(shapes.extract("Bash", r), "hello")

    def test_plain_string_response(self):
        self.assertEqual(shapes.extract("Whatever", "raw text"), "raw text")

    def test_unknown_tool_uses_fallback_fields(self):
        self.assertEqual(shapes.extract("mcp__x__y", {"result": "payload"}), "payload")

    def test_returns_none_when_no_text(self):
        self.assertIsNone(shapes.extract("Bash", {"interrupted": True}))
        self.assertIsNone(shapes.extract("Bash", {"stdout": ""}))
        self.assertIsNone(shapes.extract("Bash", None))

    def test_read_reads_nested_file_content(self):
        # 實測形狀：文字在 file.content，不是頂層 content/text/file。
        r = {"type": "text", "file": {"filePath": "/x", "content": "body",
                                       "numLines": 3, "startLine": 1, "totalLines": 3}}
        self.assertEqual(shapes.extract("Read", r), "body")

    def test_read_returns_none_when_no_content(self):
        self.assertIsNone(shapes.extract("Read", {"type": "text", "file": {"filePath": "/x", "content": ""}}))
        self.assertIsNone(shapes.extract("Read", {"type": "text"}))
        self.assertIsNone(shapes.extract("Read", {"type": "text", "file": "not a dict"}))


class TestRewrite(unittest.TestCase):
    def test_rewrite_preserves_sibling_fields(self):
        r = {"stdout": "long output", "stderr": "warn", "interrupted": False}
        out = shapes.rewrite("Bash", r, "short")
        self.assertEqual(out["stdout"], "short")
        self.assertEqual(out["stderr"], "warn")
        self.assertIs(out["interrupted"], False)

    def test_rewrite_does_not_mutate_input(self):
        r = {"stdout": "orig"}
        shapes.rewrite("Bash", r, "new")
        self.assertEqual(r["stdout"], "orig")

    def test_rewrite_plain_string(self):
        self.assertEqual(shapes.rewrite("X", "orig", "new"), "new")

    def test_rewrite_unknown_field_returns_original(self):
        r = {"interrupted": True}
        self.assertEqual(shapes.rewrite("Bash", r, "new"), r)

    def test_rewrite_read_preserves_file_siblings_and_top_level_type(self):
        r = {"type": "text", "file": {"filePath": "/x", "content": "body",
                                       "numLines": 3, "startLine": 1, "totalLines": 3}}
        out = shapes.rewrite("Read", r, "short")
        self.assertEqual(out["file"]["content"], "short")
        self.assertEqual(out["file"]["filePath"], "/x")
        self.assertEqual(out["file"]["numLines"], 3)
        self.assertEqual(out["type"], "text")

    def test_rewrite_read_does_not_mutate_input(self):
        r = {"type": "text", "file": {"filePath": "/x", "content": "orig"}}
        shapes.rewrite("Read", r, "new")
        self.assertEqual(r["file"]["content"], "orig")

    def test_rewrite_read_missing_content_returns_original(self):
        r = {"type": "text", "file": {"filePath": "/x"}}
        self.assertEqual(shapes.rewrite("Read", r, "new"), r)


if __name__ == "__main__":
    unittest.main()
