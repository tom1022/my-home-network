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
  （Ansible Vault 暗号化ファイル）は追跡対象・作業ツリーの双方から存在せず、供給経路として使わない。
  `vault.yml.example` は移行前の変数名一覧としてのみ残置している（ファイル自体のヘッダーコメントは
  Ansible Vault への複製・暗号化手順を示しており実態と食い違っている。是正は未了）。
  `ansible-inventory --list` はインベントリのパースに成功する。
- Terraform: 変数名を変えず `TF_VAR_` 接頭辞を保持したまま Infisical に格納し、`infisical run` で
  子プロセスの環境変数として供給する。`terraform.tfvars` / `.env` はシークレットの供給経路として
  使わない。`terraform/terraform.tfvars` 自体は非機微な既定値（`gateway`, `nameservers`, `ci_user`,
  `vm_template_ids`, `insecure`, `container_bind_mounts`）のみを保持するファイルとして追跡対象に
  含めている。HCP Terraform への認証は `TF_TOKEN_app_terraform_io`（`TF_VAR_` 接頭辞を持たない
  Terraform CLI 標準の環境変数）を同様に Infisical から `infisical run` 経由で供給する。
- Kubernetes: Infisical Operator（`InfisicalStaticSecret`）が Infisical から Secret を同期する
  一方向構成。SealedSecrets・SOPS/age・ArgoCD Vault Plugin は両リポジトリのコード資産としては
  除去済みだが、**クラスタ上には残骸が現存する**（`argocd` namespace の ConfigMap
  `argocd-avp-plugin-config` と Secret `argocd-sops-age`）。参照元のマニフェストが存在しない孤児
  リソースであり、消費者はいない。除去は未実施（クラスタ孤児の除去作業の対象）。
- `terraform.tfstate` はローカルに存在せず HCP Terraform（organization `fickledev`, workspace
  `my-home-network`）が保持する。機微情報を含み得るためローカルへの生成物（`.terraform/` 含む）は
  コミット対象外方針を維持する。

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

# Ansible Lint（コレクションの依存は ansible/collections/requirements.yml がバージョン範囲で宣言する）
cd ansible
ansible-galaxy collection install -r collections/requirements.yml
ansible-lint playbooks/site.yml

# Playbook 適用（例: 単一コンポーネント。シークレット変数を解決するため Infisical 経由が必須）
# 接続鍵はインベントリのパス指定ではなく Infisical のキー ANSIBLE_SSH_PRIVATE_KEY から供給する。
# ssh-add は infisical run の子プロセス内で実行し、環境変数 ANSIBLE_SSH_PRIVATE_KEY を渡す。
infisical run --token="$INFTOK" --projectId=<project-id> --env=prod -- \
  bash -c 'ssh-add - <<< "$ANSIBLE_SSH_PRIVATE_KEY" && ansible-playbook playbooks/nas.yml'
