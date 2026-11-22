# Requirements Document

## Project Description (Input)
NAS (192.168.1.201) の SMB 共有に Kanidm のアカウントで接続できるようにする。Kanidm 1.11.1 は NT ハッシュも Kerberos も持たないため、POSIX が有効で RADIUS 秘密を持つ Kanidm の person ごとに RADIUS 秘密を Kanidm の API (idm_radius_servers グループのサービスアカウントで GET /v1/person/{id}/_radius/_token) から取得し、NAS の Samba (4.17.12, tdbsam) に定期同期する。tdbsam に登録された利用者は全員 SMB に接続でき、ユーザー解決は既存の kanidm NSS を使う。RADIUS 秘密を失った、POSIX が無効になった、または削除された利用者は tdbsam から削除する。Nextcloud が使う既存のローカルユーザー nextcloud による接続は維持する。

## Introduction
NAS の SMB 共有 `smb`(`/srv/nas-data/smb`)に、POSIX が有効で RADIUS 秘密を持つ Kanidm の person が自分の Kanidm アカウント名で接続できるようにする。SMB2 以降の認証には NT ハッシュか Kerberos が要るが、Kanidm 1.11.1 はどちらも提供しない。そのため SMB のパスワードには、Kanidm が利用者ごとに発行する RADIUS 秘密を使う。NAS の Samba は RADIUS 秘密を定期的に Kanidm から取り込む。利用者の追加・削除と秘密の発行・更新は Kanidm だけで行う。

## Boundary Context
- **In scope**:
  - POSIX が有効で RADIUS 秘密を持つ Kanidm の person の RADIUS 秘密を Samba の資格情報へ同期すること(登録・更新・削除)。グループの所属は見ない
  - SMB 共有 `smb` の接続許可を、Samba の資格情報に登録された利用者全員にすること
  - 同期に使う Kanidm のサービスアカウントと、その `idm_radius_servers` への所属の宣言
  - 同期の失敗の検知
- **Out of scope**:
  - Kanidm のログインパスワードで SMB に認証すること(Kanidm 1.11.1 では成立しない)
  - SMB1 と平文パスワード認証
  - 利用者の POSIX の有効化と、RADIUS 秘密の発行(Kanidm 上の運用。秘密は本人が Kanidm の Web UI の RADIUS 画面 `https://kanidm.fickledev.com/ui/radius` で発行する。Terraform は人間の利用者を宣言しない)
  - `smb` 以外の共有の追加
- **Adjacent expectations**:
  - Nextcloud(k3s)は同じディレクトリを NFS でマウントしており、その経路と既存のローカルユーザー `nextcloud` による SMB 接続は変わらず動く
  - NAS のユーザー・グループ解決は既存の `kanidm_unixd`(PAM/NSS)が担う
  - 既存の SSH ログイン(`nas_access` の POSIX ログイン)は変わらず動く

## Requirements

### Requirement 1: Kanidm アカウントでの SMB 接続
**Objective:** As a POSIX が有効で RADIUS 秘密を持つ Kanidm の利用者, I want 自分の Kanidm アカウント名と RADIUS 秘密で SMB 共有 `smb` に接続できること, so that NAS 専用のアカウントを別に持たずに済む

#### Acceptance Criteria
1. While 利用者が POSIX が有効な Kanidm の person で RADIUS 秘密を持っている, when その利用者が Kanidm のアカウント名と RADIUS 秘密で `\\192.168.1.201\smb` に接続する, the NAS SMB サービス shall 接続を許可し、共有内の読み書きを許可する
2. If 利用者が誤った秘密で接続する, then the NAS SMB サービス shall 接続を拒否する
3. If RADIUS 秘密を持たない、または POSIX でない Kanidm 利用者が接続する, then the NAS SMB サービス shall 接続を拒否する
4. The NAS SMB サービス shall SMB2 以降の認証方式だけを受け付け、平文パスワード認証を受け付けない
5. The NAS SMB サービス shall ゲスト接続を拒否する

### Requirement 2: 資格情報の同期
**Objective:** As a 管理者, I want Kanidm 上の person の POSIX の有効・無効と RADIUS 秘密が NAS の SMB 資格情報へ自動で反映されること, so that NAS 上で利用者ごとの手作業が要らない

