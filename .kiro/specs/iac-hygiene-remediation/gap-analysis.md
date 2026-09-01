# Gap Analysis: iac-hygiene-remediation

## 1. 調査サマリ

- `my-home-network` は `terraform validate` が通り Terraform 側の足場は健全だが、`ansible-lint` は 23 failures / 3 warnings で、うち 1 件は FATAL (`playbooks/configure_scsi_disk.yml:2` — tasks ファイルを `playbooks/` に置いているため Play として解釈され構文エラー)。`gitops-apps` は `kubectl kustomize` 全 8 ディレクトリ、`helm template` 全 8 チャートが作業ツリー上では成功する。
- CI は `my-home-network/.github/workflows/secret-scan.yml` の 1 本のみ。`terraform validate` も `ansible-lint` も CI では回っていない。`gitops-apps/.github/` は 0 バイトのファイル 1 個で、CI が存在しない。
- 監査結果のうち 4 件に事実誤認があり、要件の前提が変わる。特に「ディスクプロビジョニング 350 行の 3 重管理」は「共通実装 1 本 + 移行済み 1 本 + デッドコード 1 本」であり、作業量が大幅に縮む。
- 是正の実装手段が現構成に存在しない箇所が 3 つある。ApplicationSet のアプリ単位 syncPolicy 制御、`apps/` 配下への共有ライブラリ配置、Terraform から Ansible への値の受け渡し。いずれも足場をゼロから作る必要があり、要件の実現可能性に直結する。
- 最大のリスクは要件 10.1 (全ワークロードへの resources 定義) と要件 1.4 (k3s トークンローテーション)。前者は 3 ノード homelab のスケジューリングを変え、現在 Healthy な 18 Application を壊す方向に働きうる。後者はクラスタ再構成を伴う。

## 2. 実装手段の前提

以下は要件の実現可能性に直結する現状であり、design はこれを前提に組む。

### 2.1 ディスクプロビジョニングの実装は 3 本のうち 1 本のみが共通化の対象

- `ansible/playbooks/configure_scsi_disk.yml` は `disk_item.{name,scsi_address,partition_number,filesystem_type,mount_path}` でパラメタ化された共通実装であり、`ansible/playbooks/setup_agent_storage.yml:15` から `include_tasks` + loop で呼ばれている。
- `ansible/playbooks/setup_minio_storage.yml` が参照する `minio_data_*` 変数は inventory・roles のいずれにも定義がなく、呼び出し元も存在しない。同じ役割は `ansible/inventory/host_vars/k3s-agent-z440/main.yml:8-13` の `agent_data_disks[0]` (name: minio) がカバーする。実行不能であり、削除の対象。
- 共通化を要するのは `ansible/roles/nas/tasks/storage.yml` の 1 本。処理ステップは `configure_scsi_disk.yml` と同一で、差分は「ラベルが固定値 `nas-data`」「有効化ガード `nas_data_disk_enabled` の有無」「`_partition_device` のリセット有無」「ファイルシステム種別からパッケージ名を解決する仕組み (`ansible/roles/nas/tasks/prerequisites.yml:2-9`) を持つ」の 4 点。
- 3 実装すべてに `by-path` シンボリックリンク数が 1 であることの assert と、既存パーティションレイアウトの検証 assert が入っている。要件 6.4 / 6.5 はこの事前条件チェックの保持と中断時の挙動を定める。

### 2.2 namespace 規約の逸脱は 1 箇所

`gitops-apps/apps/cluster-issuer/wildcard-certificate.yaml` は冒頭に、cert-manager の `--cluster-resource-namespace` に依存するため namespace を固定する旨を明記しており、要件 10.8 の「従わない場合はその理由を判別可能にする」を満たす。規約に寄せると ClusterIssuer が機能しなくなるため、是正の対象としない。対象は `apps/common/middlewares.yaml:5` のみ。

### 2.3 `vault.yml` は作業ツリーに実在し git 未追跡

作業ツリーに 5 ファイルが実在し、いずれも `$ANSIBLE_VAULT;1.1;AES256` で暗号化されている。

```
ansible/inventory/group_vars/all/vault.yml
ansible/inventory/host_vars/gitea/vault.yml
ansible/inventory/host_vars/k3s-server/argocd_gitea_vault.yml
ansible/inventory/host_vars/pbs/vault.yml
ansible/inventory/host_vars/vps/vault.yml
```

`.gitignore:26` の `ansible/inventory/**/*vault.yml` にマッチし、git には 1 件も追跡されていない。git 履歴への混入もない。ただし `ansible-lint` はこれらを読もうとして復号失敗 WARNING を 10 本出すため、lint を CI 化する場合は削除か除外が前提になる。

## 3. 確定済みの設計判断

以下は利用者の判断として確定しており、design はこれを前提に組む。

