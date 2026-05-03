# Development Guidelines

## Rules

- Stop after 3 failed attempts. Document what failed, question assumptions before continuing.
- Use conventional commits format: `type(scope): description`
- Make small, incremental commits — one logical change per commit.

## Anti-shortcut & calibration

- Diagnose before fixing. Name the root cause + cite the source line before any fix.
- Don't estimate time. Report size instead: files touched, lines changed, tests added.
- Before claiming done / fixed / passing, list 3 ways it could still be broken and verify each.
- Don't skip a check because it's "probably fine". Run it.

## Reader-facing output

**Scope**: 最終跟人互動的輸出 — code review、MR / PR descriptions、comments、docs、final task summary（呈現給 user 看的結尾）。
**不適用**：內部思考、tool 呼叫、sub-agent prompts、scratchpad、TodoList、conversation 中段的進度更新。

- **Avoid context gap** — reader 必須能在不回想前文 / 不查上一輪討論的情況下理解。
- **代號要在 reader 視野內可解碼** — 編號（D1, B1, Tier 2.5 等）作為 internal shorthand 沒問題，但 reader 看到時必須能在當前 doc 內找到 mapping。跨 doc boundary（design.md → MR description / commit message / Slack）一定要 translate 為 plain noun 或 inline 註解（例：`D6（Extension hard cap）`、不只寫 `D6`）。
- **判斷準則**：問自己「沒讀過 source doc 的人看到這個代號、能在 5 秒內理解嗎？」如果不能、就 translate 或加 mapping 註解。
- **不堆 performative thoroughness** — TL;DR 開場、emoji 小標、條列 5 個其實只有 2 個 load-bearing 都是 padding。reader 一句話能懂就不要列五個 bullets、兩個重點不要排到六個。
- **Final task summary 適用** — 收尾跟 user 報告「做了 X / 改了 Y」要用具體 file path / function name / 行為描述。session 內中段 subagent 之間溝通不限。
