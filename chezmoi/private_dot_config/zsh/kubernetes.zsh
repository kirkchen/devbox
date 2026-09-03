# Kubernetes prompt context catalog and Bullet Train adapter.

typeset -gA KUBE_CONTEXT_ENV=(
  'gke_jkopay-operator_asia-east1_application' 'operator'
  'gke_jkopay-prod-app_asia-east1_application' 'prod'
  'gke_jkopay-sit-app_asia-east1_application' 'sit'
  'gke_jkopay-sit-service_asia-east1_application' 'sit'
  'gke_jkopay-uat-app_asia-east1_application' 'uat'
  'gke_jkos-operator_asia-east1_application' 'operator'
  'gke_jkos-prod-app_asia-east1_application' 'prod'
  'gke_jkos-sit-app_asia-east1_application' 'sit'
  'kirk@homelab' 'prod'
  'kubernetes-admin@application-01' 'sit/uat'
  'kubernetes-super-admin@prod-jkopay' 'prod'
  'orbstack' 'local'
)

typeset -gA KUBE_CONTEXT_LOCATION=(
  'gke_jkopay-operator_asia-east1_application' 'gke'
  'gke_jkopay-prod-app_asia-east1_application' 'gke'
  'gke_jkopay-sit-app_asia-east1_application' 'gke'
  'gke_jkopay-sit-service_asia-east1_application' 'gke'
  'gke_jkopay-uat-app_asia-east1_application' 'gke'
  'gke_jkos-operator_asia-east1_application' 'gke'
  'gke_jkos-prod-app_asia-east1_application' 'gke'
  'gke_jkos-sit-app_asia-east1_application' 'gke'
  'kirk@homelab' 'personal'
  'kubernetes-admin@application-01' 'idc'
  'kubernetes-super-admin@prod-jkopay' 'idc'
  'orbstack' 'local'
)

typeset -gA KUBE_CONTEXT_LABEL=(
  'gke_jkopay-operator_asia-east1_application' 'jkopay/application'
  'gke_jkopay-prod-app_asia-east1_application' 'jkopay/application'
  'gke_jkopay-sit-app_asia-east1_application' 'jkopay/application'
  'gke_jkopay-sit-service_asia-east1_application' 'jkopay/service'
  'gke_jkopay-uat-app_asia-east1_application' 'jkopay/application'
  'gke_jkos-operator_asia-east1_application' 'jkos/application'
  'gke_jkos-prod-app_asia-east1_application' 'jkos/application'
  'gke_jkos-sit-app_asia-east1_application' 'jkos/application'
  'kirk@homelab' 'homelab'
  'kubernetes-admin@application-01' 'application-01'
  'kubernetes-super-admin@prod-jkopay' 'prod-jkopay'
  'orbstack' 'orbstack'
)

typeset -gA KUBE_CONTEXT_RISK=(
  'gke_jkopay-operator_asia-east1_application' 'high'
  'gke_jkopay-prod-app_asia-east1_application' 'high'
  'gke_jkopay-sit-app_asia-east1_application' 'low'
  'gke_jkopay-sit-service_asia-east1_application' 'low'
  'gke_jkopay-uat-app_asia-east1_application' 'medium'
  'gke_jkos-operator_asia-east1_application' 'high'
  'gke_jkos-prod-app_asia-east1_application' 'high'
  'gke_jkos-sit-app_asia-east1_application' 'low'
  'kirk@homelab' 'high'
  'kubernetes-admin@application-01' 'medium'
  'kubernetes-super-admin@prod-jkopay' 'critical'
  'orbstack' 'low'
)

if (( ! ${+reply} )); then
  typeset -ga reply
elif [[ ${(t)reply} == array* ]]; then
  typeset -ga reply
else
  typeset -g KUBE_REPLY_SCALAR="$reply"
  unset reply
  typeset -ga reply
  reply=( "$KUBE_REPLY_SCALAR" )
  unset KUBE_REPLY_SCALAR
fi

(( ${+KUBE_PROMPT_LAST_CONTEXT} )) || typeset -g KUBE_PROMPT_LAST_CONTEXT=''
(( ${+KUBE_PROMPT_LAST_NAMESPACE} )) || typeset -g KUBE_PROMPT_LAST_NAMESPACE=''
(( ${+KUBE_PROMPT_LAST_SOURCE} )) || typeset -g KUBE_PROMPT_LAST_SOURCE='<unset>'

