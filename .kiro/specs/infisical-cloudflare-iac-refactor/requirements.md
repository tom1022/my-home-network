# Requirements Document

## Project Description (Input)

my-home-network リポジトリおよび gitops-apps リポジトリのリファクタリング。シークレット管理の Infisical 集約、Cloudflare の Terraform 化、GitOps リポジトリの整理、Proxmox ホストの更新自動化を対象とする。

### 対象リポジトリ

- **my-home-network** (`/home/musashi/Documents/develop/my-home-network`): Terraform による Proxmox リソース作成と、Ansible による各ホストの構成管理
- **gitops-apps** (`/home/musashi/Documents/develop/gitops-apps`): Argo CD が同期する Kubernetes マニフェスト

### 背景と課題

**A. シークレットが両リポジトリで計6系統に分散**

my-home-network 側:

1. ansible-vault 暗号化ファイル5個（`vault_*` 変数 約22個）
2. Terraform 用 `terraform/.env` の `TF_VAR_*`
3. `ansible/inventory/host_vars/k3s-server/main.yml:8` に k3s node token が平文でコミット済み。gitleaks の既定パターンに該当せず検知をすり抜けており、git 履歴に残るためトークンローテーションが必要

gitops-apps 側:

4. SealedSecrets（`sealed-*.yaml` 14ファイル、公開鍵 `pub-cert.pem`）
5. SOPS/age（`.sops.yaml`、`apps/postgres/sops-secrets.yaml`）
6. ArgoCD Vault Plugin（`argocd/avp/`）— my-home-network の `argocd` ロールが age 鍵を配布している

**B. Cloudflare が未コード化**

`fickledev.com` の DNS、CDN プロキシ設定、WAF、Zero Trust がすべてダッシュボードで手動管理。加えて cloudflared のトンネル ID が `apps/cloudflared-fickledev/configmap-cloudflared-config.yaml` にハードコードされ、認証情報は SealedSecret として別管理という二重管理状態にある。

**C. tfstate がローカル1台に閉じている**

`terraform/terraform.tfstate` は gitignore されたローカルファイルで、どこにもバックアップがない。作業マシンが失われると state も失われ、Terraform は既存の VM / LXC を自身の管理下と認識できなくなる。その状態で適用すると同一構成を新規作成しようとするため、復旧には全リソースの手動 import が必要となる。

自宅環境内のストレージに state を置くと、**Terraform 自身が作成した基盤の上に、その Terraform の復旧手段が乗る循環**が生じる。クラスタや Proxmox が失われた際に state も同時に読めなくなるため、state の保管先は自宅環境から独立している必要がある。

**D. gitops-apps に不要な資産と構造の乱れが残存**

- `aramakisai.com` 系のアプリケーション（authentik / cloudflared / outline / planka とその PostgreSQL クラスタ、OIDC セットアップスクリプト）が稼働資産として残っている
- 同一ディレクトリに Helm チャート（`Chart.yaml` + `templates/`）と Kustomize（`kustomization.yaml` + 素のマニフェスト）が同居し、Argo CD がどちらとして解釈するかが構成から読み取れない（`cloudflared-*`、`xrayvpn`）
- `templates/` の内外で同一ファイルが重複（`configmap-default.yaml`、`sealed-*.yaml`）
- ApplicationSet の exclude リストが陳腐化し、存在しないディレクトリ（`apps/appflowy`、`apps/minio`）を除外している
- `.gitignore` に `.aider*` があるにもかかわらず `.aider.chat.history.md` 等が追跡済み
- GitHub Actions ワークフローが存在しないパス（`apps/argocd/notifications/**`）を監視している
- README が実態と乖離（nextcloud / ghost / portfolio / appflow など存在しないアプリを記載）

**D-2. ネットワーク図が実態と乖離している**

my-home-network の `README.md` および `.github/instructions/afternetwork.instructions.md` に含まれる Mermaid のネットワーク図が、稼働中の構成を表していない。

図に存在するが実体がないもの:

- `POD_NEXTCLOUD`（Nextcloud）、`POD_GHOST`（Ghost）、`POD_PORTFOLIO`（Portfolio）— gitops-apps に定義がなく namespace も存在しない
- `POD_STALWART`（Stalwart Mail）— 空の namespace のみが残存
- `POD_MINIO`（MinIO）— 127日 Pending で機能しておらず、削除対象

