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
`tasks/` 配下をサブファイル分割（例: `nas/tasks/{prerequisites,storage,gitea_share}.yml`）する。
`defaults/`, `handlers/`, `templates/`, `meta/`, `vars/` は必要な role のみ持つ。
**Example**: `ansible/roles/vps_proxy/` は `templates/` に Nginx/HAProxy 設定テンプレートを持つ。

### Ansible Playbooks
**Location**: `ansible/playbooks/`
**Purpose**: コンポーネント単位のエントリポイント（`<role>.yml`）と、それらをまとめる
`site.yml`。新規コンポーネント追加時は `site.yml` に `import_playbook` を追記する。
**Example**: `nas.yml`, `pbs.yml`, `vps.yml` はそれぞれ対応 role を実行する薄いラッパー。

### Inventory
**Location**: `ansible/inventory/`
**Purpose**: `inventory.yml` にホスト/グループ定義、`group_vars/<group>/`・`host_vars/<host>/` に
変数を分離。秘匿値は同階層の `vault.yml`（Vault 暗号化）+ `vault.yml.example`（構造のみ）で管理。
**Example**: `host_vars/vps/vault.yml` と `host_vars/vps/vault.yml.example` が対になる。

### GitOps Bootstrap
**Location**: `gitops/apps/`
**Purpose**: ArgoCD ApplicationSet の初期投入定義のみ（`gitops-apps-set.yaml`）。実際のアプリ
マニフェストは別リポジトリ `gitops-apps`（Gitea: `giteaadmin/gitops-apps.git`, ローカルでは
`../gitops-apps`）の `apps/*` を ApplicationSet が監視・同期する。本リポジトリはこの別repoの
内容を管理しない。

## Naming Conventions

- **Ansible Role/Playbook**: snake_case（例: `vps_proxy`, `proxmox_backup`）
- **Terraform Resource/Variable**: snake_case
- **Inventory Host**: kebab-case（例: `k3s-agent-minipc`）
- **Vault ファイル**: `vault.yml`（実体, 暗号化）+ `vault.yml.example`（サンプル, 平文プレースホルダ）

## Code Organization Principles

- Terraform: リソース定義はモジュール化し、環境固有値は `locals.tf` / `*.tfvars` に隔離。
- Ansible: 1 role = 1 コンポーネントの原則。role 内が肥大化したら `tasks/` をサブファイル分割。
- 適用順序への依存がある構成（証明書配布 → cert-manager 等）は `site.yml` の import 順で表現する。
- 新しいホスト/VM を追加する場合、Terraform 側（`locals`）と Ansible 側（`inventory.yml`）の両方を
  更新する必要がある。

---
_Document patterns, not file trees. New files following patterns shouldn't require updates_
