# 用 TypeSafe Jev 開發工具

2026-09 做 subagent model router 時累積的知識。分兩部分：Jev 本身的使用方式，以及
Claude Code hook 的實測事實（含官方文件寫錯的地方）。

實作在 `chezmoi/private_dot_config/claude/model-router/`，那邊的 README 講的是那個工具
怎麼用；這份講的是下次做別的工具時需要先知道什麼。

---

## Part 1：Jev

### 什麼時候該用

Jev 不生成文字，它把自然語言轉成**有型別的判斷加機率**。適合「程式需要一點語意常識才能
往下走」的地方：路由、排序、抽取、驗證、分類。

判斷準則：如果你本來打算寫一段 prompt 丟 LLM 再 parse 它的回答，那一步通常可以換成 Jev。
如果你要的是生成內容，Jev 不適用（官方明言它沒有被訓練來生成文字）。

### 三種 primitive

| primitive | 回傳 | 用在 |
|---|---|---|
| `noul` | 0–1 的機率 | 某個條件成不成立 |
| `choice` | 選中的選項 + 各選項機率 + confidence | 從一組互斥選項挑一個 |
| `score` | 加權位置 + 各級距機率 + confidence | 在一個有序維度上的程度 |

多個標籤可能同時成立時，用多個 `noul`，不要硬塞成一個 `choice`。

### 硬數字

| 項目 | 值 |
|---|---|
| 定價 | input $0.042 / M tokens，**output 免費** |
| Context | 64k / request，其中 `state` + 最長 question 合計上限 32k |
| Rate limit | 1200 RPM / 250k tokens per second |
| 輸入型態 | 純文字（string / JSON object / array）。無 image、audio、video |
| 實測延遲 | 單題 0.89s、五題同一 request 0.65–1.0s |

**五題一次問跟一題問幾乎一樣快**——獨立問題是平行評估的。所以不要為了省延遲而少問，
該拆的維度就拆開。

成本低到通常不必列入考量：一次 1k token 的呼叫約 $0.000042。

### 語言：instructions 與 criteria 一律寫英文

官方文件（`concepts/state.md`）載明：

> Jev's primary training language is English; other languages, including CJK scripts,
> are accepted but currently have lower accuracy

`state` 帶的是應用的原始資料，改不了語言，這部分的準確度損失要靠 eval 量出來。
但 `instructions` 和 `criteria` 是我們自己寫的，沒有理由不用英文。

### Score 是 0-indexed

級距編號是它在 `criteria` 陣列裡的位置，從 0 開始。三個級距的範圍是 0–2，不是 1–3。
寫 threshold 時很容易搞錯。

回傳的 `score` 是機率加權值，不是選中的級距：

```
probabilities {0: 0.0, 1: 0.57, 2: 0.43}
score = 0×0.0 + 1×0.57 + 2×0.43 = 1.43
```

### confidence 是分布集中度，不是正確率

`choice` 和 `score` 的 `confidence` 表示機率分布有多集中，**不代表答案對不對**，
也不代表可以放心行動。`noul` 沒有獨立的 confidence，機率本身就是答案——`noul` 接近 0.5
代表「是」和「否」機率相近，不是「中等程度」。

**低 confidence 通常是題目的問題，不是模型的問題。** 我們的 `consequence_of_miss`
在真實呼叫中 confidence 只有 0.02，等於在三個級距之間亂猜。回頭看 criteria 寫的是
「會造成返工，但下一道關卡會攔到」這種沒有具體情境可對照的描述。

所以 eval corpus 第一個該回答的問題不是「路由準不準」，是**每一題的 confidence 分布長怎樣**。
分布集中在低處的題目要重寫 criteria，不然它在 policy 裡等於不存在。

### 多題合成時，confidence 取最小值

官方 function calling cookbook 的做法：一個判斷錯了整個結果就錯，所以看最弱的那一題，
不是相乘也不是平均。

```python
conf = min(a["reasoning_depth"]["confidence"], a["spec_completeness"]["confidence"])
```

### 問題設計：不要問最終決策

最重要的一條。**不要問 Jev「該用哪個模型」「該分給哪個團隊」「該收多少錢」**，
要問可重用的語意維度，policy 留在 code 端組合。

三個理由：

1. 換選項清單（多一個模型、多一個團隊）就要重跑推論
2. 調 threshold 不需要重新呼叫 API——答案存下來重算就好，零成本
3. Jev 沒有你的成本結構、SLA、風險偏好，那些不該塞進 prompt

實例，router 問的是五個維度而不是「用哪個模型」：

```
reasoning_depth       這件事需要多少推理（0–2）
spec_completeness     指示把「怎麼做」交代到什麼程度（0–2）
is_readonly_lookup    是不是純粹找資訊回報
is_retry_after_failure 是不是先前失敗後的重試
consequence_of_miss   漏判的後果多嚴重（0–2）
```

然後 code 裡：

