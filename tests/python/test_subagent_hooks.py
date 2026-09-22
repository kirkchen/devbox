# tests/python/test_subagent_hooks.py
"""兩支 SubagentStop hook 的端對端測試。

bug 出在 bash glue（取錯欄位），不在萃取邏輯，所以這裡直接餵 hook 一份
SubagentStop payload 加一份 transcript，斷言存下來的是 SubagentHandback 交回的
報告，不是 `last_assistant_message` 那句收尾話。
"""
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
CHEZMOI = os.path.join(BASE, "chezmoi/private_dot_config/claude")
ARCHIVE_HOOK = os.path.join(CHEZMOI, "hooks/executable_archive-subagent-report.sh")
JUDGE_HOOK = os.path.join(CHEZMOI, "hooks/executable_judge-subagent-output.sh")
ROUTER_SRC = os.path.join(CHEZMOI, "model-router")

REPORT = ("## Findings\n" + ("一個實際的發現，長到不可能是收尾句。\n" * 40)).strip()
CLOSING_LINE = "Report delivered."


class SubagentHookHarness(unittest.TestCase):
    """把 chezmoi 來源佈署成 hook 執行期看到的樣子（`executable_` 前綴會被剝掉）。"""

    hook_under_test = None

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.router = os.path.join(self.tmp.name, "model-router")
        self.reports = os.path.join(self.tmp.name, "reports")
        # ROUTER_HOME 之外也佈一份到 $HOME 的預設路徑，這樣 hook 有沒有吃
        # ROUTER_HOME 都找得到 questions，測試失敗就一定是欄位取錯、不是檔案沒找到。
        self.home_router = os.path.join(self.home, ".config/claude/model-router")
        os.makedirs(self.home_router)
        os.makedirs(self.router)
        for target in (self.router, self.home_router):
            shutil.copy(os.path.join(ROUTER_SRC, "executable_transcript.py"),
                        os.path.join(target, "transcript.py"))
            shutil.copy(os.path.join(ROUTER_SRC, "completeness_questions.json"), target)
        self.corpus = os.path.join(self.tmp.name, "corpus.jsonl")

    def write_transcript(self, records, name="agent.jsonl"):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as fh:
            for r in records:
                fh.write(json.dumps(r) + "\n")
        return path

    def handback_transcript(self):
        """真實形狀：報告走 SubagentHandback，transcript 最後只剩一句收尾話。"""
        return self.write_transcript([
            {"type": "user", "message": {"content": [
                {"type": "text", "text": "Review the thing."}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "SubagentHandback",
                 "input": {"message": REPORT}}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": CLOSING_LINE}]}},
        ])

    def payload(self, tpath, agent_id="a1", agent_type="general-purpose"):
        return json.dumps({
            "agent_id": agent_id,
            "agent_type": agent_type,
            "session_id": "s1",
            "cwd": "/tmp/project",
            "agent_transcript_path": tpath,
            "last_assistant_message": CLOSING_LINE,
        })

    def env(self, **extra):
        env = dict(os.environ)
        env.update({
            "HOME": self.home,
            "ROUTER_HOME": self.router,
            "SUBAGENT_REPORT_DIR": self.reports,
            "EVAL_CORPUS": self.corpus,
            "ARCHIVE_SUBAGENT_REPORTS": "1",
            "JUDGE_SUBAGENT_OUTPUT": "1",
        })
        env.update(extra)
        return env

    def run_hook(self, hook, payload, **env_extra):
        return subprocess.run(["bash", hook], input=payload, capture_output=True,
                              text=True, env=self.env(**env_extra))


class TestArchiveHook(SubagentHookHarness):

    def archived(self, agent_id="a1"):
        with open(os.path.join(self.reports, agent_id + ".json"), encoding="utf-8") as fh:
            return json.load(fh)

    def test_archives_the_handback_report_not_the_closing_line(self):
        self.run_hook(ARCHIVE_HOOK, self.payload(self.handback_transcript()))
        got = self.archived()
        self.assertEqual(got["report"], REPORT)
        self.assertEqual(got["report_chars"], len(REPORT))
        self.assertEqual(got["report_source"], "handback")

    def test_archives_the_dispatch_prompt(self):
        self.run_hook(ARCHIVE_HOOK, self.payload(self.handback_transcript()))
        self.assertEqual(self.archived()["request"], "Review the thing.")

    def test_falls_back_to_the_last_message_when_there_is_no_handback(self):
        tpath = self.write_transcript([
            {"type": "user", "message": {"content": [
                {"type": "text", "text": "Do it."}]}},
        ])
        self.run_hook(ARCHIVE_HOOK, self.payload(tpath))
        got = self.archived()
        self.assertEqual(got["report"], CLOSING_LINE)
        self.assertEqual(got["report_source"], "last_message")

    def test_skips_the_eval_judge_agent(self):
        self.run_hook(ARCHIVE_HOOK,
                      self.payload(self.handback_transcript(), agent_type="eval-judge"))
        self.assertFalse(os.path.exists(os.path.join(self.reports, "a1.json")))


class TestJudgeHook(SubagentHookHarness):
    """用 PATH 上的假 curl 擋掉網路，斷言真正送進 Jev 的 output 是什麼。"""

    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.tmp.name, "bin")
        os.makedirs(self.bin)
        self.captured = os.path.join(self.tmp.name, "jev-request.json")
        fake_curl = os.path.join(self.bin, "curl")
        with open(fake_curl, "w", encoding="utf-8") as fh:
            fh.write(
                "#!/bin/bash\n"
                "# 最後一個參數是 -d 的 body；存下來供斷言。\n"
                'for a in "$@"; do prev=$cur; cur=$a; done\n'
                'printf "%%s" "$cur" > "%s"\n'
                'cat <<\'JSON\'\n'
                '{"answers":{"addressed_everything":{"noul":0.9},'
                '"signs_of_incompleteness":{"noul":0.1},'
                '"refused_or_blocked":{"noul":0.05},'
                '"output_depth":{"score":1.5,"confidence":0.9}}}\n'
                'JSON\n' % self.captured)
        os.chmod(fake_curl, os.stat(fake_curl).st_mode | stat.S_IEXEC)

    def env(self, **extra):
        env = super().env(**extra)
        env["PATH"] = self.bin + os.pathsep + env["PATH"]
        env["TYPESAFE_API_KEY"] = "test-key-not-a-real-secret"
        return env

    def corpus_rows(self):
        with open(self.corpus, encoding="utf-8") as fh:
            return [json.loads(l) for l in fh if l.strip()]

    def test_sends_the_handback_report_to_jev_not_the_closing_line(self):
        self.run_hook(JUDGE_HOOK, self.payload(self.handback_transcript()))
        with open(self.captured, encoding="utf-8") as fh:
            sent = json.load(fh)
        self.assertEqual(sent["state"]["output"], REPORT)

    def test_records_the_real_output_length_and_source(self):
        self.run_hook(JUDGE_HOOK, self.payload(self.handback_transcript()))
        rows = self.corpus_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["output_chars"], len(REPORT))
        self.assertEqual(rows[0]["report_source"], "handback")

    def test_skips_the_eval_judge_agent(self):
        self.run_hook(JUDGE_HOOK,
                      self.payload(self.handback_transcript(), agent_type="eval-judge"))
        self.assertFalse(os.path.exists(self.corpus))


if __name__ == "__main__":
    unittest.main()
