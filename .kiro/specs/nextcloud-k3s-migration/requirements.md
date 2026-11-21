# Requirements Document

## Project Description (Input)
Nextcloud を Proxmox VM 105 (hp-z440、/dev/sdb raw passthrough、2TB、使用量約621GB) から k3s へ移行する。移行先は k3s-agent-z440 上に予約済みの zvol (terraform/locals.tf の nextcloud、1000G、/var/lib/nextcloud)。メールの Web クライアント (Roundcube 等) を含む。VM 105 は spec 確定まで読み取りのみ許可、書き込み・停止・スナップショット・バックアップ実行は禁止。

## Introduction

Nextcloud は Proxmox VM 105 上で、宣言の管理外のまま稼働している。データは冗長性の無い単一の HDD (`/dev/sdb` の raw passthrough) にあり、PBS の退避対象にも含まれていない。代替不能なデータが、退避の無い単一ディスクに置かれている状態である。

移行元を読み取りのみで調べた結果 (2026-10-29 時点) は次のとおり。

- Nextcloud 30.0.2 を tarball で導入し、Apache + PHP-FPM 8.2、MariaDB 10.11、Redis で動かしている
- データ使用量は約 621GB。内訳はファイル約 305GB、ゴミ箱約 268GB、バージョン約 17GB
- 4GiB を超えるファイルが複数あり、最大は約 49GB
- 認証はローカルのみ。共有、カレンダー、連絡先、メールアカウント (Nextcloud Mail) の設定を持つ
- 外部からは現在到達できない。旧ドメイン `tochiweb.mydns.jp` は今も VPS の IP に解決されるが、VPS 側の vhost 撤去によって公開経路は失われている
- 同居する samba の共有先はマウントされておらず、中身は空
- サーバーサイド暗号化は無効

本 spec は Nextcloud を k3s へ移し、保守期間内のバージョンへ上げ、データベースを PostgreSQL へ移したうえで GitOps の宣言下に置く。そのうえで VM 105 を撤去する。VM 105 に同居する Pi-hole は撤去し、samba は NAS で代替する。あわせて、データを失わないこと (移行中も移行後も) と、Kanidm を単一の IdP とする既存の認証体系に組み込むことを満たす。メールの Web クライアントは新設せず、Nextcloud が担う (mail-platform の決定を引き継ぐ)。

## Boundary Context

- **In scope**: 移行先での Nextcloud の稼働と宣言化、移行元からのデータと設定の移行 (ゴミ箱を除く)、移行の完全性の検証、`cloud.fickledev.com` での外部公開と TLS (ファイルの大きさによらない単一の公開経路、中継点で復号しない、送信元 IP の受け渡し)、Kanidm による認証、ホームラボのメール基盤に接続する Web メール (Nextcloud Mail)、移行後のデータの退避と障害の検知、切り替えと切り戻しの手順、VM 105 の撤去、同居する Pi-hole の撤去、同居する samba の NAS による代替、VM 105 撤去後の `/dev/sdb` の退避先への転用、Nextcloud のアップグレード、データベースの MariaDB から PostgreSQL への移行、外部の記憶領域 (GDrive) への暗号化された複製
- **Out of scope**: 旧ドメイン `tochiweb.mydns.jp` に関わる VPS 側の残置物 (証明書更新の cron、DDNS 更新) の撤去、退避基盤全体の設計 (`backup-durability-and-alerting` が扱う)、ストレージへの冗長性の付与
- **Adjacent expectations**:
  - `gitops-apps` への変更を含む。既存の規約に従う。データを持つボリュームは prune と削除の対象から外す。専用ディスクは静的な PV でアプリに渡す (Garage の前例)。ノードは固定する。シークレットは Infisical Operator で供給する
  - 移行先の zvol (`vm-152-disk-1`) は PBS のデータストアと同じ物理 HDD (`zfs-pool`、単一 vdev) 上にある。PBS による退避だけでは、退避先を対象と別の記憶装置に置く原則を満たさない
  - VM 105 は、本 spec の確定まで読み取りのみ許可されている。確定後の書き込み系の操作は、設計の関門で定めた前提を確かめてから実行する
  - `backup-durability-and-alerting` は、VM 105 のデータの退避を本移行の完了後に扱うとしている。本 spec の完了がその前提になる
  - 宅外からの転送速度は、中継する VPS の回線帯域 (100Mbps) が上限になる。この上限は受け入れる。帯域はメール基盤と共有する。宅外への複製 (GDrive) は宅内の回線から送るため、この上限の影響を受けない

