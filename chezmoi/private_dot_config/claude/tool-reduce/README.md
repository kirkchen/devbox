# tool-reduce

用 TypeSafe Jev 判斷 Claude Code 裡 tool output 的哪些段落是冗餘的，換成可還原的墓碑標記，省 context。

判斷邏輯（切段、問 Jev、套門檻、寫存放區）全部在這個目錄的模組裡；PostToolUse hook 只是薄薄一層組裝，`tr-eval`、`tr-tune` 匯入同一份 `drop_policy`，離線重放跟線上決策才不會漂移。

設計依據在 `docs/superpowers/specs/2026-09-21-tool-result-reduce-design.md`——**這份文件不在版控**，只存在本機（`docs/superpowers/` 被 `.gitignore` 排除），換機器或要給別人看要另外處理。

## 開關

`TOOL_REDUCE_MODE`，寫在 `~/.config/claude/typesafe.env`（權限 600；這個檔案本身不由 chezmoi 管理，見「所有環境變數」）：

| 模式 | 行為 |
|---|---|
| `off`（預設，含完全沒設定） | PostToolUse hook 立刻回傳，不呼叫 Jev、不寫任何紀錄 |
| `shadow` | 照常判斷、寫決策紀錄，但**不改** tool output——用來累積資料，不影響 agent 看到什麼 |
| `full` | 判斷後真的把冗餘段落換成墓碑標記，回傳 `updatedToolOutput` |

沒設定就是 `off`：程式部署到位不會自己開始改東西，要明確打開才會生效。已經存在的環境變數不會被 `typesafe.env` 的內容覆寫（`jev.load_env` 用 `os.environ.setdefault`），所以互動式 shell 裡手動 `export TOOL_REDUCE_MODE=shadow` 會蓋過檔案裡的值。

**這份 README 描述的是判斷邏輯本身；hook 要真的被呼叫到，還需要在 Claude Code 的 settings 裡註冊 `PostToolUse`（`tool-reduce.py`）、`PreToolUse`（`tr-guard.py`）、`SessionEnd`（`tr-cleanup.sh`）三個 hook。目前這三支都還沒被註冊在任何 settings 檔案裡——上線是刻意分開的另一個步驟，開啟之前這整條 pipeline 完全不會被觸發。**

## 墓碑與還原

`full` 模式下，被判定冗餘的段落會原地換成一段固定格式的標記（`descriptor.py` 的 `make()`，規則產生，不是 Jev 寫的）：

```
[省略 12 行 · fetch https://api.example.com/v2/orders?since=... · tr-restore a3f2c91b0d.3]
```

看到 `tr-restore <handle>` 就照著打：

```sh
tr-restore a3f2c91b0d.3
```

還原的原文會印到 stdout，同時記一筆到 `restores.jsonl`——這是後續 eval 的 ground truth，「墓碑被還原」是無誤判的訊號。`handle` 格式是 `<decision_id>.<段落序號>`（`^[A-Za-z0-9]+\.\d+$`）；沒設 `TOOL_REDUCE_SESSION` 時，`tr-restore` 會掃過存放區底下每一個 session 目錄（排除 `archive/`，最新異動的先找）找這個 handle——`decision_id` 是 sha256 + `os.urandom`，handle 全域唯一，不會有歧義。同時開兩個 Claude Code session 時這很重要：只挑「最新異動的那一個」會讓另一個 session 的墓碑還原不了。

段落原文只存在對應 session 的存放區（預設 `~/.claude/tool-reduce/<session_id>/`，權限 700），session 結束就被 `tr-cleanup.sh` 刪掉——tool output 可能帶密鑰，不跨 session 保留。想直接讀存放區檔案而不透過 `tr-restore`，也算一次還原，會被 `tr-guard.py`（PreToolUse）觀察到並記錄，兩條路徑各記各的、不重疊。

## 檔案地圖

`chezmoi/private_dot_config/claude/tool-reduce/`：

