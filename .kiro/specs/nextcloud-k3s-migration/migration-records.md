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

## ゴミ箱の削除と対象外のアカウントの削除 (タスク 6.4、2026-11-08)

### 判定の基準と結果

- 基準: 運用者本人のアカウントだけを残す (2.1)。もう一方が、`files/` にファイルを持たず、カレンダー・連絡先の中身とメール設定を持たず、最終ログインが 1 年以上前であれば対象外とする。アカウント作成時に自動で入る初期ファイル (mtime が作成時刻の数秒内) だけのものはデータを持たないとみなした。自動生成の空のカレンダー・アドレス帳だけを持つ場合も、データを持たないに含める。
- 結果: 照会した各項目 (ファイル、共有、カレンダーとその中身、アドレス帳とその中身、メール設定、最終ログイン) で、片方だけがデータを持ち、もう片方は上の基準を満たした。基準を満たした側を対象外と判定し、`occ user:delete` で削除した。

### ゴミ箱 (2.3)

`occ trashbin:cleanup --all-users` を実行した。`oc_files_trash` の行数は 0 になり、各アカウントの `files_trashbin/files` は空か存在しない。

### 削除後の照会

次の表に、削除した対象外のアカウントの行が残っていない (0 行) ことを確かめた: `oc_users`、`oc_share` (uid_owner・uid_initiator・share_with)、`oc_calendars`・`oc_addressbooks` (principaluri)、`oc_filecache` (`home::<uid>` のストレージ ID)、`oc_storages`、`oc_mounts`、`oc_preferences`、`oc_accounts`、`oc_mail_accounts`。データディレクトリ `/media/hdd0/<uid>` も消えた。`oc_users` の行は運用者のアカウントだけになった。

## ファイルの突き合わせ (タスク 7.1、2026-11-08)

移行対象のアカウント 1 つについて、移行元 (VM 105 の `/media/hdd0/<uid>/`、稼働中、読み取りのみ) と移行先 (k3s-agent-z440 の `/var/lib/nextcloud/data/<uid>/`、2026-11-08 未明の rsync の写し) の `files/` と `files_versions/` を突き合わせた。

### 方法

- 件数と合計サイズ: 両側で `find <dir> -type f -printf '%s\n'` の件数と合計を数えた。
- 内容: 両側で `find files files_versions -type f -print0 | sort -z | xargs -0 sha256sum` の一覧を作り、パスをキーに比べた。2 本は z440 の `systemd-run` で並行に走らせた (移行元側は ssh で VM 105 から標準出力で受けた)。一覧と差異のパス一覧は z440 の `/var/lib/nextcloud/migration-staging/` に root 0600 で残している。パスは個人情報を含みうるためこの記録には書かない。

### 結果

| 項目 | 結果 |
|-----|-----|
| `files/` の件数・合計サイズ | 一致 (差 0 件、0 バイト) |
| `files_versions/` の件数・合計サイズ | 一致 (差 0 件、0 バイト) |
| SHA-256 (a) 両側にありハッシュ一致 | 全件 (両側の一覧は同数) |
| (b) ハッシュ不一致 | 0 件 |
| (c) 移行元にだけある | 0 件 |
| (d) 移行先にだけある | 0 件 |

差異が 0 件のため、取り出し後の変更で説明できる差異も、説明できない差異も無い。要件 2.5〜2.7 の突き合わせは、この時点の写しについて満たされた。移行元は稼働を続けているため、切り替え時の最終差分の後に再度突き合わせる必要がある。

### 所要時間

SHA-256 の一覧の作成は移行元側・移行先側とも約 37 分 (並行)。比較は数秒。

## 公開経路と管理画面の状態 (タスク 7.3、2026-11-08)

これはリハーサルの実測で、切り替え前の状態を対象にした。リクエストは宅内のワークステーションから送ったが、公開 DNS が VPS に解決されるため、VPS を経由する宅外と同じ経路を通った (送信元は宅のグローバル IP)。

### 公開経路

| 項目 | 結果 |
|-----|-----|
| `https://cloud.fickledev.com/status.php` | HTTP 200、証明書の検証結果 0 (成功)。本文は `installed: true`、`maintenance: false`、`versionstring: 35.0.2` |
| `http://cloud.fickledev.com/` | 301、`Location: https://cloud.fickledev.com/` (応答の `Server` は nginx) |
| 証明書 | SAN は `*.fickledev.com`、発行者は Let's Encrypt (CN=YR1)、有効期間は 2026-11-02 から 2027-01-31 |

### Traefik のアクセスログの送信元

| エントリポイント | リクエスト | ログの送信元 | 判定 |
|-----|-----|-----|-----|
| `nextcloud` | `GET /status.php` (ルータ `nextcloud-nextcloud`) | 利用者のアドレス (リクエスト元のグローバル IP と一致) | 4.7 を満たす。VPS の tailnet アドレスに置き換わっていない |
| `websecure` | `GET /healthz` (`argocd.fickledev.com`、認証不要) | k3s-server 上の `svclb-traefik` の Pod アドレス (10.42.0.76)。LAN 内から LoadBalancer 経由で入ったため | 既存の挙動。HelmChartConfig が `websecure` に値を足していないこと (`forwardedHeaders.trustedIPs: []` は `nextcloud` ポートの設定) を確認した |
| `websecure` (Cloudflare Tunnel 経由) | `hermes` ルータの複数行 | cloudflared の Pod アドレス (10.42.2.22) | 既存の挙動 |

