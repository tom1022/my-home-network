# 移行の実測記録

## リハーサルの取り出し (タスク 5.3、2026-11-08)

取り出しは k3s-agent-z440 のホストから、移行元 VM 105 に対して読み取りだけで行った。

### ファイル (rsync)

- コマンド: `rsync -aHAX --numeric-ids --exclude='/*/files_trashbin/'` で `/media/hdd0/` から `/var/lib/nextcloud/data/` へ
- rsync 3.2.7、終了コード 0
- 所要時間: 7232 秒 (約 2 時間 0 分)、平均 約 52 MB/s
- 転送: 通常ファイル 450,754 件 (ディレクトリ 276,718 件を含め総数 727,472 件)、376,507,040,120 バイト (約 351 GiB)。受信 376,639,717,123 バイト
- 移行先 `data/` の実サイズ: 376,545,358,056 バイト、通常ファイル 450,754 件 (転送件数と一致)、所有者 33:33
- 利用者ディレクトリ直下の `files_trashbin/` は 0 件 (除外が効いている)

### 設定・DB

- `config.php`: 1,649 バイト、`migration-staging/` (root:root 0600) に配置
- `mysqldump --single-transaction --default-character-set=utf8mb4`: root の unix socket 認証で成功。出力は ssh 経由で `migration-staging/nextcloud.sql` に受けた (207,538,168 バイト、末尾に `-- Dump completed`)。標準エラー出力は空
- `secret` (48 文字) と `passwordsalt` (30 文字) を Infisical prod の `NEXTCLOUD_SECRET` / `NEXTCLOUD_PASSWORDSALT` に登録。`nextcloud-secrets` の `NEXTCLOUD_SECRET` が 10 文字 (`<no value>`) から 48 文字になったことを確認

### 移行元への書き込みが無いことの確認

- ssh で移行元に実行したのは `df`、`which`、`mysqldump` (読み取り) だけ
- `/media/hdd0` の使用量: 開始前 666,350,362,624 バイト、終了後 666,350,391,296 バイト (差 +28,672 バイト)。移行元は稼働中の VM であり、ログや DB の更新による増分で、今回の操作によるものではない

## アプリの分類 (タスク 5.2、2026-11-08)

移行元のダンプ (`oc_appconfig` の `enabled` と `installed_version`) と、Nextcloud 30.0.17 の `core/shipped.json` (`shippedApps`、`alwaysEnabled`) から、同梱でないアプリを洗い出した。

### 分類表

継続するアプリは 35 対応版を各段で入れ直す。

| アプリ | 扱い | 35 対応版 / データの扱い |
|-----|-----|-----|
| calendar | 継続 | 6.6.4 |
| contacts | 継続 | 8.9.3 |
| deck | 継続 | 1.19.2 |
| tasks | 継続 | 0.18.1 |
| mail | 継続 | 5.12.6 |
| files_external | 継続 | `/SMB` の接続先を NAS の samba に替える |
| user_oidc | 新規 | 8.11.0 (8.9.0 は 35 非対応) |
| extract | 継続しない | 31 以降の対応版が無い。利用者のファイルは残る |
| metadata | 継続しない | 34・35 の対応版が無い。利用者のファイルは残る |
| richdocuments、richdocumentscode | 継続しない | 利用実績なし。利用者のファイルは残る |
| maps | 継続しない | 位置の一覧は写真から再生成できる派生データで、保持しない。写真と軌跡のファイルは残る |
| recognize | 継続しない | 分類データは派生データで、保持しない。資源の負担が大きい |
| drawio | 継続しない | `.drawio` ファイルは残る |

### 移行元で有効だった非同梱アプリ

| アプリ | installed_version | 分類 |
|-----|-----|-----|
| calendar | 5.0.6 | 継続 |
| contacts | 6.1.1 | 継続 |
| deck | 1.14.2 | 継続 |
| tasks | 0.16.1 | 継続 |
| mail | 4.0.6 | 継続 |
| drawio | 3.0.3 | 継続しない |
| extract | 1.3.6 | 継続しない |
| maps | 1.5.0 | 継続しない |
| metadata | 0.21.0 | 継続しない |
| recognize | 8.1.1 | 継続しない |
| richdocuments | 8.5.2 | 継続しない |
| richdocumentscode | 24.4.902 | 継続しない |

