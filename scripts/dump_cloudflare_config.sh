#!/usr/bin/env bash
# Cloudflare 現状構成のダンプ取得（.kiro/specs/infisical-cloudflare-iac-refactor タスク7.1）
#
# 使い方:
#   infisical run --token=<INFISICAL_TOKEN> --projectId=<id> --env=prod -- \
#     scripts/dump_cloudflare_config.sh
#
# TF_VAR_cloudflare_api_token / CLOUDFLARE_ACCOUNT_ID を Infisical から
# 環境変数として受け取り、Cloudflare API から現状構成を JSON で
# terraform/.discovery/ 配下へ保存する。読み取りのみで変更は行わない。
set -euo pipefail

OUT_DIR="${1:-terraform/.discovery}"
mkdir -p "$OUT_DIR"

: "${TF_VAR_cloudflare_api_token:?TF_VAR_cloudflare_api_token が未設定です}"
: "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID が未設定です}"

API="https://api.cloudflare.com/client/v4"
AUTH=(-H "Authorization: Bearer ${TF_VAR_cloudflare_api_token}")

# Cloudflare API 呼び出し + success:false を失敗として扱う（ponytail: エラー本文はそのまま保存するのみで
# リトライやレート制限バックオフは持たない。将来 429 が頻発したら sleep を挟む）
fetch() {
  local url="$1" out="$2"
  curl -sS "${AUTH[@]}" "$url" -o "$out"
  if ! jq -e '.success == true' "$out" >/dev/null 2>&1; then
    echo "FAILED: $url -> $out" >&2
    return 1
  fi
}

fail=0

fetch "$API/zones?account.id=${CLOUDFLARE_ACCOUNT_ID}&per_page=50" "$OUT_DIR/zones.json" || fail=1

zone_ids=$(jq -r '.result[].id' "$OUT_DIR/zones.json" 2>/dev/null || true)
for zid in $zone_ids; do
  fetch "$API/zones/$zid/dns_records?per_page=100" "$OUT_DIR/zone_${zid}_dns_records.json" || fail=1
  fetch "$API/zones/$zid/settings" "$OUT_DIR/zone_${zid}_settings.json" || fail=1
  fetch "$API/zones/$zid/rulesets" "$OUT_DIR/zone_${zid}_rulesets.json" || fail=1
done

fetch "$API/accounts/${CLOUDFLARE_ACCOUNT_ID}/cfd_tunnel?per_page=100" "$OUT_DIR/tunnels.json" || fail=1
fetch "$API/accounts/${CLOUDFLARE_ACCOUNT_ID}/access/apps?per_page=100" "$OUT_DIR/access_apps.json" || fail=1

app_ids=$(jq -r '.result[].id' "$OUT_DIR/access_apps.json" 2>/dev/null || true)
for aid in $app_ids; do
  fetch "$API/accounts/${CLOUDFLARE_ACCOUNT_ID}/access/apps/$aid/policies?per_page=100" "$OUT_DIR/access_app_${aid}_policies.json" || fail=1
done

fetch "$API/accounts/${CLOUDFLARE_ACCOUNT_ID}/r2/buckets" "$OUT_DIR/r2_buckets.json" || fail=1
fetch "$API/accounts/${CLOUDFLARE_ACCOUNT_ID}/workers/scripts" "$OUT_DIR/workers_scripts.json" || fail=1

echo "--- summary ($OUT_DIR) ---"
echo "zones:          $(jq '.result | length' "$OUT_DIR/zones.json" 2>/dev/null || echo '?')"
for zid in $zone_ids; do
  echo "zone $zid dns_records: $(jq '.result | length' "$OUT_DIR/zone_${zid}_dns_records.json" 2>/dev/null || echo '?')"
  echo "zone $zid rulesets:    $(jq '.result | length' "$OUT_DIR/zone_${zid}_rulesets.json" 2>/dev/null || echo '?')"
done
echo "tunnels:        $(jq '.result | length' "$OUT_DIR/tunnels.json" 2>/dev/null || echo '?')"
echo "access apps:    $(jq '.result | length' "$OUT_DIR/access_apps.json" 2>/dev/null || echo '?')"
echo "r2 buckets:     $(jq '.result | length' "$OUT_DIR/r2_buckets.json" 2>/dev/null || echo '?')"
echo "workers scripts:$(jq '.result | length' "$OUT_DIR/workers_scripts.json" 2>/dev/null || echo '?')"

exit "$fail"
