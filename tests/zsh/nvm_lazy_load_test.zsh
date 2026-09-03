#!/usr/bin/env zsh

setopt nounset pipefail

typeset -r REPO_ROOT=${0:A:h:h:h}
typeset -r TEST_SCRIPT=${0:A}
typeset -r TOOLS_ZSH="$REPO_ROOT/chezmoi/private_dot_config/zsh/tools.zsh"
typeset -r OHMY_ZSH="$REPO_ROOT/chezmoi/private_dot_config/zsh/oh-my-zsh.zsh"
typeset -r TEST_CASE=${1:-all}
typeset -r CASE_HOME=${2:-$(mktemp -d "${TMPDIR:-/tmp}/nvm-lazy-test.XXXXXX")}
typeset -r TRIGGER_COMMAND=${3:-}
typeset CREATED_HOME=0
typeset CASE_FAILURES=0
[[ -n ${2:-} ]] || CREATED_HOME=1

cleanup() {
    if (( CREATED_HOME )); then
        rm -rf "$CASE_HOME"
    fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

fail() {
    print -u2 -- "FAIL: $*"
    CASE_FAILURES=$((CASE_FAILURES + 1))
    return 0
}

assert_eq() {
    local expected=$1 actual=$2 message=$3
    [[ "$actual" == "$expected" ]] || fail "$message (expected '$expected', got '$actual')"
}

assert_contains() {
    local needle=$1 haystack=$2 message=$3
    [[ "$haystack" == *"$needle"* ]] || fail "$message (missing '$needle')"
}

source_tools() {
    local source_status=0
    if ! zsh -n "$TOOLS_ZSH"; then
        fail "tools.zsh has invalid Zsh syntax"
        return
    fi
    source "$TOOLS_ZSH" || source_status=$?
    # The file ends in a legitimate optional-directory conditional, which can return 1.
    if (( source_status != 0 && source_status != 1 )); then
        fail "sourcing tools.zsh failed unexpectedly (status $source_status)"
    fi
}

has_lazy_proxy_functions() {
    local command body
    for command in nvm node npm npx corepack pnpm yarn yarnpkg; do
        (( $+functions[$command] )) || return 1
        body=$(functions "$command")
        [[ "$body" == *_nvm_lazy_run* ]] || return 1
    done
}

has_no_lazy_proxy_functions() {
    local command
    for command in nvm node npm npx corepack pnpm yarn yarnpkg; do
        (( $+functions[$command] )) && return 1
    done
    return 0
}

run_case_1() {
    export HOME="$CASE_HOME"
    typeset sentinel="$CASE_HOME/nvm-script-sourced"
    print -r -- 'print -r -- loaded > "$NVM_LAZY_SENTINEL"' > "$CASE_HOME/sentinel-nvm.sh"
    export DEVBOX_NVM_LAZY_SCRIPT="$CASE_HOME/sentinel-nvm.sh" NVM_LAZY_SENTINEL="$sentinel"
    source_tools

    assert_eq 0 "${_NVM_LAZY_LOADED:-unset}" "sourcing tools.zsh does not load NVM"
    [[ ! -e "$sentinel" ]] || fail 'sourcing tools.zsh does not execute the lazy NVM script'
    [[ -z ${DEVBOX_NVM_LAZY_SCRIPT+x} ]] || fail 'public NVM lazy override is unset after sourcing'
    local script_snapshot
    script_snapshot=$(typeset -p _DEVBOX_NVM_LAZY_SCRIPT 2>/dev/null)
    [[ -n "$script_snapshot" ]] || fail 'internal NVM lazy script snapshot is retained'
    [[ "$script_snapshot" != export\ _DEVBOX_NVM_LAZY_SCRIPT=* ]] || fail 'internal NVM lazy script snapshot is not exported'
    local command body
    for command in nvm node npm npx corepack pnpm yarn yarnpkg; do
        (( $+functions[$command] )) || fail "$command lazy proxy is defined"
        body=$(functions "$command")
        assert_contains _nvm_lazy_run "$body" "$command proxy dispatches through _nvm_lazy_run"
    done
}

write_fake_nvm() {
    local fake_script=$1 log_file=$2 count_file=$3
    print -r -- 'print -r -- $# > "$NVM_LAZY_SOURCE_ARGS"' > "$fake_script"
    print -r -- '(( $# == 0 )) || return 91' >> "$fake_script"
    print -r -- 'if [[ -f "$_NVM_LAZY_COUNT" ]]; then _nvm_load_count=$(<"$_NVM_LAZY_COUNT"); else _nvm_load_count=0; fi' >> "$fake_script"
    print -r -- 'print -r -- $((_nvm_load_count + 1)) > "$_NVM_LAZY_COUNT"' >> "$fake_script"
    print -r -- '_nvm_fake_record() { print -r -- "$1|${(j:|:)@[2,-1]}" >> "$_NVM_LAZY_LOG"; }' >> "$fake_script"
    local command
    for command in nvm node npm npx corepack pnpm yarn yarnpkg; do
        if [[ "$command" == node ]]; then
            print -r -- "$command() { _nvm_fake_record $command \"\$@\"; [[ \"\${1:-}\" == exit-code ]] && return 73; return 0; }" >> "$fake_script"
        else
            print -r -- "$command() { _nvm_fake_record $command \"\$@\"; return 0; }" >> "$fake_script"
        fi
    done
}

run_case_2() {
    export HOME="$CASE_HOME"
    typeset fake_script="$CASE_HOME/fake-nvm.sh"
    typeset log_file="$CASE_HOME/calls.log"
    typeset count_file="$CASE_HOME/load-count"
    : > "$log_file"
    print -r -- 0 > "$count_file"
    typeset source_args_file="$CASE_HOME/source-args-count"
    export _NVM_LAZY_LOG="$log_file" _NVM_LAZY_COUNT="$count_file" NVM_LAZY_SOURCE_ARGS="$source_args_file"
    write_fake_nvm "$fake_script" "$log_file" "$count_file"
    export DEVBOX_NVM_LAZY_SCRIPT="$fake_script"

    source_tools
    assert_eq 0 "${_NVM_LAZY_LOADED:-unset}" "sourcing tools.zsh leaves NVM unloaded"
    assert_eq 0 "$(<"$count_file")" 'fake nvm.sh is not loaded while sourcing tools.zsh'
    if ! has_lazy_proxy_functions; then
        fail 'dispatch requires nvm, node, and pnpm lazy proxies'
        return
    fi
    cd "$CASE_HOME"
    node alpha "beta gamma"
    npm install
    pnpm --version
    node exit-code >/dev/null 2>&1
    local exit_code=$?
    assert_eq 73 "$exit_code" "proxy forwards the command exit status"

    assert_eq 1 "$(<"$count_file")" "fake nvm.sh is loaded exactly once"
    assert_eq 0 "$(<"$source_args_file")" "nvm.sh receives no target arguments"
    grep -Fqx 'node|alpha|beta gamma' "$log_file" || fail 'node preserves both arguments'
    grep -Fqx 'npm|install' "$log_file" || fail 'npm dispatches with its argument'
    grep -Fqx 'pnpm|--version' "$log_file" || fail 'pnpm dispatches with its argument'
}

run_case_3() {
    export HOME="$CASE_HOME"
    typeset nvm_script="$CASE_HOME/nvm.sh"
    print -r -- 'nvm() { return 0; }' > "$nvm_script"
    export DEVBOX_NVM_LAZY_SCRIPT="$nvm_script"
    source_tools
    if ! has_lazy_proxy_functions; then
        fail 'disappearing-script check requires the nvm lazy proxies'
        return
    fi
    rm "$nvm_script"
    local stderr exit_code
    stderr=$(nvm use 2>&1 >/dev/null)
    exit_code=$?
    assert_eq 127 "$exit_code" "disappearing nvm.sh returns 127"
    assert_contains 'nvm.sh not found' "$stderr" "disappearing nvm.sh reports the error"
}

run_case_4() {
    export HOME="$CASE_HOME"
    typeset fake_script="$CASE_HOME/failing-nvm.sh"
    typeset count_file="$CASE_HOME/load-count"
    print -r -- 0 > "$count_file"
    print -r -- 'if [[ -f "$_NVM_LAZY_COUNT" ]]; then _nvm_load_count=$(<"$_NVM_LAZY_COUNT"); else _nvm_load_count=0; fi' > "$fake_script"
    print -r -- 'print -r -- $((_nvm_load_count + 1)) > "$_NVM_LAZY_COUNT"' >> "$fake_script"
    print -r -- 'node() { return 99; }' >> "$fake_script"
    print -r -- 'return 42' >> "$fake_script"
    export DEVBOX_NVM_LAZY_SCRIPT="$fake_script" _NVM_LAZY_COUNT="$count_file"

    source_tools
    if ! has_lazy_proxy_functions; then
        fail 'source failure case starts with all lazy proxies installed'
        return
    fi
    local stderr stderr_file exit_code
    stderr_file="$CASE_HOME/source-failure.stderr"
    node first-call >/dev/null 2>"$stderr_file"
    exit_code=$?
    stderr=$(<"$stderr_file")
    assert_eq 42 "$exit_code" 'source failure returns the exact source status'
    assert_contains 'failed to source' "$stderr" 'source failure reports a clear diagnostic'
    assert_eq 0 "${_NVM_LAZY_LOADED:-unset}" 'source failure leaves NVM unloaded'
    assert_eq 1 "$(<"$count_file")" 'source failure attempts the first load once'
    has_lazy_proxy_functions || fail 'source failure reinstalls all lazy proxies'

    node second-call >/dev/null 2>"$stderr_file"
    exit_code=$?
    stderr=$(<"$stderr_file")
    assert_eq 42 "$exit_code" 'source failure can be retried with the same status'
    assert_eq 2 "$(<"$count_file")" 'source failure retries loading'
    has_lazy_proxy_functions || fail 'source retry leaves all lazy proxies installed'
}

run_case_5() {
    export HOME="$CASE_HOME"
    mkdir -p "$CASE_HOME/bin"
    export PATH="$CASE_HOME/bin:/bin:/usr/bin"
    typeset fake_script="$CASE_HOME/incomplete-nvm.sh"
    print -r -- 'print -r -- loaded > "$NVM_LAZY_SENTINEL"' > "$fake_script"
    typeset sentinel="$CASE_HOME/nvm-script-sourced"
    export DEVBOX_NVM_LAZY_SCRIPT="$fake_script" NVM_LAZY_SENTINEL="$sentinel"

    source_tools
    local stderr stderr_file exit_code
    stderr_file="$CASE_HOME/unavailable-command.stderr"
    node unavailable >/dev/null 2>"$stderr_file"
    exit_code=$?
    stderr=$(<"$stderr_file")
    assert_eq 127 "$exit_code" 'successful load with unavailable command returns 127'
    assert_contains 'command '\''node'\'' is unavailable' "$stderr" 'unavailable command reports a clear diagnostic'
    [[ -e "$sentinel" ]] || fail 'successful load executes the selected NVM script'
    assert_eq 1 "${_NVM_LAZY_LOADED:-unset}" 'successful source marks NVM loaded'
}

run_case_6() {
    export HOME="$CASE_HOME"
    mkdir -p "$CASE_HOME/relative"
    typeset sentinel="$CASE_HOME/relative-nvm-script-sourced"
    print -r -- 'print -r -- loaded > "$NVM_LAZY_SENTINEL"' > "$CASE_HOME/relative/nvm.sh"
    export DEVBOX_NVM_LAZY_SCRIPT='relative/nvm.sh' NVM_LAZY_SENTINEL="$sentinel"

    source_tools
    has_no_lazy_proxy_functions || fail 'relative NVM override does not install lazy proxies'
    cd "$CASE_HOME"
    [[ ! -e "$sentinel" ]] || fail 'relative NVM override is never sourced'
    [[ -z ${DEVBOX_NVM_LAZY_SCRIPT+x} ]] || fail 'relative NVM override is unset after sourcing'
    local script_snapshot
    script_snapshot=$(typeset -p _DEVBOX_NVM_LAZY_SCRIPT 2>/dev/null)
    [[ -n "$script_snapshot" ]] || fail 'internal NVM lazy script snapshot is retained'
    [[ "$script_snapshot" != export\ _DEVBOX_NVM_LAZY_SCRIPT=* ]] || fail 'internal NVM lazy script snapshot is not exported'
}

run_case_7() {
    export HOME="$CASE_HOME"
    typeset fake_script="$CASE_HOME/alias-safe-nvm.sh"
    print -r -- 'print -r -- loaded > "$NVM_LAZY_SENTINEL"' > "$fake_script"
    export DEVBOX_NVM_LAZY_SCRIPT="$fake_script" NVM_LAZY_SENTINEL="$CASE_HOME/nvm-script-sourced"
    setopt aliases
    alias node='print -r -- host-node-alias'

    source_tools
    has_lazy_proxy_functions || fail 'existing node alias does not prevent lazy proxy installation'
    (( $+functions[node] )) || fail 'node proxy is defined with an existing node alias'
}

run_case_8() {
    if [[ -z "$TRIGGER_COMMAND" ]]; then
        local command failures=0
        for command in nvm node npm npx corepack pnpm yarn yarnpkg; do
            if ! zsh -f "$TEST_SCRIPT" 8 '' "$command"; then
                (( failures++ ))
            fi
        done
        (( failures == 0 )) || return 1
        return 0
    fi

    export HOME="$CASE_HOME"
    typeset fake_script="$CASE_HOME/fake-nvm.sh"
    typeset log_file="$CASE_HOME/calls.log"
    typeset count_file="$CASE_HOME/load-count"
    typeset source_args_file="$CASE_HOME/source-args-count"
    : > "$log_file"
    print -r -- 0 > "$count_file"
    export _NVM_LAZY_LOG="$log_file" _NVM_LAZY_COUNT="$count_file" NVM_LAZY_SOURCE_ARGS="$source_args_file"
    write_fake_nvm "$fake_script" "$log_file" "$count_file"
    export DEVBOX_NVM_LAZY_SCRIPT="$fake_script"

    source_tools
    assert_eq 0 "${_NVM_LAZY_LOADED:-unset}" 'table-driven trigger starts unloaded'
    "$TRIGGER_COMMAND" first-arg 'second arg'
    local exit_code=$?
    assert_eq 0 "$exit_code" "$TRIGGER_COMMAND forwards a normal exit status"
    assert_eq 1 "$(<"$count_file")" "$TRIGGER_COMMAND loads NVM exactly once"
    assert_eq 0 "$(<"$source_args_file")" "$TRIGGER_COMMAND gives nvm.sh zero source arguments"
    grep -Fqx "$TRIGGER_COMMAND|first-arg|second arg" "$log_file" || fail "$TRIGGER_COMMAND forwards both arguments"
}

run_case_9() {
    export HOME="$CASE_HOME"
    typeset fake_script="$CASE_HOME/success-nvm.sh"
    print -r -- 'node() { return 0; }' > "$fake_script"
    export DEVBOX_NVM_LAZY_SCRIPT="$fake_script"
    source_tools
    function yarn { print -r -- user-yarn; return 19; }

    node trigger >/dev/null
    local exit_code=$?
    assert_eq 0 "$exit_code" 'successful trigger loads the requested command'
    local output
    output=$(yarn)
    exit_code=$?
    assert_eq 19 "$exit_code" 'user yarn function survives a successful trigger'
    assert_eq user-yarn "$output" 'user yarn function remains callable after a successful trigger'
}

run_case_10() {
    export HOME="$CASE_HOME"
    typeset fake_script="$CASE_HOME/failing-nvm.sh"
    print -r -- 'node() { return 99; }' > "$fake_script"
    print -r -- 'return 42' >> "$fake_script"
    export DEVBOX_NVM_LAZY_SCRIPT="$fake_script"
    source_tools
    function yarn { print -r -- user-yarn; return 19; }

    local stderr stderr_file exit_code
    stderr_file="$CASE_HOME/ownership-failure.stderr"
    node trigger >/dev/null 2>"$stderr_file"
    exit_code=$?
    stderr=$(<"$stderr_file")
    assert_eq 42 "$exit_code" 'failed trigger returns the exact source status'
    assert_contains 'failed to source' "$stderr" 'failed trigger reports a diagnostic'
    local output
    output=$(yarn)
    exit_code=$?
    assert_eq 19 "$exit_code" 'user yarn function survives a failed trigger'
    assert_eq user-yarn "$output" 'user yarn function remains callable after a failed trigger'
    local body
    body=$(functions node)
    assert_contains _nvm_lazy_run "$body" 'failed trigger restores only the owned node proxy'
}

run_case_11() {
    export HOME="$CASE_HOME"
    typeset fake_script="$CASE_HOME/err-return-nvm.sh"
    print -r -- 'node() { return 99; }' > "$fake_script"
    print -r -- 'return 42' >> "$fake_script"
    export DEVBOX_NVM_LAZY_SCRIPT="$fake_script"
    source_tools

    local stderr stderr_file result_file result exit_code
    stderr_file="$CASE_HOME/err-return.stderr"
    result_file="$CASE_HOME/err-return.result"
    (
        setopt err_return
        _nvm_lazy_err_return_result() {
            local exit_status=$?
            print -r -- "$exit_status|${_NVM_LAZY_LOADED:-unset}|$+functions[nvm]|$+functions[node]|$+functions[npm]|$+functions[npx]|$+functions[corepack]|$+functions[pnpm]|$+functions[yarn]|$+functions[yarnpkg]" > "$result_file"
            return "$exit_status"
        }
        trap _nvm_lazy_err_return_result EXIT
        node trigger >/dev/null 2>"$stderr_file"
    )
    exit_code=$?
    stderr=$(<"$stderr_file")
    result=$(<"$result_file")
    assert_eq 42 "$exit_code" 'ERR_RETURN preserves the exact source status'
    assert_contains 'failed to source' "$stderr" 'ERR_RETURN still reports the source failure'
    assert_contains '42|0|1|1|1|1|1|1|1|1' "$result" 'ERR_RETURN leaves NVM unloaded and restores all removed lazy proxies'
}

run_case_12() {
    export HOME="$CASE_HOME"
    typeset target_a="$CASE_HOME/nvm-a.sh"
    typeset target_b="$CASE_HOME/nvm-b.sh"
    typeset script_link="$CASE_HOME/nvm-link.sh"
    typeset marker_a="$CASE_HOME/sourced-a"
    typeset marker_b="$CASE_HOME/sourced-b"
    print -r -- 'print -r -- loaded-a > "$NVM_LAZY_MARKER_A"; node() { return 0; }' > "$target_a"
    print -r -- 'print -r -- loaded-b > "$NVM_LAZY_MARKER_B"; node() { return 0; }' > "$target_b"
    ln -s "$target_a" "$script_link"
    export DEVBOX_NVM_LAZY_SCRIPT="$script_link" NVM_LAZY_MARKER_A="$marker_a" NVM_LAZY_MARKER_B="$marker_b"

    source_tools
    rm "$script_link"
    ln -s "$target_b" "$script_link"
    node trigger >/dev/null
    local exit_code=$?
    assert_eq 0 "$exit_code" 'canonicalized override dispatches successfully'
    [[ -e "$marker_a" ]] || fail 'canonicalized override sources the original symlink target'
    [[ ! -e "$marker_b" ]] || fail 'canonicalized override does not follow a retargeted symlink'
}

run_case_13() {
    export HOME="$CASE_HOME"
    typeset bin_dir="$CASE_HOME/bin"
    typeset log_file="$CASE_HOME/standalone.log"
    mkdir -p "$bin_dir"
    export PATH="$bin_dir:/bin:/usr/bin" NVM_STANDALONE_LOG="$log_file"
    local command
    for command in node npm pnpm yarn; do
        print -r -- "#!/bin/sh" > "$bin_dir/$command"
        print -r -- 'printf "%s|%s|%s\\n" "${0##*/}" "${1:-}" "${2:-}" >> "$NVM_STANDALONE_LOG"' >> "$bin_dir/$command"
        print -r -- '[ "${1:-}" = exit-code ] && exit 73' >> "$bin_dir/$command"
        print -r -- 'exit 0' >> "$bin_dir/$command"
        chmod +x "$bin_dir/$command"
    done
    export DEVBOX_NVM_LAZY_SCRIPT="$CASE_HOME/no-nvm.sh"

    source_tools
    has_no_lazy_proxy_functions || fail 'no-NVM source installs no lazy proxies'
    node first-arg 'second arg'
    local exit_code=$?
    assert_eq 0 "$exit_code" 'standalone node preserves normal status'
    npm install 'second arg'
    assert_eq 0 "$?" 'standalone npm preserves normal status'
    pnpm --version
    assert_eq 0 "$?" 'standalone pnpm preserves normal status'
    yarn workspaces list
    assert_eq 0 "$?" 'standalone yarn preserves normal status'
    node exit-code >/dev/null
    assert_eq 73 "$?" 'standalone node preserves nonzero status'
    grep -Fqx 'node|first-arg|second arg' "$log_file" || fail 'standalone node preserves both arguments'
    grep -Fqx 'npm|install|second arg' "$log_file" || fail 'standalone npm preserves both arguments'
    grep -Fqx 'pnpm|--version|' "$log_file" || fail 'standalone pnpm preserves its argument'
    grep -Fqx 'yarn|workspaces|list' "$log_file" || fail 'standalone yarn preserves both arguments'
}

run_case_14() {
    export HOME="$CASE_HOME"
    typeset fake_zsh="$CASE_HOME/fake-oh-my-zsh"
    typeset fake_nvm="$CASE_HOME/fake-nvm.sh"
    typeset load_count="$CASE_HOME/nvm-load-count"
    mkdir -p "$fake_zsh"
    print -r -- 'prompt_nvm() { nvm current; }' > "$fake_zsh/oh-my-zsh.sh"
    print -r -- 'if [[ -f "$NVM_PROMPT_LOAD_COUNT" ]]; then _count=$(<"$NVM_PROMPT_LOAD_COUNT"); else _count=0; fi' > "$fake_nvm"
    print -r -- 'print -r -- $((_count + 1)) > "$NVM_PROMPT_LOAD_COUNT"' >> "$fake_nvm"
    print -r -- 'nvm() { print -r -- v20.11.0; return 0; }' >> "$fake_nvm"
    print -r -- 'node() { return 0; }' >> "$fake_nvm"
    print -r -- 0 > "$load_count"
    export ZSH="$fake_zsh" DEVBOX_NVM_LAZY_SCRIPT="$fake_nvm" NVM_PROMPT_LOAD_COUNT="$load_count"

    source "$OHMY_ZSH"
    source "$OHMY_ZSH"
    source_tools
    assert_eq 0 "$(<"$load_count")" 'prompt integration starts with no NVM loads'
    local prompt_before_one prompt_before_two prompt_after
    prompt_before_one=$(prompt_nvm)
    prompt_before_two=$(prompt_nvm)
    assert_eq '' "$prompt_before_one" 'first pre-command prompt skips lazy NVM'
    assert_eq '' "$prompt_before_two" 'second pre-command prompt skips lazy NVM'
    assert_eq 0 "$(<"$load_count")" 'pre-command prompts do not source NVM'
    node integration >/dev/null
    assert_eq 1 "$(<"$load_count")" 'user node command sources NVM once'
    assert_eq 1 "${_NVM_LAZY_LOADED:-unset}" 'user node command marks NVM loaded'
    prompt_after=$(prompt_nvm)
    assert_eq v20.11.0 "$prompt_after" 'post-load prompt delegates to original prompt_nvm'
    assert_eq 1 "$(<"$load_count")" 'post-load prompt does not reload NVM'
}

run_interactive_case() {
    local scenario=$1
    typeset fake_script="$CASE_HOME/interactive-nvm.sh"
    typeset count_file="$CASE_HOME/interactive-load-count"
    typeset before_file="$CASE_HOME/interactive-before-loaded"
    typeset after_file="$CASE_HOME/interactive-after-loaded"
    typeset input_file="$CASE_HOME/interactive-input"
    typeset session_file="$CASE_HOME/interactive-session"
    mkdir -p "$CASE_HOME/bin"
    print -r -- 0 > "$count_file"
    print -r -- 'if [[ -f "$NVM_LAZY_COUNT" ]]; then _count=$(<"$NVM_LAZY_COUNT"); else _count=0; fi' > "$fake_script"
    print -r -- 'print -r -- $((_count + 1)) > "$NVM_LAZY_COUNT"' >> "$fake_script"
    print -r -- 'node() { print -r -- v20.11.0; return 0; }' >> "$fake_script"
    print -r -- 'npm() { return 0; }' >> "$fake_script"
    print -r -- 'npx() { return 0; }' >> "$fake_script"
    print -r -- 'corepack() { return 0; }' >> "$fake_script"
    print -r -- 'pnpm() { return 0; }' >> "$fake_script"
    print -r -- 'yarn() { return 0; }' >> "$fake_script"
    print -r -- 'yarnpkg() { return 0; }' >> "$fake_script"
    print -r -- 'nvm() { print -r -- v20.11.0; return 0; }' >> "$fake_script"
    if [[ "$scenario" == negative ]]; then
        print -r -- '#!/bin/sh' > "$CASE_HOME/bin/rg"
        print -r -- 'exit 0' >> "$CASE_HOME/bin/rg"
        chmod +x "$CASE_HOME/bin/rg"
    fi
    print -r -- "export HOME=\"$CASE_HOME\" DEVBOX_NVM_LAZY_SCRIPT=\"$fake_script\" NVM_LAZY_COUNT=\"$count_file\"" > "$input_file"
    if [[ "$scenario" == negative ]]; then
        print -r -- "export PATH=\"$CASE_HOME/bin:\$PATH\"" >> "$input_file"
    fi
    print -r -- "source \"$TOOLS_ZSH\"" >> "$input_file"
    print -r -- "print -r -- \${_NVM_LAZY_LOADED:-unset} > \"$before_file\"" >> "$input_file"
    case "$scenario" in
        substitution) print -r -- 'value=$(node --version)' >> "$input_file" ;;
        pipeline) print -r -- 'node --version | cat >/dev/null' >> "$input_file" ;;
        background) print -r -- 'node --version >/dev/null & wait' >> "$input_file" ;;
        redirect) print -r -- 'node>/dev/null & wait' >> "$input_file" ;;
        negative)
            print -r -- 'echo node >/dev/null' >> "$input_file"
            print -r -- 'rg node >/dev/null' >> "$input_file"
            ;;
    esac
    print -r -- "print -r -- \${_NVM_LAZY_LOADED:-unset} > \"$after_file\"" >> "$input_file"
    print -r -- 'exit' >> "$input_file"

    zsh -fi < "$input_file" > "$session_file" 2>&1
    local shell_status=$?
    assert_eq 0 "$shell_status" "$scenario interactive shell exits successfully"
    assert_eq 0 "$(<"$before_file")" "$scenario starts unloaded before command"
    if [[ "$scenario" == negative ]]; then
        assert_eq 0 "$(<"$count_file")" "$scenario mentions do not load NVM"
        assert_eq 0 "$(<"$after_file")" "$scenario mentions leave NVM unloaded"
    else
        assert_eq 1 "$(<"$count_file")" "$scenario loads NVM exactly once in the parent"
        assert_eq 1 "$(<"$after_file")" "$scenario leaves the parent loaded"
    fi
}

