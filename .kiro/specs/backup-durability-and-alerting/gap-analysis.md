# Gap Analysis: backup-durability-and-alerting

要件 (11 要件 / 90 受入基準) と既存実装の差分を、実機の読み取りと両リポジトリの読み取りに基づいて整理する。
設計判断は行わない。選択肢と、設計フェーズへ持ち越す調査項目までを示す。

## 1. 現状の把握

### 1.1 退避に関わる資産

| 資産 | 位置 | 担うもの |
| --- | --- | --- |
| `proxmox_backup` role | `ansible/roles/proxmox_backup/` | PVE の vzdump ジョブ、PBS ストレージ登録、API トークンの ACL |
| `pbs` role | `ansible/roles/pbs/` | PBS のインストール、データストア登録、データストア ACL |
| `mail_backup` role | `ansible/roles/mail_backup/` | メールボックス PV の書庫化と世代保持 (pull 型) |
| `mariadb_dump` role | `ansible/roles/mariadb_dump/` | Gitea DB の論理退避と世代保持 |
| `systemd_failure_notify` role | `ansible/roles/systemd_failure_notify/` | `OnFailure=notify-failure@%n.service` を宣言したユニットの失敗を webhook へ送る汎用ハンドラ |
| Garage の退避 CronJob | `gitops-apps/apps/garage/templates/backup-*.yaml` | rclone による外部の記憶領域への複製 |
| Garage の容量検査 CronJob | `gitops-apps/apps/garage/templates/capacity-check-cronjob.yaml` | `df` の閾値超過で Job を失敗させる |
| Kanidm の内蔵退避 | `gitops-apps/apps/kanidm/configmap.yaml` の `[online_backup]` | 日次・7 世代・gzip |
| 退避対象の単一の情報源 | `ansible/inventory/host_vars/pbs/main.yml` | `pbs_backup_targets` / `pbs_backup_excluded_targets` |

### 1.2 実機で確認した状態

読み取りのみで確認した。

- **PBS のジョブ**: `prune-job list` / `verify-job list` / `sync-job list` はいずれも 0 件。`/etc/proxmox-backup/prune.cfg` と `verification.cfg` は存在しない。`datastore.cfg` は `path` のみを持ち `gc-schedule` を持たない。
- **vzdump ジョブ**: 対象は vmid 150 / 151 / 152 / 201 / 202 の 5 件、`keep-last=2`、`04:30`。インベントリの宣言と一致する。
- **データストアの内容**: `vm/` に 150 / 151 / 152 / 201、`ct/` に 100 / 113 / 202。使用量は 52G / 1.4T。
- **実機のゲスト**: 108 / 110 / 150 / 151 / 152 / 200 / 201 / 202 / 9000 / 9001。**`ct/100` と `ct/113` に対応するゲストは存在しない**。
- **通知**: `/etc/pve/notifications.cfg` は存在せず、組み込みの `mail-to-root` のみ。両ノードの送信待ち行列に配送できない通知が滞留している (n100: 12 通 / 106 KB、hp-z440: 132 通 / 391 KB)。いずれも外部の受信ドメインの 25 番への接続が時間切れになっている。宛先は運用者個人のアドレス。
- **記憶装置の検査**: hp-z440 の ZFS scrub は配布物の cron (`/etc/cron.d/zfsutils-linux`、毎月第 2 日曜) が持つ。宣言の対象外。**直近の完了は 2026-06-14 であり、以降の 2 回が実行されていない。実行されなかったこと自体が検知されていない。**
- **メールボックスの書庫**: 最新の世代が 160 バイト。`tar -tzf` の項目数は 1 (最上位ディレクトリのみ)。直前の世代は 185 項目 / 約 100 KB。**`gzip -t` を通過したため世代として採用されている。**
- **検査機構**: 両リポジトリとも `.git/hooks/` に `.sample` 以外のファイルが無く、`core.hooksPath` も設定されていない。**`pre-commit install` が一度も実行されていない。**

### 1.3 規約と統合点

- Ansible は 1 role = 1 コンポーネント。定期実行は systemd timer + oneshot service + `/usr/local/sbin` のスクリプトという形で `mail_backup` と `mariadb_dump` が既に確立している。
- 秘匿値は `lookup('env', 'VAR')` を `defaults` / `group_vars` の右辺に置き、`infisical run` が供給する。k3s 側は `InfisicalStaticSecret` が Secret を同期する。
- 通知は `systemd_failure_notify` が `OnFailure=notify-failure@%n.service` という一点の宣言だけで対象を増やせる形になっている。到達不成立時にハンドラ自身を failed にする扱いも実装済み。
- `gitops-apps` の唯一の remote は Gitea であり、ArgoCD の唯一の情報源でもある。Gitea Actions は当該インスタンスで無効 (`app.ini` に `[actions]` 節が無く runner も未登録) であり、`scripts/validate-manifests.sh` は pre-commit 経由でしか動かない設計になっている。

## 2. 要件と資産の対応

タグ: **Missing** = 資産が無い / **Partial** = 資産はあるが要件を満たさない / **Unknown** = 実測が必要 / **Constraint** = 既存の構造が制約になる

### 要件 1: 退避の完全性の検証