実体があるが図にないもの:

- Garage（稼働中の S3 互換オブジェクトストレージ。MinIO の実質的な後継）
- authentik-fickledev、mailu、xrayvpn、kubernetes-dashboard、minecraft-bedrock、home-assistant

この図はコード生成時の参照資料として `.github/instructions/` に配置されており、乖離したまま放置すると誤った前提での実装を誘発する。

**E. リポジトリ衛生の欠落（my-home-network）**

`.gitignore` の `ansible.cfg` パターンが `ansible/ansible.cfg` を巻き込み設定ファイルが未追跡。`.terraform.lock.hcl` も除外されプロバイダのバージョン固定が効かない。`roles/requirements.yml` の `rlex.k3s` がバージョン未固定かつ vendoring 済みで二重管理。`argocd` と `argocd_gitea_source` で同一変数が重複定義。

**F. Proxmox ホストの更新が自動化されていない**

Proxmox ホスト（n100 / hp-z440）のソフトウェア更新が定期的に実施されておらず、適用状況が構成管理の外にある。

**G. k3s クラスタにドリフトが蓄積している（クラスタ実査により確認）**

デプロイ経路が4系統併存している。

1. k3s auto-deploy（`/var/lib/rancher/k3s/server/manifests/`）— Ansible の `argocd` ロールが HelmChart 4件（argocd / cert-manager / reflector / reloader）、ClusterIssuer、wildcard-cert、ApplicationSet などを配置
2. Ansible `cert_manager` ロールによる `kubernetes.core.k8s` の直接適用（6箇所）— cert-manager と reflector が経路1と重複
3. ApplicationSet `apps`（gitops-apps リポジトリ内、exclude 6件）
4. ApplicationSet `gitops-apps`（my-home-network が経路1で配置、exclude なし）

経路3と経路4は同一の `apps/*` を対象とし、同名の Application を生成しようとするため所有権が分裂している。`argocd` / `base` / `home-assistant` / `mailu` は `gitops-apps` 所有、残り14件は `apps` 所有。

個別の破損と残骸:

- `garage` — `apps/garage/templates/backup-configmap.yaml` の YAML パースエラーで manifest 生成に失敗し、Sync ステータスが Unknown
- `tailscale-auth` — `kustomization.yaml` が存在しない `sops-tailscale-auth-secret.yaml` を参照し、manifest 生成に失敗
- `tailscale` — 上記により Secret `tailscale-auth` が作られず、Pod が `CreateContainerConfigError` のまま127日経過
- `common-secrets` — `ownerReferences` を持たない手動作成の Application。`SSH_AUTH_SOCK` 未設定で永続的に Unknown
- `postgres` — CNPG Cluster 3件すべてが OutOfSync
- `kubernetes-dashboard` — Degraded
- 孤児 namespace 3件 — `minio`（Pending の Pod が127日放置、Deployment / Service が残存）、`stalwart`（空）、`vikunja`（空）
- `gitops/apps/base/cert-manager/application.yaml` — 対応する Application がクラスタに存在しない死んだ定義
- gitops-apps に未コミットのローカル変更が残存（`apps/garage/templates/backup-configmap.yaml`、`apps/tailscale-auth/kustomization.yaml`、未追跡の `sealed-garage-backup-secrets.yaml` と `.gitignore`）

なお MinIO は127日間 Pending で機能しておらず、稼働中の S3 互換ストレージは Garage である。

### 達成したい状態

- シークレットの単一の源が Infisical になり、Ansible / Terraform / Kubernetes のすべてが Infisical を起点として取得する
- Cloudflare の構成が Terraform Provider v5 でコード化され版管理される。cf-terraforming で HCL と import ブロックを生成して既存構成を一度だけ state に取り込み、以降はコードが唯一の正となる
- cloudflared のトンネル定義が Terraform 側に集約され、Kubernetes 側は実行のみを担う
- Terraform の state を自宅環境外のマネージドサービスに置き、作業マシンにも自宅基盤にも依存させない
- gitops-apps から aramakisai 系の資産が除去され、パッケージング形式と参照の整合が取れている
- k3s クラスタへのデプロイ経路が Argo CD に一本化され、クラスタの状態がリポジトリと一致する
- Proxmox ホストのセキュリティ更新が自動適用される
- 両リポジトリを clone しただけで構成が再現できる

### スコープ外