| 論点 | 決定 |
|---|---|
| public リポジトリの git 履歴に残る k3s トークン | `git filter-repo` + force push で履歴から除去し、あわせてトークンをローテーションする。検出をゼロにする手段は値の除去のみとし、許可リストによる除外を用いない |
| `gitops-apps` の `autonomous-parallel-dev-platform` spec との順序 | 本 spec (是正) を先に完了させる。要件 10 が定める品質ガードを、新基盤が従う規約として design の成果物に残す |
| ホストアドレスの単一情報源化 | 一元化は行わない。重複箇所を用途とともに明示し、整合チェックのみを導入する |
| xrayvpn の扱い | 削除ではなく停止する。Kubernetes 側は replicas を 0 にし、あわせて `vps_proxy` のバックエンド経路も無効化する |
| 認証基盤 | Kanidm 単体とする。POSIX 統合は `kanidm-unixd` が担い、LDAPS は外部サービスへの認証の委譲に限って有効にする |

## 4. 現状資産の把握

### 4.1 `my-home-network`

**構成と規約**
- `ansible/ansible.cfg:4` の `roles_path = ./roles:./playbooks/roles`。後者のディレクトリは実在せず未使用。`ansible/roles/` 直下に新規 role を置けば全 playbook から解決できる。
- 既存 role の粒度は「ホスト役割単位」(nas, gitea, pbs, vps_proxy, argocd, sssd, letsencrypt, nfs_client, proxmox_backup, proxmox_unattended_upgrades)。横断的機能を担う role の前例はない。
- `ansible/playbooks/site.yml` が import するのは 8 本。`site.yml:10` でコメントアウトされているのは `k3s.yml` のみ。`argocd.yml` / `sssd.yml` / `fetch-kubeconfig.yml` / `setup_agent_storage.yml` / `setup_minio_storage.yml` は元から登録されていない。
- `k3s.yml` は `tasks` が空だが、`pre_tasks` に join token の assert を持ち `roles: - role: rlex.k3s` を適用する実働 playbook であり、デッドコードではない。
- `refresh_known_hosts.yml` は 8 playbook が import するが、`letsencrypt.yml` / `proxmox_backup.yml` / `proxmox_unattended_upgrades.yml` は import していない。site.yml 経由では先頭の `ping.yml` が 1 回入るため、非対称性は個別実行時にのみ現れる。

**シークレット供給**
- `lookup('env', ...)` は 32 箇所 / 9 ファイル (group_vars/all 10、group_vars/k3s 2、host_vars/gitea 7、host_vars/k3s-server 1、host_vars/pbs 2、host_vars/vps 1、fetch-kubeconfig 1、argocd/defaults 1、proxmox_backup/defaults 7)。命名は UPPER_SNAKE でほぼ統一。例外は `ansible/inventory/group_vars/k3s/main.yml:31` のみがフォールバック値を持つ点と、`ansible/roles/proxmox_backup/defaults/main.yml:2-5,38-40` が `group_vars/all/main.yml:14-21` と同じ環境変数を二重に読んでいる点。
- 他 31 箇所はフォールバックを持たず、未設定時は空文字として静かに通る。
- `.gitleaks.toml` は 10 行で、`useDefault = true` に k3s node token 検出ルールを 1 つ追加した構成。**allowlist セクションは存在しない**。
- `.pre-commit-config.yaml` は gitleaks v8.24.2 を `--redact --config=.gitleaks.toml` で実行。`.github/workflows/secret-scan.yml:22-27` は上流アクション `gitleaks/gitleaks-action@v2` へ `with: args:` で引数を渡しているが、当該アクションの `action.yml` は inputs を 1 つも宣言しておらず、渡した引数は実行に反映されない。履歴を見ないのは `fetch-depth: 1` とアクション側の既定挙動による。走査範囲の是正は引数の値の変更では成立しない (要件 2.6)。

**k3s トークンの流れ (要件 1.4 の実現可能性に直結)**
- `ansible/roles/rlex.k3s/defaults/main.yml` にトークン系変数は存在しない。role は `tasks/master.yml:28-39` で master 実機の `/var/lib/rancher/k3s/server/node-token` を読み、`set_fact` で `k3s_node_token` を上書きする。
- `templates/k3s.service.j2:8` が agent の systemd unit に `Environment=K3S_TOKEN=...` として平文で書き出す。
- **値のソースは master 実機であり、Infisical の `K3S_NODE_TOKEN` はその写し**。`k3s_initial_master: true` のホストに対しては `master.yml` の set_fact が後勝ちするため env の値は事実上無視される。
- ローテーションに必要な作業は、Infisical の値の更新、master 実機のトークン変更 (Ansible は実施しておらず手段が存在しない)、全 agent の unit 再生成と systemd 再起動。
- 履歴の該当コミットは `76d5bf5` (混入) と `4cfbee2` (除去)。

**Terraform**
- `terraform validate` は成功。`terraform/backend.tf:1-9` は HCP Terraform (`organization = "fickledev"`, workspace `my-home-network`) で init 済み。
- `output` ブロックは 0 個。`local_file` / `template` による inventory 生成もなく、dynamic inventory プラグインの設定もない。**Terraform から Ansible への値の受け渡し機構は存在しない**。
- IP の重複は 4 箇所。`terraform/locals.tf:6-76` が実際に cloud-init で配布する真の源泉。`ansible/inventory/inventory.yml:7-33` はその写し。`group_vars/all/main.yml:24-27` は内部 IP の部分集合。`host_vars/pbs/main.yml` は Terraform 管理外ホスト (mariadb-legacy, mirakurun) を含むため機械生成では置換できないが、同ファイルが既に `source: terraform` / `source: external` を持っており分割キーとして使える。
- `ansible/inventory/group_vars/k3s/main.yml:6,13` が `hostvars[...].ansible_host` を参照する前例を持つ。