## Requirements

### Requirement 1: 移行元の保全

**Objective:** As a ホームラボ運用者, I want 移行の全期間を通して移行元のデータが失われないことを保証したい, so that 移行が失敗しても元の状態へ戻せる

#### Acceptance Criteria

1. While 本 spec が確定していない, the 移行作業 shall VM 105 と `/dev/sdb` に対して読み取り以外の操作を行わない。
2. While 移行元を切り戻し先として保持している, the 移行作業 shall 移行元のデータディスク (`/dev/sdb`) に書き込まない。データの取り出しは読み取りだけで行う。
3. When 移行元に対して状態を変える操作 (メンテナンスモードへの切り替え、`trusted_domains` への追加、サービスの停止、設定の変更) が必要になった場合, the 移行作業 shall 設計の関門で定めた前提を確かめ、対象と影響範囲と元に戻す手順を記録してから実行する。
4. The 移行作業 shall 移行先での検証と退避の確認 (Requirement 8.2) が完了するまで、移行元のデータを消去しない。
5. While 切り替えが完了していない, the 移行作業 shall VM 105 を停止しない。VM 105 に同居する他のサービスが移行の影響を受けない。

### Requirement 2: データと設定の移行

**Objective:** As a Nextcloud の利用者, I want 移行の前と同じファイルと付随する情報を使い続けたい, so that 移行による欠落に気づかないまま元を失う事態を避けられる

#### Acceptance Criteria

1. The 移行後の Nextcloud shall 運用者本人のアカウントのファイルを保持する。長期間利用実績が無くデータを持たないアカウントは移行の対象とせず、移行先で削除し、そのアカウントのファイル・共有・カレンダー・連絡先が残らないことを確かめる。
2. The 移行作業 shall 移行元のファイルのバージョン履歴を移行後の Nextcloud に引き継がない (アカウントの付け替えでバージョン履歴を新しいアカウントへ移す製品機能が無いため)。
3. The 移行作業 shall 移行元のゴミ箱の内容 (約 268GB) を移行の対象から除く。移行後の Nextcloud のゴミ箱は空の状態で始まる。
4. The 移行後の Nextcloud shall 移行元の共有、カレンダー、連絡先、各アプリの利用者データを保持する。
5. The 移行作業 shall 移行元と移行先とで、移行対象のアカウントのファイル件数と合計サイズを突き合わせ、結果を記録する。
6. The 移行作業 shall 抽出したファイルについて、移行元と移行先とで内容が一致することを検証する。
7. If 突き合わせで差異が見つかった場合, then the 移行作業 shall 切り替えを行わず、差異の内容を記録する。
8. The 移行作業 shall 移行元で有効なアプリを、移行先で継続するものと継続しないものに分けて記録する。継続しないアプリについては、そのデータの扱いも記録する。
9. The 移行後の Nextcloud shall 移行元のインスタンスの秘密値 (`secret`、`passwordsalt`) を引き継ぐ。移行元で暗号化して保存された認証情報 (Nextcloud Mail のアカウント、外部ストレージ) が移行後も使える。

### Requirement 3: k3s 上での稼働と宣言

**Objective:** As a IaC 保守担当, I want Nextcloud の構成をすべてコードで宣言したい, so that 実機を見なくても構成を再現・把握できる

#### Acceptance Criteria

1. The Nextcloud の構成 shall `gitops-apps` に宣言され、ArgoCD によって同期される。
2. The Nextcloud のファイルデータ shall k3s-agent-z440 に予約済みの専用ディスク (`/var/lib/nextcloud`) に置かれる。
3. If 宣言からアプリが削除された場合や同期の際に prune が実行された場合, then the データを持つボリューム shall 削除されずに残る。
4. The Nextcloud が使うシークレット shall Infisical から供給される。リポジトリに平文で記録しない。
5. The Nextcloud の資源の要求量 shall k3s-agent-z440 の空き資源の範囲に収まり、同居する既存のワークロードを圧迫しない。
6. The 移行後の Nextcloud shall 保守期間内のメジャーバージョンで稼働する (Requirement 12)。
7. The Nextcloud のバックグラウンドジョブ shall 定期的に実行され、最終実行時刻を確認できる。

