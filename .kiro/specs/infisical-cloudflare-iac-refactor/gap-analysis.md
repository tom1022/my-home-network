# Gap Analysis: infisical-cloudflare-iac-refactor

**分析日**: 2026-08-28（停止許容の前提を反映して更新）
**対象要件**: requirements.md の Requirement 1〜13
**調査範囲**: my-home-network リポジトリ、gitops-apps リポジトリ、稼働中の k3s クラスタ（実査）

> `.kiro/steering/` が存在しないため、プロジェクト記憶なしで分析している。`/kiro:steering` の実行により以降の精度が上がる。

---

## 1. 現状調査

### 1-1. 再利用できる既存資産

**変数の間接化層（最重要の資産）**

my-home-network はシークレットの参照が既に1層に集約されている。

```yaml
# ansible/inventory/group_vars/all/main.yml
proxmox_api_token_secret: "{{ vault_proxmox_api_token_secret | default('') }}"
```

ロール側は `proxmox_api_token_secret` を参照し、`vault_*` を直接見ない。**この層の右辺を差し替えるだけで Requirement 1 の大半が満たせる**。対象は以下に集中している。

- `ansible/inventory/group_vars/all/main.yml`（11変数）
- `ansible/inventory/host_vars/{gitea,pbs,vps}/main.yml`
- `ansible/roles/proxmox_backup/defaults/main.yml`（7変数）
- `ansible/roles/argocd/defaults/main.yml`、`ansible/roles/argocd_gitea_source/defaults/main.yml`

**必須変数の検証パターン**

`letsencrypt`、`cert_manager`、`proxmox_backup` の各ロールが冒頭で `ansible.builtin.assert` による必須変数チェックを実装済み。Requirement 1-5（欠落時に停止）はこのパターンの水平展開で実現でき、新規の仕組みを要しない。

```yaml
# ansible/roles/cert_manager/tasks/main.yml:14 付近
- ansible.builtin.assert:
    that:
      - cert_manager_cloudflare_api_token | length > 0
```

**ロール構造の規約**

`defaults/` `tasks/` `templates/` `handlers/` `meta/` の分離、FQCN の徹底、`meta/main.yml` の `dependencies` による依存表現が全ロールで一貫している。Requirement 11 の新規ロールはこの型をなぞればよい。

**Terraform のモジュール化**

`modules/vm`、`modules/container` に切り出し済み。`locals.tf` がノード差分を吸収する。Requirement 4 は state の外部化のみを求めるため、この配置に変更は生じない。Cloudflare 向けの定義は同一ルートに追加する。

**プロジェクト規約**

`.github/instructions/rule.instructions.md` に「ansible-lint 厳守」「FQCN」「shell/command は最終手段」「**フォールバックは決して実装しない**」「ハードコード回避」が明文化されている。設計はこれに従う必要がある。

### 1-2. ツールの可用性

| ツール | 状態 | 用途 |
|---|---|---|
| terraform | 導入済 v1.15.9 | R3 / R4 |
| infisical | 導入済 v0.43.96（ログイン済） | R1 / R7 |
| kubectl / helm | 導入済 | R12 / R13 |
| sops / age / kubeseal | 導入済 | 既存シークレットの復号（移行時のみ） |
| **cf-terraforming** | **未導入** | R3 の HCL / import ブロック生成 |
| tf-migrate | 未導入 | 今回は v4→v5 移行ではないため不要 |

Ansible collections: `kubernetes.core 3.2.0`、`community.general 9.5.2`、`ansible.posix`（**2.2.0 と 1.6.2 が重複導入**）。

### 1-3. アーキテクチャ上の制約

**C-1. Argo CD の `prune: true` + `selfHeal: true`**
両 ApplicationSet が自動 prune で動作している。ディレクトリの削除が稼働リソースの削除に直結するため、R8 / R13 の削除は不可逆。**停止は許容されるがデータ消失は許容されない**ため、PVC・データベース・オブジェクトストレージの事前退避が要る。

