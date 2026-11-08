# Implementation Plan

## 全期間の制約

以下は全タスクの着手前の制約として扱う。

- VM 105 と `/dev/sdb` には、関門 (A0〜A4) の操作以外は読み取りしか行わない。関門の承認は運用者から事前に一括で与えられている。各関門は前提をコマンドの結果で確かめ、満たせば実行し、満たさなければ止まって報告する。前提の確認結果と実施 (対象・影響範囲・元に戻す手順を含む) を `manual-operations.md` に残す (要件 1.1、1.3)
- 切り替えが完了するまで VM 105 を停止しない。移行元のデータは宅外からの復元の確認が済むまで消去しない (要件 1.4、1.5)
- アップグレードとデータベースの変換は移行先でのみ行い、移行元のバージョンとデータベースに手を加えない (要件 12.3)
- シークレットの値をリポジトリ・コマンド行・会話ログに出さない。記録にはアカウント名と人数を書かない

## Phase 1: 宣言と公開経路

- [ ] 1. 認証とシークレットの土台
- [ ] 1.1 Kanidm の OAuth2 クライアントを宣言する
  - OAuth2 クライアント `nextcloud` を、origin・2 つの redirect URI・短い名前の優先・組み込みグループ idm_all_persons への scope map (`openid`、`profile`、`email`) で宣言する
  - クライアントシークレットを sensitive な出力として足す
  - `terraform validate` と plan で追加だけの差分であることを確かめてから適用する
  - 完了時、Kanidm の発見文書 `https://kanidm.fickledev.com/oauth2/openid/nextcloud/.well-known/openid-configuration` が応答する
  - _Requirements: 5.1, 5.2, 5.3_

- [x] 1.2 Nextcloud とメール基盤が使うシークレットを Infisical に登録する
  - 設計のキー一覧のうち、この時点で値を用意できるもの (DB のパスワード、OIDC のクライアントシークレット、通知メールの送信アカウントのパスワードと salt、master パスワード、samba の資格情報、宅外のリポジトリの鍵、GDrive の rclone 設定) を登録する
  - OIDC のクライアントシークレットは 1.1 の出力から値を表示せずに登録する
  - GDrive の rclone 設定 (`NEXTCLOUD_BACKUP_RCLONE_CONFIG`) は、既存の Infisical のキー `GARAGE_BACKUP_RCLONE_CONFIG` の値を表示せずに写して登録する。ブラウザでの OAuth は行わない
  - `secret` と `passwordsalt` は移行元の `config.php` の取り出し (5.3) で、管理者のアプリパスワードは Configure (6.5) の後に、実装する側が値を表示せずに登録する
  - 完了時、Infisical の該当の環境に、ここで登録すべきキーが名前で揃っていることをキー名だけの照会で確かめられる
  - _Requirements: 3.4, 8.5_

- [ ] 2. メール基盤の認証の追加と NAS の共有
- [x] 2.1 (P) k3s の Dovecot に master user を足す
  - `mailbox` の Dovecot の設定に `auth_master_user_separator`、master 用 passdb `master_static`、`import_environment` を足す
  - master パスワードを Secret から環境変数 `MASTER_PASSWORD` として Dovecot へ渡す
  - 既存の Kanidm の LDAP passdb には触れない
  - 完了時、k3s の Dovecot で `<利用者>*mailmaster` の IMAP 認証が成功し、既存のメールクライアントがアプリケーションパスワードで従来どおり接続できる
  - _Requirements: 6.3_
  - _Boundary: MailMasterAuth_
  - _Depends: 1.2_

- [x] 2.2 VPS の docker-mailserver に通知メールの送信アカウントと master user を足す
  - Dovecot の設定に、LDAP より前に `result_failure = return-fail` 付きの passwd-file passdb `noreply` を置き、LDAP の後に master 用 passdb `master-static` と `import_environment` を置く
  - パスワードファイルを Infisical のパスワードと salt から Ansible の `password_hash` で生成し、`root:dovecot`・`0640` で配置する。再実行で内容が変わらない
  - compose の environment に `MASTER_PASSWORD` を渡す
  - `ansible-lint` を通してから適用する
  - 完了時、submission 587 の STARTTLS で noreply と `<利用者>*mailmaster` が AUTH PLAIN / LOGIN とも成功し、noreply の誤パスワード 1 回が `fail2ban-regex` で 1 回と数えられる
  - _Requirements: 6.3, 6.4_

- [x] 2.3 (P) NAS に samba の共有を設ける
  - `ansible/roles/nas` と `host_vars/nas` に samba とローカル利用者を足す。資格情報は Infisical から供給する
  - 共有名はこのタスクで決める
  - 移行元の samba の共有先は空のため、データは移さない
  - 完了時、宅内から samba のローカル利用者で共有に読み書きでき、既存の NFS の共有の挙動が変わらない
  - _Requirements: 10.4_
  - _Boundary: NasSmbShare_
  - _Depends: 1.2_

