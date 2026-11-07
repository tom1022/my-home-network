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
