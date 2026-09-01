# Research Log: mail-platform

## Summary

- **Discovery Scope**: 新規構築 (メール基盤)。外部依存の一次情報確認を中心とした full discovery。
- **調査の主眼**: メールボックスの配置方式、DMS の対象バージョン、蓄積されるメールの保全方針、および設定上書き経路。いずれも requirements で「決定する」とされたまま設計に委ねられた論点である。
- **結論**: メールボックスと IMAP の終端を k3s 側に置き、VPS は MTA と submission の認証のみを担う。DMS は Dovecot 2.4 系を同梱する系列を対象とする。蓄積されるメールは復旧対象とする。
- **実証の状態**: 認証機構の成立を最小構成で確認済み。bind、設定上書き、取得の 3 項目がいずれも成立する。確認は Dovecot 2.4 系を同梱する版で行った。

## Research Log

### 1. Dovecot のネットワークファイルシステム上での動作

**調査の動機**: メールボックスの実体を k3s 側に置いたうえで VPS の Dovecot が読み書きする構成 (案 A) が成立するかを判定するため。

**確認できたこと**:

- Dovecot CE は単一サーバからのアクセスのみを支援する。「a user can only be accessed by a single Dovecot server at a time」と明記され、複数サーバからの同時アクセスは「more or less severe mailbox corruption」を招くとされる。本構成は書き込み側が単一であるため、この致命的な条件には該当しない。
- NFS 上で動作させる場合、`mmap_disable = yes` と `mail_fsync = always` を要する。索引ファイルの mmap は NFS で機能しないと明記されている。
- 単一サーバ構成では `mail_nfs_index` と `mail_nfs_storage` を有効にしてはならない。これらは director を用いない多サーバ構成における部分的な緩和策であり、上流はその構成自体を「almost guaranteed to give random errors and can potentially lose emails」と評価している。
- ロックは既定の fcntl が NFS で問題を起こしうるため、flock または dotlock への切り替えを要する場合がある。dotlock は最も遅い。
- ロックファイル等の一時ファイルを tmpfs に置く `VOLATILEDIR` の指定が推奨される。
- **未マウント時の危険**: マウント先のディレクトリが Dovecot プロセスから書き込み可能なまま NFS が外れると、空のメールディレクトリが生成され「breaks things」と警告されている。

**設計への含意**: 案 A は技術的には成立する。ただし成立させるために必要な設定と、マウント喪失時の破壊的な失敗モードへの対処が、いずれも構成の外側に積み上がる。ファイルシステムのストールはシステムコールを停止させるため、失敗が時間的に伝播する。

