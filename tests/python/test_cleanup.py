# tests/python/test_cleanup.py
"""I8：tr-cleanup.sh 是整個分支裡唯一的 `rm -rf`，而且沒有任何自動化測試。

這支腳本在 SessionEnd 被呼叫，拿 harness 送進 stdin 的 JSON 裡的
session_id 去組刪除目標。七種逃逸形狀先前只用手驗過、一條都沒進版控——
也就是說下一個人改這支腳本時，沒有任何東西會告訴他哪裡踩到線。

這些測試對「現在這一版」是綠的（腳本本身是對的），所以它們防的是回歸，
不是修 bug。為了確認它們不是永遠不會紅的假測試，另外有一個
TestTheseTestsCanActuallyFail：把腳本換成那個被 docstring 點名擋不住
`..` 的字面 glob 前綴版本，同一批穿越測試必須紅。
"""
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
CLEANUP = os.path.join(BASE, "chezmoi/private_dot_config/claude/hooks/executable_tr-cleanup.sh")


def run_cleanup(root, payload, script=None):
    """腳本吃 SessionEnd 的 JSON payload（stdin），用 TOOL_REDUCE_HOME 決定
    存放區根目錄。payload 傳字串就原樣送進去（測不合法 JSON 用）。"""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(["bash", script or CLEANUP], input=text,
                          capture_output=True, text=True,
                          env=dict(os.environ, TOOL_REDUCE_HOME=root))


