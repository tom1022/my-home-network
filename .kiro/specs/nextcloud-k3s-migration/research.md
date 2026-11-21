# Research & Design Decisions: nextcloud-k3s-migration

## Summary

- **Feature**: `nextcloud-k3s-migration`
- **Discovery Scope**: Complex Integration (稼働中の宣言外 VM からのデータ移行 + 5 段のメジャーアップグレード + DB の種別変換 + 新しい公開経路 + 認証統合 + 退避経路の新設)
- **Key Findings**:
  - **到達させる版は Nextcloud 35。**2026-10-29 時点の保守対象は 33 / 34 / 35 で、メジャーは 4 か月ごとに出て 1 年保守される。移行元の 30.0.2 からは 30.0.17 → 31.0.14 → 32.0.15 → 33.0.10 → 34.0.5 → 35.0.2 の 6 段になる。35 の保守期限は 2027-09。
  - **PostgreSQL 17 は 31〜35 の全段で公式の対応範囲に入る。**MariaDB 10.11 は 30・31 の対応範囲に入る。変換を 31 で行えば、各段の組み合わせが公式の対応範囲から外れない。公式イメージの PHP は 31・32 が 8.3、33 が 8.4、34・35 が 8.5 で、いずれも各版の対応範囲に入る。
  - **`?direct=1` を付ければ、どの設定でもパスワードでログインできる。**`user_oidc` の `allow_multiple_user_backends=0` も、本体の `hide_login_form` も、フォームを隠すだけで受け付けは止めない。要件 5.7 を満たすには、入口でパスワードログインの POST を拒否し、`token_auth_enforced` で DAV の基本認証のパスワードも拒否する必要がある。
  - **k3s の既存の Traefik Service は ServiceLB (svclb) が ClusterIP へ DNAT するため、Traefik から見える接続元は VPS にならない。**PROXY protocol の `trustedIPs` を VPS の tailnet アドレスに絞るには、新しいエントリポイントを `externalTrafficPolicy: Local` の NodePort Service で出す必要がある。Kanidm の LDAPS と mailbox の IMAPS が同じ形 (NodePort + Local) で既に VPS から到達しており、tailnet アドレスが保たれることも実証済み。
  - **Beszel の binary 版 agent は、`EXTRA_FILESYSTEMS` を与えない限りルート以外のファイルシステムを監視しない。**`k3s-agent-z440` の agent は `LISTEN` と `KEY` しか持たないため、現状では `/var/lib/nextcloud` の使用率が `Disk` アラートの対象に入っていない。
  - **restic は空のパスワードのリポジトリを `--insecure-no-password` で扱える (0.17.0 以降)。**`restic copy` の重複排除にはチャンカーのパラメータを揃える必要があり、後から作るリポジトリを `init --from-repo <先に作ったリポジトリ> --copy-chunker-params` で作る。本 spec では GDrive 側が先にできるため、宅内側をこの形で作る。

## Research Log

### 1. 到達させるメジャーバージョンと保守期間

- **Context**: 要件 12.1 は完了時点で保守期間内の版を求め、12.2 はメジャーを飛ばさない段階的な更新を求める。
- **Sources Consulted**:
  - nextcloud/server wiki `Maintenance-and-Release-Schedule.md` (2026-10-15 更新)
  - nextcloud/server wiki `Releases-and-PHP-versions.md`
  - nextcloud/documentation `stable35/admin_manual/maintenance/upgrade.rst`
  - nextcloud/server の git タグ
- **Findings**:
  - 「New major versions are published every four months and are supported for one year」。保守中は 33 (Hub 26 Winter、2027-02 まで)、34 (Hub 26 Spring、2027-06 まで)、35 (Hub 26 Summer、2026-09-16 公開、2027-09 まで)。
  - 各メジャーの最終の点版は 30.0.17 / 31.0.14 / 32.0.15 / 33.0.10 / 34.0.5 / 35.0.2 (2026-10-29 時点のタグ)。
  - upgrade.rst は、次のメジャーへ進む前に現行メジャーの最新の点版へ上げること、メジャーを飛ばせないこと、メジャー更新の後に背景ジョブの移行が終わるまで `cron.php` を 2〜3 回回すことを求める。
- **Implications**: 到達先は 35。経路は 30.0.2 → 30.0.17 → 31.0.14 → 32.0.15 → 33.0.10 → 34.0.5 → 35.0.2 の 6 段。各段の後に `cron.php` を回す。35 も 2027-09 に保守が切れるため、年 1 回以上のメジャー更新が恒常運用になる。

### 2. 各段の DB・PHP の対応範囲

- **Context**: 要件 12.9 は各段の組み合わせを公式の対応範囲に収めることを求める。
- **Sources Consulted**: nextcloud/documentation `stable31`〜`stable35` の `admin_manual/installation/system_requirements.rst`、nextcloud/docker の各版の `apache/Dockerfile`
- **Findings**:

  | 版 | MariaDB | PostgreSQL | PHP (対応) | 公式イメージの PHP |
  |----|---------|-----------|-----------|----------------|
  | 30 | 10.11 を含む | — (本 spec では使わない) | 8.1〜8.3 | 8.3 |
  | 31 | 10.6 / 10.11 / 11.4 | 13〜17 | 8.1〜8.4 | 8.3 |
  | 32 | 10.6 / 10.11 / 11.4 | 13〜17 | 8.1〜8.4 | 8.3 |
  | 33 | 10.6〜11.8 | 14〜18 | 8.2〜8.5 | 8.4 |
  | 34 | 10.6〜11.8 | 14〜18 | 8.2〜8.5 | 8.5 |
  | 35 | 10.11〜12.3 | 14〜18 | 8.3〜8.5 | 8.5 |

  - nextcloud/docker の master は 32〜35 だけを持つ。31 は「Remove EOL 31」で消えたが、Docker Hub のタグ `31.0.14-apache` (2026-03-19) と `30.0.17-apache` (2025-11-21) は残っている。
- **Implications**: MariaDB 10.11 で 30・31 を動かし、31 で PostgreSQL 17 へ変換し、32 以降は PostgreSQL 17 で進める。どの段も公式の対応範囲に収まる。

### 3. `occ db:convert-type`

- **Context**: MariaDB から PostgreSQL への変換手段の確認。
- **Sources Consulted**: nextcloud/server `stable31` と `stable35` の `core/Command/Db/ConvertType.php`、nextcloud/documentation `stable31/admin_manual/configuration_database/db_conversion.rst`
- **Findings**:
  - コマンドは 31・35 の両方に存在する。拒否するのは変換先が `sqlite3` の場合だけで、変換元の種別は制限しない。文書の例は SQLite からの変換だが、実装は汎用。
  - 変換中は自分で `maintenance` を true にし、終わると false に戻す。失敗時も false に戻してから例外を投げる。
  - `--all-apps` で無効化中のアプリのテーブルも変換する。削除済みアプリのテーブルは変換しない。`--clear-schema` で変換先のスキーマを消してからやり直せる。`--chunk-size` で 1 クエリあたりの行数を変えられる。
  - 成功すると `config.php` の `db*` を自動で書き換える。