- [ ] 3. 公開経路
- [x] 3.1 Traefik に Nextcloud 専用のエントリポイントを足す
  - `gitops-apps` に `traefik-config` を新設し、`kube-system` の HelmChartConfig `traefik` で `nextcloud` エントリポイント (8444、TLS、PROXY protocol は VPS の tailnet アドレスだけを信頼、外から届いた転送ヘッダは信頼しない、応答の待ち時間の明示) を足す
  - エントリポイントを `externalTrafficPolicy: Local` の NodePort (30443) の追加 Service だけに出す。追加 Service の名前はこのタスクで決める
  - 既存の `web` / `websecure` と既存の LoadBalancer Service には値を足さない
  - Traefik が再起動するため、適用は利用の少ない時間に行う
  - 完了時、VPS から `192.168.1.150〜152:30443` へ接続して Traefik の Pod が載るノードだけが応答し、`websecure` の既存経路の応答とアクセスログの送信元の扱いが変わっていない
  - _Requirements: 3.1, 4.1, 4.7, 4.8, 7.3_

- [x] 3.2 (P) `cloud.fickledev.com` の A レコードを宣言する
  - `terraform/cloudflare_dns.tf` の `vps_hosts` に `cloud` を `proxied = false`、`aaaa = false` で足す
  - 完了時、`cloud.fickledev.com` の問い合わせがトンネル向けの CNAME ではなく VPS の A レコードを返す
  - _Requirements: 4.1_
  - _Boundary: PublicDnsRecord_

- [x] 3.3 VPS で `cloud.fickledev.com` を SNI で振り分け、80 番を HTTPS へ転送する
  - HAProxy の `ft_tls` に SNI の振り分けを足し、`bk_nextcloud` に各 k3s ノードの `30443` を `send-proxy-v2` と死活確認付きで並べ、`timeout server` を明示する
  - 振り分けの値は既存の `vps_proxy_xray_sni` と同じ形の変数に置く
  - nginx の 80 番に `cloud.fickledev.com` を HTTPS へ 301 で転送する server ブロックを足す
  - `ansible-lint` を通してから適用する
  - 完了時、HAProxy の設定検査が通り、`http://cloud.fickledev.com/` が `https://` への 301 を返し、既存の SNI の振り分けの応答が変わらない
  - _Requirements: 4.1, 4.4, 4.6, 4.7, 7.2, 7.3_

- [ ] 4. Nextcloud の宣言
- [x] 4.1 namespace と専用ディスクの静的 PV を宣言する
  - `gitops-apps` に `apps/nextcloud` を新設し、namespace と `/var/lib/nextcloud` の hostPath 静的 PV / PVC (Retain、`claimRef` 固定、PV と PVC の双方に `Prune=false,Delete=false`) を置く
  - ディスク内を `html/`・`data/`・`dump/` の 3 つに分ける配置を前提にする
  - ワイルドカード証明書の reflector の複製先に `nextcloud` を足す
  - 完了時、ArgoCD の同期で PVC が Bound になり、PV と PVC に Garage と同じ削除除外の注記があることを確かめられる
  - _Requirements: 3.1, 3.2, 3.3_

- [x] 4.2 Infisical のシークレットを Nextcloud の namespace へ供給する
  - アプリ用と退避用の InfisicalStaticSecret を `components/infisical-common` を取り込んで置く。値は参照するキー名だけを書く
  - 完了時、`nextcloud` namespace に必要な Secret が作られ、リポジトリにシークレットの値が含まれない
  - _Requirements: 2.9, 3.4_

- [x] 4.3 Nextcloud 専用の CNPG Cluster を宣言する
  - `nextcloud-db` を `instances: 1`、PostgreSQL 17 の `imageName` 明示、local-path、k3s-agent-z440 への固定、`Prune=false,Delete=false` で置く
  - `bootstrap.initdb` に Infisical 由来の資格情報を与え、`backup:` は設定しない
  - 資源の値は設計の仮の値で置く
  - 完了時、`nextcloud-db` が Ready になり、利用者 `nextcloud` で DB `nextcloud` に接続できる
  - _Requirements: 3.3, 3.5, 12.4_

- [x] 4.4 Redis と、namespace の外からの接続を拒否する NetworkPolicy を宣言する
  - 永続化しない Redis の Deployment と Service を置く
  - NetworkPolicy で Redis への接続を `nextcloud` namespace 内に限る。DB には掛けない
  - 完了時、namespace 内からは Redis に接続でき、他の namespace からの接続が拒否される
  - _Requirements: 3.5_

- [x] 4.5 変換用の一時 MariaDB を宣言する
  - `migration-mariadb` を `mariadb:10.11`、`emptyDir`、k3s-agent-z440 への固定、namespace 内のみの Service で置く
  - 利用者 `nextcloud` のパスワードを DB のパスワードと共用で Secret から与える
  - 完了時、一時 MariaDB が起動し、利用者 `nextcloud` で接続できる
  - _Requirements: 12.9, 12.10_