k3s node token の実ローテーション作業、state 保管先サービスの組織およびワークスペースの用意、Cloudflare ダッシュボードでの API トークン発行、削除対象アプリの実データ（PostgreSQL データベース、オブジェクトストレージ上のバックアップ）の削除は、手動作業として別途実施する。

---

## Introduction

本仕様は、自宅環境のインフラを構成する2つのリポジトリ（my-home-network と gitops-apps）に対し、シークレット管理・構成のコード化・不要資産の除去・更新の自動化という4つの軸でリファクタリングを行うものである。

現状、シークレットは両リポジトリ合わせて6系統に分散しており、単一の正が存在しない。Cloudflare の構成はダッシュボードでの手動管理に留まり、cloudflared に至ってはトンネル ID と認証情報が別々の場所で管理されている。gitops-apps には運用対象外となった `aramakisai.com` 系の資産が残り、パッケージング形式の混在によって Argo CD の解釈が構成から読み取れない箇所がある。Proxmox ホストの更新は構成管理の外にある。

さらにクラスタの実査により、デプロイ経路が4系統併存し、2つの ApplicationSet が同一のディレクトリ集合を対象として Application の所有権が分裂していることが判明した。この構造が原因で、破損したまま127日放置された Application、手動作成の孤児 Application、稼働を終えたアプリケーションの namespace 残骸が蓄積している。

本リファクタリングにより、シークレットの供給を Infisical に一元化し、Cloudflare の構成を Terraform のコードとして版管理下に置く。あわせてデプロイ経路を Argo CD に一本化してドリフトの発生源を断ち、不要資産を除去し、Terraform の state を作業マシンから切り離し、ホストの更新を自動化する。

なお本仕様は運用基盤の再構成であり、存続するサービスの機能追加や変更を含まない。既存のワークロード（Gitea、NAS、PBS、k3s、VPS リバースプロキシ、および gitops-apps 上の存続アプリケーション）の動作は現状を維持することが前提となる。

## Boundary Context

- **In scope**:
  - シークレットの保管先および供給機構の変更（ansible-vault / `.env` / 平文 / SealedSecrets / SOPS-age / AVP → Infisical）
  - Cloudflare 構成（DNS、ゾーン設定、WAF、Zero Trust トンネル、Access、および実在する R2 / Workers）の Terraform コード化と state への取り込み
  - cloudflared のトンネル定義と実行の責務分離
  - Terraform state バックエンドの変更
  - gitops-apps からの aramakisai 系アプリケーションの削除と、それに伴う参照の整合
  - gitops-apps のパッケージング形式・ApplicationSet 定義・追跡対象ファイルの整理
  - ネットワーク図（`README.md` および `.github/instructions/afternetwork.instructions.md`）の実態への同期
  - k3s クラスタへのデプロイ経路の Argo CD への一本化
  - クラスタ内の孤児リソース・破損 Application の除去と、稼働していないアプリケーション（minio / stalwart / vikunja / tailscale）の削除
  - Proxmox ホストへのセキュリティ更新の自動適用
  - `.gitignore`、外部ロールのバージョン固定、Ansible 変数の重複解消
  - 上記に伴う両リポジトリのドキュメント更新

- **Out of scope**:
  - k3s node token の実際のローテーション作業（クラスタ側の操作）
  - state 保管先サービスの組織・ワークスペースの用意とプラン選定
  - Terraform 実行のリモート化（Proxmox API が LAN 内のため実行はローカルに限定する）
  - Cloudflare ダッシュボードでの API トークン発行
  - 削除対象アプリの実データ削除（PostgreSQL の既存データベース、オブジェクトストレージ上のバックアップ）
  - 存続するワークロードの機能追加・仕様変更
  - git 履歴からの秘密情報の消去（履歴書き換え）
  - Proxmox 以外のホスト（ゲスト VM / LXC）の更新自動化
  - カーネル更新に伴う再起動の自動実行
  - Argo CD 自身のブートストラップの Argo CD 化（k3s auto-deploy に残す）
  - k3s / Traefik など k3s ディストリビューションが同梱するコンポーネントの管理方式の変更

- **運用上の前提**:
  - 本環境は個人の趣味環境であり、**リファクタリング作業に伴うサービス停止は許容される**。可用性の維持よりリファクタリングの完遂を優先する
  - ただし停止の許容は**データ消失の許容を意味しない**。永続ボリューム、データベース、オブジェクトストレージ上のバックアップ、および失うと再取得に制約が伴うもの（Let's Encrypt 証明書など）は保護対象として扱う
  - 作業手順における無停止性の確保は要求しない。段階移行と一括切り替えのいずれも、より単純な方を選んでよい

