# tests/python/test_store.py
import sys, os, json, stat, tempfile, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__),
                                "../../chezmoi/private_dot_config/claude/tool-reduce"))
import store


class TestChunkRoundTrip(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.s = store.Store("sess-1", root=self.root)

    def test_save_and_load(self):
        self.s.save_chunk("d1.3", "the original text")
        self.assertEqual(self.s.load_chunk("d1.3"), "the original text")

    def test_missing_handle_returns_none(self):
        self.assertIsNone(self.s.load_chunk("nope.1"))

    def test_rejects_path_traversal(self):
        self.assertIsNone(self.s.load_chunk("../../../etc/passwd"))
        self.assertIsNone(self.s.load_chunk("d1/../../x.1"))

    def test_directory_is_private(self):
        self.s.save_chunk("d1.1", "x")
        mode = stat.S_IMODE(os.stat(self.s.path).st_mode)
        self.assertEqual(mode, 0o700)


class TestRecords(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.s = store.Store("sess-2", root=self.root)

    def test_decision_appends_jsonl_to_both_locations(self):
        self.s.record_decision({"decision_id": "d1", "tool": "Bash"})
        self.s.record_decision({"decision_id": "d2", "tool": "Read"})
        live = os.path.join(self.s.path, "decisions.jsonl")
        arch = os.path.join(self.root, "archive", "decisions.jsonl")
        for p in (live, arch):
            rows = [json.loads(l) for l in open(p, encoding="utf-8")]
            self.assertEqual([r["decision_id"] for r in rows], ["d1", "d2"])

    def test_restore_record(self):
        self.s.record_restore({"handle": "d1.3", "via": "tr-restore"})
        arch = os.path.join(self.root, "archive", "restores.jsonl")
        self.assertEqual(json.loads(open(arch).readline())["handle"], "d1.3")

    def test_append_is_best_effort_when_one_destination_is_blocked(self):
        # Block the archive location with a plain file instead of a
        # directory, simulating the fault-injection scenario from review:
        # the session-dir copy must still land and no exception may
        # escape, because the caller is a fail-open hook.
        archive_path = os.path.join(self.root, "archive")
        with open(archive_path, "w", encoding="utf-8") as fh:
            fh.write("not a directory")

        self.s.record_decision({"decision_id": "d1"})  # must not raise

        live = os.path.join(self.s.path, "decisions.jsonl")
        rows = [json.loads(l) for l in open(live, encoding="utf-8")]
        self.assertEqual(rows[0]["decision_id"], "d1")

    def test_unserialisable_record_does_not_raise(self):
        # A value json.dumps() cannot handle (a set here) must not escape
        # _append() as a TypeError — the docstring promises no exception
        # ever escapes, and the caller is a fail-open hook.
        self.s.record_decision({"decision_id": "d1", "bad": {1, 2, 3}})


class TestAbsolutePath(unittest.TestCase):
    def test_relative_root_yields_absolute_path(self):
        s = store.Store("sess-rel", root="some/relative/tool-reduce-root")
        self.assertTrue(os.path.isabs(s.path))


class TestScrub(unittest.TestCase):
    def test_removes_secret_shaped_tokens(self):
        toks = ["main.tf", "sk-abcdefghijklmnopqrstuvwxyz012345",
                "target_https_proxy", "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
                "AKIAIOSFODNN7EXAMPLE"]
        out = store.scrub(toks)
        self.assertIn("main.tf", out)
        self.assertIn("target_https_proxy", out)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz012345", out)
        self.assertNotIn("ghp_0123456789abcdefghijklmnopqrstuvwxyz", out)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", out)

    def test_removes_long_high_entropy_tokens(self):
        out = store.scrub(["aGVsbG93b3JsZGFiY2RlZmdoaWprbG1ub3BxcnN0dXZ3eHl6MDEyMzQ1"])
        self.assertEqual(out, [])


if __name__ == "__main__":
    unittest.main()