### 4.2 `gitops-apps`

**ApplicationSet の制約 (要件 10.7 / 10.9 に直結)**
- `apps/argocd/applicationset.yaml` は git directory generator 1 個で `apps/*` を走査。`exclude` の定義は**存在しない**。
- したがって `apps/common/` と `apps/base/` も通常の Application として生成され、`CreateNamespace=true` により namespace `common` / `base` が作られる。**`apps/` 配下に共有ライブラリ的ディレクトリを置くと必ず Application 化される**。回避手段は現構成にない。
- クラスタ上には `apps` と `gitops-apps` の 2 つの ApplicationSet が稼働しており、いずれも同一リポジトリの `apps/*` を同一の `{{path.basename}}` テンプレートで走査している。要件 21.13 が定める重複はこれを指す。`gitops-apps/argocd/mailu-application.yaml` は `apps/*` の走査対象外であり、クラスタ上に対応する Application を持たない未適用の残骸である。
- **アプリごとに syncPolicy を変える手段が現構成にない**。matrix / merge generator は未使用、`goTemplate` は未有効、path 内の設定ファイル読み込みもない。ApplicationSet がマニフェスト本文へ値を注入する経路も存在しない (generator が渡すのは `path` と `path.basename` のみ)。
- `Prune=false` などの sync-options アノテーションの使用は **0 件**。永続データを持つ garage PVC、postgres の CNPG Cluster、xrayvpn PVC、minecraft PVC のすべてが `prune: true` + `selfHeal: true` の対象。

**共通化の足場**
- `apps/common/` は Traefik Middleware 1 個のみ。参照側 (`apps/kubernetes-dashboard/ingress.yaml:11`, `apps/home-assistant/values.yaml:16`) は文字列 `argocd-local-whitelist@kubernetescrd` による間接参照で、kustomize / helm の依存関係ではない。
- `apps/base/` は StorageClass 1 枚のみで `kustomization.yaml` を持たない。参照は `apps/mailu/values.yaml:51` のみ。他は `local-path` を直指定しており不統一。
- Kustomize の `components:` および base+overlay パターンは**使われていない**。8 個の kustomization はすべてフラットな `resources:` 列挙。patch の使用は `apps/mailu/kustomization.yaml:11` の deprecated な `patchesStrategicMerge` のみ。
- `_helpers.tpl` を持つのは `apps/garage/` のみ。authentik-fickledev と minecraft-bedrock はラベル生成をベタ書きしている。

**Infisical シークレット同期**
- 7 ファイルすべてで `infisicalAuthRef` (`infisical-machine-identity` / namespace `infisical-operator`)、`sources` (projectId, environmentSlug `prod`, secretPath `/`)、`syncOptions` (`refreshInterval: 1m`)、`targets[].kind` / `creationPolicy` / `template.engineVersion` が一字一句同一。**projectId は 7 箇所にハードコードされている**。
- 差分は実質 targets の name / namespace と template.data のキー写像のみ。`secretType: Opaque` は authentik のみ欠落。
- 認証は**クラスタ全体で共有**。`apps/infisical-operator/templates/infisical-auth.yaml` が `InfisicalAuth` を 1 個だけ作り、全 InfisicalStaticSecret がそれを指す。ブートストラップ用の Secret は手動投入。
- 共通化の受け皿として実現可能なのは Helm chart 化と Kustomize replacements の 2 つ。ApplicationSet の template パラメータによる注入は**不可**。

**mailu の実態**
- `apps/mailu/` に `Chart.yaml` も `charts/` も存在しない。`values.yaml` は参照元チャートを失った孤児。
- ArgoCD が管理する実リソースは 6 個のみ (`ConfigMap/unbound-config`, `Service/mailu-front`, `Service/unbound`, `Deployment/unbound`, `Certificate/mailu-certificates`, `Ingress/mailu`)。mailu 本体の Pod はゼロで、稼働中は unbound 1 Pod のみ。`Service/mailu-front` は backing Pod を持たず、`Ingress/mailu` は実質 502。
- `argocd/mailu-application.yaml` は**適用されていない**。クラスタ上の `mailu` Application の `ownerReferences` は ApplicationSet `apps`。「同名 Application の二重定義」は、片方が未適用のファイル残骸である状態。
- 個別 Application 定義は 3-source 構成 (upstream Helm `mailu 2.6.3` + `$values` ref + `path: apps/mailu`) で `ignoreDifferences` を持つのに対し、ApplicationSet 生成分は `apps/mailu` を kustomize としてのみビルドする。syncPolicy は両者同一。
- **`pvc/redis-data-mailu-redis-master-0` (8Gi, Bound) は ArgoCD の管理リソース一覧に存在しない**。ディレクトリを削除しても prune の対象外で、orphan PV ごと残る。要件 5.7 の手動除去は選択肢ではなく必須パス。
- `Certificate/mailu-certificates` は現役の Let's Encrypt 証明書。削除で ACME レート制限には触れないが、DMS 移行時に再取得が要る。
- **TLS の連鎖破壊は起きない**。`tls-fickledev-com` は全 23 namespace に存在するが正は `cert-manager/wildcard-fickledev-com` で、mailu namespace のものは Reflector による複製。
- 他アプリから mailu を参照している箇所はない。

