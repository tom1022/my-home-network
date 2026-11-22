# Research & Design Decisions

## Summary
- **Feature**: `nas-smb-kanidm-auth`
- **Discovery Scope**: Extension(既存の `nas` role と `terraform-kanidm/` への追加。外部連携は Kanidm の HTTP API)
- **Key Findings**:
  - Kanidm 1.11.1 は NT ハッシュも Kerberos も持たない。SMB2 以降で使える資格情報の供給源は、平文で保存される RADIUS 秘密だけである。
  - `idm_radius_servers` は全 person の `RadiusSecret` / `MemberOf` / `Name` を読めるが、グループの `Member` は読めない。メンバーの列挙は `memberof` 検索で行う。
  - 「権限不足」「名前の解決失敗」が、エラーではなく空の結果として返る経路がある。空の結果をそのまま反映すると、同期の対象の全員を削除してしまう。

## Research Log

### Kanidm 1.11.1 の HTTP API と権限
- **Context**: 同期ジョブが使う API と、必要最小の権限を確定する。
- **Sources Consulted**: kanidm タグ v1.11.1 のソース。`server/core/src/https/v1.rs`、`server/core/src/https/v1_read.rs`、`server/lib/src/idm/radius.rs`、`server/lib/src/migration_data/dl15/access.rs`、`server/core/src/https/errors.rs`、`proto/src/internal/token.rs`。
- **Findings**:
  - `GET /v1/person/{id}/_radius` は `Option<String>` を返す。秘密が未発行なら `null`(200)。
  - `GET /v1/person/{id}/_radius/_token` は、秘密が未発行のとき `MissingAttribute` を返し、HTTP 500 になる。この 500 は他の内部エラーと区別しにくい。
  - `idm_acp_radius_servers`(受け手は `idm_radius_servers`)が読める属性は Class / Name / Uuid / DisplayName / MemberOf / Spn / RadiusSecret で、`Member` は含まない。
  - `POST /v1/raw/search` のフィルタ中の名前は UUID に解決される。存在しない名前は `UUID_DOES_NOT_EXIST` に置き換わり、エラーにならずに 0 件を返す。
  - フィルタに使う属性(class / memberof / uuid)は、radius の ACP で読める。
  - 401(トークンの失効・期限切れ)と 403 は区別して返る。v1 にはページングもレート制限も無い。
  - RADIUS の ACP は `AccountExpire` / `AccountValidFrom` を読めない。そのため、期限切れのアカウントの秘密も読めると解される(コードの読解による。実行での確認はしていない)。
  - 秘密は `abcdefghjkpqrstuvwxyz0123456789` から作る 5 文字の組を 4 つ `-` でつないだ 23 文字。
  - 利用者本人は、組み込みの `idm_acp_self_write` / `idm_acp_self_read` の権限で `kanidm person radius generate-secret` / `show-secret` を実行できる。generate-secret の前に再認証が要る。
  - サービスアカウントの API トークンは CLI で発行する。既定は読み取り専用で、有効期限の指定は任意。
- **Implications**: 秘密の取得には `_token` ではなく `_radius` を使う。`_radius` は未発行のときに 200 で `null` を返すが、ACP によって `RadiusSecret` が見えない場合にも `null` を返す(`server/core/src/actors/v1_read.rs:604-650`)。そこで、先に `/v1/self` で自分が `idm_radius_servers` に所属していることを確かめる。`GET /v1/group/{id}` は、グループが存在しなければ 200 で `null` を返す(`v1.rs:2270-2288`)。`/v1/raw/search` の応答は `{"entries": [...]}` である(`proto/src/internal/raw.rs:59-62`)。POSIX でない person は NSS で引けないため(`idm/account.rs:875-885`)、検索の条件に `class=posixaccount` を加える。

### Terraform provider seanlatimer/kanidm 0.1.10
- **Context**: サービスアカウントとトークンを IaC で宣言できる範囲を確かめる。
- **Sources Consulted**: registry の provider 0.1.10 の docs、`internal/client/service_account.go`@v0.1.10、`terraform-kanidm/mail.tf`。
- **Findings**:
  - `kanidm_service_account` の `generate_api_token`(既定 true)が発行するトークンは `read_write: true` で、有効期限が無い。値は state に残る。
  - API トークンを単独で扱うリソースは無い。
  - 組み込みグループへの部分的な追加は `kanidm_group_members` で行う(mail.tf の `idm_mail_servers` が前例)。
