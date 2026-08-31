# === HashiCorp Vault 多實例 ===
#
# token 由 ~/.local/bin/vault-token-helper 依 host 分檔存放（見 ~/.vault），
# 所以 vault CLI 只要 VAULT_ADDR 指對，就會自動用對應那座的 token。
#
# 刻意不 export VAULT_TOKEN：CLI 會優先讀環境變數而繞過 helper，
# 一旦重新登入，環境變數裡那顆就變成舊的了。需要 token 的場合只在
# 單一指令的範圍內帶入（見 tfv）。

VAULT_ADDR_JKOPAY="https://gcp-vault.jkopay.app"
VAULT_ADDR_JKOS="https://gcp-vault.jkos.app"

# _vault_token_file: 由目前的 VAULT_ADDR 推出 token 檔路徑
_vault_token_file() {
    local host="${VAULT_ADDR:-default}"
    host="${host#https://}"
    host="${host#http://}"
    host="${host//\//_}"
    printf '%s' "$HOME/.vault-tokens/${host:-default}"
}

# vault-use: 切換目前 shell 要操作哪一座 vault
#
# Usage:
#   vault-use jkopay        # 電支 gcp-vault.jkopay.app
#   vault-use jkos          # 金科 gcp-vault.jkos.app
#   vault-use               # 顯示現況
#
# 兩個終端機分頁各自 vault-use 不同座，可以同時操作互不干擾。
vault-use() {
    case "${1:-}" in
        jkopay) export VAULT_ADDR="$VAULT_ADDR_JKOPAY" ;;
        jkos)   export VAULT_ADDR="$VAULT_ADDR_JKOS" ;;
        "")
            if [[ -z "${VAULT_ADDR:-}" ]]; then
                echo "VAULT_ADDR 未設定。用法：vault-use {jkopay|jkos}"
                return 1
            fi
            ;;
        -h|--help)
            echo "Usage: vault-use {jkopay|jkos}"
            echo ""
            echo "切換目前 shell 的 VAULT_ADDR。token 由 token helper 依 host"
            echo "分檔保存，切換後不需要重新登入（除非該座還沒登過或已過期）。"
            return 0
            ;;
        *)
            echo "Unknown target: $1（可用 jkopay / jkos）" >&2
            return 1
            ;;
    esac

    local token_file="$(_vault_token_file)"
    if [[ -s "$token_file" ]]; then
        echo "VAULT_ADDR=$VAULT_ADDR（已有 token）"
    else
        echo "VAULT_ADDR=$VAULT_ADDR（尚未登入，跑 vault login -method=oidc）"
    fi
}

# tfv: 對目前 VAULT_ADDR 那座 vault 跑 terraform
#
# Usage:
#   vault-use jkos && cd vault/jkos && tfv plan
#   tfv apply tfplan
#
# Terraform 的 vault provider 不支援 token helper，只讀 VAULT_TOKEN 或
# ~/.vault-token，所以這裡把對應的 token 限縮在單一指令內帶進去。
# 順帶包掉 1Password 注入 GitLab state 認證的那串 op run。
tfv() {
    if [[ -z "${VAULT_ADDR:-}" ]]; then
        echo "Error: VAULT_ADDR 未設定，先跑 vault-use {jkopay|jkos}" >&2
        return 1
    fi

    local token_file="$(_vault_token_file)"
    if [[ ! -s "$token_file" ]]; then
        echo "Error: $VAULT_ADDR 沒有 token，先跑 vault login -method=oidc" >&2
        return 1
    fi

    local repo_root
    repo_root="$(git rev-parse --show-toplevel 2>/dev/null)"
    if [[ -z "$repo_root" ]]; then
        echo "Error: 不在 git repo 內，找不到 .env" >&2
        return 1
    fi

    VAULT_TOKEN="$(cat "$token_file")" \
        op run --account jkofintechcoltd.1password.com \
            --env-file="$repo_root/.env" -- terraform "$@"
}