**C-2. k3s auto-deploy のファイル削除セマンティクス**
`/var/lib/rancher/k3s/server/manifests/` からファイルを削除すると、k3s の deploy controller は**対象リソースも削除する**。R12 の経路移行で単純にファイルを消すと cert-manager 等が消える。停止許容の前提下では再作成で復旧できるため致命的ではないが、**Let's Encrypt の証明書は例外**（下記 C-6）。

**C-6. Let's Encrypt のレート制限**
`wildcard-fickledev-com` を含む証明書を削除して再発行すると、同一ドメインセットに対する重複証明書の発行上限（週5枚）に抵触しうる。停止は許容されても**証明書の再発行は容易に巻き戻せない**ため、Secret `tls-fickledev-com` の保全が経路移行の前提となる。

**C-3. `proxmox_nodes` 向けの構成管理導線が存在しない**
`proxmox_nodes` グループを対象とする playbook は `nas.yml` 内の `nfs_client` 適用のみ。`site.yml` にも Proxmox ホスト自体を構成する導線がない。R11 はロール・playbook・`site.yml` への組み込みまで新設が必要。

**C-4. ApplicationSet の Helm / Kustomize 自動判別**
`gitops-apps` ApplicationSet は形式を明示せず Argo CD の自動判別に委ねている。同一ディレクトリに `Chart.yaml` と `kustomization.yaml` が同居する `cloudflared-*` / `xrayvpn` は解釈が構成から読み取れない。R10 の統一はこの前提の解消を含む。

**C-5. Terraform の `required_version`**
現在 `>= 1.5.0`。導入済みバイナリは 1.15.9 のため、R4 の S3 ネイティブロック（`use_lockfile`、1.10 以降）へ引き上げても実行環境上の障害はない。

---

## 2. 要件 → 資産マップ

| # | 要件 | 既存資産 | ギャップ | 種別 |
|---|---|---|---|---|
| 1 | シークレット一元化（Ansible / TF） | 変数間接化層、`assert` パターン、infisical CLI | 右辺の置換、`assert` の水平展開、移行スクリプト | Missing（小） |
| 2 | 平文除去・再発防止 | `.gitleaks.toml`、pre-commit | k3s node token 用カスタムルール、移行スクリプト | Missing（小） |
| 3 | Cloudflare の Terraform 化 | なし | Terraform コード一式、cf-terraforming 導入、API トークン | Missing（大） |
| 4 | state の外部化 | 既存ルートモジュール稼働中 | `cloud` ブロック定義、ワークスペース作成、state 転送 | Missing |
| 5 | リポジトリ再現性 | — | `.gitignore` パターン修正、バージョン固定 | Missing（小） |
| 6 | ドキュメント整合 | README、`rule.instructions.md`、Mermaid 図 | 記述更新、ネットワーク図の全面書き直し（実体なし5件の除去、稼働中6件の追加） | Missing（中） |
| 7 | k8s シークレットの Infisical 集約 | Infisical 稼働、既存 Secret 定義 | オペレータ導入、14個の SealedSecret + SOPS の移行 | Missing + **Unknown** |
| 8 | aramakisai 系削除 | 削除対象を特定済 | 参照整合、削除順序 | Constraint（C-1） |
| 9 | cloudflared 責務分離 | 稼働中のトンネル | Terraform の tunnel / ingress 定義 | Missing + Constraint |
| 10 | gitops-apps 構造整理 | — | 形式統一、ApplicationSet 定義修正 | Constraint（C-4） |
| 11 | Proxmox 更新自動化 | apt パターン、ロール規約 | **ロール・playbook・導線すべて新規** | Missing + Constraint（C-3） |
| 12 | デプロイ経路の一本化 | — | 経路移行手順 | Constraint（C-2、最重要） |
| 13 | 孤児・破損リソース除去 | 対象を実査で特定済 | 削除手順、差分検出手順 | Constraint（C-1） |

---

## 3. 実装アプローチの選択肢

判断が分かれる5つのワークストリームについて選択肢を示す。

### WS-1. シークレット供給（Ansible / Terraform）— Requirement 1, 2

**Option A: 既存の間接化層を拡張**
`group_vars` / `defaults` の右辺を `lookup('env', 'X')` に置換し、層の構造は維持する。