**イメージとバージョン**
- `latest` タグは 5 箇所 (`teddysun/xray`, `ghcr.io/mhsanaei/3x-ui`, `bitnami/kubectl`, `ghcr.io/goauthentik/server`, `khairul169/garage-webui`)。digest 指定は 0 件。可変タグ (`nginx:stable-alpine`, `redis:7-alpine`) が 2 件。
- dependencies を持つ chart は 5 つ (cert-manager, home-assistant, infisical-operator, reflector, reloader)。`Chart.lock` と `charts/*.tgz` は 5 つとも**未追跡**。`.gitignore` は `.aider*` の 1 行のみなので、ignore されているのではなく単に commit されていない。
- **クリーンクローンでは依存を持つ 5 chart の `helm template` がすべて失敗する** (依存未取得エラー。テンプレート構文の問題ではない)。`helm dependency build` は正常に通るため、リポジトリの到達性に問題はない。

## 5. Requirement-to-Asset Map

タグの意味 — **Missing**: 実装手段が現構成に存在せず新規に作る必要がある / **Unknown**: 設計フェーズで調査が必要 / **Constraint**: 既存構成が実現方法を制約する / **Ready**: 既存資産の延長で実装できる

| 要件 | 既存資産 | ギャップ |
|---|---|---|
| 1.1-1.3 平文シークレット除去 | Infisical Operator がクラスタ全体で稼働、InfisicalStaticSecret の前例 7 件 | **Ready**。authentik は chart 内テンプレートで既に Infisical 参照を持つため、平文 env をそこへ寄せるだけ |
| 1.4-1.8 k3s トークンローテーションと履歴書き換え | rlex.k3s は master 実機からトークンを読むのみ。変更する手段を持たない | **Missing**。master 側のトークン変更手順が存在しない。加えて履歴書き換え (filter-repo) の手順も新規 |
| 2.1-2.5 スキャン範囲 | gitleaks は pre-commit と CI の両方で稼働。`.gitleaks.toml` に k3s トークン検出ルールあり | **Ready**。`--no-git` と `fetch-depth: 1` の除去のみ。履歴書き換えを先行させれば許可リストは不要 |
| 3.1-3.8 安全でない既定値 | Terraform の variable 定義、gitea role の defaults、各マニフェスト | **Ready**。ただし 3.5 / 3.6 は「必要性の根拠」の判断を要する (**Unknown**) |
| 4.1-4.2 未参照マニフェスト | `apps/xrayvpn/` の 13 ファイル中 8 が未参照。クラスタ上の稼働は `xrayvpn` Deployment 1 Pod + NodePort Service のみで、x-ui 系は一切動いていない。`x-ui-pvc.yaml` は未適用のため PVC の実体もない | **Ready**。停止の決定により、未参照 8 ファイル (x-ui 系 7 個 + 旧世代の `xray-configmap.yaml`) は削除で確定。要件 1.3 の平文 UUID も同時に解消する |
| 4.3-4.4 garage の破損 | chart 内に Service `garage-dashboard` が存在しない | **Ready**。Service 追加かダッシュボード撤去かの選択 |
| 4.5-4.6 haproxy メール経路 | 未定義変数依存で常に空レンダリング | **Ready**。mailu 撤去 (要件 5) と同時に削除する |
| 4.7-4.9 Terraform ignore_changes | `vm` / `container` モジュール | **Constraint**。`ignore_changes` を外すと次回 apply で既存リソースへの差分が出る。適用前に plan で影響を確定させる必要がある |
| 4.10 frontier の不整合 | inventory.yml と nas role | **Ready** |
| 4.12 collection 依存 | 宣言ファイルが存在しない。README と steering の両方が参照している | **Missing**。`ansible/collections/requirements.yml` を新規作成 |
| 4.13-4.14 rlex.k3s | in-tree と galaxy の二重定義 | **Unknown**。in-tree 版にローカル改変があるかの確認が必要 |
| 5.1-5.7 mailu 撤去 | ArgoCD 管理リソース 6 個 + 管理外の orphan PVC 1 個 | **Constraint**。`prune: true` により削除は自動で進むが、orphan PVC は手動除去が必須 |
| 6.1-6.6 ディスク共通化 | `configure_scsi_disk.yml` が既に共通実装 | **Ready** (2.1 の訂正により大幅に縮小)。role 化すれば ansible-lint の FATAL も同時に解消 |
| 6.7-6.15 その他の重複 | 各 role / chart | **Ready**。ただし 6.10 は authentik chart に `_helpers.tpl` を新設する必要がある |
| 7.1-7.3 IP の重複と整合チェック | Terraform output も dynamic inventory も存在しない | **決定により緩和**。整合チェックの実装手段は **Missing** (新規スクリプト + CI) |
| 7.4-7.5 Terraform 側の値 | locals.tf | **Ready** |
| 7.6-7.7 gitops 側の値 | Helm は values 化済み、Kustomize は直書き | **Constraint**。ApplicationSet がパラメータを注入できないため、Kustomize 側の変数化には configMapGenerator + replacements の足場が要る |
| 7.8-7.9 Gitea URL | `my-home-network` と `gitops-apps` の計 7 箇所 | **Constraint**。`gitops/apps/gitops-apps-set.yaml` は ArgoCD が読む生の YAML で変数化できない |
| 7.13-7.14 storageClass 統一 | `apps/base/storageclass-standard.yaml` が `standard` を定義するが利用は mailu のみ | **Ready**。mailu 撤去後、`standard` の存在意義そのものを判断する |
| 8.1-8.18 冪等性とエラー処理 | 各 role | **Ready**。ただし 8.8 は `community.crypto` collection の追加を伴う (4.12 と連動) |
| 9.1-9.14 デッドコード除去 | — | **Ready** |
| 10.1-10.3 品質ガード | 前例が upstream vendoring 分のみ | **Constraint**。3 ノード homelab で requests/limits を入れるとスケジューリングが変わる。実測に基づく値の決定が必要 (**Unknown**) |
| 10.4-10.5 タグ固定 | — | **Ready** |
| 10.6 Chart.lock | 5 chart 分が未追跡 | **Ready**。`.gitignore` に `charts/` を追加し `Chart.lock` を commit |
| 10.7 prune 保護 | アノテーションの使用実績ゼロ、ApplicationSet に例外機構なし | **Missing**。アプリ単位の制御手段そのものを作る必要がある |
| 10.9-10.10 定義方式の統一 | 6 パターンが混在 | **Unknown**。統一の是非と基準を design で決める |
| 11.1-11.4 ドキュメント同期 | — | **Ready** |
| 11.5-11.10 steering 同期 | 両リポジトリの steering が実態と乖離 (exclude の記述、collections/requirements.yml、ワークロード一覧) | **Ready** |
| 12.1-12.4 段階適用 | — | **Ready** |
| 12.5-12.9 検証と CI | terraform validate は通る。ansible-lint は 23 failures。gitops-apps は CI ゼロ | **Missing**。CI の新規構築。ansible-lint を通すには vault.yml の扱いを決める必要がある |
| 12.10-12.11 切り戻し | `prune: true` + `selfHeal: true` | **Constraint**。git revert でマニフェストは戻るが、prune 済み PVC のデータは戻らない。「切り戻せる」の定義が未確定 (**Unknown**) |