run_case_15() { run_interactive_case substitution; }
run_case_16() { run_interactive_case pipeline; }
run_case_17() { run_interactive_case background; }
run_case_18() { run_interactive_case negative; }
run_case_19() { run_interactive_case redirect; }

run_case_20() {
    export HOME="$CASE_HOME"
    typeset fake_script="$CASE_HOME/preexec-failing-nvm.sh"
    typeset count_file="$CASE_HOME/preexec-failing-load-count"
    typeset status_file="$CASE_HOME/preexec-failing-status"
    typeset second_status_file="$CASE_HOME/preexec-failing-second-status"
    typeset same_command_count_file="$CASE_HOME/preexec-failing-same-command-count"
    typeset third_status_file="$CASE_HOME/preexec-failing-third-status"
    typeset loaded_file="$CASE_HOME/preexec-failing-loaded"
    typeset proxy_file="$CASE_HOME/preexec-failing-proxies"
    typeset input_file="$CASE_HOME/preexec-failing-input"
    typeset session_file="$CASE_HOME/preexec-failing-session"
    print -r -- 0 > "$count_file"
    print -r -- 'if [[ -f "$NVM_LAZY_COUNT" ]]; then _count=$(<"$NVM_LAZY_COUNT"); else _count=0; fi' > "$fake_script"
    print -r -- 'print -r -- $((_count + 1)) > "$NVM_LAZY_COUNT"' >> "$fake_script"
    print -r -- 'node() { return 99; }' >> "$fake_script"
    print -r -- 'return 42' >> "$fake_script"
    print -r -- "export HOME=\"$CASE_HOME\" DEVBOX_NVM_LAZY_SCRIPT=\"$fake_script\" NVM_LAZY_COUNT=\"$count_file\"" > "$input_file"
    print -r -- "source \"$TOOLS_ZSH\"" >> "$input_file"
    print -r -- 'node first >/dev/null; print -r -- $? > '"$status_file"'; node second >/dev/null' >> "$input_file"
    print -r -- "print -r -- \$? > \"$second_status_file\"" >> "$input_file"
    print -r -- "print -r -- \$(<$count_file) > \"$same_command_count_file\"" >> "$input_file"
    print -r -- 'print -r -- separate-command' >> "$input_file"
    print -r -- 'node third >/dev/null' >> "$input_file"
    print -r -- "print -r -- \$? > \"$third_status_file\"" >> "$input_file"
    print -r -- "print -r -- \${_NVM_LAZY_LOADED:-unset} > \"$loaded_file\"" >> "$input_file"
    print -r -- "print -r -- \$+functions[nvm]\|\$+functions[node]\|\$+functions[npm]\|\$+functions[npx]\|\$+functions[corepack]\|\$+functions[pnpm]\|\$+functions[yarn]\|\$+functions[yarnpkg] > \"$proxy_file\"" >> "$input_file"
    print -r -- 'exit' >> "$input_file"

    zsh -fi < "$input_file" > "$session_file" 2>&1
    local shell_status=$?
    assert_eq 0 "$shell_status" 'failed preexec interactive shell exits successfully'
    assert_eq 2 "$(<"$count_file")" 'failed preexec retries only at the next command boundary'
    assert_eq 42 "$(<"$status_file")" 'failed preexec command returns the source status'
    assert_eq 42 "$(<"$second_status_file")" 'failed preexec caches failure across one submitted command line'
    assert_eq 1 "$(<"$same_command_count_file")" 'failed preexec attempts one load for both commands on one line'
    assert_eq 42 "$(<"$third_status_file")" 'failed preexec retries on the next submitted command'
    assert_eq 0 "$(<"$loaded_file")" 'failed preexec leaves the parent unloaded'
    assert_eq '1|1|1|1|1|1|1|1' "$(<"$proxy_file")" 'failed preexec restores all lazy proxies'
    local diagnostic_count
    diagnostic_count=$(grep -Fc 'failed to source' "$session_file" || true)
    assert_eq 2 "$diagnostic_count" 'failed preexec emits one diagnostic per load attempt'
}

