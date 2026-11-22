# Implementation Plan

- [x] 1. 同期ジョブの本体
- [x] 1.1 計画の規則を純関数として作り、単体テストで固める
  - 望む状態(所属・秘密の有無・NT ハッシュ・NSS での解決可否)、tdbsam の現状、同期が管理している名前、ローカルユーザー名から、利用者ごとの操作(追加・更新・取り込み・削除・何もしない・保留)を決める
  - 設計の 8 つの規則を、上から順に評価する。管理している名前の外には、削除を出さない
  - 状態ファイルが空で、tdbsam にハッシュの一致する登録がある場合は取り込みになる。その後グループから外すと削除になる
  - 単体テストが CI の pytest で通る。ローカルユーザー(`nextcloud`)に削除が出ないこと、解決不能・保留・取り込みの各経路を含む
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7_

- [x] 1.2 Kanidm の応答の解釈と NT ハッシュの計算を作る
  - 自分の所属の確認、グループの取得、メンバーの検索、利用者ごとの秘密の取得について、応答を検証して解釈する
  - 次のいずれかの場合は、全体の失敗として扱う: 所属に `idm_radius_servers` が無い、グループが `null`、`entries` の形が不正、401 / 403、接続や TLS の失敗、タイムアウト(10 秒)
  - 秘密の取得の `null` は未発行と解釈する。404 / 5xx はその利用者の保留と解釈する。名前の形式に合わない利用者も保留にする
  - TLS は OS の trust store で検証する
  - NT ハッシュは、秘密を UTF-16LE にして openssl の legacy provider に標準入力で渡して計算する。結果は接頭辞を除き、大文字に正規化する
  - 単体テストが通る。既知のベクトル(`password` → `8846F7EAEE8FB117AD06BDD830B7586C`)と、全体の失敗の各条件を含む
  - _Requirements: 4.3, 4.4, 5.1, 5.3_

- [x] 1.3 収集・適用・状態ファイル・終了コードをつなぎ、実行できるジョブにする
  - Kanidm からの収集を先に終える。全体の失敗なら、tdbsam に触れずに終了コード 1 で終わる
  - メンバーごとに NSS での解決可否を調べ、tdbsam の現状(NT ハッシュ)を読んでから、計画を作る
  - 状態ファイルは先に記録する。追加・更新・取り込みの名前は書き込みの前に加え、削除の名前は成功の後に除く。書き込みは一時ファイルからの rename で行う
  - tdbsam への登録・更新は、秘密を標準入力で渡して行う。削除は利用者ごとに独立して行い、1 件の失敗で残りを止めない
  - ログに出すのは、利用者名・操作の種別・失敗の分類だけ。秘密、トークン、NT ハッシュは出さない
  - 保留、または適用の失敗が 1 件でもあれば、終了コード 1 で終わる
  - CI の ruff の対象にこのスクリプトを加え、ruff check / format が通る
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.6, 4.3, 5.1, 5.3_

- [x] 2. (P) Kanidm の同期用サービスアカウントを宣言する
  - サービスアカウント `nas_smb_sync` を、`entry_managed_by = idm_admins`、provider でのトークン発行なしで宣言する
  - 組み込みグループ `idm_radius_servers` に、このアカウントだけを部分的に追加する
  - 読み取り専用のトークンを CLI で発行し、Infisical の `NAS_SMB_SYNC_KANIDM_TOKEN` に登録する手順を README に書く
  - `terraform validate` が通る
  - _Requirements: 4.1, 6.1_
  - _Boundary: KanidmServiceAccount_

- [ ] 3. NAS の Samba と同期ジョブの配置
- [x] 3.1 (P) smb.conf で認証方式と共有の許可を宣言する
  - `[global]` に、SMB2 以降・NTLMv2 だけ・LANMAN 無効を明示する
  - 共有 `smb` の許可を、`nextcloud` と `nas_access` のメンバーにする。共有内の操作は `nextcloud` のユーザーとグループで行い、ゲストを拒否する
  - 共有ディレクトリの所有者と mode、既存の create / directory mask は変えない
  - 描画した設定が `testparm -s` の検証を通る
  - _Requirements: 1.1, 1.3, 1.4, 1.5, 3.1, 3.2, 3.3_
  - _Boundary: SmbConfig_

