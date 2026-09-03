# Product Overview

自宅環境のプロビジョニングと構成管理をコード化した Infrastructure as Code (IaC) リポジトリ。
Proxmox VE 上のリソース作成を Terraform、各ホストの構成適用を Ansible で分離管理する。

## Core Capabilities

- Terraform による Proxmox VM / LXC のプロビジョニング（モジュール化・環境差分は変数で吸収）
- Ansible Role ベースの構成管理（Gitea, NAS, PBS, VPS Reverse Proxy, k3s 連携など）
- Infisical によるシークレット集約（平文コミット禁止）
- ArgoCD (GitOps) による k3s クラスタへのマニフェスト適用
- ネットワーク境界（Public / Edge / DMZ / LAN / Console）を意識したセキュリティ設計

## Target Use Cases

- 自宅サーバー（N100 MiniPC, HP Z440）上の VM/LXC 作成〜構成適用の再現可能な自動化
- VPS（Conoha）を経由した Web サービスの Cloudflare + Tailscale 越しの公開
- k3s 上のワークロード（Home Assistant, Garage, Minecraft, PostgreSQL/CNPG, cert-manager,
  cluster-issuer, cloudflared, Infisical Operator, reflector, reloader 等）の GitOps 管理。
  xrayvpn はマニフェストを保持したままレプリカ数 0 で停止している。実体は別リポジトリ
  `gitops-apps` にある

## Value Proposition

- リソース作成（Terraform）と構成適用（Ansible）の責務分離により変更影響を局所化
- 変数駆動設計でノード・VMID・ストレージ差分を吸収し、再利用性を確保
- gitleaks (pre-commit) + Infisical によりセキュリティを運用ではなく設計に組み込み

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

- `iac-hygiene-remediation` — 3 リポジトリ横断の是正
- `mail-platform` — メール基盤の構築
- `autonomous-parallel-dev-platform`（`gitops-apps` 側）— 自律開発環境

## Current State

以下は現在の実態であり、**知らずに前提を置くと判断を誤る**。

- **`fickledev.com` / `www.fickledev.com` は稼働中（HTTP 200）。** 証明書供給は VPS 上の certbot
  + `certbot-dns-cloudflare`（ACME DNS-01）の単一機構であり、`systemd` タイマーで自動更新される。
  Cloudflare Origin CA 機構は利用者が存在しないため撤去済み。詳細は `tech.md` の Edge / Public
  Routing 節。
- **バックアップは PBS（Proxmox Backup Server）で稼働している。** 対象 7 件（vmid 150/151/152/
  201/202/113/110）のうち 6 件（110 を除く）で検証済みの復元可能なバックアップを保持し、保持世代は
  `keep-last=2`。110（録画データ用 VM）はディスク単位の除外実装が未了のため対象外。詳細は
  `tech.md` の Backup 節。
- **ストレージに冗長性が無い。** 全ディスクが単発構成で、mirror / raidz / mdadm のいずれも無い。
- **単一の認証基盤 (IdP) は存在しない。** 認証は各サービスのローカルアカウント、ServiceAccount
  トークン、IP ホワイトリスト、Cloudflare Access（GitHub IdP）に分散している。OIDC / SAML /
  forward auth で連携しているサービスは無い。`my-home-network` 側に LDAP クライアントのロールは
  存在しない。
- **mailu と Kubernetes Dashboard は撤去済み。** xrayvpn はレプリカ数 0 で停止しており、マニフェ
  ストは復帰可能な形で保持している。クラスタの管理操作は kubeconfig と端末クライアントに一本化
  されている。

---
_Focus on patterns and purpose, not exhaustive feature lists_