### Requirement 4: 公開経路と TLS

**Objective:** As a Nextcloud の利用者, I want ブラウザと同期クライアントから HTTPS で接続したい, so that 宅外からもファイルを使える

#### Acceptance Criteria

1. The Nextcloud shall `cloud.fickledev.com` で外部に公開され、HTTPS で提供される。
2. The Nextcloud shall Nextcloud 本体の管理画面に表示されるセキュリティと設定の警告のうち、リバースプロキシとホスト名の設定に起因するものを残さない。
3. The Nextcloud shall デスクトップとモバイルの同期クライアントから接続できる。
4. If 平文の HTTP で接続された場合, then the 公開経路 shall HTTPS へ転送する。4.6 の「復号しない」は HTTPS の通信を対象とし、この転送の応答には適用しない。
5. The Nextcloud shall 旧ドメイン `tochiweb.mydns.jp` を引き継がない。
6. The 公開経路 shall 利用者の端末から Nextcloud の手前の終端までを暗号化したまま中継する。中継するホスト (VPS) で通信を復号しない。
7. The Nextcloud shall 利用者の送信元 IP アドレスを識別できる。中継するホストのアドレスに一律に置き換わらない。
8. The 公開経路 shall 既存の公開経路 (Cloudflare Tunnel 経由のもの) の送信元の扱いに影響を与えない。

### Requirement 5: 認証

**Objective:** As a ホームラボ運用者, I want Nextcloud のログインを Kanidm に集約したい, so that アカウントと MFA の管理を一箇所で済ませられる

#### Acceptance Criteria

1. The Nextcloud shall Kanidm を IdP とする OIDC でログインを受け付ける。
2. The Kanidm の OAuth2 クライアント shall `terraform-kanidm/` に宣言される。
3. When Kanidm で認証された利用者が初めてログインした場合, the Nextcloud shall その利用者を移行元の既存アカウントに対応づけ、移行したデータを引き継がせる。対応づけは Kanidm の短い名前とユーザー ID の照合で行い、独自の claim を要しない。移行作業は、運用者の移行元アカウントを Kanidm の人のアカウント名と同じユーザー ID の新しいアカウントへ付け替えて、このユーザー ID に移行したデータを結びつけておく。
5. If Kanidm が利用できない場合, then the 運用者 shall クラスタの管理経路 (kubectl) から Nextcloud の管理コマンドを実行して復旧作業を行う。Web にはパスワードでログインできる非常口を設けない。
6. Where 同期クライアントがアプリパスワードで接続する, the Nextcloud shall Kanidm を経由せずにアプリパスワードで認証できる。
7. The Nextcloud shall 利用者のローカルパスワードによる Web へのログインを受け付けない。
8. The 移行作業 shall 5.3 の対応づけで付け替え後のアカウントに結びつき、新しいアカウントが作られないことを、切り替えの前に移行先で実測する。

### Requirement 6: Web メール

**Objective:** As a メールの利用者, I want ブラウザからホームラボのメールボックスを読み書きしたい, so that メールクライアントの無い端末でもメールを使える

#### Acceptance Criteria

1. The Web メール shall Nextcloud のメール機能で提供される。メール専用の Web クライアントを別に立てない。
2. The Web メール shall ホームラボのメール基盤 (IMAP は k3s の `mailbox`、送信は VPS の docker-mailserver) に TLS で接続し、受信・閲覧・送信ができる。
3. The Web メール shall Nextcloud のメールのプロビジョニングにより、利用者がメールのパスワードを入力せずに接続する。メール基盤には master user による認証を加え、既存の認証方式 (Kanidm のアプリケーションパスワード) はメールクライアントのために残す。
4. The Nextcloud の通知メール shall ホームラボのメール基盤から送信される。

### Requirement 7: 大きなファイルの取り扱い

**Objective:** As a Nextcloud の利用者, I want 移行元にあるのと同じ大きさのファイルを扱い続けたい, so that 移行によって扱えないファイルが生まれない

#### Acceptance Criteria

