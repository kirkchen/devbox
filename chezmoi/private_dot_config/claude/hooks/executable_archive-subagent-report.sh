#!/bin/bash
# SubagentStop: 把 subagent 的最終報告存下來，供 model router 事後覆盤與標註。
#
# 為什麼需要：Claude Code 的 transcript 只留 dispatch 跟用量統計，
# subagent 實際交出的內容在 session 結束後就消失（實測 204 筆歷史 dispatch
# 只剩 2 筆可還原）。沒有產出就無法判斷「這個模型選得對不對」。
#
# 用 agent_id 當檔名；tool_use_id -> agentId 的對應在主 transcript 的
# toolUseResult.agentId，覆盤時由 outcomes.py 接回去。
#
# 開關：ARCHIVE_SUBAGENT_REPORTS=1 才動作，預設不啟用。
set -uo pipefail

CONF="$HOME/.config/claude/typesafe.env"
# shellcheck source=/dev/null
[[ -f "$CONF" ]] && . "$CONF"
[[ "${ARCHIVE_SUBAGENT_REPORTS:-0}" == "1" ]] || exit 0

R="${ROUTER_HOME:-$HOME/.config/claude/model-router}"
DIR="${SUBAGENT_REPORT_DIR:-$HOME/.local/share/model-router-eval/reports}"
mkdir -p "$DIR" 2>/dev/null || exit 0

INPUT=$(cat)
AGENT_ID=$(jq -r '.agent_id // empty' <<<"$INPUT" 2>/dev/null)
AGENT_TYPE=$(jq -r '.agent_type // empty' <<<"$INPUT" 2>/dev/null)
[[ -n "$AGENT_ID" ]] || exit 0
# agent_type 為空代表這不是一次 subagent dispatch，存下來只是垃圾
[[ -n "$AGENT_TYPE" ]] || exit 0

# eval-judge 是標註用的 agent，判它自己會污染 corpus
[[ "$AGENT_TYPE" == "eval-judge" ]] && exit 0

# 報告與當初的 dispatch prompt 都在 subagent transcript 裡，而那個檔案 session 結束
# 後會被清掉，事後撈不到，所以要在這裡存下來。
#
# 報告**不是** `last_assistant_message`：subagent 用 SubagentHandback 把報告交回
# caller，那個欄位只留下收尾句（實測大量是 `Report delivered.`，17 字元）。萃取邏輯
# 與 judge hook 共用 transcript.py，兩邊各寫一份 jq 正是這個 bug 的來源。
TPATH=$(jq -r '.agent_transcript_path // empty' <<<"$INPUT" 2>/dev/null)
EX=$(python3 "$R/transcript.py" "$TPATH" 2>/dev/null)
REQUEST=$(jq -r '.request // ""'      <<<"$EX" 2>/dev/null)
REPORT=$(jq -r '.report // ""'        <<<"$EX" 2>/dev/null)
SOURCE=$(jq -r '.report_source // ""' <<<"$EX" 2>/dev/null)
# transcript.py 還沒部署、或 agent 沒走 handback 就結束：退回舊欄位，別把整筆丟掉。
if [[ -z "$REPORT" ]]; then
  REPORT=$(jq -r '.last_assistant_message // ""' <<<"$INPUT" 2>/dev/null)
  SOURCE="last_message"
fi

jq -c --arg req "$REQUEST" --arg rep "$REPORT" --arg src "$SOURCE" '{
  agent_id, agent_type, session_id, cwd,
  ts: (now | todate),
  request: $req,
  request_chars: ($req | length),
  report: $rep,
  report_chars: ($rep | length),
  report_source: $src,
  agent_transcript_path
}' <<<"$INPUT" > "$DIR/$AGENT_ID.json" 2>/dev/null || exit 0

# 保留最近 2000 份，避免無限增長
ls -t "$DIR"/*.json 2>/dev/null | tail -n +2001 | xargs -r rm -f
exit 0