- [x] 4.6 Nextcloud 本体の Deployment と Service を宣言する
  - 公式の Apache 版 `30.0.17` をダイジェストで固定し、`app` と `cron` の 2 コンテナ、`Recreate`、k3s-agent-z440 への固定、`replicas: 0` で置く
  - 専用ディスクの `html/` を `/var/www/html` に、`data/` を `/media/hdd0` にマウントする
  - `secret`・`passwordsalt`・DB のパスワード・通知メールのパスワードを環境変数で与え、管理者の自動導入の環境変数は与えない
  - readiness は `status.php`、liveness は置かない。資源と `MaxRequestWorkers` は設計の仮の値で置く
  - PHP と Apache の上限 (本文の大きさ・待ち時間・`output_buffering`) を ConfigMap で明示する
  - 完了時、`kustomize build` が通り、同期後に Deployment が `replicas: 0` で存在して Pod が起動していない
  - _Requirements: 2.9, 3.1, 3.5, 3.7, 7.1, 7.3_

- [x] 4.7 IngressRoute と拒否のルートを宣言する
  - 本体と、パスワードログインの POST を 403 にするルートの 2 つの IngressRoute を `nextcloud` エントリポイントだけに付ける。`websecure` には付けない
  - 拒否のルートの Middleware は到達しえない値を明示した `ipAllowList` にする
  - 本体のルートに HSTS を付け、ServersTransport の待ち時間を明示する
  - 完了時、Traefik のダッシュボードまたはログでルーターと Middleware がエラー無く作られ、`websecure` 側に `cloud.fickledev.com` のルーターが無い
  - _Requirements: 4.1, 4.2, 4.8, 5.7, 7.2, 7.3_
  - _Depends: 3.1_

- [x] 4.8 Configure の段の冪等なスクリプトを ConfigMap として宣言する
  - `configure.sh` に、config.php の値、通知メールの送信設定、`hide_login_form` と `lost_password_link`、user_oidc の appconfig とシステム設定、provider の登録 (あれば更新)、files_external の `/SMB` の接続先を NAS へ替える更新、継続しないアプリの無効化と継続するアプリの版の確認 (下回れば失敗で終える)、管理者のアプリパスワードの発行 (同名のトークンを消して作り直す) を入れる
  - トークン名はこのタスクで決める
  - 資格情報は Secret の環境変数から読み、コマンド行に書かない
  - 完了時、ConfigMap が `apps/nextcloud` に宣言され、`app` コンテナから `configure.sh` を参照できる
  - _Requirements: 4.2, 4.5, 5.1, 5.3, 5.6, 5.7, 6.4, 10.5_
  - _Depends: 1.1, 2.3_

- [x] 4.9 退避の CronJob を停止状態で宣言する
  - CronJob `nextcloud-backup` を `suspend: true`、`Asia/Tokyo` の仮の時刻、`Forbid`、`startingDeadlineSeconds`、`backoffLimit: 0`、k3s-agent-z440 への固定で置く
  - rclone の実行ファイルを写す init container の後に、保守モードの確認と有効化、`pg_dump`、宅内への `restic backup`、保守モードの解除、宅外への `copy` と `forget` / `prune` と GDrive の総量の確認の段を、設計の失敗時の扱いどおりに並べる
  - 宅外の restic と `rclone size` に `RCLONE_DRIVE_STOP_ON_UPLOAD_LIMIT=true` を与え、総量が 4 TB の閾値 (仮) を超えたら失敗で終える
  - 宅内のリポジトリの準備前は宅内への取得と宅外への `copy` を行わない状態で置く
  - 取得の対象と除外 (プレビューのキャッシュ) を設計どおりにする
  - 完了時、`kustomize build` が通り、同期後に CronJob が停止状態で存在して Job が作られない
  - _Requirements: 8.1, 8.3, 8.4, 8.9, 8.10, 8.12, 8.13, 8.14, 8.16, 12.8_

## Phase 2: リハーサルと実測

- [x] 5. 関門 A0 と移行元からの取り出し
- [x] 5.1 関門 A0 の前提を確かめてから移行元に一時の公開鍵を足す
  - 前提 (Phase 1 の宣言が済んでいること) をコマンドの結果で確かめ、満たさなければ止まって報告する
  - 鍵を足す場所、鍵 (scratchpad に置いた一時のもの)、削除の手順を `manual-operations.md` に記録する
  - 接続の前に、接続先が VM 105 であることをホスト名とホスト鍵で確かめる (VM 110 と IP が重複しているため)
  - 完了時、k3s-agent-z440 から VM 105 へ鍵で ssh でき、前提の確認結果と実施の記録が `manual-operations.md` に残っている
  - _Requirements: 1.1, 1.3_

