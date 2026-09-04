#!/usr/bin/env zsh

typeset -i TESTS_PASSED=0
typeset -i TESTS_FAILED=0

assert_eq() {
  local expected="$1"
  local actual="$2"
  local name="$3"

  if [[ "$expected" == "$actual" ]]; then
    (( TESTS_PASSED++ ))
  else
    print -u2 "FAIL: $name (expected '$expected', got '$actual')"
    (( TESTS_FAILED++ ))
  fi
}

typeset TEST_ROOT="${0:A:h:h:h}"
typeset FIXTURE_DIR="$TEST_ROOT/tests/zsh/fixtures"
typeset -g PATH="$FIXTURE_DIR:$PATH"

# A prompt plugin may already own reply. Sourcing the adapter must establish a
# global array without discarding an unset, array, or scalar pre-existing value.
unset reply
source "$TEST_ROOT/chezmoi/private_dot_config/zsh/kubernetes.zsh" 2>/dev/null
typeset UNSET_REPLY_SIGNATURE="${(t)reply}|${#reply}"
reply=(sentinel another)
source "$TEST_ROOT/chezmoi/private_dot_config/zsh/kubernetes.zsh" 2>/dev/null
typeset ARRAY_REPLY_SIGNATURE="${(t)reply}|${(j:|:)reply}"
unset reply
typeset reply=scalar
source "$TEST_ROOT/chezmoi/private_dot_config/zsh/kubernetes.zsh" 2>/dev/null
typeset SCALAR_REPLY_SIGNATURE="${(t)reply}|${(j:|:)reply}"
assert_eq 'array|0|array|sentinel|another|array|scalar' "$UNSET_REPLY_SIGNATURE|$ARRAY_REPLY_SIGNATURE|$SCALAR_REPLY_SIGNATURE" "source reply compatibility"

typeset -a EXPECTED_CONTEXT_KEYS=(
  gke_jkopay-operator_asia-east1_application
  gke_jkopay-prod-app_asia-east1_application
  gke_jkopay-sit-app_asia-east1_application
  gke_jkopay-sit-service_asia-east1_application
  gke_jkopay-uat-app_asia-east1_application
  gke_jkos-operator_asia-east1_application
  gke_jkos-prod-app_asia-east1_application
  gke_jkos-sit-app_asia-east1_application
  kirk@homelab
  kubernetes-admin@application-01
  kubernetes-super-admin@prod-jkopay
  orbstack
)
typeset -a SORTED_EXPECTED_KEYS=( "${(@o)EXPECTED_CONTEXT_KEYS}" )
typeset EXPECTED_KEYS_SIGNATURE="${#SORTED_EXPECTED_KEYS}|${(j:|:)SORTED_EXPECTED_KEYS}"
typeset -a ENV_KEYS=( "${(@ok)KUBE_CONTEXT_ENV}" )
typeset -a LOCATION_KEYS=( "${(@ok)KUBE_CONTEXT_LOCATION}" )
typeset -a LABEL_KEYS=( "${(@ok)KUBE_CONTEXT_LABEL}" )
typeset -a RISK_KEYS=( "${(@ok)KUBE_CONTEXT_RISK}" )
assert_eq "$EXPECTED_KEYS_SIGNATURE" "${#ENV_KEYS}|${(j:|:)ENV_KEYS}" "environment catalog keys"
assert_eq "$EXPECTED_KEYS_SIGNATURE" "${#LOCATION_KEYS}|${(j:|:)LOCATION_KEYS}" "location catalog keys"
assert_eq "$EXPECTED_KEYS_SIGNATURE" "${#LABEL_KEYS}|${(j:|:)LABEL_KEYS}" "label catalog keys"
assert_eq "$EXPECTED_KEYS_SIGNATURE" "${#RISK_KEYS}|${(j:|:)RISK_KEYS}" "risk catalog keys"

assert_profile() {
  local context="$1"
  local expected="$2"
  reply=()
  _kube_context_profile "$context"
  assert_eq "$expected" "${(j:|:)reply}" "$context profile"
}

assert_profile gke_jkopay-operator_asia-east1_application 'operator|gke|jkopay/application|high'
assert_profile gke_jkopay-prod-app_asia-east1_application 'prod|gke|jkopay/application|high'
assert_profile gke_jkopay-sit-app_asia-east1_application 'sit|gke|jkopay/application|low'
assert_profile gke_jkopay-sit-service_asia-east1_application 'sit|gke|jkopay/service|low'
assert_profile gke_jkopay-uat-app_asia-east1_application 'uat|gke|jkopay/application|medium'
assert_profile gke_jkos-operator_asia-east1_application 'operator|gke|jkos/application|high'
assert_profile gke_jkos-prod-app_asia-east1_application 'prod|gke|jkos/application|high'
assert_profile gke_jkos-sit-app_asia-east1_application 'sit|gke|jkos/application|low'
assert_profile kirk@homelab 'prod|personal|homelab|high'
assert_profile kubernetes-admin@application-01 'sit/uat|idc|application-01|medium'
assert_profile kubernetes-super-admin@prod-jkopay 'prod|idc|prod-jkopay|critical'
assert_profile orbstack 'local|local|orbstack|low'

prompt_segment() {
  SEGMENT_BG="$1"
  SEGMENT_FG="$2"
  SEGMENT_TEXT="$3"
  SEGMENT_RECORD="$1|$2|$3"
  (( SEGMENT_CALLS++ ))
}

SEGMENT_CALLS=0
KUBE_PS1_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PS1_NAMESPACE=foundation
prompt_kube
typeset LOW_PROMPT="$SEGMENT_RECORD"
KUBE_PS1_CONTEXT=gke_jkopay-uat-app_asia-east1_application
KUBE_PS1_NAMESPACE=staging
prompt_kube
typeset MEDIUM_PROMPT="$SEGMENT_RECORD"
assert_eq 'green|black|⎈ sit | gke/jkopay/application | foundation|yellow|black|⎈ uat | gke/jkopay/application | staging' "$LOW_PROMPT|$MEDIUM_PROMPT" "low and medium prompt rendering"