files_external は同梱のアプリで、移行元で有効だった。user_oidc は移行元に無く、新規に入れる。

### 移行元で無効だった非同梱アプリ

移行元で無効、Configure の対象外 (有効化しない)。いずれも分類表に無い。

| アプリ | installed_version |
|-----|-----|
| breezedark | 29.0.0 |
| files_mindmap | 0.0.27 |
| files_rightclick | 1.6.0 |
| forms | 4.3.4 |
| spreed | 11.2.1 |

### 分類に無いアプリ

無し (有効だった非同梱アプリ 12 件はすべて分類表にある)。分類に無い有効アプリがあった場合の無効化は、Configure がタスク 6.5 で行う。

### 35.0.2 対応の確認 (2026-11-08)

`https://apps.nextcloud.com/api/v1/platform/35.0.2/apps.json` で、表の版が存在し 35.0.2 に対応することを確かめた。

| アプリ | 版 | 対応範囲 |
|-----|-----|-----|
| calendar | 6.6.4 | `>=32.0.0 <36.0.0` |
| contacts | 8.9.3 | `>=33.0.0 <37.0.0` |
| deck | 1.19.2 | `>=35.0.2 <36.0.0` |
| tasks | 0.18.1 | `>=31.0.0 <36.0.0` |
| mail | 5.12.6 | `>=32.0.0 <36.0.0` |
| user_oidc | 8.11.0 | `>=29.0.0 <36.0.0` |

deck 1.19.1 は一覧から消えており、1.19.2 に置き換わっている。

## 31.0.14 への更新と PostgreSQL への変換 (タスク 6.2、2026-11-08)

イメージ: `nextcloud:31.0.14-apache@sha256:07ec73cc816e58d6f45a162cd53ef886462c29271a23fc68d0124cec276e3767` (index digest。Docker Hub のレジストリ API で確認)。

### 1 回目の失敗とやり直し

1 回目の 31 の upgrade は、継続しないアプリが `enabled=yes` のまま残っていたため、Updater が非互換として無効化した後に App Store から入れ直し、max-version 30 の recognize が psr/log 3 の 31 で Fatal となって止まった。対策として Stage で upgrade 前に継続しないアプリを `occ app:disable` で `enabled=no` にし (design 更新済み)、Stage をやり直して再実行した。やり直した実行では `Disabled incompatible app` は deck の 1 行だけで、upgrade は成功した。

### upgrade で無効化され更新されたアプリ

| アプリ | 30.0.17 | 31.0.14 での扱い | 更新後の版 |
|-----|-----|-----|-----|
| deck | 1.14.12 | 非互換として無効化 → 同じ実行で更新され有効 | 1.15.12 |
| mail | 5.5.17 | 更新 | 5.6.21 |
| tasks | 0.16.1 | 更新 | 0.18.1 |
| calendar | 5.5.24 | 変わらず | 5.5.24 |
| contacts | 7.3.19 | 変わらず | 7.3.19 |

user_oidc は `occ app:install user_oidc` で 8.13.0 が入った (App Store の最新の 31 対応版)。`occ app:update --all` は実行していない。変換直前に継続アプリ 5 つ、user_oidc、files_external が有効なことを確かめた。

### 変換

保守モードを ON にしてから、`occ db:convert-type --no-interaction --all-apps --port 5432 pgsql nextcloud nextcloud-db-rw nextcloud` を実行した。パスワードは app コンテナ内で `umask 077` の一時ファイルに改行なしで書き (`printf "%s"`)、標準入力へリダイレクトして渡し、終了後に消した。`readPassword` は標準入力を非ブロッキングで読み trim せずに使うため、パイプや改行付きでは認証に失敗する。`--no-interaction` は「変換されないテーブル (無効アプリのもの) があっても続ける」確認に必要。`HOME=/var/www` は libpq が `/root/.postgresql` を読む権限エラーを避けるため。変換後は `dbtype` が `pgsql`、`dbhost` が `nextcloud-db-rw:5432`。所要時間は変換が約 12 分、upgrade のロールアウトが約 1 分。

### 行数の突き合わせ

