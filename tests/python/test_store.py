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




# I4：六種實測過、原本一個都沒被濾掉的真實形狀憑證，加上原本就擋得住的
# 幾種（回歸保護）。archive/ 刻意不被 tr-cleanup.sh 清掉、7 天掃除也排除
# 它，所以漏掉的東西是永久的。
MODERN_SECRETS = {
    "jwt": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
           "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4ifQ."
           "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
    "google_api_key": "AIzaSyD-9tSrke72PouQMnMX-a7eZSW0jkFMBWY",
    "gitlab_pat": "glpat-ABC123defGHI456jklM",
    # 字面拆開：這是捏造的測試值，但 GitHub 的 push protection 認樣式不認真偽，
    # 整串寫在原始碼裡會讓每次 push 被擋。組裝後 scrub() 看到的仍是完整字串。
    "stripe_live": "sk_" + "live_" + "51H8xY2KZvIcABCdefGHIjklMNOpqrSTUvwxYZ",
    "slack_app": "xapp-1-A01234567-1234567890123-abcdef",
    "huggingface": "hf_ABCdefGHIjklMNOpqrSTUvwxYZ012345",
    "npm": "npm_ABCdefGHIjklMNOpqrSTUvwxYZ0123456789",
    "vault": "hvs.CAESIJxyzABCdefGHIjklMNOpqrSTUvwxYZ0123456789",
}
ALREADY_COVERED = {
    "openai": "sk-abcdefghijklmnopqrstuvwxyz012345",
    "github": "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
    "aws": "AKIAIOSFODNN7EXAMPLE",
    "slack_bot": "xoxb-1234-5678-abcdefgh",
    "long_base64": "aGVsbG93b3JsZGFiY2RlZmdoaWprbG1ub3BxcnN0dXZ3eHl6MDEyMzQ1",
}
BENIGN_TOKENS = [
    "main.py", "target_https_proxy", "module.uat_cluster.ns_alpha",
    "src/components/Button.tsx", "kubernetes_namespace", "2026-09-22",
    "docs/superpowers/specs/2026-09-21-tool-result-reduce-design.md",
    "chezmoi/private_dot_config/claude/tool-reduce/executable_tr-eval.py",
    "noOutputExpected", "persistedOutputPath",
    # 40 字元以上、但沒有點的路徑與 snake/kebab 識別字。原本這份清單裡
    # 一個都沒有，所以「放寬正則不能把識別字掃掉」這條測不出東西——
    # 加寬 SECRET_RE 時整批被掃掉也不會紅。
    "chezmoi/private_dot_config/claude/tool-reduce",
    "google_compute_region_network_endpoint_group",
    "jkopay-payment-gateway-deployment-prod-abc123",
    "session-ac09f1da-7b9f-49ae-93c7-413e44ac698e",
    "module.gcp_uat_cluster_network.google_compute_subnetwork.primary_subnet",
    "google_compute_region_network_endpoint_group.some_very_long_attribute_name",
    # 以密鑰欄位名開頭、但整個 token 不是那個欄位名的普通識別字。
    # 前綴比對會把這一整類掃掉。
    "password_hash", "private_key_path", "access_token_url",
    "refresh_token_expiry", "secret_key_base", "api_key_id",
    "npm_package_version", "npm_config_registry",
    "hf_dataset_loader", "AIzaHelper",
]

# 欄位名稱本身（整個 token 相等，或 `name=value` 形狀）還是要濾掉——
# 上面那批「以欄位名開頭」的識別字不該把這條也一起放掉。
SECRET_FIELD_NAMES = ["password", "passwd", "api_key", "apikey", "secret_key",
                      "client_secret", "access_token", "refresh_token",
                      "private_key", "password=hunter2"]


class TestScrubCoversModernCredentialShapes(unittest.TestCase):
    def test_modern_shapes_are_scrubbed(self):
        for name, value in MODERN_SECRETS.items():
            with self.subTest(name):
                self.assertEqual(store.scrub([value]), [], f"{name} leaked")

    def test_previously_covered_shapes_still_scrubbed(self):
        for name, value in ALREADY_COVERED.items():
            with self.subTest(name):
                self.assertEqual(store.scrub([value]), [], f"{name} leaked")

    def test_ordinary_identifiers_survive(self):
        """放寬正則不能變成把所有識別字都濾掉——獨有詞集合是 tr-eval 的
        Layer 1 比對依據，濾過頭會把沉默誤刪往低估那個方向偏（刪除看起來
        比實際安全），而且 `[REDACTED]` 會出現在 agent 真正會讀的墓碑標記
        上，那是它用來決定要不要還原的那行字。"""
        self.assertEqual(store.scrub(BENIGN_TOKENS), BENIGN_TOKENS)

    def test_the_benign_list_actually_exercises_both_regression_classes(self):
        """這份清單的前提：要真的包含「≥40 字元且沒有點」跟「以密鑰欄位名
        開頭」這兩類，否則 test_ordinary_identifiers_survive 對這兩種放寬
        方式是盲的（它原本就是）。"""
        self.assertTrue(any(len(t) >= 40 and "." not in t for t in BENIGN_TOKENS))
        self.assertTrue(any(t.startswith(("password", "api_key", "npm_", "hf_"))
                            for t in BENIGN_TOKENS))

    def test_bare_credential_field_names_are_still_scrubbed(self):
        """把欄位名規則改成整詞比對，不能變成整條失效。"""
        for name in SECRET_FIELD_NAMES:
            with self.subTest(name):
                self.assertEqual(store.scrub([name]), [], f"{name} survived")

    def test_dot_separated_rule_needs_long_segments(self):
        """以 `.` 分段的規則要求每段夠長，一般模組路徑打不到。"""
        self.assertEqual(store.scrub(["a.b.c", "main.py", "pkg.module.Class"]),
                         ["a.b.c", "main.py", "pkg.module.Class"])


class TestDescriptorDoesNotCarrySecretsIntoTheArchive(unittest.TestCase):
    """descriptor.make() 把被刪段落首行的前 ~200 字元放進墓碑標記，而那個
    標記會被寫進 archive/tombstones.jsonl —— 永久保留。JWT 原本會整條進去
    （TOKEN_CHARS 含 `.`，整個 JWT 是一個 token，長 base64 那條規則碰到點
    就比對失敗）。"""

    def test_jwt_in_the_first_line_is_redacted(self):
        import descriptor
        marker = descriptor.make(
            "Authorization: Bearer " + MODERN_SECRETS["jwt"] + "\nmore\n",
            "abc123.1")
        self.assertNotIn(MODERN_SECRETS["jwt"], marker)
        self.assertIn(descriptor.REDACTED, marker)

    def test_each_modern_shape_is_redacted_in_the_marker(self):
        import descriptor
        for name, value in MODERN_SECRETS.items():
            with self.subTest(name):
                marker = descriptor.make(f"token is {value} here\nmore\n", "abc123.1")
                self.assertNotIn(value, marker, f"{name} reached the marker")


if __name__ == "__main__":
    unittest.main()