KUBE_PS1_CONTEXT=kubernetes-admin@application-01
KUBE_PS1_NAMESPACE=rhythm
prompt_kube
assert_eq 'yellow|black|⎈ sit/uat | idc/application-01 | rhythm' "$SEGMENT_RECORD" 'medium application-01 prompt rendering'

reply=(caller-reply)
unfunction prompt_segment
SEGMENT_CALLS=0
KUBE_PS1_CONTEXT=gke_jkopay-operator_asia-east1_application
KUBE_PS1_NAMESPACE=operator-ns
prompt_kube
typeset MISSING_SEGMENT_CALLS="$SEGMENT_CALLS"
prompt_segment() {
  SEGMENT_BG="$1"
  SEGMENT_FG="$2"
  SEGMENT_TEXT="$3"
  SEGMENT_RECORD="$1|$2|$3"
  (( SEGMENT_CALLS++ ))
}
prompt_kube
assert_eq '0|1|caller-reply|red|white|⎈ ! operator | gke/jkopay/application | operator-ns||' "$MISSING_SEGMENT_CALLS|$SEGMENT_CALLS|${reply[1]}|$SEGMENT_RECORD|$KUBE_PROMPT_LAST_CONTEXT|$KUBE_PROMPT_LAST_NAMESPACE" "high prompt and reply isolation"

KUBE_PS1_CONTEXT=kubernetes-super-admin@prod-jkopay
KUBE_PS1_NAMESPACE=N/A
prompt_kube
typeset CRITICAL_PROMPT="$SEGMENT_TEXT"
typeset CRITICAL_PROMPT_RECORD="$SEGMENT_RECORD"
HOSTILE_CONTEXT=$'evil%F{red}%K{blue}\\\nINJECT'
HOSTILE_NAMESPACE=$'ns%K{green}\\\rNEXT'
KUBE_PS1_CONTEXT="$HOSTILE_CONTEXT"
KUBE_PS1_NAMESPACE="$HOSTILE_NAMESPACE"
prompt_kube
assert_eq 'red|white|⎈ ! prod | idc/prod-jkopay | default|⎈ ! unknown | unknown/evil%%F{red}%%K{blue}\\ INJECT | ns%%K{green}\\ NEXT' "$CRITICAL_PROMPT_RECORD|$SEGMENT_TEXT" "critical and hostile prompt sanitization"

assert_guard_class() {
  local expected="$1"
  local name="$2"
  shift 2
  reply=()
  _kube_guard_classify "$@"
  assert_eq "$expected" "${(j:|:)reply}" "$name"
}

assert_guard_class 'read|get|pods' 'get is read-only' get pods
assert_guard_class 'read|rollout|status' 'rollout status is read-only' rollout status deployment/api
assert_guard_class 'write|rollout|restart' 'rollout restart is a write' rollout restart deployment/api
assert_guard_class 'destructive|delete|pod' 'delete is destructive' delete pod api
assert_guard_class 'write|patch|deployment' 'leading context flag is skipped' --context gke_jkopay-prod-app_asia-east1_application patch deployment api
assert_guard_class 'local|config|use-context' 'config use-context is local' config use-context orbstack

_kube_guard_action high write
assert_eq 'type-target' "$REPLY" 'high write requires target'
_kube_guard_action critical write
typeset CRITICAL_WRITE_ACTION="$REPLY"
_kube_guard_action critical unknown
typeset CRITICAL_UNKNOWN_ACTION="$REPLY"
_kube_guard_action critical destructive
typeset CRITICAL_DESTRUCTIVE_ACTION="$REPLY"
assert_eq 'type-context|type-context|type-context' "$CRITICAL_WRITE_ACTION|$CRITICAL_UNKNOWN_ACTION|$CRITICAL_DESTRUCTIVE_ACTION" 'critical actions require context'
_kube_guard_action medium write
assert_eq 'confirm' "$REPLY" 'medium write requires confirmation'
_kube_guard_action low write
assert_eq 'allow' "$REPLY" 'low write is allowed'
_kube_guard_action low destructive
assert_eq 'confirm' "$REPLY" 'low destructive requires confirmation'

_kube_context_profile kubernetes-admin@application-01
typeset IDC_MIXED_RISK="${reply[4]}"
_kube_guard_action "$IDC_MIXED_RISK" write
typeset IDC_MIXED_WRITE_ACTION="$REPLY"
_kube_guard_action "$IDC_MIXED_RISK" destructive
typeset IDC_MIXED_DESTRUCTIVE_ACTION="$REPLY"
_kube_guard_action "$IDC_MIXED_RISK" unknown
typeset IDC_MIXED_UNKNOWN_ACTION="$REPLY"
assert_eq 'medium|confirm|type-target|confirm' "$IDC_MIXED_RISK|$IDC_MIXED_WRITE_ACTION|$IDC_MIXED_DESTRUCTIVE_ACTION|$IDC_MIXED_UNKNOWN_ACTION" 'application-01 profile maps to medium guard policy'

export TEST_KUBE_CURRENT_CONTEXT=gke_jkopay-uat-app_asia-east1_application
reply=()
_kube_guard_resolve_context get pods
CURRENT_CONTEXT_RESOLUTION="${(j:|:)reply}"
reply=()
_kube_guard_resolve_context --context gke_jkopay-prod-app_asia-east1_application get pods
EXPLICIT_CONTEXT_RESOLUTION="${(j:|:)reply}"
assert_eq 'gke_jkopay-uat-app_asia-east1_application|false|gke_jkopay-prod-app_asia-east1_application|true' "$CURRENT_CONTEXT_RESOLUTION|$EXPLICIT_CONTEXT_RESOLUTION" 'exported and explicit context resolvers'
reply=()
_kube_guard_resolve_context --context= get pods
assert_eq '|true' "${(j:|:)reply}" 'empty explicit context remains explicit for the guard'