```
`$INFTOK` の取得手順は本ファイルの「Infisical CLI の使い方」を参照。

## Edge / Public Routing

- Terraform の state は HCP Terraform に移行済み。
- `cloudflare_dns.tf` の `proxied` は `root` / `www` / `console` / `crafty` / `idp` が `true`、
  `mc` / `mail` / `appflowy` が `false`（grey-cloud）。
- 証明書供給は VPS 上の certbot + `certbot-dns-cloudflare`（ACME DNS-01）の単一機構として
  `vps_proxy` role が管理する。`fickledev.com` + `*.fickledev.com` のワイルドカード証明書
  1 枚を VPS 上の全 vhost が共有し、`systemd` の `certbot-renew.timer`（日次）で自動更新する。
  そのため **1 枚の更新失敗が複数のホスト名を同時に落とす**。Cloudflare Origin CA 機構
  (`vps_proxy_origin_ca_*`) は proxied ホスト名の移設 (Workers 化) により利用者を失い撤去済み。
- `fickledev.com` / `www.fickledev.com` の配信は Cloudflare Workers (`fickledev-portfolio`) へ移設済み。
  `vps_proxy` role はこの 2 ホスト名向けの vhost を持たず、`fickledev.com.conf.j2` は
  `*.fickledev.com` の SNI 不一致キャッチオール (403 応答) のみを持つ。

## Tailscale

OPNSense が subnet router として `192.168.1.0/24`（DMZ）を advertise する。`192.168.99.0/24`（LAN）は
advertise 対象外。tailnet 経由の疎通は **2 つの設定の両方**が揃って初めて双方向に成立する。片方だけでは
方向によって通らない。

**1. netstack の無効化（`/etc/rc.conf.local`）**

FreeBSD 版 `tailscaled` は既定で advertised subnet 宛のトラフィックを userspace netstack（gVisor）で
処理する。この経路は「LAN 内ホストが自発的に外部 tailnode へ接続し、その応答が LAN 側へ戻る」方向を
処理できず、応答パケットが消失する。`tailscaled` 起動時に
`Warning: Subnet routing and exit nodes only work with additional manual configuration on freebsd,
and is not currently officially supported.` と表示される通り、FreeBSD 上の subnet routing は公式非サポート。

`/etc/rc.conf.local` に `export TS_DEBUG_NETSTACK_SUBNETS=0` を置いてカーネル TUN forwarding へ
切り替えている。このファイルは OPNSense の Tailscale GUI 設定から自動生成される
`/etc/rc.conf.d/tailscaled`（ヘッダーに `DO NOT EDIT` とあり GUI 保存のたびに上書きされる）とは
独立しており、GUI 側の設定変更では消えない。rc.subr が `load_rc_config` の過程で source するため、
`daemon(8)` 経由で起動される `tailscaled` の実プロセス環境まで継承される（`procstat -e <pid>` で確認可能）。

**2. pf の pass ルール（Firewall > Rules > Tailscale）**

netstack を無効化するとカーネル forwarding になり、tailnet 側から入るパケットの送信元は相手ノードの
Tailscale IP（例 `100.109.6.7`）のまま転送される。OPNSense が自動生成する既存ルールは送信元が
`(tailscale0:network)` になっているが、**`tailscale0` の IPv4 は `/32` のため、これは OPNSense 自身の
`100.93.205.102` 1 エントリしか展開しない**（`pfctl -sr -vv` の `(tailscale0:network:1)` の `:1` が
展開数）。他ノード発のパケットは pass にも block にもマッチせず、デフォルト deny で破棄される。

そのため tailnet の CGNAT レンジを送信元に明示した pass ルールを別途置いている。

```
pass in quick on tailscale0 inet from 100.64.0.0/10 to 192.168.1.0/24 flags S/SA keep state
```

- 送信元は **`100.64.0.0/10`**（tailnet CGNAT 全域）。GUI の "Tailscale net" を選ぶと
  `(tailscale0:network)` になり上記の罠を踏む。`/16` では他ノードのアドレスを取りこぼす。
- `block drop in quick on tailscale0 ... to (self)` より**上**に配置する。宛先 `192.168.1.0/24` は
  OPNSense 自身の LAN GW `192.168.1.1` を含むため、この順序で self 宛も許可される。
- Protocol は `any`。表示上の `flags S/SA` は TCP にのみ適用される条件で、`proto` を明示していない
  ルールでは非 TCP パケットに対してスキップされるため、ICMP も通る。

## Host Access

接続は作業環境の ED25519 鍵で行う。接続ユーザーはホストの種別で分かれる。

| ホスト | IP | 接続ユーザー | 到達性 |
|---|---|---|---|
| n100 / hp-z440（Proxmox ノード） | 192.168.1.10 / 192.168.1.2 | `root` | 可 |
| nas / k3s-server / k3s-agent-minipc / k3s-agent-z440 | 192.168.1.201 / .150 / .151 / .152 | `tochi` | 可 |
| vps | 100.109.6.7（tailnet） | `trvlr` | 可 |
| gitea（LXC 200）/ pbs（LXC 202） | 192.168.1.200 / .202 | `root` | 可 |

- 接続鍵はファイルパスで指定しない。`inventory.yml` の `target_hosts.vars` に鍵ファイルの参照は
  無く、`ANSIBLE_SSH_PRIVATE_KEY`（Infisical）を `infisical run` の子プロセス内で ssh-agent へ
  登録して使う（詳細は README の再現性確認コマンドを参照）。認可済み公開鍵の宣言的な配布は
  `ansible/roles/ssh_authorized_keys` が担い、`target_hosts` の全 9 ホスト（gitea / pbs を含む）に
  対して単一の管理対象エントリを追加する。gitea / pbs の PVE 管理ブロック（Proxmox クラスタ管理用
  RSA 鍵）はこの role の管理対象から意図して除外している。
- `ansible.cfg` の `host_key_checking` は `True`。`ansible/playbooks/refresh_known_hosts.yml` が
  ローカルの `known_hosts` を実機の鍵で更新する専用機構として存在し、`ssh_authorized_keys.yml`
  の先頭で import される（`site.yml` は `ping` の直後にこれを import する）。`known_hosts` が
  古い実行環境では、対象 playbook の実行前に `ansible-playbook playbooks/refresh_known_hosts.yml`
  を単独実行する必要がある。

## Backup

PBS（Proxmox Backup Server、LXC 202）が両 Proxmox ノードからのバックアップ先として稼働している。

- データストアは `zfs-pool`（`/mnt/zfs-pool-0`）、PVE 側ストレージ名は `pbs-zfs-pool`。
  保存先の物理ディスクは保護対象のディスクと分離されている。
- vzdump ジョブは毎日 04:30 (cron) のスケジュールで定義され、対象は `host_vars/pbs/main.yml` の
  `pbs_backup_targets`（7 件: vmid 150/151/152/201/202/113/110）と実行基盤側（`/etc/pve/jobs.cfg`）
  で一致している。保持世代は `keep-last=2`。
- 7 件中 6 件（113/150/151/152/201/202）は復元可能なバックアップを保持し、
  `proxmox-backup-manager verify` によるデータ整合性検証も確認済み。**110（録画データ用 VM）は
  ディスク単位の除外実装が未了のため、初回バックアップを意図的に見送っている**（対象に含めると
  録画データ全体〔thin 実使用約 124G〕が毎回バックアップされ、除外意図に反するため）。
- 対象外（明示的除外）: 200（gitea）。GitHub へのオフサイトミラーで代替する方針。

## Storage

- 物理ディスクは n100 に SSD 1 本、hp-z440 に SSD 1 本 + HDD 2 本。**冗長性は無い**
  （mirror / raidz / mdadm のいずれも無い）。`zfs-pool` も単一 vdev。
- SMART は全台 PASSED、代替・保留セクタとも 0。ZFS の scrub は直近でエラー 0。
- LVM-thin プールは overcommit していない（割当率は両ノードとも 65〜70%、metadata は 1.5% 前後）。
- スナップショットは全ノード・全ゲストで 0 件。参照されていない孤児ボリュームも無い。
- `zfs-pool` は単一 vdev（HDD `sdc`、ST4000VN006、3.62T）。実データは約 35G、物理空きは約 3.59T。
  `refreservation` の合計が実データを大きく上回る。内訳は Nextcloud を k3s へ移行するための
  **確保済みの移行先**（`vm-152-disk-1`、1000G、現在は空）、nas 用（`vm-201-disk-0`、1000G）、
  PBS データストア（`subvol-202-disk-0`）。
- hp-z440 の `sda`（SSD、931.5G）は `local-lvm` のみに使う。thin プール `data` の使用率は
  約 41% で、SSD 上に新規 thin LV を切る余地がある。
- hp-z440 の `sdb`（HDD、1.8T、ext4、`PARTLABEL=Nextcloud`）は Proxmox のストレージとして
  未登録かつ未マウント。VM 105 へのパススルーの有無は未確認。
- n100 は SSD 単体構成。HDD も ZFS プールも無い。
- 全 VM の disk は `discard=on`。ゲスト内で解放した領域は thin プールへ返る。
- `local-lvm:vm-107-disk-1` は VM 110 の起動ディスクとして**稼働中**。存在しない VM 107 由来の
  名前が残っているだけで孤児ではない。
- Garage の実体は k3s ノードの起動用ディスク上にあり、CNPG の継続的な退避先でもある。
  索引と実体の分離、および起動用ディスクからの分離が未了。

### 記憶装置の役割別の使い分け

置き場所はアプリケーション単位ではなく**役割単位**で決める。

| 役割 | 置き場所 | 理由 |
| --- | --- | --- |
| 索引・メタデータ・データベース | SSD | 不規則な小さい読み書きが主で、遅延が体感に直結する |
| 添付・画像・バックアップ・メールボックスの実体 | HDD | 逐次的な書き込みが主で、遅延の影響を受けない |

書き込み量の多い保存先を SSD に置かない。摩耗するのは SSD であり、HDD に書き込み回数の
上限は無い。バックアップやオブジェクト記憶のような書き込み主体の負荷は HDD に置く。

索引と実体を分離できる実装は分離する。Garage は `metadata_dir` と `data_dir`、Dovecot は
索引の格納先を、それぞれ別のパスに指定できる。

継続的な退避の保存先を、退避が守ろうとしている対象と同一の記憶装置に置かない。

## Proxmox Guests

`terraform/locals.tf` に定義があるのは k3s 3 台（150/151/152）、nas（201）、gitea（200）、
pbs（202）、mariadb-legacy（113）。**以下は実機に存在するが Terraform 管理外**で、実機と定義の対応が付いていない。

| ノード | 種別 | ID | 名前 |
|---|---|---|---|
| n100 | LXC | 113 | MariaDB |
| n100 | VM | 9000 | debian-12-template（停止） |
| hp-z440 | VM | 105 | nextcloud（`/dev/sdb` を raw passthrough） |
| hp-z440 | VM | 108 | windows（停止、OS ディスクの定義が無い） |
| hp-z440 | VM | 110 | tv |
| hp-z440 | VM | 9001 | debian-12-template（停止） |

## Cluster Management

クラスタの管理操作（デプロイ状態の確認、手動介入）は kubeconfig と端末クライアント（`kubectl` 等）に
一本化している。ブラウザ経由の管理 UI は存在しない。kubeconfig は `~/.kube/config`（コンテキスト
`default`）。

```bash
kubectl get nodes
kubectl get applications -n argocd
```

この一本化の対象は**クラスタの管理操作の手段そのもの**であり、**ブラウザから提供される開発
ワークスペース**（クラウド IDE・ブラウザ内ターミナル等）を対象に含めない。そのようなワークスペース
上で kubeconfig と端末クライアントを使って操作すること自体は、この規約の対象外であり禁止しない。
両者を区別しないまま読むと、ブラウザのみで統合開発環境と端末を提供する構成が規約違反として
誤読されうる。

## Key Technical Decisions

- Terraform と Ansible の責務を厳密分離（リソース作成 vs 構成適用）し、変更の影響範囲を限定
- VM/LXC 定義は `for_each` + `locals` でホスト差分をデータ化し、モジュール本体は共通化
- ネットワーク層を Public/Edge/DMZ/LAN/Console に分離し、境界ごとにアクセス制御を設計

---
_Document standards and patterns, not every dependency_
