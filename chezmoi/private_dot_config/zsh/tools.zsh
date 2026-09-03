# === macOS Language Version Managers ===
# This file is only loaded on macOS (see .zshrc)
# Each tool only loads if installed

# === Ruby (rbenv) ===
if [[ -d "$HOME/.rbenv" ]]; then
    export PATH="$HOME/.rbenv/bin:$PATH"
    eval "$(rbenv init -)"
fi

# === Node.js (NVM) ===
export NVM_DIR="$HOME/.nvm"
typeset -gA _DEVBOX_NVM_LAZY_TRIGGERS

_nvm_lazy_collect_triggers() {
    local command command_path
    local -a command_paths
    for command in nvm node npm npx corepack pnpm yarn yarnpkg; do
        _DEVBOX_NVM_LAZY_TRIGGERS[$command]=1
    done
    setopt local_options null_glob
    command_paths=( "$NVM_DIR"/versions/node/*/bin/*(N) )
    for command_path in "${command_paths[@]}"; do
        [[ -f "$command_path" && -x "$command_path" ]] || continue
        _DEVBOX_NVM_LAZY_TRIGGERS[${command_path:t}]=1
    done
}
_nvm_lazy_collect_triggers

typeset -g _DEVBOX_NVM_LAZY_SCRIPT="${DEVBOX_NVM_LAZY_SCRIPT:-}"
typeset +x _DEVBOX_NVM_LAZY_SCRIPT
unset DEVBOX_NVM_LAZY_SCRIPT
typeset -gi _NVM_LAZY_LOADED=0
typeset -gi _DEVBOX_NVM_LAZY_PREEXEC_STATUS=0
if [[ -n "$_DEVBOX_NVM_LAZY_SCRIPT" ]]; then
    if [[ "$_DEVBOX_NVM_LAZY_SCRIPT" = /* && -f "$_DEVBOX_NVM_LAZY_SCRIPT" && -r "$_DEVBOX_NVM_LAZY_SCRIPT" ]]; then
        _DEVBOX_NVM_LAZY_SCRIPT="${_DEVBOX_NVM_LAZY_SCRIPT:A}"
    else
        _DEVBOX_NVM_LAZY_SCRIPT=
    fi
elif [[ -f "/opt/homebrew/opt/nvm/nvm.sh" && -r "/opt/homebrew/opt/nvm/nvm.sh" ]]; then
    _DEVBOX_NVM_LAZY_SCRIPT="/opt/homebrew/opt/nvm/nvm.sh"
elif [[ -f "/usr/local/opt/nvm/nvm.sh" && -r "/usr/local/opt/nvm/nvm.sh" ]]; then
    _DEVBOX_NVM_LAZY_SCRIPT="/usr/local/opt/nvm/nvm.sh"
fi

typeset -gA _DEVBOX_NVM_LAZY_PROXY_BODIES

_nvm_lazy_install_proxies() {
    local command
    for command in "$@"; do
        case "$command" in
            nvm) function nvm { _nvm_lazy_run nvm "$@"; } ;;
            node) function node { _nvm_lazy_run node "$@"; } ;;
            npm) function npm { _nvm_lazy_run npm "$@"; } ;;
            npx) function npx { _nvm_lazy_run npx "$@"; } ;;
            corepack) function corepack { _nvm_lazy_run corepack "$@"; } ;;
            pnpm) function pnpm { _nvm_lazy_run pnpm "$@"; } ;;
            yarn) function yarn { _nvm_lazy_run yarn "$@"; } ;;
            yarnpkg) function yarnpkg { _nvm_lazy_run yarnpkg "$@"; } ;;
        esac
        _DEVBOX_NVM_LAZY_PROXY_BODIES[$command]=$(functions "$command")
    done
}

_nvm_lazy_load() {
    local source_status command
    local -a removed_proxies=()

    (( _NVM_LAZY_LOADED )) && return 0
    if (( ! _NVM_LAZY_LOADED )); then
        if [[ "$_DEVBOX_NVM_LAZY_SCRIPT" != /* || ! -f "$_DEVBOX_NVM_LAZY_SCRIPT" || ! -r "$_DEVBOX_NVM_LAZY_SCRIPT" ]]; then
            print -u2 -- 'nvm lazy-loading: nvm.sh not found'
            return 127
        fi

        for command in nvm node npm npx corepack pnpm yarn yarnpkg; do
            if (( $+functions[$command] )) && [[ "$(functions "$command")" == "${_DEVBOX_NVM_LAZY_PROXY_BODIES[$command]}" ]]; then
                unfunction "$command"
                removed_proxies+=("$command")
            fi
        done
        if source "$_DEVBOX_NVM_LAZY_SCRIPT"; then
            source_status=0
        else
            source_status=$?
        fi
        if (( source_status != 0 )); then
            _nvm_lazy_install_proxies "${removed_proxies[@]}"
            print -u2 -- "nvm lazy-loading: failed to source $_DEVBOX_NVM_LAZY_SCRIPT (status $source_status)"
            return "$source_status"
        fi
        _NVM_LAZY_LOADED=1
    fi
}

_nvm_lazy_run() {
    if (( $# == 0 )); then
        print -u2 -- 'nvm lazy-loading: no command requested'
        return 2
    fi

    local requested_command=$1 source_status
    shift
    local -a requested_args=("$@")
    set --

    if (( _DEVBOX_NVM_LAZY_PREEXEC_STATUS != 0 )); then
        source_status=$_DEVBOX_NVM_LAZY_PREEXEC_STATUS
        return "$source_status"
    fi

    if _nvm_lazy_load; then
        :
    else
        source_status=$?
        return "$source_status"
    fi

    if (( ! $+functions[$requested_command] && ! $+commands[$requested_command] )); then
        print -u2 -- "nvm lazy-loading: command '$requested_command' is unavailable"
        return 127
    fi

    "$requested_command" "${requested_args[@]}"
}

# Lexical command-position detection for direct commands, assignments,
# pipelines, backgrounds, redirects, groups, and bounded substitutions. The
# ${(z)} lexer keeps quote/escape boundaries; recursive scanning only examines
# unquoted $(), backticks, and process substitutions, avoiding raw substring
# matches such as `echo 'literal; node'`.
_nvm_lazy_token_subcommands() {
    local token=$1 depth=${2:-0}
    (( depth >= 3 )) && return 1
    local i j char quote='' escaped=0 inner nested token_length=${#token}
    local inner_quote inner_escaped
    for (( i = 1; i <= token_length; i++ )); do
        char=${token[i]}
        if (( escaped )); then
            escaped=0
            continue
        fi
        if [[ "$char" == \\ ]]; then
            escaped=1
            continue
        fi
        if [[ "$quote" == "'" ]]; then
            [[ "$char" == "'" ]] && quote=
            continue
        elif [[ "$quote" == '"' ]]; then
            [[ "$char" == '"' ]] && { quote=; continue; }
        elif [[ "$char" == "'" || "$char" == '"' ]]; then
            quote=$char
            continue
        fi
        if [[ "$char" == '`' ]]; then
            inner=
            inner_quote=''
            inner_escaped=0
            for (( j = i + 1; j <= token_length; j++ )); do
                char=${token[j]}
                if (( inner_escaped )); then
                    inner_escaped=0
                    inner+="$char"
                    continue
                fi
                if [[ "$char" == \\ ]]; then
                    inner_escaped=1
                    inner+="$char"
                    continue
                fi
                if [[ "$inner_quote" == "'" ]]; then
                    inner+="$char"
                    [[ "$char" == "'" ]] && inner_quote=''
                    continue
                elif [[ "$inner_quote" == '"' ]]; then
                    inner+="$char"
                    [[ "$char" == '"' ]] && inner_quote=''
                    continue
                elif [[ "$char" == "'" || "$char" == '"' ]]; then
                    inner_quote=$char
                    inner+="$char"
                    continue
                fi
                [[ "$char" == '`' ]] && break
                inner+="$char"
            done
            _nvm_lazy_command_needed "$inner" "$((depth + 1))" && return 0
            i=$j
            continue
        fi
        # Arithmetic expansion starts with $(( and contains no command.
        if [[ "${token[i,i+1]}" == '$(' && "${token[i+2]}" == '(' ]]; then
            continue
        fi
        if [[ "${token[i,i+1]}" == '$(' || "${token[i,i+1]}" == '<(' || "${token[i,i+1]}" == '>(' || "${token[i,i+1]}" == '=(' ]]; then
            inner=
            nested=1
            inner_quote=''
            inner_escaped=0
            for (( j = i + 2; j <= token_length; j++ )); do
                char=${token[j]}
                if (( inner_escaped )); then
                    inner_escaped=0
                    inner+="$char"
                    continue
                fi
                if [[ "$char" == \\ ]]; then
                    inner_escaped=1
                    inner+="$char"
                    continue
                fi
                if [[ "$inner_quote" == "'" ]]; then
                    inner+="$char"
                    [[ "$char" == "'" ]] && inner_quote=''
                    continue
                elif [[ "$inner_quote" == '"' ]]; then
                    inner+="$char"
                    [[ "$char" == '"' ]] && inner_quote=''
                    continue
                elif [[ "$char" == "'" || "$char" == '"' ]]; then
                    inner_quote=$char
                    inner+="$char"
                    continue
                fi
                [[ "$char" == '(' ]] && (( nested++ ))
                if [[ "$char" == ')' ]]; then
                    (( nested-- ))
                    (( nested == 0 )) && break
                fi
                inner+="$char"
            done
            _nvm_lazy_command_needed "$inner" "$((depth + 1))" && return 0
            i=$j
        fi
    done
    return 1
}

_nvm_lazy_command_needed() {
    local command_line=$1 depth=${2:-0} token command_position=1 redirect_pending=0
    local -a tokens=( ${(z)command_line} )
    for token in "${tokens[@]}"; do
        _nvm_lazy_token_subcommands "$token" "$depth" && return 0
        if (( redirect_pending )); then
            redirect_pending=0
            continue
        fi
        if [[ "$token" =~ '^[0-9]*(>|>>|<|<<|<<<|<>|>\||>&|<&|&>|>>&)$' ]]; then
            redirect_pending=1
            continue
        fi
        case "$token" in
            ';'|'|'|'||'|'&'|'&&'|'('|'{') command_position=1; continue ;;
            ')'|'}') command_position=0; continue ;;
        esac
        (( command_position )) || continue
        if [[ "$token" =~ '^[[:alpha:]_][[:alnum:]_]*=' ]]; then
            continue
        fi
        [[ -n "${_DEVBOX_NVM_LAZY_TRIGGERS[$token]:-}" ]] && return 0
        command_position=0
    done
    return 1
}

_nvm_lazy_preexec() {
    _DEVBOX_NVM_LAZY_PREEXEC_STATUS=0
    (( _NVM_LAZY_LOADED )) && return 0
    [[ -n "$_DEVBOX_NVM_LAZY_SCRIPT" ]] || return 0
    if _nvm_lazy_command_needed "${1:-}"; then
        if _nvm_lazy_load; then
            :
        else
            _DEVBOX_NVM_LAZY_PREEXEC_STATUS=$?
        fi
    fi
    return 0
}

_nvm_lazy_register_preexec() {
    [[ $- == *i* ]] || return 0
    autoload -Uz add-zsh-hook
    add-zsh-hook -d preexec _nvm_lazy_preexec 2>/dev/null || :
    [[ -n "$_DEVBOX_NVM_LAZY_SCRIPT" ]] && add-zsh-hook preexec _nvm_lazy_preexec
}

if [[ -n "$_DEVBOX_NVM_LAZY_SCRIPT" ]]; then
    _nvm_lazy_install_proxies nvm node npm npx corepack pnpm yarn yarnpkg
fi
_nvm_lazy_register_preexec

# === pnpm ===
export PNPM_HOME="$HOME/Library/pnpm"
[[ -d "$PNPM_HOME" ]] && export PATH="$PNPM_HOME:$PATH"

# === JetBrains Toolbox ===
[[ -d "$HOME/.jetbrains" ]] && export PATH="$HOME/.jetbrains:$PATH"

# === .NET ===
[[ -d "$HOME/.dotnet" ]] && export PATH="$HOME/.dotnet:$PATH"
