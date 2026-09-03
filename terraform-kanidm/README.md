# terraform-kanidm

Kanidm (`gitops-apps/apps/kanidm/`) の利用者・グループ・OIDC クライアントを宣言的に
管理する、独立した Terraform ルートモジュール。

## 適用手段が非公式である事実と固定した供給元

Kanidm には利用者・グループ・OIDC クライアントを宣言的に適用する上流公式の手段が
存在しない。本モジュールは以下のサードパーティ製 Terraform provider を用いる。

- 供給元: https://github.com/SeanLatimer/terraform-provider-kanidm
- 配布: https://registry.terraform.io/providers/seanlatimer/kanidm
- 固定バージョン: `0.1.10`（`versions.tf` で完全一致固定。`~>` 等の範囲指定は使わない）
- 対応 Kanidm バージョン: provider README 記載の要求は `>= 1.8.5`。本環境の Kanidm は
  `1.11.1`（`gitops-apps/apps/kanidm/deployment.yaml` のダイジェスト参照）で満たす。

比較検討した代替候補は `oddlama/kanidm-provision`。JSON 宣言 + 専用トラッキング
グループによる差分検出で冪等性を持つが、(a) コンテナ配布物を持たずバイナリのみで
k3s Job 化に追加のイメージビルドを要する、(b) `account_policy`（`credential_type_minimum`
/ `authsession_expiry` 等、要件 26.33 が要求するグループ単位の認証情報種別・セッション
有効期限の設定）を実装していない、の 2 点で本要件を満たせないため採用しなかった。

## state の分離

本モジュールの state は既存の HCP Terraform ワークスペース `my-home-network`
（Proxmox / Cloudflare を管理）とは**別ワークスペース** `kanidm-identity`
（同一組織 `fickledev`）に置く。Kanidm の利用者・グループ・OIDC クライアントの
宣言はインフラのプロビジョニングとは変更頻度・関心事が異なり、同一 state に
混ぜると plan の差分がノイズ化するため分離した。

## 認証

`provider "kanidm"` は Kanidm のサービスアカウント API トークンで認証する
（person の主資格情報は使わない）。トークンを持つサービスアカウント
`terraform-kanidm` は本モジュールの適用対象外として Kanidm 側に直接作成した
（Terraform 自身が自分の認証情報を管理する循環を避けるための一回限りの
ブートストラップ。`admin` の初期パスワードを `kanidmd recover-account` で
発行した既存の運用と同じ位置づけ）。トークンは Infisical `prod` の
`TF_VAR_kanidm_token` に格納済み。

## 適用方法

```sh
cd terraform-kanidm
infisical run --token="$INFTOK" --projectId=<project-id> --env=prod -- terraform init
infisical run --token="$INFTOK" --projectId=<project-id> --env=prod -- terraform plan
infisical run --token="$INFTOK" --projectId=<project-id> --env=prod -- terraform apply
```

`terraform/` 側の既存の運用（README.md 参照）と同じく、ローカルの `.env` /
`terraform.tfvars` は使わない。