| 檔案 | 負責什麼 |
|---|---|
| `shapes.py` | 每個工具 `tool_response` 的形狀：把要濾的文字讀出來（`extract`）、把濾完的文字寫回去（`rewrite`）。Bash／Read 的形狀已用即時探針驗證過，其餘工具（WebFetch、WebSearch…）沿用猜測，之後要用到得重新驗證 |
| `chunker.py` | 結構感知切段：先拆信封（MCP 的 `{"result": "..."}`、Read 的行號前綴），再照一組分隔符優先順序（JSON 逗號、grep 分組、`---`、標題…）切，最後才退回固定寬度。`''.join(chunks) == payload` 是硬性不變量 |
| `jev.py` | TypeSafe Jev client：讀 `typesafe.env`（`load_env`，逐行 parse、不 source shell）、組問題（`build_questions`）、送請求（`ask`）、把答案攤平成每段一組分數（`scores`） |
| `questions.json` | 送給 Jev 的兩題：`noise`（這段是不是在複述別處已有的內容）、`uniq`（這段有沒有別處沒有的事實） |
| `drop_policy.py` | 門檻（`noise_min`／`uniq_max`／`min_chunks`／`max_drop_ratio`）與 `decide()`——PostToolUse hook 跟 `tr-tune` 共用同一份，不刪第一段、不刪最後一段的位置規則也在這裡 |
| `descriptor.py` | 產生墓碑標記文字；也產生「獨有詞集合」給 `tr-eval` 的 Layer 1 比對用。兩者都先過密鑰過濾（`store.SECRET_RE`） |
| `store.py` | Session 存放區：`save_chunk`／`load_chunk`，`record_decision`／`record_tombstone`／`record_restore`（各寫一份到 session 目錄，同時附加寫一份到 `archive/`），密鑰正則，存放區根目錄的單一解析公式 |
| `jsonl_io.py` | `tr-stats`／`tr-eval`／`tr-tune` 共用的 best-effort JSONL 讀取器：解析失敗或不是 dict 的行一律濾掉並計數，不丟例外 |
| `executable_tr-stats.py` | `tr-stats` CLI（見下方「三個工具」） |
| `executable_tr-eval.py` | `tr-eval` CLI |
| `executable_tr-tune.py` | `tr-tune` CLI |

`chezmoi/private_dot_config/claude/hooks/`：

| 檔案 | 負責什麼 |
|---|---|
| `executable_tool-reduce.py` | PostToolUse hook，真正的過濾邏輯：取輸入 → 切段 → 問 Jev → 套 `drop_policy` → 寫存放區 → 輸出 `updatedToolOutput`。任何異常都 fail-open（不輸出，原文照送給模型） |
| `executable_tr-guard.py` | PreToolUse hook，觀察 agent 是不是繞過 `tr-restore` 直接讀了存放區檔案，記進 `restores.jsonl`。永遠不阻擋任何呼叫，只負責記錄 |
| `executable_tr-cleanup.sh` | SessionEnd hook，刪掉這個 session 的段落原文（`archive/` 的紀錄檔不動），外加清掉超過 7 天的殘留 session 目錄 |

`chezmoi/dot_local/bin/`：

| 檔案 | 負責什麼 |
|---|---|
| `executable_tr-restore` | 還原一個 handle：印到 stdout，記一筆 `restores.jsonl` |

## 三個工具

| 工具 | 做什麼 | 什麼時候跑 |
|---|---|---|
| `tr-stats.py` | 從封存區（或單一 `--session`）彙總實際數字：毛省、墓碑成本、還原拉回、淨省、還原率、依工具拆分、noise 分數分佈直方圖 | 想知道「目前到底省了多少、還原了多少」的任何時候；累積資料後定期看健康度 |
| `tr-eval.py` | Layer 1：把每個被刪的墓碑分成 `restored`（確定誤刪，已被救回，精確訊號）／`silent_miss`（沒還原，但該段的獨有詞後來出現在 transcript 裡——近似趨勢指標，不是精確量測）／`clean`。加 `--batch out.jsonl` 會額外產出給人工盲標的批次（被刪段落 + 10% 未刪對照組，拿掉決策欄位） | 平時想看沉默誤刪的趨勢，跑不帶參數的版本；要準備一批人工標註（供 `tr-tune` 的人工基準用）時跑 `--batch` |
| `tr-tune.py` | 拿 `decisions.jsonl` 裡已經存的 Jev 原始分數做網格重放（零 API 成本、零延遲），列出候選門檻；`--apply` 套用「沉默誤刪率不高於現行、省最多」的候選，但要先過人工基準閘門 | 累積夠多決策紀錄、且 `human_baseline.json` 夠新之後，想重新調整門檻時跑 |

三支共用同一套「盡力而為」容錯：封存檔案可能寫壞、寫一半（`store._append` 不保證原子性），解析失敗或形狀不對的紀錄一律跳過、累計成 `records_skipped` 印出來，不丟例外、不安靜吞掉。

## 目前的操作點：noise≥0.7、uniq≤0.4、不刪頭尾

`drop_policy.DEFAULTS`：

| 門檻 | 值 | 意義 |
|---|---|---|
| `noise_min` | 0.7 | 這段要「複述別處已有內容」到這個分數以上，才有資格被刪 |
| `uniq_max` | 0.4 | 這段的「別處沒有的事實」分數要在這個分數以下 |
| `min_chunks` | 3 | 段數低於這個數字，整份放行不判斷 |
| `max_drop_ratio` | 0.6 | 單份 tool result 最多刪掉的字元比例，超過就從 noise 最低的候選開始留回來 |

不論分數多高，第一段跟最後一段永遠不刪。