_kube_prompt_source() {
  if (( ${+KUBECONFIG} )); then
    REPLY="$KUBECONFIG"
  else
    REPLY='<unset>'
  fi
}

_kube_prompt_capture() {
  local context="${KUBE_PS1_CONTEXT-}"
  local namespace="${KUBE_PS1_NAMESPACE-}"
  local REPLY

  [[ -n "$context" && "$context" != N/A && "$context" != BINARY-N/A ]] || context=''
  [[ -n "$namespace" && "$namespace" != N/A ]] || namespace=default
  _kube_prompt_source
  KUBE_PROMPT_LAST_CONTEXT="$context"
  KUBE_PROMPT_LAST_NAMESPACE="$namespace"
  KUBE_PROMPT_LAST_SOURCE="$REPLY"
}

_kube_context_profile() {
  local context="${1-}"
  local env='unknown'
  local location='unknown'
  local label="$context"
  local risk='high'

  if [[ -n "$context" && -n "${KUBE_CONTEXT_ENV[$context]-}" ]]; then
    env="${KUBE_CONTEXT_ENV[$context]}"
    location="${KUBE_CONTEXT_LOCATION[$context]}"
    label="${KUBE_CONTEXT_LABEL[$context]}"
    risk="${KUBE_CONTEXT_RISK[$context]}"
  fi

  reply=( "$env" "$location" "$label" "$risk" )
}

_kube_prompt_sanitize() {
  local value="${1-}"
  value="${value//\\/\\\\}"
  value="${value//[[:cntrl:]]/ }"
  value="${value//$'%'/%%}"
  REPLY="$value"
}

prompt_kube() {
  (( ${+functions[prompt_segment]} )) || return 0

  local context="${KUBE_PS1_CONTEXT-}"
  [[ -n "$context" && "$context" != N/A && "$context" != BINARY-N/A ]] || return 0

  local namespace="${KUBE_PS1_NAMESPACE-}"
  [[ -n "$namespace" && "$namespace" != N/A ]] || namespace='default'

  local -a reply
  local REPLY
  _kube_context_profile "$context"
  local env="${reply[1]}"
  local location="${reply[2]}"
  local label="${reply[3]}"
  local risk="${reply[4]}"
  local safe_env safe_location safe_label safe_namespace
  _kube_prompt_sanitize "$env"
  safe_env="$REPLY"
  _kube_prompt_sanitize "$location"
  safe_location="$REPLY"
  _kube_prompt_sanitize "$label"
  safe_label="$REPLY"
  _kube_prompt_sanitize "$namespace"
  safe_namespace="$REPLY"
  local bg='red'
  local fg='white'
  local marker='! '

  case "$risk" in
    low)
      bg='green'
      fg='black'
      marker=''
      ;;
    medium)
      bg='yellow'
      fg='black'
      marker=''
      ;;
  esac

  local text="⎈ ${marker}${safe_env} | ${safe_location}/${safe_label} | ${safe_namespace}"
  prompt_segment "$bg" "$fg" "$text"
}

_kube_guard_option_kind() {
  case "${1-}" in
    --context|--namespace|-n|-s|-v|-Al|--kubeconfig|--cluster|--user|--server|--token|--as|--as-group|--as-uid|--username|--password|--request-timeout|--certificate-authority|--client-certificate|--client-key|--cache-dir|--tls-server-name|--profile|--profile-output|--log-backtrace-at|--log-dir|--log-file|--log-file-max-size|--log-flush-frequency|--stderrthreshold|--v|--vmodule)
      REPLY=value
      ;;
    --context=*|--namespace=*|--kubeconfig=*|--cluster=*|--user=*|--server=*|--token=*|--as=*|--as-group=*|--as-uid=*|--username=*|--password=*|--request-timeout=*|--certificate-authority=*|--client-certificate=*|--client-key=*|--cache-dir=*|--tls-server-name=*|--profile=*|--profile-output=*|--log-backtrace-at=*|--log-dir=*|--log-file=*|--log-file-max-size=*|--log-flush-frequency=*|--stderrthreshold=*|--v=*|--vmodule=*|-n=*|-s=*|-v=*|-n?*|-s?*|-v?*)
      REPLY=attached
      ;;
    --add-dir-header=*|--alsologtostderr=*|--disable-compression=*|--insecure-skip-tls-verify=*|--logtostderr=*|--match-server-version=*|--one-output=*|--skip-headers=*|--skip-log-headers=*|--warnings-as-errors=*|--all-namespaces=*|-A=*|--add-dir-header|--alsologtostderr|--disable-compression|--insecure-skip-tls-verify|--logtostderr|--match-server-version|--one-output|--skip-headers|--skip-log-headers|--warnings-as-errors|-A|-Al*|--all-namespaces|-h|--help)
      REPLY=boolean
      ;;
    --)
      REPLY=separator
      ;;
    -*)
      REPLY=unknown
      ;;
    *)
      REPLY=word
      ;;
  esac
}