run_case_21() {
    export HOME="$CASE_HOME" NVM_DIR="$CASE_HOME/.nvm"
    typeset nvm_bin="$NVM_DIR/versions/node/v-test/bin"
    typeset fake_script="$CASE_HOME/arbitrary-nvm.sh"
    typeset count_file="$CASE_HOME/arbitrary-load-count"
    typeset log_file="$CASE_HOME/tsc.log"
    typeset input_file="$CASE_HOME/arbitrary-input"
    typeset session_file="$CASE_HOME/arbitrary-session"
    mkdir -p "$nvm_bin"
    print -r -- '#!/bin/sh' > "$nvm_bin/tsc"
    print -r -- 'printf "%s|%s\\n" "${1:-}" "${2:-}" >> "$NVM_TSC_LOG"' >> "$nvm_bin/tsc"
    print -r -- 'exit 0' >> "$nvm_bin/tsc"
    chmod +x "$nvm_bin/tsc"
    print -r -- 0 > "$count_file"
    print -r -- 'if [[ -f "$NVM_TSC_COUNT" ]]; then _count=$(<"$NVM_TSC_COUNT"); else _count=0; fi' > "$fake_script"
    print -r -- 'print -r -- $((_count + 1)) > "$NVM_TSC_COUNT"' >> "$fake_script"
    print -r -- 'export PATH="$NVM_DIR/versions/node/v-test/bin:$PATH"' >> "$fake_script"
    print -r -- "export HOME=\"$CASE_HOME\" NVM_DIR=\"$NVM_DIR\" DEVBOX_NVM_LAZY_SCRIPT=\"$fake_script\" NVM_TSC_COUNT=\"$count_file\" NVM_TSC_LOG=\"$log_file\" PATH=\"/bin:/usr/bin\"" > "$input_file"
    print -r -- "source \"$TOOLS_ZSH\"" >> "$input_file"
    print -r -- 'tsc --version' >> "$input_file"
    print -r -- "print -r -- \$? > \"$CASE_HOME/arbitrary-status\"" >> "$input_file"
    print -r -- "print -r -- \${_NVM_LAZY_LOADED:-unset} > \"$CASE_HOME/arbitrary-loaded\"" >> "$input_file"
    print -r -- 'exit' >> "$input_file"

    zsh -fi < "$input_file" > "$session_file" 2>&1
    local shell_status=$?
    assert_eq 0 "$shell_status" 'arbitrary executable interactive shell exits successfully'
    assert_eq 0 "$(<"$CASE_HOME/arbitrary-status")" 'arbitrary NVM executable succeeds'
    assert_eq 1 "$(<"$count_file")" 'arbitrary NVM executable loads once'
    assert_eq 1 "$(<"$CASE_HOME/arbitrary-loaded")" 'arbitrary NVM executable loads the parent'
    grep -Fqx -- '--version|' "$log_file" || fail 'arbitrary NVM executable receives its arguments'
}

