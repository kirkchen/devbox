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




class TestSessionIdContainment(unittest.TestCase):
    """M1：存放區裡每一個「拿外來字串組路徑」的地方都先驗證再組 —— 除了
    真正寫檔案的那一端。`Store("../escaped-session")` 會寫到存放區外面，
    `Store("/tmp/absolute")` 會寫到 /tmp（os.path.join 碰到絕對路徑會整段
    丟掉前面的 root）。session_id 今天來自 harness 的 UUID，不是攻擊者
    控制的，所以這不是現成的攻擊路徑；但它是這條不變量在整個模組裡唯一
    的缺口，而缺口在寫入端比在讀取端更貴。"""

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def test_traversal_session_id_is_rejected(self):
        with self.assertRaises(ValueError):
            store.Store("../escaped-session", root=self.root)

    def test_absolute_session_id_is_rejected(self):
        with self.assertRaises(ValueError):
            store.Store("/tmp/absolute", root=self.root)

    def test_nested_session_id_is_rejected(self):
        with self.assertRaises(ValueError):
            store.Store("a/b", root=self.root)

    def test_empty_and_non_string_session_ids_are_rejected(self):
        for bad in ("", None, 3, b"sess"):
            with self.assertRaises(ValueError):
                store.Store(bad, root=self.root)

    def test_archive_is_not_a_usable_session_id(self):
        """封存區只存紀錄、不存原文，而且永遠不會被清掉。一個叫 archive
        的 session 會把可能帶密鑰的段落原文寫進去。"""
        with self.assertRaises(ValueError):
            store.Store("archive", root=self.root)

    def test_ordinary_session_ids_still_work(self):
        for good in ("sess-1", "unknown", "ac09f1da-7b9f-49ae-93c7-413e44ac698e"):
            s = store.Store(good, root=self.root)
            self.assertEqual(os.path.dirname(s.path), os.path.abspath(self.root))


class TestSaveChunkIsAtomic(unittest.TestCase):
    """I6 的一半：open(p,"w") 先截斷再寫，寫到一半失敗會留下一個零位元組
    的 `<handle>.txt`。那個檔案存在、load_chunk 讀得到、回傳空字串 ——
    一個指向空氣的墓碑，直接打穿「刪掉的東西一定救得回來」。"""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.s = store.Store("sess-atomic", root=self.root)

    def test_encode_failure_leaves_no_truncated_file(self):
        with self.assertRaises(UnicodeEncodeError):
            self.s.save_chunk("d1.1", "text with a lone surrogate \ud800 in it")
        self.assertFalse(os.path.exists(os.path.join(self.s.path, "d1.1.txt")))
        self.assertIsNone(self.s.load_chunk("d1.1"))

    def test_failed_overwrite_leaves_the_previous_content_intact(self):
        self.s.save_chunk("d1.2", "the original text")
        with self.assertRaises(UnicodeEncodeError):
            self.s.save_chunk("d1.2", "\ud800")
        self.assertEqual(self.s.load_chunk("d1.2"), "the original text")

    def test_no_temp_files_are_left_behind_on_failure(self):
        with self.assertRaises(UnicodeEncodeError):
            self.s.save_chunk("d1.3", "\ud800")
        self.assertEqual([n for n in os.listdir(self.s.path) if n.endswith(".tmp")], [])

    def test_saved_chunk_is_still_private(self):
        self.s.save_chunk("d1.4", "x")
        mode = stat.S_IMODE(os.stat(os.path.join(self.s.path, "d1.4.txt")).st_mode)
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