| 受入基準 | 既存資産 | 判定 |
| --- | --- | --- |
| 1.1 大きさを実測値と突き合わせて記録 | 無し | Missing |
| 1.2 直前の世代に対する比率での失敗判定 | 無し | Missing |
| 1.3 空である状態と取得失敗の区別 | 無し | Missing |
| 1.4 空であることの明示 | 無し | Missing |
| 1.5 閾値の宣言 | 無し | Missing |
| 1.6 展開が成立しない世代を採用しない | `mail_backup` の `gzip -t` | Partial |
| 1.7 判定失敗を通知の対象とする | `systemd_failure_notify` (経路のみ) | Partial |

**出来ていること**: `mail_backup` は `.partial` への書き出し → `gzip -t` → `mv` の順で、圧縮として壊れた書庫を世代へ昇格させない。`set -euo pipefail` と、新しい世代が置かれた後にのみ世代整理を行う順序も確立している。

**無いこと**: 中身の量に対する検査が一切無い。実測のとおり、項目数 1 の空の書庫が `gzip -t` を通過して最新世代になっている。`mariadb_dump` は `gzip -t` に相当する検査すら持たず、`OnFailure` も宣言していない。PBS 側の世代についても、大きさの推移を突き合わせる機構は無い。

**Constraint**: 「直前の世代に対する比率」は、`mail_backup` と `mariadb_dump` がそれぞれ独立したスクリプトで世代を管理しているため、共通の判定を置くなら 2 つのスクリプトに同じ処理が二重化する。PBS の世代は保存先が chunk 単位の重複排除であり、群のディレクトリの大きさは実データ量を表さない。PBS 側の「大きさ」は API から取得する必要がある。

### 要件 2: オフサイトへの複製

| 受入基準 | 既存資産 | 判定 |
| --- | --- | --- |
| 2.1 保護対象と保存先が同一の記憶装置に載る箇所の列挙 | 無し | Missing |
| 2.2 既存の外部の記憶領域を用いる | Garage の rclone CronJob (`gdrive:` remote) | あり |
| 2.3 上限 4 TB | 無し | Missing |
| 2.4 使用量の把握と上限接近の検知 | 無し | Missing |
| 2.5 提供元が内容を読み取れない形 | **未成立** | Partial |
| 2.6 退避基盤のデータストアを対象に含める | 無し | Missing |
| 2.7 `gitops-apps` の実体を対象に含める | 無し | Missing |
| 2.8 Gitea 除外の根拠を実態に即した記述へ | **根拠の仕組みが存在しない** | Missing |
| 2.9 `gitops-apps` の復元の実地検証 | 無し | Missing |
| 2.10 既存の複製の復元の実地検証 | 無し | Missing |
| 2.11 上限に収まらない場合の優先順位 | 無し | Missing |

**出来ていること**: rclone による外部の記憶領域への複製が Garage について既に動いている。`InfisicalStaticSecret` から `rclone.conf` を Secret として与え、CronJob が読み取り専用でマウントした PVC を tar して `gdrive:backup/garage` へ置き、`rclone delete --min-age 2d` で古い複製を消す。**この形がそのまま他の対象へ広げられる土台になる。**

**無いこと・成立していないこと**:

- **暗号化が成立していない。** `InfisicalStaticSecret` は `encryption-password` を Secret へ載せているが、`backup.sh` はこの値をどこでも参照していない。`rclone` の `crypt` remote も使われていない。書庫は平文で外部へ置かれている。受入基準 2.5 は資産が「有るように見えて機能していない」状態にある。
- 対象は Garage のみ。PBS のデータストアも `gitops-apps` の実体も対象外。
- `gitops-apps` の remote は Gitea 1 箇所のみ。Gitea (LXC 200) 自身は `pbs_backup_excluded_targets` で `reason: github-offsite-backup` として除外されているが、**Gitea から GitHub へミラーする仕組みは `ansible/roles/gitea/` にもインベントリにも存在しない。**除外の根拠が存在しない仕組みを指している (受入基準 2.8 が指す状態)。
- 使用量の把握、上限、優先順位のいずれも宣言が無い。

**Constraint**: 保護対象と保存先の同居関係は次のとおりで、要件 2.1 の列挙はこの形になる。

| 保護対象 | 実体の位置 | 退避の保存先 | 同居 |
| --- | --- | --- | --- |
| Kanidm の DB | k3s-agent-minipc の PV (n100 SSD) | **同じ PV の `/data/backups`** | **同一ボリューム** |
| メールボックス | k3s-agent-minipc の PV (n100 SSD) | pbs の `zfs-pool` (hp-z440 sdc) | 分離 |
| Gitea の DB | gitea LXC (n100 SSD) | pbs の `/var/backups` (hp-z440 sdc) | 分離 |
| Garage | k3s-agent-z440 の hostPath (hp-z440) | 外部の記憶領域 | 分離 |
| PBS 自身 (ct/202) | hp-z440 sdc の subvol | **自身のデータストア (同じ sdc)** | **同一装置** |
| hp-z440 上のゲスト (152/201) | hp-z440 sda | hp-z440 sdc | 同一ホスト |

### 要件 3: 退避基盤自身の維持

| 受入基準 | 既存資産 | 判定 |
| --- | --- | --- |
| 3.1 世代の整理 (prune) | 無し | Missing |
| 3.2 整合性の検証 (verify) | 無し | Missing |
| 3.3 領域の回収 (GC) | 無し | Missing |
| 3.4 上記 3 つを宣言として保持 | 無し | Missing |
| 3.5 記憶装置の検査と未実行の検知 | 配布物の cron のみ。**未実行が発生済み** | Partial |
| 3.6 不整合を通知の対象とする | 無し | Missing |
| 3.7 退避基盤自身の永続状態の扱い | 判断の記録が無い | Missing |