run_case_22() {
    export HOME="$CASE_HOME"
    typeset fake_script="$CASE_HOME/lexical-nvm.sh"
    typeset count_file="$CASE_HOME/lexical-load-count"
    typeset before_file="$CASE_HOME/lexical-before"
    typeset negative_file="$CASE_HOME/lexical-negative"
    typeset after_file="$CASE_HOME/lexical-after"
    typeset input_file="$CASE_HOME/lexical-input"
    typeset session_file="$CASE_HOME/lexical-session"
    print -r -- 0 > "$count_file"
    print -r -- 'if [[ -f "$NVM_LEXICAL_COUNT" ]]; then _count=$(<"$NVM_LEXICAL_COUNT"); else _count=0; fi' > "$fake_script"
    print -r -- 'print -r -- $((_count + 1)) > "$NVM_LEXICAL_COUNT"' >> "$fake_script"
    print -r -- 'node() { print -r -- v20.11.0; return 0; }' >> "$fake_script"
    print -r -- "export HOME=\"$CASE_HOME\" DEVBOX_NVM_LAZY_SCRIPT=\"$fake_script\" NVM_LEXICAL_COUNT=\"$count_file\" PATH=\"/bin:/usr/bin\"" > "$input_file"
    print -r -- "source \"$TOOLS_ZSH\"" >> "$input_file"
    print -r -- "print -r -- \${_NVM_LAZY_LOADED:-unset} > \"$before_file\"" >> "$input_file"
    print -r -- "echo 'literal; node --version' >/dev/null" >> "$input_file"
    print -r -- "print -r -- '\$(node --version)' >/dev/null" >> "$input_file"
    print -r -- "print -r -- '\\\$(node --version)' >/dev/null" >> "$input_file"
    print -r -- "print -r -- \$(<\"$count_file\") > \"$negative_file\"" >> "$input_file"
    print -r -- '(node --version >/dev/null)' >> "$input_file"
    print -r -- 'value=`node --version`' >> "$input_file"
    print -r -- 'cat <(node --version) >/dev/null' >> "$input_file"
    print -r -- "print -r -- \${_NVM_LAZY_LOADED:-unset} > \"$after_file\"" >> "$input_file"
    print -r -- 'exit' >> "$input_file"

    zsh -fi < "$input_file" > "$session_file" 2>&1
    local shell_status=$?
    assert_eq 0 "$shell_status" 'lexical parser interactive shell exits successfully'
    assert_eq 0 "$(<"$before_file")" 'lexical parser starts unloaded'
    assert_eq 0 "$(<"$negative_file")" 'quoted and escaped literals do not load NVM'
    assert_eq 1 "$(<"$count_file")" 'lexical command forms load NVM once'
    assert_eq 1 "$(<"$after_file")" 'lexical command forms leave parent loaded'
}

