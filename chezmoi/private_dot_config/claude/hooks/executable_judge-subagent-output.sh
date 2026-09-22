#!/bin/bash
# SubagentStop (async): Layer 1 完成度篩檢。
#
# 用 Jev 判「這次 subagent 有沒有交出被要求的東西」，結果寫進 eval corpus。
# 便宜到可以每筆都跑（約 $0.00008/次），非阻塞，失敗就安靜跳過。
#
# 這一層是「篩選」不是「定論」：它挑出可疑案例交給 Layer 2 的真模型 judge。
# 用 Jev 判 Jev 的路由結果有循環性，所以它的輸出不當 eval ground truth。
#
# 開關：JUDGE_SUBAGENT_OUTPUT=1
set -uo pipefail

CONF="$HOME/.config/claude/typesafe.env"
# shellcheck source=/dev/null
[[ -f "$CONF" ]] && . "$CONF"
[[ "${JUDGE_SUBAGENT_OUTPUT:-0}" == "1" ]] || exit 0
[[ -n "${TYPESAFE_API_KEY:-}" ]] || exit 0

R="${ROUTER_HOME:-$HOME/.config/claude/model-router}"
CORPUS="${EVAL_CORPUS:-$HOME/.local/share/model-router-eval/corpus.jsonl}"
MAX=12000   # request / output 各自送進 Jev 的字元上限，避開 state 過大掉準
mkdir -p "$(dirname "$CORPUS")" 2>/dev/null || exit 0

INPUT=$(cat)
AGENT_ID=$(jq -r '.agent_id // empty'              <<<"$INPUT" 2>/dev/null)
AGENT_TYPE=$(jq -r '.agent_type // empty'          <<<"$INPUT" 2>/dev/null)
SESSION=$(jq -r '.session_id // empty'             <<<"$INPUT" 2>/dev/null)
CWD=$(jq -r '.cwd // empty'                        <<<"$INPUT" 2>/dev/null)
TPATH=$(jq -r '.agent_transcript_path // empty'    <<<"$INPUT" 2>/dev/null)
LAST=$(jq -r '.last_assistant_message // empty'    <<<"$INPUT" 2>/dev/null)
[[ -n "$AGENT_ID" ]] || exit 0
# agent_type 為空代表這不是一次 subagent dispatch（主 session 的 Stop 也會走到
# 這個事件），存下來只會污染 corpus
[[ -n "$AGENT_TYPE" ]] || exit 0

# eval-judge 是標註用的 agent，判它自己會污染 corpus
[[ "$AGENT_TYPE" == "eval-judge" ]] && exit 0

# dispatch prompt 與實際交回的報告都在 subagent transcript 裡。
# `last_assistant_message` **不是**報告：subagent 用 SubagentHandback 把報告交回
# caller，那個欄位只留下收尾句（實測大量是 `Report delivered.`，17 字元）。
# 萃取邏輯與 archiver 共用 transcript.py，兩邊各寫一份 jq 正是這個 bug 的來源。
EX=$(python3 "$R/transcript.py" "$TPATH" 2>/dev/null)
REQUEST=$(jq -r '.request // ""'       <<<"$EX" 2>/dev/null)
OUTPUT=$(jq -r '.report // ""'         <<<"$EX" 2>/dev/null)
SOURCE=$(jq -r '.report_source // ""'  <<<"$EX" 2>/dev/null)
# transcript.py 還沒部署、或 agent 沒走 handback 就結束：退回舊欄位，別把整筆丟掉。
# corpus 記下 report_source，之後才分得出哪些列是完整報告、哪些只是收尾句。
if [[ -z "$OUTPUT" ]]; then
  OUTPUT="$LAST"
  SOURCE="last_message"
fi
[[ -n "$REQUEST" && -n "$OUTPUT" ]] || exit 0

REQ=$(jq -n \
  --slurpfile q "$R/completeness_questions.json" \
  --arg req "${REQUEST:0:$MAX}" --arg out "${OUTPUT:0:$MAX}" --arg at "$AGENT_TYPE" \
  '{model: $q[0].model,
    state: {agent_type: $at, request: $req, output: $out},
    questions: $q[0].questions}' 2>/dev/null) || exit 0

# 毫秒時戳。不能用 `date +%s%3N`：BSD date 不支援 %3N 但也不報錯，
# 會回傳結尾帶 N 的字串，後面的算術就整個炸掉而且 || fallback 不會觸發。
now_ms() { python3 -c 'import time;print(int(time.time()*1000))'; }
T0=$(now_ms)
RESP=$(curl -sS --max-time 20 https://api.typesafe.ai/v1/systemone \
  -H "Authorization: Bearer $TYPESAFE_API_KEY" \
  -H "Content-Type: application/json" -d "$REQ") || exit 0
T1=$(now_ms)

jq -e '.answers' >/dev/null 2>&1 <<<"$RESP" || exit 0

# flag：交給 Layer 2 真模型 judge 複查的條件
jq -c --arg aid "$AGENT_ID" --arg at "$AGENT_TYPE" --arg s "$SESSION" --arg cwd "$CWD" \
      --argjson ms "$((T1 - T0))" --arg src "$SOURCE" \
      --arg req_chars "${#REQUEST}" --arg out_chars "${#OUTPUT}" \
  '{ts: (now|todate), agent_id: $aid, agent_type: $at, session_id: $s, cwd: $cwd,
    layer: 1,
    request_chars: ($req_chars|tonumber), output_chars: ($out_chars|tonumber),
    report_source: $src,
    screen: .answers,
    jev_latency_ms: $ms,
    needs_layer2: (
      (.answers.addressed_everything.noul   < 0.7) or
      (.answers.signs_of_incompleteness.noul > 0.3) or
      (.answers.refused_or_blocked.noul      > 0.3) or
      (.answers.output_depth.score           < 0.6)
    )}' <<<"$RESP" >>"$CORPUS" 2>/dev/null

exit 0