- **Implications**: 変換は 31 の段で `--all-apps` を付けて行う。失敗時は `--clear-schema` で変換先を空にしてやり直せるため、変換元 (一時 MariaDB) を壊さずに再試行できる。

### 4. 公式 Docker イメージのふるまい

- **Context**: Kustomize で公式イメージを使う場合と Helm chart を使う場合の比較、および段階的な更新との噛み合い。
- **Sources Consulted**: nextcloud/docker の `docker-entrypoint.sh`、`31/apache/Dockerfile` (削除直前のコミット)、`35/apache/Dockerfile`、nextcloud/helm のリリース
- **Findings**:
  - エントリポイントは `/var/www/html/version.php` から導入済みの版を読み、イメージの版が 1 メジャーだけ新しければ `occ upgrade` を自動で実行する。2 メジャー以上離れていると起動を拒否する。
  - 導入済みの版が読めない (空のボリューム) 場合はコードを `/usr/src/nextcloud` から同期し、`config` などのディレクトリは空のときだけ埋める。管理者の環境変数が無ければ自動導入はしない。
  - Apache 版は `remoteip` を有効にし、`RemoteIPHeader X-Real-IP` と私設アドレス帯 (10/8、172.16/12、192.168/16) を内部プロキシとして信頼する。`LimitRequestBody` は `APACHE_BODY_LIMIT` (既定 1073741824) で、PHP の `upload_max_filesize` / `post_max_size` は `PHP_UPLOAD_LIMIT` (既定 512M)、`memory_limit` は `PHP_MEMORY_LIMIT` (既定 512M)。
  - イメージは `/cron.sh` (busybox crond で 5 分ごとに `cron.php`) を持つ。
  - nextcloud/helm の最新は `nextcloud-9.4.1` (appVersion 35.0.2)。
- **Implications**: 段階的な更新はイメージのタグを 1 メジャーずつ差し替えるだけで進む。Helm chart は 1 版ごとに appVersion が固定され、プローブや設定の層が段階更新と保守モードの操作に重なる。kanidm・mailbox と同じく Kustomize で公式イメージを直接使う。

### 5. 大きなファイルと各段の上限

- **Context**: 要件 7.3 は中継の各段の本文上限と待ち時間を明示することを求める。
- **Sources Consulted**:
  - nextcloud/documentation `stable35/admin_manual/configuration_files/big_file_upload_configuration.rst`
  - nextcloud/server `stable35/config/config.sample.php` (`files.chunked_upload.max_size`)
  - nextcloud/desktop `src/libsync/configfile.cpp` (master)
  - traefik/traefik `v3.6.7` の `docs/content/reference/install-configuration/entrypoints.md`、`.../crd/http/serverstransport.md`
  - 本リポジトリの `ansible/roles/vps_proxy/templates/haproxy.cfg.j2`
- **Findings**:
  - チャンク分割のアップロードと WebDAV の単一 PUT には `upload_max_filesize` / `post_max_size` が効かず、PHP と Web サーバーの待ち時間が上限になる。Apache の `LimitRequestBody` は 2.4.54 以降の既定が 1 GiB。
  - サーバー側のチャンク上限の既定は 100 MiB。デスクトップクライアントの `maxChunkSize` の既定も 100 MiB。
  - Traefik のエントリポイントの `readTimeout` の既定は 60s で、本文を含むリクエスト全体の読み取り時間を制限する。`writeTimeout` の既定は 0 (無制限)、`idleTimeout` は 180s。
  - ServersTransport の `responseHeaderTimeout` の既定は 0 (無制限)、`dialTimeout` は 30s。
  - Traefik は既定で本文を緩衝せず、本文の大きさの上限を持たない。
  - VPS の HAProxy は `mode tcp`、`timeout client 1h`、`timeout server 1h`、`timeout connect 10s`。TCP モードでは本文の大きさを見ない。`timeout client` / `server` は無通信の時間に対する上限。
  - PHP の `max_execution_time` は Linux では入出力の待ちを含まない実行時間に対して働く。
- **Implications**: 既定のままだと Traefik の `readTimeout` 60s が 100 MiB のチャンクを遅い回線で送る場合に先に切れる。新しいエントリポイントでは 0 (無制限) を明示する。Apache の `LimitRequestBody` は 0 (無制限) を明示する。49GB のダウンロードは VPS の 100Mbps で 65 分程度かかるが、どの段にも転送時間の総量に対する上限は無く、無通信の上限 (HAProxy の 1h、Apache の `Timeout`) だけが働く。

### 6. 公開経路と送信元 IP

- **Context**: 要件 4.6 / 4.7 / 4.8。
- **Sources Consulted**:
  - 実機 (`kubectl --context default`): `kube-system/traefik` の Service、`svclb-traefik-*` の環境変数、Traefik の起動引数、HelmChart `traefik` の `valuesContent`
  - traefik/traefik-helm-chart `v38.0.2` の `values.yaml`、`templates/service.yaml`、`templates/_service.tpl`
  - k3s-io/docs `docs/add-ons/helm.md` (HelmChartConfig)、`docs/networking/networking-services.md`
  - 本リポジトリの `terraform/cloudflare_dns.tf`、`ansible/roles/vps_proxy/templates/{haproxy.cfg.j2,fickledev.com.conf.j2,nginx.conf.j2}`
  - gitops-apps の `apps/mailbox/service.yaml`、`apps/kanidm/service.yaml`、`apps/coredns-custom/configmap.yaml`
- **Findings**:
  - Traefik は `rancher/mirrored-library-traefik:3.6.7`、chart は `traefik-38.0.201+up38.0.2`。HelmChartConfig は現存しない。エントリポイントは `web` (8000) / `websecure` (8443) / `metrics` / `traefik`。
  - `kube-system/traefik` は `type: LoadBalancer`、`externalTrafficPolicy: Cluster`。svclb の Pod は `DEST_IPS` に ClusterIP を持ち、そこへ転送する。Traefik が受け取る接続の送信元は VPS のアドレスではなくなる。
  - chart は `service.additionalServices.<名前>` で別の Service を作れ、ポートごとに `expose.<Service 名>` でどの Service に出すかを選べる。`nodePort` も固定できる。エントリポイントごとに `proxyProtocol.trustedIPs`、`forwardedHeaders.trustedIPs`、`transport.respondingTimeouts` を持てる。
  - k3s は `kube-system` の HelmChartConfig `traefik` の `valuesContent` を追加の値ファイルとして chart に渡す。HelmChart 側の `spec.set` は `global.systemDefaultRegistry` だけで、ポート定義と衝突しない。
  - Traefik の文書は、PROXY protocol を有効にしたエントリポイントがヘッダの有無どちらの接続も受け付け、`trustedIPs` に含まれる接続元だけで送信元を置き換えると書く。
  - ノードの `INTERNAL-IP` は 172.16.0.150〜152。インベントリの `ansible_host` と steering の Host Access は 192.168.1.150〜152。VPS から tailnet 経由で届くのは OPNsense が広告する 192.168.1.0/24 側で、Kanidm の LDAPS (`192.168.1.151:30636`) がこの経路で稼働している。
  - Traefik の Pod は現在 `k3s-server` で動いている。
  - `terraform/cloudflare_dns.tf` には `*.fickledev.com` のトンネル向け CNAME がある。`cloud` の A レコードを明示すれば、そちらが優先して返る。
  - HAProxy の `bind *:443` は IPv4 のみを待ち受ける。
  - VPS の nginx の 80 番は `*.fickledev.com` を 403 で返す。`default_server` の HTTPS 転送は、より具体的なこのワイルドカードに負けて `cloud.fickledev.com` には働かない。
