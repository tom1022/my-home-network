# Research & Design Decisions

## Summary

- **Feature**: `infisical-cloudflare-iac-refactor`
- **Discovery Scope**: Complex Integration（2リポジトリ + 稼働中の k3s クラスタ + 外部 SaaS）
- **Key Findings**:
  - **Garage は `if-none-match` による相互排他を設計上サポートしない**ため state バックエンドに使えない。加えて自宅内ストレージは循環依存を生む。HCP Terraform（Local 実行モード）の採用でロック・履歴・循環回避をまとめて解決した
  - **Cloudflare Provider v5 のトンネルトークン データソースに不具合報告がある**。これを回避する設計にすると、副次的に tfstate へ秘密が入らなくなる
  - **ドリフトの構造的原因は依存方向の違反**にある。Ansible（構成適用層）が Kubernetes リソース（アプリケーション層）を直接 apply しており、レイヤを飛び越えている
  - 停止許容の前提により、経路移行は段階移行ではなく一括切り替えが最適解となる

---

## Research Log

### Garage の S3 条件付き書き込み対応

- **Context**: Requirement 4-5（ロックによる同時更新防止）を Terraform の S3 バックエンドで実現できるか。`use_lockfile = true` は S3 の条件付き書き込みに依存する
- **Sources Consulted**:
  - [Garage Known issues](https://garagehq.deuxfleurs.fr/documentation/reference-manual/known-issues/)
  - [Garage S3 Compatibility](https://garagehq.deuxfleurs.fr/documentation/reference-manual/s3-compatibility/)
  - [Garage releases](https://git.deuxfleurs.fr/Deuxfleurs/garage/releases)
  - クラスタ実査: 稼働中イメージは `dxflrs/garage:v2.2.0`
- **Findings**:
  - Terraform の `use_lockfile` は `PutObject` に `If-None-Match` を付与してロックファイルを原子的に作成する方式（Terraform 1.10 で実験導入、1.11 で GA）
  - Garage は公式に次を明言している。「合意アルゴリズムを持たない設計であるため、書き込みまたはロック設定の完了**前に**同時到達した上書き要求を、安全かつ一貫した方法で拒否できない」
  - 結果として「`if-none-match` の実用的なユースケースの多くはサポートできない（例: **並行writer間の相互排他の実装**）」と記載されている
  - v2.2.0 に「precondition 時刻がオブジェクトのタイムスタンプと等しい場合の処理修正」があるが、上記の構造的制約を解消するものではない
- **Implications**:
  - **`use_lockfile = true` を Garage に対して設定してはならない**。動作するように見えて競合時に静かに失敗する（最悪の失敗様式）
  - Garage は state バックエンドの候補から外れる。代替として自宅環境外のサービスを評価した（下記「Design Decision: state バックエンドとロック方式」）

### state バックエンドの代替候補

- **Context**: Garage で S3 ネイティブロックが使えない場合の代替
- **Findings**:
  - Terraform の `s3` バックエンドのロック手段は DynamoDB（非推奨化）と `use_lockfile` のみ。Garage は DynamoDB 互換 API を提供しない
  - `pg` バックエンドは PostgreSQL のアドバイザリロックを用いる。クラスタ内に CNPG の `postgres-cluster` が稼働している
  - ただしクラスタ実査の結果、PostgreSQL の Service はすべて `ClusterIP` であり外部公開されていない
- **Implications**:
  - `pg` バックエンドの採用には PostgreSQL の外部公開が必要となり、攻撃面が増える
  - さらに致命的な問題として、**Proxmox の Terraform が、その Terraform 自身が作成した VM 上で動く k3s 内の PostgreSQL に依存する循環が生じる**。クラスタ全損時に Proxmox の state を読めず復旧できない
  - `pg` バックエンドは採用不可と判断する

### Cloudflare Provider v5 と cf-terraforming

- **Context**: Requirement 3 / 9 の実現手段
- **Sources Consulted**:
  - [Terraform v5 Provider GA changelog](https://developers.cloudflare.com/changelog/post/2025-02-03-terraform-v5-provider/)
  - [Version 5 Upgrade Guide](https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/guides/version-5-upgrade)
  - [cf-terraforming README / releases](https://github.com/cloudflare/cf-terraforming)
  - [cloudflare_zero_trust_tunnel_cloudflared_config](https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_tunnel_cloudflared_config)
  - [Issue #5149: tunnel token データソースがトークンを返さない](https://github.com/cloudflare/terraform-provider-cloudflare/issues/5149)
- **Findings**:
  - v5 は OpenAPI スキーマから自動生成される方式に変わり、v4 から資源名が変更された（`cloudflare_record` → `cloudflare_dns_record` 等）。最新は v5.19.0 系
  - cf-terraforming は「プロバイダでリリースされた資源は自動的に generate / import 対象になる」方針で v5 に追随している
  - トンネルは `cloudflare_zero_trust_tunnel_cloudflared`、経路定義は `cloudflare_zero_trust_tunnel_cloudflared_config`（`ingress` に hostname / service を列挙）で管理できる
  - トークン取得用の `cloudflare_zero_trust_tunnel_cloudflared_token` データソースには、トークンを返さないという不具合報告がある
  - v5 は移行初期に不具合報告が多く、Cloudflare は2週間ごとの改善リリースを表明している
- **Implications**:
  - トンネル本体と経路定義は Terraform で管理できる
  - **トークンデータソースには依存しない設計とする**。トークンは Infisical に直接保管し、Kubernetes へは Operator が同期する
  - この回避は副次的な利点を持つ。**トンネルトークンが tfstate に一切書き込まれない**ため、state ファイルの機密性要件が下がる

### Kubernetes シークレット供給オペレータ

- **Context**: Requirement 7 の実装方式
- **Sources Consulted**:
  - [Infisical Kubernetes Operator](https://infisical.com/videos/kubernetes-operator-video-page)
  - [ESO Infisical provider](https://external-secrets.io/latest/provider/infisical/)
  - [External Secrets Operator is paused. What's next?](https://infisical.com/blog/external-secrets-operator-paused)
- **Findings**:
  - Infisical 公式オペレータは `InfisicalConnection`（接続先）、`InfisicalAuth`（認証）、同期定義リソースの3 CRD で構成される。取り込みに加え、クラスタからの押し出しと動的シークレットのリースにも対応する
  - ESO は汎用オペレータで Infisical をプロバイダとして扱う。2025年8月に新規リリースが一時停止したが、メンテナ交代により再開している
  - 一般的な指針として、既に ESO を運用しているなら ESO に Infisical プロバイダを足すのが簡単、Infisical 中心の新規構成なら公式オペレータが推奨される
- **Implications**:
  - 本環境は ESO を運用しておらず、バックエンドは Infisical 単一である。公式オペレータが素直に適合する

### Proxmox VE における unattended-upgrades

- **Context**: Requirement 11 の実装方式
- **Sources Consulted**: Proxmox 公式フォーラムの複数スレッド、Debian 12（bookworm）の慣行
- **Findings**:
  - PVE のパッケージを対象に含めるには `Unattended-Upgrade::Allowed-Origins` に `origin=Proxmox,label=Proxmox Debian Repository` を加える
  - 各リポジトリの origin / label は `apt-cache policy` で確認できる
  - Proxmox は安定版 Debian より流動的で、マイナーバージョン間で新規パッケージが必要になることがあるため、公式には `dist-upgrade` が推奨される
  - unattended-upgrades は本質的に `upgrade` 相当であり、新規パッケージの導入や削除を伴う更新は適用しない
- **Implications**:
  - unattended-upgrades ではセキュリティ更新の自動適用までが射程となる
  - **PVE のバージョン更新（`dist-upgrade`）は手動作業として残る**。Requirement 11-5（対象範囲の明示）およびドキュメントでこの境界を明示する必要がある

### k3s auto-deploy の削除セマンティクス

- **Context**: Requirement 12 の移行手順
- **Findings**:
  - `/var/lib/rancher/k3s/server/manifests/` からファイルを削除すると、k3s の deploy controller は対象リソースも削除する
  - 同ディレクトリに `.skip` 拡張子のファイルを置くと、対応するマニフェストの処理をスキップさせられる
  - 停止が許容される前提では、削除されたリソースは Argo CD 側から再作成できる
- **Implications**:
  - 段階移行（`.skip` 活用）の主たる利点は無停止性であり、停止許容下では手順の長さが純粋なコストになる
  - ただし Let's Encrypt 証明書は例外。再発行は同一ドメインセットに対する重複証明書の上限（週5枚）に抵触しうるため、Secret の退避が必要

### 本仕様スコープ外の手動作業（HCP Terraform / Cloudflare Terraform トークン / Infisical Operator bootstrap）の実施

- **Context**: design.md で「本仕様のスコープ外の手動作業」と明記されていた3項目（HCP Terraform の組織・workspace・API トークン、Cloudflare の Terraform 専用広域トークン、Infisical Operator の bootstrap 認証情報）を、タスク 3 系着手前に実施した
- **実施内容**:
  - **HCP Terraform**: Personal 組織 `fickledev` を作成し、CLI-Driven Workflow の workspace `my-home-network` を作成。実行モードを Local に設定。User API Token（有効期限12ヶ月）を発行し、Infisical に `TF_TOKEN_app_terraform_io` として格納済み
  - **Cloudflare**: 既存の DNS-01 用トークンとは別に、Terraform 専用のカスタムトークン `terraform-my-home-network` を作成。権限は Account（Access: Apps 編集, Access: Policies 編集, Cloudflare Tunnel 編集, Workers スクリプト編集, Workers R2 Storage 編集）と Zone（DNS 編集, ゾーン設定編集, ゾーン WAF 編集, ゾーン読み取り）。対象は `musashi.tochimura@gmail.com's Account` と `fickledev.com` ゾーンのみに限定。Infisical に `CLOUDFLARE_TERRAFORM_API_TOKEN` として格納済み。あわせて `CLOUDFLARE_ACCOUNT_ID`、`CLOUDFLARE_ZONE_ID` も同プロジェクトに格納済み
  - **Infisical Operator bootstrap**: 組織 Machine Identity `infisical-k8s-operator`（universal-auth 認証）を作成し、`fickledev` プロジェクトに Viewer ロールで追加。client id / client secret は Infisical には格納せず（Operator 自身が Infisical から認証情報を読む構成のため、循環依存を避ける）、ローカルの `~/.config/infisical/k8s-operator-bootstrap.env`（パーミッション 600）に保管。クラスタ側に Operator 用 namespace はまだ存在しないため、タスク 4.1 実装時にこのファイルの値で `kubectl create secret` する
- **Implications**:
  - タスク 4.1・6.1・7.2 は追加の手動準備なしに着手できる
  - Infisical CLI の非対話的な使い方（machine identity トークンの明示指定が必須である理由を含む）は `tech.md` に記録した

---

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 単層 GitOps | すべてを Argo CD で管理 | 経路が一意。ドリフトの構造的原因が消える | Argo CD 自身の起動に鶏卵問題が残る | 採用（ブートストラップのみ例外） |
| 役割分担型 | 基盤は Ansible、アプリは Argo CD | 現状からの変更が小さい | 境界が運用者の記憶に依存し、再発する | 却下 |
| Pull 型のみ | Ansible を全廃し k3s も GitOps 化 | 理論上最も一貫する | ホスト OS 構成の適用手段を失う | 却下 |

**選定パターン**: 単層 GitOps + 最小ブートストラップ。

責務を「シークレットの正（Infisical）」「基盤のプロビジョニング（Terraform）」「ホスト構成（Ansible）」「クラスタ内の全リソース（Argo CD）」の4層に分け、**依存方向を左から右への一方向に固定する**。現状のドリフトは、Ansible（ホスト構成層）が Kubernetes リソース（クラスタ層）を直接 apply して層を飛び越えていることに起因する。この違反を解消することが Requirement 12 の本質である。

---

## Design Decisions

### Decision: state バックエンドとロック方式

- **Context**: 現状の `terraform/terraform.tfstate` はローカルの単一ファイルでバックアップがない。喪失すると既存 VM / LXC を管理下と認識できなくなり、復旧に全リソースの手動 import を要する
- **Alternatives Considered**:
  1. Garage（自宅内 S3 互換） — **却下**。Garage は「合意アルゴリズムを持たない設計であるため `if-none-match` による並行 writer 間の相互排他は実装できない」と公式に明記しており、`use_lockfile` は動作するように見えて競合時に静かに破綻する。加えて自宅内ストレージであるため、Terraform 自身が作った基盤の上にその復旧手段が乗る循環が生じる
  2. `pg` バックエンド（CNPG PostgreSQL） — **却下**。Service が `ClusterIP` のみで外部非公開。さらに Garage と同じ循環問題を持つ
  3. ローカル state + オフラインバックアップ — 循環はないが、ロックも履歴もなく、バックアップ運用が人手に依存する
  4. **HCP Terraform（Free プラン）** — 自宅環境から完全に独立し、ロックと state 履歴を標準で備える
- **Selected Approach**: **HCP Terraform、実行モードは Local**。単一ルートモジュールに対しワークスペース1件を割り当てる
- **Rationale**:
  - 自宅環境のどのコンポーネントにも依存しないため、**循環依存が原理的に発生しない**。クラスタや Proxmox が全損しても state を読める
  - ロックが標準で提供されるため、Garage では充足不能だった要件が満たせる
  - Free プランは管理リソース500・1 concurrent run。本環境は現状6リソース（VM 4 / LXC 2）で、Cloudflare 追加後も数十規模に留まる
  - **Local 実行モードが必須**。Proxmox API は LAN 内（`192.168.1.10` / `192.168.1.2`）にあり、HCP のリモート実行機からは到達できない
  - Local 実行モードは HCP のワークスペース変数・変数セットを評価しない。この性質により、**シークレットが Infisical のみに存在する状態が構造的に保証される**（Requirement 1 の単一の正と整合）
- **Trade-offs**: state に記録される Proxmox 認証情報が外部サービスへ渡る。API トークン認証を用い、トークン権限を Terraform の操作範囲に限定して影響を抑える
- **Follow-up**: 組織の用意、ワークスペース1件の作成、実行モードの Local 設定、API トークンの発行は手動の前提作業となる。認証は `terraform login` ではなく `TF_TOKEN_app_terraform_io` の注入で行い、作業マシンにログイン状態を持たせない

### Decision: cloudflared トークンの供給経路

- **Context**: Requirement 9-2（マニフェストに直接記述しない）、9-5（Infisical 起点で供給）
- **Alternatives Considered**:
  1. Terraform の `cloudflare_zero_trust_tunnel_cloudflared_token` データソースで取得し、Kubernetes Secret を Terraform が作成する
  2. トークンを Infisical に保管し、Operator が Kubernetes へ同期する。Terraform はトンネルと経路のみ管理する
- **Selected Approach**: **選択肢2**
- **Rationale**: データソースに不具合報告があり依存を避けたい。加えて選択肢1ではトークンが平文で tfstate に記録され、state の機密性要件が上がる
- **Trade-offs**: トークンの初回投入が手動作業となる（Boundary の「手動作業」に計上済み）
- **Follow-up**: トンネルを Terraform に import する際、既存トンネルの ID を保持できるか確認する。再作成となる場合はトークンも再発行となり Infisical の更新が必要

### Decision: Kubernetes シークレット供給の実装

- **Context**: Requirement 7
- **Alternatives Considered**: Infisical 公式オペレータ / ESO + Infisical プロバイダ / SealedSecrets 併存
- **Selected Approach**: **Infisical Kubernetes Operator**
- **Rationale**: バックエンドが Infisical 単一であり抽象化層の利点がない。ESO 未導入のため移行元の資産もない
- **Trade-offs**: 将来バックエンドを変える場合の移行コストが高い
- **Follow-up**: オペレータ自身の認証情報（Machine Identity）をどう供給するか。ブートストラップ時のみ手動投入とし、以降はオペレータが自己完結する構成とする

### Decision: 経路移行の粒度

- **Context**: Requirement 12。停止が許容される
- **Alternatives Considered**: 一括切り替え / `.skip` を用いた段階移行 / ApplicationSet 統合のみ先行
- **Selected Approach**: **一括切り替え**。ただし証明書 Secret は事前退避する
- **Rationale**: 段階移行の主たる利点は無停止性であり、停止許容下では手順の長さが純粋なコストとなる
- **Trade-offs**: 失敗時の切り分けが段階移行より難しい。事前に Argo CD 側の定義を揃えて `plan` 相当の確認を済ませることで補う

### Decision: Ansible のシークレット参照方式

- **Context**: Requirement 1
- **Selected Approach**: 既存の変数間接化層の右辺を `lookup('env', 'NAME')` に置換し、`infisical run --env=prod --` で包んで実行する
- **Rationale**: 差分が最小で、Terraform 側と機構が揃う（Requirement 1-1）。新規のコレクション依存が生じない
- **Trade-offs**: `infisical run` でのラップを忘れると変数が空で解決される。**プロジェクト規約がフォールバック禁止を定めているため、各ロールの `assert` で空値を検出して停止させる**ことで補償する（Requirement 1-5）

---

## Risks & Mitigations

- **state に含まれる Proxmox 認証情報の外部流出** — API トークン認証の採用とトークン権限の限定
- **既存シークレットの復号鍵喪失** — 他の作業に先立って全シークレットを Infisical へ移送する。移行完了の確認まで既存の暗号化ファイルを削除しない
- **Let's Encrypt のレート制限抵触** — 経路移行前に `tls-fickledev-com` Secret を退避し、再発行を伴わない形で引き継ぐ
- **Cloudflare Provider v5 の不具合** — 適用前に必ず差分なしへ収束させる。トークンデータソースには依存しない
- **cloudflared トンネルの再作成** — import 可否を事前検証する。再作成となる場合はトークン再発行と Infisical 更新をセットで計画する
- **削除対象アプリのデータ消失** — `prune: true` により不可逆。削除前に PVC・データベース・オブジェクトストレージの退避要否を判断する
- **PVE の自動更新による予期しない挙動** — 再起動を自動化せず、`dist-upgrade` を対象外とすることで影響範囲を限定する

---

## References

- [Garage Known issues](https://garagehq.deuxfleurs.fr/documentation/reference-manual/known-issues/) — `if-none-match` による相互排他が非対応である根拠
- [Garage v2.0.0 release blog](https://garagehq.deuxfleurs.fr/blog/2025-06-garage-v2/) — v2 系の変更点
- [Terraform S3 backend native state locking](https://www.bschaatsbergen.com/s3-native-state-locking) — `use_lockfile` の内部動作
- [Terraform Cloudflare Provider Version 5 Upgrade Guide](https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/guides/version-5-upgrade) — v5 の資源名体系
- [cloudflare_zero_trust_tunnel_cloudflared_config](https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/resources/zero_trust_tunnel_cloudflared_config) — トンネル経路定義の契約
- [terraform-provider-cloudflare Issue #5149](https://github.com/cloudflare/terraform-provider-cloudflare/issues/5149) — トークンデータソースの不具合
- [cf-terraforming](https://github.com/cloudflare/cf-terraforming) — v5 対応方針
- [Infisical Kubernetes Operator](https://infisical.com/videos/kubernetes-operator-video-page) — CRD 構成
- [ESO Infisical provider](https://external-secrets.io/latest/provider/infisical/) — 代替案の仕様

### Decision: Terraform ルートモジュールを分割しない

- **Context**: 当初は Proxmox 向けと Cloudflare 向けを別ルートモジュールに分割する方針だった。分割の根拠として、Proxmox API が LAN 限定であるため両者を同一 state に置くと Cloudflare の変更にも LAN 到達性が必要になる、という点を挙げていた。
- **Correction**: この根拠は成立しない。OPNsense の Tailscale Router が `192.168.1.0/24` を広告しており、Proxmox API へはリモートからも到達できる。この前提は requirements.md の Adjacent expectations に既出である。
- **Alternatives**:
  - 分割する — 障害の隔離が得られる。Cloudflare Provider v5 の不具合で `refresh` が失敗しても Proxmox 側の操作を継続できる。一方でディレクトリ移動、backend 定義2件、init / apply の二重化を伴う。
  - 分割しない（採用） — 単一 state・単一ワークスペース。Proxmox 6リソース、Cloudflare 数十件という規模では plan 時間も影響範囲も問題にならない。両者は相互参照しないため、分割で得られる疎結合はもともと存在しない。
- **Selected Approach**: **分割しない**。既存の `terraform/` をそのまま単一ルートモジュールとし、Cloudflare 向けファイルを接頭辞付きで追加する。
- **Trade-off**: Cloudflare Provider v5 の障害が Proxmox 側の操作も止める。収束前に適用しない運用と HCP の state 履歴（直近100件）で影響を限定する。
- **Follow-up**: 将来リソース数が増えるか、Cloudflare 側の変更頻度が Proxmox 側と大きく乖離した場合は分割を再検討する。