- **Adjacent expectations**:
  - Infisical のプロジェクトおよび環境（`prod`）が利用可能であること
  - k3s クラスタ、Proxmox、Cloudflare の各 API が到達可能であること
  - Argo CD の ApplicationSet が `prune: true` で動作しており、ディレクトリの削除が稼働リソースの削除に直結すること
  - state 保管先のマネージドサービスが利用可能であり、無料枠の管理リソース上限に対して本環境の規模（現状6リソース、Cloudflare 追加後も数十規模）が十分に収まること
  - Proxmox API（`192.168.1.10` / `192.168.1.2`）および k3s API が LAN セグメントに閉じており、外部からの到達は OPNsense の Tailscale Router 経由に限られること。HCP のリモート実行環境からは到達できない
  - OPNsense の Tailscale Router が LAN セグメント（`192.168.1.0/24`）への到達性を提供しており、クラスタ内 subnet router の削除後もリモートアクセスが維持されること

---

## Requirements

### Requirement 1: シークレット供給の Infisical 一元化（Ansible / Terraform）

**Objective:** As a ホームラボ運用者, I want Ansible と Terraform のシークレットを Infisical から単一の機構で取得できること, so that 秘密情報の保管先が分散せず、どの作業マシンからでも同じ手順で構成を適用できる

#### Acceptance Criteria

1. The シークレット供給基盤 shall Ansible と Terraform の双方に対し、同一の機構（環境変数注入）でシークレットを供給する。
2. When 運用者が Infisical 経由で Ansible プレイブックを実行した場合, the Ansible インベントリ shall ansible-vault のパスワード入力を要求することなく、すべてのシークレット変数を解決する。
3. The シークレット供給基盤 shall Infisical 上のシークレット名を、既存の `vault_` 接頭辞を除去して大文字化した名前と一対一で対応させる。
4. Where Terraform が `TF_VAR_` 接頭辞の環境変数を参照する場合, the シークレット供給基盤 shall 変数名を変更することなく同一の名前で供給する。
5. If 必要なシークレットが供給されなかった場合, then the Ansible ロール shall 空値のまま処理を継続せず、欠落している変数を特定できる形で実行を停止する。
6. The my-home-network リポジトリ shall 暗号化されたものを含め、シークレットの値を保持するファイルを追跡対象に持たない。
7. The シークレット供給基盤 shall 用途の異なる認証情報を個別のシークレットとして保持し、単一の認証情報を複数用途で共用しない。

### Requirement 2: 平文シークレットの除去と再発防止

**Objective:** As a ホームラボ運用者, I want 平文のシークレットがリポジトリから排除され、同種の混入が自動検知されること, so that 秘密情報の意図しない露出を防げる

#### Acceptance Criteria

1. The my-home-network リポジトリ shall 追跡対象のファイルに平文のシークレットを含まない。
2. When 平文のシークレットを含む変更が commit されようとした場合, the シークレットスキャン shall 当該変更を検出して commit を拒否する。
3. Where 既定の検出パターンで捕捉できない形式のシークレット（k3s node token 等）が存在する場合, the シークレットスキャン shall 当該形式を検出対象に含める。
4. The 移行手順 shall 既存の ansible-vault 暗号化ファイルから Infisical への値の移送を、人手による転記を介さずに実施できる手段を提供する。
5. While 移行の妥当性が確認されていない期間, the 移行手順 shall 既存の vault ファイルを削除せず、切り戻し可能な状態を維持する。
6. If 平文でコミットされたシークレットが git 履歴に残存する場合, then the プロジェクトドキュメント shall 当該シークレットのローテーションが必要である旨と、その対象を明示する。

### Requirement 3: Cloudflare 構成の Terraform 化

**Objective:** As a ホームラボ運用者, I want Cloudflare の構成がコードとして版管理されること, so that ダッシュボードでの手動変更に依存せず、構成の変更履歴と意図を追跡できる

#### Acceptance Criteria

