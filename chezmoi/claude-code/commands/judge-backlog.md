---
description: 跑 model router 的 Layer 2 judge，把累積的 subagent 產出盲標成 eval 資料
---

執行 model router 的 Layer 2 標註。

## 步驟

1. 跑 `~/.config/claude/model-router/select_layer2.py $ARGUMENTS`
   它會挑出待判案例（Layer 1 flag + 返工 + 隨機對照組）並產生盲標批次到
   `~/.local/share/model-router-eval/batches/`。
   輸出 0 筆就到此為止，回報「沒有待判案例」。

2. 讀 `~/.config/claude/model-router/JUDGE.md`，確認分級定義。

3. 對每個 `batch-NN.json` **平行**派一隻 `eval-judge` subagent（它的 frontmatter 已指定 opus）。
   每隻的指示：
   - 讀 `JUDGE.md` 與自己那一個批次檔
   - 把 JSON 陣列結果寫到 `~/.local/share/model-router-eval/judge-out-NN.json`
   - 只寫檔，不要把完整結果貼回來，回報「已寫入 N 筆」即可

4. 跑 `~/.config/claude/model-router/merge_layer2.py ~/.local/share/model-router-eval/judge-out-*.json`

5. 刪掉 `judge-out-*.json`，回報摘要：本輪判了幾筆、tier 分布、Layer 1 的漏判率與準確率。

## 不要做的事

- 不要自己替 judge 補標註。judge 漏掉的就回報漏掉，不要填。
- 不要把批次內容貼進對話，那是原始工作內容而且很長。
- `merge_layer2.py` 若提示沒有人工基準，照實轉達：judge 標註在有人工基準比對之前，
  還不能拿來評 Jev 的路由準確度。