**出来ていること**: `pbs` role がデータストアの登録と ACL の宣言までを持ち、冪等な形で書かれている (現在の ACL を JSON で読み、必要なときだけ `acl update` を発行する)。ここに `prune-job` / `verify-job` / GC のスケジュールを足す構造上の余地はある。

**無いこと**: 3 つのジョブが実機に 1 件も無く、宣言も無い。vzdump 側の `prune-backups keep-last=2` はバックアップ直後に自ノードの群を整理するだけであり、退役したゲストの群 (`ct/100`、`ct/113`) には触れない。実測でこれらが残っていることが、prune ジョブの不在の帰結として現れている。GC が一度も動いていないため、参照されなくなった chunk も回収されていない。

**Constraint**: PBS 自身 (ct/202) が自身のデータストア上に退避される循環がある。要件 3.7 が求める「判断の記録」はこの循環をどう扱うかの記録になる。また記憶装置の検査は配布物の cron に依存しており、これを宣言へ取り込むと配布物側の cron と二重になる。

### 要件 4: 障害の検知と通知経路の一本化

| 受入基準 | 既存資産 | 判定 |
| --- | --- | --- |
| 4.1 単一の経路を宣言として保持 | `systemd_failure_notify` | Partial |
| 4.2 到達できる資産のみで成立 | webhook は外向き HTTPS のみ | あり |
| 4.3 既存の収集機構の到達可否の確認 | 未記録 | Missing |
| 4.4 対話的な連絡手段への逐次送信を用いない | webhook は専用の宛先 | Unknown |
| 4.5 仮想化基盤の退避失敗の通知 | **配送できない経路に滞留中** | Missing |
| 4.6 GitOps 同期失敗の通知 | 無し | Missing |
| 4.7 容量監視の閾値超過の通知 | Job を失敗させるのみ | Partial |
| 4.8 送信不成立を成功と区別 | `notify-failure.sh` が実装済み | あり |
| 4.9 意図的な事象での到達確認 | 未実施 | Missing |
| 4.10 秘匿値と個人識別情報を含めない | `notify-failure.sh` が journal 抜粋を載せない設計 | あり |
| 4.11 滞留した通知の扱い | **144 通が滞留中、扱い未決** | Missing |
| 4.12 通知対象の事象の一覧 | 無し | Missing |
| 4.13 宣言対象外ホストへの依存の記録 | 未記録 | Missing |
| 4.14 経路に合致しない実装の置き換え | PVE の組み込み経路が残存 | Missing |

**出来ていること**: `systemd_failure_notify` は要件 4 の中核をほぼ満たす設計を既に持つ。単一の webhook、`EnvironmentFile` による URL の秘匿 (`0600` / root、`curl --config -` で `ps` にも出さない)、本文にホスト名・ユニット名・時刻・結果コードだけを載せて journal の抜粋を載せない方針、2xx 以外でハンドラ自身を failed にする扱い。要件 4.2 / 4.8 / 4.10 は既存実装が満たしている。

**無いこと**:

- 現在この経路に接続しているユニットは `mail-backup-pull.service` のみ。`mariadb-dump-gitea.service` は `OnFailure` を宣言していない。
- **仮想化基盤 (PVE) の通知は組み込みの `mail-to-root` のままで、実測のとおり配送に失敗して滞留している。**要件 4.5 と 4.14 の対象。
- ArgoCD に notifications controller が無い (`apps/argocd/` は ApplicationSet と kustomization のみ)。要件 4.6 は資産ゼロ。
- Garage の容量検査は Job を失敗させるだけで、Job の失敗を外へ出す経路が無い。要件 4.7 が明示的に否定する「記録のみをもって検知とみなす」状態。
- 滞留分 (n100 12 通 / hp-z440 132 通) の扱いが未決。内容は退避ジョブの結果通知であり、宛先は運用者個人のアドレス。

**Constraint**: k3s 側 (ArgoCD、CronJob) には `OnFailure` に相当する仕組みが無く、systemd の機構をそのまま流用できない。管理用 PC 上の Prometheus はこのコードベースから到達できず、要件 4.2 により通知の経路に組み入れられない (要件 4.3 はその事実の記録を求める)。hp-z440 と VPS には node_exporter が稼働しており、その収集先が到達できないホストであること自体が要件 4.13 の記録対象になる。

### 要件 5: 認証基盤の永続状態の保全

| 受入基準 | 既存資産 | 判定 |
| --- | --- | --- |
| 5.1 実体と異なる場所への複製 | **同一 PV 上** | Missing |
| 5.2 宣言対象外の情報が退避のみで保全されることの記録 | `identities.tf` の冒頭に境界の記述あり | Partial |
| 5.3 定期生成と世代数の確認 | `[online_backup]` (日次 / 7 世代) | Partial |
| 5.4 生成失敗を通知の対象とする | 無し | Missing |
| 5.5 復元の実地検証 | 無し | Missing |
| 5.6 版の情報を伴う | 未確認 | Unknown |
| 5.7 管理権限の回復経路の記録 | 無し | Missing |

