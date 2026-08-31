# Technology Stack

## Architecture

2層構成の IaC。Terraform が Proxmox 上のリソース（VM/LXC）を宣言的に作成し、Ansible がその上の
OS/ミドルウェア構成を適用する。Gitea（自前 CI 起点）から Terraform apply、ArgoCD が k3s への
マニフェスト同期を担う GitOps ループ。

## Core Technologies

- **IaC**: Terraform >= 1.5.0, provider `bpg/proxmox` >= 0.95.0
- **Configuration Management**: Ansible >= 10.7.0（Role ベース）, ansible-lint >= 26.3.0
- **Virtualization**: Proxmox VE（VM: qemu-guest-agent 前提, LXC: Debian 12 テンプレート）
- **GitOps**: ArgoCD（`gitops/apps/`, ApplicationSet パターン）
- **Edge/Proxy**: Nginx, HAProxy（TCP stream）, Cloudflare, Tailscale
- **Runtime**: Python >= 3.10（uv 管理, `pyproject.toml` / `uv.lock`）

## Key Libraries

- `rlex.k3s`（外部 Ansible Role, k3s クラスタ構築）
- Terraform provider `bpg/proxmox`（VM/LXC/ストレージ/ネットワーク管理）

## Development Standards

### Secrets
- シークレットの単一の正は Infisical（workspace は `.infisical.json` の `workspaceId` で固定、
  環境は `prod` 単一）。Ansible / Terraform / Kubernetes のいずれもここから値を取得する。
- Ansible: ロール本体は一般名の変数のみ参照する既存の変数間接化層を維持し、`group_vars` /
  `host_vars` の右辺だけを `lookup('env', 'VAR_NAME')` に束縛する。`inventory/**/vault.yml`
  （Ansible Vault 暗号化ファイル）は追跡対象から除去済みで、供給経路として使わない。
  `vault.yml.example` は移行前の変数名一覧としてのみ残置している。
- Terraform: 変数名を変えず `TF_VAR_` 接頭辞を保持したまま Infisical に格納し、`infisical run` で
  子プロセスの環境変数として供給する。`terraform.tfvars` / `.env` はローカルでは使用しない。
- Kubernetes: Infisical Operator（`InfisicalSecretSync` 等）が Infisical から Secret を同期する
  一方向構成。SealedSecrets・SOPS/age・ArgoCD Vault Plugin は資産ごと除去済み。
- `terraform.tfvars` / `terraform.tfstate` は機微情報を含むためコミット対象外方針。

#### Infisical CLI の使い方（machine identity / 非対話）
- machine identity（universal-auth）でのログインは以下の手順で行う。値は `~/.config/infisical/universal-auth.env`
  の `INFISICAL_UNIVERSAL_AUTH_CLIENT_ID` / `INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET` を使う。
  ```bash
  set -a; source ~/.config/infisical/universal-auth.env; set +a
  INFTOK=$(infisical login --method=universal-auth \
    --client-id="$INFISICAL_UNIVERSAL_AUTH_CLIENT_ID" \
    --client-secret="$INFISICAL_UNIVERSAL_AUTH_CLIENT_SECRET" \
    --plain --silent)
  infisical run --token="$INFTOK" --projectId=<project-id> --env=prod -- <command>
  ```
- **`--token` と `--projectId` を必ず明示する**。省略すると `infisical secrets` / `infisical run` は
  ローカルにキャッシュされた対話ログインセッション（`~/.infisical/infisical-config.json` の
  `loggedInUserEmail`）を優先して参照してしまう。別アカウントでの対話ログイン履歴が残っていると、
  machine identity のトークンが正しくても `This project does not belong to your selected organization`
  という誤解を招くエラーになる（project ID・org ID 自体は正しいため、この現象が出たら真っ先にセッション
  キャッシュの混在を疑う）。
- シークレット値をターミナル出力・ログに晒さない。`infisical secrets`（テーブル表示）は使わず、
  `infisical run -- <command>` で子プロセスの環境変数として渡すか、単一値のみが必要な場合は
  `infisical secrets get <name> --plain` を使う。

### Code Quality
- pre-commit + gitleaks（`--redact`, `.gitleaks.toml`）で秘密情報の混入を検知
- ansible-lint を playbook 適用前に実行

### Testing
- Terraform: `terraform validate`
- Ansible: `ansible-lint playbooks/site.yml`

## Development Environment

### Required Tools
- Terraform >= 1.5.0
- Ansible / ansible-lint（uv 経由、`.venv` 使用）
- Proxmox API トークン（`proxmox_api_token_id` / `proxmox_api_token_secret`）

### Common Commands
```bash
# Terraform 検証（Infisical 経由でシークレットを供給）
cd terraform
infisical run --token="$INFTOK" --projectId=<project-id> --env=prod -- terraform init
infisical run --token="$INFTOK" --projectId=<project-id> --env=prod -- terraform validate

# Ansible 依存導入 + Lint
cd ansible
ansible-galaxy collection install -r collections/requirements.yml
ansible-lint playbooks/site.yml

# Playbook 適用（例: 単一コンポーネント。シークレット変数を解決するため Infisical 経由が必須）
infisical run --token="$INFTOK" --projectId=<project-id> --env=prod -- \
  ansible-playbook playbooks/nas.yml
```
`$INFTOK` の取得手順は本ファイルの「Infisical CLI の使い方」を参照。

## Key Technical Decisions

- Terraform と Ansible の責務を厳密分離（リソース作成 vs 構成適用）し、変更の影響範囲を限定
- VM/LXC 定義は `for_each` + `locals` でホスト差分をデータ化し、モジュール本体は共通化
- ネットワーク層を Public/Edge/DMZ/LAN/Console に分離し、境界ごとにアクセス制御を設計

---
_Document standards and patterns, not every dependency_