reply=()
_kube_guard_classify --profile-output config patch deployment api
PROFILE_CONFIG_CLASS="${(j:|:)reply}"
reply=()
_kube_guard_classify --profile-output get patch deployment api
PROFILE_GET_CLASS="${(j:|:)reply}"
reply=()
_kube_guard_classify --warnings-as-errors=true get pods
BOOLEAN_GLOBAL_CLASS="${(j:|:)reply}"
reply=()
_kube_guard_classify --unknown-global config patch deployment api
UNKNOWN_GLOBAL_CLASS="${(j:|:)reply}"
reply=()
_kube_guard_classify auth --profile-output reconcile reconcile -f policy.yaml
AUTH_PROFILE_CLASS="${(j:|:)reply}"
reply=()
_kube_guard_classify certificate --profile-output approve approve csr/example
CERTIFICATE_PROFILE_CLASS="${(j:|:)reply}"
reply=()
_kube_guard_classify rollout --profile-output status status deployment/api
ROLLOUT_PROFILE_CLASS="${(j:|:)reply}"
reply=()
_kube_guard_classify auth --unknown-global reconcile
AUTH_UNKNOWN_CLASS="${(j:|:)reply}"
reply=()
_kube_guard_classify auth -- reconcile
AUTH_SEPARATOR_CLASS="${(j:|:)reply}"
export TEST_KUBE_CURRENT_CONTEXT=gke_jkopay-sit-app_asia-east1_application
export TEST_KUBE_NAMESPACE=default
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=default
LOW_PROFILE_OUTPUT="$(kubectl --profile-output get patch deployment api 2>&1)"
LOW_PROFILE_STATUS="$?"
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-prod-app_asia-east1_application
HIGH_PROFILE_OUTPUT="$(kubectl --context gke_jkopay-prod-app_asia-east1_application --profile-output config patch deployment api 2>&1)"
HIGH_PROFILE_STATUS="$?"
assert_eq 'write|patch|deployment|write|patch|deployment|read|get|pods|unknown|||write|auth|reconcile|write|certificate|approve|read|rollout|status|unknown|auth||read|auth||0|EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=default --profile-output get patch deployment api|1|blocked' "$PROFILE_CONFIG_CLASS|$PROFILE_GET_CLASS|$BOOLEAN_GLOBAL_CLASS|$UNKNOWN_GLOBAL_CLASS|$AUTH_PROFILE_CLASS|$CERTIFICATE_PROFILE_CLASS|$ROLLOUT_PROFILE_CLASS|$AUTH_UNKNOWN_CLASS|$AUTH_SEPARATOR_CLASS|$LOW_PROFILE_STATUS|$LOW_PROFILE_OUTPUT|$HIGH_PROFILE_STATUS|$([[ "$HIGH_PROFILE_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'profiling values and grouped verbs use safe policy paths'

export TEST_KUBE_NAMESPACE=''
reply=()
_kube_guard_resolve_namespace gke_jkopay-sit-app_asia-east1_application get pods
DEFAULT_NAMESPACE_RESOLUTION="${(j:|:)reply}"
export TEST_KUBE_NAMESPACE=resolver-ns
reply=()
_kube_guard_resolve_namespace gke_jkopay-sit-app_asia-east1_application get pods
IMPLICIT_NAMESPACE_RESOLUTION="${(j:|:)reply}"
assert_eq 'default|false|resolver-ns|false' "$DEFAULT_NAMESPACE_RESOLUTION|$IMPLICIT_NAMESPACE_RESOLUTION" 'default and exported implicit namespace resolvers'
reply=()
_kube_guard_resolve_namespace gke_jkopay-sit-app_asia-east1_application -n first --namespace=second -nfoundation get pods
assert_eq 'foundation|true' "${(j:|:)reply}" 'mixed namespace flags use the final explicit target'

reply=()
_kube_guard_resolve_namespace gke_jkopay-prod-app_asia-east1_application -n foundation -A get pods
ALL_NAMESPACE_RESOLUTION="${(j:|:)reply}"
_kube_context_profile gke_jkopay-prod-app_asia-east1_application
ALL_NAMESPACE_RISK="${reply[4]}"
_kube_guard_action "$ALL_NAMESPACE_RISK" write
ALL_NAMESPACE_ACTION="$REPLY"
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=default
KUBE_PROMPT_LAST_SOURCE='<unset>'
export TEST_KUBE_CURRENT_CONTEXT=gke_jkopay-sit-app_asia-east1_application
export TEST_KUBE_NAMESPACE=default
ALL_NAMESPACE_EXECUTION="$(kubectl patch deployment api --all-namespaces)"
assert_eq 'all-namespaces|true|high|type-target|prod:all-namespaces|EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=default patch deployment api --all-namespaces' "$ALL_NAMESPACE_RESOLUTION|$ALL_NAMESPACE_RISK|$ALL_NAMESPACE_ACTION|prod:${ALL_NAMESPACE_RESOLUTION%%|*}|$ALL_NAMESPACE_EXECUTION" 'all namespaces is canonical while unqualified execution receives a safety pin'