1. The Cloudflare Terraform モジュール shall DNS レコード、ゾーン設定、WAF ルールセット、Zero Trust トンネル、および Access アプリケーション/ポリシーをコードとして定義する。
2. Where R2 バケットまたは Workers スクリプトが実在する場合, the Cloudflare Terraform モジュール shall それらもコードとして定義する。
3. When 既存の Cloudflare 構成をコード化する場合, the 移行手順 shall 既存リソースを state に取り込むことで、稼働中の設定を削除することなく移行を完了する。
4. When 取り込み完了後に構成計画を確認した場合, the Cloudflare Terraform モジュール shall 差分なしを出力する。
5. If コード化されていない Cloudflare リソースが残存する場合, then the 移行手順 shall 現状の構成一覧と state の内容を突き合わせることで、その存在を検出可能にする。
6. The Cloudflare Terraform モジュール shall 使用するプロバイダのメジャーバージョンを明示的に固定する。
7. The Cloudflare Terraform モジュール shall 証明書発行（DNS-01 チャレンジ）用の既存 API トークンとは分離された、Terraform 専用の認証情報を使用する。
8. While 差分なしの状態に収束していない期間, the 移行手順 shall 構成の適用を行わない。

### Requirement 4: Terraform state の外部保管

**Objective:** As a ホームラボ運用者, I want Terraform の state が作業マシンからも自宅基盤からも独立していること, so that 作業マシンを失っても構成の管理権を失わず、複数のマシンから同じ構成を扱える

#### Acceptance Criteria

1. The Terraform 構成 shall state を自宅環境の外部にあるマネージドサービスに保管し、自宅環境内のいかなるコンポーネントにも依存させない。
2. When state を移行した後に構成計画を確認した場合, the Terraform 構成 shall 差分なしを出力する。
3. While 同一の state に対する更新が並行して発生する場合, the state バックエンド shall ロックにより同時更新を防止する。
4. The Terraform 実行 shall プランおよび適用を作業者のローカル環境で行う。
5. The Terraform 構成 shall シークレットの供給元を Infisical に限定し、state バックエンド側の変数機構に秘密を保持しない。
6. The state バックエンド shall 過去の state を保持し、誤った適用からの復旧経路を提供する。

### Requirement 5: リポジトリの再現性

**Objective:** As a ホームラボ運用者, I want リポジトリを clone しただけで構成を適用できる状態であること, so that 作業マシンの入れ替えや他者による再現が可能になる

#### Acceptance Criteria

1. When 運用者がリポジトリを clone した場合, the my-home-network リポジトリ shall Ansible の実行に必要な設定ファイルを追跡対象として含む。
2. The my-home-network リポジトリ shall Terraform プロバイダのバージョンロックファイルを追跡対象に含める。
3. The Ansible ロール依存定義 shall 外部ロールのバージョンを明示的に固定する。
4. The Ansible 変数定義 shall 同一の変数を複数のロールで重複して定義しない。
5. If 除外パターンが意図しないファイルを追跡対象から外している場合, then the リポジトリ shall パターンの適用範囲を限定し、当該ファイルを追跡対象に戻す。
6. The リポジトリ shall 生成物および秘密情報を含むファイルを追跡対象から除外した状態を維持する。

### Requirement 6: ドキュメントの整合

**Objective:** As a ホームラボ運用者, I want 両リポジトリのドキュメントが実装の現状と一致すること, so that 記載を信頼して手順を実行でき、設計意図が失われない

#### Acceptance Criteria

1. The プロジェクトドキュメント shall シークレット管理方式として Infisical を記載し、Ansible Vault・SealedSecrets・SOPS を前提とした記述を残さない。
2. The プロジェクトドキュメント shall 再現性確認の手順を、Infisical 経由での実行を前提とした形で記載する。
3. When ディレクトリ構成が変更された場合, the プロジェクトドキュメント shall 変更後の構成を反映する。
4. The プロジェクトドキュメント shall 自動化されず手動作業として残る項目を、実施が必要な作業として明示する。
5. The プロジェクト規約 shall コード生成時の前提となるシークレット管理方式の記述を、実装後の方式と一致させる。
6. The gitops-apps ドキュメント shall 実在しないアプリケーションを記載せず、稼働中のアプリケーション一覧と一致させる。
7. The ネットワーク図 shall 実体を持たないコンポーネントを含まない。
8. The ネットワーク図 shall 稼働中の主要コンポーネントとその依存関係を反映する。
9. When ネットワーク図を更新した場合, the プロジェクト規約 shall `README.md` と `.github/instructions/afternetwork.instructions.md` の双方で同一の内容を保持する。