- **Implications**: 新しいエントリポイントを NodePort + `externalTrafficPolicy: Local` の追加 Service で出し、HAProxy から 3 ノードの 192.168.1.15x へ `check` 付きで送る。Traefik の Pod があるノードだけが応答するため、Pod の移動に HAProxy の死活確認が追従する。`trustedIPs` には VPS の tailnet アドレスだけを置く。DNS は A だけで AAAA を置かない。80 番の HTTPS 転送には VPS の nginx に専用の server ブロックが要る。

### 7. Nextcloud のリバースプロキシ設定と管理画面の警告

- **Context**: 要件 4.2。
- **Sources Consulted**: nextcloud/server `stable35` の `config/config.sample.php` (`trusted_proxies` / `forwarded_for_headers` / `overwriteprotocol` / `overwritehost` / `overwrite.cli.url`)、`apps/settings/lib/SetupChecks/ForwardedForHeaders.php`、`status.php`
- **Findings**:
  - `trusted_proxies` が空のまま `X-Forwarded-Host` が届くと、管理画面に「reverse proxy header configuration is incorrect」のエラーが出る。Traefik はこのヘッダを付ける。
  - `REMOTE_ADDR` が `trusted_proxies` に含まれ、かつ転送ヘッダから別のアドレスを得られた場合が成功になる。`REMOTE_ADDR` が `trusted_proxies` に含まれない場合も成功 (proxy 無しとして扱う)。
  - `status.php` は保守モード中も HTTP 200 を返し、本文の `maintenance` が true になる。
- **Implications**: `trusted_proxies` に Pod CIDR (10.42.0.0/16) を、`forwarded_for_headers` に `HTTP_X_FORWARDED_FOR` を明示する。公式イメージの `remoteip` が先に `REMOTE_ADDR` を利用者のアドレスへ置き換えるため、Nextcloud 側の判定は「proxy 無し」の成功に落ちる。どちらの経路でも利用者のアドレスが得られる。外形監視は保守モードで落ちない条件 (`installed` が true) にする。

### 8. user_oidc と Kanidm の結びつけ

- **Context**: 要件 5.1〜5.8。
- **Sources Consulted**:
  - nextcloud/user_oidc `v8.11.0` の `README.md`、`lib/Controller/LoginController.php`、`lib/Service/ProvisioningService.php`、`lib/Db/UserMapper.php`
  - nextcloud/server `stable31` / `stable34` / `stable35` の `lib/private/User/Database.php`、`lib/private/User/Manager.php`、`core/Controller/LoginController.php`、`config/config.sample.php` (`hide_login_form` / `token_auth_enforced`)
  - kanidm/kanidm `v1.11.1` の `book/src/integrations/oauth2.md`、`book/src/integrations/oauth2/examples.md`
  - SeanLatimer/terraform-provider-kanidm `v0.1.10` の `docs/resources/oauth2_basic.md`
  - Nextcloud App Store API `/api/v1/platform/<版>/apps.json`
- **Findings**:
  - `user_oidc` は `mapping-uid` の claim をそのまま `userManager->get()` に渡し、既存の利用者がいれば (`soft_auto_provision` が既定の true のとき) その利用者でログインさせる。`unique-uid` のハッシュ化は新しい利用者を作る経路でだけ働き、既存の利用者との照合には関与しない。
  - Database バックエンドの `loadUser` は `uid_lower` 列を `mb_strtolower` した値で引く (31 / 34 / 35 で確認。34 以降はメールアドレスでの再検索も加わった)。`Manager::getUserObject` は `getRealUID` で実際の uid を取り直す。大文字小文字の違いは吸収される。
  - `disable_account_creation=true` にすると、既存の利用者が見つからない場合はアカウントを作らずログインを拒否する。
  - OIDC でのログイン直後に `last-password-confirm` を 4 年先に設定し、パスワード再確認の画面を出さない。
  - `allow_multiple_user_backends=0` は Kanidm への自動転送になるが、README は「Admins can still use the regular login through adding the `?direct=1`」と書く。本体の `hide_login_form` も「the direct login still works with adding `?direct=1`」と書く。
  - `token_auth_enforced` は「Enforce token authentication for clients, which blocks requests using the user password」。
  - Kanidm は、クライアントが要求するスコープを scope map で付与されていない利用者の認可を拒否する。`prefer-short-username` で `preferred_username` が SPN ではなく `name` になる。provider 0.1.10 は `prefer_short_username` 属性を持つ。
  - `user_oidc` 8.11.0 は 29〜35 に対応する。
- **Implications**: 照合は設定だけで成立する (確定済みの決定と一致)。加えて `disable_account_creation=true` にすれば、照合に失敗したときに空のアカウントが作られる代わりにログインが拒否される。ローカルパスワードの Web ログインを止めるには、入口でパスワードログインの POST を拒否する必要がある。

### 9. 移行元で有効なアプリの到達先での対応

