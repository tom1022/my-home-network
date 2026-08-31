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
- VPS（Conoha）を経由した Web/Mail サービスの Cloudflare + Tailscale 越しの公開
- k3s 上のワークロード（Nextcloud, Ollama, MinIO, Ghost, Stalwart Mail 等）の GitOps 管理

## Value Proposition

- リソース作成（Terraform）と構成適用（Ansible）の責務分離により変更影響を局所化
- 変数駆動設計でノード・VMID・ストレージ差分を吸収し、再利用性を確保
- gitleaks (pre-commit) + Infisical によりセキュリティを運用ではなく設計に組み込み

---
_Focus on patterns and purpose, not exhaustive feature lists_
