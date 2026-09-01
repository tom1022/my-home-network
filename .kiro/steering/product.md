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
  cloudflared, Infisical Operator 等）の GitOps 管理。実体は別リポジトリ `gitops-apps` にある

## Value Proposition

- リソース作成（Terraform）と構成適用（Ansible）の責務分離により変更影響を局所化
- 変数駆動設計でノード・VMID・ストレージ差分を吸収し、再利用性を確保
- gitleaks (pre-commit) + Infisical によりセキュリティを運用ではなく設計に組み込み

## Related Repositories

本ホームラボは 3 リポジトリで構成される。

| リポジトリ | 内容 | 公開範囲 |
|---|---|---|
| `my-home-network`（本リポジトリ） | Ansible / Terraform / scripts | **GitHub public** |
| `gitops-apps` | ArgoCD 管理の k8s マニフェスト | 自ホスト Gitea |
| `portfolio` | `fickledev.com` を配信する Next.js サイト | — |

本リポジトリは public のため、追跡対象に書く内容は公開される前提で判断する。

## Active Specifications

- `iac-hygiene-remediation` — 3 リポジトリ横断の是正
- `mail-platform` — メール基盤の構築
- `autonomous-parallel-dev-platform`（`gitops-apps` 側）— 自律開発環境

## Current State

以下は現在の実態であり、**知らずに前提を置くと判断を誤る**。

- **Ansible の playbook は実行できない。** 詳細は `tech.md` の Secrets 節。
- **バックアップは 1 件も存在しない。** 詳細は `tech.md` の Backup 節。
- **`fickledev.com` / `www.fickledev.com` はダウンしている（HTTP 521）。** VPS のオリジン証明書が
  2026-06-02 に失効し、Cloudflare の `ssl = "strict"` がオリジンを拒否している。オリジン自体は
  証明書検証を省けば HTTP 200 を返す。実体は HP Z440 上の LXC 115（`portfolio`, 192.168.1.103）。
- **ストレージに冗長性が無い。** 全ディスクが単発構成で、mirror / raidz / mdadm のいずれも無い。
- **IdP（authentik）は稼働しているが、認証連携しているサービスが 1 つも無い。** OIDC / SAML /
  forward auth の設定が両リポジトリに存在しない。実際の認証は各サービスのローカルアカウント、
  ServiceAccount トークン、IP ホワイトリスト、Cloudflare Access（GitHub IdP）で行われている。

---
_Focus on patterns and purpose, not exhaustive feature lists_