run_case_23() {
    export HOME="$CASE_HOME"
    typeset fake_script="$CASE_HOME/assignment-nvm.sh"
    typeset count_file="$CASE_HOME/assignment-load-count"
    typeset input_file="$CASE_HOME/assignment-input"
    typeset session_file="$CASE_HOME/assignment-session"
    print -r -- 0 > "$count_file"
    print -r -- 'if [[ -f "$NVM_ASSIGNMENT_COUNT" ]]; then _count=$(<"$NVM_ASSIGNMENT_COUNT"); else _count=0; fi' > "$fake_script"
    print -r -- 'print -r -- $((_count + 1)) > "$NVM_ASSIGNMENT_COUNT"' >> "$fake_script"
    print -r -- 'node() { print -r -- v20.11.0; return 0; }' >> "$fake_script"
    print -r -- "export HOME=\"$CASE_HOME\" DEVBOX_NVM_LAZY_SCRIPT=\"$fake_script\" NVM_ASSIGNMENT_COUNT=\"$count_file\" PATH=\"/bin:/usr/bin\"" > "$input_file"
    print -r -- "source \"$TOOLS_ZSH\"" >> "$input_file"
    print -r -- 'FOO=bar node --version | cat >/dev/null' >> "$input_file"
    print -r -- "print -r -- \${_NVM_LAZY_LOADED:-unset} > \"$CASE_HOME/assignment-loaded\"" >> "$input_file"
    print -r -- 'exit' >> "$input_file"

    zsh -fi < "$input_file" > "$session_file" 2>&1
    local shell_status=$?
    assert_eq 0 "$shell_status" 'assignment command interactive shell exits successfully'
    assert_eq 1 "$(<"$count_file")" 'assignment command loads NVM once'
    assert_eq 1 "$(<"$CASE_HOME/assignment-loaded")" 'assignment command loads the parent'
}

