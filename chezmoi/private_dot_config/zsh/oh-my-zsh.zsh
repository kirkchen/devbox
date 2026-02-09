# Oh-My-Zsh Configuration
# Path to your oh-my-zsh installation (already set in .zshrc.tmpl)
# export ZSH=$HOME/.oh-my-zsh

# Theme configuration
ZSH_THEME="bullet-train/bullet-train"

# Bullet-train theme configuration
BULLETTRAIN_PROMPT_ORDER=(
  context
  dir
  git
  kctx
  nvm
  cmd_exec_time
)
BULLETTRAIN_NVM_SHOW=true
BULLETTRAIN_GO_SHOW=true
BULLETTRAIN_KCTX_KUBECTL=true
BULLETTRAIN_KCTX_BG=magenta
BULLETTRAIN_KCTX_FG=white
BULLETTRAIN_EXEC_TIME_SHOW=true
BULLETTRAIN_DIR_EXTENDED=2
BULLETTRAIN_GIT_PROMPT_CMD=\$(git_prompt_info)
BULLETTRAIN_CONTEXT_HOSTNAME="${HOSTNAME:-DevContainer}"

# Oh-My-Zsh update behavior
DISABLE_AUTO_UPDATE=false
DISABLE_UPDATE_PROMPT=false
UPDATE_ZSH_DAYS=7

# Completion settings
ENABLE_CORRECTION="true"
COMPLETION_WAITING_DOTS="true"

# History settings
HIST_STAMPS="yyyy-mm-dd"

# Plugins to load
plugins=(
  git
  gitfast
  zsh-autosuggestions
  z
  alias-tips
  docker-compose
  fzf
  colored-man-pages
  command-not-found
  extract
  sudo
)

# Source Oh-My-Zsh
source $ZSH/oh-my-zsh.sh