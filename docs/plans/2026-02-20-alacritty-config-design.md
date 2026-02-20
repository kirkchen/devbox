# Alacritty 配置 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 devbox repo 新增 Alacritty 終端模擬器配置，搭配現有 Tmux 使用。

**Architecture:** 透過 chezmoi 管理 Alacritty TOML 配置檔，並在 macOS 安裝腳本中加入 cask 安裝指令。最小化變更，不動現有 Zellij/iTerm2/Tmux 配置。

**Tech Stack:** Chezmoi, Alacritty (TOML config), Homebrew cask

---

### Task 1: 建立 Alacritty 配置檔

**Files:**
- Create: `chezmoi/private_dot_config/alacritty/alacritty.toml`

**Step 1: 建立配置檔**

```toml
live_config_reload = true

[window]
padding.x = 8
padding.y = 8
decorations = "Buttonless"
option_as_alt = "Both"

[font]
size = 14.0
normal.family = "Source Code Pro"
```

**Step 2: 驗證 chezmoi diff**

Run: `chezmoi diff --source="./chezmoi" 2>&1 | head -20`
Expected: 顯示新增 `~/.config/alacritty/alacritty.toml`

**Step 3: Commit**

```bash
git add chezmoi/private_dot_config/alacritty/alacritty.toml
git commit -m "feat(alacritty): add minimal Alacritty configuration

Source Code Pro font, Buttonless window, Option as Alt, live reload."
```

---

### Task 2: 安裝腳本加入 Alacritty

**Files:**
- Modify: `chezmoi/.chezmoiscripts/run_once_02-install-cli-tools.sh.tmpl:26`

**Step 1: 在 macOS Homebrew 區塊的 `delta` 行後新增 Alacritty cask 安裝**

在第 26 行 (`command_exists delta || brew install git-delta`) 之後加入：

```bash
    command_exists alacritty || brew install --cask alacritty
```

**Step 2: 驗證腳本語法**

Run: `bash -n chezmoi/.chezmoiscripts/run_once_02-install-cli-tools.sh.tmpl 2>&1 || echo "Note: template syntax errors are expected from chezmoi tags"`
Expected: 只有 chezmoi template tag 的語法提示，無其他錯誤

**Step 3: Commit**

```bash
git add chezmoi/.chezmoiscripts/run_once_02-install-cli-tools.sh.tmpl
git commit -m "feat(alacritty): add Alacritty to macOS install script"
```