reply=()
_kube_guard_resolve_namespace gke_jkopay-prod-app_asia-east1_application --context=gke_jkopay-prod-app_asia-east1_application apply -f -A
AMBIGUOUS_ALL_SHORT_NAMESPACE="${(j:|:)reply}"
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=default
KUBE_PROMPT_LAST_SOURCE='<unset>'
export TEST_KUBE_CURRENT_CONTEXT=gke_jkopay-sit-app_asia-east1_application
export TEST_KUBE_NAMESPACE=default
AMBIGUOUS_ALL_SHORT_EXECUTION="$(kubectl apply -f -A)"
AMBIGUOUS_ALL_LONG_EXECUTION="$(kubectl apply -f --all-namespaces)"
assert_eq 'all-namespaces|true|EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=default apply -f -A|EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=default apply -f --all-namespaces' "$AMBIGUOUS_ALL_SHORT_NAMESPACE|$AMBIGUOUS_ALL_SHORT_EXECUTION|$AMBIGUOUS_ALL_LONG_EXECUTION" 'ambiguous all-namespaces forms display scope and retain an implicit safety pin'

reply=()
_kube_guard_resolve_namespace gke_jkopay-prod-app_asia-east1_application --context=gke_jkopay-prod-app_asia-east1_application delete pod api -A
ACTUAL_DELETE_ALL_NAMESPACE="${(j:|:)reply}"
_kube_context_profile gke_jkopay-prod-app_asia-east1_application
_kube_guard_action "${reply[4]}" destructive
assert_eq 'all-namespaces|true|type-target|prod:all-namespaces' "$ACTUAL_DELETE_ALL_NAMESPACE|$REPLY|prod:${ACTUAL_DELETE_ALL_NAMESPACE%%|*}" 'actual delete all-namespaces retains canonical confirmation scope'

KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=default
KUBE_PROMPT_LAST_SOURCE='<unset>'
export TEST_KUBE_NAMESPACE=changed-namespace
AMBIGUOUS_ALL_DRIFT_OUTPUT="$(kubectl apply -f -A 2>&1)"
AMBIGUOUS_ALL_DRIFT_STATUS="$?"
assert_eq '1|blocked' "$AMBIGUOUS_ALL_DRIFT_STATUS|$([[ "$AMBIGUOUS_ALL_DRIFT_OUTPUT" == *'namespace changed'* && "$AMBIGUOUS_ALL_DRIFT_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'ambiguous all-namespaces form receives normal namespace drift protection'
export TEST_KUBE_NAMESPACE=default

reply=()
_kube_guard_resolve_namespace gke_jkopay-sit-app_asia-east1_application --all-namespaces=true get pods
ALL_NAMESPACES_LONG_TRUE="${(j:|:)reply}"
reply=()
_kube_guard_resolve_namespace gke_jkopay-sit-app_asia-east1_application -A=TRUE get pods
ALL_NAMESPACES_SHORT_TRUE="${(j:|:)reply}"
export TEST_KUBE_NAMESPACE=normal-ns
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=normal-ns
KUBE_PROMPT_LAST_SOURCE='<unset>'
ALL_NAMESPACES_FALSE_EXECUTION="$(kubectl patch deployment api --all-namespaces=false)"
ALL_NAMESPACES_INVALID_OUTPUT="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n normal-ns patch deployment api --all-namespaces=invalid 2>&1)"
ALL_NAMESPACES_INVALID_STATUS="$?"
assert_eq 'all-namespaces|true|all-namespaces|true|EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=normal-ns patch deployment api --all-namespaces=false|1|blocked' "$ALL_NAMESPACES_LONG_TRUE|$ALL_NAMESPACES_SHORT_TRUE|$ALL_NAMESPACES_FALSE_EXECUTION|$ALL_NAMESPACES_INVALID_STATUS|$([[ "$ALL_NAMESPACES_INVALID_OUTPUT" == *'invalid all-namespaces value'* && "$ALL_NAMESPACES_INVALID_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'assigned all-namespaces booleans handle true, false, and invalid values safely'

reply=()
_kube_guard_resolve_namespace gke_jkopay-sit-app_asia-east1_application -A=0 get pods
assert_eq 'normal-ns|false' "${(j:|:)reply}" 'short all-namespaces zero remains namespace scoped'
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=normal-ns
KUBE_PROMPT_LAST_SOURCE='<unset>'
SHORT_FALSE_EXECUTION="$(kubectl patch deployment api -A=false)"
assert_eq 'EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=normal-ns patch deployment api -A=false' "$SHORT_FALSE_EXECUTION" 'short all-namespaces false retains implicit namespace pin'
SHORT_INVALID_OUTPUT="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n normal-ns patch deployment api -A=invalid 2>&1)"
SHORT_INVALID_STATUS="$?"
assert_eq '1|blocked' "$SHORT_INVALID_STATUS|$([[ "$SHORT_INVALID_OUTPUT" == *'invalid all-namespaces value'* && "$SHORT_INVALID_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'invalid short all-namespaces value blocks before execution'