- [ ] 3.2 (P) 同期ジョブを NAS に配置し、15 分ごとに動かす
  - スクリプトを root だけが実行できる形で置く
  - Kanidm の URL、トークン、グループ名を、root だけが読める 0600 の env ファイルに `no_log` で置く。トークンは Infisical から env の lookup で受け取り、空なら適用を止める
  - 状態ファイルのディレクトリを root だけが使える形で作る
  - oneshot の service(失敗時に `notify-failure@%n.service`)と timer(`*:0/15`、1 分のランダム遅延、Persistent)を置き、timer を有効にする
  - nas role に既存と同じ取り込み方で組み込み、変数を defaults と `vault.yml.example` に加える
  - `playbooks/nas.yml` で、`systemd_failure_notify` を `nas` より先に当てる
  - `ansible-lint` と syntax-check が通る
  - _Requirements: 4.2, 4.3, 5.2, 6.2, 6.3_
  - _Boundary: SyncTasks_
  - _Depends: 1.3_

- [ ] 4. 実機への適用
- [ ] 4.1 Kanidm に適用し、トークンを用意する
  - `terraform-kanidm` を plan で確かめてから apply する。`idm_radius_servers` の既存のメンバーが外れないことを、plan で確かめる
  - 読み取り専用のトークンを CLI で発行し、値は標準出力に出さずに Infisical に登録する
  - トークンで `/v1/self` を読み、所属に `idm_radius_servers` が含まれることを確かめる
  - _Requirements: 4.1, 4.2, 6.1_
  - _Depends: 2_

- [ ] 4.2 NAS に適用し、冪等性を確かめる
  - `playbooks/nas.yml` を適用する。2 回目の適用で changed が 0 になる
  - timer が有効で、初回の実行が成功して終わる
  - env ファイルが root:root 0600 であること、journal に秘密が出ていないことを確かめる
  - _Requirements: 4.3, 6.2, 6.3_

- [ ] 5. 実機での検証
- [ ] 5.1 接続と同期の挙動を実測する
  - 検証用の Kanidm の利用者を作り、POSIX を有効にして `nas_access` に入れ、秘密を発行する。次の周期の後、その利用者のアカウント名と秘密で `smbclient` から接続できる。`@nas_access` のグループの判定が通ることも、ここで確かめる
  - 誤った秘密と、`nas_access` に入っていない利用者は拒否される
  - 秘密を再発行すると、古い秘密は拒否され、新しい秘密で接続できる
  - 変化の無い周期の後、tdbsam の Password last set が変わらない
  - グループから外すと、次の周期の後に tdbsam からエントリが消え、接続できなくなる
  - Kanidm のグループの所属は、並列の作業と同時に変更しない
  - 検証が終わったら、検証用の利用者を削除する
  - _Requirements: 1.1, 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 2.7_

- [ ] 5.2 既存の利用者との共存と、失敗時の挙動を実測する
  - `nextcloud` での SMB 接続と、Nextcloud の外部ストレージが従来どおり動く
  - Kanidm の利用者が SMB で作ったファイルを、Nextcloud から編集できる。逆向きもできる
  - SSH ログインと、Gitea・Nextcloud 向けの NFS エクスポートが変わっていない
  - Kanidm に届かない URL を与えて同期ジョブを直接実行し、終了コード 1 で終わり、tdbsam が変わらないことを確かめる。本番の Discord に通知を飛ばさないよう、unit 経由では失敗させない。service に `OnFailure=notify-failure@%n.service` が設定されていることは、systemd のプロパティで確かめる
  - SMB1 と、ゲストでの接続が拒否される
  - _Requirements: 1.4, 1.5, 3.1, 3.2, 3.3, 3.4, 5.1, 5.2_
