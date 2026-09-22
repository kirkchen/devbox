# tests/python/test_backfill.py
"""backfill_corpus.py：用真報告重建 corpus 與存檔。

重建走的是「合成一份 SubagentStop payload、餵給那兩支 hook」，不是另外實作一次
評分。所以這裡測的是選樣、payload 形狀、以及換檔時的保底，不重測評分邏輯。
"""
import importlib.util
import json
import os
import stat
import tempfile
import unittest

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
MODULE_PATH = os.path.join(
    BASE, "chezmoi/private_dot_config/claude/model-router/executable_backfill_corpus.py")

_spec = importlib.util.spec_from_file_location("backfill", MODULE_PATH)
backfill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(backfill)


class TestFindTranscript(unittest.TestCase):
    """corpus 只存 agent_id，transcript 要自己從 projects 樹裡找回來。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.projects = os.path.join(self.tmp.name, "projects")

    def _make(self, project, session, agent_id):
        d = os.path.join(self.projects, project, session, "subagents")
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "agent-%s.jsonl" % agent_id)
        open(path, "w").close()
        return path

    def test_finds_the_transcript_by_agent_id(self):
        want = self._make("proj-a", "sess-1", "abc123")
        self.assertEqual(backfill.find_transcript("abc123", self.projects), want)

    def test_returns_none_when_the_transcript_is_gone(self):
        self._make("proj-a", "sess-1", "abc123")
        self.assertIsNone(backfill.find_transcript("missing", self.projects))

    def test_does_not_confuse_an_agent_id_that_is_a_prefix_of_another(self):
        self._make("proj-a", "sess-1", "abc123456")
        self.assertIsNone(backfill.find_transcript("abc123", self.projects))


class TestBuildPayload(unittest.TestCase):
    """合成的 payload 要長得跟 Claude Code 真的送進 SubagentStop 的一樣。"""

    def test_carries_the_identity_fields_from_the_corpus_row(self):
        row = {"agent_id": "a1", "agent_type": "Explore",
               "session_id": "s1", "cwd": "/tmp/project"}
        got = backfill.build_payload(row, "/path/agent-a1.jsonl", "Report delivered.")
        self.assertEqual(got["agent_id"], "a1")
        self.assertEqual(got["agent_type"], "Explore")
        self.assertEqual(got["session_id"], "s1")
        self.assertEqual(got["cwd"], "/tmp/project")
        self.assertEqual(got["agent_transcript_path"], "/path/agent-a1.jsonl")
        self.assertEqual(got["last_assistant_message"], "Report delivered.")

    def test_missing_optional_fields_become_empty_not_absent(self):
        got = backfill.build_payload({"agent_id": "a1"}, "/p.jsonl", "")
        self.assertEqual(got["session_id"], "")
        self.assertEqual(got["cwd"], "")


class TestCommit(unittest.TestCase):
    """換檔一定要留得回去：原檔備份，備份不覆蓋。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = os.path.join(self.tmp.name, "corpus.jsonl")
        with open(self.target, "w", encoding="utf-8") as fh:
            fh.write('{"old": true}\n')
        self.replacement = os.path.join(self.tmp.name, "new.jsonl")
        with open(self.replacement, "w", encoding="utf-8") as fh:
            fh.write('{"new": true}\n')

    def test_replaces_the_target_and_keeps_the_original_as_backup(self):
        backup = backfill.commit(self.replacement, self.target)
        with open(self.target, encoding="utf-8") as fh:
            self.assertEqual(json.loads(fh.read()), {"new": True})
        with open(backup, encoding="utf-8") as fh:
            self.assertEqual(json.loads(fh.read()), {"old": True})

    def test_does_not_clobber_an_existing_backup(self):
        first = backfill.commit(self.replacement, self.target)
        with open(self.replacement, "w", encoding="utf-8") as fh:
            fh.write('{"newer": true}\n')
        second = backfill.commit(self.replacement, self.target)
        self.assertNotEqual(first, second)
        with open(first, encoding="utf-8") as fh:
            self.assertEqual(json.loads(fh.read()), {"old": True})

    def test_commits_when_there_is_no_existing_target(self):
        fresh = os.path.join(self.tmp.name, "absent.jsonl")
        self.assertIsNone(backfill.commit(self.replacement, fresh))
        self.assertTrue(os.path.exists(fresh))