design.md には `websecure` の送信元の期待値が具体値で書かれていない (「変わらないこと」だけ)。導入前のログは取得していないため、「導入前と同じ形」は、`websecure` の設定に差分が無いことと、送信元がクラスタ内のプロキシ (svclb、cloudflared) のアドレスであることから判断した。導入前後のログの直接比較は未実施。

### セキュリティと設定の警告 (`occ setupchecks`)

69 項目中 success 62、info 5、warning 2。error は 0。

| 区分 | 項目 | 内容 | 原因の見立て |
|-----|-----|-----|-----|
| warning | MimeTypeMigrationAvailable | mimetype の移行が可能 | 移行したデータに対する通常の保守項目。プロキシ・ホスト名とは無関係 |
| warning | DatabaseHasMissingIndices | 省略可能なインデックスが未作成 | アップグレード後の保守項目 (`occ db:add-missing-indices`)。プロキシ・ホスト名とは無関係 |
| info | DaemonCheck (AppAPI) | 既定のデプロイデーモン未登録 | 外部アプリを使わないため該当しない |
| info | TwoFactorConfiguration | 2 要素認証が強制されていない | 運用方針の項目 |
| info | ServerIdConfig | `serverid` 未設定 | 単一 PHP サーバーのため不要 |
| info | BruteForceThrottler | リモートアドレスを判定できない | CLI にはクライアントの接続が無いための表示 |
| info | ForwardedForHeaders | リモートアドレスを判定できない | 同上 |

リバースプロキシとホスト名の設定: `trusted_proxies` は `10.42.0.0/16`、`forwarded_for_headers` は `HTTP_X_FORWARDED_FOR`、`overwriteprotocol` は `https`、`overwrite.cli.url` は `https://cloud.fickledev.com`、`trusted_domains` は `cloud.fickledev.com` のみ。`overwritehost` は未設定。

CLI で判定できない項目: BruteForceThrottler と ForwardedForHeaders はブラウザからのリクエストの `REMOTE_ADDR` で判定されるため、CLI では info になる。この 2 項目と、ブラウザのリクエストで判定される他の項目 (HTTPS 判定、ヘッダ、WebDAV 等) は、管理画面での表示を確認していないので、リバースプロキシ起因の警告が無いことは CLI の範囲では確認できたが、管理画面では未検証。

### 背景ジョブ

- `backgroundjobs_mode`: `cron`
- `lastcron`: 1794119703 (2026-11-08 15:35:03 JST)。確認時刻 15:36 の約 1 分前で、定期的に実行されている。
- 管理画面での表示は未検証 (ブラウザのログインが必要なため)。

### 未検証の項目

- 管理画面の「セキュリティと設定の警告」の表示 (ブラウザのログインが必要)。CLI の `setupchecks` で代替した範囲は上記のとおり。
- 管理画面での背景ジョブの最終実行時刻の表示。
- `websecure` の送信元の導入前後の直接比較。
- 実際の宅外の回線 (携帯回線等) からの接続。今回は宅内のワークステーションから VPS を経由した。

## アカウントの付け替え (タスク 6.7、2026-11-08)

### 実行

- `reassign-account.sh` (gitops-apps `be255d7`・`ad87b16`・`a8b83bf`) を移行先で実行した。最初の実行は `files:transfer-ownership --move` が `Destination path does not exists or is not empty` で止まった。全員向けの外部ストレージ `/SMB` のマウントポイントがホームの中身に数えられたため。直前に `/SMB` の設定を外す処理を足して再実行した。
- バージョン履歴は新 uid に追従しなかった (occ にユーザーのセッションが無く `files_versions` の移動フックが働かない)。設計どおり引き継がず、旧 uid の削除で消した。
- 所要時間は、ファイルの移動 (同一ファイルシステム内の rename) を含めて各実行とも 1 分未満。
- 2 回続けて実行し、2 回目は旧 uid が無いため全体が飛ばされた。

### 照合

- 移す前の旧 uid と移した後の新 uid で、`files/` のファイル数と合計バイト数、カレンダーごとのオブジェクト数、Deck のボード数、共有先のファイルが存在する共有の数がそれぞれ一致した。削除済みのファイルを指していた共有は旧 uid の削除で消えた。
- 旧 uid は存在せず、admin グループのメンバーは新 uid だけである。
- ユーザー設定は設計の除外分を除いて移った。
- `/SMB` は Configure (c) で作り直され、新 uid から見える。

### 資格情報と Mail

- Configure (e) が新 uid でアプリパスワードを発行し、Infisical の `NEXTCLOUD_MAIL_PROVISIONING_AUTH` を値を表示せずに登録し直した。登録した値と k8s の Secret の値が一致することをハッシュで確かめた。
- `mail-provisioning-rehearsal-2` (gitops-apps `7228754`) が成功し、新 uid に provisioning の Mail アカウントが付いた。