#### Acceptance Criteria
1. When person が POSIX 有効かつ RADIUS 秘密を持つ状態になる, the 資格情報同期 shall 同期の周期内にその利用者を SMB の資格情報に登録する
2. When 利用者が Kanidm で RADIUS 秘密を再発行する, the 資格情報同期 shall 同期の周期内に SMB の資格情報を新しい秘密へ更新し、古い秘密での接続を拒否させる
3. When person の POSIX が無効になる、または person が削除される, the 資格情報同期 shall 同期の周期内にその利用者の SMB の資格情報を削除する
4. When 利用者の RADIUS 秘密が Kanidm から削除される, the 資格情報同期 shall 同期の周期内にその利用者の SMB の資格情報を削除する
5. If POSIX が有効な person が RADIUS 秘密を持っていない, then the 資格情報同期 shall その利用者を SMB の資格情報に登録せず、他の利用者の同期を続ける
6. The 資格情報同期 shall 同期の対象ではない SMB の資格情報(ローカルユーザー `nextcloud`)を登録・変更・削除しない
7. When POSIX の状態と秘密に変化が無い, the 資格情報同期 shall SMB の資格情報を変更しない

### Requirement 3: 既存の利用者との共存
**Objective:** As a 管理者, I want Kanidm の利用者を追加しても Nextcloud の外部ストレージと既存のアクセスが壊れないこと, so that 既存のサービスを止めずに導入できる

#### Acceptance Criteria
1. The NAS SMB サービス shall ローカルユーザー `nextcloud` による既存の SMB 接続を引き続き許可する
2. When Kanidm の利用者が SMB でファイルやディレクトリを作成する, the NAS SMB サービス shall Nextcloud(NFS 経由)がそれを読み書きできる所有者と権限で作成する
3. When Nextcloud が NFS 経由でファイルやディレクトリを作成する, the NAS SMB サービス shall Kanidm の利用者が SMB でそれを読み書きできるようにする
4. The NAS shall 既存の `nas_access` の SSH ログインと、Gitea・Nextcloud 向けの NFS エクスポートを変えない

### Requirement 4: 秘密の取り扱い
**Objective:** As a 管理者, I want 同期に使う認証情報と利用者の秘密が漏れないこと, so that NAS や公開リポジトリから資格情報が露出しない

#### Acceptance Criteria
1. The 資格情報同期 shall Kanidm への認証に、RADIUS 秘密の読み取りに必要な権限(`idm_radius_servers` への所属)だけを持つ専用のサービスアカウントを使う
2. The 資格情報同期 shall サービスアカウントの API トークンを Infisical から供給し、リポジトリに平文で置かない
3. The 資格情報同期 shall RADIUS 秘密を、ログ・プロセスの引数・NAS 上のファイルに出力せず、サービスアカウントのトークンを、ログ・プロセスの引数に出力せず NAS 上では root だけが読める 0600 のファイルにだけ置く
4. The 資格情報同期 shall Kanidm との通信を TLS で行い、サーバー証明書を検証する

### Requirement 5: 失敗の検知
**Objective:** As a 管理者, I want 同期が失敗したことに気付けること, so that 秘密の更新や削除が反映されないまま放置されない

#### Acceptance Criteria
1. If Kanidm に到達できない、認証に失敗する、または kanidm-unixd が Kanidm に接続できていない, then the 資格情報同期 shall 既存の SMB の資格情報を削除・変更せずに同期を中止し、失敗として記録する
2. If 同期が失敗する, then the 資格情報同期 shall 既存の通知の仕組みを通じて管理者に知らせる
3. If 一部の利用者の登録・更新・削除に失敗する, then the 資格情報同期 shall 残りの利用者の同期を続け、失敗した利用者を失敗として記録する

### Requirement 6: 宣言的な管理
**Objective:** As a 管理者, I want この構成すべてを IaC で再現できること, so that NAS を作り直しても同じ状態に戻せる

#### Acceptance Criteria
1. The 構成 shall サービスアカウントとその `idm_radius_servers` への所属を `terraform-kanidm/` で宣言する
2. The 構成 shall Samba の設定と同期の仕組み(実行の定期化を含む)を `ansible/roles/nas` の適用で構成する
3. When Ansible の適用を繰り返す, the 構成 shall 2 回目以降に変更を生じさせない
