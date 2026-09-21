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

DIR="${SUBAGENT_REPORT_DIR:-$HOME/.local/share/model-router-eval/reports}"
mkdir -p "$DIR" 2>/dev/null || exit 0

INPUT=$(cat)
AGENT_ID=$(jq -r '.agent_id // empty' <<<"$INPUT" 2>/dev/null)
[[ -n "$AGENT_ID" ]] || exit 0

# eval-judge 是標註用的 agent，判它自己會污染 corpus
[[ "$(jq -r '.agent_type // empty' <<<"$INPUT" 2>/dev/null)" == "eval-judge" ]] && exit 0

# 也把當初的 dispatch prompt 存下來：它在 subagent transcript 的第一則 user 訊息，
# 而那個檔案 session 結束後會被清掉，事後撈不到。
TPATH=$(jq -r '.agent_transcript_path // empty' <<<"$INPUT" 2>/dev/null)
REQUEST=""
if [[ -f "$TPATH" ]]; then
  REQUEST=$(jq -rs '[.[] | select(.type=="user") | .message.content
                     | if type=="string" then . else (map(select(.type=="text").text) | join("\n")) end][0] // ""' \
            "$TPATH" 2>/dev/null | sed 's/<system-reminder>.*//')
fi

jq -c --arg req "$REQUEST" '{
  agent_id, agent_type, session_id, cwd,
  ts: (now | todate),
  request: $req,
  request_chars: ($req | length),
  report: (.last_assistant_message // ""),
  report_chars: (.last_assistant_message // "" | length),
  agent_transcript_path
}' <<<"$INPUT" > "$DIR/$AGENT_ID.json" 2>/dev/null || exit 0

# 保留最近 2000 份，避免無限增長
ls -t "$DIR"/*.json 2>/dev/null | tail -n +2001 | xargs -r rm -f
exit 0