- **Context**: 要件 2.8 / 12.7。
- **Sources Consulted**: Nextcloud App Store API (`apps.nextcloud.com` の platform API。`platform/31.0.14` / `33.0.10` / `35.0.2` ほか 31〜35 の各版)
- **Findings**:
  - 継続するアプリの 35 対応版: calendar 6.6.4、contacts 8.9.3、deck 1.19.1、tasks 0.18.1、mail 5.12.6 (5.9.x は NC 35.0.2 の有効化時の DB 移行が失敗するため使わない。#17)、user_oidc 8.11.0 (8.9.0 は 35 非対応)。files_external は同梱。
  - 継続しないアプリ: extract (31 以降の対応版が無い)、metadata (34・35 の対応版が無い)、richdocuments と richdocumentscode (利用実績なし)、maps (位置の一覧は写真から再生成できる派生データ。写真と軌跡のファイルは残る)、recognize (分類データは派生データで、資源の負担が大きい)、drawio (`.drawio` ファイルは残る)。
- **Implications**: 継続するアプリは各段で対応版を入れ直す。継続しないアプリのコードは移行先に入れない。tasks は 36 対応版が無く、次のメジャー更新で再確認が要る。

### 10. restic と GDrive

- **Context**: 要件 8.4〜8.6、8.14、8.15。
- **Sources Consulted**:
  - restic/restic `v0.19.1` の `doc/030_preparing_a_new_repo.rst`、`doc/045_working_with_repos.rst`、`docker/Dockerfile.release`
  - Google Workspace 管理者ヘルプ「Drive storage and upload limits」(answer/172541)
  - rclone の `docs/content/drive.md`
- **Findings**:
  - 最新は v0.19.1 (2026-07-05)。`--insecure-no-password` で空のパスワードのリポジトリを作成・操作できる。`init` と `copy` は変換元に対する `--from-insecure-no-password` を持つ。
  - `copy` の重複排除にはチャンカーのパラメータを揃える必要があり、宛先を `init --from-repo <元> --copy-chunker-params` で作る。既存のリポジトリのチャンカーのパラメータは後から変えられない。パラメータの写しは方向を問わず、先に存在するリポジトリから後のリポジトリへ写す。
  - 公式イメージは alpine に restic だけを入れたもので、rclone を含まない。
  - Google Drive は 1 利用者あたり 24 時間で 750 GB までのアップロードとコピーを許す。rclone は `--drive-stop-on-upload-limit` で上限到達を致命的なエラーにできる。
- **Implications**: GDrive 側が先にできるため、宅内側を `init --from-repo <GDrive> --copy-chunker-params --insecure-no-password` で作る。以降の `restic copy` は新しいブロブだけを送る。rclone は別のイメージから実行ファイルを取り込む。750GB/日の上限は rclone の環境変数で失敗として扱う (#13)。

### 11. 退避と監視の既存資産

- **Context**: 要件 8.10〜8.12。
- **Sources Consulted**: gitops-apps の `apps/garage/templates/{backup-cronjob,capacity-check-cronjob,infisical-backup-secret}.yaml`、本リポジトリの `ansible/roles/{gatus,beszel_agent,systemd_failure_notify,beszel_hub}`、`ansible/inventory/group_vars/console/main.yml`、`.kiro/specs/backup-durability-and-alerting/gap-analysis.md`、henrygd/beszel `v0.19.0` の `agent/disk.go`
- **Findings**:
  - Discord への通知の宛先は Infisical の `PORTFOLIO_DISCORD_WEBHOOK_URL` ひとつで、Gatus・Beszel・`systemd_failure_notify` が共有する。
  - k3s の CronJob の失敗を通知へつなぐ仕組みは無い。Garage の容量検査は Job を失敗させるだけで、通知しない。`backup-durability-and-alerting` の gap-analysis はこれを未解決として挙げている。
  - Gatus は console-pi で動き、`gatus_endpoints` が監視対象の唯一の正。
  - Beszel の agent は `FILESYSTEM`・`EXTRA_FILESYSTEMS`・`/extra-filesystems` 配下のいずれかで指定されたものだけを追加で監視する。binary 版の agent に何も与えなければ、監視するのはルートだけになる。
- **Implications**: 外形監視は Gatus に 1 エンドポイント足す。容量はノードのファイルシステムを Beszel の `EXTRA_FILESYSTEMS` で拾う。CronJob の失敗通知は `backup-durability-and-alerting` の共通の仕組みに任せ、BackupJob は自前で通知を送らない。

### 12. `/dev/sdb` を VM 152 へ渡す手段

- **Context**: 要件 8.6。
- **Sources Consulted**:
  - proxmox/pve-storage `src/PVE/Storage.pm` (`check_volume_access`)、`src/PVE/API2/Disks/ZFS.pm` (`POST /nodes/{node}/disks/zfs`)、`src/PVE/API2/Storage/Config.pm` (`POST /storage`)
  - bpg/terraform-provider-proxmox `v0.111.1` の `docs/resources/virtual_environment_vm.md`
  - 実機 (hp-z440) の `pveversion`
  - 本リポジトリの `terraform/{providers.tf,variables.tf,modules/vm/main.tf}`
- **Findings**:
  - hp-z440 は pve-manager 8.4.21 / qemu-server 8.4.5 / libpve-storage-perl 8.3.8。
  - `check_volume_access` は `Only root can pass arbitrary filesystem paths.` として、`root@pam` 以外の利用者による任意のホストパスの指定を拒否する。API トークンの利用者は `root@pam` と一致しないため、host のブロックデバイスを渡す `path_in_datastore` は通らない。
  - bpg/proxmox 0.111.1 の docs は `path_in_datastore` を「Experimental」「(as root only) host's filesystem paths」と書き、API トークンでは使えずパスワード認証が要る旨を述べる。本リポジトリの Terraform は API トークン (`proxmox_auth_method = "token"`) で認証する。
  - `TerraformProvisioner` ロールに `Sys.Modify` が無い。ZFS プールの作成 (`POST /nodes/{node}/disks/zfs`、ZFS.pm) は `Sys.Modify` を要するため Terraform からはできない。Proxmox ストレージの登録 (`POST /storage`) は `Datastore.Allocate` で足り、できる。
  - VM モジュールのディスクは `zfs_pools` → `lvm_disks` の順に生成され、provider は位置で照合する。`zfs_pools` に key を足すと `lvm_disks` のディスクの位置が後ろにずれる。
  - Terraform の宣言に無いディスクを手作業で足すと、次の apply で取り外しの差分が出る。
- **Implications**: プールの作成だけを Ansible で 1 回行い、ストレージの登録と VM 152 の仮想ディスクを Terraform で宣言する。VM モジュールの `zfs_pools` に任意の `datastore` を足す。

### 13. restic の再開と rclone の 750GB/日の上限

- **Context**: 要件 8.14、8.15。最初の世代を切り替えの停止時間の中で送る。
- **Sources Consulted**: restic/restic `v0.19.1` の `doc/faq.rst`、`internal/repository/index` (`indexMaxAge` 10 分)、`doc/030_preparing_a_new_repo.rst` (rclone backend の `-o rclone.args`)、rclone の `docs/content/drive.md` (`--drive-stop-on-upload-limit`)
- **Findings**:
  - restic 0.19.1 は中断した `backup` を、index の書き出しが済んだ分から再開できる (FAQ、`indexMaxAge` 10 分)。再開時にファイルを走査し直すため、複数晩に分けると晩ごとに変わったファイルが混ざり、世代が単一の時点で整合しない。
  - rclone の `--drive-stop-on-upload-limit` は既定が false で、無いと 750GB の上限に当たっても再試行し続ける。
  - restic の rclone backend にこのフラグを付けるには、`-o rclone.args=...` か環境変数 `RCLONE_DRIVE_STOP_ON_UPLOAD_LIMIT=true` を使う。
- **Implications**: 最初の世代は停止時間の中で 1 回の実行で取り、中断したら同じ停止の中で再実行する。上限は環境変数で失敗として扱う。

### 14. Nextcloud Mail の認証方式

- **Context**: 要件 6.3。
- **Sources Consulted**: nextcloud/mail `v5.9.3` の XOAUTH2 の実装、nextcloud/mail の issue #13311、#13317
- **Findings**: 5.9.3 の XOAUTH2 は Google と Microsoft だけを対象にする。OIDC のトークンによる IMAP / SMTP の認証は #13311 と #13317 が未マージ。
- **Implications**: Kanidm の OIDC を使う利用者のメール接続は、トークンでは認証できない。プロビジョニングと Dovecot の master user で補う。

### 15. Kanidm の SMTP / SMB 認証の制約

- **Context**: 要件 6.4、10.4。
- **Sources Consulted**: kanidm/kanidm `v1.11.1` の book (アカウントとアプリケーションパスワード、service account)
- **Findings**: アプリケーションパスワードは person 専用で、service account が持てる資格情報は API token だけ。SMB 認証 (NTLM / Kerberos) は提供しない。
- **Implications**: 通知メールの送信アカウントは Dovecot の passwd-file、samba の認証はローカル利用者で賄う。

### 16. Mail のプロビジョニングと Dovecot の master user

- **Context**: 要件 6.3。
- **Sources Consulted**: nextcloud/mail `v5.9.3` の `lib/Db/Provisioning.php`、`lib/Service/Provisioning/Manager.php` (`updatePassword`)、`lib/Middleware/ProvisioningMiddleware.php`、Dovecot の `src/auth/auth-settings.c` (`passdb_master`、`auth_master_user_separator`)
- **Findings** (ソースの読解。実機での確認は #17):
  - `Provisioning` は `imapUser` / `smtpUser` / `emailTemplate` のテンプレート (`%USERID%` など) と `masterPassword` / `masterPasswordEnabled` を持つ。`masterPassword` は `oc_mail_provisionings.master_password` に平文で入る。
  - `ProvisioningMiddleware` が利用者のリクエストの際にアカウントを作成・更新し、`Manager` の `updatePassword` が `masterPasswordEnabled` のときに master のパスワードを使う。
  - Dovecot は `master = yes` の passdb で認証した利用者を master user とし、`auth_master_user_separator` で区切った `利用者*master` の形で、利用者名義のログインを許す。
- **Implications**: Dovecot に master 用 passdb と区切りを足し、Mail に `%USERID%*mailmaster` のテンプレートを与えれば、利用者はパスワードを入力せずに接続できる。実機の結果は #17。

### 17. ローカル検証の結果

- **Context**: 要件 6.3、6.4。本番と同じ版・同じダイジェストのイメージとダミー値のローカル環境で確認した。
- **Sources Consulted**: ローカル検証 2026-10-29
- **Findings**:
  - **Mail の版**: 5.9.x は NC 35.0.2 で有効化時の DB 移行 `Version5007Date20260108124422` が `TypeError` (DBAL の `Table` 型宣言と NC 35 の `OC\DB\Schema\Table` の不一致) で失敗する。stable5.9 に backport が無い。修正 (上流 b5283cf1、`Table|ITable`) は 5.10.14 以降・5.11.0 以降・5.12.0 以降に入っている。5.12.6 の info.xml は nextcloud 32〜35、PHP 8.1〜8.5 で、apps.nextcloud.com の 35.0.2 向け一覧に掲載されている。
  - **k3s の Dovecot 2.4.0 の master passdb**: `auth_master_user_separator = *` と、`passdb master_static { driver = static, master = yes, username_filter = mailmaster, passdb_static_password = {PLAIN}%{env:MASTER_PASSWORD} }`、`import_environment { MASTER_PASSWORD = %{env:MASTER_PASSWORD} }` で動く。名前付き passdb での `password =` は `Unknown setting` で起動しない。`import_environment` が無いと空に展開されて照合に失敗する。コンテナには環境変数 `MASTER_PASSWORD` を Secret から渡す。
  - **VPS の docker-mailserver v16.0.0 (Dovecot 2.4.1)**: `dovecot.cf.j2` は noreply の passdb、既存の LDAP passdb、master の passdb の順にする。
    - noreply の passdb は LDAP より前に置き `result_failure = return-fail` を付ける。無いと noreply の誤パスワード 1 回で LDAP への照会も走り、fail2ban の dovecot フィルタが 2 回数える (`fail2ban-regex` で実測)。
    - master の passdb 名はハイフン (`master-static`)。fail2ban の dovecot フィルタは passdb 名に `[a-z\-]+` しか許さず、アンダースコアでは失敗行を拾わない (実測)。k3s 側は fail2ban を使わないので `master_static`。
    - noreply のパスワードファイルは `root:dovecot` `0640`。auth プロセスは dovecot ユーザーで動き、`0600 root:root` は認証サーバーとの接続断で失敗する。ハッシュは Ansible の `password_hash('sha512', salt)`。salt を固定すると同一の出力になり、`openssl passwd -6 -salt` と一致する。
    - `compose.yaml.j2` の environment に `MASTER_PASSWORD` を足す。
    - submission 587 の STARTTLS で noreply と `alice*mailmaster` が AUTH PLAIN / LOGIN とも成功する。master で認証したとき Postfix の `sasl_username` はログイン先の利用者名 (`alice`) になる。
  - **両 Dovecot に共通の性質**: master パスワードでは存在しない利用者名でもログインが成功し、`/srv/vmail/<名前>` が作られる (master passdb は対象利用者の存在を確かめない)。`<名前>*<mailmaster 以外>` は認証失敗ではなく一時エラー (`All password databases were skipped`) で返る。大文字始まりの `Alice*mailmaster` でも userdb の `lower` により同じメールボックスに入る。
  - **プロビジョニングの REST API**:
    - 認証は管理者のアプリパスワードの Basic 認証。ヘッダ `OCS-APIRequest: true` で CSRF を通す (無いと 412)。`requesttoken` は不要。
    - body は `{"data":{...}}` (フラットだと 400)。必須は provisioningDomain、emailTemplate、imapUser、imapHost、imapPort、imapSslMode、smtpUser、smtpHost、smtpPort、smtpSslMode。
    - 冪等にするには `GET /apps/mail/api/settings/provisioning` の一覧から `provisioningDomain=="*"` の id を引き、あれば `POST .../provisioning/{id}` で更新、無ければ `POST .../provisioning` で作成する。一覧は `masterPassword` を伏せ字で返すため、更新のたびに実値を送る。Job のイメージに `jq` が要る。
    - 設定値は provisioningDomain `*`、emailTemplate `%EMAIL%`、imapUser と smtpUser `%USERID%*mailmaster`、masterPasswordEnabled true、IMAP は `mail.fickledev.com:993` (SSL)。
  - **emailTemplate**: `%USERID%@...` だと大文字始まりの uid でアドレスが大文字始まりになる。`%EMAIL%` は user_oidc がログイン時に Kanidm の email claim で上書きする Nextcloud の email を使い、小文字の正しいアドレスになる (実測)。Kanidm に mail 属性が無い利用者では `%EMAIL%` がリテラルのまま入る (エラーにならない)。メールボックスを持つ利用者は docker-mailserver の宛先照合 `(&(mail=%s)(class=person))` のため必ず mail 属性を持つので、該当しない。user_oidc は `--mapping-email=email`、スコープに `email`。
  - **Mail のアカウント作成**: 利用者が初めて Mail を開いた時点で作られる。プロビジョニングの作成後は、OIDC でない既存の利用者 (管理者など) にもアカウントが作られる (実測)。
  - **user_oidc の既存利用者との対応**: 初回ログインで Nextcloud の email と表示名を Kanidm の値で上書きする。`mapping-uid=preferred_username`、`unique-uid=0` で、Kanidm の小文字の名前が、大文字小文字だけが異なる既存の uid に対応づき、利用者は増えない (実測)。
  - **ローカル手順の要点**: Kanidm の自己署名の証明書は CA と leaf を分ける。OAuth2 クライアントの作成には、操作する管理者の `idm_oauth2_admins` への追加が要る。
- **Implications**: 6.3 / 6.4 の経路は design の確定形で成立する。Mail は 5.12.6 を使う。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 公式イメージ + Kustomize | Deployment / Service / PV / IngressRoute を直接書く | 段階更新はタグの差し替えだけ。kanidm・mailbox と同じ形 | 構成要素を自分で並べる | 採用 |
| nextcloud/helm | 公式 chart を依存に持つ umbrella chart | 部品が揃っている | 1 版ごとに appVersion が固定。プローブ・設定の層が段階更新と保守モードの操作に重なる | 不採用 |
| 既存の websecure に PROXY protocol を足す | `websecure` の `trustedIPs` に VPS を入れる | 新しいエントリポイントが要らない | svclb の DNAT で接続元が VPS にならない。Tunnel 経由の既存経路の送信元の扱いを変える (4.8 に反する) | 不採用 |
| 専用エントリポイント + NodePort (Local) | Nextcloud 専用のエントリポイントを NodePort Service で出す | 送信元が保たれ、`trustedIPs` を VPS 1 つに絞れる。既存経路に触れない | Traefik の再起動を伴う。ノード 3 台を HAProxy に並べる | 採用 |

## Design Decisions

### Decision: 到達先を Nextcloud 35 にする

- **Context**: 要件 12.1。
- **Alternatives Considered**:
  1. 33 で止める — 段数は 3 つ減るが 2027-02 に保守が切れる
  2. 35 まで上げる — 2027-09 まで保守される
- **Selected Approach**: 35.0.2 まで上げる。
- **Rationale**: 33 は移行の完了から数か月で保守が切れ、すぐに 34・35 の更新が要る。どのみち踏む段を移行先の宣言に乗る前の一括作業で済ませる。
- **Trade-offs**: 移行時の作業時間が増える。
- **Follow-up**: 着手時点で保守対象の版が変わっていないかを再確認する。

### Decision: 変換は 31 の段で行う

- **Context**: 要件 12.3 / 12.9。
- **Alternatives Considered**:
  1. 30 で変換 — 30 の PostgreSQL 対応は本 spec の調査対象外で、移行元と同じ版で変換する利点も無い
  2. 31 で変換 — MariaDB 10.11 と PostgreSQL 17 の両方が対応範囲に入る最初の段
- **Selected Approach**: 31.0.14 に上げた後、`occ db:convert-type --all-apps pgsql` を実行する。
- **Rationale**: 確定済みの決定どおり。どの段も対応範囲から外れない。

### Decision: `/dev/sdb` は ZFS プールの仮想ディスクとして VM 152 へ渡す

- **Context**: 要件 8.6、8.7。
- **Selected Approach**: hp-z440 で `/dev/sdb` を単一ディスクの ZFS プールにする (Ansible で 1 回だけ、関門の前提を確かめた後、冪等ガード付き)。Terraform の `proxmox_storage_zfspool` で登録し、VM 152 にそのストレージ上の仮想ディスクを宣言する。新プールを `host_health_zfs_pools` に足して scrub する。
- **Rationale**: API トークンのまま宣言でき、ZFS のチェックサムと scrub で劣化を検知できる (#12)。
- **却下**: raw パススルー (Proxmox が任意のホストパスを root@pam のパスワード認証にしか許さず、API トークンでは通らない)。`qm set` の手作業 (宣言とずれる)。`TerraformProvisioner` への `Sys.Modify` 付与と `proxmox_node_disk_zfs` (権限の拡大。作り直しの差分でディスクが初期化される危険)。

### Decision: 宅外の最初の世代は切り替えの停止時間の中で取る

- **Context**: 要件 8.9、8.15。
- **Selected Approach**: 移行先の保守モードの解除前に、宅外のリポジトリへ直接取る。切り替えの開始時刻に夜間などの制約を置かない。
- **Rationale**: 単一の時点で整合した世代になる。restic は中断した backup を再開できる (#13)。
- **Trade-offs**: 停止時間が最初の世代の送信を終えるまで延びる。停止時間の長さは問わない (運用者の判断)。
- **却下**: 切り替え後に複数晩に分けて送る (再開時に走査し直すため単一の時点で整合しない)。保守モードを短く切って利用中にファイルを読む (8.9 に反する)。

### Decision: 退避の失敗の通知は共通の仕組みに任せる

- **Context**: 要件 8.10。
- **Selected Approach**: BackupJob は自前で通知を送らず、Job の失敗終了で示す。通知は `backup-durability-and-alerting` の共通の仕組みで満たし、本 spec はその spec に依存する。
- **却下**: Job から webhook を直接叩く (共通の仕組みと二重になる)。Gatus の外部エンドポイントへ結果を送る (console-pi への inbound を開ける必要があり、`admin-plane-rebuild` の許可集合に触れる)。

### Decision: Web メールは master user とプロビジョニングで認証する

- **Context**: 要件 6.3。
- **Selected Approach**: IMAP の接続先は `mail.fickledev.com:993`。Mail 5.12.6 のプロビジョニング (provisioningDomain `*`、emailTemplate `%EMAIL%`、`%USERID%*mailmaster`、masterPasswordEnabled) と Dovecot の master user で認証する。設定は gitops-apps の Job が REST API に投入する。k3s の Dovecot と VPS の docker-mailserver の両方に master 用 passdb を足し、既存の LDAP passdb は残す。
- **Rationale**: OIDC のトークンでは IMAP を認証できない (#14)。メールクライアントの認証方式に触れずに済む。
- **却下**: 利用者が Kanidm のアプリケーションパスワードを Mail に手で入れる (発行は本人の対話端末でしか行えず、パスワードの入力を要する)。`coredns-custom` に別名を足す (既存の `mail.fickledev.com` の経路で足りる)。証明書の検証を無効にする。docker-mailserver 標準の master アカウント機能 (LDAP 構成で未サポート)。

### Decision: 通知メールは passwd-file の送信アカウントで送る

- **Context**: 要件 6.4。
- **Selected Approach**: 送信元 `noreply@fickledev.com`。VPS の Dovecot に、LDAP より前に `result_failure = return-fail` 付きで passwd-file の passdb を足し、ハッシュは Ansible の `password_hash('sha512', salt)` で生成する (salt を Infisical から供給し、冪等)。
- **却下**: Kanidm の service account (アプリケーションパスワードは person 専用で、送信の認証に使えない)。運用者のアカウントの流用 (アプリケーションパスワードの発行は本人のセッションでしか行えない)。

### Decision: 切り戻しの猶予期間は置かない

- **Context**: 要件 9.3。
- **Selected Approach**: 移行の検証 (要件 2) と宅外からの復元の確認 (8.2) が済んだら VM 105 の撤去に進む。停止と削除はそれぞれ関門の前提を確かめてから実行する。

### Decision: samba は NAS のローカル利用者で認証する

- **Context**: 要件 10.4。
- **Selected Approach**: NAS (`ansible/roles/nas`) に samba を立て、samba のローカル利用者で認証する。資格情報は Infisical。
- **却下**: Kanidm による認証 (SMB 認証を提供しない、#15)。

### Decision: 宅内のリポジトリは空のパスワードにする

- **Context**: 要件 8.6 は宅内の退避を秘匿のために暗号化せず、鍵を失って読めなくなる状態を作らないことを求める。
- **Alternatives Considered**:
  1. `--insecure-no-password` — 鍵そのものを持たない
  2. 退避先と同じ場所から引ける固定のパスワード — 例えばリポジトリの隣にパスワードのファイルを置く
- **Selected Approach**: `--insecure-no-password`。
- **Rationale**: 固定のパスワードは秘匿の役に立たず、ファイルの欠落や食い違いという失敗の仕方だけを増やす。空のパスワードは失う鍵そのものが無く、restic が公式に支える形で、毎回のコマンドに明示のオプションを要求するため取り違えも起きにくい。
- **Trade-offs**: 宅内の退避先の中身は、そのディスクを読める者に見える。原本と同じ自宅内にあり、要件 8.6 が受け入れている。

### Decision: 宅内のリポジトリを GDrive のリポジトリからチャンカーのパラメータを写して作る

- **Context**: 要件 8.14 / 8.15。最初の世代は宅内を経由せず GDrive へ直接取る。
- **Selected Approach**: GDrive のリポジトリを先に `init` し、宅内のリポジトリは `/dev/sdb` の初期化後に `init --from-repo <GDrive> --copy-chunker-params --insecure-no-password` で作る。
- **Rationale**: 後から作る側に写す以外に揃える手段が無い。揃えないと `restic copy` が既に GDrive にあるデータも送り直す。

### Decision: 送信元 IP は専用エントリポイントと NodePort (Local) で渡す

- **Context**: 要件 4.7 / 4.8。
- **Selected Approach**: HelmChartConfig で `nextcloud` エントリポイントを足し、`externalTrafficPolicy: Local` の NodePort Service だけに出す。`proxyProtocol.trustedIPs` は VPS の tailnet アドレスだけにする。
- **Rationale**: 既存の LoadBalancer Service では接続元が書き換わる。LDAPS と IMAPS が同じ形で動いている。
- **Trade-offs**: HelmChartConfig の適用で Traefik が再起動し、Tunnel 経由の全経路が一瞬止まる。

### Decision: ローカルパスワードの Web ログインを入口で拒否する

- **Context**: 要件 5.7。`?direct=1` によるパスワードログインは本体の設定では止められない。
- **Alternatives Considered**:
  1. 利用者のパスワードを誰も知らない値に置き換える — 受け付け自体は残る
  2. Traefik でパスワードログインの POST (`/login`、`/index.php/login`) を 403 にする
- **Selected Approach**: 2 に加え、`token_auth_enforced=true`、`allow_multiple_user_backends=0`、`hide_login_form=true`、`lost_password_link=disabled` を設定する。
- **Rationale**: 受け付けそのものを止められるのは 2 だけ。OIDC のログインは `/apps/user_oidc/*` を、ログインフロー v2 の承認は `/login/v2/*` を通るため、完全一致の 2 つのパスだけを止めても既存の経路に影響しない。パスワードの再確認は OIDC のログインで省略される。

### Decision: 照合に失敗したときにアカウントを作らせない

- **Context**: 要件 5.3 / 5.8 は新しいアカウントが作られないことを求める。
- **Selected Approach**: `user_oidc` の `disable_account_creation=true` (`auto_provision` と `soft_auto_provision` は既定の true のまま)。
- **Rationale**: 確定済みの決定 (`soft_auto_provision` は既定) を変えずに、照合の失敗をログイン拒否として表に出せる。5.8 の実測は引き続き行う。

### Decision: データディレクトリのコンテナ内のパスを移行元と同じにする

- **Context**: 移行元の `datadirectory` は `/media/hdd0`。
- **Selected Approach**: 専用ディスクの `data` サブディレクトリをコンテナの `/media/hdd0` にマウントする。
- **Rationale**: ルートのストレージの識別子 (`oc_storages` の `local::<datadirectory>/`) がパスから作られる。パスを変えると識別子の書き換えが要る。同じパスにすれば DB に手を入れずに済む。

## Risks & Mitigations

- **ノードのアドレスの食い違い (範囲外の既知の問題)** — steering は k3s ノードを 192.168.1.150〜152 とするが、実機の `INTERNAL-IP` は 172.16.0.150〜152。VPS から届くのは 192.168.1.0/24 側で、LDAPS が同じ経路で動いている。NodePort が 192.168.1.15x で応答することを、HAProxy への組み込み前に VPS から実測する。どちらが正しい記述かの判断は本 spec では行わない。
- **IP の重複 (範囲外の既知の問題)** — `host_vars/pbs/main.yml:79` の VM 110 の IP 192.168.1.11 が VM 105 と同じ。移行元への接続先を IP で指定する手順では、接続先が VM 105 であることをホスト名とホスト鍵で確かめる。
- **Traefik の再起動** — HelmChartConfig の適用で Traefik が作り直される。適用は利用の少ない時間に行い、適用後に既存の公開ホスト名の応答を確かめる。
- **最初の宅外世代の所要時間** — 自宅の上り帯域は未計測。送信時間は切り替えの停止時間に含まれるため、リハーサルで上り帯域を測って見積もる。
- **z440 のメモリ** — requests の空きは約 6.6Gi、limits は 80% 割当済み。Nextcloud 一式の limits を足すと limits の合計は割当可能量を超える (requests は収まる)。値は仮で、リハーサルで実測して見直す。

## References

- [Nextcloud Maintenance and Release Schedule](https://github.com/nextcloud/server/wiki/Maintenance-and-Release-Schedule) — 保守対象の版と期限
- [Nextcloud Releases and PHP versions](https://github.com/nextcloud/server/wiki/Releases-and-PHP-versions) — 版ごとの PHP の対応範囲
- [System requirements (stable31〜35)](https://github.com/nextcloud/documentation/blob/stable35/admin_manual/installation/system_requirements.rst) — DB / PHP の対応範囲
- [Upgrade manually (stable35)](https://github.com/nextcloud/documentation/blob/stable35/admin_manual/maintenance/upgrade.rst) — 段階的な更新と背景の移行
- [Backup (stable35)](https://github.com/nextcloud/documentation/blob/stable35/admin_manual/maintenance/backup.rst) — 保守モードでの取得対象
- [Converting database type (stable31)](https://github.com/nextcloud/documentation/blob/stable31/admin_manual/configuration_database/db_conversion.rst) — `occ db:convert-type`
- [ConvertType.php (stable31)](https://github.com/nextcloud/server/blob/stable31/core/Command/Db/ConvertType.php) — 変換の実装
- [Uploading big files (stable35)](https://github.com/nextcloud/documentation/blob/stable35/admin_manual/configuration_files/big_file_upload_configuration.rst) — 大きなファイルの設定
- [config.sample.php (stable35)](https://github.com/nextcloud/server/blob/stable35/config/config.sample.php) — `trusted_proxies` / `token_auth_enforced` / `hide_login_form` / チャンク上限
- [ForwardedForHeaders.php (stable35)](https://github.com/nextcloud/server/blob/stable35/apps/settings/lib/SetupChecks/ForwardedForHeaders.php) — リバースプロキシの警告の判定
- [Database.php (stable35)](https://github.com/nextcloud/server/blob/stable35/lib/private/User/Database.php) — uid の大文字小文字を区別しない照合
- [nextcloud/docker](https://github.com/nextcloud/docker) — 公式イメージ、エントリポイントの更新処理
- [nextcloud/helm releases](https://github.com/nextcloud/helm/releases) — chart の現行版
- [user_oidc v8.11.0 README](https://github.com/nextcloud/user_oidc/blob/v8.11.0/README.md) — 自動プロビジョニングと `?direct=1`
- [user_oidc v8.11.0 LoginController.php](https://github.com/nextcloud/user_oidc/blob/v8.11.0/lib/Controller/LoginController.php) — 照合とパスワード再確認の省略
- [Kanidm v1.11.1 OAuth2](https://github.com/kanidm/kanidm/blob/v1.11.1/book/src/integrations/oauth2.md) — scope map と短い名前
- [terraform-provider-kanidm v0.1.10 oauth2_basic](https://github.com/SeanLatimer/terraform-provider-kanidm/blob/v0.1.10/docs/resources/oauth2_basic.md) — `prefer_short_username`
- [Traefik v3.6.7 EntryPoints](https://github.com/traefik/traefik/blob/v3.6.7/docs/content/reference/install-configuration/entrypoints.md) — `proxyProtocol` / `respondingTimeouts`
- [Traefik v3.6.7 ServersTransport](https://github.com/traefik/traefik/blob/v3.6.7/docs/content/reference/routing-configuration/kubernetes/crd/http/serverstransport.md) — 転送の待ち時間
- [traefik-helm-chart v38.0.2 values.yaml](https://github.com/traefik/traefik-helm-chart/blob/v38.0.2/traefik/values.yaml) — `ports` / `additionalServices`
- [K3s Helm (HelmChartConfig)](https://docs.k3s.io/add-ons/helm#customizing-packaged-components-with-helmchartconfig) — 同梱の Traefik の上書き
- [HAProxy configuration manual: send-proxy-v2](https://docs.haproxy.org/2.8/configuration.html#5.2-send-proxy-v2) — PROXY protocol v2 の送出
- [restic: Preparing a new repository (v0.19.1)](https://github.com/restic/restic/blob/v0.19.1/doc/030_preparing_a_new_repo.rst) — `--insecure-no-password`、rclone backend
- [restic: Working with repositories (v0.19.1)](https://github.com/restic/restic/blob/v0.19.1/doc/045_working_with_repos.rst) — `copy` と `--copy-chunker-params`
- [Google Drive upload limits](https://support.google.com/a/answer/172541) — 24 時間 750 GB
- [CloudNativePG v1.30.0 versions.go](https://github.com/cloudnative-pg/cloudnative-pg/blob/v1.30.0/pkg/versions/versions.go) — 既定のイメージが PostgreSQL 18 であること
- [pve-storage Storage.pm (check_volume_access)](https://github.com/proxmox/pve-storage/blob/master/src/PVE/Storage.pm) — 任意のホストパスは root のみ
- [pve-storage API2/Disks/ZFS.pm](https://github.com/proxmox/pve-storage/blob/master/src/PVE/API2/Disks/ZFS.pm) — ZFS プール作成の権限
- [bpg/terraform-provider-proxmox v0.111.1 virtual_environment_vm](https://github.com/bpg/terraform-provider-proxmox/blob/v0.111.1/docs/resources/virtual_environment_vm.md) — `path_in_datastore` と API トークンの制約
- [restic v0.19.1 FAQ](https://github.com/restic/restic/blob/v0.19.1/doc/faq.rst) — 中断した backup の再開
- [rclone drive](https://github.com/rclone/rclone/blob/master/docs/content/drive.md) — `--drive-stop-on-upload-limit`
- [nextcloud/mail v5.12.6](https://github.com/nextcloud/mail/tree/v5.12.6) — 35 対応版。DB 移行の修正 (コミット b5283cf1) を含む
- [nextcloud/mail v5.9.3](https://github.com/nextcloud/mail/tree/v5.9.3) — XOAUTH2、プロビジョニング (`lib/Db/Provisioning.php`、`lib/Service/Provisioning/Manager.php`、`lib/Middleware/ProvisioningMiddleware.php`)
- [nextcloud/mail #13311](https://github.com/nextcloud/mail/issues/13311)、[#13317](https://github.com/nextcloud/mail/issues/13317) — OIDC トークン認証 (未マージ)
- [Kanidm v1.11.1 book](https://github.com/kanidm/kanidm/tree/v1.11.1/book/src) — アプリケーションパスワードと service account
- [Dovecot auth-settings.c](https://github.com/dovecot/core/blob/main/src/auth/auth-settings.c) — `passdb_master`、`auth_master_user_separator`
- [Nextcloud App Store platform API](https://apps.nextcloud.com/api/v1/platform/35.0.2/apps.json) — アプリの 31〜35 対応版
- [Beszel v0.19.0 agent/disk.go](https://github.com/henrygd/beszel/blob/v0.19.0/agent/disk.go) — 追加のファイルシステムの検出条件
