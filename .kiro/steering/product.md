# Product Overview

自宅環境のプロビジョニングと構成管理をコード化した Infrastructure as Code (IaC) リポジトリ。
Proxmox VE 上のリソース作成を Terraform、各ホストの構成適用を Ansible で分離管理する。

## Core Capabilities

- Terraform による Proxmox VM / LXC のプロビジョニング（モジュール化・環境差分は変数で吸収）
- Ansible Role ベースの構成管理（Gitea, NAS, PBS, VPS Reverse Proxy, k3s 連携など）
- Terraform（`terraform-kanidm/`）による Kanidm のグループ・OAuth2 クライアント・アカウント
  ポリシーの宣言的管理
- Infisical によるシークレット集約（平文コミット禁止）
- ArgoCD (GitOps) による k3s クラスタへのマニフェスト適用
- ネットワーク境界（Public / Edge / DMZ / LAN / Console）を意識したセキュリティ設計

## Target Use Cases

- 自宅サーバー（N100 MiniPC, HP Z440）上の VM/LXC 作成〜構成適用の再現可能な自動化
- VPS（Conoha）を経由した Web サービスの Cloudflare + Tailscale 越しの公開
- k3s 上のワークロード（Kanidm, oauth2-proxy, Home Assistant, Garage, Minecraft,
  Dovecot + ClamAV（`mailbox`）, PostgreSQL/CNPG, cert-manager, cluster-issuer, cloudflared,
  CoreDNS カスタム設定, Infisical Operator, reflector, reloader 等）の GitOps 管理。
  xrayvpn はマニフェストを保持したままレプリカ数 0 で停止している。実体は別リポジトリ
  `gitops-apps` にある

## Value Proposition

- リソース作成（Terraform）と構成適用（Ansible）の責務分離により変更影響を局所化
- 変数駆動設計でノード・VMID・ストレージ差分を吸収し、再利用性を確保
- gitleaks（`.github/workflows/secret-scan.yml` の CI ジョブで強制。`.pre-commit-config.yaml`
  による同一フックのローカル実行は任意）+ Infisical によりセキュリティを運用ではなく設計に組み込み

## Related Repositories

本ホームラボは 3 リポジトリで構成される。

| リポジトリ | 内容 | 公開範囲 |
|---|---|---|
| `my-home-network`（本リポジトリ） | Ansible / Terraform / scripts | **GitHub public** |
| `gitops-apps` | ArgoCD 管理の k8s マニフェスト | 自ホスト Gitea（非公開） |
| `portfolio` | `fickledev.com` を配信する Next.js サイト + Cloudflare Worker | **GitHub public** |

`my-home-network` と `portfolio` は GitHub public のため、追跡対象に書く内容は公開される前提で判断する。
`gitops-apps` は自ホスト Gitea のみでホストされ外部に公開されていない。

## Active Specifications

- `admin-plane-rebuild` — 管理面の再構成（要件定義フェーズ）
- `backup-durability-and-alerting` — バックアップの堅牢化と検知（要件定義フェーズ）
- `autonomous-parallel-dev-platform`（`gitops-apps` 側）— 自律開発環境（要件定義フェーズ）

## Current State

以下は現在の実態であり、**知らずに前提を置くと判断を誤る**。

- **`fickledev.com` / `www.fickledev.com` の配信元は Cloudflare Workers（`fickledev-portfolio`）。**
  VPS 上の certbot + `certbot-dns-cloudflare`（ACME DNS-01）は撤去せず残しており、`*.fickledev.com`
  の SNI 不一致キャッチオール vhost と、メール基盤（docker-mailserver が `/etc/letsencrypt` を
  読む）への証明書供給を担う。Cloudflare Origin CA 機構は利用者が存在しないため撤去済み。詳細は
  `tech.md` の Edge / Public Routing 節。
- **バックアップは PBS（Proxmox Backup Server）で稼働している。** 対象の正は
  `ansible/inventory/host_vars/pbs/main.yml` の `pbs_backup_targets`、明示的な除外の正は同ファイルの
  `pbs_backup_excluded_targets`（件数をここに写さない）。除外理由は gitea が GitHub へのオフサイト
  ミラーで代替するため、mirakurun-epgstation が録画データと OS で単一ディスクを共有し録画データ
  だけを外せないため。保持世代は同ファイルの `pbs_backup_keep_last`。詳細は `tech.md` の Backup 節。
- **ストレージに冗長性が無い。** 全ディスクが単発構成で、mirror / raidz / mdadm のいずれも無い。
- **単一の認証基盤 (IdP) は Kanidm。** k3s 上の `kanidm` が唯一の IdP で、グループ・OAuth2
  クライアント・アカウントポリシー・LDAP アプリケーションの宣言は `terraform-kanidm/` が持つ
  （state は HCP Terraform の別ワークスペース `kanidm-identity`）。人間の利用者
  （`kanidm_person`）とその所属は意図して宣言せず、Kanidm サーバ側の実体を Terraform の管理対象に
  しない境界を敷いている。サービスアカウントの所属だけは例外で、`terraform-kanidm/mail.tf` が
  `idm_mail_servers` への所属を宣言する。連携経路は 4 系統。
  - **OIDC 直結**: ArgoCD（`argocd-cm` の `oidc.config`、Dex は使わない）、Gitea（OAuth2 認証
    ソース）、Cloudflare Access（Kanidm を OIDC IdP として登録。適用先は Guacamole）
  - **forward auth**: Traefik の `forward-auth-chain` middleware（接続元制限 → ヘッダ除去 →
    oauth2-proxy への forwardAuth）経由。適用先は Home Assistant と Garage
  - **LDAPS**: メール基盤の Postfix（VPS の docker-mailserver）と Dovecot（k3s の `mailbox`）が
    `ldaps.kanidm.fickledev.com:3636` にバインドする
  - **UNIX 統合**: NAS が `ansible/roles/kanidm_unixd`（kanidm-unixd + PAM/NSS）で Kanidm の
    アカウントによる SSH ログインを受ける
- **mailu と Kubernetes Dashboard は撤去済み。** xrayvpn はレプリカ数 0 で停止しており、マニフェ
  ストは復帰可能な形で保持している。クラスタ全体に対する無制限の管理操作は kubeconfig と端末
  クライアントに限る。ブラウザから届く管理 UI は ArgoCD の Web UI だけで、これは GitOps の同期
  状態に範囲が限られる。詳細は `tech.md` の Cluster Management 節。

---
_Focus on patterns and purpose, not exhaustive feature lists_