- ✅ 差分が最小。ロール本体に一切触れない
- ✅ 既存の `assert` パターンをそのまま流用できる
- ❌ 変数名の対応表が暗黙になる（命名規則のドキュメント化で補える）

**Option B: 専用の変数ファイルを新設**
`inventory/group_vars/all/infisical.yml` を作り、既存 `main.yml` から非シークレット設定と分離する。

- ✅ シークレット由来の変数が一望できる
- ❌ ファイルが増え、`main.yml` との参照関係を追う手間が増える
- ❌ Ansible の変数優先順位が同一階層のため、読み込み順の考慮が要る

**Option C: `infisical.vault` コレクションの lookup を使う**
CLI ではなく Ansible の lookup プラグインで直接取得する。

- ✅ Ansible 単体で完結し `infisical run` のラップが不要
- ❌ 新規コレクション依存と Machine Identity の設定が増える
- ❌ Terraform 側は別機構のままになり、Requirement 1-1（同一機構）を満たさない

### WS-2. Kubernetes シークレット — Requirement 7

**Option A: Infisical Kubernetes Operator**
`InfisicalConnection` / `InfisicalAuth` / シークレットリソースの3 CRD で構成する。

- ✅ Infisical 専用のため設定が素直で、双方向同期や動的シークレットにも将来対応できる
- ✅ 他のシークレットマネージャを使わない本環境の実態に合う
- ❌ Infisical 以外に切り替える際の移行コストが高い

**Option B: External Secrets Operator + Infisical プロバイダ**
汎用オペレータの provider として Infisical を指定する。

- ✅ デファクトに近く、情報量が多い
- ✅ 将来のバックエンド変更に強い
- ❌ 抽象化層のぶん設定項目が多い
- ❌ 2025年8月に新規リリースが一時停止した経緯がある（その後メンテナ交代で再開）

**Option C: SealedSecrets を残したまま Infisical を併用**
既存14個を維持し、新規のみ Infisical にする。

- ❌ Requirement 7-1（単一方式への統一）および 7-3 に反する
- ❌ 二重管理が固定化する

### WS-3. Cloudflare の Terraform 化 — Requirement 3, 9

**Option A: cf-terraforming で全面生成**
`generate` で HCL、`import` で import ブロックを一括生成し、収束させる。

- ✅ 取りこぼしが構造的に起きにくい
- ✅ 手作業のマッピングが不要
- ❌ cf-terraforming の導入が必要
- ❌ 生成される HCL は冗長で、`for_each` 化などの整形が別途要る

**Option B: 手書き + `terraform plan` での突き合わせ**
API ダンプを見ながら HCL を書き、差分ゼロに追い込む。

- ✅ 最初から意図した構造（`locals` + `for_each`）で書ける
- ❌ レコード数に比例して工数が伸び、取りこぼしのリスクが残る

**Option C: ハイブリッド**
cf-terraforming で骨子を生成し、DNS など反復性の高い部分だけ `for_each` に整形する。

- ✅ 網羅性と可読性を両立できる
- ❌ 生成物と整形後の対応関係を追う一手間がある

### WS-4. デプロイ経路の一本化 — Requirement 12

**Option A: 一括切り替え（停止許容下での推奨）**
Argo CD 側の定義を揃えたうえで、証明書 Secret のみ退避し、auto-deploy のマニフェストをまとめて除去して Argo CD に引き継ぐ。

- ✅ 手順が単純で短時間に終わる
- ✅ 中間状態が存在しないため、経路の重複による混乱が起きない
- ❌ 一時的にクラスタ基盤が失われる（停止許容の前提下では受容可能）
- ❌ C-6 により証明書 Secret の退避だけは必須

**Option B: 段階移行**
`.skip` による k3s auto-deploy の無効化 → Argo CD 側で同一リソースを採用 → 元マニフェストを除去、の順で1コンポーネントずつ移す。

- ✅ 各段階でロールバックでき、失敗時の切り分けが容易
- ❌ 手順が長く、コンポーネント数ぶん繰り返す
- ❌ `.skip` の挙動検証（Research 4）が前提になる