- [x] 5.2 (P) アプリの分類を記録する
  - 設計の分類表 (継続 / 継続しない / データの扱い) を `migration-records.md` に記録する
  - 表にも継続の一覧にも無いアプリ、または到達するバージョンに対応しないアプリが見つかった場合は、無効にして記録に残す
  - 完了時、分類表と、無効にしたアプリの記録が残っている
  - _Requirements: 2.8, 12.7_
  - _Boundary: MigrationRecords_

- [x] 5.3 移行元から読み取りだけでファイル・設定・DB を取り出す
  - k3s-agent-z440 のホストから、各利用者の `files_trashbin/` を除いてデータディレクトリを数値の所有者を保って rsync で `data/` へ写す
  - `config/config.php` だけを取り、コードは取らない
  - `mysqldump --single-transaction` を移行元で実行し、出力を ssh 経由で移行先に受ける。移行元のディスクに書かない
  - ホストから `/dev/sdb` をマウントしない
  - 取り出した `config.php` の `secret` と `passwordsalt` を、値を表示せずに Infisical に登録する
  - 完了時、移行先にファイルと `config.php` と DB のダンプが揃い、移行元に書き込みが無い
  - _Requirements: 1.2, 2.2, 2.3, 2.4, 2.9, 9.2_

- [x] 6. 移行先での段階更新と変換 (リハーサル)
- [x] 6.1 Stage: 一時 MariaDB と `config.php` を用意し、30.0.17 で起動する
  - ダンプを一時 MariaDB に読み込む
  - `config.php` の DB の接続先・Redis・ローカルキャッシュ・`apps_paths` を設計の表どおりに書き換え、`datadirectory`・`secret`・`passwordsalt`・`instanceid` は移行元のまま `html/config/` に置き、公式イメージの `apps.config.php` を置く
  - `replicas: 1` にする commit を積む
  - 継続するアプリを `occ app:install` で入れてから `occ upgrade` で 30.0.17 に上げ、`cron.php` を 2〜3 回実行する
  - 完了時、`occ status` が 30.0.17 と導入済みを返し、継続するアプリが有効になっている
  - _Requirements: 2.4, 2.9, 6.1, 12.2, 12.3, 12.9_

- [x] 6.2 31.0.14 に上げて PostgreSQL へ変換する
  - イメージのタグを 31.0.14 に変える commit を積み、`cron.php` を 2〜3 回実行する
  - 変換の直前に deck と mail を含む継続するアプリが有効であることを確かめ、無効なら止める
  - 変換の直前に MariaDB で主要なテーブルの行数を数える
  - `occ db:convert-type --all-apps` で `nextcloud-db` へ変換する。パスワードはコマンド行に書かない。失敗したら `--clear-schema` を付けて再実行する
  - 変換の直後に PostgreSQL で同じテーブルの行数を数え、突き合わせの結果を `migration-records.md` に記録する
  - 完了時、Nextcloud が PostgreSQL に接続して動き、行数の突き合わせが一致している
  - _Requirements: 12.2, 12.3, 12.4, 12.5, 12.9_

- [x] 6.3 32 から 35 まで 1 メジャーずつ上げる
  - 32.0.15、33.0.10、34.0.5、35.0.2 の順に、タグを変える commit を 1 段ずつ積み、各段の後に `cron.php` を 2〜3 回実行する
  - 32 以降の段で、App Store が入れた Mail が 5.10.14 以上であることを確かめる
  - 各段で継続するアプリが導入された版を記録する
  - 完了時、`occ status` が 35.0.2 を返し、Mail 5.12.6 以上が有効化されて DB 移行が成功している
  - _Requirements: 3.6, 12.1, 12.2, 12.9_

- [x] 6.4 ゴミ箱を空にし、移行対象外のアカウントを削除する
  - `occ trashbin:cleanup --all-users` を実行し、ゴミ箱が空であることを確かめる
  - 移行対象外のアカウントを `occ user:delete` で消し、共有・カレンダー・連絡先・ファイルキャッシュにそのアカウントの行が残らないことを照会する
  - 結果をアカウント名を書かずに記録する
  - 完了時、ゴミ箱が空で、対象外のアカウントの行が残っていないことの照会結果が記録に残っている
  - _Requirements: 2.1, 2.3_

- [x] 6.5 Configure を実行して移行先の設定を入れる
  - `configure.sh` を `app` コンテナ内で www-data として実行する
  - 2 回続けて実行して結果が変わらないことを確かめる
  - config.php の値、provider、`/SMB` の接続先、継続しないアプリの無効化を照会して確かめる
  - 発行された管理者のアプリパスワードを、値を表示せずに Infisical に登録する
  - 完了時、照会した設定がすべて設計どおりで、Infisical に管理者のアプリパスワードが登録されている
  - _Requirements: 4.5, 5.1, 5.3, 5.6, 5.7, 6.4, 10.5_