_kube_guard_separator_index() {
  local -a arguments
  arguments=( "$@" )
  local kind
  local index=1

  while (( index <= ${#arguments} )); do
    _kube_guard_option_kind "${arguments[index]}"
    kind="$REPLY"
    case "$kind" in
      value)
        (( index += 2 ))
        ;;
      separator)
        REPLY="$index"
        return
        ;;
      *)
        (( index++ ))
        ;;
    esac
  done

  REPLY="$index"
}

_kube_guard_next_command_word() {
  local -a arguments
  arguments=( "$@" )
  local argument
  local REPLY
  local boundary kind
  local index=1

  _kube_guard_separator_index "${arguments[@]}"
  boundary="$REPLY"

  while (( index < boundary )); do
    argument="${arguments[index]}"
    _kube_guard_option_kind "$argument"
    kind="$REPLY"
    case "$kind" in
      value)
        if (( index == ${#arguments} )); then
          reply=( unknown '' "$index" )
          return
        fi
        (( index += 2 ))
        continue
        ;;
      attached|boolean)
        (( index++ ))
        continue
        ;;
      unknown)
        reply=( unknown '' "$index" )
        return
        ;;
      word)
        reply=( found "$argument" "$index" )
        return
        ;;
    esac
  done

  reply=( none '' "$boundary" )
}

_kube_guard_find_root_word() {
  local -a arguments scan
  arguments=( "$@" )
  local offset=0

  if [[ "${arguments[1]-}" == -- ]]; then
    offset=1
    arguments=( "${arguments[@]:1}" )
  fi
  _kube_guard_next_command_word "${arguments[@]}"
  scan=( "${reply[@]}" )
  if [[ "${scan[1]}" == found ]]; then
    reply=( found "${scan[2]}" "$(( scan[3] + offset ))" )
  else
    reply=( "${scan[1]}" '' '' )
  fi
}

_kube_guard_command_separator_index() {
  local -a arguments root_scan tail
  arguments=( "$@" )
  local verb root_index tail_separator

  if [[ "${arguments[1]-}" == -- ]]; then
    REPLY=1
    return
  fi
  _kube_guard_find_root_word "${arguments[@]}"
  root_scan=( "${reply[@]}" )
  [[ "${root_scan[1]}" == found ]] || { REPLY="$(( ${#arguments} + 1 ))"; return; }
  verb="${root_scan[2]}"
  root_index="${root_scan[3]}"
  case "$verb" in
    exec|debug|run|cp)
      tail=( "${arguments[@]:$root_index}" )
      _kube_guard_separator_index "${tail[@]}"
      tail_separator="$REPLY"
      if (( tail_separator <= ${#tail} )); then
        REPLY="$(( root_index + tail_separator ))"
        return
      fi
      ;;
  esac
  REPLY="$(( ${#arguments} + 1 ))"
}

_kube_guard_target_flag_after_verb() {
  local -a arguments root_scan
  arguments=( "$@" )
  local REPLY
  local root_index boundary argument
  local index

  _kube_guard_find_root_word "${arguments[@]}"
  root_scan=( "${reply[@]}" )
  if [[ "${root_scan[1]}" != found ]]; then
    for argument in "${arguments[@]}"; do
      case "$argument" in
        --context|--context=*|--namespace|--namespace=*|-n|-n=*|-n?*) return 0 ;;
      esac
    done
    return 1
  fi
  root_index="${root_scan[3]}"
  _kube_guard_command_separator_index "${arguments[@]}"
  boundary="$REPLY"
  for (( index = root_index + 1; index < boundary; index++ )); do
    case "${arguments[index]}" in
      --context|--context=*|--namespace|--namespace=*|-n|-n=*|-n?*) return 0 ;;
    esac
  done
  return 1
}