### Requirement 7: Kubernetes シークレットの Infisical 集約

**Objective:** As a ホームラボ運用者, I want Kubernetes 上のシークレットも Infisical を起点として供給されること, so that クラスタ内外でシークレットの正が一つに定まり、暗号鍵の配布と管理が不要になる

#### Acceptance Criteria

1. The gitops-apps リポジトリ shall Kubernetes へのシークレット供給機構を単一の方式に統一する。
2. The Kubernetes シークレット供給基盤 shall Infisical に保管された値を起点としてクラスタ内の Secret を生成する。
3. When シークレット機構の移行が完了した場合, the gitops-apps リポジトリ shall SealedSecrets、SOPS/age、ArgoCD Vault Plugin のいずれの資産も残さない。
4. When シークレット機構の移行が完了した場合, the Ansible 構成 shall Argo CD への age 秘密鍵の配布を行わない。
5. The gitops-apps リポジトリ shall 暗号化されたものを含め、シークレットの値を保持するファイルを追跡対象に持たない。
6. While 移行の妥当性が確認されていない期間, the 移行手順 shall 既存のシークレット定義を削除せず、切り戻し可能な状態を維持する。
7. If Infisical からシークレットを取得できなかった場合, then the Kubernetes シークレット供給基盤 shall 空の Secret を生成せず、同期の失敗を検知可能な形で示す。

### Requirement 8: aramakisai 系アプリケーションの削除

**Objective:** As a ホームラボ運用者, I want 運用対象外となった aramakisai 系のアプリケーションと関連資産が除去されること, so that リポジトリが稼働中の構成のみを表し、不要なリソース消費とメンテナンス対象が減る

#### Acceptance Criteria

1. The gitops-apps リポジトリ shall aramakisai 系アプリケーション（authentik-aramakisai、cloudflared-aramakisai、outline、planka）のマニフェストを含まない。
2. The gitops-apps リポジトリ shall 削除対象アプリケーション専用のセットアップスクリプトを含まない。
3. When アプリケーションを削除した場合, the gitops-apps リポジトリ shall 当該アプリケーションを参照する他のマニフェスト（PostgreSQL クラスタ定義、スケジュールバックアップ、オブジェクトストレージのバケット定義、Kustomize のリソース一覧）から該当する参照を除去する。
4. When 削除後に Argo CD が同期した場合, the Kubernetes クラスタ shall 削除対象アプリケーションのリソースを保持しない。
5. If 削除対象アプリケーションのデータが永続ボリュームまたはオブジェクトストレージに残存する場合, then the プロジェクトドキュメント shall その削除が手動作業として必要である旨を明示する。
6. The gitops-apps リポジトリ shall 削除後に、存続するアプリケーションが参照する定義を破壊しない。

### Requirement 9: cloudflared の責務分離

**Objective:** As a ホームラボ運用者, I want cloudflared のトンネル定義が Terraform に集約され Kubernetes 側は実行のみを担うこと, so that トンネル ID と認証情報の二重管理が解消され、公開経路の定義が一箇所で追える

#### Acceptance Criteria

1. The Cloudflare Terraform モジュール shall cloudflared のトンネルと、その公開ホスト名に対する経路定義を管理する。
2. The gitops-apps リポジトリ shall cloudflared のトンネル識別子および認証情報をマニフェスト内に直接記述しない。
3. The Kubernetes 上の cloudflared shall トンネルの実行のみを担い、経路の定義を保持しない。
4. When トンネルの経路定義を変更した場合, the 運用者 shall Terraform 側の変更のみで反映を完了できる。
5. The cloudflared 認証情報 shall Infisical を起点として Kubernetes へ供給される。
6. When 移行が完了した場合, the cloudflared shall 移行前と同一の公開ホスト名に対する到達性を提供する。

### Requirement 10: gitops-apps の構造整理

**Objective:** As a ホームラボ運用者, I want gitops-apps のパッケージング形式と定義が一貫していること, so that Argo CD の解釈が構成から読み取れ、意図しない同期結果を避けられる

#### Acceptance Criteria

