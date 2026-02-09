# Claude Code Settings 說明

## statusLine

顯示格式：`🌿 分支 | 模型名稱 | 目錄名稱`

例如：`🌿 main | Claude Opus 4.5 | devbox`

命令拆解：
1. `input=$(cat)` - 讀取 Claude 傳入的 JSON
2. `git symbolic-ref --short HEAD` - 取得目前 git 分支
3. `jq '.model.display_name'` - 從 JSON 取模型名稱
4. `jq '.workspace.current_dir'` - 從 JSON 取當前目錄
5. `basename` - 只取目錄名稱

## enabledPlugins

- `code-review` - 程式碼審查功能
- `superpowers` - 增強功能（TDD、debugging 等 skills）

## permissions.deny

安全規則，禁止讀取/寫入敏感檔案：
- `.env*` - 環境變數檔案
- `**/secrets/**` - secrets 目錄
- `rm -rf /` - 防止誤刪根目錄