_kube_guard_classify() {
  local -a arguments root_scan subverb_arguments subverb_scan
  arguments=( "$@" )
  local verb=''
  local subverb=''
  local class='unknown'
  local root_index

  _kube_guard_find_root_word "${arguments[@]}"
  root_scan=( "${reply[@]}" )
  if [[ "${root_scan[1]}" == unknown ]]; then
    reply=( unknown '' '' )
    return
  fi
  if [[ "${root_scan[1]}" == found ]]; then
    verb="${root_scan[2]}"
    root_index="${root_scan[3]}"
    subverb="${arguments[root_index + 1]-}"
  fi

  case "$verb" in
    auth|rollout|certificate)
      subverb=''
      subverb_arguments=( "${arguments[@]:$root_index}" )
      _kube_guard_next_command_word "${subverb_arguments[@]}"
      subverb_scan=( "${reply[@]}" )
      if [[ "${subverb_scan[1]}" == unknown ]]; then
        reply=( unknown "$verb" '' )
        return
      fi
      [[ "${subverb_scan[1]}" == found ]] && subverb="${subverb_scan[2]}"
      ;;
  esac

  case "$verb" in
    ''|help|options|get|describe|logs|top|explain|api-resources|api-versions|cluster-info|version|wait|diff|completion)
      class='read'
      ;;
    config)
      class='local'
      ;;
    auth)
      [[ "$subverb" == reconcile ]] && class='write' || class='read'
      ;;
    rollout)
      case "$subverb" in
        status|history) class='read' ;;
        *) class='write' ;;
      esac
      ;;
    certificate)
      case "$subverb" in
        approve|deny) class='write' ;;
        *) class='read' ;;
      esac
      ;;
    delete|drain)
      class='destructive'
      ;;
    apply|create|replace|edit|patch|scale|set|annotate|label|expose|autoscale|run|debug|exec|attach|cp|port-forward|proxy|cordon|uncordon|taint)
      class='write'
      ;;
  esac

  reply=( "$class" "$verb" "$subverb" )
}

_kube_guard_resolve_context() {
  local -a arguments root_scan
  arguments=( "$@" )
  local context=''
  local explicit=false
  local REPLY
  local limit kind argument
  local index=1

  _kube_guard_find_root_word "${arguments[@]}"
  root_scan=( "${reply[@]}" )
  limit="${root_scan[3]:-1}"
  while (( index < limit )); do
    argument="${arguments[index]}"
    case "$argument" in
      --context=*)
        context="${argument#--context=}"
        explicit=true
        (( index++ ))
        ;;
      --context)
        context="${arguments[index + 1]-}"
        explicit=true
        (( index += 2 ))
        ;;
      *)
        _kube_guard_option_kind "$argument"
        kind="$REPLY"
        [[ "$kind" == value ]] && (( index += 2 )) || (( index++ ))
        ;;
    esac
  done

  if [[ "$explicit" != true ]]; then
    explicit=false
    context="$(command kubectl config current-context)"
  fi
  reply=( "$context" "$explicit" )
}

_kube_guard_resolve_named_namespace() {
  local -a arguments root_scan
  arguments=( "$@" )
  local namespace=''
  local explicit=false
  local REPLY
  local limit kind argument
  local index=1

  _kube_guard_find_root_word "${arguments[@]}"
  root_scan=( "${reply[@]}" )
  limit="${root_scan[3]:-1}"
  while (( index < limit )); do
    argument="${arguments[index]}"
    case "$argument" in
      --namespace=*|-n=*)
        namespace="${argument#*=}"
        explicit=true
        (( index++ ))
        ;;
      -n?*)
        namespace="${argument#-n}"
        explicit=true
        (( index++ ))
        ;;
      --namespace|-n)
        namespace="${arguments[index + 1]-}"
        explicit=true
        (( index += 2 ))
        ;;
      *)
        _kube_guard_option_kind "$argument"
        kind="$REPLY"
        [[ "$kind" == value ]] && (( index += 2 )) || (( index++ ))
        ;;
    esac
  done

  reply=( "$namespace" "$explicit" )
}