1. The gitops-apps リポジトリ shall 各アプリケーションディレクトリにおいて、Helm と Kustomize のいずれか一方のパッケージング形式のみを用いる。
2. The gitops-apps リポジトリ shall 同一内容のマニフェストを複数の場所に重複して配置しない。
3. The ApplicationSet 定義 shall 実在しないディレクトリを除外対象に列挙しない。
4. The ApplicationSet 定義 shall 自動同期の対象と対象外を、リポジトリの実際のディレクトリ構成と一致させる。
5. The gitops-apps リポジトリ shall 除外パターンで指定されたファイルを追跡対象に含まない。
6. If 継続的インテグレーションの定義が実在しないパスを監視している場合, then the gitops-apps リポジトリ shall 当該定義を実態に合わせるか除去する。

### Requirement 11: Proxmox ホストの更新自動化

**Objective:** As a ホームラボ運用者, I want Proxmox ホストのセキュリティ更新が自動で適用されること, so that 更新漏れによる脆弱性の放置を防ぎ、更新作業の手間を減らせる

#### Acceptance Criteria

1. The Ansible 構成 shall Proxmox ホストに対する自動更新の設定を、構成管理の対象として定義する。
2. The Proxmox ホスト shall セキュリティ更新を自動的に適用する。
3. The 自動更新 shall 再起動を伴う更新を自動では実行しない。
4. Where 再起動が必要な更新が適用された場合, the Proxmox ホスト shall その状態を運用者が確認できる形で示す。
5. The Ansible 構成 shall 自動更新の対象とするパッケージの範囲を明示的に指定する。
6. If 自動更新が失敗した場合, then the Proxmox ホスト shall 失敗の記録を残す。
7. The 自動更新 shall 稼働中のゲスト（VM / LXC）を停止させない。

### Requirement 12: k3s デプロイ経路の Argo CD への一本化

**Objective:** As a ホームラボ運用者, I want クラスタへのデプロイ経路が Argo CD に一本化されること, so that リソースの管理主体が一意に定まり、経路の重複に起因するドリフトが再発しない

#### Acceptance Criteria

1. The k3s クラスタ shall Argo CD 以外の経路で継続的に管理されるアプリケーションリソースを持たない。
2. The k3s auto-deploy 機構 shall Argo CD 自身のブートストラップに必要な最小限のマニフェストのみを配置する。
3. The Ansible 構成 shall クラスタ内リソースを直接適用しない。
4. The Argo CD 構成 shall 同一のディレクトリ集合を対象とする ApplicationSet を複数持たない。
5. When ApplicationSet を統合した場合, the Argo CD shall すべての Application の所有権を単一の ApplicationSet に収束させる。
6. The k3s クラスタ shall cert-manager、reflector、reloader、ClusterIssuer、ワイルドカード証明書を、それぞれ単一の経路で管理する。
7. If 経路の除去によって失われるリソースが再取得に制約を伴う場合（Let's Encrypt 証明書等）, then the 移行手順 shall 当該リソースを保全したうえで経路を切り替える。
8. When 経路の統合が完了した場合, the k3s クラスタ shall 統合前と同一のサービス群を提供する。

### Requirement 13: クラスタ内の孤児・破損リソースの除去

**Objective:** As a ホームラボ運用者, I want クラスタの状態がリポジトリの定義と一致すること, so that クラスタに何が存在するかをリポジトリから判断でき、放置された破損に気付ける

#### Acceptance Criteria

1. The k3s クラスタ shall リポジトリに対応する定義を持たない namespace を保持しない。
2. The k3s クラスタ shall ApplicationSet が生成していない Application を保持しない。
3. The k3s クラスタ shall 稼働を終了したアプリケーション（minio、stalwart、vikunja、tailscale）のリソースを保持しない。
4. When ドリフトの解消が完了した場合, the Argo CD shall すべての Application について Sync ステータスを Synced として報告する。
5. When ドリフトの解消が完了した場合, the Argo CD shall すべての Application について Health ステータスを Healthy として報告する。
6. The gitops-apps リポジトリ shall Kustomize および Helm の定義から、存在しないファイルを参照しない。
7. The gitops-apps リポジトリ shall 構文的に不正なマニフェストを含まない。
8. The gitops-apps リポジトリ shall クラスタに適用済みの内容と乖離した未コミットの変更を残さない。
9. If Argo CD がマニフェストの生成に失敗した場合, then the 運用者 shall 失敗した Application と原因を特定できる。
10. When ドリフトの解消が完了した場合, the 運用者 shall クラスタとリポジトリの差分を検出する手順を実行して、差分がないことを確認できる。