- [x] 6.6 Mail のプロビジョニングの Job を宣言して投入する
  - REST API に冪等に投入する Job を、`jq` を含むイメージで宣言する。既存の `provisioningDomain=="*"` の設定があれば更新し、無ければ作成し、毎回 `masterPassword` の実値を送る
  - 認証は管理者のアプリパスワードによる Basic 認証と `OCS-APIRequest` ヘッダで行い、資格情報は Infisical から供給する
  - Job 名の連番の書式はこのタスクで決め、リハーサル用の名前で commit する
  - `ttlSecondsAfterFinished` を付けない
  - 完了時、Job が成功し、同じ内容で 2 回実行してもプロビジョニングの設定が重複しない
  - _Requirements: 6.2, 6.3_

- [ ] 6.7 アカウントの付け替えスクリプトを作り、移行先へ適用する
  - gitops-apps の `apps/nextcloud/scripts/reassign-account.sh` を設計の Reassign の順に作る。`configure.sh` と同じ置き場所・同じ実行 (www-data で runuser) にする。旧 uid と新 uid は環境変数で渡し、各手順は済んでいれば飛ばす。ユーザー設定は設計の除外分を除いて `occ user:setting` で 1 件ずつ移す
  - `configure.sh` (a) に `skeletondirectory` (空文字)、`default_language` (`ja`)、`default_locale` (`ja_JP`)、`default_timezone` (`Asia/Tokyo`) を足す
  - 移行先へ適用し、所要時間を実測して記録する。共有の検証は共有先のファイルが存在する共有だけを数える
  - 2 回続けて実行して結果が変わらないことを確かめる
  - `configure.sh` を再実行する。管理者のアプリパスワードは新 uid で発行されるため、Infisical の `NEXTCLOUD_MAIL_PROVISIONING_AUTH` を値を表示せずに登録し直し、`mail-provisioning` の Job を連番を進めて再実行する
  - 結果をアカウント名を書かずに記録する
  - 完了時、旧 uid のファイル・カレンダー・Deck・共有が新 uid に揃い、旧アカウントが無く、`NEXTCLOUD_MAIL_PROVISIONING_AUTH` が新 uid のものになっている
  - _Requirements: 2.1, 2.2, 2.4, 5.3, 6.3_
  - _Depends: 6.4, 6.6_

- [ ] 7. リハーサルの検証と実測
- [x] 7.1 ファイルの件数・合計サイズ・内容を突き合わせる
  - 移行対象のアカウントの `files/` と `files_versions/` について、両側でファイル件数とバイト数を数える
  - 両側で全ファイルの SHA-256 の一覧を、移行元の旧 uid のパスと移行先の新 uid のパスを対応させて作り、突き合わせる
  - 結果と差異を `migration-records.md` に記録する
  - 完了時、件数・サイズ・内容の突き合わせの結果が記録され、差異があればその内容が記録されている
  - _Requirements: 2.2, 2.5, 2.6, 2.7_

- [ ] 7.2 認証の結びつきと拒否を実測する
  - Kanidm からログインし、移行したファイルが見えること、`oc_users` と `oc_user_oidc` の件数が Reassign の後から変わらないことを確かめる
  - `?direct=1` を含むパスワードログインの POST が 403 になり、利用者パスワードでの WebDAV が拒否されることを確かめる
  - デスクトップとモバイルの同期クライアントがログインフロー v2 で接続し、アプリパスワードで同期できることを確かめる
  - 完了時、各項目の実測結果が記録に残り、新しいアカウントが作られていない
  - _Requirements: 4.3, 5.3, 5.6, 5.7, 5.8_

- [ ] 7.3 公開経路と管理画面の状態を実測する
  - 宅外の回線から `https://cloud.fickledev.com/status.php` が応答し、`http://` が 301 を返すことを確かめる
  - Traefik のアクセスログで送信元が利用者のアドレスになっていること、`websecure` の既存経路の送信元の扱いが変わらないことを確かめる
  - 35 の管理画面の「セキュリティと設定の警告」を記録し、リバースプロキシとホスト名に起因するものが無いことを確かめる
  - 管理画面に背景ジョブの最終実行時刻が表示されることを確かめる
  - 完了時、各項目の実測結果が記録に残っている
  - _Requirements: 3.7, 4.1, 4.2, 4.4, 4.7, 4.8_

- [ ] 7.4 大きなファイルを宅外から実測する
  - 宅外の回線から、Web とデスクトップのクライアントで 49GB 以上のファイルをアップロードし、ダウンロードする
  - 完了したことを合否とし、所要時間は記録だけする
  - テスト用のファイルを実測の後に消す
  - 完了時、両方のクライアントでアップロードとダウンロードが完了したことが記録に残っている
  - _Requirements: 7.1, 7.2, 7.3, 7.4_

- [ ] 7.5 Web メールと通知メールを実測する
  - Mail を開いた時点でアカウントが作られ、パスワードの入力なしに受信・閲覧・送信ができることを確かめる
  - 管理画面の「メールを送信してテスト」が届くことを確かめる
  - メールクライアントが従来のアプリケーションパスワードで接続できることを確かめる
  - 完了時、各項目の実測結果が記録に残っている
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

