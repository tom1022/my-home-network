# Project Structure

## Organization Philosophy

レイヤー分離型。トップレベルでツール（`terraform/` / `ansible/` / `gitops/`）ごとにディレクトリを分け、
各ツール内はさらに責務単位（module / role / playbook）で分割する。

## Directory Patterns

### Terraform Modules
**Location**: `terraform/modules/{container,vm}/`
**Purpose**: Proxmox リソース種別ごとの再利用可能モジュール。`main.tf` はルートの `for_each` から
呼ばれ、ホスト固有値は `locals.tf` / `variables.tf` で注入する。
**Example**: 新しい VM を追加する場合、モジュールを増やすのではなく `terraform/main.tf` の
`local.vms` にエントリを追加する。

### Ansible Roles
**Location**: `ansible/roles/<role_name>/`
**Purpose**: コンポーネント単位の構成管理。`tasks/main.yml` をエントリポイントとし、大きい役割は
`tasks/` 配下をサブファイル分割（例: `nas/tasks/{main,gitea_share}.yml`）する。ディスク
プロビジョニングは role 横断で `storage_disk` role に集約されている。
`defaults/`, `handlers/`, `templates/`, `meta/`, `vars/` は必要な role のみ持つ。
**Example**: `ansible/roles/vps_proxy/` は `templates/` に Nginx/HAProxy 設定テンプレートを持つ。

### Ansible Playbooks
**Location**: `ansible/playbooks/`
**Purpose**: コンポーネント単位のエントリポイント（`<role>.yml`）。`site.yml` はホスト構成の日常適用を
まとめるエントリポイントで、`ping`, `ssh_authorized_keys`, `nas`, `gitea`, `pbs`, `vps`,
`proxmox_backup`, `proxmox_unattended_upgrades` を import する。`k3s.yml`, `argocd.yml`,
`refresh_known_hosts.yml`, `setup_agent_storage.yml`, `fetch-kubeconfig.yml` は意図的に `site.yml` に
含めない独立したエントリポイント（クラスタ構築・診断・一度限りの操作など、日常適用のライフサイクルとは
異なるタイミングで実行するもの）。新規コンポーネントを日常適用の対象に含める場合のみ `site.yml` に
`import_playbook` を追記する。
**Example**: `nas.yml`, `pbs.yml`, `vps.yml` はそれぞれ対応 role を実行する薄いラッパー。

### Inventory
**Location**: `ansible/inventory/`
**Purpose**: `inventory.yml` にホスト/グループ定義、`group_vars/<group>/`・`host_vars/<host>/` に
変数を分離。秘匿値は一般名の変数から `lookup('env', 'VAR_NAME')` で参照し、Infisical が
`infisical run` 経由で供給する環境変数を解決先とする。同階層の `vault.yml.example` は移行前の
変数名一覧として残置しているのみで、供給経路としては使わない（ファイル自体のヘッダーコメントは
Ansible Vault への複製・暗号化手順を示しており、実態と食い違っている。運用者判断が必要な残課題）。
作業ツリーに暗号化済み `vault.yml` は存在しない。
**Example**: `group_vars/all/main.yml` の `proxmox_api_token_secret: "{{ lookup('env', 'PROXMOX_API_TOKEN_SECRET') }}"`。

### GitOps Bootstrap
**Location**: `gitops/apps/`
**Purpose**: ArgoCD ApplicationSet の初期投入定義のみ（`gitops-apps-set.yaml`）。実際のアプリ
マニフェストは別リポジトリ `gitops-apps`（Gitea: `giteaadmin/gitops-apps.git`, ローカルでは
`../gitops-apps`）の `apps/*` を ApplicationSet が監視・同期する。通常の運用では本リポジトリは
この別 repo の内容を管理しない。

ただし `.kiro/specs/` に置く仕様は例外で、`gitops-apps` および `portfolio` への変更を含めて
1 本の spec で横断管理することがある。各 spec の Boundary Commitments が対象範囲を定める。

## Naming Conventions

- **Ansible Role/Playbook**: snake_case（例: `vps_proxy`, `proxmox_backup`）
- **Terraform Resource/Variable**: snake_case
- **Inventory Host**: kebab-case（例: `k3s-agent-minipc`）
- **Infisical シークレットキー**: `vault_` 接頭辞を除去した大文字スネークケース（例: `vault_proxmox_api_token_secret` → `PROXMOX_API_TOKEN_SECRET`）。Terraform 用のみ `TF_VAR_` 接頭辞を保持する。

## Code Organization Principles

- Terraform: リソース定義はモジュール化し、環境固有値は `locals.tf` / `*.tfvars` に隔離。
- Ansible: 1 role = 1 コンポーネントの原則。role 内が肥大化したら `tasks/` をサブファイル分割。
- 適用順序への依存がある構成（`ssh_authorized_keys` → 各コンポーネント等）は `site.yml` の
  import 順で表現する。
- 新しいホスト/VM を追加する場合、Terraform 側（`locals`）と Ansible 側（`inventory.yml`）の両方を
  更新する必要がある。

---
_Document patterns, not file trees. New files following patterns shouldn't require updates_