```python
if lookup > 0.7 and depth < 0.7:  tier = 0
elif spec > 1.4 and depth < 1.6:  tier = 0   # 指示已寫完整，謄寫性質
elif depth < 1.3:                 tier = 1
...
if conseq > 1.4 and tier < 1:     tier = 1   # 高後果下限
```

### criteria 要寫具體情境

Jev 1.13 的已知弱點第一項是「literal reading」——它照字面讀，不推論言外之意。
criteria 寫「複雜的任務」沒用，要寫「要自己拆解問題、在多個方案之間取捨，或診斷成因不明的錯誤」。

Score 的每個級距要能獨立成立，不能依賴讀者對照前後級距才懂。

### 已知弱點與對應做法

官方 `model-jaggedness/jev-1.13.md` 列了九項。實務上影響最大的幾個：

| 弱點 | 做法 |
|---|---|
| Literal reading | criteria 寫具體情境，不用抽象形容詞 |
| 數字、計數、日期比較不可靠 | 不要問「這需要幾個步驟」「這是不是在那之後」。算術交給 code |
| Large irrelevant state 會掉準 | 只放判斷需要的欄位，不要把整段 context 原封不動丟進去 |
| 不把 state 當敵意資料 | 使用者可以在內容裡寫指令影響判斷。有安全或成本意涵時 code 端要有下限 |
| 多跳推理、雙重否定降準 | 一題只問一個判斷，拆開問 |
| 相關題目之間沒有數學保證 | `P(noul) ≠ 1 - P(not noul)`，不要靠互補關係推導 |

### state 用具名 JSON 欄位

不要把多段內容串成一個字串。`instructions` 裡用反引號指稱欄位，巢狀路徑也可以：

```json
{"state": {"agent_type": "general-purpose", "task": "...", "prior_attempt": "..."}}
```
```
"instructions": "`task` is a unit of work... `prior_attempt` is what failed before."
```

### 一定要存 Jev 的原始答案

這是整個設計裡最划算的一個決定。決策紀錄裡存最後的結論沒用，要存**每一題的原始分數與
confidence**。

有了原始答案，調 threshold 就只是拿同一批答案重算一次——零 API 成本、零延遲，可以把整段
歷史瞬間重放，網格搜尋幾百種門檻組合也只是幾秒的事。只存結論的話，每次調參都要重跑推論。

---

## Part 2：兩層 judge 與循環論證

做任何「用模型判斷」的工具，都會遇到「怎麼知道它判得對」。

### 不能用同一個模型判自己

用 Jev 篩檢 Jev 的路由結果、或拿一個 LLM judge 的標註當 ground truth 去自動調另一個模型的
門檻，都是閉環：兩者會朝共同的偏誤收斂，指標一路變好而實際品質一路變差，**而且從指標上
看不出來**。

### 分兩層

| | Layer 1 | Layer 2 |
|---|---|---|
| 跑什麼 | Jev 篩檢完成度 | 真模型盲標 |
| 頻率 | 每筆 | 被篩出來的少數 |
| 成本 | ~$0.00008 | 一次 opus 呼叫 |
| 角色 | **篩選器** | **ground truth** |
| 時機 | 當下（async，不阻塞） | 延後 |

Layer 2 必須延後，因為有些訊號要等後續事件才知道——例如「這個實作後來被要求重做」要等
下一次 dispatch 才看得到。

### 三件容易漏掉的事

**盲標。** 給 judge 的資料要拿掉「當初做了什麼決定」。看得到的話，judge 標出來的只是在
複述那個決定，這份標註就沒有鑑別力。

**隨機對照組。** 只判被篩選器挑出來的案例，就永遠量不到篩選器的**漏判率**。固定抽 10%
沒被 flag 的一起判，才能算出來。用 id 的雜湊決定抽樣，重跑會挑到同一批。

**人工基準。** 這是唯一從迴圈外進來的訊號，不能省。做成硬性閘門：自動調校在人工基準
筆數不足、人機一致率低於門檻、或基準過期（其後新增樣本超過上限）時**拒絕套用並說明原因**，
而不是默默照跑。穩態下的人工成本大約每累積 200 筆補標 10 筆。

### 自動調校的排序不要「在上限內求最大」

網格搜尋門檻時，如果目標寫成「錯誤率在上限內、省最多」，它會為了一點收益把最貴的那種
錯誤推到天花板。要先固定「危險的錯誤不得比現行更差」，在那個子集合裡才比較收益；
要拿安全性換成本必須是明確的一個旗標，不能默默發生。

---

## Part 3：Claude Code hook 的實測事實

以下都是 2.1.278 實測。有幾項跟官方文件不符。

### updatedInput 是整份取代，不是合併

**文件說它會與原 input 合併，實際是整份取代。** 只回傳要改的欄位會讓工具呼叫失敗：

```
PreToolUse hook for Agent returned updatedInput that failed schema validation:
The parameter `description` type is expected as `string` but provided as `unknown`
```

正確做法是回傳完整的 `tool_input` 再改那一欄：

```python
{"hookSpecificOutput": {"hookEventName": "PreToolUse",
                        "updatedInput": {**tool_input, "model": "haiku"}}}
```

