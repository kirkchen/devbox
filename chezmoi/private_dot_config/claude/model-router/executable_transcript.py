#!/usr/bin/env python3
"""從 subagent transcript 取出 dispatch prompt 與實際交回的報告。

為什麼需要這個模組：SubagentStop 事件的 `last_assistant_message` **不是**報告。
subagent 是透過 `SubagentHandback` 這個 tool call 把報告交回 caller 的，交完之後
在自己的 transcript 留一句收尾話（實測大量是字串 `Report delivered.`，17 字元）。
拿那句話當產出去評分，等於在評一句「我交了」。

兩支 SubagentStop hook（judge 與 archiver）都要同一份萃取邏輯，各寫一份 jq 就是
這個 bug 的來源，所以放在這裡，並且有測試（tests/python/test_transcript.py）。

可以 import，也可以當 CLI 給 bash hook 用：

    transcript.py <agent_transcript_path>
    → {"request": ..., "report": ..., "report_source": "handback"|""}
"""
import json
import re
import sys

HANDBACK_TOOL = "SubagentHandback"
# system-reminder 是注入的內容，不是使用者寫的 prompt，整塊拿掉（含沒有收尾標籤的情況）。
_SYSTEM_REMINDER = re.compile(r"<system-reminder>.*?(?:</system-reminder>|\Z)", re.S)


def _numbered_records(path):
    """yield (行號, JSON 記錄)。行號含壞行與空行，才對得回原檔的位置。"""
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return
    with fh:
        for index, line in enumerate(fh):
            line = line.strip()
            if not line:
                continue
            try:
                yield index, json.loads(line)
            except ValueError:
                continue


def _records(path):
    """逐行 yield transcript 的 JSON 記錄，壞行跳過。"""
    for _, record in _numbered_records(path):
        yield record


def _blocks(record):
    content = (record.get("message") or {}).get("content")
    return content if isinstance(content, list) else []


def _is_handback(record):
    return any(isinstance(b, dict)
               and b.get("type") == "tool_use"
               and b.get("name") == HANDBACK_TOOL
               for b in _blocks(record))


def handback_positions(path):
    """每一次 SubagentHandback 所在的行號（0 起算）。

    一個 agent 可以交回不只一次，SubagentStop 每次交回各觸發一次 hook。回填要重現
    「那一次交回當下」的 transcript 狀態，就得知道每次交回停在哪一行。
    """
    return [index for index, record in _numbered_records(path) if _is_handback(record)]


def handback_report(path):
    """最後一次 SubagentHandback 交回的報告；沒有就回空字串。

    取最後一次而非第一次：agent 可能交回後被追問再交一次，最後那份才是定案。

    回傳前 strip：報告的頭尾空白沒有意義，而 bash 的 `$(...)` 本來就會吃掉結尾換行。
    在來源就正規化，import 用跟 CLI 用才會拿到同一個值，長度統計也才對得起來。
    """
    report = ""
    for record in _records(path):
        for block in _blocks(record):
            if (isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") == HANDBACK_TOOL):
                report = (block.get("input") or {}).get("message") or ""
    return report.strip()


def dispatch_request(path):
    """當初的 dispatch prompt = transcript 第一則 user 訊息，去掉 system-reminder。"""
    for record in _records(path):
        if record.get("type") != "user":
            continue
        content = (record.get("message") or {}).get("content")
        if isinstance(content, str):
            text = content
        else:
            text = "\n".join(
                b.get("text") or "" for b in _blocks(record)
                if isinstance(b, dict) and b.get("type") == "text")
        return _SYSTEM_REMINDER.sub("", text).strip()
    return ""


def main(argv):
    path = argv[1] if len(argv) > 1 else ""
    report = handback_report(path)
    json.dump({"request": dispatch_request(path),
               "report": report,
               "report_source": "handback" if report else ""},
              sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