## 6. 実装アプローチの選択肢

### 6.1 ディスクプロビジョニングの共通化

**Option A: `configure_scsi_disk.yml` を新規 role `storage_disk` に昇格させる**

`ansible/roles/storage_disk/tasks/main.yml` + `defaults/main.yml` を作り、`nas` role からは `include_role` + loop で `disk_item` を渡す。`nas_data_*` 変数は `disk_item` へマップする。`setup_minio_storage.yml` は削除。

- 利点: `playbooks/` に tasks ファイルを置く構造が解消され、ansible_lint の FATAL が同時に消える。呼び出し側 2 箇所が同一インタフェースになる。新規 role 1 個・削除 1 ファイルで完結する。
- 欠点: 既存 role がすべて「ホスト役割単位」であるのに対し、横断的機能 role という新しい粒度を持ち込む。`ansible/roles/nas/tasks/prerequisites.yml` が持つファイルシステム種別からパッケージ名を解決する仕組みを role 側へ移すか、呼び出し側に残すかの判断が要る。

**Option B: `configure_scsi_disk.yml` を `ansible/playbooks/tasks/` などへ移し、tasks ファイルのまま共有する**

- 利点: 変更が最小。role という新しい粒度を持ち込まない。
- 欠点: `include_tasks` のパス解決が呼び出し元からの相対になり脆い。ansible-lint の FATAL が解消されるかは配置次第で、role 化ほど確実でない。

**Option C: `nas` role に吸収し、`setup_agent_storage.yml` からも `nas` role を部分的に呼ぶ**

- 利点: 新規 role を作らない。
- 欠点: `nas` role が NAS 以外のホストからも呼ばれることになり、1 role = 1 コンポーネントの原則が崩れる。推奨しない。

**推奨: Option A。** ansible-lint の唯一の FATAL を同時に解消できる点が決め手。

### 6.2 ApplicationSet のアプリ単位制御 (要件 10.7 / 10.9)

**Option A: ApplicationSet に `exclude` を追加し、特殊な扱いが要るアプリを個別 Application として切り出す**

`apps/argocd/applicationset.yaml` の generator に `exclude: true` のパスを追加し、`apps/base` `apps/common` および永続データを持つアプリを ApplicationSet の対象外にする。個別 Application は `argocd/` 配下に置く。

- 利点: ArgoCD の標準機能のみで実現できる。steering の既存記述 (exclude されている前提) とも整合する。`argocd/mailu-application.yaml` という前例がある。
- 欠点: 個別 Application は ApplicationSet が管理しないため、手動適用が必要になり GitOps から外れる。管理対象が二系統になる。