**出来ていること**: Kanidm の `[online_backup]` が日次 7 世代で動く宣言を持つ。PVC には `Prune=false,Delete=false` の注釈があり、同期による削除から外れている。VM 151 は vzdump の対象に含まれるため、ゲスト単位の第 2 層は存在する。

**無いこと**: `db_path = /data/kanidm.db` と `[online_backup] path = /data/backups` が同一の PVC 上にある。当該 PVC は k3s-agent-minipc (n100 の単一 SSD) の local-path 上にあり、冗長性が無い。要件 5.1 が禁じる構成そのもの。生成失敗の通知経路も、復元の検証も、管理権限の回復経路の記録も無い。

### 要件 6: 変更の混入を止めるゲートの有効化

| 受入基準 | 既存資産 | 判定 |
| --- | --- | --- |
| 6.1 記録される前の検査 | **未有効化** | Missing |
| 6.2 作業環境での有効化の確認 | **`.git/hooks` に sample のみ** | Missing |
| 6.3 `gitops-apps` の秘匿値検査の設定 | 無し | Missing |
| 6.4 マニフェストの構文と展開の検証 | `scripts/validate-manifests.sh` + pre-commit 定義 | Partial |
| 6.5 有効化手順の再現可能な記録 | 無し | Missing |
| 6.6 新しい作業環境でも成立する宣言 | 無し | Missing |

**出来ていること**: `my-home-network` は `.pre-commit-config.yaml` (gitleaks、`--redact`、`.gitleaks.toml` に k3s ノードトークンの独自ルール) と GitHub Actions 側の 2 段の gitleaks (差分と全履歴) を持つ。`gitops-apps` は `scripts/validate-manifests.sh` を持ち、全 kustomize / helm のレンダリングと Application 名の重複を検出する。

**無いこと**: **両リポジトリとも pre-commit hook が導入されていない。**`git config core.hooksPath` も未設定。したがって記録前の検査は一度も動いていない。`my-home-network` は記録後の GitHub Actions で拾えるが、要件 6.1 が明示的に否定する「記録された後の検査のみに依存」の状態。`gitops-apps` は Gitea Actions が無効で `.github/workflows/` も空のため、**pre-commit が唯一の関門であり、それが無効なので関門がゼロ**。さらに `gitops-apps` には gitleaks の設定自体が無い (要件 6.3)。

**Constraint**: `validate-manifests.sh` は `kubectl` / `helm` / `yq` を作業環境に要求し、`helm dependency build` でネットワークを使う。要件 6.6 の「新しい作業環境でも成立する宣言」はこの依存の扱いを含む。

### 要件 7: 退役したゲストの退避の扱い

| 受入基準 | 既存資産 | 判定 |
| --- | --- | --- |
| 7.1 実機に無いゲストの退避の列挙 | 未実施 (本書で列挙) | Missing |
| 7.2 保持 / 削除の決定と記録 | 無し | Missing |
| 7.3 保持する場合の世代整理の対象外の宣言 | 無し | Missing |
| 7.4 削除前の再構築可能性の確認 | 無し | Missing |
| 7.5 対象・対象外の双方から漏れている状態の解消 | **漏れている** | Missing |
| 7.6 役目を終えた定義の残置の確認 | 未実施 | Partial |

**列挙 (実測)**:

| 群 | 世代 | 最新 | 実機のゲスト |
| --- | --- | --- | --- |
| `ct/100` | 1 | 2026-09-03T10:40:29Z | 存在しない |
| `ct/113` | 4 | 2026-09-03T14:06:05Z | 存在しない |

いずれも `pbs_backup_targets` にも `pbs_backup_excluded_targets` にも記載が無い。要件 7.5 が指す状態。

**要件 7.6 について**: `ansible/inventory` / `ansible/roles` / `terraform` / `gitops` の追跡対象を検索した範囲では、退役したゲストの名前や vmid を参照する定義は残っていない。`mariadb_dump` role は残存するが、これは Gitea DB の論理退避として現行の役目を持つ (pbs 上で稼働中、直近の生成物あり)。シークレットの棚卸しは Infisical 側のキー名の確認が必要で未実施。

### 要件 8: 宣言と実態の一致の回復

| 受入基準 | 対象の記述 | 判定 |
| --- | --- | --- |
| 8.1 退避対象の件数と内訳 | `product.md` / `tech.md` が「対象 7 件 (150/151/152/201/202/113/110)」と記述。実態は 5 件 | Missing |
| 8.2 実機に無いゲストを復元可能として記述しない | 同上が 113 を「復元可能な退避を保持」に含めている | Missing |
| 8.3 認証基盤の導入の反映 | `product.md` が「単一の認証基盤 (IdP) は存在しない」と記述。実態は Kanidm が稼働 | Missing |
| 8.4 認証の連携方式の記述 | `product.md` が「OIDC / SAML / forward auth で連携しているサービスは無い」「LDAP クライアントのロールは存在しない」と記述。実態は OIDC クライアント複数、`kanidm_unixd` role が存在 | Missing |
| 8.5 実態を正として改める | — | 手順 |
| 8.6 存在しない仕組みを除外の理由に挙げない | Gitea の除外理由 `github-offsite-backup` (要件 2.8 と同じ対象) | Missing |

