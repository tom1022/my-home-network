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
- **ただし現状、Ansible の playbook は一切実行できない。** 追跡対象からは外れているものの、
  暗号化された `vault.yml` が作業ツリーに 5 つ残っている（`group_vars/all/`,
  `host_vars/{gitea,k3s-server,pbs,vps}/`）。`ansible.cfg` に `vault_password_file` の指定が
  無いため、**インベントリのパース時点で全 play が失敗する**。
  ```
  $ ansible-inventory --list
  ERROR! Attempting to decrypt but no vault secrets found
  ```
  `ansible-lint` を含め、インベントリを読む操作はすべてこの影響を受ける。
- Terraform: 変数名を変えず `TF_VAR_` 接頭辞を保持したまま Infisical に格納し、`infisical run` で
  子プロセスの環境変数として供給する。`terraform.tfvars` / `.env` はローカルでは使用しない。
- Kubernetes: Infisical Operator（`InfisicalStaticSecret`）が Infisical から Secret を同期する
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

# Ansible Lint
# 注: `ansible/collections/requirements.yml` は存在しない。コレクションの依存定義は
# リポジトリ内に無く、実行環境に導入済みのものに暗黙依存している。
cd ansible
ansible-lint playbooks/site.yml

# Playbook 適用（例: 単一コンポーネント。シークレット変数を解決するため Infisical 経由が必須）
infisical run --token="$INFTOK" --projectId=<project-id> --env=prod -- \
  ansible-playbook playbooks/nas.yml
```
`$INFTOK` の取得手順は本ファイルの「Infisical CLI の使い方」を参照。

## Edge / Public Routing

- Terraform の state は HCP Terraform に移行済み。
- `cloudflare_dns.tf` の `proxied` は `root` / `www` / `console` / `crafty` / `idp` が `true`、
  `mc` / `mail` / `appflowy` が `false`（grey-cloud）。Cloudflare Origin CA を使えるのは
  proxied 側のみで、grey-cloud のホスト名には適用できない。
- 証明書は `fickledev.com` + `*.fickledev.com` のワイルドカード 1 枚を VPS 上の全 vhost が共有する。
  そのため **1 枚の更新失敗が複数のホスト名を同時に落とす**。
- `fickledev.com.conf.j2` の `location /blog/` が向く上流 `192.168.1.101` は**実在しない**。

## Host Access

接続は作業環境の ED25519 鍵で行う。接続ユーザーはホストの種別で分かれる。

| ホスト | IP | 接続ユーザー | 到達性 |
|---|---|---|---|
| n100 / hp-z440（Proxmox ノード） | 192.168.1.10 / 192.168.1.2 | `root` | 可 |
| nas / k3s-server / k3s-agent-minipc / k3s-agent-z440 | 192.168.1.201 / .150 / .151 / .152 | `tochi` | 可 |
| vps | 100.109.6.7（tailnet） | `trvlr` | 可 |
| **gitea（LXC 200）/ pbs（LXC 202）** | 192.168.1.200 / .202 | `root` | **不可** |

- **gitea と pbs は認可済み公開鍵が手元の鍵と一致しない。** どちらも `root` のみが存在し、一般
  ユーザーは存在しない。収容元の Proxmox ノードから `pct exec 200 --` / `pct exec 202 --` で
  到達できる（gitea は n100 上、pbs は hp-z440 上）。
- **`inventory.yml` の `ansible_ssh_private_key_file` はパスを固定しているだけで、鍵の同一性を
  固定していない。** 同じパスが実行環境ごとに異なる鍵へ解決されうるため、到達性が実行環境に依存する。
- `known_hosts` が nas / k3s-server / k3s-agent-minipc / k3s-agent-z440 の 4 ホストでずれており、
  `REMOTE HOST IDENTIFICATION HAS CHANGED!` が出る。`ansible.cfg` の `host_key_checking = False` と
  全 playbook 冒頭の `refresh_known_hosts.yml` が互いを無意味にしている。

## Backup

**現時点でバックアップは 1 件も存在しない。「バックアップがあるから復元できる」という前提を置かない。**

- `/etc/pve/storage.cfg` の `pbs: pbs-zfs-pool` に `disable` が設定されている。
- 毎日 04:30 の vzdump ジョブは両ノードで
  `could not activate storage 'pbs-zfs-pool': storage 'pbs-zfs-pool' is disabled`
  を吐いて失敗し続けており、**成功実績が無い**。PBS データストアにスナップショットは 1 本も無い。
- vzdump ジョブの対象は 3 件、`host_vars/pbs/main.yml` の `pbs_backup_targets` は 7 件で一致しない。
- **バックアップ先が保護対象と同じ物理ディスク上にある。** 有効化してもディスク障害時には
  対象とバックアップが同時に失われる。

## Storage

- 物理ディスクは n100 に SSD 1 本、hp-z440 に SSD 1 本 + HDD 2 本。**冗長性は無い**
  （mirror / raidz / mdadm のいずれも無い）。`zfs-pool` も単一 vdev。
- SMART は全台 PASSED、代替・保留セクタとも 0。ZFS の scrub は直近でエラー 0。
- LVM-thin プールは overcommit していない（割当率は両ノードとも 65〜70%、metadata は 1.5% 前後）。
- スナップショットは全ノード・全ゲストで 0 件。参照されていない孤児ボリュームも無い。
- `zfs-pool` は `refreservation` の合計が実データを大きく上回る。内訳は MinIO の残骸（実質空）、
  Nextcloud を k3s へ移行するための**確保済みの移行先**（現在は空）、nas 用、PBS データストア。
- **全 VM の disk が `discard=ignore`。** ゲスト内で解放した領域が thin プールへ返らず、
  約 180G が滞留している。`terraform/modules/vm/main.tf` の disk ブロックに `discard` の指定が
  無く、かつ `lifecycle.ignore_changes` に `disk` が含まれるため、定義側からは矯正できない。
- `local-lvm:vm-107-disk-1` は VM 110 の起動ディスクとして**稼働中**。存在しない VM 107 由来の
  名前が残っているだけで孤児ではない。

## Proxmox Guests

`terraform/locals.tf` に定義があるのは k3s 3 台（150/151/152）、nas（201）、gitea（200）、
pbs（202）のみ。**以下は実機に存在するが Terraform 管理外**で、実機と定義の対応が付いていない。

| ノード | 種別 | ID | 名前 |
|---|---|---|---|
| n100 | LXC | 113 | MariaDB |
| n100 | VM | 9000 | debian-12-template（停止） |
| hp-z440 | LXC | 100 | ollama |
| hp-z440 | LXC | 115 | portfolio |
| hp-z440 | VM | 105 | nextcloud（`/dev/sdb` を raw passthrough） |
| hp-z440 | VM | 108 | windows（停止、OS ディスクの定義が無い） |
| hp-z440 | VM | 110 | tv |
| hp-z440 | VM | 9001 | debian-12-template（停止） |

## Key Technical Decisions

- Terraform と Ansible の責務を厳密分離（リソース作成 vs 構成適用）し、変更の影響範囲を限定
- VM/LXC 定義は `for_each` + `locals` でホスト差分をデータ化し、モジュール本体は共通化
- ネットワーク層を Public/Edge/DMZ/LAN/Console に分離し、境界ごとにアクセス制御を設計

---
_Document standards and patterns, not every dependency_