run_process_substitution_case() {
    local process_form=$1
    typeset fake_script="$CASE_HOME/process-${process_form}-nvm.sh"
    typeset count_file="$CASE_HOME/process-${process_form}-load-count"
    typeset input_file="$CASE_HOME/process-${process_form}-input"
    typeset session_file="$CASE_HOME/process-${process_form}-session"
    export HOME="$CASE_HOME"
    print -r -- 0 > "$count_file"
    print -r -- 'if [[ -f "$NVM_PROCESS_COUNT" ]]; then _count=$(<"$NVM_PROCESS_COUNT"); else _count=0; fi' > "$fake_script"
    print -r -- 'print -r -- $((_count + 1)) > "$NVM_PROCESS_COUNT"' >> "$fake_script"
    print -r -- 'node() { print -r -- v20.11.0; return 0; }' >> "$fake_script"
    print -r -- "export HOME=\"$CASE_HOME\" DEVBOX_NVM_LAZY_SCRIPT=\"$fake_script\" NVM_PROCESS_COUNT=\"$count_file\" PATH=\"/bin:/usr/bin\"" > "$input_file"
    print -r -- "source \"$TOOLS_ZSH\"" >> "$input_file"
    case "$process_form" in
        input) print -r -- 'cat <(node --version) >/dev/null' >> "$input_file" ;;
        output) print -r -- 'print -r -- data > >(node --version >/dev/null); wait' >> "$input_file" ;;
        file) print -r -- 'print -r -- =(node --version) >/dev/null' >> "$input_file" ;;
    esac
    print -r -- "print -r -- \${_NVM_LAZY_LOADED:-unset} > \"$CASE_HOME/process-$process_form-loaded\"" >> "$input_file"
    print -r -- 'exit' >> "$input_file"

    zsh -fi < "$input_file" > "$session_file" 2>&1
    local shell_status=$?
    assert_eq 0 "$shell_status" "$process_form process substitution shell exits successfully"
    assert_eq 1 "$(<"$count_file")" "$process_form process substitution loads NVM once"
    assert_eq 1 "$(<"$CASE_HOME/process-$process_form-loaded")" "$process_form process substitution loads the parent"
}