- **Implications**: 要件 4.1(必要最小の権限)を満たすため、`generate_api_token = false` にして、読み取り専用のトークンを CLI で発行する。トークンの発行と Infisical への登録は Terraform の外の手作業になる。mail-platform の前例も、トークンを Infisical に入れる工程は手作業である。

### Samba 4.17.12
- **Context**: tdbsam を非対話で操作する方法、変化の判定、複数ユーザーでの書き込み。
- **Sources Consulted**: samba-4.17.12 の docs-xml(smbpasswd.8、pdbedit.8、smbdotconf)、`source3/passdb/pdb_interface.c`、`source3/lib/username.c`。
- **Findings**:
  - `smbpasswd -a -s <user>` は標準入力からパスワードを 2 回読む。登録済みのユーザーに対してはパスワードを更新する。削除は `pdbedit -x -u <user>`。
  - tdbsam に登録するユーザーは `getpwnam` で解決できればよい。NSS(kanidm)で引ければ、`/etc/passwd` に無くてよい。
  - `pdbedit -L -w` は smbpasswd 形式で出力し、4 番目のフィールドが NT ハッシュ(`MD4(UTF-16LE(password))` の大文字 16 進)。
  - 既定値: `server min protocol = SMB2_02`、`ntlm auth = ntlmv2-only`、`lanman auth = no`、`map to guest = Never`。
- **Implications**: 秘密から計算した NT ハッシュと、`pdbedit -L -w` の値を比べる。一致すれば書き込まない(2.7)。

### NAS の実機(Debian 12)
- **Context**: 同期ジョブの実行環境を確かめる。
- **Sources Consulted**: `ssh tochi@192.168.1.201` での読み取り(2026-11-22)。
- **Findings**:
  - python3 3.11.2 で、`hashlib.new("md4")` は `ValueError: unsupported hash type md4` になる。
  - `openssl dgst -md4 -provider legacy` は動く。`ossl-modules/legacy.so` がある。
  - curl はあるが、jq は無い。systemd は 252。
  - 共有ディレクトリ `/srv/nas-data/smb` は `nextcloud:nextcloud`(uid 994 / gid 992)の 0750。NFS は `all_squash,anonuid=994,anongid=992`。
  - kanidm-unixd 1.11.1 で、`uid_attr_map` / `gid_attr_map` は `name`。nsswitch は `passwd: kanidm files`。
  - `kanidm.fickledev.com` の証明書は公開 CA の発行で、OS の trust store で検証できる。
- **Implications**: 同期ジョブは Python の標準ライブラリで書き、NT ハッシュは openssl の legacy provider で計算する。秘密は標準入力で渡す。

### 既存の作り(リポジトリ)
- **Context**: 定期実行・秘密の配置・失敗の通知の前例に揃える。
- **Sources Consulted**:
  - `ansible/roles/systemd_failure_notify`
  - `ansible/roles/host_health/templates/host-health-check.{service,timer}.j2`
  - `ansible/roles/cloudflared_tunnel/tasks`
  - `ansible/playbooks/mail_backup.yml`
  - `scripts/test_*.py`
  - `pyproject.toml`
  - `.github/workflows/ci.yml`
- **Findings**:
  - 定期実行は oneshot の service と timer(`OnCalendar`、`RandomizedDelaySec`、`Persistent=true`)で作る。失敗の通知は `OnFailure=notify-failure@%n.service` で Discord に送る。
  - playbook は、ハンドラのユニットを置く `systemd_failure_notify` を、それを使う role より先に当てる(mail_backup.yml)。
  - ホストに常駐させる秘密は、Infisical の env を `lookup('env')` で読み、root:root 0600 の env ファイルとして `no_log` 付きで置く。unit は `EnvironmentFile=` で読む。`LoadCredential` の前例は無い。
  - テストは `scripts/test_*.py` で、importlib で対象を読み込み、純関数を assert する。CI の pytest がこれを実行する。
- **Implications**: 同じ形に揃える。Python の同期スクリプトをホストに置くのは初めてだが、jq が無く、NT ハッシュの比較と JSON の処理が要るため、bash より Python が適する。

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 定期の pull 同期(採用) | NAS 上の timer が Kanidm の API から読み、tdbsam へ反映する | 部品が NAS の中で完結する。Kanidm 側に変更が要らない | 反映が同期の周期だけ遅れる | 既存の timer と OnFailure の作りに乗る |
| Kanidm からの push | Kanidm の変更をきっかけに NAS へ送る | 即時に反映される | Kanidm 1.11.1 に変更を外へ知らせる仕組みが無い | 成立しない |
| SMB パスワードの手動管理 | `valid users = @nas_access` にして手で `smbpasswd` する | 部品が要らない | 資格情報の発行と失効が Kanidm に集まらない | ユーザーが案 A(同期)を選んだ |