**Option B: リソース単位で `argocd.argoproj.io/sync-options: Prune=false` アノテーションを付ける**

永続データを持つリソース (PVC、CNPG Cluster) にのみアノテーションを付け、ApplicationSet は一律のままにする。

- 利点: ApplicationSet を変更しない。保護対象が宣言的にマニフェスト側へ書かれるため、どのリソースが保護されているかがコードから読める。管理系統は 1 つのまま。
- 欠点: syncPolicy そのものは変えられないため、要件 10.9 (定義方式の統一) の解決にはならない。アノテーションの付け漏れは検知できない。

**Option C: matrix generator + path 内の設定ファイルでアプリ単位のパラメータを渡す**

- 利点: 一般解になる。将来アプリが増えても機構が効く。
- 欠点: ApplicationSet の構成が大きく変わり、全 18 Application に影響する。homelab の規模に対して過剰。

**推奨: Option B を主、Option A を `apps/base` / `apps/common` の Application 化解消にのみ限定して併用。** 要件 10.7 が求めるのは「永続データの誤削除に対する防御」であり、Option B がそれを最小の変更で満たす。Option A を全面採用すると GitOps から外れる Application が増え、mailu で起きた「未適用のファイル残骸」を再生産する。

### 6.3 Infisical 定義の共通化 (要件 6.11 / 7.5)

**Option A: projectId と authRef のみを 1 箇所へ寄せ、7 ファイルの構造はそのまま残す**

Kustomize 側は configMapGenerator + replacements、Helm 側は values の共通キーで projectId を参照する。

- 利点: ディレクトリ形式の変更を伴わない。要件 7.5 (projectId の単一情報源化) を満たす。
- 欠点: `infisicalAuthRef` / `syncOptions` の重複は残る。要件 6.11 の「共通する構造を単一の定義として共有する」を完全には満たさない。

**Option B: InfisicalStaticSecret を生成する共通 Helm chart を作り、全アプリがそれを依存に持つ**

- 利点: 重複が完全に消える。
- 欠点: kustomize 管理の cloudflared / xrayvpn / postgres を chart 化する必要があり、3 アプリのディレクトリ形式変更を伴う。`apps/` 配下に共有 chart を置くと ApplicationSet に Application 化されるため、リポジトリ外か `apps/` 外への配置が要る。

**推奨: Option A。** Option B は要件 10.9 (定義方式の統一) と同時に扱うべき話であり、単独で進めると手戻りになる。

### 6.4 IP 重複の整合チェック (要件 7.1、決定により緩和)

**Option A: `scripts/` に整合チェックスクリプトを新設し、CI で実行する**

`terraform/locals.tf` と `ansible/inventory/` の IP を突き合わせ、不一致を検出する。`host_vars/pbs/main.yml` の `source: terraform` / `external` フィールドを分割キーとして使い、Terraform 管理外ホストを除外する。

- 利点: ブラスト半径ゼロ。既存の構造 (`source` フィールド) をそのまま使える。
- 欠点: スクリプトの保守が要る。`locals.tf` を HCL としてパースする必要がある (`terraform` コマンド経由か、単純な正規表現か)。

**Option B: ドキュメントに重複箇所の一覧を残すだけで、チェックは行わない**

- 利点: 実装ゼロ。
- 欠点: 要件 7.1 の「不整合の検知」を満たさない。片方だけ更新される事故は防げない。

**推奨: Option A。** ただしパース方法は design で決める (**Research Needed**)。

### 6.5 CI の構築 (要件 12.5 / 12.6)

**Option A: `my-home-network` に terraform validate + ansible-lint、`gitops-apps` に kustomize build + helm template の workflow を追加する**

- 利点: 両リポジトリで検証が自動化され、要件 12.5 / 12.6 を満たす。`terraform validate` は現状で通るため即座に CI 化できる。
- 欠点: `ansible-lint` は現状 23 failures で、CI をグリーンにするには是正の完了が前提。かつ作業ツリーの vault.yml が復号失敗 WARNING を出すため、削除するか `--exclude` するかの判断が要る。`terraform validate` は HCP Terraform の認証を要するため、CI に token を渡す必要がある (**Research Needed**)。
- `gitops-apps` 側は `helm dependency build` を CI で実行するか、`Chart.lock` + `charts/` を commit するかで挙動が変わる。要件 10.6 は前者を選ぶ形になっている。

**Option B: 段階的に導入する。まず `gitops-apps` の kustomize build + helm template のみ、`my-home-network` の ansible-lint は是正完了後**

- 利点: CI が最初からグリーンになる。是正の進捗を CI で守れる。
- 欠点: 是正期間中の `my-home-network` は自動検証がないまま。

**推奨: Option B。** ansible-lint を先に入れると赤い CI が常態化し、警告が無視される状態を作る。

## 7. 工数とリスク