**設計文件（離線 200 筆語料的量測）預估這個操作點省 7.9%。拿真正上線的 pipeline（含實際 chunker）跑 120 筆真實 tool result（1,113 個段落、847,766 字元、即時呼叫 Jev），量到的是 2.2%，比設計預估低了不少。**

差距的原因：離線研究當時用的 chunker 跟現在實際上線的不是同一份，切法不同、段落分佈跟著不同；真實資料的 noise 分數也比離線研究假設的更集中在低分區——p25 0.24、p50 0.33、p75 0.46、p90 0.61。門檻設在 0.7，等於要求一個段落的 noise 分數贏過九成同類段落，還要同時滿足 `uniq≤0.4`、且不能是頭尾，三個條件疊加，真正通過的段落自然很少。同一批資料另外量到：`noise≥0.6` 省 3.7%，`noise≥0.5` 省 6.7%。

決定：照樣在 `noise≥0.7` 上線。這是設計文件裡唯一「逐段還原」跟「整份重讀」兩種情境都為正的操作點（design 文件 2.4 節）；往下調換來的節省，目前沒有真實還原遙測能證明代價可以接受。等資料累積、`tr-eval` 有真正的還原紀錄可以量，再用 `tr-tune` 從實測重新推導門檻，不是憑離線預估直接往下調。

## 調校流程

1. `tr-eval.py --batch out.jsonl`——產出一批被刪段落（含 10% 未刪對照組），拿掉決策欄位
2. 人工盲標（看不到當初的判斷結果），整理成 `human_baseline.json`，放在存放區的 `archive/human_baseline.json`（預設 `~/.claude/tool-reduce/archive/human_baseline.json`）。至少要有三個欄位：`labelled`（標註筆數）、`agreement`（人機一致率）、`new_since`（基準之後累積了幾筆新樣本）
3. `tr-tune.py`——只列候選、不套用、不寫任何檔案
4. `tr-tune.py --apply`——套用「沉默誤刪率不高於現行、省最多」的候選，但要先過人工基準閘門：至少 20 筆標註、一致率至少 70%、基準之後新增樣本不超過 200 筆

**這道閘門是硬性拒絕（`BaselineTooThin` → `--apply` 直接回傳非零、不寫入 `thresholds.json`），不是印個警告接著照套。** 原因：Jev 的原始分數、`tr-eval` 的 Layer 1 三態分類、`tr-tune` 的候選重放，全部是同一套系統在給自己的作業打分數。如果拿這個閉環自己的輸出當調校的唯一依據，門檻會往「大家一起看走眼」的方向收斂——每個自動算出來的指標都在變好看，實際品質卻在變差，而且光看這些指標本身看不出任何警訊。人工基準是唯一從這個迴圈外面進來的訊號；它弱到不能用（太少、太舊、跟人對不上）的時候，就不該被信任來把關——警告可以被忽略，硬性拒絕不能。

## 所有環境變數

日常只需要 `TOOL_REDUCE_MODE` 跟 `TYPESAFE_API_KEY`，其餘是測試與搬移用的覆寫點。

| 變數 | 預設 | 用途 |
|---|---|---|
| `TOOL_REDUCE_MODE` | 未設（等同 `off`） | 開關：`off`／`shadow`／`full` |
| `TYPESAFE_API_KEY` | 無（未設時 PostToolUse hook 的 Jev 呼叫會失敗，被 fail-open 吞掉，等同不判斷、原文照送） | Jev API 金鑰，讀自 `typesafe.env` |
| `TOOL_REDUCE_HOME` | `~/.claude/tool-reduce` | 段落原文與紀錄的存放區根目錄 |
| `TOOL_REDUCE_LIB` | `~/.config/claude/tool-reduce` | hook（`tool-reduce.py`／`tr-guard.py`／`tr-restore`）載入判斷模組的路徑 |
| `TOOL_REDUCE_THRESHOLDS` | `~/.config/claude/tool-reduce/thresholds.json` | 門檻檔；不存在就用 `drop_policy.DEFAULTS`，`tr-tune --apply` 只改這個檔案，不動程式碼 |
| `TOOL_REDUCE_SIZE_GATE` | `2000`（字元） | tool output 短於這個長度，整份放行不判斷 |
| `TOOL_REDUCE_TIMEOUT` | `2.5`（秒） | 呼叫 Jev 的逾時 |
| `TOOL_REDUCE_MAX_CHUNKS` | `16` | 單份 tool result 最多切幾段 |
| `TOOL_REDUCE_SESSION` | 無（`tr-restore` 掃過每一個 session 目錄） | `tr-restore` 限定只去某一個 session 存放區找 handle |
| `TOOL_REDUCE_TRANSCRIPT_DIR` | `~/.claude/projects` | `tr-eval`／`tr-tune` 找 transcript 比對獨有詞的目錄（測試用覆寫點） |
| `TOOL_REDUCE_API` | `https://api.typesafe.ai/v1/systemone` | Jev API endpoint（測試用覆寫點） |