**Option C: ApplicationSet の統合のみ先行**
所有権の分裂だけ先に解消し、経路の統合は後続にする。

- ✅ 影響範囲が小さく、R13 の前提を先に整えられる
- ❌ Requirement 12 は未達のまま残る

### WS-5. Proxmox 更新自動化 — Requirement 11

**Option A: 新規 `unattended_upgrades` ロール + 専用 playbook**
汎用ロールとして作り、`proxmox_nodes` を対象とする playbook を新設して `site.yml` に組み込む。

- ✅ 既存のロール規約に沿い、他ホストへも展開できる
- ✅ C-3 の導線欠如を根本から埋める
- ❌ 新規ファイルが3〜4点増える

**Option B: 既存ロールへの相乗り**
`sssd` や `nfs_client` など既存ロールに設定タスクを追加する。

- ❌ 責務が混ざり、`rule.instructions.md` の責務分離方針に反する

**Option C: playbook 単体で完結**
ロール化せず playbook にタスクを直書きする。

- ✅ ファイル数が最小
- ❌ 再利用できず、複雑化したときにロールへの分割が必要になる

---

## 4. 工数とリスク

停止が許容されるため、可用性維持の手当てが不要になり、WS-4 と削除作業のリスクが下がる。残るリスクは**不可逆なデータ消失**に限定される。

| ワークストリーム | 要件 | 工数 | リスク | 根拠 |
|---|---|---|---|---|
| WS-1 シークレット（Ansible / TF） | R1, R2 | **S** | **Low** | 間接化層が既にあり、置換対象が特定済み。既存 `assert` を流用できる |
| WS-5 Proxmox 更新 | R11 | **S** | **Low** | 既存 apt パターンとロール規約をなぞるのみ |
| リポジトリ衛生 | R5 | **S** | **Low** | `.gitignore` とバージョン固定の修正に閉じる |
| ドキュメント | R6 | **M** | **Low** | ネットワーク図の書き直しを含む。2ファイルで同一内容を保つ必要がある |
| WS-4 経路一本化 | R12 | **M** | **Low** | 停止許容により一括切り替えが可能。残る配慮は C-6 の証明書 Secret 退避のみ |
| gitops-apps 構造整理 | R10 | **M** | **Low** | 意図しない再作成が起きても停止許容下では受容できる |
| WS-3 Cloudflare | R3, R9 | **M** | **Medium** | 未導入ツールの習得を伴う。本番 DNS レコードの消失が外部到達性に直結する点が Medium 要因 |
| WS-2 k8s シークレット | R7 | **L** | **Medium** | 14個の SealedSecret + SOPS の移行。**復号可能なうちに値を吸い出さないと復元不能**。オペレータ選定も未決 |
| 削除作業 | R8, R13 | **M** | **Medium** | 停止は許容されるが、PVC / データベース / バックアップの消失は不可逆。事前退避の要否判断が要る |

**全体**: M〜L / Low〜Medium。停止許容により当初の High 判定は解消した。残るクリティカルパスは **WS-2 のシークレット吸い出し**（復号鍵を失うと復元不能）と **C-6 の証明書保全**。

---

## 5. Research Needed（設計フェーズへ持ち越す調査項目）

1. ~~**Garage の S3 条件付き書き込み対応**~~（解決済）
   Garage は合意アルゴリズムを持たず、設計上 `If-None-Match` による排他を提供しない。加えて自宅環境内に state を置く構成は、Terraform 自身が作成した基盤の上に復旧手段が乗る循環を生む。**HCP Terraform（Free / 実行モード Local）を採用**し、state の保管・ロック・履歴保持を自宅環境の外に置くことで解決した。詳細は `research.md` の決定記録を参照。

2. **Infisical Kubernetes Operator と External Secrets Operator の選定**
   本環境が Infisical 単一バックエンドであること、Argo CD 管理下に置くことを前提とした比較。

3. **cf-terraforming の v5 対応範囲**
   どのリソース種別が `generate` 可能か。Zero Trust / WAF ルールセットの生成品質。未対応分は手書きになる。