1. The Nextcloud shall 移行元に存在する最大のファイル (約 49GB) と同等以上の大きさのファイルを、Web と同期クライアントの両方からアップロード・ダウンロードできる。
2. The Nextcloud shall ファイルの大きさによって接続先のホスト名や公開経路を変えない。大きなファイルも、通常の利用と同じ経路で扱える。
3. The 公開経路 shall 1 リクエストあたりの本文の大きさと、応答を待つ時間に、7.1 の大きさの分割アップロードとその結合を妨げる上限を持たない。この条件は中継の各段 (VPS の中継、クラスタの入口、Nextcloud の Web サーバーと PHP) のそれぞれで満たし、既定値に頼らず明示する。
4. The 移行作業 shall 7.1 の大きさのファイルについて、宅外からのアップロードとダウンロードが完了することを、切り替えの前に実測する。実測は宅外の回線から実際のクライアントで行い、完了したことを合否とする。所要時間の目標値は置かない。

### Requirement 8: 退避と障害の検知

**Objective:** As a ホームラボ運用者, I want 移行後のデータを本体とは別の記憶装置と宅外に退避し、異常に気づける状態にしたい, so that 移行によって代替不能なデータの保護が弱まらない

#### Acceptance Criteria

1. The Nextcloud のデータとデータベース shall 本体 (移行先の専用ディスク) に加え、本体と物理的に異なる宅内の記憶装置と、宅外の記憶領域の 2 か所に退避される。ただし 8.16 の期間は宅内の退避先を欠く。
2. The 退避 shall VM 105 の撤去の前に、宅外の記憶領域から少なくとも 1 世代を取得し、そこから復元できることが確認されている。
3. The 宅外への複製 shall 既存の外部の記憶領域 (GDrive) に保存する。新たな提供元との契約を要しない。
4. The 宅外への複製 shall 提供元がファイルの内容とファイル名を読み取れない形で保存する。
5. The 宅外への複製の復号に要する鍵 shall Infisical に保存し、あわせて Infisical とは別の場所に控えを持つ。Infisical が利用できない状況でも復元できる。
6. The 宅内の退避先 shall VM 105 の撤去後の `/dev/sdb` とし、k3s-agent-z440 へ渡す。Nextcloud 本体はこの退避先をマウントしない。宅内の退避は、本体と同じく自宅内にあるため秘匿のための暗号化をしない。退避の道具の都合で鍵を要する場合も、鍵を失って宅内の退避が読めなくなる状態を作らない。
7. The 移行作業 shall `/dev/sdb` を退避先として初期化する操作を、移行の検証 (Requirement 2) と宅外からの復元の確認 (8.2) が完了した後に、対象と影響範囲を記録してから実行する。
8. The 移行作業 shall `/dev/sdb` を退避先とする前に健全性の診断を行い、結果を記録する。
9. The 退避 shall ファイル、データベース、Nextcloud の設定を、復元時に整合する同一の時点で取得する。
10. If 退避が失敗した場合, then the 退避機構 shall 既存の通知経路 (Discord) へ通知する。
11. If Nextcloud が外部から応答しなくなった場合, then the 外形監視 shall 既存の通知経路へ通知する。
12. When Nextcloud のデータディスクまたは退避先の使用率が定めた閾値を超えた場合, the 監視 shall 既存の通知経路へ通知する。
13. The 宅外への複製の容量 shall `backup-durability-and-alerting` が定めるオフサイト複製の上限 (4 TB) の内訳として扱う。
14. The 宅外への複製 shall 複数の世代を保持し、各回の送信量を前回からの差分に限る。日々の送信量が提供元の 1 日あたりのアップロード上限に収まる。
15. The 宅外への最初の世代 shall 宅内の退避先を経由せず、移行先から直接取得する。以降の世代は宅内の退避先から複製する。
16. While 切り替えから `/dev/sdb` の初期化までの期間, the 退避 shall 宅外の複製と移行元のデータだけで保護される状態を許容する。

### Requirement 9: 切り替えと切り戻し

**Objective:** As a ホームラボ運用者, I want 切り替えの手順と切り戻しの条件を事前に決めておきたい, so that 移行の途中で判断に迷わない

#### Acceptance Criteria

