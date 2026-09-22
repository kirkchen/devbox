# Model router

用 TypeSafe Jev 依任務內容決定 subagent 要跑哪個模型。

## 檔案

| 檔案 | 用途 |
|---|---|
| `questions.json` | 送給 Jev 的問題定義。eval 跟 hook 共用，改這裡兩邊一起變 |
| `policy.py` | Jev 答案 → tier 的決策邏輯，以及 fill/guard 模式判斷。唯一的決策實作 |
| `outcomes.py` | 從 Claude Code transcript 收 subagent 執行結果，以 `tool_use_id` 為 key |
| `review.py` | 覆盤：決策紀錄 ⋈ 實際結果 ⋈ Layer 1 完成度 |
| `screening.py` | 讀 corpus，把路由決策按「有沒有改過模型」分群比 Layer 1 分數 |
| `run_eval.py` | 對標註好的 eval set 跑 Jev 計分 |
| `transcript.py` | 從 subagent transcript 取 dispatch prompt 與 handback 報告。兩支 hook 共用的唯一萃取實作 |
| `backfill_corpus.py` | 用真報告重評既有 corpus（合成 SubagentStop 餵給 hook，不另外實作評分） |

eval 資料集另外放在 `~/.local/share/model-router-eval/`，因為裡面有工作專案的 prompt 內容，不進 dotfiles repo。

## 設定架構

### 唯一的設定來源

`~/.config/claude/typesafe.env`（權限 600）。

**這個檔案不由 chezmoi 管理**，已列入 `.chezmoiignore`。做成 chezmoi template 就得把密鑰
存進 `~/.config/chezmoi/chezmoi.toml` 明文，所以改成 machine-local；`chezmoi apply`
不會覆寫也不會刪除它。換機器要手動建。

```sh
TYPESAFE_API_KEY=...          # https://console.typesafe.ai/keys
ROUTER_MODE=shadow            # off | shadow | fill-only | full
ROUTER_NOTIFY=applied         # off | applied | all
ARCHIVE_SUBAGENT_REPORTS=1
JUDGE_SUBAGENT_OUTPUT=1
```

三支 hook 各自讀這個檔案，不依賴 shell 環境（hook 不繼承互動式 shell 的 env）：

- 兩支 `.sh` 用 `. "$CONF"`
- `model-router.py` 用自己的 `load_env()` 逐行 parse `KEY=VALUE`，**不 source shell**，
  避免執行檔案裡的任意內容

### 所有環境變數

日常只需要上面五個，其餘是測試與搬移用的覆寫點。

| 變數 | 預設 | 讀取者 |
|---|---|---|
| `TYPESAFE_API_KEY` | 無（未設則所有 hook 靜默跳過） | 三支 hook、`run_eval.py` |
| `ROUTER_MODE` | `off` | `model-router.py` |
| `ROUTER_NOTIFY` | `applied` | `model-router.py` |
| `ARCHIVE_SUBAGENT_REPORTS` | `0` | `archive-subagent-report.sh` |
| `JUDGE_SUBAGENT_OUTPUT` | `0` | `judge-subagent-output.sh` |
| `ROUTER_HOME` | `~/.config/claude/model-router` | 三支 hook（找 policy、questions、`transcript.py`） |
| `ROUTER_LOG` | `$ROUTER_HOME/decisions.jsonl` | `model-router.py`、`tune.py` |
| `ROUTER_API` | `https://api.typesafe.ai/v1/systemone` | `model-router.py`（測試用） |
| `ROUTER_TIMEOUT` | `2.5`（秒） | `model-router.py` |
| `ROUTER_PROJECTS` | `~/.claude/projects/*` | `tune.py` |
| `SUBAGENT_REPORT_DIR` | `~/.local/share/model-router-eval/reports` | `archive-subagent-report.sh` |
| `EVAL_CORPUS` | `~/.local/share/model-router-eval/corpus.jsonl` | `judge-subagent-output.sh`、`screening.py` |
| `EVAL_DIR` | `~/.local/share/model-router-eval` | `select_layer2.py`、`merge_layer2.py`、`tune.py`、`backfill_corpus.py` |
| `CLAUDE_PROJECTS` | `~/.claude/projects` | `backfill_corpus.py`（找 subagent transcript） |

### 檔案在哪

