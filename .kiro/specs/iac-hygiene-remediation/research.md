# Research & Design Decisions: iac-hygiene-remediation

## Summary

- **Feature**: `iac-hygiene-remediation`
- **Discovery Scope**: Extension (稼働中の 3 リポジトリに対する是正。Light discovery + 外部依存の的を絞った調査)
- **Key Findings**:
  - `/var/lib/rancher/k3s/server/node-token` は **server token へのシンボリックリンク**であり、現行の Ansible 実装は agent に**クラスタ管理者権限に相当するトークン**を配布している。git 履歴に漏洩した `K10...::server:` 形式の値も server token である。要件 1 の深刻度が想定より高い。
  - `.github/workflows/secret-scan.yml:27` の `args:` 入力は gitleaks-action v2 が宣言していない入力であり、**渡した引数は実行に反映されない**。監査は「`--no-git` のため履歴を見ない」と結論したが、実際の機序は「v2 が push / pull_request では `--log-opts` で差分コミットのみを走査する」ことにある。結論 (履歴が走査されない) は変わらないが、対処方法が異なる。
  - `k3s token rotate` は v1.28.3+k3s1 以降で利用可能で、対象クラスタは v1.35.0+k3s3。ノードの再参加は不要で、新トークンでの再起動のみで足りる。k3s サービス停止中もコンテナは走行を続けるため、ワークロード無停止でコントロールプレーンの一時断のみに抑えられる。
  - ArgoCD の `Prune=false` はリソース側アノテーションが Application 側設定を常に上書きする。`selfHeal: true` が有効でも強制削除は起こらず、prune がスキップされて Application が OutOfSync に留まる。誤削除の防御として意図どおり機能する。
  - PBS のバックアップが 1 件も存在しない原因は、`/etc/pve/storage.cfg` の `pbs: pbs-zfs-pool` に `disable` が設定されていることであると実測で確定した。vzdump ジョブは毎日起動し、両ノードで `storage 'pbs-zfs-pool' is disabled` を出力して失敗し続けている。加えて保存先が保護対象と同じ物理ディスク上にあり、有効化のみでは冗長性を持たない。
  - 要件 18 の 500G の解放は、既存の記述が挙げる 4 箇所の撤去では 1 バイトも空かない。`terraform/locals.tf` の宣言と PVE 上のディスク切り離し・zvol 削除を加えた 6 箇所を要する。増える容量の実体はデータの削除ではなく `refreservation` の返却である。
  - 全 VM のディスクが `discard=ignore` であり、ゲスト内で解放した約 180G が thin pool へ返らずに滞留している。`terraform/modules/vm/main.tf` は `discard` を指定せず、`lifecycle.ignore_changes` に `disk` を含むため定義側から矯正できない。要件 4.7 と同じ根を持つ。
  - `Chart.lock` が存在しない場合、`helm dependency build` は `helm dependency update` と同じ挙動にフォールバックし、依存バージョンが毎回再解決される。ArgoCD repo-server は依存欠落を検出して `dependency build` を自動実行するため、`charts/*.tgz` のコミットは不要だが `Chart.lock` のコミットは再現性のために必要。

## Research Log

### k3s ノードトークンのローテーション