steering の記述の食い違いは上記のほかにも及ぶ。`tech.md` の Backup 節は「7 件中 6 件は復元可能」「110 はディスク単位の除外実装が未了」と記述するが、実態は対象 5 件であり 113 は退役済み。`tech.md` の Storage 節は「ZFS の scrub は直近でエラー 0」と記述するが、直近の完了は約 3 か月前で以降 2 回が未実行。`tech.md` の Cluster Management 節と `product.md` の Related Repositories は概ね実態と一致している。

### 要件 9: 宣言されていない変更の正規化

第 3 節に一覧と探索方法を分けて記す。

### 要件 10: 実施における制約

手順上の制約であり、既存資産との差分ではない。ただし 10.5 (2 回続けて適用したときに 2 回目で変更が生じない) は、新たに足す機構が既存ロールの冪等性の水準に合わせる必要があることを意味する。`pbs` role の ACL の扱い (現在の状態を JSON で読んでから差分だけを発行する) が、PBS のジョブ定義を足す際の参考になる。

### 要件 11: 認証経路の健全性の回復と維持

| 受入基準 | 既存資産 | 判定 |
| --- | --- | --- |
| 11.1 成立していない経路の列挙 | 未実施 | Missing |
| 11.2 原因の実測による特定 | 管理用 PC への経路については実施済み | Partial |
| 11.3 追跡対象の管理機構への経路 | `kanidm_oauth2_basic.gitea` + Gitea 側の認証ソース | Unknown |
| 11.4 同期の管理機構への経路 | `kanidm_oauth2_public.argocd` (ブラウザと CLI の 2 つの戻り先を宣言済み) | Unknown |
| 11.5 認可の条件を緩めない | — | 手順 |
| 11.6 唯一の管理経路が依存する所属を宣言対象に含める | **`identities.tf` が所属を意図的に対象外としている** | Constraint |
| 11.7 個人識別情報を秘匿値の供給機構から与える | 無し | Missing |
| 11.8 運用者本人の資格情報での端から端までの確認 | 未実施 | Missing |
| 11.9 経路の不成立を検知できる状態 | 無し | Missing |
| 11.10 集合全体を置換する手段を用いない | 無し | Missing |
| 11.11 切り分けに必要な記録を読み取れる権限 | 未確認 | Unknown |
| 11.12 認可の条件に用いる値の形式を実発行内容と突き合わせて記録 | `claim_value` に SPN 形式を宣言済み、突き合わせの記録は design 側 | Partial |

**出来ていること**: `cloudflare_zero_trust.tf` は識別提供者に `scopes = ["openid","profile","email","groups"]` と `claims = ["groups"]` の双方を宣言し、Access のポリシーが `claim_name = "groups"` / `claim_value = "guacamole_access@kanidm.<domain>"` で判定する形になっている。`kanidm_group.guacamole_access` と、MFA を要求する `kanidm_account_policy` も宣言されている。

**Constraint (要件 11.6 と既存の設計判断の衝突)**: `terraform-kanidm/identities.tf` は冒頭で「`kanidm_person` とグループ所属を宣言しない」ことを明示的な設計判断として記録している。理由は 2 つ。(a) このリポジトリが公開されており、所属の変更のたびに個人の識別子が差分に残る。(b) provider 0.1.10 の挙動で、`members` を省略すると実際の所属を変えずに管理対象から外れる一方、明示的な空集合 `[]` は収束しない差分を出し続ける。**要件 11.6 が求める「所属を宣言の対象に含める」は、この既存の判断と正面から衝突する。**要件 11.7 (個人識別情報を秘匿値の供給機構から与える) はこの衝突を解く方向を示唆しているが、provider の (b) の挙動が「単一の所属だけを宣言し他を保持する」ことを許すかは未確認。

**要件 11.10 との関係**: 所属の一覧を集合として置換する操作は、複数の作業主体が同時に触ったときに互いの追加を消す。実装手段の選択で「対象の値のみを指定する追加 / 削除」に限る必要がある。

## 3. 要件 9 の対象の一覧 — 実装済みだが宣言されていない変更

### 3.1 探索の方法

記憶や伝聞ではなく、次の 3 つの機械的な操作で洗い出した (受入基準 9.7)。

1. **宣言の凍結時点の特定**: 両 spec の `requirements.md` の最終更新コミットを `git log -- <path>` で特定した。`mail-platform` は `f39dbc9`、`iac-hygiene-remediation` は `2539c57`。
2. **凍結後の実装変更の抽出**: 両リポジトリで凍結時点より後のコミットを列挙し、`git show --stat` で `ansible/` `terraform/` `terraform-kanidm/` `gitops/` および `gitops-apps/apps/` に触れるものだけを残した。`.kiro/` のみに触れるコミットは除外した。
3. **受入基準との突き合わせ**: 残った各変更について、その変更が満たしている性質を両 spec の `requirements.md` に対して検索し、対応する受入基準の有無を判定した。`design.md` / `research.md` にのみ根拠があるものは「宣言されていない」に分類した。
4. **補足の走査**: 追跡対象に無い操作 (実機のみで行われた変更) は上記で拾えないため、実機の状態を宣言と突き合わせて差分を探した (PBS のジョブ、PVE の通知設定、Kanidm のグループ所属、git hooks の導入状態)。

### 3.2 一覧