| 路徑 | 內容 | 誰產生 |
|---|---|---|
| `chezmoi/private_dot_config/claude/` | **原始碼,唯一的真實來源** | 人 |
| `~/.config/claude/model-router/` | 部署後的工具 | `chezmoi apply` |
| `~/.config/claude/hooks/` | 部署後的 hook | `chezmoi apply` |
| `~/.claude/settings.json` | hook 註冊 | `run_onchange_05-configure-claude-settings.sh` |
| `~/.claude/agents/eval-judge.md`、`~/.claude/commands/judge-backlog.md` | agent 與指令 | 同上 |
| `~/.config/claude/typesafe.env` | 密鑰與開關 | **手動** |
| `~/.config/claude/model-router/thresholds.json` | 調校後的門檻（不存在則用 `policy.DEFAULTS`） | `tune.py --apply` |
| `~/.config/claude/model-router/decisions.jsonl` | 路由決策，含 Jev 原始答案 | `model-router.py` |
| `~/.local/share/model-router-eval/` | reports/、corpus.jsonl、labels.jsonl、batches/ | hook 與 Layer 2 |

改程式碼一律改 `chezmoi/` 底下，再 `chezmoi apply --source="./chezmoi" ~/.config/claude`。
動到 hook 註冊或 agent/command 則要讓 `run_onchange_05` 重跑。

## ROUTER_MODE 各模式的行為

| 模式 | 行為 |
|---|---|
| `off` | hook 立刻 exit 0，完全不呼叫 Jev。預設值 |
| `shadow` | 呼叫 Jev、寫紀錄，但**不改** dispatch。用來累積覆盤資料 |
| `fill-only` | 只在呼叫端沒指定 `model` 時填補。不覆寫任何明確指定 |
| `full` | fill + 雙向 guard（可升可降） |

沒有 `ROUTER_MODE` 時一律當 `off`。這是刻意的：hook 裝上去之後不會自己開始作用，要明確打開。

## 決策紀錄格式

hook 每次決策 append 一行到 `~/.config/claude/model-router/decisions.jsonl`：

```json
{
  "ts": "2026-09-21T13:05:12+08:00",
  "session_id": "<PreToolUse 輸入的 session_id>",
  "tool_use_id": "toolu_01ABC...",
  "cwd": "/Users/kirk.chen/Code/...",
  "subagent_type": "general-purpose",
  "description": "Review Task 7 (spec + quality)",
  "prompt_chars": 4800,
  "mode": "shadow",
  "model_requested": "opus",
  "requested_tier": 2,
  "jev": { "reasoning_depth": {"score": 1.8, "confidence": 0.9}, "...": {} },
  "pred_tier": 1,
  "pred_conf": 0.85,
  "why": "推理需求高但指示夠完整",
  "action": "guard:down",
  "model_applied": "sonnet",
  "jev_latency_ms": 480,
  "error": null
}
```

`tool_use_id` 是接回 transcript 的鍵，一定要寫。`model_applied` 為 `null` 代表沒動（shadow 或 skip）。
Jev 失敗時 `error` 填原因、`model_applied` 為 `null`，dispatch 照原樣進行。

## 覆盤

```sh
~/.config/claude/model-router/review.py
~/.config/claude/model-router/review.py --since 2026-09-20
```

輸出：決策分布、Jev 延遲、實際生效的改動（對照同層歷史 tool_uses 中位數）、需要人工看的案例，
以及產出完成度。

`--corpus` 指到別的 corpus 可以換一批 Layer 1 分數；corpus 不存在時那一節會說接不到，不會壞掉。

### 產出完成度那一節在說什麼

tool_uses 只答得出「跑了幾輪」，答不出「產出有沒有比較差」。這一節把決策按
「router 有沒有實際改掉模型」分兩群，各自看 Layer 1 四題的中位數。

**它是敘述不是證據，報表自己會把這句話印出來。** 兩個理由：router 專挑它判斷簡單的任務
降級，兩群難度本來就不同——差異為零可能代表降級沒害處，也可能代表它只降級了本來就簡單的；
而且 Layer 1 是 Jev 判 Jev 自己的結果，有循環性。要下結論得走 Layer 2 盲標加人工基準。

判定「改壞了」的兩個自動訊號：
- **需返工** — 某個 `Implement Task N` 之後出現 `Re-review Task N fix round`，代表產出沒過 review
- **工作量暴增** — 改過模型的 dispatch，`tool_uses` 超過同層歷史中位數 1.8 倍

兩者都只是篩選器，最終要看 subagent 實際交出什麼。

## 自動 judge：兩層

路由決定之後要有人判「這個決定對不對」，否則沒有 eval 也沒有調整依據。分兩層，因為兩層要回答的問題和成本差很多。

### Layer 1 — 當下完成度篩檢（每筆都跑）

`hooks/judge-subagent-output.sh`，SubagentStop 的 **async** command hook，不阻塞 handback。

從 `agent_transcript_path` 取回當初的 dispatch prompt（第一則 user 訊息）與 subagent 實際交回的
報告，送 Jev 問四題（`completeness_questions.json`）：