AMBIGUOUS_A_OUTPUT="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n normal-ns patch deployment api -wA 2>&1)"
AMBIGUOUS_A_STATUS="$?"
assert_eq '1|blocked' "$AMBIGUOUS_A_STATUS|$([[ "$AMBIGUOUS_A_OUTPUT" == *'separate flags'* && "$AMBIGUOUS_A_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'ambiguous bundled all-namespaces shorthand blocks before execution'
AMBIGUOUS_A_TRUE_OUTPUT="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n normal-ns patch deployment api -wA=true 2>&1)"
AMBIGUOUS_A_TRUE_STATUS="$?"
assert_eq '1|blocked' "$AMBIGUOUS_A_TRUE_STATUS|$([[ "$AMBIGUOUS_A_TRUE_OUTPUT" == *'separate flags'* && "$AMBIGUOUS_A_TRUE_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'true assigned ambiguous all-namespaces shorthand blocks before execution'
AMBIGUOUS_A_FALSE_OUTPUT="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n normal-ns patch deployment api -wA=false 2>&1)"
AMBIGUOUS_A_FALSE_STATUS="$?"
assert_eq '1|blocked' "$AMBIGUOUS_A_FALSE_STATUS|$([[ "$AMBIGUOUS_A_FALSE_OUTPUT" == *'separate flags'* && "$AMBIGUOUS_A_FALSE_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'false assigned ambiguous all-namespaces shorthand blocks before execution'
AMBIGUOUS_A_INVALID_OUTPUT="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n normal-ns patch deployment api -wA=invalid 2>&1)"
AMBIGUOUS_A_INVALID_STATUS="$?"
assert_eq '1|blocked' "$AMBIGUOUS_A_INVALID_STATUS|$([[ "$AMBIGUOUS_A_INVALID_OUTPUT" == *'separate flags'* && "$AMBIGUOUS_A_INVALID_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'invalid assigned ambiguous all-namespaces shorthand blocks before execution'
AMBIGUOUS_A_SERVER_OUTPUT="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n normal-ns patch deployment api -Ashttps://prod.example 2>&1)"
AMBIGUOUS_A_SERVER_STATUS="$?"
assert_eq '1|blocked' "$AMBIGUOUS_A_SERVER_STATUS|$([[ "$AMBIGUOUS_A_SERVER_OUTPUT" == *'separate flags'* && "$AMBIGUOUS_A_SERVER_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'A-leading server shorthand bundle blocks before execution'
AMBIGUOUS_A_SERVER_EQUALS_OUTPUT="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n normal-ns patch deployment api -As=https://prod.example 2>&1)"
AMBIGUOUS_A_SERVER_EQUALS_STATUS="$?"
assert_eq '1|blocked' "$AMBIGUOUS_A_SERVER_EQUALS_STATUS|$([[ "$AMBIGUOUS_A_SERVER_EQUALS_OUTPUT" == *'separate flags'* && "$AMBIGUOUS_A_SERVER_EQUALS_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'assigned A-leading server shorthand bundle blocks before execution'
reply=()
_kube_guard_classify -Al get delete pod api
EXACT_AL_CLASS="${(j:|:)reply}"
reply=()
_kube_guard_resolve_namespace gke_jkopay-prod-app_asia-east1_application --context=gke_jkopay-prod-app_asia-east1_application -Al get delete pod api
EXACT_AL_NAMESPACE="${(j:|:)reply}"
EXACT_AL_OUTPUT="$(kubectl --context=gke_jkopay-prod-app_asia-east1_application -Al get delete pod api 2>&1)"
EXACT_AL_STATUS="$?"
assert_eq 'destructive|delete|pod|all-namespaces|true|1|blocked' "$EXACT_AL_CLASS|$EXACT_AL_NAMESPACE|$EXACT_AL_STATUS|$([[ "$EXACT_AL_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'bare A-label bundle consumes selector before destructive root'

reply=()
_kube_guard_resolve_namespace gke_jkopay-prod-app_asia-east1_application --context=gke_jkopay-prod-app_asia-east1_application -n foundation patch deployment api -Al=app=api
ALL_NAMESPACES_BUNDLE_RESOLUTION="${(j:|:)reply}"
_kube_context_profile gke_jkopay-prod-app_asia-east1_application
_kube_guard_action "${reply[4]}" write
ALL_NAMESPACES_BUNDLE_ACTION="$REPLY"
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=foundation
KUBE_PROMPT_LAST_SOURCE='<unset>'
export TEST_KUBE_NAMESPACE=foundation
ALL_NAMESPACES_BUNDLE_EXECUTION="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n foundation patch deployment api -Al=app=api)"
assert_eq 'all-namespaces|true|type-target|prod:all-namespaces|EXEC:--context=gke_jkopay-sit-app_asia-east1_application -n foundation patch deployment api -Al=app=api' "$ALL_NAMESPACES_BUNDLE_RESOLUTION|$ALL_NAMESPACES_BUNDLE_ACTION|prod:${ALL_NAMESPACES_BUNDLE_RESOLUTION%%|*}|$ALL_NAMESPACES_BUNDLE_EXECUTION" 'bundled all-namespaces shorthand is canonical and omits namespace pin'