| # | 変更 | 位置 | 対応する受入基準 | 状態 |
| --- | --- | --- | --- | --- |
| 1 | Dovecot の `passdb static` を `{CRYPT}*` により到達不能化 | `gitops-apps/apps/mailbox/configmap.yaml` | 9.3 | 追跡対象に存在。根拠は design 側のみ |
| 2 | ClamAV を VPS から k3s の Pod へ移設 | `gitops-apps/apps/mailbox/clamav.yaml`、`ansible/roles/mailserver/templates/rspamd-antivirus.conf.j2` | 9.4 | 追跡対象に存在。**既存の受入基準 (メモリ不足なら有効化せず記録) とは異なる結末を採っている** |
| 3 | PBS のデータストア ACL の宣言化 | `ansible/roles/pbs/` | 9.5 | 追跡対象に存在。最小権限を求める受入基準が両 spec に無い |
| 4 | 退避失敗の通知 (`OnFailure=notify-failure@%n.service` と汎用ハンドラ) | `ansible/roles/systemd_failure_notify/`、`ansible/roles/mail_backup/templates/mail-backup-pull.service.j2` | 本 spec の要件 4 | 追跡対象に存在。既存の受入基準は「記録に残す」までで通知を求めていない |
| 5 | 認証済み送信のレート制限 | `ansible/roles/mailserver/templates/rspamd-ratelimit.conf.j2` | 9.6 | 追跡対象に存在。値の根拠はテンプレート内のコメントのみ |
| 6 | Cloudflare Access の識別提供者への `claims = ["groups"]` の追加 | `terraform/cloudflare_zero_trust.tf` | 11.3 / 11.12 | 追跡対象に存在。要件を経ていない |
| 7 | Kanidm の `guacamole_access` グループへの所属の復旧 | 追跡対象に無し (実機のみ) | 11.6 / 11.7 | **宣言に残っていない。IaC の管理対象外の操作** |
| 8 | Kanidm のデータ PVC への `Prune=false,Delete=false` の付与 | `gitops-apps/apps/kanidm/pvc.yaml` | 本 spec の要件 5 | 追跡対象に存在。同じ注釈をメールボックスの PV に求める受入基準は存在するが、認証基盤の PV に対応するものは無い |

**#8 は既知の 7 件に含まれていなかった。**探索の手順 2 と 3 で、`gitops-apps` の凍結後コミットのうち唯一の受入基準未対応のものとして現れた。同じ注釈がメールボックスの PV では受入基準に裏付けられているのに対し、認証基盤の PV では裏付けが無い。

### 3.3 「宣言されていない」の別の形 — 宣言はあるが機能していないもの

要件 9 の一覧とは別に、宣言と実装が食い違っている箇所を 1 件確認した。設計フェーズで扱う対象になる。

- **Garage の退避の暗号化**: `InfisicalStaticSecret` が `encryption-password` を Secret へ同期しているが、`backup.sh` も `rclone` の呼び出しもこの値を参照していない。暗号化を意図した宣言だけが存在し、実際には平文で外部の記憶領域へ置かれている。要件 2.5 に直接関わる。

## 4. 実装の方針の選択肢

決定はしない。3 つの方向と trade-off を示す。

### Option A: 既存のロールとマニフェストを拡張する

- 要件 3 を `pbs` role に足す (`proxmox-backup-manager prune-job create` / `verify-job create` / `datastore update --gc-schedule` を、既存の ACL と同じ「現状を JSON で読んでから差分だけ発行する」形で)。
- 要件 1 を `mail_backup` と `mariadb_dump` の各スクリプトに足す。
- 要件 4 を `systemd_failure_notify` の適用範囲の拡大として扱い、`mariadb_dump` にも `OnFailure` を宣言し、PVE 側は `notifications.cfg` の webhook 送信先を `proxmox_backup` role から宣言する。
- 要件 2 を `apps/garage` の CronJob の形をそのまま複製して他の対象へ広げる。

**Trade-off**
- 新しいファイルが最小で、既存の規約 (1 role = 1 コンポーネント、systemd timer + oneshot) をそのまま使える。
- `pbs` role が「インストール + データストア + ACL + prune + verify + GC」を持ち肥大化する。`tasks/` のサブファイル分割の判断が必要になる。
- 完全性の判定が `mail_backup` と `mariadb_dump` に二重化する。片方だけ直る事故が起きやすい。
- Garage の CronJob を複製すると、退避のスクリプトが対象ごとに 3 つ以上に増える。暗号化が未成立という既存の欠陥もそのまま複製される危険がある。

### Option B: 新しい責務ごとに独立した機構を作る

- 完全性の判定を単一のスクリプト (`backup_integrity` 相当の role) に切り出し、`mail_backup` / `mariadb_dump` の双方から呼ぶ。閾値は role の `defaults` に宣言する。
- 退避基盤の維持を `pbs_maintenance` 相当の独立した role にする。
- オフサイトへの複製を、対象ごとの CronJob ではなく単一の複製機構 (退避の集約先である pbs から `rclone` で送る) にする。PBS のデータストアと `gitops-apps` の実体を同じ経路に乗せられる。
- k3s 側の通知を、CronJob の失敗を拾って同じ webhook へ送る単一の機構にする。

**Trade-off**
- 責務の境界が明確で、完全性の判定も複製も 1 箇所を直せば全対象に効く。
- 要件 2 を pbs へ集約すると、hp-z440 の全損時に「複製の送り元」も同時に失われる。送り元の可用性が新たな単一障害点になる。
- role とマニフェストの数が増え、`site.yml` の適用順序の依存が増える。
- k3s 側の通知機構は既存の資産が無く、新規の作り込みになる (Job の失敗を検知して webhook を叩く仕組みをどう置くか)。

