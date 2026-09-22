# tests/python/test_transcript.py
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest

BASE = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
MODULE_PATH = os.path.join(
    BASE, "chezmoi/private_dot_config/claude/model-router/executable_transcript.py")

_spec = importlib.util.spec_from_file_location("transcript", MODULE_PATH)
transcript = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(transcript)


def _rec(type_, content):
    return {"type": type_, "message": {"content": content}}


def _write_transcript(tmpdir, records, name="agent.jsonl"):
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return path


class TestHandbackReport(unittest.TestCase):
    """報告是 SubagentHandback 交回去的，不是 transcript 最後那句話。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_strips_surrounding_whitespace_so_bash_and_python_agree(self):
        # bash 的 $(...) 會吃掉結尾換行，來源不正規化的話兩種用法長度會對不起來。
        path = _write_transcript(self.tmp.name, [
            _rec("assistant", [{"type": "tool_use", "name": "SubagentHandback",
                               "input": {"message": "\n  The report.\n\n"}}]),
        ])
        self.assertEqual(transcript.handback_report(path), "The report.")

    def test_returns_the_handback_message_not_the_closing_line(self):
        # 這就是線上那個 bug 的形狀：收尾句 17 字元，真報告 10k 字元。
        report = ("## Findings\n" + ("一個實際的發現。\n" * 500)).strip()
        path = _write_transcript(self.tmp.name, [
            _rec("user", [{"type": "text", "text": "Review the thing."}]),
            _rec("assistant", [{"type": "tool_use", "name": "SubagentHandback",
                               "input": {"message": report}}]),
            _rec("user", [{"type": "tool_result",
                          "content": [{"type": "text", "text": '{"success":true}'}]}]),
            _rec("assistant", [{"type": "text", "text": "Report delivered."}]),
        ])
        self.assertEqual(transcript.handback_report(path), report)

    def test_returns_empty_when_the_agent_never_handed_back(self):
        path = _write_transcript(self.tmp.name, [
            _rec("user", [{"type": "text", "text": "Do the thing."}]),
            _rec("assistant", [{"type": "text", "text": "I could not."}]),
        ])
        self.assertEqual(transcript.handback_report(path), "")

    def test_returns_the_last_handback_when_the_agent_handed_back_twice(self):
        path = _write_transcript(self.tmp.name, [
            _rec("assistant", [{"type": "tool_use", "name": "SubagentHandback",
                               "input": {"message": "first"}}]),
            _rec("assistant", [{"type": "tool_use", "name": "SubagentHandback",
                               "input": {"message": "second"}}]),
        ])
        self.assertEqual(transcript.handback_report(path), "second")

    def test_ignores_other_tool_calls_that_carry_a_message_field(self):
        path = _write_transcript(self.tmp.name, [
            _rec("assistant", [{"type": "tool_use", "name": "Bash",
                               "input": {"message": "not the report"}}]),
        ])
        self.assertEqual(transcript.handback_report(path), "")

    def test_skips_malformed_lines(self):
        path = os.path.join(self.tmp.name, "broken.jsonl")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("{not json\n")
            fh.write(json.dumps(_rec("assistant", [
                {"type": "tool_use", "name": "SubagentHandback",
                 "input": {"message": "survived"}}])) + "\n")
        self.assertEqual(transcript.handback_report(path), "survived")

    def test_missing_file_returns_empty(self):
        self.assertEqual(
            transcript.handback_report(os.path.join(self.tmp.name, "nope.jsonl")), "")


class TestDispatchRequest(unittest.TestCase):
    """dispatch prompt = subagent transcript 的第一則 user 訊息。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_returns_the_first_user_message(self):
        path = _write_transcript(self.tmp.name, [
            _rec("user", [{"type": "text", "text": "The dispatch prompt."}]),
            _rec("assistant", [{"type": "text", "text": "ok"}]),
            _rec("user", [{"type": "text", "text": "A later turn."}]),
        ])
        self.assertEqual(transcript.dispatch_request(path), "The dispatch prompt.")

    def test_handles_content_given_as_a_plain_string(self):
        path = _write_transcript(self.tmp.name, [_rec("user", "Plain string prompt.")])
        self.assertEqual(transcript.dispatch_request(path), "Plain string prompt.")

    def test_joins_several_text_blocks(self):
        path = _write_transcript(self.tmp.name, [
            _rec("user", [{"type": "text", "text": "first"},
                          {"type": "text", "text": "second"}]),
        ])
        self.assertEqual(transcript.dispatch_request(path), "first\nsecond")

    def test_strips_the_whole_system_reminder_block_not_just_its_first_line(self):
        path = _write_transcript(self.tmp.name, [
            _rec("user", [{"type": "text", "text":
                           "Real prompt.\n<system-reminder>\nnoise line\nmore noise\n"
                           "</system-reminder>\nTail."}]),
        ])
        self.assertEqual(transcript.dispatch_request(path), "Real prompt.\n\nTail.")

    def test_strips_an_unterminated_system_reminder(self):
        path = _write_transcript(self.tmp.name, [
            _rec("user", [{"type": "text", "text":
                           "Real prompt.\n<system-reminder>\ndangling noise"}]),
        ])
        self.assertEqual(transcript.dispatch_request(path), "Real prompt.")

    def test_missing_file_returns_empty(self):
        self.assertEqual(
            transcript.dispatch_request(os.path.join(self.tmp.name, "nope.jsonl")), "")


class TestCommandLine(unittest.TestCase):
    """兩支 bash hook 靠這個 CLI 取值，所以輸出形狀要鎖住。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self, path):
        out = subprocess.run([sys.executable, MODULE_PATH, path],
                             capture_output=True, text=True, check=True)
        return json.loads(out.stdout)

    def test_emits_request_report_and_source(self):
        path = _write_transcript(self.tmp.name, [
            _rec("user", [{"type": "text", "text": "Prompt."}]),
            _rec("assistant", [{"type": "tool_use", "name": "SubagentHandback",
                               "input": {"message": "The report."}}]),
            _rec("assistant", [{"type": "text", "text": "Report delivered."}]),
        ])
        got = self._run(path)
        self.assertEqual(got["request"], "Prompt.")
        self.assertEqual(got["report"], "The report.")
        self.assertEqual(got["report_source"], "handback")

    def test_reports_no_source_when_there_is_no_handback(self):
        path = _write_transcript(self.tmp.name, [
            _rec("user", [{"type": "text", "text": "Prompt."}]),
        ])
        got = self._run(path)
        self.assertEqual(got["report"], "")
        self.assertEqual(got["report_source"], "")

    def test_missing_file_still_emits_valid_json(self):
        got = self._run(os.path.join(self.tmp.name, "nope.jsonl"))
        self.assertEqual(got, {"request": "", "report": "", "report_source": ""})


if __name__ == "__main__":
    unittest.main()