**出典**:
- [NFS — Dovecot documentation (2.3)](https://doc.dovecot.org/2.3/configuration_manual/nfs/)
- [Formats Overview | Dovecot CE (2.4)](https://doc.dovecot.org/2.4.0/core/config/mailbox/formats.html)

### 2. オブジェクトストレージへの格納可否

**調査の動機**: メールボックスをクラスタ内の S3 互換ストレージに置く案 (案 C) の実現性を判定するため。

**確認できたこと**:

- Dovecot のオブジェクトストレージ格納機構 (obox) は Dovecot Pro の機能であり、Community Edition には含まれない。
- obox は AWS S3 を直接支援対象とし、S3 互換の実装については支援水準が下がる。互換性の担保は利用者の責任とされる。

**設計への含意**: 案 C は Community Edition では成立しない。商用版の導入は本 spec の前提と釣り合わないため却下する。

**出典**:
- [S3-compatible Storages — Dovecot documentation](https://doc.dovecot.org/2.3/configuration_manual/mail_location/obox/s3/)
- [Obox Storage Support: S3 Compatible — Dovecot Pro](https://doc.dovecotpro.com/main/storage/providers/s3.html)

### 3. docker-mailserver の設定上書き経路

**調査の動機**: Postfix の配送先を LMTP に変更できるか、および Dovecot の bind DN テンプレートを注入できるかを判定するため。

**確認できたこと**:

- Postfix の設定は `docker-data/dms/config/postfix-main.cf` に置いた内容が既定の `main.cf` へ追記され、起動時に `postconf -nf` で重複が除去される。任意のパラメータを指定でき、`virtual_transport` もこの経路で設定できる。
- `postfix-master.cf` は行ごとに `postconf -P` へ渡される。形式は `<service>/<type>/<parameter>` であり、値との間に空白を置けない。
- Dovecot 側の上書き経路 (`dovecot.cf` が `/etc/dovecot/local.conf` として反映されるか) は上流ドキュメントから確定できなかった。実証の対象とする。

**出典**:
- [Override the Default Configs | Postfix](https://docker-mailserver.github.io/docker-mailserver/latest/config/advanced/override-defaults/postfix/)

### 4. docker-mailserver の版

**確認できたこと**:

| 版 | 公開日 | 同梱 Dovecot |
|---|---|---|
| v16.0.0 | 2026-08-30 | 2.4 系 |
| v15.1.0 | 2025-08-12 | 2.3 系 |
| v15.0.2 | 2025-03-26 | 2.3 系 |

- v16.0.0 は Dovecot 2.3 から 2.4 への移行を伴う。設定名が変わり (`auth_bind` → `passdb_ldap_bind`、`auth_bind_userdn` → `passdb_ldap_bind_userdn`)、上流の設定ファイルには移行完了後にさらに破壊的な変更を入れる旨の記述が残っている。
- v15.1.0 は公開から 1 年以上が経過しており、設定名に関する既存の記述と事例が最も多い。

**出典**:
- [docker-mailserver releases](https://github.com/docker-mailserver/docker-mailserver/releases)

### 6. 認証機構の実証

**確認の範囲**: 認証基盤とメールサーバを最小構成で起動し、認証の成立と設定上書き経路を確認した。VPS および k3s の実環境は用いていない。用いた版は Dovecot 2.4 系を同梱する系列。

**成立した事項**:

1. アプリケーション指定を含む bind DN によるアプリケーションパスワードでの bind が成立する。
2. アプリケーション指定を外すと同一のパスワードでは bind できない。POSIX パスワードの経路に落ちる。
3. 主クレデンシャルではアプリケーション指定を含む bind ができない。
4. リンクされたグループから利用者を外すと即座に bind できなくなり、再追加で復帰する。失効の手段としてはこれが最も速い。
5. 資格情報の再設定に用いる引換券の発行はメール送信を要さない。既定の有効期限は 1 時間。
6. 設定ファイルの追加による上書き経路は有効であり、実行中の設定値として反映される。
7. アプリケーションパスワードによる取得のログインが成立する。

**当初の想定と異なっていた事項**:

| 項目 | 当初の想定 | 実際 |
|---|---|---|
| メール属性の検索 | 単独のフィルタで検索できる | **インデックスされていない**。単独のフィルタは資源制限により拒否される。インデックス済み属性との論理積が必要 |
| 属性の読み取り許可がない場合 | エラーが返る | **エラーではなく 0 件が返る**。呼び出し側からは宛先が存在しないのと区別できない |
| ホームディレクトリの属性 | 返らない | 返る。ただし値は識別子に基づくものであり、利用者名に基づかない |
| 所有者の識別子と既定シェル | 返らない | 返らない。POSIX の有効化後も同様 |
| 管理者による代理発行 | 記述なし | **成立しない**。利用者自身の認証済みセッションを要する |
| 発行操作の自動化 | 記述なし | **成立しない**。対話的な端末を要する |
| 既定のアカウントポリシー | 記述なし | 多要素を要求する。パスワードのみの資格情報を許すにはポリシーの緩和が必要 |
| 環境変数による認証設定 | 有効 | **反映されない**。設定ファイルの追加と、既定の項目定義の差し替えの双方が必要 |
| 自己署名証明書 | 利用できる | 認証局とサーバ証明書を分ける必要がある。認証局の証明書をそのまま提示すると拒否される |

**設計への含意**:

- 検索を組み立てる際、メール属性は必ずインデックス済み属性との論理積とする。受入基準に反映する。
- 属性の読み取り許可の欠落は無言で失敗する。構築時の検証手順に、許可の有無を直接確認する項目を置く。
- 所有者の識別子とメールボックスの位置を静的な値とする方針は変わらない。ホームディレクトリの属性が返ることは、その値が利用者名に基づかないため利用しない。
- アプリケーションパスワードの発行は自動化できない。構成のコード化の対象外として明示し、利用者の作業として記述する。
- 認証の設定は環境変数では与えられない。設定ファイルの追加と項目定義の差し替えの双方を構成に含める。版の更新時に追随を要する箇所として記録する。
- 証明書の連鎖に制約がある。本番は認証局が発行するため通常は問題にならないが、認証局の証明書を末端の証明書として用いる構成は成立しない。

### 5. 家庭回線の送信制約

**確認できたこと**: 家庭回線は一般的な個人用回線であり、外向き 25 番ポートが遮断されている (OP25B)。

**影響範囲**:

| 経路 | ポート | 発信元 | OP25B の影響 |
|---|---|---|---|
| 外部からの MX 受信 | 25 | VPS が受信する | なし |
| 外部 MTA への送信 | 25 | VPS から発信する | なし |
| VPS から k3s への配送 | LMTP | tailnet 内 | なし |
| submission / IMAP | 587 / 465 / 993 | VPS が終端する | なし |

家庭回線を通過するのは tailnet のトラフィックのみであり、k3s 側は外部 MTA へ直接送信しない。したがって採用する構成は OP25B に抵触しない。

**設計への含意**: k3s 側に独自の外向き SMTP を発生させる構成 (メールボックス側に MTA を置いて直接送出する形) は採らない。また家庭回線に受信用のポートを開けない。公開されるアドレスを VPS のものに限ることで、動的アドレスとポート開放の問題を同時に回避する。

### 8. VPS のポート到達性

**測定日**: 2026-09-01。VPS 上および OP25B の影響を受けない外部経路からの TCP 接続によって確認した。定義や管理画面の表示ではなく実接続による。

**外向き 25 番 — 開いている**:

VPS から外部の MX (`gmail-smtp-in.l.google.com`、`mx01.mail.com`) の 25 番へ TCP 接続が確立する。提供元のドキュメントによれば、外向き 25 番の制限は 2026-05-12 以降に作成された新規アカウントを対象とする。当該契約はそれより前に作成されており対象外であり、実測と一致する。

したがって外向き 25 番の遮断を理由とする撤退の分岐は成立しない。ただし提供元の方針変更で前提が変わりうるため、事実として記録する。

**内向きの到達性 — 25 番は解除済み**:

2026-09-01 に OP25B の影響を受けない経路から測定した時点では、応答の種類が 3 つに分かれていた。

| ポート | 外部からの応答 | 意味 |
|---|---|---|
| 143 / 443 / 465 / 587 / 993 | TCP 確立 | 開放 |
| 110 / 995 | RST | 経路は開通、listener 不在 |
| **22 / 25** | **ドロップ** | **フィルタあり** |

このとき 25 番のドロップは提供元側のフィルタによるものと特定した。根拠は 2 つ。VPS の ufw は `is-active` が `inactive` で動作しておらずホスト側にパケットを落とす主体が存在しないこと、および 110 / 995 が RST を返しており上流が汎用的にはパケットを通していること (汎用的に落としているならこれらもドロップになる) である。

**2026-09-02、利用者が提供元のコントロールパネルで解除を行い、25 番の疎通を確認した。** 現在は到達する。

**測定経路の制約**: 家庭回線から VPS への 25 番の測定は無効である。家庭回線は OP25B により外向き 25 番が塞がれているため、失敗は経路の家庭側で落ちた結果であり、VPS 側および提供元側のフィルタの状態を示さない。上記の測定はいずれもこの制約を満たす経路から行っている。

**設計への含意**:

- 内向き 25 番は解除済みであり、構成全体の前提は満たされている。ただし段階 0 の関門としては残す。解除状態が維持されていることを着手時点で確認するためであり、失われていれば同じ操作で再解除する。
- 解除は提供元のコントロールパネルでの操作であり、コードによる管理の対象外。逆引きの設定と同じ扱いとし、人の作業として明示する。確認は OP25B の影響を受けない経路からの実接続で行う。
- 465 / 587 / 993 は到達が確認済みであり、submission と IMAPS の公開経路について提供元側の操作を要しない。
- 143 は到達するが、本 spec は平文の取得を用いないため待受を持たない。
- 22 のドロップは本 spec の対象外。VPS への接続は tailnet を経由する。

### 9. VPS 上の既存の中継定義

**確認できたこと**: VPS の `/etc/haproxy/haproxy.cfg` は mtime 2026-04-20 で凍結された状態で稼働している。メール 6 ポート (25 / 587 / 465 / 143 / 993 / 4190) の frontend と backend が値の埋まった状態で存在し、いずれも k3s の NodePort へ TCP 中継している。

一方、当該設定を生成するテンプレート側の変数は未定義であり、ロールを実適用すると当該ブロックは空でレンダリングされて消える。稼働中の設定とテンプレートの出力が一致していない。

**設計への含意**:

- 現在稼働している中継は mailu 時代のもので、メールの終端をすべて k3s 側に置く構成を前提としている。本 spec が採る構成は VPS で終端し、メールボックスのみを k3s に置くため、**中継の向きと対象が異なる**。4 月時点の定義をそのまま復活させてはならない。
- 本 spec の構成における対応は次のとおり。

| ポート | 用途 | 扱い |
|---|---|---|
| 25 | 外部からの受信 | VPS で終端 (Postfix) |
| 465 / 587 | submission | VPS で終端 (Postfix + Dovecot SASL) |
| 993 | 取得 | 格納側へ経路透過で中継。TLS の終端は格納側 |
| 143 | 平文の取得 | 用いない。待受も中継も持たない |
| 4190 | ManageSieve | 用いない。待受も中継も持たない。到達性も確認しない |

- ロールの実適用が既存の設定を消すことは、この構成では問題にならない。消えた後に本 spec が定義する中継のみを置く。ただし適用の順序として、消える時点で取得の経路が一時的に途切れる点を段階の停止条件に含める。

### 7. 衛星サービスの有効化条件

**確認できたこと**: 迷惑メール判定 (rspamd)、ウイルス検査 (ClamAV)、および認証の反復失敗に対する遮断 (fail2ban) は、いずれも環境変数で切り替わる。既定値と依存関係は次のとおり。

| 環境変数 | 既定値 | 備考 |
|---|---|---|
| `ENABLE_RSPAMD` | 0 | 迷惑メール判定。有効化すると DKIM 署名も担う |
| `ENABLE_CLAMAV` | 0 | ウイルス検査。rspamd から呼び出される |
| `ENABLE_FAIL2BAN` | 0 | 反復失敗の遮断。`NET_ADMIN` を要する |
| `ENABLE_OPENDKIM` | **1** | 旧来の DKIM 署名 |
| `ENABLE_OPENDMARC` | **1** | 旧来の認証結果の記録 |
| `ENABLE_POLICYD_SPF` | **1** | 旧来の送信者方針の検査 |
| `ENABLE_AMAVIS` | **1** | 旧来のメッセージ検査の中継 |
| `RSPAMD_CHECK_AUTHENTICATED` | 0 | 認証済みの送信への検査適用。0 でも DKIM 署名は行われる |

- rspamd を有効化する場合、上流は `ENABLE_OPENDKIM` / `ENABLE_OPENDMARC` / `ENABLE_POLICYD_SPF` / `ENABLE_AMAVIS` をいずれも 0 にすることを指示している。これら 4 つは**既定で有効**であり、rspamd を足すだけでは無効にならない。
- とくに `ENABLE_OPENDKIM` を 1 のまま rspamd を有効化すると、DKIM 署名が二重に付与される。二重署名は受信側の検証に失敗する。
- fail2ban はホストのパケットフィルタを操作するため、コンテナ定義に `cap_add: NET_ADMIN` を要する。付与しない場合、有効化しても遮断が機能しない。
- ClamAV は定義データベース全体を常駐メモリに読み込む。上流が挙げる現在の目安は約 850MB で、増加を続けている。ClamAV を用いない場合の最小要求は 512MB。swap を用いない場合、上流は約 3GB を要すると記述している。

**確認できなかったこと**: 定義データベースの更新処理 (freshclam) が要するディスク容量と実行間隔について、上流のドキュメントに記述がない。上記の値は v16.0.0 に固有ではなく、版ごとの差分は確認していない。

**出典**:
- [Rspamd — docker-mailserver documentation](https://docker-mailserver.github.io/docker-mailserver/latest/config/security/rspamd/)
- [Environment Variables — docker-mailserver documentation](https://docker-mailserver.github.io/docker-mailserver/latest/config/environment/)
- [FAQ — docker-mailserver documentation](https://docker-mailserver.github.io/docker-mailserver/latest/faq/)

**設計への含意**:

- 衛星サービスの有効化は、有効化する 3 変数と無効化する 4 変数の組で 1 つの決定として扱う。片方だけの適用を許さない。
- DKIM 署名の担当を rspamd に一本化する。要件 6.3 / 7.5 / 9.4 は署名機構を名指ししていないため、担当の変更による記述の矛盾は生じない。鍵の生成方法が旧来の機構と異なる点のみ、構築時に確認する。
- ClamAV の要求量は VPS の実リソースを上回りうる。着手前にメモリと swap を実測し、下回る場合は有効化しない判断とその残存リスクを記録する。rspamd と fail2ban は当該制約の対象外であり、単独で有効化できる。
- 有効化しただけでは動作を確認したことにならない。迷惑メール判定とウイルス検知には、判定を発火させる既知の検体を用いた確認を置く。遮断は意図的な反復失敗によって確認する。

## Architecture Pattern Evaluation

| 案 | 構成 | 新規に要する要素 | ロックの扱い | 配送失敗時の挙動 | 判定 |
|---|---|---|---|---|---|
| A | VPS の Dovecot が k3s 側のストレージをネットワークファイルシステムとして読み書きする | ストレージの公開、VPS 側のマウント、Dovecot の NFS 向け設定、マウント喪失時の保護 | 恒常的に広域網の遅延にさらされる。設定で緩和する | ファイルシステムのストールがシステムコールを停止させる。未マウント時の書き込み保護を別途要する | 却下 |
| B | メールボックスと IMAP の終端を k3s 側に置き、VPS は MTA と submission の認証を担う | k3s 側のメール格納コンポーネント、LMTP と IMAPS の公開、VPS 側の配送先指定と TCP 中継 | ネットワークファイルシステムを用いないため構造的に発生しない | 配送先へ到達できない場合、送信側の待ち行列に留まり再試行される。標準の挙動として保証される | **採用** |
| C | オブジェクトストレージに格納する | 商用版の導入 | — | — | 却下 (Community Edition に機能が存在しない) |

## Design Decisions

### Decision: メールボックスと IMAP の終端を k3s 側に置く (案 B)

**根拠**:

1. ロックの問題を構造的に回避する。案 A はロックの問題を設定で緩和するのに対し、案 B はネットワークファイルシステムを用いないため問題自体が発生しない。
2. 配送先へ到達できない場合の挙動が標準の機構で保証される。送信側の待ち行列に留まり再試行されるため、メールを損失させない要求が追加の作り込みなしに満たされる。案 A は未マウント時の書き込み保護を別途構成する必要があり、その失敗はメールの損失に直結する。
3. 広域網を通過するのが応用層の規約になる。案 A では広域網の障害がファイルシステムのストールとしてプロセスを停止させるのに対し、案 B では規約が定める時間制限と再試行の対象になる。
4. 認証の経路が短くなる。メールボックス側の認証は同一クラスタ内の認証基盤に対して行われ、広域網を経由しない。

**受け入れる代償**: メールを扱うコンポーネントが 2 つになる。VPS 側は送信の認証のみ、k3s 側は取得の認証とメールの格納を担う。双方が同一の認証基盤を参照するため、bind の方式は共通である。

**要件との関係**: 受入基準 5.2 は「VPS が当該ストレージへ到達し、DMS がメールボックスを読み書きできる状態にする」と述べる。案 B において VPS はメールボックスを直接読み書きせず、配送規約を介して書き込みを生じさせる。文言としては直接のファイルアクセスを読み取れるため、実装に先立って要件側の表現を調整する。

### Decision: DMS は Dovecot 2.4 系を同梱する版を対象とする

**根拠**: 認証機構の実証を当該系列で行い、成立を確認している。要件 1 が実証を本構築の前提条件と定める以上、実証していない系列を対象とすることはその趣旨に反する。設定名と変数の展開規則が系列間で異なるため、実証で成立した構成をそのまま持ち込めるのは当該系列に限られる。

公開直後の主要版更新を避ける動機は、不具合の原因を切り分ける対象を増やさないことにあった。実証により当該系列に固有の落とし穴 (環境変数による認証設定が反映されないこと、既定の項目定義の差し替えを要すること) が具体的に判明しているため、この懸念は実質的に解消している。

**受け入れる代償**: 公開から日が浅い系列を対象とする。上流の設定ファイルには移行完了後にさらに破壊的な変更を入れる旨の記述が残っており、次の主要版更新で設定の追随を要する可能性がある。版を固定し、更新を別の作業として扱う。

### Decision: 蓄積されるメールを復旧対象とする

**根拠**: `iac-hygiene-remediation` はクラスタ上の永続データを復旧対象外としているが、その根拠は「失っても再構築できる」ことにある。受信したメールは再構築できない。同一の扱いを適用しない。

**方式**: メールボックスを定期的に書庫として取り出し、メールボックスの実体を保持する物理ディスクとは異なる物理ディスク上の保存先へ複製する。この環境のディスクはいずれも単発構成で冗長性を持たないため、障害域の境界は物理ディスクであり、ホストを分けるだけでは保全にならない。世代数の上限を設ける。仮想化基盤の保護機構による計算機単位の保護を第 2 の層として位置づけるが、粒度が粗いため第 1 の層としない。

**分離が成立していることの確認 (2026-09-02 実測)**: 保護対象のゲストのルートディスクは n100 と hp-z440 の `pve/data` (いずれも `sda`) にある。一方、保全先となる hp-z440 の `zfs-pool` は `sdc` (4TB) 上にあり、ディスク単位の分離は既に成立している。

```
zfs-pool                    SIZE 3.62T   ALLOC 452M   FREE 3.62T
zfs-pool/subvol-202-disk-0  USED 24.3M                  (PBS データストア)
```

プール全体の実使用は 452MB。`USED` として見える 2.48T はすべて `refreservation` による予約であり実データではない。容量の制約はない。

メールボックスの永続ボリュームは k3s ノード (VM 152、hp-z440 の `sda` 上) に載るため、保全先を `sdc` とすることで要件を満たす。

**残る障害の範囲**: 物理ディスク単体の故障では実体と成果物のいずれかが残る。両者を収容する hp-z440 の全損では同時に失われる。この粒度が現構成の限界であり、解消にはホストをまたぐ複製を要する。

### Decision: 送信経路を VPS に限定する

**根拠**: 家庭回線の外向き 25 番ポートが遮断されている。k3s 側から外部 MTA への直接送信は成立しない。あわせて送信元の識別に用いる記録 (SPF / DKIM / DMARC / 逆引き) はすべて VPS のアドレスに対して設定する。

## Risks & Mitigations

| リスク | 影響 | 緩和 |
|---|---|---|
| 認証機構の実証が成立しない | 構築に着手できない | 実証を最初の段階に置き、実環境を用いずに完結させる。不成立の場合は認証基盤の選定を見直す判断材料として結果を提示する |
| 設定上書きの構成が版の更新で崩れる | submission の認証が成立しなくなる | 上書きは追加設定と項目定義の差し替えの併用であり、対象版に固有である。版を可変でない参照で固定し、更新を別の作業として扱う。k3s 側は上書きに依存せず直接構成するため影響を受けない |
| メール属性の検索が資源制限で拒否される | 宛先の照合が成立しない | 当該属性はインデックスされていない。検索を必ずインデックス済み属性との論理積として組み立てる |
| 検索主体の属性読み取り許可が欠ける | 宛先が存在しないのと区別できない失敗が起きる | 許可の欠落はエラーではなく 0 件として現れる。許可の有無を直接確認する検証を構築時の独立した手順として置く |
| 広域網の断絶 | 配送と取得が停止する | 配送は送信側の待ち行列に留まる。取得は復旧後に再開する。メールの損失は生じない |
| メールボックス格納先の喪失 | 蓄積したメールの喪失 | 定期的な書庫の取り出しと、クラスタ外への複製 |
| 逆引きが設定できない | 送信が迷惑メールと判定される | 提供元の管理画面での操作を利用者の作業として明示する |
| 主要版の更新が滞留する | 保守されない版の使用が長期化する | 対象版を記録し、基盤の成立確認後に更新を別の作業として扱う |

## References

- [NFS — Dovecot documentation (2.3)](https://doc.dovecot.org/2.3/configuration_manual/nfs/)
- [Formats Overview | Dovecot CE (2.4)](https://doc.dovecot.org/2.4.0/core/config/mailbox/formats.html)
- [S3-compatible Storages — Dovecot documentation](https://doc.dovecot.org/2.3/configuration_manual/mail_location/obox/s3/)
- [Obox Storage Support: S3 Compatible — Dovecot Pro](https://doc.dovecotpro.com/main/storage/providers/s3.html)
- [Override the Default Configs | Postfix — docker-mailserver](https://docker-mailserver.github.io/docker-mailserver/latest/config/advanced/override-defaults/postfix/)
- [Provisioner (LDAP) — docker-mailserver](https://docker-mailserver.github.io/docker-mailserver/latest/config/account-management/provisioner/ldap/)
- [Environment Variables — docker-mailserver](https://docker-mailserver.github.io/docker-mailserver/latest/config/environment/)
- [docker-mailserver releases](https://github.com/docker-mailserver/docker-mailserver/releases)
- [LDAP | Dovecot CE 2.4.1](https://doc.dovecot.org/2.4.1/core/config/auth/databases/ldap.html)
- [Passdb LDAP with authentication binds (2.3)](https://doc.dovecot.org/2.3/configuration_manual/authentication/ldap_bind/)
- [LDAP — Kanidm Administration](https://kanidm.github.io/kanidm/stable/integrations/ldap.html)
- [Application Passwords 設計文書 — Kanidm](https://github.com/kanidm/kanidm/blob/master/book/src/developers/designs/application_passwords.md)
- [Access Control Introduction — Kanidm](https://kanidm.github.io/kanidm/stable/access_control/intro.html)
- [Server Configuration — Kanidm](https://kanidm.github.io/kanidm/stable/server_configuration.html)
- [Postfix ldap_table(5)](https://www.postfix.org/ldap_table.5.html)
- [Postfix LMTP + virtual_transport](https://www.postfix.org/postconf.5.html#virtual_transport)