class CleanupCase(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.outside = tempfile.mkdtemp()
        # 封存區：只存紀錄，這支腳本絕不能碰
        self.archive = os.path.join(self.root, "archive")
        os.makedirs(self.archive)
        with open(os.path.join(self.archive, "decisions.jsonl"), "w") as fh:
            fh.write('{"decision_id": "d1"}\n')
        # 一個正常的 session 目錄
        self.session = os.path.join(self.root, "sess-normal")
        os.makedirs(self.session)
        with open(os.path.join(self.session, "d1.0.txt"), "w") as fh:
            fh.write("a deleted passage")
        # 存放區外面的目標：任何測試結束後它都必須還在
        self.canary = os.path.join(self.outside, "do-not-delete")
        os.makedirs(self.canary)
        with open(os.path.join(self.canary, "important.txt"), "w") as fh:
            fh.write("still here")

    def tearDown(self):
        for d in (self.root, self.outside):
            shutil.rmtree(d, ignore_errors=True)

    def assertCanaryIntact(self):
        self.assertTrue(os.path.isdir(self.canary), "deleted something outside the store")
        self.assertTrue(os.path.exists(os.path.join(self.canary, "important.txt")))

    def assertArchiveIntact(self):
        self.assertTrue(os.path.isdir(self.archive), "deleted the archive")
        self.assertTrue(os.path.exists(os.path.join(self.archive, "decisions.jsonl")))


class TestNormalCleanup(CleanupCase):
    def test_removes_the_named_session_directory(self):
        r = run_cleanup(self.root, {"session_id": "sess-normal"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.session))
        self.assertArchiveIntact()

    def test_leaves_other_sessions_alone(self):
        other = os.path.join(self.root, "sess-other")
        os.makedirs(other)
        run_cleanup(self.root, {"session_id": "sess-normal"})
        self.assertTrue(os.path.isdir(other))

    def test_unknown_session_is_a_no_op(self):
        r = run_cleanup(self.root, {"session_id": "sess-never-existed"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(self.session))
        self.assertArchiveIntact()


class TestTraversalShapes(CleanupCase):
    """三種穿越寫法。`case "$DIR" in "$ROOT"/*)` 這類字面 glob 前綴比對
    擋不住它們：`"$ROOT/../../etc"` 字面上就是以 `"$ROOT/"` 開頭。腳本
    改成把路徑交給 python3 做 realpath 再比對前綴。"""

    def test_dotdot_escaping_the_root_deletes_nothing(self):
        rel = os.path.relpath(self.canary, self.root)
        r = run_cleanup(self.root, {"session_id": rel})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertCanaryIntact()

    def test_absolute_session_id_deletes_nothing(self):
        r = run_cleanup(self.root, {"session_id": self.canary})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertCanaryIntact()

    def test_dotdot_that_normalises_back_inside_is_still_the_session(self):
        """`sess-normal/../sess-normal` 正規化後還在存放區底下——不能
        因為字串裡有 `..` 就一律拒絕，那會變成另一種壞掉。"""
        r = run_cleanup(self.root, {"session_id": "sess-normal/../sess-normal"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.session))
        self.assertCanaryIntact()

    def test_root_itself_is_never_deleted(self):
        for sid in (".", "sess-normal/..", "./"):
            with self.subTest(sid):
                r = run_cleanup(self.root, {"session_id": sid})
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(os.path.isdir(self.root), f"deleted the root via {sid!r}")


class TestSymlinkIntoTheStore(CleanupCase):
    def test_session_id_that_is_a_symlink_out_of_the_store_deletes_nothing(self):
        link = os.path.join(self.root, "sess-link")
        os.symlink(self.canary, link)
        r = run_cleanup(self.root, {"session_id": "sess-link"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertCanaryIntact()


class TestArchiveIsNeverTouched(CleanupCase):
    def test_archive_as_the_session_id_is_refused(self):
        r = run_cleanup(self.root, {"session_id": "archive"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertArchiveIntact()

    def test_archive_reached_through_dotdot_is_refused(self):
        r = run_cleanup(self.root, {"session_id": "sess-normal/../archive"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertArchiveIntact()

    def test_old_archive_survives_the_seven_day_sweep(self):
        old = time.time() - 30 * 86400
        os.utime(self.archive, (old, old))
        r = run_cleanup(self.root, {"session_id": "sess-normal"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertArchiveIntact()


class TestEmptyAndMissingSessionIds(CleanupCase):
    def test_empty_session_id_deletes_nothing(self):
        r = run_cleanup(self.root, {"session_id": ""})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(self.session))
        self.assertArchiveIntact()

    def test_null_session_id_deletes_nothing(self):
        r = run_cleanup(self.root, {"session_id": None})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(self.session))

    def test_missing_key_deletes_nothing(self):
        r = run_cleanup(self.root, {"other": "field"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(self.session))

    def test_non_string_session_id_deletes_nothing(self):
        r = run_cleanup(self.root, {"session_id": 42})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(self.session))

    def test_unparseable_stdin_deletes_nothing_and_exits_zero(self):
        r = run_cleanup(self.root, "not json at all{")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(self.session))

    def test_empty_stdin_deletes_nothing_and_exits_zero(self):
        r = run_cleanup(self.root, "")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isdir(self.session))

    def test_missing_store_root_exits_zero(self):
        missing = os.path.join(self.root, "does-not-exist")
        r = run_cleanup(missing, {"session_id": "sess-normal"})
        self.assertEqual(r.returncode, 0, r.stderr)


class TestSevenDaySweep(CleanupCase):
    def test_sweeps_stale_session_dirs(self):
        stale = os.path.join(self.root, "sess-stale")
        os.makedirs(stale)
        old = time.time() - 30 * 86400
        os.utime(stale, (old, old))
        r = run_cleanup(self.root, {"session_id": "sess-normal"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(stale))

    def test_keeps_recent_session_dirs(self):
        recent = os.path.join(self.root, "sess-recent")
        os.makedirs(recent)
        run_cleanup(self.root, {"session_id": "sess-normal"})
        self.assertTrue(os.path.isdir(recent))

    def test_a_stale_symlink_out_of_the_store_is_not_followed(self):
        """存放區底下混進一個指到外面的舊符號連結時，7 天掃除不能把
        rm -rf 的目標帶出根目錄。find 沒有 -L，符號連結的型別是 l 不是 d，
        天生被 -type d 排除。"""
        link = os.path.join(self.root, "sess-stale-link")
        os.symlink(self.canary, link)
        old = time.time() - 30 * 86400
        os.utime(link, (old, old), follow_symlinks=False)
        os.utime(self.canary, (old, old))
        r = run_cleanup(self.root, {"session_id": "sess-normal"})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertCanaryIntact()

    def test_sweep_does_not_recurse_into_session_dirs(self):
        """-maxdepth 1 只看根目錄的直接子項。session 目錄底下一個很舊的
        子目錄不該被單獨挑出來刪（那會在一個還活著的 session 底下挖洞）。"""
        nested = os.path.join(self.session, "nested-old")
        os.makedirs(nested)
        old = time.time() - 30 * 86400
        os.utime(nested, (old, old))
        run_cleanup(self.root, {"session_id": "sess-other-session"})
        self.assertTrue(os.path.isdir(nested))


class TestTheseTestsCanActuallyFail(CleanupCase):
    """上面那批對現在這一版腳本是綠的，所以要證明它們不是永遠不會紅。

    把正規化那一步換掉，改成腳本自己 docstring 點名擋不住的字面 glob
    前綴比對版本，同一批穿越測試必須紅——這是 C2 那條教訓的直接應用：
    一個不可能失敗的測試，本身就是要防的東西。"""

    def _naive_script(self):
        """`case "$DIR" in "$ROOT"/*)` 版本：字面上 "$ROOT/../../x" 就是
        以 "$ROOT/" 開頭，glob 會匹配，但正規化後其實在存放區外面。"""
        path = os.path.join(tempfile.mkdtemp(), "naive-cleanup.sh")
        with open(path, "w") as fh:
            fh.write(
                '#!/usr/bin/env bash\n'
                'set -euo pipefail\n'
                'ROOT="${TOOL_REDUCE_HOME:-$HOME/.claude/tool-reduce}"\n'
                'SID="$(python3 -c \'import json,sys\n'
                'try: p=json.load(sys.stdin)\n'
                'except Exception: p={}\n'
                'print(p.get("session_id") or "")\' 2>/dev/null)" || true\n'
                '[[ -n "$SID" ]] || exit 0\n'
                'DIR="$ROOT/$SID"\n'
                'case "$DIR" in\n'
                '  "$ROOT"/*) [[ -d "$DIR" ]] && rm -rf -- "$DIR" ;;\n'
                'esac\n'
                'exit 0\n')
        return path

    def test_the_naive_script_really_does_escape(self):
        rel = os.path.relpath(self.canary, self.root)
        run_cleanup(self.root, {"session_id": rel}, script=self._naive_script())
        self.assertFalse(
            os.path.isdir(self.canary),
            "the naive glob-prefix script was expected to escape the store; "
            "if it did not, the traversal tests above prove nothing")

    def test_the_real_script_does_not(self):
        rel = os.path.relpath(self.canary, self.root)
        run_cleanup(self.root, {"session_id": rel})
        self.assertCanaryIntact()


if __name__ == "__main__":
    unittest.main()