| テーブル | 結果 |
|-----|-----|
| oc_filecache | 一致 |
| oc_share | 一致 |
| oc_calendarobjects | 一致 |
| oc_calendars | 一致 |
| oc_cards | 一致 |
| oc_addressbooks | 一致 |
| oc_users | 一致 |
| oc_accounts | 一致 |
| oc_preferences | 一致 |
| oc_appconfig | 一致 (変換直前の計測の後に MariaDB の行が増えたため、変換後に両側を再計測して一致を確認) |
| oc_mail_accounts | 一致 |
| oc_mail_messages | 一致 |
| oc_deck_assigned_labels、oc_deck_assigned_users、oc_deck_attachment、oc_deck_board_acl、oc_deck_boards、oc_deck_cards、oc_deck_labels、oc_deck_sessions、oc_deck_stacks | 一致 (存在する 9 テーブルを個別に比較) |
| oc_files_versions | 一致 |

## 32 から 35 への段階更新 (タスク 6.3、2026-11-08)

32.0.15、33.0.10、34.0.5、35.0.2 の順にイメージのタグを変える commit を 1 段ずつ積んだ。4 段とも upgrade は成功し、Pod は再起動せず、各段の後に `cron.php` を 3 回実行して終了コードはすべて 0 だった。`occ app:update --all` は実行していない。

### 段ごとの結果

| 段 | イメージ (index digest) | upgrade の所要時間 (起動ログの `Initializing` から `Update successful`) | upgrade で無効化 → 同じ実行で更新されたアプリ | 同じ実行で App Store から更新されたアプリ |
|-----|-----|-----|-----|-----|
| 32.0.15 | `nextcloud:32.0.15-apache@sha256:68feaa8992524ac26b4c00194b81c1ae6dc8e9f412ac82de0c5f4d4a2ee4bbcd` | 約 52 秒 | deck | calendar、contacts、mail、deck |
| 33.0.10 | `nextcloud:33.0.10-apache@sha256:1a18e5248b836a2f925ce553bd28d7dd69b0205632372f4c506356342182be8e` | 約 35 秒 | deck | contacts、deck |
| 34.0.5 | `nextcloud:34.0.5-apache@sha256:b89746a4febc93de82141921417f43b0d5ce69c3746feb485372559e9fbeec3f` | 約 42 秒 | deck | deck |
| 35.0.2 | `nextcloud:35.0.2-apache@sha256:d88929dc8386420b8963f86cabb667fdaf733eef9dcf8fc98e226801a32c023c` | 約 41 秒 | deck | deck |

各段で `occ status` は目標の版、`needsDbUpgrade` false、`maintenance` false を返した。継続しないアプリ (drawio、extract、maps、metadata、recognize、richdocuments、richdocumentscode) は、各段で `occ app:list --shipped=false` に有効としても無効としても現れず、`custom_apps/` にもディレクトリが無い (calendar、contacts、deck、mail、tasks、user_oidc の 6 つだけ)。files_external は各段で有効 (32 は 1.24.1、33 は 1.25.1、34 は 1.26.0、35 は 2.0.0)。

### 継続アプリと user_oidc が導入された版

| アプリ | 31 | 32 | 33 | 34 | 35 | 版の表の 35 列 |
|-----|-----|-----|-----|-----|-----|-----|
| calendar | 5.5.24 | 6.6.5 | 6.6.5 | 6.6.5 | 6.6.5 | 6.6.4 |
| contacts | 7.3.19 | 8.3.21 | 8.9.5 | 8.9.5 | 8.9.5 | 8.9.3 |
| deck | 1.15.12 | 1.16.9 | 1.17.8 | 1.18.6 | 1.19.2 | 1.19.2 |
| tasks | 0.18.1 | 0.18.1 | 0.18.1 | 0.18.1 | 0.18.1 | 0.18.1 |
| mail | 5.6.21 | 5.13.1 | 5.13.1 | 5.13.1 | 5.13.1 | 5.12.6 |
| user_oidc | 8.13.0 | 8.13.0 | 8.13.0 | 8.13.0 | 8.13.0 | 8.11.0 |

6 つとも 35 で版の表の 35 列以上であり、すべて有効。

### Mail の版

32 の段で mail は 5.6.21 から 5.13.1 に更新され、要件の 5.10.14 以上を満たした。33・34・35 でも 5.13.1 のまま有効で、35.0.2 の有効化時の DB 移行を含む upgrade は成功している。

### Configure への反映

deck 1.19.1 は App Store から消えているため、gitops-apps の `configure.sh` の `KEEP_APPS` を `deck:1.19.2` に直した。