- [x] 7.6 資源の使用量を実測して要求量を見直す
  - リハーサル中の Nextcloud・DB・Redis・一時 MariaDB のメモリと CPU を実測する
  - 仮の requests / limits を実測に基づいて見直す commit を積む
  - 完了時、k3s-agent-z440 の requests の合計が割当可能量に収まり、同居するワークロードが追い出されていない
  - _Requirements: 3.5_

## Phase 3: 切り替え

- [ ] 8. 切り替え
- [ ] 8.1 `backup-durability-and-alerting` の要件 4.15 の完了を確かめる
  - k3s の CronJob と Job の失敗が定めた通知先へ届くことが、同 spec の側で確かめられていることを確認する
  - 未完了なら関門 A1 に進まず、VM 105 を本番のまま保つ
  - 完了時、4.15 の完了の確認結果が `manual-operations.md` に記録されている
  - _Requirements: 8.10_

- [ ] 8.2 切り戻しの手順と失われる範囲、Kanidm 障害時の管理経路を記録する
  - 切り戻しで失われる範囲 (切り替え後に移行先で行われたすべての変更) と、移行先から移行元へ戻す経路を持たないことを `manual-operations.md` に書く。運用者の確認は待たない
  - 切り戻しの手順 (移行元の保守モードの解除だけで、宅内の LAN から直接使える状態に戻す。外部公開は戻さない) を `manual-operations.md` に定める
  - Kanidm が使えないときに kubectl から occ を実行する管理の手順を `manual-operations.md` に定める
  - 完了時、失われる範囲が記録に残っている
  - _Requirements: 5.5, 9.2, 9.4_

- [ ] 8.3 関門 A1 の前提を確かめてから移行元を保守モードにし、パイプラインを再実行する
  - 前提 (`backup-durability-and-alerting` の 4.15 の完了と、リハーサルの検証 (要件 2、5.8、7.4) の合格) をコマンドの結果で確かめ、満たさなければ止まって報告する
  - 移行元を保守モードにするのと同時に、同じ config.php への書き込みで `trusted_domains` に `192.168.1.11` を足す。移行元の `trusted_domains` は旧ドメイン 2 つだけで LAN の名前・IP を含まないことは読み取りで確認済み。切り戻しは移行元の保守モードの解除だけで行う。対象・影響範囲・戻し方を `manual-operations.md` に記録する。VM 105 は止めず、同居サービスに影響させない
  - 移行先を `replicas: 0` → 移行先での変更と DB を捨てる → タグを 30.0.17 に戻す → Stage → `replicas: 1` の順で作り直す
  - 最終ダンプと最終差分の rsync を取り、Stage から Reassign と Configure までを再実行する
  - 完了時、移行元が保守モードで、移行先が 35.0.2 で Reassign と Configure まで済んだ状態になっている
  - _Requirements: 1.3, 1.5, 9.1, 12.6_

- [ ] 8.4 プロビジョニングを再投入し、保守モードで突き合わせる
  - 連番を進めた切り替え用の名前の `mail-provisioning` Job を commit して投入する
  - 移行先で保守モードを有効にする
  - 移行元の旧 uid のパスと移行先の新 uid のパスを対応させて、件数・サイズを突き合わせ、最終差分の rsync が転送・削除したファイルだけを両側で SHA-256 を再計算して突き合わせる
  - 差異があれば切り替えず、内容を記録する
  - 完了時、静止した状態での突き合わせの結果が一致として記録されている
  - _Requirements: 2.5, 2.6, 2.7, 6.3_

- [ ] 8.5 宅外の最初の世代を停止時間の中で取る
  - 宅外のリポジトリが無ければ作り、`pg_dump` の後に移行先から直接 `restic backup` する単発の Job `nextcloud-backup-initial-<連番>` を宣言する。保守モードには触れない
  - 対象と除外は退避の CronJob と同じにし、`RCLONE_DRIVE_STOP_ON_UPLOAD_LIMIT=true` を与え、`ttlSecondsAfterFinished` を付けない
  - 停止時間の中で commit して起動し、失敗したら連番を進めて再実行する
  - 完了時、GDrive の restic リポジトリに 1 世代が存在し、`restic snapshots` で確かめられる
  - _Requirements: 8.3, 8.4, 8.9, 8.15_

- [ ] 8.6 移行先の保守モードを解除して Live にし、認証を再実測する
  - 移行先の保守モードを解除する
  - OIDC で付け替え後のアカウントに結びつき新しいアカウントが作られないこと、ローカルパスワードログインが拒否されることを確かめる
  - 失敗したら保守モードに戻して Configure を直し、再実行する
  - 完了時、利用者が `cloud.fickledev.com` を使える状態で、再実測の結果が記録に残っている
  - _Requirements: 5.7, 5.8_

- [ ] 8.7 一時 MariaDB を撤去する
  - 変換と行数の記録が済んだ後に、一時 MariaDB の宣言を `kustomization.yaml` からも消す commit を積む
  - 完了時、`nextcloud` namespace に MariaDB の資源が無く、宣言にも残っていない
  - _Requirements: 12.10_