run_case_24() { run_process_substitution_case input; }
run_case_25() { run_process_substitution_case output; }
run_case_26() { run_process_substitution_case file; }

run_case_27() {
    export HOME="$CASE_HOME"
    typeset fake_script="$CASE_HOME/arithmetic-nvm.sh"
    typeset count_file="$CASE_HOME/arithmetic-load-count"
    typeset input_file="$CASE_HOME/arithmetic-input"
    typeset session_file="$CASE_HOME/arithmetic-session"
    print -r -- 0 > "$count_file"
    print -r -- 'if [[ -f "$NVM_ARITHMETIC_COUNT" ]]; then _count=$(<"$NVM_ARITHMETIC_COUNT"); else _count=0; fi' > "$fake_script"
    print -r -- 'print -r -- $((_count + 1)) > "$NVM_ARITHMETIC_COUNT"' >> "$fake_script"
    print -r -- 'node() { return 0; }' >> "$fake_script"
    print -r -- "export HOME=\"$CASE_HOME\" DEVBOX_NVM_LAZY_SCRIPT=\"$fake_script\" NVM_ARITHMETIC_COUNT=\"$count_file\" PATH=\"/bin:/usr/bin\"" > "$input_file"
    print -r -- "source \"$TOOLS_ZSH\"" >> "$input_file"
    print -r -- 'echo $((node + 1)) >/dev/null' >> "$input_file"
    print -r -- "print -r -- \${_NVM_LAZY_LOADED:-unset} > \"$CASE_HOME/arithmetic-loaded\"" >> "$input_file"
    print -r -- 'exit' >> "$input_file"

    zsh -fi < "$input_file" > "$session_file" 2>&1
    local shell_status=$?
    assert_eq 0 "$shell_status" 'arithmetic expansion shell exits successfully'
    assert_eq 0 "$(<"$count_file")" 'arithmetic expansion does not load NVM'
    assert_eq 0 "$(<"$CASE_HOME/arithmetic-loaded")" 'arithmetic expansion leaves parent unloaded'
}

run_case_28() {
    export HOME="$CASE_HOME"
    typeset fake_script="$CASE_HOME/backtick-nvm.sh"
    typeset count_file="$CASE_HOME/backtick-load-count"
    typeset input_file="$CASE_HOME/backtick-input"
    typeset session_file="$CASE_HOME/backtick-session"
    print -r -- 0 > "$count_file"
    print -r -- 'if [[ -f "$NVM_BACKTICK_COUNT" ]]; then _count=$(<"$NVM_BACKTICK_COUNT"); else _count=0; fi' > "$fake_script"
    print -r -- 'print -r -- $((_count + 1)) > "$NVM_BACKTICK_COUNT"' >> "$fake_script"
    print -r -- 'node() { print -r -- v20.11.0; return 0; }' >> "$fake_script"
    print -r -- "export HOME=\"$CASE_HOME\" DEVBOX_NVM_LAZY_SCRIPT=\"$fake_script\" NVM_BACKTICK_COUNT=\"$count_file\" PATH=\"/bin:/usr/bin\"" > "$input_file"
    print -r -- "source \"$TOOLS_ZSH\"" >> "$input_file"
    print -r -- 'value=`node --version`' >> "$input_file"
    print -r -- "print -r -- \${_NVM_LAZY_LOADED:-unset} > \"$CASE_HOME/backtick-loaded\"" >> "$input_file"
    print -r -- 'exit' >> "$input_file"

    zsh -fi < "$input_file" > "$session_file" 2>&1
    local shell_status=$?
    assert_eq 0 "$shell_status" 'backtick command shell exits successfully'
    assert_eq 1 "$(<"$count_file")" 'backtick command loads NVM once'
    assert_eq 1 "$(<"$CASE_HOME/backtick-loaded")" 'backtick command loads the parent'
}

run_nested_quote_case() {
    local quote_form=$1
    typeset fake_script="$CASE_HOME/quoted-$quote_form-nvm.sh"
    typeset count_file="$CASE_HOME/quoted-$quote_form-load-count"
    typeset input_file="$CASE_HOME/quoted-$quote_form-input"
    typeset session_file="$CASE_HOME/quoted-$quote_form-session"
    export HOME="$CASE_HOME"
    print -r -- 0 > "$count_file"
    print -r -- 'if [[ -f "$NVM_QUOTED_COUNT" ]]; then _count=$(<"$NVM_QUOTED_COUNT"); else _count=0; fi' > "$fake_script"
    print -r -- 'print -r -- $((_count + 1)) > "$NVM_QUOTED_COUNT"' >> "$fake_script"
    print -r -- 'node() { print -r -- v20.11.0; return 0; }' >> "$fake_script"
    print -r -- "export HOME=\"$CASE_HOME\" DEVBOX_NVM_LAZY_SCRIPT=\"$fake_script\" NVM_QUOTED_COUNT=\"$count_file\" PATH=\"/bin:/usr/bin\"" > "$input_file"
    print -r -- "source \"$TOOLS_ZSH\"" >> "$input_file"
    case "$quote_form" in
        single) print -r -- "value=\$(echo ')'; node --version)" >> "$input_file" ;;
        double) print -r -- 'value=$(echo "x)"; node --version)' >> "$input_file" ;;
    esac
    print -r -- "print -r -- \${_NVM_LAZY_LOADED:-unset} > \"$CASE_HOME/quoted-$quote_form-loaded\"" >> "$input_file"
    print -r -- 'exit' >> "$input_file"

    zsh -fi < "$input_file" > "$session_file" 2>&1
    local shell_status=$?
    assert_eq 0 "$shell_status" "$quote_form quoted-parenthesis shell exits successfully"
    assert_eq 1 "$(<"$count_file")" "$quote_form quoted-parenthesis command loads NVM once"
    assert_eq 1 "$(<"$CASE_HOME/quoted-$quote_form-loaded")" "$quote_form quoted-parenthesis command loads the parent"
}