**報告不是 `last_assistant_message`。** 那個欄位是 subagent 把報告交回 caller 之後留下的收尾句，
實測大量是字串 `Report delivered.`（17 字元）。真正的報告在 transcript 裡 `SubagentHandback`
這個 tool call 的 `message` 欄位。兩者差 13.6 倍（中位數 293 vs 2,992 字元）。

萃取由 `transcript.py` 負責，judge 與 archiver 共用。兩邊各寫一份 jq 正是 2026-09-22 兩邊
一起取錯欄位的原因，理由同 `policy.py` 被線上 hook 與離線 `tune.py` 共用。
corpus 與存檔都記 `report_source`（`handback` / `last_message`），分得出哪些列是完整報告。

| question | 問什麼 |
|---|---|
| `addressed_everything` | request 點名的每一項，output 有沒有對應處理 |
| `signs_of_incompleteness` | 有沒有做到一半就停的跡象 |
| `refused_or_blocked` | 有沒有表示做不到、被擋住、要更多資訊 |
| `output_depth` | 只複述請求 / 有實質查證 / 找出請求沒點名的問題 |

每筆約 $0.00008。結果 append 到 `~/.local/share/model-router-eval/corpus.jsonl`，
並算出 `needs_layer2` 旗標。

**這一層是篩選，不是定論。** 用 Jev 判 Jev 自己的路由結果有循環性，所以它的輸出不當 eval ground truth。

開關：`JUDGE_SUBAGENT_OUTPUT=1`

### Layer 2 — 事後 tier 判定（少數）

用真模型 judge，產出 `expected_tier`（這件工作最低需要哪一級模型）——這才是 eval 的 ground truth。

只處理三種：

1. Layer 1 標了 `needs_layer2` 的
2. 事後出現返工訊號的（`Re-review Task N fix round`，要等後續 dispatch 才知道，所以必須延後跑）
3. **隨機 10% 對照組** — 沒有對照組就只會看到篩選器挑出來的案例，永遠量不到 Layer 1 的漏判率

judge 必須盲標：看不到當初用了哪個模型，也看不到 Layer 1 的分數。
`make_label_batches.py` 產出的批次已經拿掉 `model_requested` / `model_resolved` / `prelabel`。

```sh
R=~/.config/claude/model-router
$R/make_label_batches.py --size 8        # 盲標批次
# → judge 依 $R/JUDGE.md 判，輸出存成 judge-out-NN.json
$R/merge_labels.py ~/.local/share/model-router-eval/judge-out-*.json
$R/merge_labels.py --agreement           # 跟人工基準比一致率
```

### 校準（不能跳）

judge 跟 Jev 都是模型，兩者一致只代表它們犯一樣的錯。自己手標 10 筆當基準：

```sh
$R/merge_labels.py --human my-labels.json
$R/merge_labels.py --agreement
```

**完全一致率低於 70% 就不要用 judge 標剩下的**，先改 `JUDGE.md` 的分級定義再重跑。

### 語言

Jev 的問題定義（instructions / criteria）一律寫英文：官方文件載明
「Jev's primary training language is English; other languages, including CJK scripts,
are accepted but currently have lower accuracy」。

`state` 帶的是任務原文，改不了——中文任務的判斷準確度會低一些，這是 eval 要量出來的東西之一，
不是可以假裝沒有的風險。`JUDGE.md` 是給 Claude 看的，不受此限。

### 歷史資料

Claude Code 不保留 subagent 產出，session 結束後 `outputFile` 會被清掉。
實測 204 筆歷史 dispatch 只剩 2 筆可還原，所以歷史資料只拿來看「任務形態 → tier」的粗訊號，
不當品質基準。真正的 corpus 從 Layer 1 開啟之後開始累積。

subagent transcript 本身在磁碟上留得比較久，所以 Layer 1 用錯欄位那段期間的列可以事後重評：

```sh
$R/backfill_corpus.py            # 只報告：多少個 agent、會重評幾次
$R/backfill_corpus.py --apply    # 重評並換檔，原檔備份成 .bak-<時間>
$R/backfill_corpus.py --all --apply   # 連已經是 handback 的列也重評（萃取方式改過時）
```

**重評的單位是「每一次 handback」，不是「每個舊列」。** 一個 agent 可以交回不只一次
（實測 76 個 agent 共 92 次），SubagentStop 每次各觸發一次 hook，所以 corpus 同一個
`agent_id` 本來就會有好幾列——那不是重複，是不同次的交付。

照舊列數重跑會讓每一列都讀到 transcript 的**最終**狀態，變成同一份報告的複本，中間
幾次交回的內容就沒了。所以 `rebuild()` 是照 `transcript.handback_positions()` 把
transcript 切到那一次交回為止，一次餵一份給 hook，重現當下看到的狀態。

存檔（`reports/`）以 `agent_id` 為檔名，一個 agent 只有一份，存最終狀態，而且餵的是
真實路徑不是切片——切片跑完就刪，存進去只會留下死路徑。