| 領域 | 工数 | リスク | 根拠 |
|---|---|---|---|
| 要件 1 (シークレット除去) のうち 1.1-1.3 | S | Low | Infisical の前例が 7 件あり、パターンをなぞるだけ |
| 要件 1.4-1.6 (k3s トークンローテーション + 履歴書き換え) | M | **High** | master 実機のトークン変更手段が存在せず、クラスタ再構成を伴う可能性。force push は全 commit hash を変える |
| 要件 2 (スキャン範囲) | S | Low | 引数 2 つの変更。履歴書き換え後なら許可リストも不要 |
| 要件 3 (安全でない既定値) | S | Medium | 3.1 の TLS 検証有効化は Proxmox 証明書が自己署名の場合に apply が止まる |
| 要件 4 (破損コード) のうち 4.7-4.9 | M | **High** | `ignore_changes` の除去は稼働中 VM への差分を生む。plan での事前確認が必須 |
| 要件 4 のその他 | S | Low | 削除と修正が中心 |
| 要件 5 (mailu 撤去) | S | Medium | ArgoCD 管理リソースは 6 個のみで撤去自体は軽い。orphan PVC の手動除去を落とすと残骸が残る |
| 要件 6 (重複の共通化) | S | Low | 2.1 の訂正により大幅縮小。role 化 1 個 + 削除 1 本 + 各 role の小規模な整理 |
| 要件 7 (ハードコード) | M | Low | 決定により一元化を回避。整合チェックスクリプトの新規作成が主 |
| 要件 8 (冪等性とエラー処理) | M | Medium | 対象タスクが多い。8.8 は collection 追加を伴う。挙動変更を含むため各 role の再実行検証が要る |
| 要件 9 (デッドコード除去) | S | Low | 削除のみ。ただし要件 9.9 のローカル state 削除は HCP Terraform への移行完了確認が前提 |
| 要件 10 のうち 10.1-10.3 | M | **High** | 3 ノード homelab で requests/limits を入れるとスケジューリングが変わり、現在 Healthy な 18 Application を壊しうる |
| 要件 10 のうち 10.4-10.6 | S | Medium | `latest` の固定はイメージ更新の停止を意味する。現行の稼働バージョンを実機から確定させる必要がある |
| 要件 10.7 (prune 保護) | S | Low | アノテーション付与のみ |
| 要件 10.9-10.10 (定義方式の統一) | L | Medium | 6 パターンの混在を整理する。cnpg-operator の 18,000 行 vendoring をどうするかを含む |
| 要件 11 (ドキュメント同期) | S | Low | 記述の修正のみ |
| 要件 12 (段階適用と CI) | M | Medium | CI の新規構築。HCP Terraform の認証を CI に渡す方法が未確定 |
| 要件 13 (xrayvpn 停止) | S | Low | PVC が存在せずデータ保全の考慮が不要。replicas の変更と `host_vars/vps` からのバックエンド除去のみ |
| 要件 14 (クラスタ孤児の除去) | S | Medium | 対象は 4 種。sealed-secrets の CRD 削除のみ不可逆で、単独適用と事前確認を要する |
| 要件 15 (エッジ証明書の再建) | M | **High** | 公開配信が停止中で復旧が最優先。Origin CA と ACME の 2 機構を併用し、割り当てとロールのテンプレート化を同時に確定させる |
| 要件 16 (エッジ実機と定義の整合) | M | **High** | エッジホストは唯一生きている公開経路の終端で切り戻し手段がない。適用でメール 6 ポートの待受が消えるため mailu 撤去と同一適用に束ねる |
| 要件 17 (ホスト到達性の回復) | M | **High** | 4 ホストが全ての手持ち鍵で認証を拒否する。コンソール経由でも回復しない場合は当該ホストが検証対象から外れ、要件 19 の着手も止まる |
| 要件 18 (死蔵ストレージの解放) | S | Medium | 500GB の解放は 4 箇所の同時撤去。孤児ディレクトリは対応リソースの不在確認のみ |
| 要件 19 (定期実行とバックアップ) | M | **High** | 修復ではなく再構築。成功したバックアップが一度も存在せず、PBS への到達性回復が前提。段階 1 の不可逆な削除がこの完了を待つ |
| 要件 20 (シークレット棚卸し) | S | Medium | 参照ゼロが 7 件、参照先不在が 2 件。エッジの平文認証情報はローテーション不可で残存リスクの記録に留まる |
| 要件 21 (重複制御機構の解消) | M | Medium | 対象が 12 項目に分散。CRD の削除判断と StorageClass の除去が他要件と順序で結合する |
| 要件 22 (静的品質ゲートの拡張) | S | Low | 除外設定後の指摘は 148 件で大半が機械的修正。リポジトリ設定の変更を含む |
| 要件 23 (リポジトリ資産の整理) | S | Low | 枝 2 本と空リポジトリ 2 件の除去。spec の追跡開始は段階 3 の完了待ち |
| 要件 24 (portfolio の Workers 移設) | L | **High** | 静的エクスポートへの切り替え、Worker の新規実装、デプロイ経路の置換、DNS の切り替え、旧 LXC の除去が連鎖する。公開サイトの配信断に直結する |

**全体: XL (3-4 週間相当)。リスク High が 8 領域。**

要件 15 / 16 / 17 / 19 は段階 0 から段階 1 の前提条件として直列に連なる。ここが最長経路であり、全体の工数はこの直列部分に支配される。

## 8. Research Needed