## Design Decisions

### Decision: 秘密の取得に `_radius` を使う
- **Context**: 2.5(未発行のメンバーは飛ばす)と 5.3(障害は失敗として記録する)を区別する必要がある。
- **Alternatives Considered**:
  1. `_radius/_token`: 未発行が 500 になり、内部エラーと区別しにくい
  2. `_radius`: 未発行は 200 で `null` になる
- **Selected Approach**: `GET /v1/person/{uuid}/_radius`
- **Rationale**: 自分の所属を確かめたうえでなら、`null` を「未発行」と解釈できる。サーバーの障害は 5xx として区別できる。
- **Trade-offs**: グループの所属は `_token` から取れないので、別の検索で取る。
- **Follow-up**: 実装後に、未発行の利用者について 200 / `null` が返ることを実機で確認する。

### Decision: 同期の対象を状態ファイルで追跡する
- **Context**: 2.6(`nextcloud` に触れない)と 2.3 / 2.4(削除)を両立させる。
- **Alternatives Considered**:
  1. tdbsam のユーザーのうち、uid が Kanidm の範囲にあるものを対象にする: Kanidm から消えた利用者は getpwnam で解決できず、uid を引けない
  2. 同期が登録した名前を状態ファイルに記録し、その中だけを削除の候補にする
- **Selected Approach**: 2。状態ファイルには利用者名だけを書き、秘密もハッシュも書かない。
- **Rationale**: 削除の対象を「同期が自分で登録したもの」に限れる。
- **Trade-offs**: 状態ファイルは tdbsam への書き込みより先に記録し、削除は成功の後に反映する。状態ファイルが欠けた場合は、ハッシュの一致する登録を ADOPT で取り込み直して復元する。

### Decision: 共有内の操作を `nextcloud` の権限で行う(`force user` / `force group`)
- **Context**: 3.2 / 3.3。NFS は `all_squash` で、Nextcloud の書き込みを uid 994 / gid 992 に潰している。共有ディレクトリは 0750 である。
- **Alternatives Considered**:
  1. `force user = nextcloud` / `force group = nextcloud`
  2. setgid ディレクトリ + `force group` + `create mask 0664`: Nextcloud が作るファイルは、PHP の umask によって 0644 になる。そのため SMB の利用者は書き換えられない
- **Selected Approach**: 1
- **Rationale**: SMB と NFS で所有者が一致し、権限の食い違いが構造上起きない。認証は利用者ごとのままである。
- **Trade-offs**: ファイルの所有者からは、誰が書いたかが分からない。

### Decision: サービスアカウントのトークンを CLI で発行する
- **Context**: 4.1。provider が発行するトークンは読み書き可能で、無期限である。
- **Selected Approach**: `generate_api_token = false` にして、`kanidm service-account api-token generate` で読み取り専用のトークンを発行する。値は Infisical の `NAS_SMB_SYNC_KANIDM_TOKEN` に手で登録する。
- **Trade-offs**: Terraform の外の手作業が 1 回生じる。

## Risks & Mitigations
- `idm_radius_servers` のトークンは、`nas_access` 以外の利用者の RADIUS 秘密も読める。このラボでは RADIUS 秘密を SMB 以外に使わないため、漏洩しても影響は NAS の SMB に限られる。トークンは読み取り専用で、root だけが読める。
- 空の結果による全員の削除。グループが UUID で解決できない場合は、変更をせずに中止する。0 件の結果は、グループの存在を確かめたうえでの正常な状態として扱う。
- Kanidm のアカウントの期限切れは、RADIUS の ACP からは判定できない。失効はグループからの除外か、秘密の削除で行う。
- kanidm-unixd がオフラインでキャッシュも無い場合、getpwnam が失敗して SMB にログインできない。これは既存の SSH ログインと同じ依存である。

## References
- https://github.com/kanidm/kanidm/blob/v1.11.1/book/src/integrations/radius.md — RADIUS 秘密の平文保存と、`idm_radius_servers`
- https://github.com/kanidm/kanidm/blob/v1.11.1/book/src/supported_features.md — パスワードの保存方式(Argon2ID / TPM HMAC)。Kerberos は記載が無い
- https://www.samba.org/samba/history/samba-4.11.0.html — `encrypt passwords` の廃止、SMB1 の既定での無効化
- https://www.freedesktop.org/software/systemd/man/252/systemd.unit.html — `OnFailure=`