export TEST_KUBE_NAMESPACE=default
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=default
KUBE_PROMPT_LAST_SOURCE='<unset>'
assert_eq 'EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=default exec pod/api -- env --all-namespaces --all-namespaces=invalid -Al=app=api -wA=false' "$(kubectl exec pod/api -- env --all-namespaces --all-namespaces=invalid -Al=app=api -wA=false)" 'all namespaces values after exec payload separator stay opaque'
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=default
KUBE_PROMPT_LAST_SOURCE='<unset>'
assert_eq 'EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=default cp -- -A' "$(kubectl cp -- -A)" 'cp short all-namespaces payload stays opaque'
assert_eq 'EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=default cp -- --all-namespaces' "$(kubectl cp -- --all-namespaces)" 'cp long all-namespaces payload stays opaque'
PAYLOAD_SHORT_SERVER_OUTPUT="$(kubectl exec pod/api --container app -- -shttps://prod.example 2>&1)"
PAYLOAD_SHORT_SERVER_STATUS="$?"
assert_eq '1|blocked' "$PAYLOAD_SHORT_SERVER_STATUS|$([[ "$PAYLOAD_SHORT_SERVER_OUTPUT" == *'connection override'* && "$PAYLOAD_SHORT_SERVER_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'exec payload server shorthand blocks before execution'
PAYLOAD_CP_SERVER_OUTPUT="$(kubectl cp --container app -- -s=https://prod.example 2>&1)"
PAYLOAD_CP_SERVER_STATUS="$?"
assert_eq '1|blocked' "$PAYLOAD_CP_SERVER_STATUS|$([[ "$PAYLOAD_CP_SERVER_OUTPUT" == *'connection override'* && "$PAYLOAD_CP_SERVER_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'cp payload server shorthand blocks before execution'
PAYLOAD_LONG_SERVER_OUTPUT="$(kubectl exec pod/api -- --server=https://prod.example 2>&1)"
PAYLOAD_LONG_SERVER_STATUS="$?"
assert_eq '1|blocked' "$PAYLOAD_LONG_SERVER_STATUS|$([[ "$PAYLOAD_LONG_SERVER_OUTPUT" == *'connection override'* && "$PAYLOAD_LONG_SERVER_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'exec payload long server override blocks before execution'
SHORT_BUNDLE_SERVER_OUTPUT="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n sit patch deployment api -wshttps://prod.example 2>&1)"
SHORT_BUNDLE_SERVER_STATUS="$?"
assert_eq '1|blocked' "$SHORT_BUNDLE_SERVER_STATUS|$([[ "$SHORT_BUNDLE_SERVER_OUTPUT" == *'connection override'* && "$SHORT_BUNDLE_SERVER_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'bundled server shorthand blocks before execution'
SHORT_BUNDLE_SERVER_EQUALS_OUTPUT="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n sit patch deployment api -ws=https://prod.example 2>&1)"
SHORT_BUNDLE_SERVER_EQUALS_STATUS="$?"
assert_eq '1|blocked' "$SHORT_BUNDLE_SERVER_EQUALS_STATUS|$([[ "$SHORT_BUNDLE_SERVER_EQUALS_OUTPUT" == *'connection override'* && "$SHORT_BUNDLE_SERVER_EQUALS_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'assigned bundled server shorthand blocks before execution'
NAMESPACE_SHORT_SPLIT_EXECUTION="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n sit patch deployment api)"
NAMESPACE_SHORT_ATTACHED_EXECUTION="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -nsit patch deployment api)"
assert_eq 'EXEC:--context=gke_jkopay-sit-app_asia-east1_application -n sit patch deployment api|EXEC:--context=gke_jkopay-sit-app_asia-east1_application -nsit patch deployment api' "$NAMESPACE_SHORT_SPLIT_EXECUTION|$NAMESPACE_SHORT_ATTACHED_EXECUTION" 'namespace short forms remain valid outside raw override scanning'
reply=()
_kube_guard_resolve_namespace gke_jkopay-prod-app_asia-east1_application --context=gke_jkopay-prod-app_asia-east1_application -n foundation patch deployment api -Alstatus=ready
AL_SELECTOR_NAMESPACE="${(j:|:)reply}"
AL_SELECTOR_EXECUTION="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n foundation patch deployment api -Alstatus=ready)"
assert_eq 'all-namespaces|true|EXEC:--context=gke_jkopay-sit-app_asia-east1_application -n foundation patch deployment api -Alstatus=ready' "$AL_SELECTOR_NAMESPACE|$AL_SELECTOR_EXECUTION" 'label-selector A bundle remains canonical without connection block'

export TEST_KUBE_CURRENT_CONTEXT=gke_jkopay-sit-app_asia-east1_application
export TEST_KUBE_NAMESPACE=default
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-prod-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=default
STALE_CONTEXT_OUTPUT="$(kubectl get pods 2>&1)"
STALE_CONTEXT_STATUS="$?"
assert_eq '1|blocked' "$STALE_CONTEXT_STATUS|$([[ "$STALE_CONTEXT_OUTPUT" == *'context changed'* ]] && print blocked || print executed)" 'stale context blocks command'

KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=default
NORMAL_SEPARATOR_OUTPUT="$(kubectl exec pod/api -- env --context=orbstack)"
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=foundation
RAW_BOUNDARY_OUTPUT="$(kubectl --context gke_jkopay-sit-app_asia-east1_application -n foundation --profile-output -- -s=https://prod.example patch deployment api 2>&1)"
RAW_BOUNDARY_STATUS="$?"
assert_eq 'EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=default exec pod/api -- env --context=orbstack|1|blocked' "$NORMAL_SEPARATOR_OUTPUT|$RAW_BOUNDARY_STATUS|$([[ "$RAW_BOUNDARY_OUTPUT" == *'connection override'* && "$RAW_BOUNDARY_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'separator payload stays opaque but option values do not create a boundary'

KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=foundation
STALE_NAMESPACE_OUTPUT="$(kubectl get pods 2>&1)"
STALE_NAMESPACE_STATUS="$?"
assert_eq '1|blocked' "$STALE_NAMESPACE_STATUS|$([[ "$STALE_NAMESPACE_OUTPUT" == *'namespace changed'* ]] && print blocked || print executed)" 'stale namespace blocks command'

KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=stale
assert_eq 'EXEC:--context=gke_jkopay-sit-app_asia-east1_application -n first --namespace=second -nfoundation get pods' "$(kubectl -n first --namespace=second -nfoundation get pods)" 'mixed explicit namespace bypasses stale namespace without a pin'

KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=default
OVERRIDE_OUTPUT="$(kubectl --kubeconfig /tmp/prod-config patch deployment api 2>&1)"
OVERRIDE_STATUS="$?"
SHORT_SERVER_OUTPUT="$(kubectl -s https://prod.example patch deployment api 2>&1)"
SHORT_SERVER_STATUS="$?"
EQUALS_SERVER_OUTPUT="$(kubectl -s=https://prod.example patch deployment api 2>&1)"
EQUALS_SERVER_STATUS="$?"
ATTACHED_SERVER_OUTPUT="$(kubectl -shttps://prod.example patch deployment api 2>&1)"
ATTACHED_SERVER_STATUS="$?"
IDENTITY_OVERRIDE_OUTPUT="$(kubectl --as-uid 1 --username user --password pass patch deployment api 2>&1)"
IDENTITY_OVERRIDE_STATUS="$?"
IDENTITY_EQUALS_OUTPUT="$(kubectl --as-uid=1 --username=user --password=pass patch deployment api 2>&1)"
IDENTITY_EQUALS_STATUS="$?"
assert_eq '1|1|1|1|1|1|blocked|blocked|blocked|blocked|blocked|blocked' "$OVERRIDE_STATUS|$SHORT_SERVER_STATUS|$EQUALS_SERVER_STATUS|$ATTACHED_SERVER_STATUS|$IDENTITY_OVERRIDE_STATUS|$IDENTITY_EQUALS_STATUS|$([[ "$OVERRIDE_OUTPUT" == *'connection override'* && "$OVERRIDE_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)|$([[ "$SHORT_SERVER_OUTPUT" == *'connection override'* && "$SHORT_SERVER_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)|$([[ "$EQUALS_SERVER_OUTPUT" == *'connection override'* && "$EQUALS_SERVER_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)|$([[ "$ATTACHED_SERVER_OUTPUT" == *'connection override'* && "$ATTACHED_SERVER_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)|$([[ "$IDENTITY_OVERRIDE_OUTPUT" == *'connection override'* && "$IDENTITY_OVERRIDE_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)|$([[ "$IDENTITY_EQUALS_OUTPUT" == *'connection override'* && "$IDENTITY_EQUALS_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'connection and identity overrides fail closed'

export TEST_KUBE_CURRENT_CONTEXT=gke_jkopay-sit-app_asia-east1_application
EMPTY_CONTEXT_EQUALS_OUTPUT="$(kubectl --context= delete pod api 2>&1)"
EMPTY_CONTEXT_EQUALS_STATUS="$?"
EMPTY_CONTEXT_SPACE_OUTPUT="$(kubectl --context '' delete pod api 2>&1)"
EMPTY_CONTEXT_SPACE_STATUS="$?"
assert_eq '1|1|blocked' "$EMPTY_CONTEXT_EQUALS_STATUS|$EMPTY_CONTEXT_SPACE_STATUS|$([[ "$EMPTY_CONTEXT_EQUALS_OUTPUT$EMPTY_CONTEXT_SPACE_OUTPUT" == *'explicit target is empty'* && "$EMPTY_CONTEXT_EQUALS_OUTPUT$EMPTY_CONTEXT_SPACE_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'empty explicit context forms never raw-execute destructive command'

KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=default
KUBE_PROMPT_LAST_SOURCE='<unset>'
export TEST_KUBE_NAMESPACE=nonempty
EMPTY_NAMESPACE_EQUALS_OUTPUT="$(kubectl --namespace= get pods 2>&1)"
EMPTY_NAMESPACE_EQUALS_STATUS="$?"
EMPTY_NAMESPACE_SPACE_OUTPUT="$(kubectl --namespace '' get pods 2>&1)"
EMPTY_NAMESPACE_SPACE_STATUS="$?"
EMPTY_SHORT_EQUALS_OUTPUT="$(kubectl -n= get pods 2>&1)"
EMPTY_SHORT_EQUALS_STATUS="$?"
EMPTY_SHORT_SPACE_OUTPUT="$(kubectl -n '' get pods 2>&1)"
EMPTY_SHORT_SPACE_STATUS="$?"
assert_eq '1|1|1|1|blocked' "$EMPTY_NAMESPACE_EQUALS_STATUS|$EMPTY_NAMESPACE_SPACE_STATUS|$EMPTY_SHORT_EQUALS_STATUS|$EMPTY_SHORT_SPACE_STATUS|$([[ "$EMPTY_NAMESPACE_EQUALS_OUTPUT$EMPTY_NAMESPACE_SPACE_OUTPUT$EMPTY_SHORT_EQUALS_OUTPUT$EMPTY_SHORT_SPACE_OUTPUT" == *'explicit target is empty'* && "$EMPTY_NAMESPACE_EQUALS_OUTPUT$EMPTY_NAMESPACE_SPACE_OUTPUT$EMPTY_SHORT_EQUALS_OUTPUT$EMPTY_SHORT_SPACE_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'empty explicit namespace forms fail closed'

export TEST_KUBE_CURRENT_CONTEXT=gke_jkopay-sit-app_asia-east1_application
export TEST_KUBE_NAMESPACE=race-ns
export TEST_KUBE_RACE_FILE="$FIXTURE_DIR/.kube-guard-race-${$}"
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=race-ns
RACE_OUTPUT="$(kubectl get pods)"
RACE_STATUS="$?"
assert_eq '0|EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=race-ns get pods|changed' "$RACE_STATUS|$RACE_OUTPUT|$([[ -f "$TEST_KUBE_RACE_FILE" ]] && print changed || print unchanged)" 'implicit target is pinned across config change'
command rm -f -- "$TEST_KUBE_RACE_FILE"
unset TEST_KUBE_RACE_FILE

export TEST_KUBE_CURRENT_CONTEXT=gke_jkopay-sit-app_asia-east1_application
export TEST_KUBE_NAMESPACE=default
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=default
KUBE_PROMPT_LAST_SOURCE='<unset>'
unset KUBECONFIG
POST_VERB_TARGET_OUTPUT="$(kubectl apply -f --context=orbstack 2>&1)"
POST_VERB_TARGET_STATUS="$?"
PRE_VERB_TARGET_OUTPUT="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application -n foundation apply -f manifest.yaml)"
assert_eq '1|blocked|EXEC:--context=gke_jkopay-sit-app_asia-east1_application -n foundation apply -f manifest.yaml' "$POST_VERB_TARGET_STATUS|$([[ "$POST_VERB_TARGET_OUTPUT" == *'place target flags before the verb'* && "$POST_VERB_TARGET_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)|$PRE_VERB_TARGET_OUTPUT" 'target flags after the verb fail closed'

INSECURE_OUTPUT="$(kubectl --insecure-skip-tls-verify patch deployment api 2>&1)"
INSECURE_STATUS="$?"
INSECURE_EQUALS_OUTPUT="$(kubectl --insecure-skip-tls-verify=true patch deployment api 2>&1)"
INSECURE_EQUALS_STATUS="$?"
assert_eq '1|1|blocked|blocked' "$INSECURE_STATUS|$INSECURE_EQUALS_STATUS|$([[ "$INSECURE_OUTPUT" == *'connection override'* ]] && print blocked || print executed)|$([[ "$INSECURE_EQUALS_OUTPUT" == *'connection override'* ]] && print blocked || print executed)" 'insecure TLS overrides fail closed'

KUBE_PS1_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PS1_NAMESPACE=default
unset KUBECONFIG
_kube_prompt_capture
export KUBECONFIG=/tmp/other-config
SOURCE_DRIFT_OUTPUT="$(kubectl get pods 2>&1)"
SOURCE_DRIFT_STATUS="$?"
assert_eq '1|blocked' "$SOURCE_DRIFT_STATUS|$([[ "$SOURCE_DRIFT_OUTPUT" == *'kubeconfig source changed'* && "$SOURCE_DRIFT_OUTPUT" != *'/tmp/other-config'* && "$SOURCE_DRIFT_OUTPUT" != *'EXEC:'* ]] && print blocked || print executed)" 'kubeconfig provenance drift blocks reads'
unset KUBECONFIG

KUBE_PS1_CONTEXT=gke_jkopay-uat-app_asia-east1_application
KUBE_PS1_NAMESPACE=render-ns
_kube_prompt_capture
CAPTURE_SIGNATURE="$KUBE_PROMPT_LAST_CONTEXT|$KUBE_PROMPT_LAST_NAMESPACE"
KUBE_PS1_CONTEXT=orbstack
KUBE_PS1_NAMESPACE=changed-by-render
prompt_kube
assert_eq 'gke_jkopay-uat-app_asia-east1_application|render-ns|gke_jkopay-uat-app_asia-east1_application|render-ns' "$CAPTURE_SIGNATURE|$KUBE_PROMPT_LAST_CONTEXT|$KUBE_PROMPT_LAST_NAMESPACE" 'prompt render does not mutate parent snapshot'

typeset -a CAPTURE_HOOKS=( "${(@M)precmd_functions:#_kube_prompt_capture}" )
source "$TEST_ROOT/chezmoi/private_dot_config/zsh/kubernetes.zsh" 2>/dev/null
typeset -a RESOURCED_CAPTURE_HOOKS=( "${(@M)precmd_functions:#_kube_prompt_capture}" )
assert_eq '1|1|_kube_prompt_capture' "${#CAPTURE_HOOKS}|${#RESOURCED_CAPTURE_HOOKS}|${precmd_functions[-1]}" 'capture hook is unique and appended after prior hooks'

KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=stale
KUBE_PROMPT_LAST_SOURCE='<unset>'
export TEST_KUBE_NAMESPACE=fresh
EXPLICIT_CONTEXT_NAMESPACE_OUTPUT="$(kubectl --context=gke_jkopay-sit-app_asia-east1_application get pods)"
assert_eq 'EXEC:--namespace=fresh --context=gke_jkopay-sit-app_asia-east1_application get pods' "$EXPLICIT_CONTEXT_NAMESPACE_OUTPUT" 'explicit context bypasses namespace drift and pins fresh namespace'

reply=()
_kube_guard_classify -- delete pod api
LEADING_SEPARATOR_CLASS="${(j:|:)reply}"
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=fresh
KUBE_PROMPT_LAST_SOURCE='<unset>'
assert_eq 'destructive|delete|pod|EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=fresh -- get pods' "$LEADING_SEPARATOR_CLASS|$(kubectl -- get pods)" 'leading separator preserves destructive root and receives pins before it'

KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=fresh
KUBE_PROMPT_LAST_SOURCE='<unset>'
assert_eq 'EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=fresh create -- payload' "$(kubectl create -- payload)" 'implicit pins precede non-exec trailing separator'

HOSTILE_PROMPT_CONTEXT=$'prompt\e]8;;evil\a'
HOSTILE_CURRENT_CONTEXT=$'current\e]8;;evil\a'
KUBE_PROMPT_LAST_CONTEXT="$HOSTILE_PROMPT_CONTEXT"
KUBE_PROMPT_LAST_NAMESPACE=default
KUBE_PROMPT_LAST_SOURCE='<unset>'
export TEST_KUBE_CURRENT_CONTEXT="$HOSTILE_CURRENT_CONTEXT"
export TEST_KUBE_NAMESPACE=default
HOSTILE_DRIFT_OUTPUT="$(kubectl get pods 2>&1)"
HOSTILE_DRIFT_STATUS="$?"
assert_eq '1|safe' "$HOSTILE_DRIFT_STATUS|$([[ "$HOSTILE_DRIFT_OUTPUT" == *$'\e'* || "$HOSTILE_DRIFT_OUTPUT" == *$'\a'* ]] && print unsafe || print safe)" 'drift diagnostics sanitize hostile targets'
export TEST_KUBE_CURRENT_CONTEXT=gke_jkopay-sit-app_asia-east1_application

unfunction kubectl
typeset SAVED_TEST_PATH="$PATH"
PATH=/nonexistent
rehash
source "$TEST_ROOT/chezmoi/private_dot_config/zsh/kubernetes.zsh" 2>/dev/null
PATH="$FIXTURE_DIR:$SAVED_TEST_PATH"
rehash
KUBE_PROMPT_LAST_CONTEXT=gke_jkopay-sit-app_asia-east1_application
KUBE_PROMPT_LAST_NAMESPACE=default
KUBE_PROMPT_LAST_SOURCE='<unset>'
assert_eq 'EXEC:--context=gke_jkopay-sit-app_asia-east1_application --namespace=default get pods' "$(kubectl get pods)" 'wrapper survives late kubectl path initialization'

if (( TESTS_FAILED )); then
  print "$TESTS_FAILED tests failed"
  exit 1
fi

if (( TESTS_PASSED != 82 )); then
  print "expected 82 assertions, got $TESTS_PASSED"
  exit 1
fi

print "$TESTS_PASSED tests passed"
