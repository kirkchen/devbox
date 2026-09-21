"""每個工具的 tool_response 形狀：把要過濾的文字讀出來、把過濾後的文字寫回去。

形狀是 PostToolUse hook 的 updatedToolOutput 必須符合的契約。Claude Code 會驗證，
不符就記錄 "does not match <tool>'s output shape" 並改用原輸出（fail-safe，不會爆）。

Bash 與 Read 的形狀已用 2026-09-21 的即時探針驗證過（見
docs/superpowers/specs/2026-09-21-tool-result-reduce-design.md 2.5 節）：

- Bash 的 tool_response 是扁平 dict：
  ``{"stdout": str, "stderr": str, "interrupted": bool, "isImage": bool,
  "noOutputExpected": bool}``。文字欄位是 ``stdout``，改寫時原樣保留其他欄位即被接受。

- Read 的 tool_response 是巢狀 dict，**不是**扁平字串欄位：
  ``{"type": "text", "file": {"filePath": str, "content": str, "numLines": int,
  "startLine": int, "totalLines": int}}``。文字在 ``file.content``，不是頂層的
  ``content``/``text``/``file``（``file`` 本身是 dict，不是字串）。這點與寫這份檔案前
  依 transcript 猜測的版本不同，以探針實測為準。改寫時要保留 ``type`` 與 ``file`` 底下
  其他欄位（``filePath``、``numLines``、``startLine``、``totalLines``），只換
  ``file.content``，同樣被接受。

WebFetch、WebSearch 與其他 MCP 工具尚未用探針驗證，沿用先前依 transcript 觀察寫的
猜測形狀（扁平字串欄位），之後任務若要用到這些工具要重新驗證。
"""

# 工具名 -> 依序嘗試的頂層文字欄位。Read 走獨立的巢狀路徑，不查這個表。
TEXT_FIELDS = {
    "Bash": ("stdout",),
    "WebFetch": ("content", "text"),
    "WebSearch": ("content", "text"),
}
FALLBACK_FIELDS = ("content", "text", "result", "results", "output", "stdout")


def _fields(tool_name):
    return TEXT_FIELDS.get(tool_name, FALLBACK_FIELDS)


def _read_file_content(tool_response):
    """回傳 Read 巢狀 tool_response 裡的 file dict，取不出來回 None。"""
    file = tool_response.get("file")
    if isinstance(file, dict) and isinstance(file.get("content"), str):
        return file
    return None


def extract(tool_name, tool_response):
    """回傳要過濾的文字，取不出來回 None。"""
    if isinstance(tool_response, str):
        return tool_response
    if not isinstance(tool_response, dict):
        return None
    if tool_name == "Read":
        file = _read_file_content(tool_response)
        if file is not None and file["content"]:
            return file["content"]
        return None
    for k in _fields(tool_name):
        v = tool_response.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def rewrite(tool_name, tool_response, new_text):
    """回傳與原本同形狀、只換掉文字欄位的物件。找不到欄位就原樣回傳。"""
    if isinstance(tool_response, str):
        return new_text
    if not isinstance(tool_response, dict):
        return tool_response
    if tool_name == "Read":
        file = _read_file_content(tool_response)
        if file is not None and file["content"]:
            out = dict(tool_response)
            out["file"] = dict(file)
            out["file"]["content"] = new_text
            return out
        return tool_response
    for k in _fields(tool_name):
        if isinstance(tool_response.get(k), str) and tool_response[k]:
            out = dict(tool_response)
            out[k] = new_text
            return out
    return tool_response