- [ ] 8.8 外形監視・ログイン拒否の監視・データディスクの使用率監視を足す
  - Gatus のテンプレートに、`endpoint.method` が定義されているときだけ出力する分岐を足す。既存のエンドポイントの出力は変えない
  - `gatus_endpoints` に `status.php` の監視 `nextcloud` と、`POST /login` が 403 であることの監視 `nextcloud-login-deny` を足し、既存の注記を合わせる
  - `beszel_agent` に、ホストごとの追加ファイルシステムを `EXTRA_FILESYSTEMS` で渡す変数を足し (既定は空で既存のホストの挙動を変えない)、k3s-agent-z440 に `/var/lib/nextcloud` を与える
  - Live の後に行う
  - 完了時、Gatus で 2 つのエンドポイントが成功と判定され、既存のエンドポイントの判定が変わらず、Beszel で `/var/lib/nextcloud` の使用率が見え既存の `Disk` アラートの判定対象に入っている
  - _Requirements: 5.7, 8.11, 8.12_

## Phase 4: 宅外からの復元確認

- [ ] 9. 宅外からの全量復元を確かめる
  - 専用ディスクの空きが復元の量を上回ることを確かめ、下回れば実行しない
  - GDrive のリポジトリの最新の世代を専用ディスクの一時ディレクトリへ `restic restore --verify` で全量復元する
  - Infisical とは別の場所の鍵の控えから鍵を読んで復元できることを確かめる
  - DB のダンプを `nextcloud-db` 内の一時の DB に読み込み、主要なテーブルの行数を本番と比べる
  - 確認の後に一時ディレクトリと一時の DB を消す
  - 完了時、復元の成功と行数の一致が `manual-operations.md` に記録されている
  - _Requirements: 8.2, 8.5_

## Phase 5: VM 105 と同居サービスの撤去

- [ ] 10. VM 105 の撤去
- [ ] 10.1 Pi-hole の参照が残っていないことを確かめる
  - OPNsense の DHCP が配る DNS サーバー、Unbound の転送先、各ホストのリゾルバ設定に Pi-hole のアドレスが無いことを確かめる
  - Pi-hole の問い合わせ記録から直近の問い合わせ元を読み取りで確かめる
  - 参照元があれば既存の DNS (OPNsense) へ切り替える。代替のサービスは新設しない
  - 完了時、Pi-hole を参照する機器と設定が無いことが記録されている
  - _Requirements: 10.1, 10.2, 10.3_

- [ ] 10.2 samba の代替と外部ストレージの接続先を確かめる
  - NAS の samba の共有が使え、Nextcloud の外部ストレージ `/SMB` が NAS に接続していることを確かめる
  - 完了時、VM 105 の samba に依存する利用が無いことが記録されている
  - _Requirements: 10.4, 10.5_

- [ ] 10.3 関門 A2 の前提を確かめてから VM 105 を停止する
  - 移行の検証 (要件 2)、宅外からの全量復元 (8.2)、Pi-hole を参照している所が無い (または 10.2 で既存の DNS へ切り替え済み) ことをコマンドの結果で確かめ、満たさなければ止まって報告する
  - 対象と影響範囲と元に戻す手順を `manual-operations.md` に記録して停止する
  - 完了時、VM 105 が停止し、前提の確認結果と実施の記録が残っている
  - _Requirements: 1.4, 9.3_

- [ ] 10.4 関門 A3 の前提を確かめてから VM 105 を削除する
  - 前提 (A2 の完了、VM 105 の設定から `/dev/sdb` を外したこと) をコマンドの結果で確かめ、満たさなければ止まって報告する
  - 起動用ディスクが失われることを `manual-operations.md` に記録して削除する
  - 削除の後に、関門 A0 で用意した一時の鍵を消す
  - 完了時、VM 105 が Proxmox に存在せず、`/dev/sdb` がホストに残り、一時の鍵が消えている
  - _Requirements: 1.4, 9.3_

## Phase 6: 宅内の退避先

- [ ] 11. `/dev/sdb` の転用と退避の全段の有効化
- [ ] 11.1 `/dev/sdb` の健全性を診断する
  - hp-z440 で SMART の自己診断 (long) を行い、代替・保留・修正不能セクタと自己診断の結果を記録する
  - 記録するだけで、結果で採否を分けない
  - 完了時、診断の結果が記録されている
  - _Requirements: 8.8_

- [ ] 11.2 (P) 単一ディスクの ZFS プールを作る play を用意する
  - hp-z440 で `/dev/sdb` を ZFS プール `zfs-backup` にする play を新設する。`/dev/sdb` が既にプールの構成ディスクであれば何もしない冪等ガードを持たせる
  - `host_health_zfs_pools` に `zfs-backup` を足す
  - play はこのタスクでは実行しない
  - 完了時、`ansible-lint` が通り、check モードで冪等ガードの分岐が確かめられる
  - _Requirements: 8.6, 8.7_
  - _Boundary: BackupDiskPool_