## 自動調校與人工的分界

| 環節 | 自動程度 |
|---|---|
| 收資料（Layer 1 + archiver） | 全自動，hook 觸發 |
| Layer 2 標註 | `/judge-backlog` 手動觸發，判斷全自動 |
| 門檻調校 | `tune.py` 全自動 |
| 漂移偵測 | `review.py` 報表 |
| **人工基準標註** | **只有這項需要你** |

### 為什麼門檻調校不用重新呼叫 Jev

決策紀錄存了 Jev 的**原始答案**（`jev` 欄位），不是只存最後選了哪個模型。
換門檻只是拿同一批答案重算一次，零成本零延遲，可以把整段歷史瞬間重放。

門檻本身放在 `thresholds.json`，`policy.py` 啟動時讀取，不存在就用 `DEFAULTS`。
`tune.py --apply` 只改那個檔案，不動程式碼。

```sh
tune.py                          # 只報告
tune.py --apply                  # 過閘門才寫入
tune.py --allow-worse-downgrade  # 明確用安全性換成本
```

### 排序刻意不是「在上限內省最多」

那會為了一點成本把錯誤降級率推到天花板。錯誤降級是這個系統最貴的失誤——
`subagent-driven-development/SKILL.md:208` 說便宜模型在多步驟任務上會多跑 2-3 倍輪次，
省了單價賠上總量。

所以預設只考慮**錯誤降級率不高於現行**的組合，在那之中才比省多少。
要拿安全性換成本必須明確加 `--allow-worse-downgrade`，不會默默發生。

### 套用閘門

四道，任一不過就拒絕並說明原因，不會默默照跑：

1. 人工基準至少 10 筆
2. judge 與人工基準的一致率 >= 70%
3. 最後一筆人工標註之後，新增樣本不超過 200 筆（基準沒過期）
4. 新門檻的錯誤降級率不超過上限、且不高於現行、且確實有改善

### 人工基準為什麼不能省

judge 跟 Jev 都是模型。拿 judge 的標註當 ground truth 自動調 Jev 的門檻是一個閉環：
兩者會朝共同的偏誤收斂，指標一路變好而實際品質一路變差，而且從指標上看不出來。

人工基準是唯一從迴圈外進來的訊號。閘門 2 跟 3 就是在強制它保持新鮮。

**工作量**：每季約 10 筆手標，或每累積 200 筆新樣本補 10 筆。

```sh
merge_layer2.py --human my-labels.json
```

## Router hook

`hooks/model-router.py`，PreToolUse 的 `Agent|Task` matcher。

寫成 Python 而不是 shell，因為它直接 `import policy`——線上決策與離線 `tune.py`
共用同一份實作，不會各自漂移。

### 已驗證的行為

| 情境 | 行為 |
|---|---|
| `ROUTER_MODE` 未設 / `off` | 立即退出，不呼叫 Jev |
| `shadow` | 呼叫 Jev、寫紀錄、印出「本來會改什麼」，但不改 dispatch |
| `eval-judge`、白名單外的 agent type | 不碰 |
| 認不得的 model id | 不碰 |
| `fill-only` + 無 model | 填補 |
| `fill-only` + 已指定 model | 不碰 |
| `full` + 已指定 model | 雙向 guard |
| Jev 連不上 / 回傳壞 JSON / 逾時 | 無輸出、exit 0，錯誤記進紀錄 |

白名單：`general-purpose` `claude` `Explore` `Plan`。

### updatedInput 是整份取代

官方文件寫「merged with original」是錯的（實測於 2.1.278）。只回傳 `{model: ...}`
會讓 Agent 呼叫 schema 驗證失敗：

```
The parameter `description` type is expected as `string` but provided as `unknown`
```

所以 hook 回傳完整 `tool_input` 再改 `model` 那一欄。

### 可見度

`ROUTER_NOTIFY`：`off` | `applied`（預設）| `all`

Claude Code 把 `systemMessage` 渲染在 Agent 呼叫底下，前面自動加
`PreToolUse:Agent says: `（約 23 欄）。訊息刻意壓在單行以內：

```
● Agent(Review Task 7)
  └ PreToolUse:Agent says: router · general-purpose · opus → sonnet · 指示夠完整 (0.88)
```

`applied` 只在實際改動、或 shadow 模式下「本來會改」時出聲。
shadow 用 `⇢` 跟實際改動的 `→` 區分。維持原樣與 Jev 失敗要 `all` 才會顯示。

### 決策紀錄

每筆一行寫進 `~/.config/claude/model-router/decisions.jsonl`，**含 Jev 的 5 題原始答案**。
這是 `tune.py` 能零成本重放整段歷史的前提——沒存原始答案就只能重新呼叫 API。