4. **k3s auto-deploy の `.skip` 機構の挙動**
   `.skip` ファイル配置で対象リソースを削除せず管理を外せるか。Requirement 12-7 の実現手段として検証が要る。

5. **Argo CD Application の所有権移管手順**
   ApplicationSet 統合時に、既存 Application を削除せず所有権だけ移す方法（`ownerReferences` の付け替え、`preserveResourcesOnDeletion` の活用）。

6. **Proxmox VE における unattended-upgrades の適用範囲**
   `pve-no-subscription` リポジトリのパッケージが対象に含まれるか。Requirement 11-5（対象範囲の明示）に必要。

7. **cloudflared のトンネル切り替え時の無停止性**
   Terraform 管理へ移す際に、既存トンネルを import できるか、再作成が必要か。Requirement 9-6 に関わる。

---

## 6. 設計フェーズへの推奨

### 推奨アプローチ

| ワークストリーム | 推奨 | 理由 |
|---|---|---|
| WS-1 | **Option A**（既存層を拡張） | 差分最小で規約に沿う。新規依存なし |
| WS-2 | **Option A**（Infisical Operator） | 単一バックエンド構成の実態に合致。ただし Research 2 の結論次第 |
| WS-3 | **Option C**（ハイブリッド） | 網羅性を確保しつつ DNS を `for_each` で可読に保てる |
| WS-4 | **Option A**（一括切り替え） | 停止許容により段階移行の利点が薄れる。証明書 Secret の退避のみ行えば単純な手順で足りる |
| WS-5 | **Option A**（新規ロール） | C-3 の導線欠如を埋め、既存規約に沿う |

### 実施順序の指針

停止許容により、可用性を保つための順序制約は外れる。残る制約は**データの不可逆性**と**認証情報の供給依存**の2点のみ。

1. **値の吸い出しを最優先**: 既存シークレット（ansible-vault 5ファイル、SealedSecrets 14個、SOPS）を復号可能なうちに Infisical へ移送する。**復号鍵を失うと復元できない**ため、他のどの作業よりも先に行う
2. **証明書 Secret の退避**: `tls-fickledev-com` を保全する（C-6）
3. **削除対象のデータ退避判断**: aramakisai 系および minio / stalwart / vikunja / tailscale について、残すべきデータの有無を確認する
4. **低リスクの独立作業**: リポジトリ衛生（R5）、Proxmox 更新（R11）— 他に依存しない
5. **シークレット基盤の切り替え**: WS-1（R1, R2）→ WS-2（R7）— WS-3 の認証情報供給元になるため Cloudflare より先
6. **削除**: R8, R13
7. **Cloudflare**: WS-3（R3, R9）
8. **経路一本化**: WS-4（R12）
9. **ドキュメント**: R6 — 全体の確定後

1〜3 は不可逆性への備えであり、着手前に済ませる。4 以降は依存関係の許す範囲で順序を入れ替えてよい。

### 設計フェーズで決めるべき事項

- Kubernetes シークレットオペレータの選定（Research 2）
- パッケージング形式の統一先（Helm / Kustomize のどちらに寄せるか）
- ApplicationSet の統合先（gitops-apps リポジトリ内か、Ansible 配置側か）
- 削除作業の事前退避手順（PVC / データベース / オブジェクトストレージ）
- 経路移行の粒度（コンポーネント単位の移行順序）

---

## 7. 参考

- [Infisical - External Secrets Operator](https://external-secrets.io/latest/provider/infisical/) — ESO の Infisical プロバイダ仕様
- [The Infisical Kubernetes Operator](https://infisical.com/videos/kubernetes-operator-video-page) — Infisical 公式オペレータの CRD 構成
- [External Secrets Operator is paused. What's next?](https://infisical.com/blog/external-secrets-operator-paused) — ESO のメンテナンス状況の経緯
- [Terraform Cloudflare Provider Version 5 Upgrade Guide](https://registry.terraform.io/providers/cloudflare/cloudflare/latest/docs/guides/version-5-upgrade) — v5 のリソース名体系
- [cf-terraforming releases](https://github.com/cloudflare/cf-terraforming/releases) — v5 対応状況
