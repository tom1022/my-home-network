# シークレット移送対応表

タスク 1.1 の成果物。Infisical への実投入は行わない机上作業であり、命名規則の確定と
移送前後の対応関係の記録のみを目的とする。値は一切含まない。

## Infisical プロジェクト参照

- リポジトリルートに `.infisical.json` を配置済み（`workspaceId` はプレースホルダ `<INFISICAL_PROJECT_ID>`）
- 環境スラグは `prod` の単一環境とし、パス階層は用いず全キーを平坦に保持する
- 実際の `workspaceId` は、ユーザーが Infisical プロジェクトを作成した後に `infisical init` を実行して埋める

## 命名規則

1. Ansible Vault 由来のシークレットは `vault_` 接頭辞を除去し、大文字スネークケースに変換する
   （例: `vault_gitea_admin_password` → `GITEA_ADMIN_PASSWORD`）
2. 平文でコミットされている非 Vault 変数（k3s node token）も同様に、変数名を大文字化してキー名とする
   （例: `k3s_node_token` → `K3S_NODE_TOKEN`）
3. Terraform 用シークレット（`TF_VAR_*`）は接頭辞・変数名を一切変更せず、そのままキー名とする
   （Terraform がプロセス環境変数名から直接値を解決するため、名前を変えると供給できなくなる）
4. Cloudflare の認証情報は用途ごとに個別のシークレットとして分離する（Requirement 1.7）
   - DNS-01 用（既存・DNS 編集のみの最小権限）: 命名規則1の機械的変換ではなく、用途を明示する名前
     `CLOUDFLARE_DNS01_API_TOKEN` を例外的に採用する
   - Terraform 用（新規・広域スコープ）: 規則3に従い `TF_VAR_cloudflare_api_token` とする
   - 単一の認証情報を両用途で共用しない

## 対応表

値は含めない。「移送前の所在」はファイルパスと変数名、「Infisical キー名」は移送後のキー名を示す。

### Ansible Vault 由来（暗号化ファイル5点、`.example` からキー名を特定）

| 移送前の所在 | Infisical キー名 | 備考 |
|---|---|---|
| `ansible/inventory/group_vars/all/vault.yml:vault_sssd_bind_password` | `SSSD_BIND_PASSWORD` | |
| `ansible/inventory/group_vars/all/vault.yml:vault_letsencrypt_contact_email` | `LETSENCRYPT_CONTACT_EMAIL` | |
| `ansible/inventory/group_vars/all/vault.yml:vault_letsencrypt_cloudflare_api_token` | `CLOUDFLARE_DNS01_API_TOKEN` | 命名規則4の例外。DNS-01用・既存・最小権限 |
| `ansible/inventory/group_vars/all/vault.yml:vault_proxmox_api_host` | `PROXMOX_API_HOST` | |
| `ansible/inventory/group_vars/all/vault.yml:vault_proxmox_api_user` | `PROXMOX_API_USER` | |
| `ansible/inventory/group_vars/all/vault.yml:vault_proxmox_api_token_id` | `PROXMOX_API_TOKEN_ID` | |
| `ansible/inventory/group_vars/all/vault.yml:vault_proxmox_api_token_secret` | `PROXMOX_API_TOKEN_SECRET` | |
| `ansible/inventory/group_vars/all/vault.yml:vault_proxmox_pbs_username` | `PROXMOX_PBS_USERNAME` | |
| `ansible/inventory/group_vars/all/vault.yml:vault_proxmox_pbs_password` | `PROXMOX_PBS_PASSWORD` | |
| `ansible/inventory/group_vars/all/vault.yml:vault_proxmox_pbs_fingerprint` | `PROXMOX_PBS_FINGERPRINT` | |
| `ansible/inventory/group_vars/all/vault.yml:vault_argocd_sops_age_key` | `ARGOCD_SOPS_AGE_KEY` | AVP/SOPS機構自体はタスク4.3で除去対象。それまでの移行期間用に移送のみ実施 |
| `ansible/inventory/host_vars/gitea/vault.yml:vault_gitea_db_host` | `GITEA_DB_HOST` | |
| `ansible/inventory/host_vars/gitea/vault.yml:vault_gitea_db_name` | `GITEA_DB_NAME` | |
| `ansible/inventory/host_vars/gitea/vault.yml:vault_gitea_db_user` | `GITEA_DB_USER` | |
| `ansible/inventory/host_vars/gitea/vault.yml:vault_gitea_db_password` | `GITEA_DB_PASSWORD` | |
| `ansible/inventory/host_vars/gitea/vault.yml:vault_gitea_admin_password` | `GITEA_ADMIN_PASSWORD` | |
| `ansible/inventory/host_vars/gitea/vault.yml:vault_gitea_security_secret_key` | `GITEA_SECURITY_SECRET_KEY` | |
| `ansible/inventory/host_vars/gitea/vault.yml:vault_gitea_security_internal_token` | `GITEA_SECURITY_INTERNAL_TOKEN` | |
| `ansible/inventory/host_vars/k3s-server/argocd_gitea_vault.yml:vault_argocd_gitea_username` | `ARGOCD_GITEA_USERNAME` | |
| `ansible/inventory/host_vars/k3s-server/argocd_gitea_vault.yml:vault_argocd_gitea_password` | `ARGOCD_GITEA_PASSWORD` | |
| `ansible/inventory/host_vars/pbs/vault.yml:vault_mariadb_dump_user` | `MARIADB_DUMP_USER` | |
| `ansible/inventory/host_vars/pbs/vault.yml:vault_mariadb_dump_password` | `MARIADB_DUMP_PASSWORD` | |
| `ansible/inventory/host_vars/vps/vault.yml:vault_vps_become_password` | `VPS_BECOME_PASSWORD` | |