run_redirect_case() {
    local redirect_form=$1
    typeset fake_script="$CASE_HOME/redirect-$redirect_form-nvm.sh"
    typeset count_file="$CASE_HOME/redirect-$redirect_form-load-count"
    typeset input_file="$CASE_HOME/redirect-$redirect_form-input"
    typeset session_file="$CASE_HOME/redirect-$redirect_form-session"
    export HOME="$CASE_HOME"
    print -r -- 0 > "$count_file"
    print -r -- 'if [[ -f "$NVM_REDIRECT_COUNT" ]]; then _count=$(<"$NVM_REDIRECT_COUNT"); else _count=0; fi' > "$fake_script"
    print -r -- 'print -r -- $((_count + 1)) > "$NVM_REDIRECT_COUNT"' >> "$fake_script"
    print -r -- 'node() { print -r -- v20.11.0; return 0; }' >> "$fake_script"
    print -r -- "export HOME=\"$CASE_HOME\" DEVBOX_NVM_LAZY_SCRIPT=\"$fake_script\" NVM_REDIRECT_COUNT=\"$count_file\" PATH=\"/bin:/usr/bin\"" > "$input_file"
    print -r -- "source \"$TOOLS_ZSH\"" >> "$input_file"
    case "$redirect_form" in
        pipeline) print -r -- '2>/dev/null node --version | cat >/dev/null' >> "$input_file" ;;
        substitution) print -r -- 'value=$(2>/dev/null node --version)' >> "$input_file" ;;
        group) print -r -- '(2>/dev/null node --version)' >> "$input_file" ;;
    esac
    print -r -- "print -r -- \${_NVM_LAZY_LOADED:-unset} > \"$CASE_HOME/redirect-$redirect_form-loaded\"" >> "$input_file"
    print -r -- 'exit' >> "$input_file"

    zsh -fi < "$input_file" > "$session_file" 2>&1
    local shell_status=$?
    assert_eq 0 "$shell_status" "$redirect_form redirect shell exits successfully"
    assert_eq 1 "$(<"$count_file")" "$redirect_form redirect command loads NVM once"
    assert_eq 1 "$(<"$CASE_HOME/redirect-$redirect_form-loaded")" "$redirect_form redirect command loads the parent"
}

run_case_29() { run_nested_quote_case single; }
run_case_30() { run_nested_quote_case double; }
run_case_31() { run_redirect_case pipeline; }
run_case_32() { run_redirect_case substitution; }
run_case_33() { run_redirect_case group; }

case "$TEST_CASE" in
    1) run_case_1; (( CASE_FAILURES == 0 )) || exit 1 ;;
    2) run_case_2; (( CASE_FAILURES == 0 )) || exit 1 ;;
    3) run_case_3; (( CASE_FAILURES == 0 )) || exit 1 ;;
    4) run_case_4; (( CASE_FAILURES == 0 )) || exit 1 ;;
    5) run_case_5; (( CASE_FAILURES == 0 )) || exit 1 ;;
    6) run_case_6; (( CASE_FAILURES == 0 )) || exit 1 ;;
    7) run_case_7; (( CASE_FAILURES == 0 )) || exit 1 ;;
    8) run_case_8; (( CASE_FAILURES == 0 )) || exit 1 ;;
    9) run_case_9; (( CASE_FAILURES == 0 )) || exit 1 ;;
    10) run_case_10; (( CASE_FAILURES == 0 )) || exit 1 ;;
    11) run_case_11; (( CASE_FAILURES == 0 )) || exit 1 ;;
    12) run_case_12; (( CASE_FAILURES == 0 )) || exit 1 ;;
    13) run_case_13; (( CASE_FAILURES == 0 )) || exit 1 ;;
    14) run_case_14; (( CASE_FAILURES == 0 )) || exit 1 ;;
    15) run_case_15; (( CASE_FAILURES == 0 )) || exit 1 ;;
    16) run_case_16; (( CASE_FAILURES == 0 )) || exit 1 ;;
    17) run_case_17; (( CASE_FAILURES == 0 )) || exit 1 ;;
    18) run_case_18; (( CASE_FAILURES == 0 )) || exit 1 ;;
    19) run_case_19; (( CASE_FAILURES == 0 )) || exit 1 ;;
    20) run_case_20; (( CASE_FAILURES == 0 )) || exit 1 ;;
    21) run_case_21; (( CASE_FAILURES == 0 )) || exit 1 ;;
    22) run_case_22; (( CASE_FAILURES == 0 )) || exit 1 ;;
    23) run_case_23; (( CASE_FAILURES == 0 )) || exit 1 ;;
    24) run_case_24; (( CASE_FAILURES == 0 )) || exit 1 ;;
    25) run_case_25; (( CASE_FAILURES == 0 )) || exit 1 ;;
    26) run_case_26; (( CASE_FAILURES == 0 )) || exit 1 ;;
    27) run_case_27; (( CASE_FAILURES == 0 )) || exit 1 ;;
    28) run_case_28; (( CASE_FAILURES == 0 )) || exit 1 ;;
    29) run_case_29; (( CASE_FAILURES == 0 )) || exit 1 ;;
    30) run_case_30; (( CASE_FAILURES == 0 )) || exit 1 ;;
    31) run_case_31; (( CASE_FAILURES == 0 )) || exit 1 ;;
    32) run_case_32; (( CASE_FAILURES == 0 )) || exit 1 ;;
    33) run_case_33; (( CASE_FAILURES == 0 )) || exit 1 ;;
    all)
        typeset case_number failures=0
        for case_number in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33; do
            if ! zsh -f "$0" "$case_number"; then
                (( failures++ ))
            fi
        done
        (( failures == 0 )) || exit 1
        ;;
    *) print -u2 -- "FAIL: unknown test case: $TEST_CASE"; exit 2 ;;
esac

print -- "PASS: NVM lazy-loading regression tests"