class TestMergeLateRows(unittest.TestCase):
    """hook 是全域的：重建期間別的 session 可能把新列 append 進來，不能換檔換掉。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.target = os.path.join(self.tmp.name, "corpus.jsonl")

    def _write(self, path, rows):
        with open(path, "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps(r) + "\n")

    def test_keeps_a_row_appended_while_the_backfill_was_running(self):
        # 開跑時讀到只有 a1；跑到一半別的 session 補了 a9。
        self._write(self.target, [{"agent_id": "a1"}, {"agent_id": "a9"}])
        merged = backfill.merge_rows(original=[{"agent_id": "a1"}],
                                     rebuilt=[{"agent_id": "a1", "new": True}],
                                     target=self.target)
        ids = [r["agent_id"] for r in merged]
        self.assertIn("a9", ids)
        self.assertEqual([r for r in merged if r["agent_id"] == "a1"],
                         [{"agent_id": "a1", "new": True}])

    def test_replaces_a_rebuilt_row_rather_than_duplicating_it(self):
        self._write(self.target, [{"agent_id": "a1"}])
        merged = backfill.merge_rows(original=[{"agent_id": "a1"}],
                                     rebuilt=[{"agent_id": "a1", "new": True}],
                                     target=self.target)
        self.assertEqual(merged, [{"agent_id": "a1", "new": True}])

    def test_keeps_a_stale_row_that_was_not_rebuilt_this_run(self):
        # --limit 或 hook 沒產出時，沒處理到的舊列必須原樣留著，不能被換掉的檔案吃掉。
        self._write(self.target, [{"agent_id": "a1"}, {"agent_id": "a2"}])
        merged = backfill.merge_rows(
            original=[{"agent_id": "a1"}, {"agent_id": "a2"}],
            rebuilt=[{"agent_id": "a1", "new": True}], target=self.target)
        self.assertEqual(sorted(r["agent_id"] for r in merged), ["a1", "a2"])
        self.assertIn({"agent_id": "a2"}, merged)


class TestRebuild(unittest.TestCase):
    """跑 hook 的那一段。用 stub hook 取代真的 hook，不打網路。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.projects = os.path.join(self.tmp.name, "projects")
        d = os.path.join(self.projects, "proj", "sess", "subagents")
        os.makedirs(d)
        self.tpath = os.path.join(d, "agent-a1.jsonl")
        open(self.tpath, "w").close()
        self.out = os.path.join(self.tmp.name, "out.jsonl")

    def _stub_hook(self, body):
        path = os.path.join(self.tmp.name, "stub.sh")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/bash\n" + body)
        os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC)
        return path

    def test_counts_a_row_as_rebuilt_when_the_hook_appends_it(self):
        hook = self._stub_hook(
            'INPUT=$(cat)\n'
            'printf \'{"agent_id":"a1","layer":1}\\n\' >> "$EVAL_CORPUS"\n')
        summary = backfill.rebuild([{"agent_id": "a1"}], self.projects,
                                   judge_hook=hook, corpus_out=self.out)
        self.assertEqual(summary["rebuilt"], 1)
        self.assertEqual(summary["no_transcript"], 0)
        self.assertEqual(summary["hook_produced_nothing"], 0)

    def test_counts_a_row_the_hook_silently_dropped(self):
        hook = self._stub_hook("cat >/dev/null\n")
        summary = backfill.rebuild([{"agent_id": "a1"}], self.projects,
                                   judge_hook=hook, corpus_out=self.out)
        self.assertEqual(summary["rebuilt"], 0)
        self.assertEqual(summary["hook_produced_nothing"], 1)

    def test_skips_rows_whose_transcript_is_gone(self):
        hook = self._stub_hook(
            'cat >/dev/null\n'
            'printf \'{"agent_id":"x"}\\n\' >> "$EVAL_CORPUS"\n')
        summary = backfill.rebuild([{"agent_id": "vanished"}], self.projects,
                                   judge_hook=hook, corpus_out=self.out)
        self.assertEqual(summary["no_transcript"], 1)
        self.assertEqual(summary["rebuilt"], 0)
        self.assertFalse(os.path.exists(self.out))

    def test_feeds_the_hook_a_payload_naming_the_transcript(self):
        seen = os.path.join(self.tmp.name, "seen.json")
        hook = self._stub_hook(
            'cat > "%s"\n'
            'printf \'{"agent_id":"a1"}\\n\' >> "$EVAL_CORPUS"\n' % seen)
        backfill.rebuild([{"agent_id": "a1", "agent_type": "Explore"}], self.projects,
                         judge_hook=hook, corpus_out=self.out)
        with open(seen, encoding="utf-8") as fh:
            payload = json.load(fh)
        self.assertEqual(payload["agent_transcript_path"], self.tpath)
        self.assertEqual(payload["agent_type"], "Explore")


if __name__ == "__main__":
    unittest.main()