キー名は各 `*.vault.yml.example` から特定した（対話でのパスワード取得が前提のため、暗号化ファイル自体は復号していない）。

### Terraform 由来（`terraform/.env`、キー名のみ）

作業ツリーに実ファイル `terraform/.env` は存在せず（gitignore 対象のローカルファイル）、
`terraform/.env.example` からキー名を特定した。`TF_VAR_` 接頭辞は変更しない。

| 移送前の所在 | Infisical キー名 | 備考 |
|---|---|---|
| `terraform/.env:TF_VAR_proxmox_api_url` | `TF_VAR_proxmox_api_url` | |
| `terraform/.env:TF_VAR_proxmox_auth_method` | `TF_VAR_proxmox_auth_method` | 現状値は `password`。タスク3.3でトークン認証への切替を予定 |
| `terraform/.env:TF_VAR_proxmox_username` | `TF_VAR_proxmox_username` | 現行のパスワード認証用。トークン認証切替後は不要になる可能性あり |
| `terraform/.env:TF_VAR_proxmox_password` | `TF_VAR_proxmox_password` | 同上 |
| `terraform/.env:TF_VAR_proxmox_api_token_id` | `TF_VAR_proxmox_api_token_id` | `.env.example` ではコメントアウト（token認証を選択した場合に使用）。タスク3.3での主経路になる予定 |
| `terraform/.env:TF_VAR_proxmox_api_token_secret` | `TF_VAR_proxmox_api_token_secret` | 同上 |
| `terraform/.env:TF_VAR_ssh_public_key` | `TF_VAR_ssh_public_key` | |

### Cloudflare Terraform 用（新規、移送元なし）

命名規則4に基づき、DNS-01用とは分離した Terraform 専用の広域認証情報を新規に保持する。
既存ファイルからの移送ではないため「移送前の所在」は存在しない。

| 移送前の所在 | Infisical キー名 | 備考 |
|---|---|---|
| （新規・既存ファイルなし） | `TF_VAR_cloudflare_api_token` | Terraform用・新規・広域スコープ。DNS01用トークンとは別個体で発行する |

### 平文コミット済み k3s node token

| 移送前の所在 | Infisical キー名 | 備考 |
|---|---|---|
| `ansible/inventory/host_vars/k3s-server/main.yml:8`（変数 `k3s_node_token`） | `K3S_NODE_TOKEN` | git 履歴に平文で残存。ローテーションが別途必要（タスク10.1で明示） |

## 集計

- Ansible Vault 由来: 23件
- Terraform `.env` 由来: 7件
- Cloudflare Terraform 用（新規）: 1件
- 平文 k3s node token: 1件
- **合計: 32件**

## スコープ外（本タスクでは対応表に含めない）

以下は design.md の InfisicalProjectLayout で言及されているが、既存ファイルからの移送対象（本タスクの
洗い出し対象3系統）に該当しないため、対応する後続タスクで扱う。

- `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_ZONE_ID`（タスク7.2, Cloudflare Terraform 導入時に新規変数として追加）
- `CLOUDFLARED_TUNNEL_TOKEN`（現状 gitops-apps 側の SealedSecret。タスク4.2/7.4で移行）
- `TF_TOKEN_app_terraform_io`（タスク6.1, HCP Terraform state バックエンド導入時に追加）