- [ ] 11.3 VM モジュールにデータストアのディスクの宣言を足す
  - VM モジュールに map 変数 `datastore_disks` と、それを回す `dynamic "disk"` を既存の `lvm_disks` のブロックの後ろに足す。`zfs_pools` と `lvm_disks` は変えない
  - 新プールを `proxmox_storage_zfspool` で登録する宣言と、k3s-agent-z440 の `datastore_disks.restic_local` (scsi4、`backup = false`) を足す。`size` はプールの作成後に決まるため 11.4 で確定する
  - 同じ commit で `host_vars/pbs` の `backup_excluded_disks` に scsi4 を足す (Terraform と Ansible が打ち消し合わないため)
  - このタスクでは適用しない
  - 完了時、`terraform validate` が通り、plan で VM 152 の差分がディスク 1 本の追加だけで、他の VM と既存のディスクに差分が無い
  - _Requirements: 8.1, 8.6_

- [ ] 11.4 関門 A4 の前提を確かめてから `/dev/sdb` を初期化し、VM 152 へ渡す
  - 前提 (A3 の完了と、11.1 の SMART の結果の記録) をコマンドの結果で確かめ、満たさなければ止まって報告する。対象と影響範囲を `manual-operations.md` に記録する
  - ZFS プールを作る play を実行し、Terraform を適用する
  - `agent_data_disks` に退避先 (12 文字以内で `nextcloud` と重ならない名前をこのタスクで決める) を足して xfs で初期化し、`/var/lib/nextcloud-backup` にマウントする
  - `datastore_disks.restic_local` の `size` は、作ったプールの `zpool list` の FREE の 90% を 100G 単位で切り捨てた値 (試算上 1600 前後) にする
  - 完了時、`zpool status` が正常で、k3s-agent-z440 に `/var/lib/nextcloud-backup` がマウントされ、既存の `/var/lib/nextcloud` が変わっていない
  - _Requirements: 8.6, 8.7_

- [ ] 11.5 宅内のリポジトリを作り、退避の CronJob の全段を有効にする
  - 宅内の退避先の静的 PV / PVC (Retain、`Prune=false,Delete=false`) を足し、CronJob だけが参照する
  - 宅内のリポジトリを GDrive のリポジトリからチャンカーのパラメータを写し、`--insecure-no-password` で作る
  - 宅内への取得と宅外への `copy` を有効にし、CronJob を `suspend: false` にする commit を積む
  - 完了時、Nextcloud 本体の Pod の定義に宅内の退避先が現れず、CronJob が停止状態でなくなっている
  - _Requirements: 8.1, 8.6, 8.14, 8.16_

- [ ] 11.6 退避の毎晩の実行と失敗時の挙動を確かめる
  - 毎晩の実行が成功し、宅内と宅外に世代が増え、宅外への送信が差分だけであることを確かめる
  - 失敗を注入した実行 (宅内の退避先を読み取り専用にする等) で、保守モードが解除され Job が失敗で終わることを確かめる
  - 保守の時間の長さを記録する
  - 完了時、成功と失敗注入の両方の結果が記録されている
  - _Requirements: 8.1, 8.9, 8.10, 8.14_

- [ ] 11.7 宅内の退避先の使用率を監視対象に入れる
  - k3s-agent-z440 の追加ファイルシステムに `/var/lib/nextcloud-backup` を足す
  - 完了時、Beszel で `/var/lib/nextcloud-backup` の使用率が見え、既存の `Disk` アラートの判定対象に入っている
  - _Requirements: 8.12_

## Phase 7: 記録の一致

- [ ] 12. 記録を実態に合わせる
- [ ] 12.1 steering を移行後の実態に合わせる
  - `tech.md` の Storage 節・Proxmox Guests 表・Backup 節と `product.md` の Nextcloud の所在、移行先の予約、`/dev/sdb` の記述を実態に合わせる
  - 完了時、steering に VM 105 の Nextcloud と「空の予約」の記述が残っていない
  - _Requirements: 11.1_

- [ ] 12.2 (P) 退避除外の宣言の理由を改める
  - PBS の `scsi2` の除外理由を「restic で別媒体へ退避している」に改め、宅内の退避先のディスク (11.3 で除外済み) の注記も同じ理由に揃える
  - `terraform/locals.tf` の `nextcloud` の注記を同じ理由に改める
  - 完了時、除外の宣言に「空であること」を理由とする記述が残っていない
  - _Requirements: 11.2_
  - _Boundary: RecordsAlignment_

- [ ] 12.3 乖離検出に移行後の Nextcloud を反映する
  - `check_host_address_drift.py` の `STATIC_UNMANAGED_HOSTS` から `nextcloud` を外し、テストを合わせる
  - 完了時、`pytest scripts/` が通る
  - _Requirements: 11.3_