_kube_guard_resolve_context_namespace() {
  local context="$1"
  local namespace

  namespace="$(command kubectl config view --minify --context="$context" --output 'jsonpath={..namespace}')"
  [[ -n "$namespace" ]] || namespace=default
  REPLY="$namespace"
}

_kube_guard_resolve_namespace() {
  local context="$1"
  shift
  local -a arguments
  arguments=( "$@" )
  local namespace=''
  local explicit=false
  local REPLY

  _kube_guard_resolve_named_namespace "${arguments[@]}"
  namespace="${reply[1]}"
  explicit="${reply[2]}"

  # Cluster-wide scope is canonical and deliberately wins over named namespaces.
  if _kube_guard_has_all_namespaces "${arguments[@]}"; then
    namespace=all-namespaces
    explicit=true
  fi

  if [[ "$explicit" != true ]]; then
    _kube_guard_resolve_context_namespace "$context"
    namespace="$REPLY"
  fi
  reply=( "$namespace" "$explicit" )
}

_kube_guard_action() {
  local risk="$1"
  local class="$2"

  case "$class" in
    read|local)
      REPLY=allow
      ;;
    *)
      case "$risk:$class" in
        critical:*) REPLY=type-context ;;
        high:*) REPLY=type-target ;;
        medium:destructive) REPLY=type-target ;;
        medium:write|medium:unknown|low:destructive|low:unknown) REPLY=confirm ;;
        low:write) REPLY=allow ;;
        *) REPLY=confirm ;;
      esac
      ;;
  esac
}

_kube_guard_has_connection_override() {
  local argument shorthand

  for argument in "$@"; do
    case "$argument" in
      -s|-s=*|-s?*|--kubeconfig|--kubeconfig=*|--cluster|--cluster=*|--user|--user=*|--server|--server=*|--token|--token=*|--as|--as=*|--as-group|--as-group=*|--as-uid|--as-uid=*|--username|--username=*|--password|--password=*|--certificate-authority|--certificate-authority=*|--client-certificate|--client-certificate=*|--client-key|--client-key=*|--tls-server-name|--tls-server-name=*|--insecure-skip-tls-verify|--insecure-skip-tls-verify=*)
        return 0
        ;;
    esac

    if [[ "$argument" == -?* && "$argument" != --* ]]; then
      shorthand="${argument%%=*}"
      [[ "$shorthand" == -n* ]] && continue
      [[ "$argument" == -Al?* ]] && continue
      [[ "$shorthand" == -?*s* ]] && return 0
    fi
  done
  return 1
}

_kube_guard_has_ambiguous_all_namespaces_bundle() {
  local -a arguments
  arguments=( "$@" )
  local REPLY
  local boundary kind argument shorthand
  local index=1

  _kube_guard_command_separator_index "${arguments[@]}"
  boundary="$REPLY"
  while (( index < boundary )); do
    argument="${arguments[index]}"
    case "$argument" in
      -Al)
        (( index += 2 ))
        ;;
      -A|-A=*|-Al?*)
        (( index++ ))
        ;;
      -A*)
        return 0
        ;;
      --*)
        _kube_guard_option_kind "$argument"
        kind="$REPLY"
        [[ "$kind" == value ]] && (( index += 2 )) || (( index++ ))
        ;;
      *)
        if [[ "$argument" == -?* ]]; then
          shorthand="${argument%%=*}"
          [[ "$shorthand" == -?*A* ]] && return 0
        fi
        _kube_guard_option_kind "$argument"
        kind="$REPLY"
        [[ "$kind" == value ]] && (( index += 2 )) || (( index++ ))
        ;;
    esac
  done
  return 1
}