design フェーズで解決が必要な未確定事項。

1. **k3s トークンのローテーション手順**。master 実機のトークンをどう変更するか。k3s のバージョンによっては `k3s token rotate` が使えるが、agent の再参加が必要かとダウンタイムの実測が未確認。Ansible から実施する手段を新設するか、手動手順として文書化するかも未決定。
2. **`git filter-repo` の適用範囲**。トークンが混入したファイルは `ansible/inventory/host_vars/k3s-server/main.yml` のみか、他のパスにも波及していないか。force push 後に GitHub 側の unreferenced object が残る点への対応 (support 依頼の要否)。
3. ~~**`xrayvpn` の稼働構成の確定**~~ — 解決済み。稼働は `xrayvpn` Deployment 1 Pod + NodePort Service (`443:32080`, `8000:32206`) のみ。x-ui 系は一切動いておらず PVC の実体もない。停止の決定により未参照 8 ファイルは削除で確定した。残る確認事項は、NodePort 32080 を参照している VPS 側の設定 (`ansible/inventory/host_vars/vps/main.yml:14-22` の `xray_vpn_backend`) を無効化した際に、`vps_proxy` の nginx / haproxy 設定が正しくレンダリングされるか。
4. **resources 値の決定方法**。現在の実使用量をどう測るか (metrics-server の有無、`kubectl top` の可否)。requests を入れた際の 3 ノードへの配置変化の見積もり。
5. **`ignore_changes` 除去時の差分**。`terraform plan` を実行して、`disk` と `user_account` を無視しなくした場合に既存 VM / LXC へどのような差分が出るかを事前に確定させる。再作成が発生するなら要件 4.7 / 4.8 の実現方法を変える必要がある。
6. **Proxmox API の証明書**。要件 3.1 で TLS 検証を有効化した際に、Proxmox 側の証明書が検証を通るか。自己署名なら CA の配布か例外設定が要る。
7. **`rlex.k3s` の in-tree 版のローカル改変の有無**。galaxy 版との差分を取り、改変があるなら in-tree を正とするか、パッチとして分離するかを決める。
8. **HCP Terraform の認証を CI に渡す方法**。`terraform validate` を CI で回すために必要な token の管理方法。Infisical から供給するか GitHub Secrets を使うか。
9. **「切り戻せる」の定義** (要件 12.7)。マニフェストの復元までを指すのか、prune 済みデータの復元までを含むのか。後者なら削除系タスクの前段にバックアップ手順が必要になる。
10. **要件 10.9 の統一方針**。6 パターンの混在をどこまで統一するか。cnpg-operator の 18,000 行 vendoring を Helm dependency へ移すかどうかを含む。

## 9. 設計フェーズへの推奨

**優先アプローチ**

要件 12.1 が定める適用順序 (セキュリティ → 破損コード → mailu → 重複 → 残り) は分類順であってリスク順ではない。実際にはリスク High が要件 1.4-1.6、要件 4.7-4.9、要件 10.1-10.3 に分散しており、これらを分離した段階設計を推奨する。

具体的には以下の 4 段階。

- **段階 1 (低リスク・即時)**: 要件 2 (スキャン範囲)、要件 9 (デッドコード除去)、要件 11 (ドキュメント同期)、要件 6 (重複の共通化)、要件 5 (mailu 撤去)、要件 13 (xrayvpn 停止)。いずれも削除と修正が中心でロールバックが容易。この段階の完了で `gitops-apps` の CI (kustomize build + helm template) を導入できる。
- **段階 2 (中リスク・検証を伴う)**: 要件 3 (安全でない既定値)、要件 8 (冪等性とエラー処理)、要件 7 (整合チェック)、要件 4 の低リスク項目、要件 10.4-10.7。各 role の再実行検証を伴う。この段階の完了で `my-home-network` の ansible-lint を CI に載せられる。
- **段階 3 (高リスク・単独適用)**: 要件 1.4-1.6 (トークンローテーションと履歴書き換え)、要件 4.7-4.9 (`ignore_changes` の除去)。それぞれ単独で適用し、他の変更と混ぜない。事前に plan / 影響評価を必須とする。
- **段階 4 (規約策定)**: 要件 10.1-10.3、10.9-10.10。`autonomous-parallel-dev-platform` が従うべき規約となるため、成果物として明文化する。

**主要な設計判断**

- ディスクプロビジョニングは新規 role `storage_disk` への昇格を採り、`setup_minio_storage.yml` は削除する。ansible-lint の FATAL 解消を同時に達成する。
- prune 保護はリソース単位のアノテーションで実現し、ApplicationSet の `exclude` は `apps/base` / `apps/common` の Application 化解消にのみ使う。GitOps から外れる Application を増やさない。
- Infisical 定義の共通化は projectId と authRef の集約に留め、chart 化は要件 10.9 と同時に判断する。
- CI は `gitops-apps` から先に導入し、`my-home-network` の ansible-lint は段階 2 完了後に載せる。赤い CI を常態化させない。
- 2 章の訂正と 3 章の決定は requirements.md へ反映済み。要件は 13 本・受入基準 143 件となった。design はこの反映後の requirements.md を入力とする。
