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
  kube
  nvm
  cmd_exec_time
)
BULLETTRAIN_NVM_SHOW=true
BULLETTRAIN_GO_SHOW=true
BULLETTRAIN_EXEC_TIME_SHOW=true
BULLETTRAIN_DIR_EXTENDED=2
BULLETTRAIN_GIT_PROMPT_CMD=\$(git_prompt_info)
BULLETTRAIN_CONTEXT_HOSTNAME="${HOSTNAME:-DevContainer}"

# Oh-My-Zsh update behavior
DISABLE_AUTO_UPDATE=false
DISABLE_UPDATE_PROMPT=false
UPDATE_ZSH_DAYS=7

# Completion settings
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
  zsh-syntax-highlighting
)

# kube-ps1 caches kubeconfig changes, avoiding a kubectl subprocess on every prompt.
if [[ -d "$ZSH/plugins/kube-ps1" ]] && (( ! ${plugins[(I)kube-ps1]} )); then
  plugins+=(kube-ps1)
fi

# Source Oh-My-Zsh
source $ZSH/oh-my-zsh.sh

# Bullet Train's nvm prompt calls `nvm current`; defer it until NVM is needed.
if (( $+functions[prompt_nvm] )) && (( ! $+functions[_DEVBOX_BULLETTRAIN_PROMPT_NVM] )); then
  functions -c prompt_nvm _DEVBOX_BULLETTRAIN_PROMPT_NVM
fi
if (( $+functions[_DEVBOX_BULLETTRAIN_PROMPT_NVM] )); then
  function prompt_nvm {
    if [[ -n "${_DEVBOX_NVM_LAZY_SCRIPT:-}" && "${_NVM_LAZY_LOADED:-0}" == 0 ]]; then
      return 0
    fi
    _DEVBOX_BULLETTRAIN_PROMPT_NVM "$@"
  }
fi