_kube_guard_has_all_namespaces() {
  local -a arguments
  arguments=( "$@" )
  local boundary kind argument value
  local all_namespaces=false
  local index=1

  _kube_guard_command_separator_index "${arguments[@]}"
  boundary="$REPLY"
  while (( index < boundary )); do
    argument="${arguments[index]}"
    case "$argument" in
      -A=*|--all-namespaces=*)
        value="${argument#*=}"
        case "$value" in
          1|t|T|TRUE|true|True)
            all_namespaces=true
            ;;
          0|f|F|FALSE|false|False)
            all_namespaces=false
            ;;
          *)
            REPLY=invalid
            return 2
            ;;
        esac
        (( index++ ))
        ;;
      -Al)
        all_namespaces=true
        (( index += 2 ))
        ;;
      -A|--all-namespaces|-Al?*)
        all_namespaces=true
        (( index++ ))
        ;;
      *)
        _kube_guard_option_kind "$argument"
        kind="$REPLY"
        [[ "$kind" == value ]] && (( index += 2 )) || (( index++ ))
        ;;
    esac
  done
  REPLY="$all_namespaces"
  [[ "$all_namespaces" == true ]]
}

_kube_guard_confirm() {
  local mode="$1"
  local context="$2"
  local environment="$3"
  local namespace="$4"
  local risk="$5"
  local input=''
  local expected=''
  local REPLY
  local tty_fd
  local safe_context safe_environment safe_namespace safe_risk

  _kube_prompt_sanitize "$context"
  safe_context="$REPLY"
  _kube_prompt_sanitize "$environment"
  safe_environment="$REPLY"
  _kube_prompt_sanitize "$namespace"
  safe_namespace="$REPLY"
  _kube_prompt_sanitize "$risk"
  safe_risk="$REPLY"

  if ! { exec {tty_fd}<>/dev/tty } 2>/dev/null; then
    print -u2 -- 'kubectl guard: cannot confirm without a readable terminal.'
    return 1
  fi
  print -u "$tty_fd" -- "kubectl target: env=$safe_environment context=$safe_context namespace=$safe_namespace risk=$safe_risk"

  case "$mode" in
    confirm)
      print -u "$tty_fd" -n -- 'Proceed? [y/N] '
      ;;
    type-target)
      expected="$environment:$namespace"
      print -u "$tty_fd" -n -- "Type ${safe_environment}:${safe_namespace} to proceed: "
      ;;
    type-context)
      expected="$context"
      print -u "$tty_fd" -n -- "Type $safe_context to proceed: "
      ;;
    *)
      exec {tty_fd}>&-
      return 1
      ;;
  esac

  if ! IFS= read -r -u "$tty_fd" input; then
    exec {tty_fd}>&-
    print -u2 -- 'kubectl guard: cannot read confirmation from the terminal.'
    return 1
  fi
  exec {tty_fd}>&-

  if [[ "$mode" == confirm ]]; then
    [[ "$input" == y || "$input" == Y ]]
  else
    [[ "$input" == "$expected" ]]
  fi
}

_kube_guard_redraw() {
  [[ -o zle ]] && zle reset-prompt 2>/dev/null
}