1. The 移行手順 shall 切り替えの時点で移行元への書き込みが止まっている状態を作り、最終差分を移したうえで移行先へ切り替える。
2. If 切り替えの後に移行先で致命的な不具合が見つかった場合, then the 移行手順 shall 移行元へ戻す手順を備える。切り戻しは、宅内の LAN から移行元に直接接続してデータを利用・取り出しできる状態に戻すことを指し、外部への公開は戻さない。戻す手順は移行元の保守モードの解除だけで実行できる。
3. When 切り替えが完了し、退避からの復元が確認された場合 (Requirement 8.2), the 移行作業 shall VM 105 を撤去する。停止と削除はそれぞれ、設計の関門で定めた前提を確かめてから実行する。
4. The 移行手順 shall 切り戻した場合に失われる変更の範囲 (切り替え後に移行先で行われた変更) を、切り替えの前に記録に残す。アップグレードとデータベースの移行は移行先でのみ行うため、移行先から移行元へデータを戻す経路は持たない。

### Requirement 10: 同居サービスの撤去と代替

**Objective:** As a ホームラボ運用者, I want VM 105 に同居する Nextcloud 以外のサービスを、撤去の前に片付けておきたい, so that VM 105 の撤去で気づかないうちに機能を失わない

#### Acceptance Criteria

1. The 移行作業 shall VM 105 の撤去の前に、Pi-hole を DNS として参照している機器や設定が残っていないことを確認する。
2. If Pi-hole を参照している機器や設定が見つかった場合, then the 移行作業 shall その参照先を既存の DNS に切り替えてから Pi-hole を撤去する。
3. The 移行作業 shall Pi-hole を代替するサービスを新設しない。
4. The 移行作業 shall VM 105 の samba が提供していたファイル共有を NAS で代替する。VM 105 に新たな共有を残さない。
5. Where Nextcloud の外部ストレージ (SMB) を移行後も継続する, the 移行後の Nextcloud shall 接続先を NAS とする。

### Requirement 11: 記録の一致

**Objective:** As a IaC 保守担当, I want プロジェクトの記録を移行後の実態に合わせたい, so that 後続の作業が古い前提で判断を誤らない

#### Acceptance Criteria

1. When 移行が完了した場合, the IaC 保守担当 shall steering に記された Nextcloud の所在、移行先の予約、PBS の退避除外の記述を実態に合わせて更新する。
2. When 移行先の専用ディスクにデータが置かれた場合, the IaC 保守担当 shall 空であることを理由とした退避除外の宣言を見直す。
3. The IaC 保守担当 shall 宣言と実機の乖離を検出する仕組みに、移行後の Nextcloud を反映する。

### Requirement 12: アップグレードとデータベースの移行

**Objective:** As a ホームラボ運用者, I want 移行にあわせて Nextcloud を保守期間内のバージョンへ上げ、データベースを PostgreSQL に移したい, so that 保守の切れたソフトウェアと、クラスタ内で唯一の MariaDB を抱え続けずに済む

#### Acceptance Criteria

1. The 移行後の Nextcloud shall 移行の完了時点で保守期間内にあるメジャーバージョンで稼働する。
2. The 移行作業 shall Nextcloud が定めるアップグレードの経路に従い、メジャーバージョンを飛ばさずに順に上げる。
3. The 移行作業 shall アップグレードとデータベースの移行を移行先で行う。移行元のバージョンとデータベースには手を加えない。
4. The 移行後の Nextcloud のデータベース shall PostgreSQL とし、クラスタで稼働中の CloudNativePG のオペレーターで、Nextcloud 専用の Cluster として提供する。共有の `postgres-cluster` には載せない。データベースの退避は Requirement 8 の経路だけで行い、別の継続的な退避は設けない。
5. The 移行作業 shall データベースの移行の前後で、主要なテーブル (ファイルキャッシュ、共有、カレンダー、連絡先、アカウント、各アプリの利用者データ) の行数を突き合わせ、結果を記録する。
6. If アップグレードまたはデータベースの移行の途中で失敗した場合, then the 移行作業 shall 移行元から取り出した状態に戻してやり直せる。移行元への再度の書き込みを要しない。
7. If 移行元で有効なアプリが、到達するバージョンに対応していない、または継続の分類に無い場合, then the 移行作業 shall そのアプリを無効にし、Requirement 2.8 の記録に含める。
8. The PostgreSQL のデータベース shall Requirement 8 の退避の対象に含まれる。
9. The 移行作業 shall アップグレードとデータベースの移行の各段階で、Nextcloud の版とデータベース・PHP の版の組み合わせを、その版の公式の対応範囲に収める。
10. The 移行作業 shall 変換のために一時的に用意した MariaDB を変換の完了後に撤去し、宣言にも残さない。
