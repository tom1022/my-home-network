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