### PreToolUse 可以改 subagent 的模型，而且蓋得過明確指定

Agent tool 的 model 解析優先序：per-invocation `model` > 定義檔 frontmatter >
`CLAUDE_CODE_SUBAGENT_MODEL` > 主對話模型。hook 的 `updatedInput` 改的就是最高優先那層，
所以連呼叫端明寫的 `model: opus` 都蓋得過去（實測降級到 Haiku 成功，主 transcript 的
`toolUseResult.resolvedModel` 可驗證）。

工具名在 2.1.63 之後是 `Agent`，`Task` 保留為 alias。matcher 寫 `Agent|Task` 兩邊都涵蓋。

### SubagentStop 拿得到完整產出

欄位：`agent_id`、`agent_type`、`last_assistant_message`（subagent 的完整最終報告）、
`agent_transcript_path`、`session_id`、`cwd`。

**`agent_type` 可能是空字串。** SubagentStop 在非 subagent dispatch 的情況下也會觸發，
不檢查的話會存到主 session 的訊息。一定要加 `[[ -n "$AGENT_TYPE" ]]` 這類守衛。

### transcript 不保留 subagent 產出

主 transcript 只有 dispatch 與用量統計，`outputFile` 指向的檔案 session 結束後會被清掉。
實測 204 筆歷史 dispatch 只剩 2 筆可還原。

**要事後分析 subagent 品質，就必須在 SubagentStop 當下存下來。** 一併存
`agent_transcript_path` 第一則 user 訊息（= 當初的 dispatch prompt），它也是會消失的。

### 接合各種紀錄的鍵

| 來源 | 有什麼 |
|---|---|
| PreToolUse | `tool_use_id`，沒有 `agent_id`（agent 還沒生出來） |
| SubagentStop | `agent_id`，沒有 `tool_use_id` |
| 主 transcript `toolUseResult` | **兩個都有**，加上 `resolvedModel` |
| task-notification | `tool-use-id` + `subagent_tokens` / `tool_uses` / `duration_ms` |

所以跨紀錄的 join 一定要經過主 transcript。

### systemMessage 會顯示給使用者

`systemMessage` 渲染在工具呼叫底下，Claude Code 會自動加前綴：

```
● Agent(Review Task 7)
  └ PreToolUse:Agent says: router · general-purpose · opus → sonnet · 指示夠完整 (0.88)
```

前綴 `PreToolUse:Agent says: ` 約佔 23 欄，中文又是雙寬字元，訊息要壓在單行內就得算一下。
`additionalContext` 是給模型看的，不是給人看的，兩者別搞混。

### async 只有 command hook 支援

`prompt` 和 `agent` 型別的 hook 會阻塞。要非阻塞就用 `"type": "command"` 加
`"async": true`，但 async hook 的 stdout 不會被採用，所以它只能做記錄類的事，不能回傳決策。

### 設定不用重啟

hooks 由 file watcher 讀取，改 `settings.json` 立即生效。
`/hooks` 可以列出目前所有已註冊的 hook 與來源。

### hook 註冊在 user level 會在所有 session 觸發

`~/.claude/settings.json` 的 hook 對這台機器上所有專案生效。開發階段要隔離，用專案層的
`.claude/settings.local.json`（gitignored），測完移除。

這也意味著資料會跨專案累積。如果某些專案的內容不該被記錄，那些 session 要個別關掉。

---

## Part 4：踩過的坑

**BSD `date` 不支援 `%3N`，而且不報錯。** `date +%s%3N` 在 macOS 回傳 `17899710643N`，
所以 `date +%s%3N 2>/dev/null || fallback` 的 fallback **永遠不會觸發**，後面的算術
以 `value too great for base` 失敗。要毫秒時戳就直接用 python：

```bash
now_ms() { python3 -c 'import time;print(int(time.time()*1000))'; }
```

這個 bug 讓整層篩檢從來沒寫出過資料，Jev 有被呼叫、有正確回答，結果全丟掉。
**同類陷阱**：任何「指令失敗時 fallback」的寫法，都要先確認那個指令失敗時真的回傳非零。

**Hook 要 fail-open。** 任何異常都不輸出、`exit 0`，讓原本的動作照常進行。
外部 API 在關鍵路徑上，一定要有硬性 timeout。router 用 2.5 秒，實測延遲 0.65–1.0 秒。

**開關預設關。** hook 裝上去之後不該自己開始作用。用環境變數控制，沒設就當關閉。
這讓 `chezmoi apply` 之後行為不變，開啟是明確的動作。

**密鑰檔不要交給 chezmoi 管理。** 做成 template 就得把密鑰存進 `chezmoi.toml` 明文。
放 machine-local 檔案（600）並加進 `.chezmoiignore`，apply 不會覆寫也不會刪除。

**驗證要一步一步來，不要一次建完才測。** 這次先用一支「永遠回傳固定值」的探針 hook
確認 `updatedInput` 真的能改 model，才往下做。那步如果不通，後面全部白做。
同樣地，`SubagentStop` 拿不拿得到報告也是先用探針確認的。