_kube_guard_run() {
  local -a reply
  local -a execution_arguments
  local REPLY
  local class verb subverb context context_explicit namespace namespace_explicit source
  local all_namespaces named_namespace named_namespace_explicit namespace_pin namespace_pin_explicit
  local environment location label risk action
  local safe_prompt_context safe_context safe_prompt_namespace safe_namespace

  _kube_guard_classify "$@"
  class="${reply[1]}"
  verb="${reply[2]}"
  subverb="${reply[3]}"

  if [[ "$class" == local ]]; then
    command kubectl "$@"
    return
  fi

  if _kube_guard_target_flag_after_verb "$@"; then
    print -u2 -- 'kubectl guard: place target flags before the verb; command blocked.'
    return 1
  fi

  if _kube_guard_has_ambiguous_all_namespaces_bundle "$@"; then
    print -u2 -- 'kubectl guard: ambiguous bundled all-namespaces flag; use separate flags; command blocked.'
    return 1
  fi

  _kube_guard_has_all_namespaces "$@"
  all_namespaces="$REPLY"
  if [[ "$REPLY" == invalid ]]; then
    print -u2 -- 'kubectl guard: invalid all-namespaces value; command blocked.'
    return 1
  fi

  if _kube_guard_has_connection_override "$@"; then
    print -u2 -- 'kubectl guard: connection override cannot be safely profiled; command blocked.'
    return 1
  fi

  _kube_prompt_source
  source="$REPLY"
  if [[ "$source" != "$KUBE_PROMPT_LAST_SOURCE" ]]; then
    print -u2 -- 'kubectl guard: kubeconfig source changed since prompt; refresh and retry.'
    return 1
  fi

  _kube_guard_resolve_context "$@"
  context="${reply[1]}"
  context_explicit="${reply[2]}"
  if [[ -z "$context" ]]; then
    if [[ "$context_explicit" == true ]]; then
      print -u2 -- 'kubectl guard: explicit target is empty; command blocked.'
      return 1
    fi
    print -u2 -- 'kubectl guard: cannot resolve an effective context; command blocked.'
    return 1
  fi

  _kube_guard_resolve_named_namespace "$@"
  named_namespace="${reply[1]}"
  named_namespace_explicit="${reply[2]}"
  if [[ "$named_namespace_explicit" == true && -z "$named_namespace" ]]; then
    print -u2 -- 'kubectl guard: explicit target is empty; command blocked.'
    return 1
  fi

  _kube_guard_resolve_namespace "$context" "$@"
  namespace="${reply[1]}"
  namespace_explicit="${reply[2]}"

  if [[ "$namespace_explicit" == true && -z "$namespace" ]]; then
    print -u2 -- 'kubectl guard: explicit target is empty; command blocked.'
    return 1
  fi

  namespace_pin="$namespace"
  namespace_pin_explicit="$namespace_explicit"
  if [[ "$all_namespaces" == true ]]; then
    if [[ "$named_namespace_explicit" == true ]]; then
      namespace_pin="$named_namespace"
      namespace_pin_explicit=true
    else
      _kube_guard_resolve_context_namespace "$context"
      namespace_pin="$REPLY"
      namespace_pin_explicit=false
    fi
  fi

  if [[ "$context_explicit" != true && "$context" != "$KUBE_PROMPT_LAST_CONTEXT" ]]; then
    _kube_prompt_sanitize "$KUBE_PROMPT_LAST_CONTEXT"
    safe_prompt_context="$REPLY"
    _kube_prompt_sanitize "$context"
    safe_context="$REPLY"
    print -u2 -- "kubectl guard: context changed since prompt (prompt: $safe_prompt_context; current: $safe_context). Refresh the prompt and retry."
    _kube_guard_redraw
    return 1
  fi
  if [[ "$context_explicit" != true && "$namespace_pin_explicit" != true && "$namespace_pin" != "$KUBE_PROMPT_LAST_NAMESPACE" ]]; then
    _kube_prompt_sanitize "$KUBE_PROMPT_LAST_NAMESPACE"
    safe_prompt_namespace="$REPLY"
    _kube_prompt_sanitize "$namespace_pin"
    safe_namespace="$REPLY"
    print -u2 -- "kubectl guard: namespace changed since prompt (prompt: $safe_prompt_namespace; current: $safe_namespace). Refresh the prompt and retry."
    _kube_guard_redraw
    return 1
  fi

  _kube_context_profile "$context"
  environment="${reply[1]}"
  location="${reply[2]}"
  label="${reply[3]}"
  risk="${reply[4]}"
  _kube_guard_action "$risk" "$class"
  action="$REPLY"
  if [[ "$action" != allow ]] && ! _kube_guard_confirm "$action" "$context" "$environment" "$namespace" "$risk"; then
    return 1
  fi

  execution_arguments=()
  [[ "$context_explicit" == true ]] || execution_arguments+=( "--context=$context" )
  [[ "$namespace_pin_explicit" == true ]] || execution_arguments+=( "--namespace=$namespace_pin" )
  execution_arguments+=( "$@" )
  command kubectl "${execution_arguments[@]}"
}

kubectl() {
  _kube_guard_run "$@"
}

autoload -Uz add-zsh-hook 2>/dev/null
if (( ${+functions[add-zsh-hook]} )); then
  add-zsh-hook -d precmd _kube_prompt_capture 2>/dev/null
  add-zsh-hook precmd _kube_prompt_capture
fi