- **Context**: 要件 1.4-1.8。git 履歴に漏洩したトークンをローテーションする必要があるが、現行の Ansible role にトークンを変更する手段が存在せず、実現可能性とダウンタイムが未確定だった。
- **Sources Consulted**:
  - [k3s token CLI](https://docs.k3s.io/cli/token)
  - [ADR: Support Rotating Server Tokens](https://github.com/k3s-io/k3s/blob/master/docs/adrs/server-token-rotation.md)
  - [k3s PR #8265](https://github.com/k3s-io/k3s/pull/8265)
  - [k3s Stopping K3s](https://docs.k3s.io/upgrades/killall)
  - [k3s `pkg/server/server.go`](https://github.com/k3s-io/k3s/blob/master/pkg/server/server.go)
  - [k3s `pkg/daemons/control/deps/deps.go`](https://github.com/k3s-io/k3s/blob/master/pkg/daemons/control/deps/deps.go)
- **Findings**:
  - `k3s token rotate` は v1.28.3+k3s1 / v1.27.7+k3s1 以降で利用可能。対象クラスタは v1.35.0+k3s3 のため利用できる。
  - 公式文言: 「After running this command, all servers and any agents that originally joined with the old token must be restarted with the new token.」ノードの削除・再 join は不要。
  - rotate は bootstrap データを旧トークンで復号し新トークンで再暗号化して `token` ファイルと `passwd` ファイルを更新する。既存 server には再起動時にファイルが伝播する。
  - k3s サービスを停止しても走行中のコンテナは停止しない。したがってワークロードは無停止で、単一 server 構成ではコントロールプレーン API のみが再起動中に一時断となる。
  - トークンは 3 種類ある。Server (`--token` / `K3S_TOKEN`)、Agent (`--agent-token` / `K3S_AGENT_TOKEN`)、Bootstrap (`k3s token create`)。
  - 値の形式は `K10<cluster CA の SHA256>::<username>:<password>` で、`::server:` が server token、`::node:` が agent token に対応する。
  - **`/var/lib/rancher/k3s/server/node-token` は `server/token` へのシンボリックリンクである** (`os.Symlink(serverTokenFile, np)`、コメント `// backwards compatibility`)。公式は server token について「Anyone with access to the server token essentially has full administrator access to the cluster」と明記している。
  - ローテーション前に取得したスナップショットの復元には旧トークンが必要なため、旧トークンは破棄せず保管する必要がある。
- **Implications**:
  - 要件 1.4 は実現可能で、ダウンタイムはコントロールプレーン API の数十秒に限定される。
  - `rlex.k3s` role が `node-token` を読んで agent に配布している構造は、agent にクラスタ管理者権限を与えている。ローテーションと同時に `--agent-token` を導入し、agent には `server/agent-token` を配布する設計とする。これは要件 3 (安全でない既定値の是正) の趣旨に合致する。
  - 旧トークンの保管先は Infisical とし、スナップショット復元用であることを明示する。

### git 履歴からのシークレット除去

- **Context**: 要件 1.6-1.8。public リポジトリの履歴に残るトークンの除去方法と、force push 後に残存する経路の把握。
- **Sources Consulted**:
  - [GitHub Docs: Removing sensitive data from a repository](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
  - [git-filter-repo man page](https://manpages.debian.org/testing/git-filter-repo/git-filter-repo.1.en.html)
- **Findings**:
  - `git filter-repo --replace-text <file>` でファイル削除ではなく文字列置換ができる。式ファイルは 1 行 1 ルールで `探索文字列==>置換文字列` の形式。プレフィックスに `literal:` (既定) / `glob:` / `regex:` を指定できる。`--path` との併用が可能。
  - GitHub 公式は**「シークレットの場合、第一手順として当該シークレットを失効またはローテーションする」**ことを明示している。「once rotated, it can no longer be used for access, and that may be sufficient to solve your problem」。
  - 推奨ツールとして記載されているのは git-filter-repo のみ。BFG は現行ドキュメントに記載がない。
  - force push 後も残るもの: Pull Request 内の参照とキャッシュされたビュー。これらの除去には GitHub Support への依頼が必要。
  - fork が存在すればそこに残り続ける。fork が 0 件でも、書き換え前のクローンを持つ者が push すると復活する (recontamination) 点と、書き換え前のコミット SHA を知る者は直接アクセスできる点を公式が挙げている。
- **Implications**:
  - 実施順序は「ローテーション → 履歴書き換え → 残存経路の確認」とする。ローテーションを先に完了させれば、履歴書き換えが不完全でも実害が残らない。
  - 対象リポジトリの Pull Request の有無を事前に確認し、存在する場合は Support 依頼の要否を判断する。
  - 書き換え後はローカルクローンを再取得し、旧クローンからの push を行わない。

### gitleaks の走査範囲

- **Context**: 要件 2。監査は `--no-git` を原因と特定したが、実際の設定と action の挙動を確認する必要があった。
- **Sources Consulted**:
  - [gitleaks-action v2.3.9 `src/gitleaks.js`](https://github.com/gitleaks/gitleaks-action/blob/v2.3.9/src/gitleaks.js)
  - [gitleaks README](https://github.com/gitleaks/gitleaks)
  - [gitleaks コマンド移行表](https://gist.github.com/zricethezav/b325bb93ebf41b9c0b0507acf12810d2)
- **Findings**:
  - gitleaks-action v2 は引数を内部でハードコードしており、`detect --redact -v --exit-code=2 --report-format=sarif ...` を常に実行する。`--no-git` は付与されない。
  - 走査範囲はイベント種別で決まる。`push` / `pull_request` では `--log-opts=--no-merges --first-parent <base>^..<head>` が付与され差分コミットのみが対象となる。`schedule` / `workflow_dispatch` では `--log-opts` が付かず全履歴が対象になる。
  - `fetch-depth: 0` が必要。浅いクローンでは `baseRef^` が解決できない。
  - gitleaks 本体は v8.19.0 で `detect` / `protect` を deprecated 化し、`git` / `dir` / `stdin` の 3 モードに再編した。現行の安定版は v8.30.1。
  - gitleaks-action の最新は v3.0.0 で、v2 からの変更は `actions/checkout@v6` への更新と Node ランタイムの更新のみ。
  - `GITLEAKS_LICENSE` は Organization 所有リポジトリでのみ必須。個人アカウントのリポジトリでは不要。
- **Implications**:
  - `args:` を書き換えるだけでは目的を達成できない。ワークフローの構成そのものを変える必要がある。
  - 設計は「push / pull_request では差分走査を維持し、`schedule` による全履歴走査ジョブを追加する」方針とする。`fetch-depth: 0` は全履歴走査ジョブに設定する。
  - 実装時に `args:` が実際に無視されているかを検証する手順を設ける。研究結果はソースコードの読解に基づくため、実測で確認する。

### ArgoCD の prune 保護と ApplicationSet の除外

- **Context**: 要件 10.7 / 10.9。永続データを持つリソースを一律 `prune: true` から守る手段と、`apps/base` / `apps/common` が Application 化される問題の解消。
- **Sources Consulted**:
  - [Argo CD Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/)
  - [Argo CD ApplicationSet Git Generator](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators-Git/)
- **Findings**:
  - リソースの `metadata.annotations` に `argocd.argoproj.io/sync-options: Prune=false` を付与する。複数指定はカンマ区切り。
  - リソース側のアノテーションは Application 側の syncPolicy を常に上書きする。
  - `Prune=false` は sync 時の prune を抑止し、`Delete=false` は Application 削除時の cascade delete を抑止する。用途が異なるため、両方守る場合は両方指定する。
  - `selfHeal: true` が有効でも `Prune=false` のリソースが強制削除されることはない。prune がスキップされ、Application は OutOfSync に留まり、その理由が sync-status パネルに表示される。
  - ApplicationSet の git directory generator は同一 `directories` リスト内に `exclude: true` のエントリを置くことで除外できる。除外ルールは包含ルールより優先度が高く、記述順に依存しない。パターンは Go の `path.Match` 構文。
- **Implications**:
  - 要件 10.7 はリソース単位のアノテーションで満たす。Application を ApplicationSet の外へ出す必要はない。
  - 誤削除時の挙動は「削除されず OutOfSync のまま残る」となり、検知可能な形で止まる。これは望ましい挙動である。
  - `apps/base` / `apps/common` は `exclude: true` で ApplicationSet の対象外にする。ただし両者は現在 Application として実在するため、除外は既存 Application の削除を伴う。`apps/base` の StorageClass はクラスタスコープ資源であり、mailu 撤去後に唯一の利用者を失う点と併せて扱いを決める。

### Helm 依存の解決と再現性

- **Context**: 要件 10.6 / 12.7。`Chart.lock` と `charts/` の扱い、クリーンクローンでのレンダリング失敗への対処。
- **Sources Consulted**:
  - [helm dependency build](https://helm.sh/docs/helm/helm_dependency_build/)
  - [Argo CD Helm user guide](https://argo-cd.readthedocs.io/en/stable/user-guide/helm/)
  - [argo-cd `util/helm/cmd.go`](https://github.com/argoproj/argo-cd/blob/master/util/helm/cmd.go)
- **Findings**:
  - ArgoCD repo-server は `helm template` を実行し、依存欠落エラーを検出したときに `helm dependency build` を実行してリトライする。`dependency update` は実行しない。
  - Helm 公式: 「If no lock file is found, `helm dependency build` will mirror the behavior of `helm dependency update`」。つまり lock が無いと依存バージョンが再解決される。
  - ArgoCD 公式ドキュメントには chart dependencies / `Chart.lock` に関する記述がない。明示的な推奨は存在しない。
- **Implications**:
  - `Chart.lock` をコミットし、`charts/` を `.gitignore` に追加する。これにより再現性を確保しつつリポジトリの肥大を避ける。
  - CI での検証は `helm dependency build` を実行してから `helm template` を実行する構成とする。依存リポジトリへの到達性は前提とする。

### ワークロードのリソース設定

- **Context**: 要件 10.1。3 ノードのクラスタに requests / limits を後から導入する際の値の決め方と、スケジューリングへの影響。
- **Sources Consulted**:
  - [Kubernetes: Resource Management for Pods and Containers](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/)
  - [Kubernetes: Autoscaling Workloads](https://kubernetes.io/docs/concepts/workloads/autoscaling/)
  - [VPA quickstart](https://github.com/kubernetes/autoscaler/blob/master/vertical-pod-autoscaler/docs/quickstart.md)
  - [VPA API reference](https://github.com/kubernetes/autoscaler/blob/master/vertical-pod-autoscaler/docs/api.md)
- **Findings**:
  - CPU limit は CPU throttling によりカーネルが強制する。memory limit は OOM kill による事後的な強制である。
  - limit のみを指定し request を省略すると、Kubernetes が limit を request にコピーする。
  - VPA の `updateMode: "Off"` は Pod を再作成せずに推奨値のみを算出し、VPA オブジェクトから参照できる。metrics-server が前提。VPA は Kubernetes 標準同梱ではなく add-on。
  - 対象クラスタでは metrics-server が稼働しており `kubectl top` が機能する。ノードのメモリ使用率は 16-30% で余裕がある。
  - CPU limit の是非について Kubernetes 公式は中立。メンテナの Tim Hockin は「memory limit == request」「CPU limit は設定しない」を推奨している。コミュニティの合意は完全ではない。
- **Implications**:
  - 値の決定は VPA `updateMode: "Off"` による実測を経てから行う。推測値を先に入れない。
  - 方針は「memory は requests == limits、CPU は requests のみ」とする。CPU throttling による遅延を避けつつ、メモリの巻き添え OOM を防ぐ。
  - 要件 10.1-10.3 は測定期間を必要とするため、段階 4 に配置する。

### Ansible の実装手段

- **Context**: 要件 8.8 (証明書の有効期限判定)、要件 4.12 (collection 依存の宣言)、要件 9.14 (lint からの除外)、要件 6.1 (マウントの冪等性)。
- **Sources Consulted**:
  - [community.crypto.x509_certificate_info](https://docs.ansible.com/ansible/latest/collections/community/crypto/x509_certificate_info_module.html)
  - [Ansible: Installing collections](https://docs.ansible.com/ansible/latest/collections_guide/collections_installing.html)
  - [ansible-lint Configuring](https://docs.ansible.com/projects/lint/configuring/)
  - [ansible-lint load-failure rule](https://docs.ansible.com/projects/lint/rules/load-failure/)
  - [ansible.posix.mount](https://docs.ansible.com/ansible/latest/collections/ansible/posix/mount_module.html)
- **Findings**:
  - `x509_certificate_info` の `not_after` は ASN.1 TIME 形式の文字列 (`YYYYMMDDHHMMSSZ`) であり、直接比較できない。`valid_at` パラメータに相対時刻 (`+30d` 等) を与えると真偽値が返る。これが標準的な判定方法。`expired` も返る。
  - `requirements.yml` の `collections:` は `name` / `version` / `source` / `type` / `signatures` を取る。`version` は `>=1.0.0,<2.0.0` のような範囲指定が可能。
  - `ansible-lint` の `exclude_paths` は設定ファイルの位置からの相対パスとして解釈される。Vault 暗号化ファイルの除外は `load-failure` ルールのドキュメントが `exclude_paths` を明示的に案内している。
  - ただし `exclude_paths` に入れても `group_vars` は Ansible 側のロード経路で読まれることがある既知の不具合が報告されている。回避策は `ansible.cfg` に `vault_password_file` を設定する方法。
  - `ansible.posix.mount` の `state: mounted` はマウントと fstab 登録の双方を行い冪等である。`remounted` のみ常に changed を返す。
- **Implications**:
  - 要件 8.8 は `valid_at` を用いた判定として設計する。日付の手計算は不要になる。
  - 要件 9.13 は「作業ツリーの vault.yml を削除する」を第一選択とする。除外設定に既知の不具合があるため、ファイル自体を残さない方が確実。
  - 要件 8.7 は `state: mounted` の冪等性に依存する形とし、事前チェックのタスク自体を削除する。

### 管理対象ホストへの SSH 接続の実態

- **Context**: 要件 17。到達性の回復手段を確定するため、インベントリ上の全ホストに対する接続の成否と、監査が報告した「4 ホストで手持ちの全鍵が拒否される」との食い違いの機序を確定する必要があった。
- **Sources Consulted**: 実機調査 (各ホストへの接続試行、収容元ノード経由での `gitea` / `pbs` の内部確認、鍵の指紋照合)、`ansible/inventory/inventory.yml`、`ansible/inventory/host_vars/`
- **Findings**:
  - `ansible/inventory/inventory.yml` はグループ既定で `ansible_user: tochi` と `ansible_ssh_private_key_file: ~/.ssh/hp-z440` を与え、ホスト単位で `n100` / `hp-z440` / `gitea` / `pbs` に `root`、`vps` に `trvlr` を上書きしている。`host_vars/` および `group_vars/` に接続変数の上書きは存在しない。
  - 接続ユーザーの割当はいずれのホストでも実在するアカウントを指す。`gitea` (LXC 200) と `pbs` (LXC 202) には UID 1000 以上の一般アカウントが 1 つも存在せず `root` のみであるため、この 2 件についても `root` の指定が正しい。
  - **`ansible_ssh_private_key_file` はパスによる指定であり、鍵の同一性を固定しない。** 現在の環境では `~/.ssh/hp-z440` と `~/.ssh/id_ed25519` が同一の ED25519 鍵 (`SHA256:DrwTJvulnr2IpaEcleVndl9mF6b8taV5f/czy83YwoI`) であるが、別の環境では同名のパスが中身の異なる別の鍵へ解決される。
  - 現在の環境では `n100` / `hp-z440` / `nas` / k3s の 3 ノード / `vps` の計 7 ホストが認証に成功する。
  - `gitea` と `pbs` のみ到達しない。両者の `/root/.ssh/authorized_keys` が認可しているのは 4096bit RSA の `musas@DESKTOP-0TS76P5` であり、手元に対応する秘密鍵が無い。
  - `gitea` の収容元は `n100`、`pbs` の収容元は `hp-z440` である。いずれの収容元も `root` で接続でき、`pct exec` によってゲスト内で操作を実行できる。
  - `nas` および k3s の 3 ノードの計 4 ホストで、実機のホスト鍵と `~/.ssh/known_hosts` の登録内容が一致しない。
- **Implications**:
  - 要件 17 の中核は接続変数の是正でも鍵の一括再配布でもなく、**鍵の同一性を固定して到達性を実行環境から独立させること**である。監査の「4 ホスト不通」と現在の「2 ホスト不通」は、同名の別鍵を持つ環境と持たない環境の 2 つの観測であり、非再現性そのものの証跡である。
  - 供給元を Infisical に一本化し、インベントリからパスによる鍵の指定を除去する (要件 17.9 / 17.10) ことが再現性の成立条件となる。
  - 鍵の注入を要するのは `gitea` と `pbs` の 2 ホストに限られる。注入は収容元ノード経由で完結し、仮想化基盤のコンソールへの直接操作を必要としない。段階 0.5 に「本 spec の外の手段を要する可能性」は残らない。
  - 両コンテナが古い RSA 鍵のみを認可している状態は、要件 17.11 の宣言的な適用で解消する。
  - PBS への到達は段階 0.5 の内部で成立するため、要件 19 のバックアップ再構築が段階 0.5 の完了時点で着手可能になる。
  - ホスト鍵の不一致 4 件は要件 8.12 が指す相互無効化の実害である。方針の一本化は既知ホスト情報の更新を伴う。

### 仮想化基盤上の未管理ゲスト

- **Context**: 要件 28、および要件 24.15 が定める旧配信元コンテナの特定。`terraform/locals.tf` の定義と実機のゲストの対応を確定する必要があった。
- **Sources Consulted**: 実機調査 (`n100` および `hp-z440` 上のゲスト一覧と構成の取得)、`terraform/locals.tf`
- **Findings**:
  - `terraform/locals.tf` が定義するのは k3s 3 台 (150 / 151 / 152)、`nas` (201)、`gitea` (200)、`pbs` (202) の 6 件のみ。
  - `n100` 上の未定義ゲスト: LXC 113 (`MariaDB`、192.168.1.100、50G、稼働)、VM 9000 (`debian-12-template`、3G、停止)。
  - `hp-z440` 上の未定義ゲスト: LXC 100 (`ollama`、192.168.1.105、64G、稼働)、LXC 115 (`portfolio`、192.168.1.103、2 cores / 2048MB / rootfs `local-lvm:vm-115-disk-0` 32G、稼働)、VM 105 (`nextcloud`、32G、稼働)、VM 108 (`windows`、停止)、VM 110 (`tv`、128G、稼働)、VM 9001 (`debian-12-template`、3G、停止)。
  - VM 110 の virtio0 は `local-lvm:vm-107-disk-1` を参照する。VM 107 は存在せず、命名だけが残っている。
  - LXC 113 (`MariaDB`) は `ansible/inventory/host_vars/pbs/main.yml` が保持するダンプ用資格情報の対象と対応する可能性がある。
- **Implications**:
  - 要件 24.15 の「旧配信元の LXC」は `hp-z440` 上の LXC 115 と特定される。
  - 残る未定義ゲストのうち 4 件は現に稼働しており、要件 28 は撤去ではなく「定義側に取り込むか管理対象外として明示するか」の決定と記録を求める形とする。
  - 管理対象外と決定したゲストは、要件 7.3 が定めるアドレス整合の判定除外の情報源となる。

### 仮想化基盤のストレージ監査

- **Context**: 要件 18 / 19 / 28。バックアップの失敗原因、解放可能な容量、および仮想化基盤上のストレージの実態が未確定だった。要件 19 の失敗原因は推測に留まっており、要件 18 の解放手順は撤去箇所を網羅していなかった。
- **Sources Consulted**: 実機調査 (`n100` / `hp-z440` 上での `pvesm status`、`lvs`、`zfs list -o space`、`qm config` / `pct config`、`smartctl`、`zpool status`、タスクログの vzdump エントリ、`/etc/pve/storage.cfg`、`/etc/pve/jobs.cfg`、各ゲスト内の `df`)、`terraform/locals.tf`、`terraform/modules/vm/main.tf`、`terraform/variables.tf`、`ansible/inventory/host_vars/pbs/main.yml`、`ansible/inventory/host_vars/k3s-agent-z440/main.yml`、`ansible/playbooks/`
- **Findings**:
  - **PBS のスナップショットは 1 本も存在しない。** データストア `/mnt/zfs-pool-0` の中身は空の `.chunks` (65536 ディレクトリ) と `.lock` のみで実サイズ 41M。
  - 原因は `/etc/pve/storage.cfg` の `pbs: pbs-zfs-pool` に `disable` が設定されていることである。`pvesm status` は両ノードで `disabled` を返す。毎日 04:30 の vzdump ジョブは有効だが、両ノードで `could not activate storage 'pbs-zfs-pool': storage 'pbs-zfs-pool' is disabled` を出力して失敗している。タスクログの vzdump エントリは全件このエラーであり成功実績はゼロ。
  - 保存先 `zfs-pool/subvol-202-disk-0` は保護対象のゲストと同じ 4TB HDD (hp-z440 の `sdc`) 上にある。
  - `/etc/pve/jobs.cfg` の vzdump job の対象は `vmid 202,113,110` の 3 件。`ansible/inventory/host_vars/pbs/main.yml` の `pbs_backup_targets` は 7 件 (150, 151, 152, 201, 202, 113, 110) であり、150 / 151 / 152 / 201 が実機側に存在しない。
  - `host_vars/pbs/main.yml` の `skip_extra_zvol_dataset_disks: true` (152, 201) と `pbs_backup_todo` の「Confirm Proxmox VM disk backup=0 for zvol/dataset disks」は実機に反映されていない。VM 152 の `scsi1` / `scsi2` と VM 201 の `scsi1` はいずれも `backup=1` であり、空の 1500G + 1000G がバックアップ対象に含まれている。
  - **物理ディスク一覧** (全て単発。mirror / raidz / mdadm は存在しない)

    | ノード | デバイス | 型番 | 容量 | 種別 | 稼働時間 | 用途 |
    |---|---|---|---|---|---|---|
    | n100 | sda | ShiJi 512GB | 476.9G | SSD | 3,412h | LVM (`pve` VG 全体) |
    | hp-z440 | sda | WDC WDS100T2B0A | 931.5G | SSD | 18,448h | LVM (`pve` VG 全体) |
    | hp-z440 | sdb | ST2000VN004 | 1.8T | HDD | 20,806h | VM 105 へ raw passthrough |
    | hp-z440 | sdc | ST4000VN006 | 3.6T | HDD | 3,883h | `zfs-pool` (単一 vdev) |

  - 全ディスクの SMART は PASSED で、代替セクタ・保留セクタとも 0。`zfs-pool` の最終 scrub は 2026-06-14 でエラー 0。
  - **thin pool は overcommit していない。** n100 の `pve/data` は 348.82 GiB に対し割当 245.0 GiB (70.2%)、`data_percent` 29.55%、`metadata_percent` 1.43%。hp-z440 は 794.30 GiB に対し 516.0 GiB (65.0%)、`data_percent` 43.44%、`metadata_percent` 1.56%。
  - **真の孤児ボリュームはゼロ。** `pvesm list` が返す全ボリュームが `qm config` / `pct config` から参照されている。**スナップショットの滞留もゼロ** (ZFS、LVM thin、全ゲストの `listsnapshot` のいずれも 0 件)。
  - **zvol の予約と実使用**: `zfs-pool/vm-152-disk-0` は 500G (`refreservation` 508G) に対し実ファイル 0 件、実データ 90.9M〜188M。`zfs-pool/vm-152-disk-1` は 1000G (`refreservation` 1016G) に対し実ファイル 0 件。前者の削除で `zfs-pool` の AVAIL は 1.03T から約 1.53T になる。増分の実体は予約の返却である。
  - **`discard=ignore` による thin pool の滞留は約 180G。** 全 VM のディスクが `discard=ignore` (VM 105 / VM 110 は指定自体がなく既定の `ignore`)。VM 152 は 128G 割当に対し thin 実割当 123.3G (96.30%) でゲスト内 `df` は 17G。VM 150 は 64G に対し 61.4G (95.95%) / 23G。VM 110 は 128G に対し 124.1G (96.99%)。VM 105 の root は 32G に対し 30.4G (94.85%) / 16.3G。LXC 側 (CT 113 / 200 / 100 / 115 / 202) にこの問題は生じていない。
  - **割当過大**: CT 113 (50G / 実使用 1.3G)、CT 200 (64G / 2.6G、実データは NFS 上)、VM 201 (64G / 1.9G)、CT 202 (64G / 5.0G)。
  - `local-lvm:vm-110-disk-0` は 1G で thin 割当 0.00%。VM 110 の `unused0` として参照されているため孤児判定されないが実質は空。`local-lvm:vm-107-disk-1` は 128G / thin 割当 124.1G で、孤児ではなく VM 110 の `virtio0` として稼働中の起動ディスクである。
  - VM 108 (`windows`) は OS ディスクの定義自体を持たず `tpmstate0` 4M のみ。`boot: order=hostpci0;ide0;net0` による GPU パススルーと ISO 起動の構成。`local:iso/*` が約 11G を占める (Windows10 4.9G / ubuntu-desktop 3.4G / ubuntu-server 2.1G / virtio-win 724M)。
  - テンプレート 9000 / 9001 は `lv_attr` が `Vri---tz-k` であり thin の `data_percent` に計上されない。実占有はほぼ 0。
  - 孤児ディレクトリは 6 件、いずれも `/var/lib/rancher/k3s/storage/` 配下で合計約 42.3M。うち 5 件が `k3s-agent-z440` (`budibase_database-storage-budibase-couchdb-0` の 3 件で合計 1.2M / 2026-04-05、`appflowy_postgres-pvc` 41M / 2026-03-08、`appflowy_redis-pvc` 8.0K / 2026-03-08)、**1 件が `k3s-server`** (`appflowy_redis-pvc` 8.0K / 2026-03-08)。`budibase` / `appflowy` の名前空間も PV も存在しない。
  - **`/var/lib/minio` を作ったのは `setup_agent_storage.yml`** が `host_vars/k3s-agent-z440/main.yml` の `agent_data_disks[0]` を反復した結果である。`setup_minio_storage.yml` は `minio_data_*` 変数がどこにも定義されておらず呼び出し元も持たない、実行実績のないデッドコードである。
  - `terraform/modules/vm/main.tf:52-66` の `dynamic "disk"` は `local.zfs_pools_map` のリスト位置から `interface = format("scsi%s", tostring(tonumber(disk.key) + 1))` を導出する。`main.tf:112` の `lifecycle.ignore_changes` には `disk` が含まれる。
  - `terraform/variables.tf:134-138` の `zfs_pool_sizes` は `map(any)` / default `{}` で、どこからも参照されず tfvars にも存在しない。
  - VM 105 (nextcloud) のパススルー HDD (`/dev/sdb`) 上に Nextcloud の実データ 666GB が存在する。当該ゲストは `zfs-pool` にも `terraform/locals.tf` にも定義を持たず、vzdump ジョブの対象にも含まれていない。
- **Implications**:
  - 要件 19 の中核は「継続的な失敗の原因究明」ではなく**保存先ストレージの無効化の解消**であり、原因は実測により確定した。加えて、有効化だけでは保護対象と成果物が同一の物理ディスク上に並ぶ状態が残るため、保存先の物理分離を要件 19.15 として明示する。
  - 実機のジョブ定義とインベントリの対象集合が一致しないため、情報源をインベントリに一本化する (要件 19.16)。空の zvol の除外はインベントリ上に宣言済みで実機に未反映であるため、反映を要件 19.17 とする。
  - 要件 18 の撤去箇所は 4 箇所では不足であり、`terraform/locals.tf` の宣言と PVE 上のディスク切り離し・zvol 削除を加えた 6 箇所となる。ゲスト内の umount と fstab 削除だけでは 1 バイトも空かない。
  - `zfs_pools` の要素を除去すると残るボリュームの `interface` が繰り上がるため、`terraform plan` による事前確認を要件 18.8 として明示する。
  - `discard` は `ignore_changes` に `disk` が含まれる限り定義側から矯正できず、要件 4.7 と同じ根を持つ。要件 18.9 / 18.10 は段階 3 で `ignore_changes` の解除と同一の適用に載せる。
  - overcommit の不在、真の孤児の不在、スナップショット滞留の不在は監査済みの事実として design に記録し、同じ調査を繰り返さない。
  - VM 105 は要件 19 の対象ではなく、要件 28 の判断対象である。冗長性を持たない単発 HDD 上に 666GB の実データがバックアップなしで存在する事実を、要件 28.7 の判断材料とする。
  - `zfs_pool_sizes` のデッドコードは既に要件 9.6 が扱っており、要件 18 で重ねて扱わない。

### 認証基盤の候補比較

- **Context**: 要件 25 / 26。撤去する認証基盤の置き換え先を確定する。ホームラボにはメール基盤が存在せず、NAS の POSIX アカウントを同一のディレクトリで扱う必要があるため、この 2 点が選定の主軸となる。
- **Sources Consulted**:
  - [Kanidm: Authentication and Credentials](https://kanidm.github.io/kanidm/stable/accounts/authentication_and_credentials.html)
  - [Kanidm: Account Policy](https://kanidm.github.io/kanidm/stable/accounts/account_policy.html)
  - [Kanidm: POSIX Accounts and Groups](https://kanidm.github.io/kanidm/stable/accounts/posix_accounts_and_groups.html)
  - [Kanidm: PAM and nsswitch](https://kanidm.github.io/kanidm/stable/integrations/pam_and_nsswitch.html)
  - [Kanidm: LDAP](https://kanidm.github.io/kanidm/stable/integrations/ldap.html)
  - [Kanidm: OAuth2](https://kanidm.github.io/kanidm/stable/integrations/oauth2.html)
  - [Kanidm: OAuth2 examples](https://kanidm.github.io/kanidm/stable/integrations/oauth2/examples.html)
  - [Kanidm: Backup and Restore](https://kanidm.github.io/kanidm/stable/backup_and_restore.html)
  - [Kanidm: Server Updates](https://kanidm.github.io/kanidm/stable/server_updates.html)
  - [Kanidm: Debian / Ubuntu packaging](https://kanidm.github.io/kanidm/stable/packaging/debian_ubuntu_packaging.html)
  - [Kanidm PPA](https://kanidm.github.io/kanidm_ppa/)
  - [Kanidm: unixd 設定例](https://github.com/kanidm/kanidm/blob/master/examples/unixd)
  - [kanidm-provision](https://github.com/oddlama/kanidm-provision)
  - [Terraform Provider: SeanLatimer/kanidm](https://registry.terraform.io/providers/SeanLatimer/kanidm/latest/docs)
  - [Authelia: OpenID Connect 1.0 Provider roadmap](https://www.authelia.com/roadmap/active/openid-connect-1.0-provider/)
  - [Authelia: lldap integration](https://www.authelia.com/integration/ldap/lldap/)
  - [Authelia: Notifications](https://www.authelia.com/configuration/notifications/introduction/)
  - [Authelia issue #10177](https://github.com/authelia/authelia/issues/10177)
  - [lldap](https://github.com/lldap/lldap)
  - [lldap: PAM 設定例](https://github.com/lldap/lldap/blob/main/example_configs/pam/README.md)
  - [Zitadel discussion #1929](https://github.com/zitadel/zitadel/discussions/1929)
  - [FreeIPA: Install and Deploy](https://www.freeipa.org/page/InstallAndDeploy)
- **Findings**:

  認証情報の管理方式の比較。

  | 構成 | 利用者によるパスワード変更 | リセット経路と SMTP 依存 | ポリシー・ロックアウト | 2FA の自己管理 | Linux での `passwd` |
  |---|---|---|---|---|---|
  | authelia + lldap | 可 (lldap Web UI、Authelia 4.39 でポータル内変更) | **SMTP 依存**。notifier は `smtp` か `filesystem` の二択で必須。SMTP 無しは `/config/notification.txt` を管理者が手で拾う運用。管理者用リセットリンク発行 API は未実装 | **無し**。lldap にポリシー・履歴・ロックアウトなし。Authelia の連続失敗 BAN はポータルのみを守り LDAP bind は素通り | ポータルで TOTP / WebAuthn / Duo。登録リンクも notifier 経由 | 理屈上は可 (lldap は LDAP Modify 対応、sssd `chpass_provider = ldap`) |
  | **Kanidm** | 可 (Web UI credential update session、`kanidm self posix set_password`) | **SMTP 不要**。`kanidm person credential create-reset-token <user> [ttl]` が QR + URL を発行し、利用者が `/ui/reset` で自己設定する。既定 TTL 1 時間 (最大 24 時間) | zxcvbn 強度検査を全パスワードに強制、バッドリスト、グループ単位の `password-minimum-length` / `credential-type-minimum` / `auth-expiry` / `privilege-expiry`、レートリミット + ソフトロック。**パスワードローテーションは非対応 (アンチ機能として明示)** | 可 (credential update session 内で Passkey / TOTP / attested passkey を自己登録) | **不可**。`passwd` の変更を Kanidm へ push back しない |
  | Keycloak | 可 | Forgot-password は SMTP 必須 | 強い | 可 | **不可** (LDAP サーバではないため POSIX 統合が成立しない) |
  | Zitadel | 可 | SMTP 前提 | 中 | 可 | **不可** (LDAP サーバ機能なし。公式に提供予定未定) |
  | FreeIPA | 可 | 管理者リセットは SMTP 不要 | 最強 | 可 | **可** (Kerberos 経由) |
  | OpenLDAP + authelia | 可 (ppolicy + self-service) | 秘密の質問方式で SMTP 回避可 | 強い (ppolicy) | Authelia 側 | 可 (RFC3062 exop) |

  リソースと構成の比較。

  | 構成 | コンポーネント数 | リソース目安 | POSIX 統合 | 懸念 |
  |---|---|---|---|---|
  | **Kanidm** | **1** (+ NAS に unixd) | Rust + SQLite。authentik / Keycloak より一桁小さい | **最良** (unixd がホーム自動生成、グループマップ、オフラインキャッシュ) | implicit flow 非対応、`passwd` 不可、**マイナー版スキップ不可**、LDAP は read-only |
  | authelia + lldap | 2 (+ HA なら Redis で 3) | Authelia < 30MB、lldap ~10MB (最軽量) | 条件付き | 認証情報の管理が弱い (上表) |
  | Keycloak | 1 (+ ストア) | 512MB〜1GB | 不可 | 重い |
  | FreeIPA (+ Keycloak) | 2 | FreeIPA 単体で最低 2GB・実用 4GB | 最強 | OIDC provider ではない。ホームラボに重すぎる |

  - Kanidm の `kanidmd` は reverse proxy 越しに配置する場合も TLS を自前で終端することを要求し、StartTLS に対応しない。
  - `[online_backup]` はサーバ側の設定として宣言する。リストアはバックアップを取得したバージョンと同一のバージョンでのみ成立する。
  - 更新はマイナーバージョンを飛ばせない。1.5 から 1.7 への直接更新は成立せず、1.5 → 1.6 → 1.7 の順を要する。
  - `kanidm-unixd-tasks` がホームディレクトリを自動生成し、`home_mount_prefix` がネットワークホーム向けの設定として用意されている。`kanidm.map_group` でローカルグループのメンバをディレクトリ側のグループで拡張できる。
  - UID/GID の動的割当レンジは `1879048192`–`2147483647`、手動割当の推奨レンジは `65536`–`524287`。
  - `pam_allowed_login_groups` によりログイン可能なグループをホスト単位で制限できる。
  - Debian / Ubuntu 向けには公式 PPA が提供されており、apt source として宣言できる。
  - ユーザー・グループ・OAuth2 クライアントの宣言的な適用手段は `kanidm-provision` と Terraform provider の 2 つで、**いずれも非公式**である。
  - Gitea の認証ソースは `app.ini` ではなくデータベース内に保持される。`gitea admin auth list` / `add-oauth` / `update-oauth --id N` が操作手段であり、冪等性は Gitea 側が保証しない。
  - ArgoCD は `argocd-cm` の `oidc.config` で OIDC provider に直結でき、dex を必要としない。CLI 用には PKCE を要求する public client を別に登録する。`argocd-rbac-cm` の `policy.csv` が参照するグループ名は大文字小文字を区別する。
  - Guacamole の内蔵 OIDC 拡張は implicit flow のみを実装しており、Kanidm はこれを拒否する。`guacamole-auth-header` 拡張と forward auth の組み合わせが成立する経路となる。
  - `console.fickledev.com` は Cloudflare Access のアプリケーションとして定義され、`allowed_idps` が GitHub を指している。Guacamole の認証は現状 Cloudflare Access が GitHub を IdP として担っており、撤去対象の認証基盤とは独立している。Guacamole が用いるトンネルも撤去対象の基盤が用いるトンネルとは別である。
  - Home Assistant は `trusted_proxies` と `use_x_forwarded_for` の設定を要し、コンパニオンアプリの経路は forward auth と相性が悪い。
- **Implications**:
  - 要件 26 の基盤は Kanidm 単体とする。根拠は Design Decisions に記録する。
  - Garage は S3 API と UI で扱いを分ける。API パスに forward auth をかけると AWS 署名 v4 の検証が壊れる。
  - Guacamole は内蔵 OIDC ではなく header 認証を前提として設計する。上流からの認証ヘッダの除去が成立条件となる。
  - NAS の UID/GID レンジは Kanidm の既定と現行の設定のいずれとも一致しないため、実機の所有者情報を確認したうえで決定する。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 単一の一括是正 | 全 143 件の受入基準を 1 つの変更セットとして適用 | 中間状態が存在しない | 稼働中環境で切り分けが不可能。1 箇所の失敗で全体が止まる | 却下 |
| リスク階層型の段階適用 | 影響度と可逆性で 4 段階に分け、段階ごとに検証と CI 導入を挟む | 各段階が独立して切り戻せる。CI をグリーンな状態で導入できる | 段階間の依存関係を設計で明示する必要がある | **採用** |
| リポジトリ単位の分割 | `my-home-network` と `gitops-apps` を別々に完了させる | コミット単位が自然 | mailu 撤去と xrayvpn 停止が両リポジトリにまたがるため分割できない | 部分的に採用 (コミット粒度としてのみ) |
| ワークロード規約の先行策定 | 要件 10 を最初に確定させ、他の是正をその規約の下で行う | 新基盤 spec との整合が早期に取れる | resources の値決定に実測期間が必要で、他の是正を待たせる | 却下 (段階 4 に配置) |

## Design Decisions

### Decision: 適用順序をリスク階層で定義する

- **Context**: 要件 12.1 は「セキュリティ → 壊れているコード → mailu → 重複 → 残り」という分類順を定めるが、高リスク項目 (トークンローテーション、`ignore_changes` 除去、resources 導入) が複数の分類に分散している。
- **Alternatives Considered**:
  1. 要件 12.1 の分類順をそのまま採用する。
  2. 影響度と可逆性による 4 段階に再編する。
- **Selected Approach**: 4 段階。段階 1 は削除と修正のみで可逆、段階 2 は挙動変更を伴い再実行検証が必要、段階 3 は高影響で単独適用、段階 4 は実測を要する規約策定。要件 12.13 が高影響変更の単独適用を求めており、この再編はその具体化にあたる。
- **Rationale**: 稼働中環境では「何を戻せば元に戻るか」が明確であることが、分類の見た目の整合より重要。
- **Trade-offs**: 要件の分類と適用段階が 1 対 1 に対応しなくなる。design の Migration Strategy で対応表を示すことで補う。
- **Follow-up**: 各段階の完了条件を検証手段として定義し、tasks 生成時にその粒度を維持する。

### Decision: agent への配布トークンを server token から agent token へ切り替える

- **Context**: 調査により `node-token` が server token へのリンクであり、agent にクラスタ管理者権限が配られていることが判明した。漏洩した値も server token である。
- **Alternatives Considered**:
  1. ローテーションのみ行い、配布するトークンの種類は変更しない。
  2. ローテーションと同時に `--agent-token` を導入し、agent には agent token を配布する。
- **Selected Approach**: 2。server 側で `--agent-token` を設定し、`rlex.k3s` の呼び出し側が agent へ配布する値を `server/agent-token` に切り替える。
- **Rationale**: ローテーションは agent の再起動を伴うため、同じ再起動の機会に配布経路を是正すれば追加のダウンタイムが発生しない。ローテーションだけでは「次に漏洩したときも管理者権限が漏れる」構造が残る。
- **Trade-offs**: `rlex.k3s` は Galaxy 由来の role であり、`set_fact` で `k3s_node_token` を上書きする内部実装に依存している。role 本体を改変せずに実現できるかを実装時に確認する必要がある。可能なら呼び出し側の変数注入のみで対応し、不可能なら role のフォークではなく playbook 側でのトークン配布に切り替える。
- **Follow-up**: `rlex.k3s` の in-tree 版と Galaxy 版の差分確認 (要件 4.14) と同時に実施する。

### Decision: シークレットスキャンは差分走査と全履歴走査を分離する

- **Context**: gitleaks-action v2 は引数がハードコードされており、`args:` 入力は反映されない。イベント種別で走査範囲が決まる。
- **Alternatives Considered**:
  1. `args:` を修正する。
  2. action を使わず gitleaks バイナリを直接実行する。
  3. 既存ジョブを差分走査として維持し、`schedule` トリガの全履歴走査ジョブを追加する。
- **Selected Approach**: 3。既存ジョブから効果のない `args:` を除去し、`fetch-depth: 0` を設定する。別途 `schedule` トリガのジョブを追加し、全履歴を走査する。
- **Rationale**: action の想定された使い方に沿う。バイナリ直接実行は SARIF 出力や PR コメント連携を自前で組む必要があり、得られるものに対して複雑さが見合わない。
- **Trade-offs**: 履歴の汚染を検知するまでに最大でスケジュール間隔の遅延が生じる。ただし履歴書き換え後の再汚染検知が目的であり、リアルタイム性は要求されない。
- **Follow-up**: `args:` が実際に無視されることを実装時に確認する。反映される場合は選択肢 1 に切り替える。

### Decision: prune 保護は ApplicationSet の除外ではなくリソースアノテーションで行う

- **Context**: 要件 10.7。永続データを持つリソースを誤削除から守る。
- **Alternatives Considered**:
  1. ApplicationSet から該当アプリを `exclude: true` し、個別 Application として syncPolicy を変える。
  2. リソースに `Prune=false` アノテーションを付与する。
- **Selected Approach**: 2。`exclude: true` は `apps/base` / `apps/common` の Application 化解消にのみ用いる。
- **Rationale**: 選択肢 1 は GitOps から外れる Application を増やす。`argocd/mailu-application.yaml` が未適用のまま残骸化した前例があり、同じ構造を再生産する。選択肢 2 は保護対象がマニフェスト上に宣言的に現れ、どのリソースが保護されているかがコードから読める。
- **Trade-offs**: syncPolicy そのものは全アプリ一律のまま残る。アプリごとに sync 挙動を変える要求が将来生じた場合は再設計が必要。
- **Follow-up**: `Prune=false` と `Delete=false` の使い分けを設計で明示する。PVC には両方を付与する。

### Decision: IP の重複は解消せず、検知に留める

- **Context**: 要件 7.1-7.3。利用者の判断により単一情報源化は行わない。
- **Alternatives Considered**:
  1. 共有 YAML を Terraform と Ansible の双方が読む。
  2. Terraform output から inventory を生成する。
  3. 重複を明示し、不整合を検知するチェックのみ導入する。
- **Selected Approach**: 3。`terraform/locals.tf` と `ansible/inventory/` を突き合わせるチェックを実装し、CI で実行する。
- **Rationale**: ホスト 8 台・静的 IP・変更頻度がほぼゼロという実態に対し、選択肢 1 は `for_each` のキー変更により稼働中 VM の再作成を招きうる。ブラスト半径が便益に見合わない。
- **Trade-offs**: 重複そのものは残る。ただし片方だけ更新される事故は検知できる。
- **Follow-up**: `locals.tf` の解析方法を決める。`terraform` コマンドを介さずに解析できる形が望ましい。

### Decision: resources の値は `kubectl top` の実測値と余裕係数で決める

- **Context**: 要件 10.1-10.3。3 ノードのクラスタに requests / limits を導入する。当初は VPA `updateMode: "Off"` による 1-2 週間の測定を想定していたが、是正を今回で完了させる方針が確定したため再検討した。
- **Alternatives Considered**:
  1. 一般的な既定値を推測で設定する。
  2. VPA を `updateMode: "Off"` で導入し、推奨値を実測してから設定する。
  3. 稼働中の metrics-server から `kubectl top` で実測し、余裕係数を掛けて決める。
- **Selected Approach**: 3。
- **Rationale**: 選択肢 2 は新しいコントローラとカスタムリソースをクラスタに追加する。本 spec は「使われないまま残る資産」を除去することを目的としており、そのために新たな常駐資産を導入するのは自己矛盾する。加えて測定期間が是正の完了を遅らせる。実測の結果、自作ワークロードのメモリ使用量は合計約 2.8Gi、CPU は全て 10m 未満であり、ノード総容量 32Gi に対して余裕が大きい。この規模では VPA の統計的な精度を必要としない。
- **Trade-offs**: 実測値は測定時点の値であってピーク値ではない。余裕係数を保守的に取ることで補う。
- **Follow-up**: 適用後に OOMKilled が発生しないことを一定期間確認する。発生した場合の引き上げ手順を残す。

### Decision: 品質ガードの対象を ArgoCD が管理する全ワークロードとする

- **Context**: 要件 10.1-10.3。当初の記述は対象を自作のワークロードに限っていた。この限定のもとでは `argocd-server` と `cnpg-operator` が `resources` を持たないまま残る。
- **Alternatives Considered**:
  1. 自作のワークロードに限定する。上流由来のものは上流の判断に委ねる。
  2. ArgoCD が管理する全ワークロードを対象とし、梱包の出自で区別しない。
- **Selected Approach**: 2。
- **Rationale**: `resources` を持たない Pod の QoS は BestEffort となり、ノードのメモリが逼迫した際に最初に退去の対象となる。`argocd-server` と `cnpg-operator` はクラスタの制御プレーンにあたり、これらが停止すると GitOps による是正そのものが機能しなくなる。要件 10 の目的はワークロードの品質ガードの確立であり、梱包の出自によって適用範囲を変える根拠がない。
- **Trade-offs**: 上流由来のワークロードへ設定を与える手段が梱包形態ごとに異なる。Helm チャートは `values`、Kustomize と上流マニフェストの取り込みは patch を要する。`apps/cnpg-operator/cnpg-operator.yaml` は 1.1MB / 18,000 行の取り込みであり、patch 対象の特定に手間がかかる。`securityContext` の注入は上流が前提とする権限を奪って起動を妨げうるため、上流が既に定義しているものは尊重し、注入は不足するものに限る。
- **Follow-up**: 上流由来のワークロードは実測値を持たないため、適用時に `kubectl top` で実測する。設定を与える手段が存在しないワークロードは、対象と理由を記録して未対応の放置と区別する。

### Decision: クラスタ上の孤児リソースを是正対象に含める

- **Context**: resources の実測中に、Git 上に対応する定義を持たないワークロードがクラスタ上に存在することが判明した。監査もギャップ分析もリポジトリの内容のみを対象としており、この観点が抜けていた。
- **Alternatives Considered**:
  1. リポジトリの是正に留め、クラスタ実体の孤児は別途扱う。
  2. 要件 14 として本 spec の対象に含める。
- **Selected Approach**: 2。
- **Rationale**: 発見された孤児のうち `default` namespace の authentik スタックは 2 日間起動に失敗し続けており、sealed-secrets は steering が「撤去済み」と記述する機構の実体である。後者は要件 11 (ドキュメントと実態の一致) が対象とする齟齬そのものであり、リポジトリ側だけを直しても解消しない。GitOps を導入していながら実態が Git から読み取れないという状態は、本 spec が扱う「膿」と同じ性質を持つ。
- **Trade-offs**: spec の対象がリポジトリからクラスタ実体へ広がる。Boundary Commitments に明記して境界を保つ。
- **Follow-up**: 除去後にクラスタ上のワークロードを再列挙し、ArgoCD の管理下にないものが残っていないことを確認する。

### Decision: IdP は Kanidm 単体とする

- **Context**: 要件 25 / 26。認証の背後に置く対象は Gitea、ArgoCD、NAS のログイン統合、Home Assistant、Garage の UI、および Guacamole である。ホームラボはメール基盤を持たず、NAS では POSIX アカウントとホームディレクトリを同一のディレクトリから供給する必要がある。
- **Alternatives Considered**:
  1. authelia + lldap
  2. Kanidm 単体
  3. Keycloak
  4. Zitadel
  5. FreeIPA (+ OIDC provider)
  6. OpenLDAP + authelia
- **Selected Approach**: 2。Kanidm 単体を IdP とし、NAS には `kanidm-unixd` を導入する。
- **Rationale**:
  1. SMTP に依存せずパスワードリセットと 2 段階認証の登録が完結する。メール基盤を持たない構成で成立する唯一の候補が Kanidm と FreeIPA であり、後者は規模が合わない。
  2. `kanidm-unixd-tasks` がホームディレクトリを自動生成し、`home_mount_prefix` がネットワークホーム向けに設計されている。`kanidm.map_group` でローカルグループを拡張できるため GID の手動整合が不要になる。
  3. コンポーネントが 1 つであり、IdP と OIDC provider の間の属性マッピングという故障点を持たない。
  4. 認証情報のポリシー (強度検査、バッドリスト、グループ単位の最低クレデンシャル種別、ソフトロック) が実装として存在する。
  5. ユーザー、グループ、OIDC クライアントを宣言的に定義できる。
- **Trade-offs**:
  - Guacamole の内蔵 OIDC 拡張は implicit flow のみを実装しており Kanidm が拒否するため、header 認証と forward auth へ切り替える。上流からの認証ヘッダを除去しない限り認証を迂回されるため、この除去が成立条件となる。
  - NAS 上で `passwd` によるパスワード変更が成立しない。利用者を Web UI または `kanidm self posix set_password` へ誘導する経路が必要になる。
  - マイナーバージョンを飛ばした更新ができない。ArgoCD の自動同期でイメージタグが飛ぶ経路を塞ぐ必要がある。
  - リストアはバックアップ取得時と同一バージョンでしか成立しない。バックアップとイメージタグを対で扱う。
  - 宣言的な適用手段 (`kanidm-provision` / Terraform provider) はいずれも非公式であり、供給元とバージョンの固定が前提となる。
- **Follow-up**: NAS の UID/GID レンジは実機の所有者情報を確認したうえで決定する。Kanidm の既定の動的割当レンジ (`1879048192`–`2147483647`)、手動割当の推奨レンジ (`65536`–`524287`)、現行の設定のいずれとも一致しないため、既存ファイルとの整合を確認せずにレンジを固定しない。

### Decision: Kubernetes Dashboard を撤去し kubeconfig と端末クライアントに寄せる

- **Context**: 要件 27。Dashboard は上流マニフェストの取り込みで導入されており、公開経路、TLS 検証のスキップ、二重定義の公開定義、保守が終了したイメージ、実態と乖離した README を同時に抱えている。
- **Alternatives Considered**:
  1. 現行の系列を維持したまま是正する。
  2. 保守されている系列へ更新したうえで是正する。
  3. 撤去し、クラスタの操作手段を kubeconfig と端末クライアントに一本化する。
- **Selected Approach**: 3。
- **Rationale**: Dashboard が提供する機能は kubeconfig を持つ端末クライアントで代替できる。維持は上流マニフェストの取り込み、外部公開経路、管理者権限のサービスアカウントという 3 つの資産を同時に抱えることを意味し、単独の利用者に対する便益に見合わない。撤去は 4 件の個別の是正を同時に解消する。
- **Trade-offs**: ブラウザからクラスタを閲覧する手段を失う。操作には端末とネットワーク到達性が必要になる。
- **Follow-up**: README と steering の記述を撤去後の操作手段に一致させる。

## Risks & Mitigations

- **k3s トークンローテーション中のコントロールプレーン断** — 単一 server 構成のため API が数十秒停止する。走行中コンテナは停止しないため、ワークロードへの影響はない。ArgoCD の sync が失敗しうるため、実施前に自動 sync の一時停止を検討する。実施前にクラスタのスナップショットを取得し、旧トークンを保管する。
- **履歴書き換え後の再汚染** — 書き換え前のクローンから push されると復活する。書き換え後に全クローンを再取得し、旧クローンを破棄する。`schedule` トリガの全履歴走査で再汚染を検知する。
- **`ignore_changes` 除去による VM 再作成** — `disk` を無視しなくすると既存 VM に差分が出る可能性がある。適用前に `terraform plan` を実行し、再作成が発生する場合は要件 4.7 の実現方法を変更する。plan の結果が確定するまで適用しない。
- **Proxmox API の TLS 検証有効化による apply 失敗** — 証明書が自己署名の場合に検証が通らない。適用前に証明書を確認し、必要なら CA を配布する。検証を有効にできない場合は、その理由をコード上に記録した上で既定値のみ安全側に倒す。
- **mailu 撤去時の orphan PVC 残存** — `pvc/redis-data-mailu-redis-master-0` は ArgoCD の管理外であり prune されない。撤去手順に手動除去を必須ステップとして含める。
- **xrayvpn 停止時の外部経路の取り残し** — `appflowy.fickledev.com` の DNS レコードと VPS の haproxy SNI 分岐が残ると、到達可能だが応答しない経路になる。要件 13.4 の検証として、停止後に当該ホスト名への接続が確立しないことを確認する。
- **ansible-lint の Vault 復号警告** — `exclude_paths` に既知の不具合があるため、作業ツリーの vault.yml を削除する方針とする。削除できない事情が判明した場合は `ansible.cfg` の `vault_password_file` による回避に切り替える。
- **`rlex.k3s` の内部実装への依存** — agent token への切り替えが role 本体の改変を要する可能性がある。改変が必要な場合は in-tree 版を正とする決定 (要件 4.14) と併せて判断する。
- **認証基盤のマイナーバージョンのスキップ** — Kanidm はマイナーバージョンを飛ばした更新に対応しない。ArgoCD の自動同期でイメージタグが飛ぶと、リストア不能な状態に至る。イメージタグを可変でない参照で固定し、更新を段階的に行う経路のみを残す。
- **NAS の UID/GID レンジの非互換** — Kanidm の既定の割当レンジは現行の設定と重ならない。既存ファイルの所有者を確認せずに切り替えると、ファイルの所有権が解決できなくなる。レンジの決定を実機確認の後に置き、移行の要否を判断する。
- **forward auth による S3 API の破壊** — Garage の S3 API パスに forward auth を適用すると AWS 署名 v4 の検証が壊れる。middleware の適用対象を UI のパスに限定する。
- **header 認証における認証ヘッダの持ち込み** — Guacamole の header 認証は上流が付与するヘッダを信頼する。上流からの当該ヘッダを除去しない限り、任意の利用者を名乗れる。除去を成立条件として設計に記録する。

## References

- [k3s token CLI](https://docs.k3s.io/cli/token) — トークンの種類とローテーション手順
- [k3s ADR: Support Rotating Server Tokens](https://github.com/k3s-io/k3s/blob/master/docs/adrs/server-token-rotation.md) — ローテーションの内部動作
- [k3s Stopping K3s](https://docs.k3s.io/upgrades/killall) — サービス停止時のコンテナ継続稼働
- [GitHub Docs: Removing sensitive data from a repository](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository) — 履歴書き換えの公式手順
- [git-filter-repo](https://github.com/newren/git-filter-repo) — `--replace-text` の仕様
- [Argo CD Sync Options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/) — `Prune=false` / `Delete=false`
- [Argo CD ApplicationSet Git Generator](https://argo-cd.readthedocs.io/en/stable/operator-manual/applicationset/Generators-Git/) — `exclude: true`
- [helm dependency build](https://helm.sh/docs/helm/helm_dependency_build/) — lock 不在時のフォールバック
- [gitleaks-action v2.3.9 `src/gitleaks.js`](https://github.com/gitleaks/gitleaks-action/blob/v2.3.9/src/gitleaks.js) — 引数のハードコードと走査範囲
- [community.crypto.x509_certificate_info](https://docs.ansible.com/ansible/latest/collections/community/crypto/x509_certificate_info_module.html) — `valid_at` による有効期限判定
- [ansible-lint load-failure rule](https://docs.ansible.com/projects/lint/rules/load-failure/) — Vault 暗号化ファイルの除外
- [ansible.posix.mount](https://docs.ansible.com/ansible/latest/collections/ansible/posix/mount_module.html) — `state: mounted` の冪等性
- [Kubernetes: Resource Management for Pods and Containers](https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/) — requests / limits の強制機序
- [VPA API reference](https://github.com/kubernetes/autoscaler/blob/master/vertical-pod-autoscaler/docs/api.md) — `updateMode: "Off"`
- [Kanidm: Authentication and Credentials](https://kanidm.github.io/kanidm/stable/accounts/authentication_and_credentials.html) — リセットトークンによる SMTP 非依存の自己設定
- [Kanidm: Account Policy](https://kanidm.github.io/kanidm/stable/accounts/account_policy.html) — グループ単位のポリシーとソフトロック
- [Kanidm: POSIX Accounts and Groups](https://kanidm.github.io/kanidm/stable/accounts/posix_accounts_and_groups.html) — UID/GID の割当レンジ
- [Kanidm: PAM and nsswitch](https://kanidm.github.io/kanidm/stable/integrations/pam_and_nsswitch.html) — unixd の設定項目とホーム自動生成
- [Kanidm: LDAP](https://kanidm.github.io/kanidm/stable/integrations/ldap.html) — read-only LDAP と StartTLS 非対応
- [Kanidm: OAuth2](https://kanidm.github.io/kanidm/stable/integrations/oauth2.html) — implicit flow 非対応
- [Kanidm: OAuth2 examples](https://kanidm.github.io/kanidm/stable/integrations/oauth2/examples.html) — 各コンシューマの設定例
- [Kanidm: Backup and Restore](https://kanidm.github.io/kanidm/stable/backup_and_restore.html) — `[online_backup]` と同一バージョン制約
- [Kanidm: Server Updates](https://kanidm.github.io/kanidm/stable/server_updates.html) — マイナーバージョンのスキップ不可
- [Kanidm: Debian / Ubuntu packaging](https://kanidm.github.io/kanidm/stable/packaging/debian_ubuntu_packaging.html) — クライアントの導入方法
- [Kanidm PPA](https://kanidm.github.io/kanidm_ppa/) — apt source の宣言
- [Kanidm: unixd 設定例](https://github.com/kanidm/kanidm/blob/master/examples/unixd) — `home_*` および `map_group` の記法
- [kanidm-provision](https://github.com/oddlama/kanidm-provision) — 宣言的な適用手段 (非公式)
- [Terraform Provider: SeanLatimer/kanidm](https://registry.terraform.io/providers/SeanLatimer/kanidm/latest/docs) — 宣言的な適用手段 (非公式)
- [Authelia: OpenID Connect 1.0 Provider roadmap](https://www.authelia.com/roadmap/active/openid-connect-1.0-provider/) — provider 機能の到達点
- [Authelia: lldap integration](https://www.authelia.com/integration/ldap/lldap/) — 組み合わせ時の構成
- [Authelia: Notifications](https://www.authelia.com/configuration/notifications/introduction/) — notifier の二択と SMTP 依存
- [Authelia issue #10177](https://github.com/authelia/authelia/issues/10177) — 管理者用リセットリンク発行の未実装
- [lldap](https://github.com/lldap/lldap) — 機能範囲とポリシーの不在
- [lldap: PAM 設定例](https://github.com/lldap/lldap/blob/main/example_configs/pam/README.md) — Linux 統合の前提
- [Gitea: Authentication](https://docs.gitea.com/administration/authentication) — OIDC 認証ソースの構成
- [Gitea: Command Line](https://docs.gitea.com/administration/command-line) — `admin auth list` / `add-oauth` / `update-oauth`
- [Argo CD: OIDC without dex](https://argo-cd.readthedocs.io/en/stable/operator-manual/user-management/google/) — `oidc.config` による直結と CLI 用 public client
- [Guacamole: OpenID Connect Authentication](https://guacamole.apache.org/doc/gug/openid-auth.html) — implicit flow のみの実装
- [Guacamole: Header Authentication](https://guacamole.apache.org/doc/gug/header-auth.html) — `REMOTE_USER` ヘッダの扱い
- [Home Assistant: Authentication providers](https://www.home-assistant.io/docs/authentication/providers/) — 内蔵認証と信頼するプロキシ
- [hass-auth-header](https://github.com/BeryJu/hass-auth-header) — ヘッダ認証の連携方式
- [Zitadel discussion #1929](https://github.com/zitadel/zitadel/discussions/1929) — LDAP サーバ機能の提供予定
- [FreeIPA: Install and Deploy](https://www.freeipa.org/page/InstallAndDeploy) — 必要リソース