### Option C: 折衷 — 到達手段の境界で分ける

- **systemd で動くもの (pbs / PVE / gitea)**: 既存の `systemd_failure_notify` と timer の規約をそのまま拡張する (Option A)。完全性の判定だけは共有のスクリプトに切り出す (Option B)。
- **k3s で動くもの (Kanidm / Garage / 容量検査)**: 通知と複製を新しい機構として置く (Option B)。既存の Garage CronJob は、暗号化の欠陥を直したうえで共通の土台へ寄せる。
- **段階**: 第 1 段で検知 (要件 4 / 要件 6) を成立させ、第 2 段で退避基盤の維持 (要件 3) と完全性 (要件 1)、第 3 段でオフサイト (要件 2) と認証基盤 (要件 5) を扱う。要件 8 / 要件 9 は各段の完了時に反映する。

**Trade-off**
- 到達手段が異なる 2 つの世界を無理に統一しないため、どちらの規約も壊さない。
- 通知の経路が 2 つの実装を持つことになる (systemd の `OnFailure` と k3s 側の何らかの機構)。要件 4.1 の「単一の経路」は宛先の単一性で満たすことになり、実装の単一性とは別であることを設計で明示する必要がある。
- 段階を分けることで、要件 10.4 (是正中に既存の退避が失敗する時間帯の把握) の対象範囲が段ごとに小さくなる。

## 5. 規模と危険度

| 要件 | 規模 | 危険度 | 根拠 |
| --- | --- | --- | --- |
| 要件 1 完全性の検証 | M | Medium | スクリプトの拡張は既存の型に乗るが、閾値の設計と「空」の定義は対象ごとに異なる |
| 要件 2 オフサイトへの複製 | L | High | 既存の複製が暗号化されておらず作り直しに近い。4 TB の上限、対象の選定、復元の実地検証、外部の提供元への依存が絡む |
| 要件 3 退避基盤の維持 | M | Medium | 既存の `pbs` role の型に乗るが、GC と verify は実データに触れる操作であり実行時間と負荷が未知 |
| 要件 4 通知経路の一本化 | M | Medium | systemd 側は既存資産で足りる。k3s 側と PVE 側が新規。滞留分の扱いに判断が要る |
| 要件 5 認証基盤の保全 | M | High | 唯一の正が単一ボリューム上にある。復元の検証を稼働中の実体に影響を与えずに行う手段が未確立 |
| 要件 6 検査ゲートの有効化 | S | Low | 設定は既に揃っており、導入と宣言だけが欠けている |
| 要件 7 退役ゲストの扱い | S | Medium | 列挙は済んだ。削除する場合は不可逆であり、要件 10.1 の承認が要る |
| 要件 8 宣言と実態の一致 | S | Low | 記述の修正のみ。他要件の完了後に反映する |
| 要件 9 正規化 | S | Low | 一覧は本書で確定。要件としての記述に落とす作業 |
| 要件 11 認証経路 | M | High | 既存の設計判断 (所属を IaC の対象外とする) と衝突する。provider の挙動が未確認。並行作業で所属が消える危険が既知 |

## 6. 設計フェーズで調査を要する項目 (Research Needed)

### 外部の記憶領域への複製

- 既存の `rclone.conf` が指す remote の種別と、`crypt` remote を重ねられるか。既存の複製 (平文) と新しい複製 (暗号化) の移行の順序。
- 暗号化の方式の選択: `rclone crypt` remote か、書庫の生成時点での暗号化か。復元時に必要な鍵の保管場所 (Infisical に置く場合、Infisical 自体が失われた場合の復元経路)。
- 現在の使用量と、4 TB の上限に対する各対象の所要量。PBS のデータストアは 52G だが chunk の重複排除後の値であり、複製の方式 (データストアの同期か、書庫化して送るか) で所要量が変わる。
- 使用量の把握の手段 (`rclone about` が当該 remote で使えるか) と、上限接近の検知をどの経路へ流すか。
- `gitops-apps` の「退避から作業できる状態を復元できる」の定義: bare のクローンで足りるか、Gitea のインスタンスごとか。

### 退避基盤の prune / verify / GC のジョブ定義

- `proxmox-backup-manager` の `prune-job` / `verify-job` / `gc-schedule` を冪等に宣言する形。既存の ACL の扱い (現状を JSON で読んでから差分だけ発行) がそのまま使えるか、`--output-format json` が各サブコマンドで使えるか。
- verify と GC の所要時間と、vzdump のスケジュール (04:30) との干渉。データストアの実データが小さいうちに確立しておく利点。
- prune のスケジュールと `keep-last=2` の関係。vzdump 側の `prune-backups` と PBS 側の prune ジョブが二重に効く場合の扱い。
- 退役したゲストの群を prune の対象から外す手段 (namespace の分離か、群単位の保持方針か)。
- 記憶装置の検査を宣言へ取り込む方法と、配布物の cron との二重化の回避。未実行の検知の手段 (`zpool status` の最終 scrub 時刻を読む定期の確認)。

### 通知経路の実現手段

- PVE の通知の宛先を webhook にする手段。`notifications.cfg` の webhook エンドポイントを API から冪等に宣言できるか。組み込みの `mail-to-root` を無効化する手順と、滞留分の扱い (破棄するか、内容を確認してから破棄するか)。
- ArgoCD の同期失敗を外へ出す手段。notifications controller を導入するか、Application の状態を定期的に確認する仕組みを別に置くか。ArgoCD 自体が落ちている場合に検知が失われる点の扱い。
- k3s の CronJob (Garage の容量検査、退避) の失敗を webhook へ送る手段。
- 通知の宛先が単一の webhook であることの記録と、当該の宛先が失われた場合の扱い。
- 意図的な事象での到達確認 (要件 4.9) をどう行うか。既存の `notify-failure.sh` は 2xx 以外で自身を failed にするため、失敗時の観測点は journal になる。

### 認証経路

- Kanidm の provider が「特定の所属だけを宣言し、他の所属を保持する」ことを許すか。`members` の扱いが集合の置換になるなら要件 11.10 と衝突する。
- 個人の識別子を秘匿値の供給機構から与えたときに、Terraform の state (HCP) と plan の出力に識別子が現れないか。
- Gitea と ArgoCD への認証経路が現在成立しているかの実測 (要件 11.1 / 11.3 / 11.4)。定義は揃っているが、成立の確認は未実施。
- 経路の不成立を検知する手段 (要件 11.9)。認可の応答を定期的に確認する仕組みは、認証情報を要するため通知経路とは別の設計になる。

### その他

- Kanidm の退避の復元検証を、稼働中の実体に影響を与えずに行う方法 (別 namespace への一時的な展開など)。
- Kanidm の退避成果物が版の情報を伴うか (要件 5.6) の確認。
- 管理権限の回復経路 (要件 5.7) が `kanidmd recover-account` で成立するか、それがコンテナ内の操作を要する点の扱い。

## 7. 既存の構造との衝突

新たに足す機構が既存の規約と噛み合わない箇所を挙げる。

1. **要件 11.6 と `identities.tf` の設計判断**: 所属を宣言の対象に含めることは、当該ファイルが明示的に採らなかった方針である。公開リポジトリに個人の識別子を残さないという理由と、provider の挙動という理由の 2 つがある。要件 11.7 は前者への回答になりうるが、後者は未検証。**この衝突の解消は設計フェーズの主要な判断になる。**

2. **要件 3 と `pbs` role の責務**: 1 role = 1 コンポーネントの原則の下で `pbs` role は既に「インストール + サービス + データストア + ACL」を持つ。維持のジョブを足すと責務が広がる。`structure.md` は「role 内が肥大化したら `tasks/` をサブファイル分割」を規定しており、この規約に従うか別 role にするかの判断が要る。

3. **要件 4 と到達手段の分断**: `systemd_failure_notify` は systemd の `OnFailure` を前提としており、k3s の CronJob と ArgoCD には適用できない。要件 4.1 の「単一の経路」を実装の単一性と読むと、既存資産を捨てることになる。宛先の単一性と読む場合はその解釈を設計に明示する必要がある。

4. **要件 2 と `gitops-apps` の情報源**: `structure.md` は「通常の運用では本リポジトリは別 repo の内容を管理しない」と規定する。`gitops-apps` の実体を複製の対象に含めると、複製の機構をどちらのリポジトリに置くかで規約に触れる。spec の Boundary Commitments が対象範囲を定めるという例外規定はあるが、恒久的な機構の置き場所は別の判断になる。

5. **要件 6.6 と作業環境の依存**: `gitops-apps` の検査は `kubectl` / `helm` / `yq` を要求し、`helm dependency build` がネットワークを使う。「新しい作業環境でも成立する宣言」は、これらの依存を宣言に含めるか、検査を軽くするかの判断を含む。

6. **要件 1 と PBS の重複排除**: 「書庫の大きさを保護対象の実測値と突き合わせる」は、chunk 単位で重複排除される PBS の世代に対しては群のディレクトリの大きさでは測れない。PBS 側と、書庫を直接作る側 (`mail_backup` / `mariadb_dump`) とで、判定の実装が別になる。

7. **要件 5.1 と local-path の制約**: 認証基盤の PV は local-path であり、複製先を別のノード / 別の装置に置くには、PV の外へ書き出す機構 (pull 型の取り出し) が要る。`mail_backup` が既に同じ形 (制限付きの鍵と強制コマンドで PV を tar して pbs が引く) を確立しており、これが最も近い先例になる。

## 8. 設計フェーズへの引き継ぎ

- 要件 6 は資産が揃っており最も早く閉じられる。要件 4 の検知が成立する前に他の是正を進めると、是正中の失敗に気づけない。**検知 (要件 4) と関門 (要件 6) を先に置く順序**が、要件 10.4 の制約とも整合する。
- 要件 1 の失敗は既に起きている (項目数 1 の書庫が最新世代として採用されている)。世代保持数が 14 であるため、同じことが繰り返されれば有効な世代が押し出される。要件 1 の緊急度は要件 2 より高い可能性がある。
- 要件 9 の一覧は本書の第 3 節で確定した (8 件)。要件としての記述への落とし込みは、既存の受入基準 9.3-9.6 が 4 件を指しており、残り 4 件 (#4 の通知、#7 の所属、#8 の PVC 注釈、および 3.3 の暗号化の不成立) の扱いを決める必要がある。
- 要件 11 の衝突 (第 7 節の 1) は、設計より先に provider の挙動の実測が要る。実測なしに方針を決めると、収束しない差分か、他の所属の消失のどちらかを招く。
