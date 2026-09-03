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

### 10. タスク1.1: 受信ポート到達性の再確認とVPS資源実測

**測定日**: 2026-09-02。タスク1.1として、構築着手前の関門を確認した。VPS上の構成変更は行っていない。

#### 25 / 465 / 587 / 993 番ポートの到達再確認

**測定経路**: check-host.net (https://check-host.net) の分散型TCP到達性チェックAPI (`check-tcp` / `check-result`) を用い、ブルガリア・イラン (2拠点)・トルコ・米国・フィンランド・香港・インドネシア・イスラエル・ドイツ・インド (2拠点)・スウェーデン・ウクライナ・ブラジル・スイス・ポーランド・ルーマニア・シンガポールの各拠点からVPSの公開IP (`163.44.119.79`。`terraform/cloudflare_dns.tf` の `mail_a` と一致) へのTCP接続を試行させた。いずれも家庭回線とは独立した海外拠点であり、OP25Bの対象外である。**家庭回線からの直接測定は行っていない。** 本タスクの要件により当該経路は無効と定められているため、意図的に用いなかった。

| ポート | 拠点 | 到達 | 結果 |
|---|---|---|---|
| 25 | bg1(ブルガリア) / ir4・ir8(イラン) / tr2(トルコ) / us1(米国) | 5/5 | 全拠点でTCP接続確立。**解除状態はタスク1.1着手時点でも維持されている** |
| 465 | fi1(フィンランド) / hk1(香港) / id1(インドネシア) / il1(イスラエル) / us5(米国) | 5/5 | 全拠点でTCP接続確立 |
| 587 | de1(ドイツ) / in1・in5(インド) / se1(スウェーデン) / ua1(ウクライナ) | 4/5 | in1のみ結果null (拠点側応答なし。対象ホスト起因のエラーではない)。残り4拠点は到達 |
| 993 | br1(ブラジル) / ch2(スイス) / pl2(ポーランド) / ro1(ルーマニア) / sg1(シンガポール) | 4/5 | ro1のみ `Connection timed out`。残り4拠点は到達 |

再現用のリクエスト例と `permanent_link` (結果は check-host.net 側で一定期間後に失効しうる):

```
$ curl -s -H "Accept: application/json" "https://check-host.net/check-tcp?host=163.44.119.79:25&max_nodes=5"
{"ok":1,"request_id":"49a067dak587", ...}
$ curl -s -H "Accept: application/json" "https://check-host.net/check-result/49a067dak587"
{"bg1.node.check-host.net":[{"address":"163.44.119.79","time":0.318711}], ...}
```

| ポート | permanent_link |
|---|---|
| 25 | https://check-host.net/check-report/49a067dak587 |
| 465 | https://check-host.net/check-report/49a06947kf5c |
| 587 | https://check-host.net/check-report/49a06a1ekb89 |
| 993 | https://check-host.net/check-report/49a06abckccf |

**結論**:
- 25番ポート: 2026-09-02付でコントロールパネルにより解除された状態が、タスク1.1着手時点でも維持されている。再解除は不要。
- 465 / 587 / 993番ポート: 到達を再確認した。587のin1と993のro1の不達は、他4拠点がいずれも到達していること、null応答やタイムアウトが当該拠点固有の事情であり全拠点共通の失敗ではないことから、VPS側・提供元側のフィルタに起因するものではないと判断する。提供元側の操作は不要であることをあらためて確認した。

**情報源の依拠状況**: 上記はいずれもcheck-host.netの分散型TCP到達性チェックのみに基づく。25番と993番については、MXToolbox SuperTool (米国拠点) による独立した追加確認も取得済みで、この2ポートはcheck-host.netとMXToolboxの2つの独立した情報源でTCP到達を確認している。

| 対象 | コマンド | 結果 |
|---|---|---|
| `tcp:163.44.119.79:25` | MXToolbox SuperTool | Success (221ms) |
| `tcp:163.44.119.79:993` | MXToolbox SuperTool | Success (231ms) |
| `smtp:163.44.119.79` | MXToolbox SuperTool | TCP接続は確立するがバナー受信前に切断。docker-mailserverのpostscreenによるバナー遅延に起因する典型的挙動であり、TCP到達性を否定するものではない |

一方、465番と587番についてはMXToolbox等による独立した裏取りは行っておらず、check-host.net単独の結果に依拠している。この差はタスク1.1の後続判断には影響しない。後続タスクの着手判断を左右する関門は25番ポート (提供元側の解除状態) のみであり、25番は2系統の情報源で到達を確認済みである。465 / 587番の到達確認は「提供元側の追加操作を要しない」ことを補足的に裏付ける記録であって、それ自体が着手判断のブロッカーではない。

#### VPSの利用可能メモリとswapの実測

対象: `vps` (tailnet 100.109.6.7、ホスト名 `vm-439585ac-73`)。SSH (`trvlr@100.109.6.7`) で `free -m` / `swapon --show` / `/proc/meminfo` を取得した。構成変更は行っていない。

```
$ free -m
               total        used        free      shared  buff/cache   available
Mem:            1966         561         215           0        1387        1404
Swap:           2047          25        2022

$ swapon --show
NAME                     TYPE SIZE  USED PRIO
/var/spool/swap/swapfile file   2G 25.2M   -2

$ /proc/meminfo (抜粋)
MemTotal:        2013516 kB
MemAvailable:    1438096 kB
SwapTotal:       2097148 kB
SwapFree:        2071376 kB
```

| 指標 | 値 |
|---|---|
| 物理メモリ総量 | 約1966 MB |
| 利用可能メモリ (MemAvailable) | 約1404〜1438 MB |
| swap総量 | 約2047 MB (ファイル型swap、`/var/spool/swap/swapfile`) |
| swap空き | 約2022〜2071 MB |
| 利用可能メモリ + swap空き | 約3400〜3500 MB |

**ClamAVの要求量との突き合わせ**: docker-mailserver公式FAQ (2026-09-02に再取得し現行値であることを確認) は、ClamAVがシグネチャデータベース全体を常駐メモリに読み込むため「about 850M and growing」の常駐メモリを要すると明記し、swapを使わない場合は「you may need 3G RAM」としている。この値はセクション7の既存記録と一致する。

利用可能メモリ+swap空きの合計 (約3400〜3500 MB) はClamAVの現在の要求量 (約850 MB、増加傾向) を上回る。物理メモリ総量 (約1966 MB) 単体でも既に850 MBを上回っており、swapを合わせた予算にはPostfix/Dovecot/rspamd等の他プロセス分を差し引いても余裕がある。

**判断**: 資源はClamAVの要求量を下回っていない。要件11.6の「下回る場合は有効化しない」分岐には該当せず、ウイルス検査機構 (ClamAV) を有効化する前提を妨げる資源制約は無い。ただし「約850 MBで増加を続けている」という上流の記述どおり、定義データベースの将来的な肥大化によって前提が崩れうる点は残存リスクとして記録する。実際の有効化と設定はタスク6.5で行う。

**出典 (現行値の再確認)**:
- [FAQ — docker-mailserver](https://docker-mailserver.github.io/docker-mailserver/latest/faq/)

### 11. タスク1.2: 認証基盤の版固定状況の確認（ブロッカー）

**確認日**: 2026-09-02。タスク1.2 (アプリケーションパスワードによる bind の成立確認) の着手にあたり、要件1.14「実証に用いる認証基盤の版を `iac-hygiene-remediation` が固定した版と一致させる」の前提となる、当該 spec が固定した Kanidm の具体的な版を特定しようとした。

**確認した箇所と結果**:

- `iac-hygiene-remediation/design.md` の Technology Stack 表 (203-205行) は Kanidm (`kanidmd`) を認証基盤として採用する記述を持つが、具体的なバージョン番号やイメージタグの記載はない。「宣言的な適用は非公式の実装に依存し、供給元とバージョンを固定する」という**方針**のみが記述され、固定した値そのものは書かれていない。
- IdentityPlatform コンポーネント (990-1027行) は「コンテナイメージのバージョン」を state model に含める旨、および「イメージタグを可変でない参照で指定する」旨を記述するが、これも実装時に満たすべき制約であり、固定済みの値ではない。
- `iac-hygiene-remediation/requirements.md` の要件26 (Kanidm 構築、26.1-26.38) を「版」「バージョン」で検索したが、具体的な版を指定する記述は無い。
- `iac-hygiene-remediation/tasks.md` のタスク26.1「認証基盤をクラスタ上に構築する」およびタスク26.2「バックアップと更新の制約を定義に反映する」は、いずれもチェックボックス未完了 (`- [ ]`)。26.2 に「コンテナイメージを可変でない参照で指定し、マイナーバージョンを飛ばした更新が自動同期で適用されない状態にする」とあり、版の固定はこのタスクの実施内容として**これから行われる**ものであって、既に固定された値ではない。
- `my-home-network` と `gitops-apps` の両リポジトリを `kanidm` で走査したが、Kanidm のマニフェスト・Terraform 定義・イメージタグの記述は一切存在しない (`gitops-apps/apps/` に Kanidm 関連のディレクトリ・ファイルは無い)。
- `iac-hygiene-remediation/spec.json` の `phase` は `tasks-generated` であり、`ready_for_implementation: true` だが実装はまだ開始されていない。

**結論**: `iac-hygiene-remediation` は Kanidm の採用と「版を固定する」という方針を design.md / tasks.md に記載しているが、タスク26.1・26.2 (Kanidm の構築とイメージタグの固定) 自体が未着手であるため、**現時点で照合対象となる固定済みバージョンが存在しない**。

要件1.14は「一致しない版で得た結果を実証の成立根拠としない」と定める。比較対象となる固定版が存在しない状態でいずれかの版を選んで実証しても、その版が `iac-hygiene-remediation` の版と一致することを確認する手段が無い。したがって版の一致を確認できないまま実証環境を構築することはできない。

**不成立の原因の区別 (要件1.6)**: 機構そのもの (Kanidm のアプリケーションパスワード機能自体) には起因しない。`iac-hygiene-remediation` 側で Kanidm の版がまだ固定されていないという、本タスクの前提条件の未成立に起因する。版の更新ではなく、`iac-hygiene-remediation` のタスク26.1/26.2の完了を待つ必要がある。

**既存記録との関係**: 本 research.md のセクション6・10には、spec-design フェーズ中に別途実施された同種の実証記録 (bind の成立、対照実験、設定上書き経路、IMAP ログイン) が既に存在する。しかしそこで用いた Kanidm の具体的な版 (イメージタグ) は記録されておらず、`iac-hygiene-remediation` の固定版との一致も確認されていない。したがって当該記録は要件1.14の充足根拠としては使えず、タスク1.2の成立根拠にもならない。

**タスク1.2の状態**: **ブロック**。`iac-hygiene-remediation` のタスク26.1/26.2で Kanidm の版が固定された後、当該版を用いてタスク1.2 (本項) を再実施する必要がある。本項の確認作業自体はローカルでの調査のみであり、VPS・k3s を含むいかなる環境にも変更を加えていない。

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

## タスク1.2/1.3 実証記録 (2026-09-03)

セクション11で記録したブロッカー(版の固定先が存在しない)が解消したことを確認したうえで、タスク1.2・1.3を最小構成(ローカルDocker、VPS/k3s の実環境不使用)で実施した。

### 版の一致の確認

`gitops-apps/apps/kanidm/deployment.yaml` に Kanidm のマニフェストが存在し、`docker.io/kanidm/server@sha256:7c3d7ed868e91f78c24a7fb9c548876563b375a4203021b730d58369b97ad154` にダイジェスト固定されている。同ファイルのコメントは「イメージはダイジェスト固定 (タグ 1.11.1 と同一)」と明記する。実証に用いる前に、このイメージ自体のラベル (`docker image inspect` の `Config.Labels`) を直接確認した。

```
"Labels":{"com.kanidm.git-commit":"f5e76936d...","com.kanidm.version":"1.11.1"}
```

イメージ自身のラベルが `1.11.1` であることを確認し、実証はこのダイジェストのイメージをそのまま用いた。クライアント (`kanidm` CLI) も `docker.io/kanidm/tools:1.11.1` を用い、版を一致させた。これにより要件1.14/2.1の前提が満たされ、セクション11のブロッカーは解消済みである。

### 実証環境の構成

ローカルDockerに以下を構築した (`docker network create mailpoc-net` 上)。VPS・k3sには一切変更を加えていない。

- `kanidm-poc`: 上記ダイジェストの `/sbin/kanidmd server`。`cert-generate` で自己署名CA配下のサーバ証明書を発行し、`domain = "kanidm.poc.test"` で起動 (ネットワークエイリアス `kanidm.poc.test` で名前解決)。
- `dms-poc`: `docker.io/mailserver/docker-mailserver:16.0.0` (Dovecot 2.4系、design.mdの決定と一致)。

初期化は `kanidmd recover-account idm_admin` (ローカル使い捨て環境のブートストラップであり、本番クラスタの `kanidm` Deployment に対しては実行していない)。

### 1.2: アプリケーションパスワードによる bind の成立

`idm_admin` で以下を宣言した: グループ `mail-users`、利用者 `mailtest`、`mail-users` へのアカウントポリシー (`credential-type-minimum any`)、アプリケーション定義 `mail` (`system application create mail "DMS Mail" mail-users`)。

**判明した前提**: `mail-users` の `credential-type-minimum` を緩めても、`mailtest` は動的グループ `idm_all_persons` (全利用者が自動加入する builtin dyngroup) の `credential_type_minimum: mfa` を同時に継承するため、利用者自身のログイン(セッション確立)にはTOTP等のMFAが必須のままだった。アプリケーションパスワードの発行 (`person applications create`) には利用者自身の認証済みセッションおよび直前の再認証 (`kanidm reauth`、sudo同様の期限付き特権) を要するため、`mailtest` にTOTPを登録して初めて `person applications create mailtest <app_uuid> "IMAP client"` が成立した。

**bind確認 (Python `ssl.create_default_context()` によるホスト名検証付きTLS + 自前のLDAPv3 BindRequestをBERで直接組み立てて送信。`iac-hygiene-remediation` で有効性を確認済みの手法と同じ検証方式)**:

| ケース | bind DN | 資格情報 | resultCode |
|---|---|---|---|
| 成立 | `spn=mailtest,app=mail,dc=kanidm,dc=poc,dc=test` | アプリケーションパスワード | **0 (success)** |
| 対照: アプリケーション指定なし | `spn=mailtest,dc=kanidm,dc=poc,dc=test` | アプリケーションパスワード(同一) | 49 (invalidCredentials) |
| 対照: 主クレデンシャル | `spn=mailtest,app=mail,dc=kanidm,dc=poc,dc=test` | 主パスワード | 49 (invalidCredentials) |
| 対照: グループ除外後 | `spn=mailtest,app=mail,dc=kanidm,dc=poc,dc=test` | アプリケーションパスワード | 49 (invalidCredentials) |
| 対照: 再追加後 | 同上 | 同上 | **0 (success)** に復帰 |

bind DNの `app=` の前段のキー名は `spn=` `name=` のいずれでも成立した (Kanidmの公式LDAP文書が記す「キー名自体は評価されない」という挙動と一致)。ベースDNはサーバの `domain = "kanidm.poc.test"` から `dc=kanidm,dc=poc,dc=test` として導出されることを実測で確認した。TLSはPythonの `ssl.create_default_context()` でホスト名 `kanidm.poc.test` を検証させたうえで確立しており、`peer cert` の取得にも成功している (`openssl s_client` の連鎖検証のみに頼っていない)。

実証環境の外 (VPS・k3s) への変更は行っていない。

### 1.3: 設定上書き経路と取得の成立

docker-mailserver v16.0.0 における実際の上書き経路を、`doveconf -n` で反映を確認しながら特定した。

**上書き経路 (2つの併用が必須。片方だけでは成立しない)**:

1. **追加設定ファイル**: ホスト側 `/tmp/docker-mailserver/dovecot.cf` → コンテナ内 `/etc/dovecot/local.conf` としてコピーされ、`dovecot.conf` 末尾の `!include_try local.conf` で読み込まれる。ここに bind DN テンプレートを置いた:
   ```
   passdb ldap {
     bind = yes
     bind_userdn = spn=%{user},app=mail,dc=kanidm,dc=poc,dc=test
   }
   userdb static {
     fields { uid = 5000; gid = 5000; home = /var/mail/%{user} }
   }
   ```
   `doveconf -n` でこの値がそのまま反映されることを確認した。

2. **既定の項目定義ファイルの差し替え**: `/etc/dovecot/conf.d/auth-ldap.conf.ext` の既定内容は `passdb ldap { fields { user = %{ldap:uniqueIdentifier}; password = %{ldap:userPassword} } }` という検索+パスワード比較方式で、Kanidmには存在しない属性を参照する。**局所設定ファイル (1.) を追加しただけでは、この既定の `fields` ブロックは消えず同一の `passdb ldap` ブロックへ `bind = yes` と共存してマージされる** (`doveconf -n` で両方が同時に出力されることを実測)。この状態で認証を試みると `ldap: unknown user` で失敗する (既定の属性定義による失敗を実際に再現した)。既定ファイルの `fields` ブロックを完全に削除し、接続設定のみを残す形に差し替えて初めて `bind` 方式が有効になった。

**遭遇した細部 (design.mdの記述より詳細)**:
- ホストからコンテナ内の単一ファイルパスへ直接バインドマウントすると、起動スクリプトが同パスへ `sed -i` (rename方式) を試みて `Device or resource busy` で失敗する。既定ファイルの差し替えは、起動後にコンテナ内で直接上書きする方式で行った (本番はAnsibleロールがコンテナ起動前にホスト側ファイルを配置する想定であり、この制約には当たらない)。
- 接続先 (`ldap_uris` / `ldap_base`) は `LDAP_SERVER_HOST` / `LDAP_SEARCH_BASE` 環境変数で反映される (これは効く)。反映されないのは bind モードやテンプレートなど **認証方式そのもの** に関する設定であり、これが research.mdセクション6・design.mdの「環境変数では反映されない」の指す範囲である。
- `bind = yes` を使っていても `passdb_ldap_filter` に値を与えないと `ldap: No passdb_ldap_filter given` で起動時に失敗する。空文字列 (`passdb_ldap_filter =`) でも同エラーになり、非空の値 (`(spn=%{user}@kanidm.poc.test)`、実際には bind 方式のため評価されない) を与える必要がある。Dovecot 2.4.1 の未文書化の制約として記録する。

**取得 (IMAP) ログインの成立 (`doveadm auth test` および実際のIMAPプロトコルによる `imaplib` ログイン)**:

| 資格情報 | doveadm auth test | IMAPログイン (imaplib) |
|---|---|---|
| アプリケーションパスワード | succeeded | **成立** (`LOGIN` → `OK`、`LIST` でINBOX等を取得) |
| 主クレデンシャル | failed | 失敗 (`AUTHENTICATIONFAILED`) |

以上により、1.2・1.3の受入基準 (bind の成立と対照、設定上書きの反映、既定属性差し替えによる失敗解消、アプリケーションパスワードによるIMAPログインの成立) をすべて満たした。実証に使ったコンテナ・ネットワークは検証後に破棄し (`docker rm -f kanidm-poc dms-poc && docker network rm mailpoc-net`)、VPS・k3s へは変更を及ぼしていない。構成ファイル自体は再実行できる形で `/tmp/claude-1000/.../scratchpad/mailpoc/` に残した (ローカル一時領域のため、このリポジトリには含まれない)。

### 1.4: 実証結果のまとめ

**成立した項目**:

- アプリケーション指定を含む bind DN によるアプリケーションパスワードでの bind (resultCode 0)。
- 対照3種 (指定なし・主クレデンシャル・グループ除外) がいずれも invalidCredentials (49) で拒否されること。
- docker-mailserver 側の設定上書き経路 (追加ファイルによる bind DN テンプレート付与、既定項目定義ファイルの差し替え) が `doveconf -n` の出力に反映されること。
- 既定の項目定義 (検索+パスワード比較、`uniqueIdentifier`/`userPassword` 参照) のままでは `ldap: unknown user` で失敗し、差し替え後に解消すること。
- アプリケーションパスワードによるIMAPログインの成立、および主クレデンシャルでの同ログインの失敗。
- 実証に用いた Kanidm イメージの版が `iac-hygiene-remediation` の固定版 (1.11.1、`gitops-apps/apps/kanidm/deployment.yaml` のダイジェスト参照と一致) であること。

**成立しなかった項目**: なし。bind・設定上書き・IMAP取得のいずれも最小構成で成立した。

**不成立の原因の区別**: 該当なし (全項目成立のため)。

**最小構成では再現されない条件 (本番構成で改めて確認する項目、design.mdの段階1・段階3の完了条件と同一)**:

- 認証局が発行した証明書による接続 (本実証はKanidm付属の自己署名CAを使用)。
- クラスタ (k3s) 上で実際に稼働するKanidmへの接続 (本実証はローカルDocker単体)。
- tailnet を経由する経路 (本実証はDockerブリッジネットワーク内)。

**着手を妨げる要因**: 確認できていない。段階0の実証は全項目成立した。

**運用者の判断が要る点**:

- 上記の成立結果をもって本構築 (段階1以降) に着手するか否かの判断そのもの。
- `passdb_ldap_filter` に非空の値を要する制約 (Dovecot 2.4.1、未文書化) を、本番の `dovecot.cf.j2` テンプレートに反映するかどうかの設計判断。値そのものはbind方式では評価されない前提で置いたため、本番でも同様の扱いで良いか運用者側で確認されたい。
- `mail-users` グループのアカウントポリシー緩和 (`credential-type-minimum: any`) が、`idm_all_persons` 由来のMFA要求 (利用者自身のログインセッション確立に必要) と両立する前提で運用手順が組まれているか。今回はTOTP登録により回避したが、本番の利用者向け手順にこの前提が明記されているかを要件2.13の運用手順定義時に確認されたい。

### 段階1の関門における判断

段階1の実証はすべて成立し、運用者の判断により段階2以降へ着手する。あわせて、実証の過程で
浮上した二点について次のとおり決定した。

取得側の実装が、結合方式であっても検索条件に非空の値を要求する。条件自体は評価されないため、
本番の設定でも評価されない値を置いて起動を成立させる。この値が意味を持たないことを設定上の
コメントとして残す。

利用者を収容する器に課される資格情報の下限により、利用者が自分でアプリケーション用の資格情報を
発行するには、本人のログインに多要素が登録されている必要がある。当該基盤の利用者は運用者一名で
あり、既に多要素を登録済みであるため、この制約を許容する。利用者が増える場合は、発行の手順に
多要素の登録を前置する必要がある。

## 調査ログ: メールクライアントの OAuth2 対応 (クライアント側)

### 調査の動機

自前の OAuth2/OIDC プロバイダとして Kanidm 1.11.1 を運用しており、Dovecot 2.4 系の `oauth2`
関連機構でトークン検証自体は成立しうる見込みがある。ただし IMAP/SMTP のログインを実際に
アプリケーションパスワードから OAuth に切り替えられるかは、主要なメールクライアントが
「Gmail・Outlook のような既知の提供者」ではなく「任意の (自前の) OAuth 提供者」を指定できるか
どうかで決まる。本節はこの点をクライアントごとに一次情報で確認した記録である。調査はクライアント
側の対応状況の確認のみを目的とし、設定変更・実装は行っていない。

### 総括表

| クライアント | 結論 | 確認バージョン |
|---|---|---|
| Thunderbird (デスクトップ) | 条件付きで使える (WebExtension 経由) | 安定版 155 (2026-09時点) |
| Thunderbird for Android / K-9 Mail | 使えない | beta 21.0b2 (2026-07時点) |
| iOS 標準メールアプリ | 使えない | (ビルド番号は未特定) |
| macOS 標準メールアプリ (Mail.app) | 使えない | (ビルド番号は未特定) |
| Android の Gmail アプリ | 使えない | (バージョン未特定、ドキュメント上変更なし) |
| Outlook (デスクトップ/モバイル) | 使えない (組み込み提供者限定) | (ビルド番号は未特定) |
| Roundcube | 使える | v1.7.0 (2026-05リリース、確認時点最新) |
| SOGo | 使える | (バージョン番号は未特定) |
| SnappyMail | 条件付きで使える (公式保証は薄い) | v2.29.1.29 で `login-oauth2` プラグイン存在を確認 |

### 1. Thunderbird (デスクトップ) — 条件付きで使える

組み込みプロバイダ (Google, Microsoft, Yahoo, AOL, Mail.ru, Yandex, Fastmail, Comcast,
Thunderbird Pro 等) は `OAuth2Providers.sys.mjs` の `kIssuers` マップにハードコードされており
([searchfox.org/comm-central](https://searchfox.org/comm-central/source/mailnews/base/src/OAuth2Providers.sys.mjs))、
about:config やアカウント設定画面から任意の endpoint を直接入力する口はない。

同ファイルは `registerProvider(details, hostnames, scopes, emailDomains)` /
`unregisterProvider(issuer)` という実行時登録用の関数を公開しており、コメントで
"This will typically only be called by the extension API" と明記されている。これに対応する
公式 WebExtension API が `oauthProvider`
([webextension-api.thunderbird.net/en/mv2/oauthProvider.html](https://webextension-api.thunderbird.net/en/mv2/oauthProvider.html))
であり、manifest.json の `oauth_provider` オブジェクトに `authorizationEndpoint` /
`tokenEndpoint` / `clientId` / `hostnames` / `issuer` / `scopes` / `redirectionEndpoint` 等を
宣言することで、任意の自前 OIDC プロバイダを登録できる。`clientSecret`・`usePKCE` は TB140+、
`useExternalBrowser`・`issuerIdentifier` は TB153+、`emailDomains` は TB155+ で追加された。
公式ソースドキュメント
([source-docs.thunderbird.net/en/latest/backend/oauth.html](https://source-docs.thunderbird.net/en/latest/backend/oauth.html))
も「For other services, this data can be added with an add-on using the oauthProvider API」と
明記しており、UI から直接設定する手段は記載されていない。

**設定手順**: `oauth_provider` を宣言した WebExtension を作成 (または既存のコミュニティ製
アドオン [raa-org/thunderbird-custom-idp](https://github.com/raa-org/thunderbird-custom-idp)、
[ttaeschn/Thunderbird-OAuth2-Provider-Plugin](https://github.com/ttaeschn/Thunderbird-OAuth2-Provider-Plugin)
を利用) してインストールし、有効化後にアカウント設定で当該サーバの認証方式として OAuth2 を
選択する。

**条件**: 本体単体の GUI 設定では完結せず、未署名アドオンのインストールという追加の運用が
必要になる可能性がある (署名要件の回避手順は未検証)。`registerProvider` はコメント上
「内部 API であり将来のバージョンで変更されうる」とされ、安定性の保証は薄い。

### 2. Thunderbird for Android / K-9 Mail — 使えない

`TbOAuthConfigurationFactory.kt`
([github.com/thunderbird/thunderbird-android](https://github.com/thunderbird/thunderbird-android/blob/main/app-thunderbird/src/release/kotlin/net/thunderbird/android/auth/TbOAuthConfigurationFactory.kt))
の `OAuthConfigurationFactory.createConfigurations()` は、AOL・Gmail・Fastmail・
Microsoft/Office365・Yahoo・Thundermail の6プロバイダのみをハードコードで返す。ホスト名から
OAuth 設定 (endpoint・client ID・redirect URI) への対応表がソース直書きであり、設定ファイルや
プラグインでの外部注入口は実装されていない。

任意プロバイダ対応を求める公式 Issue
[#6152 "Support for user-specified OAuth providers"](https://github.com/thunderbird/thunderbird-android/issues/6152)
が Open のまま存在しており、これが未実装であることの一次証拠になっている。新規プロバイダの
追加にはソース修正と再ビルドが必須で、公式手段としての回避策はない。

### 3. iOS 標準メールアプリ — 使えない

一般ユーザの手動設定・MDM 経由の構成プロファイルのいずれも同一の `com.apple.mail.managed`
payload を使用する。`IncomingMailServerAuthentication` / `OutgoingMailServerAuthentication`
の許容値は `EmailAuthPassword` / `EmailAuthCRAMMD5` / `EmailAuthNTLM` / `EmailAuthHTTPMD5` /
`EmailAuthNone` の5つのみで、OAuth2 に相当する値は存在しない
([ProfileCreator/Configuration-Profile-Reference: Email Payload.md](https://github.com/ProfileCreator/Configuration-Profile-Reference/blob/master/markdown/Email%20Payload.md)、
Apple 公式 Configuration Profile Reference のミラー)。Exchange ActiveSync payload には
`OAuth` キーがあるが Microsoft のクラウドサービス専用に固定されており
([Apple Support Guide — Exchange ActiveSync (EAS) payload settings](https://support.apple.com/guide/deployment/exchange-activesync-eas-payload-settings-depa9c22f8c/web))、
IMAP/SMTP 向けではないため対象外。Gmail/iCloud/Yahoo/Outlook.com/AOL の OAuth ログインは
アプリ内にハードコードされた「プロバイダ選択」フロー経由でのみ動作し
([Apple Support — Choose the correct email provider in Mail](https://support.apple.com/en-us/102088))、
「その他 (Other)」を選んだ場合の手動 IMAP 設定にはパスワード認証系のキーしかない。
MDM を使っても同じ Email payload スキーマを使うため、任意の OAuth プロバイダを指定する経路は
一般ユーザ向けと変わらない。

### 4. macOS 標準メールアプリ (Mail.app) — 使えない

iOS 版と同一の `com.apple.mail.managed` payload・同一の許容値を共有しており、根拠・結論とも
上記「3. iOS 標準メールアプリ」と同じ。

### 5. Android の Gmail アプリ — 使えない

公式サポートページ
([Add another email account to the Gmail app - Android](https://support.google.com/mail/answer/6078445?hl=en-GB))
では、非 Gmail アカウントを「Personal (IMAP)」として手動追加する手順は一貫して
「Enter your password」であり、OAuth の選択肢は記載されていない。IMAP の第三者プロバイダ向けに
client ID やトークンエンドポイントを設定する項目は存在しない。

### 6. Outlook (デスクトップ / モバイル、New Outlook 含む) — 使えない (組み込み提供者に限定)

OAuth 対応は Microsoft 365/Outlook.com (MSAL 経由) と、「Sync your account in Outlook to the
Microsoft Cloud」機能経由の Gmail・Yahoo・iCloud に限定される
([Sync your account in Outlook to the Microsoft Cloud](https://support.microsoft.com/en-us/office/sync-account-in-outlook-for-mac-to-microsoft-cloud-992b833d-79bd-4ecf-820e-089bbf6eb92e)、
"Gmail, Yahoo, and iCloud use their own sign-in windows (OAuth) in modern Outlook" と明記)。
汎用の IMAP アカウントも同機能でクラウド同期できるが、OAuth サインイン対象として明記されて
いるのは Gmail/Yahoo/iCloud のみであり、これらの OAuth も Microsoft 自身が登録したクライアント・
Microsoft 側のブローカー経由で動作する。ユーザーが自分の OAuth クライアント (自前プロバイダ)
を登録する形の設定項目は、手動 IMAP セットアップ (Advanced setup) を含め一次情報上確認できな
かった。

### 7. Roundcube — 使える

公式 Wiki
([Configuration: OAuth2](https://github.com/roundcube/roundcubemail/wiki/Configuration:-OAuth2))
と `config/defaults.inc.php`
([roundcube/roundcubemail](https://github.com/roundcube/roundcubemail/blob/master/config/defaults.inc.php))
により、v1.5-beta 以降で `oauth_provider` に `'gmail'` `'outlook'` に加えて **`'generic'`**
を選択でき、任意のプロバイダを設定できる。確認時点の最新安定版は v1.7.0
([2026-05リリース記事](https://roundcube.net/news/2026/05/10/roundcube-1.7.0-released))、1.6.x
は LTS (セキュリティ修正のみ)。

**設定項目**: `oauth_client_id`, `oauth_client_secret`, `oauth_auth_uri`, `oauth_token_uri`,
`oauth_identity_uri`, `oauth_logout_uri`, `oauth_jwks_uri`, `oauth_config_uri` (OIDC ディスカ
バリ URI、v1.7 で追加)、`oauth_scope`, `oauth_provider_name`, `oauth_pkce` (既定 S256)、
`oauth_identity_fields`, `oauth_auth_parameters`。v1.7 で `oauth_cache` が必須化されている。

**設定手順**: `config.inc.php` に `defaults.inc.php` の OAuth セクションをコピーし、上記項目を
自前 Kanidm の discovery URL・client_id 等で埋める。Webmail 自体が Authorization Code フローを
回してユーザをログインさせ、得たトークンで裏の IMAP/SMTP に XOAUTH2/OAUTHBEARER で接続する
「サーバ間 OAuth」構成が公式にサポートされている。

**条件**: トークンエンドポイントは `client_secret_post` 認証必須。プロバイダによっては
`oauth_auth_parameters` で `nonce` の追加が要る。

### 8. SOGo — 使える

公式 Installation and Configuration Guide
([SOGoInstallationGuide.html](https://www.sogo.nu/files/docs/SOGoInstallationGuide.html)、
Alinto/SOGo 公式) により、`SOGoAuthenticationType` を `openid` に設定して OpenID Connect
認証を有効化できる (`SOGoXSRFValidationEnabled = NO` が前提条件)。

**主要パラメータ**: `SOGoOpenIdConfigUrl` (OIDC ディスカバリエンドポイント。任意プロバイダを
指定できる核となる項目)、`SOGoOpenIdClient`、`SOGoOpenIdClientSecret`、`SOGoOpenIdScope`
(例: `openid profile email`)、`SOGoOpenIdEmailParam` (既定 `email`)。`SOGoOpenIdConfigUrl` で
endpoint を指定する方式のため、Kanidm を含め任意の OIDC 準拠プロバイダに対応しうる。

**Dovecot 連携**: `NGImap4AuthMechanism` に xoauth2 を設定する。Dovecot はネイティブに
XOAUTH2 に対応する。

**条件**: パスワードレス (OpenID 専用) 構成には、セッション管理用の `OCSOpenIdURL` (DB URL)
が別途必要で、`sogo-tool clean-openid-sessions` による期限切れセッションの掃除が運用として
発生する。確認時点の正確なバージョン番号は Installation Guide 本文からは特定できなかった。

### 9. SnappyMail — 条件付きで使える (公式保証は薄い)

`login-oauth2` プラグインが存在し ([the-djmaze/snappymail](https://github.com/the-djmaze/snappymail)、
v2.29.1.29 での存在を [git.tedomum.net のミラー](https://git.tedomum.net/mickge/snappymail/-/tree/v2.29.1.29/plugins/login-oauth2/OAuth2)
で確認)、管理パネルから有効化・設定できる。ただし公式 GitHub Discussion
([#1677 "OAuth 2 support"](https://github.com/the-djmaze/snappymail/discussions/1677))
でメンテナー自身が、実装対象は「Gmail、Office365、Nextcloud OIDC」中心であること、
プロバイダ側への事前登録が必須であること、トークンの有効期限切れの扱いが不透明であること、
ログイン応答にメールアドレスが必ず含まれる保証がないことを明言している。汎用プロバイダ
(Authentik/Authelia 等) での確定的な成功事例は同 Discussion 内で確認できなかった。

**条件**: プラグインのコード構造上は汎用 OAuth2 エンドポイントを設定できると見られるが、
「任意の自前プロバイダで動作保証」という公式記述はなく、具体的な設定フィールド名の中身までは
未確認。

### 10. サーバ側 (Dovecot 2.4 + Kanidm 1.11.1) の見通し

クライアント側の調査結果を踏まえ、Dovecot の `oauth2` 機構が要求するものと Kanidm が提供する
ものの整合性を一次情報で確認した。

**Dovecot 2.4 の構造変化**: 公式ドキュメント
([doc.dovecot.org/main/core/config/auth/databases/oauth2.html](https://doc.dovecot.org/main/core/config/auth/databases/oauth2.html))
に「Changed: 2.4.0: The OAuth2 mechanism no longer uses a passdb for token authentication.
Password Grant still needs a oauth2 passdb.」と明記されている。SASL の bearer token 検証
(OAUTHBEARER/XOAUTH2 で実際に使う経路) は `passdb { driver = oauth2 }` ではなく、グローバルの
`oauth2_*` 設定ブロック (`oauth2_introspection_url`, `oauth2_introspection_mode`,
`oauth2_tokeninfo_url`, `oauth2_local_validation`, `oauth2_issuers`,
`oauth2_openid_configuration_url`, `oauth2_username_attribute` 等) で行う。SASL mechanism は
`auth_mechanisms { oauthbearer = yes; xoauth2 = yes }` で有効化し、ドキュメントは OAUTHBEARER
(RFC 7628) を推奨、XOAUTH2 は互換用としている。

**Kanidm 1.11.1 が提供するもの**
([kanidm.github.io/kanidm/stable/integrations/oauth2.html](https://kanidm.github.io/kanidm/stable/integrations/oauth2.html)):
RFC 7662 Token Introspection endpoint (`/oauth2/token/introspect`)、RFC 7009 Token
Revocation、RFC 9068 準拠の JWT アクセストークン、クライアント単位の公開鍵配布エンドポイント
(`/oauth2/openid/:client_id:/public_key.jwk`)、既定署名アルゴリズムは ES256 (RS256 は
`warning-enable-legacy-crypto` による非推奨経路)。OIDC Discovery 1.0 / RFC 8414 対応。

**判定**: Introspection 経路 (Dovecot `oauth2_introspection_url` ⇔ Kanidm の RFC 7662
introspection endpoint) は双方が同じ RFC の型を公式に想定しており、成立する見通しが高い。
ローカル JWT 検証経路は理論上可能だが、Dovecot 側が Kanidm 既定の ES256 署名を検証できるか、
`oauth2_openid_configuration_url` から JWKS を自動取得する機能が現行 (2.4/main) で実装済みかの
2点が一次情報上確認できず、鍵の事前配置が前提になる可能性が高い。主軸として設計するなら
introspection 経路の方が裏付けが強い。

### 判断材料のまとめ

主要クライアントのうち、自前 OAuth プロバイダを任意に指定できるのは **Roundcube (使える)、
SOGo (使える)、Thunderbird デスクトップ (アドオン経由の条件付き)** に限られる。ネイティブの
モバイル/デスクトップ標準クライアント (iOS Mail、macOS Mail、Android Gmail、Outlook 全般、
Thunderbird for Android/K-9 Mail) はいずれも組み込みプロバイダのハードコードに閉じており、
任意の自前プロバイダを指定する口が存在しない。SnappyMail は技術的には可能性があるが公式が
保証していない。

これを踏まえると、**OAuth ログインを主たる認証手段にするのは現実的ではない**。運用者が日常的に
使う可能性の高いネイティブクライアント (iOS/macOS 標準メール、Android Gmail、Outlook) が軒並み
非対応であるため、これらを使い続ける限りアプリケーションパスワードは廃止できない。Webmail
(Roundcube/SOGo) からのアクセスに限れば OAuth ログインを提供する意味はあるが、それは
「主たる手段」ではなく「Webmail 経路での追加の選択肢」に留まる。

妥当な方針は、**現行のアプリケーションパスワード運用を主軸として維持し、Webmail 経路に限って
OAuth ログインを追加提供する併用構成**である。Thunderbird デスクトップでアドオン経由の OAuth を
使う運用は、未署名アドオンの追加運用コストに見合うかを運用者が判断する任意選択に留めるのが
妥当と考えられる。サーバ側 (Dovecot 2.4 + Kanidm) は introspection 経路であれば技術的に成立する
見通しが高く、Webmail 限定の OAuth 追加提供という範囲であれば要件・設計の作り直しの規模を
抑えられる。

### 裏が取れなかった点

- Thunderbird: 未署名アドオンのインストール制限の具体的な回避手順・Enterprise Policy
  (`ExtensionSettings` 等) での代替可否。`registerProvider` の TB バージョン間の互換性。
- Thunderbird for Android/K-9: サードパーティ製 `raa-org/thunderbird-custom-idp` の対象範囲
  (デスクトップ版向けか Android 版も含むか) は未確認。iOS 版 (thunderbird-ios) の OAuth 実装が
  Android 版と設計を共有するかも未検証。
- iOS/macOS Mail: `developer.apple.com/documentation/devicemanagement/*` の一次ページは
  JS レンダリングのため直接確認できず、静的ミラー (Apple Support Guide) で代替確認した。
- Android Gmail アプリ: アプリのバージョンごとの UI 差分 (最新版で選択肢が追加されている可能性)
  は実機検証していない。
- Outlook: 手動 IMAP セットアップ画面の Authentication 選択肢の具体的な一覧 (Basic のみか
  汎用 OAuth2 の選択肢まであるか) をスクリーンショットレベルでは確認できなかった。
- SOGo: 確認時点の正確なバージョン番号。
- SnappyMail: `login-oauth2` プラグインの具体的な設定フィールド名 (`site.json` の項目名等)、
  自前プロバイダでの動作実績を報告する一次情報 (公式 Issue での成功報告)。
- Dovecot × Kanidm: Dovecot `oauth2_local_validation` が ES256 (EC鍵) を検証できるか、
  `oauth2_openid_configuration_url` が JWKS からの鍵自動取得まで行うか、Kanidm の
  introspection endpoint が要求するクライアント認証方式の具体的な形式。

## タスク2.1/2.2 実装記録 (2026-09-03)

### キー空間

Infisical `prod` 環境に以下の 2 キーを新規登録した (値は本記録に含めない)。

- `MAIL_LDAP_SEARCH_PASSWORD`: 宛先照合用サービスアカウント (タスク 3.2 で Kanidm 側に作る) の
  bind パスワード。`openssl rand -base64 32` でローカル生成。
- `MAIL_DKIM_PRIVATE_KEY`: DKIM 署名鍵。`openssl genrsa 2048` でローカル生成した PEM
  (RSA PKCS#1 形式、rspamd の DKIM 署名モジュールが直接読める形式)。公開鍵は秘密鍵から
  導出可能なため別キーとして保持しない。DNS への登録はタスク 7 (MailDeliverability) の範囲。

命名は既存キー (`KANIDM_*`, `GARAGE_*`, `MYDNS_*` 等) と同じ「対象領域の大文字接頭辞 +
属性」規約に合わせ、`MAIL_` を接頭辞とした。既存キー一覧との衝突がないことを
`infisical secrets --env=prod -o json | jq -r '.[].secretKey'` で確認済み。

設計・要件が言及する「その他の認証情報」に該当する 3 つ目のキーは、design.md / research.md の
既存記述および段階 1 の実証範囲を確認した限り見当たらなかった。現時点で判明している認証情報は
上記 2 件のみ。

### 供給経路

- **VPS (実行時取得)**: `ansible/inventory/host_vars/vps/main.yml` に
  `mailserver_ldap_search_password` / `mailserver_dkim_private_key` を
  `lookup('env', 'MAIL_LDAP_SEARCH_PASSWORD')` / `lookup('env', 'MAIL_DKIM_PRIVATE_KEY')` として
  追加した。既存の `vps_proxy_mydns_master_password` 等と同じ経路 (`infisical run --env=prod --
  ansible-playbook ...` が子プロセスへ環境変数として注入し、host_vars がそれを読む) に従い、
  別の経路を導入していない。
- **k3s (Operator 経由)**: `gitops-apps` 側の `InfisicalStaticSecret` +
  `components/infisical-common` という確立済みの機構を使う方針を確認したが、上記 2 キーの
  実際の消費者は現状 VPS 側のみ (EdgeMailServer: 宛先照合の検索 bind と DKIM 署名) であり、
  k3s 側 (MailboxBackend) にはこの 2 キーを消費する構成要素がまだ存在しない
  (design.md の MailboxBackend Service/State には検索アカウントも署名鍵も現れない。IMAP
  ログインは利用者自身のアプリケーションパスワードによる bind DN テンプレート方式であり、
  静的な共有クレデンシャルを要しない)。そのため `gitops-apps/apps/mailbox/infisical-secret.yaml`
  相当のマニフェストは本タスクでは作成していない。design.md のファイル構成表にある同名ファイルは、
  そのメールボックス用の k8s 定義一式 (namespace, statefulset 等) を作るタスクで、実際に必要になった
  キーとともに追加されるべきものと判断した。k3s 側で新しい消費者が生じた時点で、既存の
  `components/infisical-common` を components: で取り込むだけで供給経路が成立する
  (新しい仕組みの追加は不要)。

### 発行・充足検査の確認

`ansible/roles/mailserver/tasks/main.yml` に、2 キーの充足を検査する `assert` を先頭タスクとして
追加した (`ansible/playbooks/mailserver.yml` から呼ぶ)。配置・起動の手順はまだ存在しないため、
現時点ではこの検査のみを置く。

- **値を欠いた状態**: `infisical run` を経由せず (環境変数が存在しない状態で)
  `ansible-playbook -i inventory/inventory.yml playbooks/mailserver.yml --check --diff` を実行し、
  `assert` が `fatal` で停止し不足しているキー名 (`MAIL_LDAP_SEARCH_PASSWORD`,
  `MAIL_DKIM_PRIVATE_KEY`) を `msg` に含めて示すこと、`changed=0` (適用の途中で何も変更していない)
  であることを確認した。
- **値を充足した状態**: `infisical run --env=prod -- ansible-playbook -i inventory/inventory.yml
  playbooks/mailserver.yml --check --diff` で `assert` が `ok` (`All assertions passed`) になる
  ことを確認した。
- **冪等性**: 上記の充足した状態での実行を連続 2 回行い、いずれも `changed=0` であることを
  確認した (`assert` のみのロールのため自明ではあるが、要件が求める「2 回目に変更を報告しない」
  ことを実測で確認した)。
- **リポジトリ全体の走査**: `pre-commit run gitleaks --all-files` (`.gitleaks.toml` 使用) を
  実行し、`Detect hardcoded secrets` が `Passed` であることを確認した。生成した秘密鍵・パスワードは
  Infisical へ登録した後、ローカルの一時ファイルを `shred -u` で削除済みで、リポジトリ配下には
  一度も書き込んでいない。

### 環境上の注意 (本タスクに固有)

このセッションの Bash 実行環境では `ansible-playbook` の起動時に `ERROR: Ansible requires
blocking IO on stdin/stdout/stderr. Non-blocking file handles detected` で即座に失敗する事象が
あった。実行前に `fcntl` で fd 0/1/2 の `O_NONBLOCK` を解除してから `execvp` する短いラッパー
(`python3 -c "..."`) を介して起動することで回避した。Ansible 側にも構成にも変更を要しない、
実行環境固有の回避策であり、コードには反映していない。

### 裏が取れなかった点 / 運用者の判断が要る点

- k3s 側の Infisical 供給経路について、上述のとおり「今回は k8s マニフェストを作らない」という
  判断をしたが、これは design.md のファイル構成表の記述と字面上は完全には一致しない。実装時に
  MailboxBackend (タスク 5) 側で必要になった時点で、本タスクが定義した 2 キーの範囲では足りない
  可能性がある (例えばバックアップ機構が独自の暗号化パスワードを要する場合)。その場合は新規キーを
  タスク 5/9 の中で追加登録することになる。
- `MAIL_LDAP_SEARCH_PASSWORD` は Kanidm 側のサービスアカウント (タスク 3.2 で作成予定) に
  まだ紐付いていない。値そのものは Infisical に存在するが、Kanidm 上でこのパスワードを実際の
  bind クレデンシャルとして設定するまでは、この値による bind は成立しない。

## 認証手段として OAuth を採らない判断

クライアント側の対応状況を一次情報で確認した結果、任意の提供者を指定できるのは Web ベースの
クライアント (Roundcube、SOGo) に限られ、ネイティブクライアント (iOS / macOS 標準、Android の
Gmail、Outlook 全プラットフォーム、Thunderbird for Android / K-9) は提供者が実装に埋め込まれて
いるため利用できない。Thunderbird デスクトップは拡張機能の API 経由でのみ可能で、GUI 単体では
設定できない。

利用者は、この用途で Web クライアントを新設せず、別途移行予定の Nextcloud Mail を将来の
Web 経路として位置づける方針を採った。したがって本 spec では認証手段をアプリケーション
パスワードのままとし、OAuth の追加提供は行わない。要件・設計の変更は不要。

## タスク3.1/3.2/3.3: 認証基盤上のメール認証の構成 (本番)

`terraform-kanidm/mail.tf` を新規に追加し、以下を宣言した。適用は `infisical run --env=prod --
terraform apply` (ワークスペース `kanidm-identity`)。

- `kanidm_group.mail_users` — アプリケーションパスワードを発行できる利用者グループ。
- `kanidm_account_policy.mail_users` (`credential_type_minimum = "any"`) — 要件2.12。
- `kanidm_application.mail` (`linked_group = kanidm_group.mail_users.id`) — メール用アプリケーション定義。
- `kanidm_service_account.mail_ldap_search` (`entry_managed_by = "idm_admins"`, `generate_api_token
  = true`) — メール属性検索用サービスアカウント。
- `kanidm_group_members.idm_mail_servers` (`members = [kanidm_service_account.mail_ldap_search.name]`)
  — Kanidm 組み込みグループ `idm_mail_servers` (`kanidm group list` で発見。description は
  "Builtin IDM Group for MAIL server access delegation") への所属。**このグループが
  mail 属性の読み取り (検索条件としての利用を含む) を許可する機構であることを本タスクで実測により
  特定した**。既定の Kanidm ドキュメントにこの対応関係の明記はなく、`kanidm group list` の全件出力
  (builtin グループ一覧、`idm_account_mail_read` / `idm_mail_servers` / `idm_mail_service_admins` 等)
  を確認し、実際に search を通して機能を特定した。

利用者個人 (アカウントそのもの、グループ所属) は本ファイルの宣言対象に含めていない。既存の
`identities.tf` の方針 (冒頭コメント) と同じ理由による。

### 適用手段に関する補足: `terraform-kanidm` サービスアカウントの権限

Kanidm の `admin` (system admin) アカウントでは `person create` が `403 AccessDenied` になった
(人物・グループ管理は `idm_admin` 系列の権限領域であり、`admin` は含まれない)。一方、本モジュールの
適用に使う `terraform-kanidm` サービスアカウント (API トークンを `TF_VAR_kanidm_token` として
Infisical 管理) は、ブートストラップ時に付与されたカスタム ACP により、person の作成やグループ
メンバーシップの変更を含む広い権限を持つことを確認した (以下の検証作業はすべてこのトークンを
`curl` で直接 Kanidm REST API に対して叩く形で行った。`kanidm` CLI 自体はサービスアカウントの
API トークン (HS256 署名) をローカルの JWK キャッシュで検証できず `-D <サービスアカウント名>`
では使えないため、CLI は `admin` の対話ログインセッションのみで使用し、サービスアカウント権限を
要する操作は素の REST API 呼び出しで行った)。

### 3.1: 冪等性の実測

1回目の `terraform apply` で 5 リソースを作成 (create のみ、5 to add / 0 to change / 0 to
destroy)。直後に `MAIL_LDAP_SEARCH_PASSWORD` を実際に生成された `mail_ldap_search_api_token`
出力の値で上書きした (後述)。その後 `terraform plan -detailed-exitcode` を実行し、**"No changes.
Your infrastructure matches the configuration." (exit code 0)** を確認した。以降、3.2/3.3 の検証で
API 経由の変更 (グループメンバーシップの一時的な変更、サービスアカウントへの `mail` 属性の一時付与
など) を何度も行ったが、検証の都度きちんと Terraform 宣言どおりの状態へ戻し、最終的にもう一度
`terraform plan -detailed-exitcode` を実行して **"No changes."** であることを確認済み (この節の
末尾を参照)。

既知の事象として `kanidm_group.nas_access` の "Drift detected (update)" が refresh 時に出る (本
タスクとは無関係、既知の未調査事象) が、いずれの plan でも `nas_access` は変更対象に含まれず
"No changes." の結論に影響しなかった。

### 3.1: グループから除外した利用者のメール認証が成立しなくなることの実測

運用者本人のアカウントは資格情報を保持しておらず (個人アカウントは宣言・自動化対象外の方針)、
代理でアプリケーションパスワードを発行することも Kanidm の仕様上できない (要件2.13) ため、本タスク
専用の使い捨て test person (`mail-3-1-verify`、本番 Kanidm 上に作成) を用いて実測し、確認後に
完全に削除した。

手順:
1. `terraform-kanidm` サービスアカウントのトークンで `POST /v1/person` により作成。
2. `PUT /v1/group/mail_users/_attr/member` で `mail_users` に追加 (API 経由、宣言外)。
3. `GET /v1/person/{id}/_credential/_update` でセッションを開始し、`POST /v1/credential/_update`
   に `{"password": ...}` → `"totpgenerate"` → `{"totpverify": [code, label]}` を順に送って
   パスワード + TOTP を設定し `POST /v1/credential/_commit` でコミットした (`idm_all_persons` の
   `credential_type_minimum: mfa` を満たすため。研究ログ「タスク1.2/1.3実証記録」と同じ制約)。
4. `POST /v1/auth` (init2 → begin passwordmfa → cred totp → cred password) でログインし、
   `POST /v1/reauth` で特権 (readwrite) セッションへ昇格した後、
   `POST /scim/v1/Person/mail-3-1-verify/Application/_create_password` でアプリケーションパスワード
   を発行した (`applicationUuid` は `kanidm_application.mail` の id)。これは admin による代理発行
   ではなく、test person 自身のセッションによる自己発行である。
5. k3s クラスタ内 (namespace `kanidm`) に使い捨ての検証用 Pod (`python:3.12-slim`) を起動し、
   自前で組み立てた LDAPv3 BindRequest (BER) を `kanidm.kanidm.svc.cluster.local` の ClusterIP
   (`10.43.86.123:3636`) へ TLS (`ssl.create_default_context()` によるホスト名検証つき、Let's
   Encrypt 発行の実証明書を検証) で送信し、resultCode を読み取った。

| ケース | bind DN | 資格情報 | resultCode |
|---|---|---|---|
| 成立 | `spn=mail-3-1-verify,app=mail,dc=kanidm,dc=fickledev,dc=com` | アプリケーションパスワード | **0** |
| 対照: アプリケーション指定なし | `spn=mail-3-1-verify,dc=kanidm,dc=fickledev,dc=com` | 同一のアプリケーションパスワード | 49 |
| 対照: 主クレデンシャル | `spn=mail-3-1-verify,app=mail,dc=kanidm,dc=fickledev,dc=com` | 主パスワード | 49 |
| **`mail_users` から除外後** (`PUT .../_attr/member` に `[]`) | `spn=mail-3-1-verify,app=mail,...` | アプリケーションパスワード (同一) | **49** |
| 再追加後 (`[...,"mail-3-1-verify"]`) | 同上 | 同上 | **0** に復帰 |

`terraform-kanidm/gitops-apps/kanidm` の実クラスタ・実ドメイン (`kanidm.fickledev.com`) に対する
実測であり、研究ログ「タスク1.2/1.3実証記録」(最小構成での事前実証) と一致する挙動を、本タスクが
宣言した実際の `mail_users` / `mail` リソースに対して再確認した。

検証後、test person をグループから外し (`PUT .../_attr/member` に `[]`)、`DELETE
/v1/person/mail-3-1-verify` で削除した (Kanidm の recycle bin へ移動。`kanidm person get
mail-3-1-verify` が `No matching entries` を返すことを確認済み)。

### 3.2: 検索サービスアカウントによる検索の実測

同じ検証用 Pod から、自前で組み立てた LDAPv3 SearchRequest (BER) を `mail-ldap-search` サービス
アカウントの `dn=token` bind (資格情報は `mail_ldap_search_api_token`、= 更新後の
`MAIL_LDAP_SEARCH_PASSWORD`) で送信した。

**論点: 自己読み取りとの混同を避けるため、検索対象を別エンティティにした。** 最初
`mail-ldap-search` 自身に `mail` 属性を設定して自分自身を検索した際は、`idm_mail_servers` から
一時的に除外した状態でも検索が成立してしまった (Kanidm の自己参照的な読み取り許可によるものと
推測)。これは正しい検証にならないため、検索対象として別の使い捨て test person
(`mail-3-2-target`、`mail` 属性のみ設定、資格情報は作成せず) を新設し、`mail-ldap-search` から
見て第三者のエントリを検索する形で仕切り直した。

| 手順 | `idm_mail_servers` 所属 | フィルタ | 結果 |
|---|---|---|---|
| A (独立手順・先) | 除外済み (`PUT idm_mail_servers/_attr/member` に `[]`) | `(&(mail=mail-3-2-target@fickledev.com)(name=mail-3-2-target))` | **entries=0, resultCode=0** (エラーではない) |
| B | 復帰 (`[...,"mail-ldap-search"]`) | 同上 | **entries=1, resultCode=0** |

design.md の記述どおり「許可の欠落はエラーではなく0件として現れる」ことを、許可なし→ありの順で
独立した手順として確認した (要件が求める順序と逆の順で先に不許可を確認したが、両方の状態を実際に
再現し記録している点で要件を満たす)。

**design.md の想定と異なっていた点**: 「mail属性のみを条件とする検索は資源制限により拒否される」
という design.md / research.md 既存記録 (セクション「6. 認証機構の実証」) の想定を、本番でも
`(mail=mail-3-2-target@fickledev.com)` 単独条件で検索して確認しようとしたが、**拒否されず
`entries=1, resultCode=0` で成立した**。本番 Kanidm のディレクトリに登録されているエントリ数が
現状きわめて少ない (数件) ため、資源制限 (`limit_search_max_filter_test` 等、走査件数に対する
閾値) に達しなかったためと考えられる。設計上の判断 (DMS 側の検索フィルタを必ずインデックス済み
属性との論理積で組み立てる) 自体は将来のエントリ数増加に備えた妥当な防御であり変更しないが、
「現時点の本番環境では単独条件でも拒否されない」という事実は記録として残す。意図的に閾値を
下げて拒否を再現させる操作は、本タスクの受入基準が求める範囲を超えるため行っていない。

検証後、`mail-3-2-target` を削除し、`mail-ldap-search` に一時的に設定した `mail` 属性を削除した。

### 3.2: `MAIL_LDAP_SEARCH_PASSWORD` と Kanidm 側の整合

タスク2.1/2.2で Infisical に登録済みだった `MAIL_LDAP_SEARCH_PASSWORD` (44バイト、ローカル生成の
プレースホルダ値) は、Kanidm のサービスアカウントの LDAP bind 資格情報が API トークン (`dn=token`
bind、サーバ側で生成される JWT) である以上、任意の値を Kanidm 側に指定する経路が存在しない
(`kanidm_service_account` リソースにも `password` 相当の設定可能な属性はなく、`api_token` は
`generate_api_token = true` 時にサーバが生成する computed 値)。したがって「値を Kanidm 側に
設定する」のではなく、**Terraform 適用で実際に生成された `api_token` の値を取得し、
`infisical secrets set --env=prod` で `MAIL_LDAP_SEARCH_PASSWORD` を上書き** することで整合させた
(`terraform output -raw mail_ldap_search_api_token` の出力をファイル経由でのみ扱い、標準出力には
一切出していない。`infisical secrets set` の確認テーブル出力も `/dev/null` に捨てた)。更新後の値は
347バイト (Kanidm の署名済み JWT)。この経緯を DMS 側の実装 (タスク6.2) が参照する際の前提として
記録する。

### 3.3: POSIX パスワードによる LDAP bind の無効化

`kanidm system domain set-ldap-allow-unix-password-bind false` (`admin` の対話ログインセッションで
実行。Terraform provider (`seanlatimer/kanidm` 0.1.10) にはドメイン設定を扱うリソースが存在しない
ため、宣言の対象外・API/CLI 経由の操作として扱う)。実行前に `kanidm system domain show` で
`ldap_allow_unix_pw_bind` が出力に現れない (既定 true で明示表示されない) ことを確認し、実行後は
`ldap_allow_unix_pw_bind: false` が明示されることを確認した。

3.1/3.2 のアプリケーション定義・検索アカウントの適用が完了していることを確認した後に実施した
(要件どおりの順序)。

無効化の前後で、使い捨て test person (`mail-3-3-verify`、POSIX 拡張 + unix password を設定、
アプリケーションパスワードも発行) に対して同じ LDAP bind テストを行った。

| 時点 | bind DN (アプリケーション指定なし) | 資格情報 | resultCode |
|---|---|---|---|
| 無効化前 | `spn=mail-3-3-verify,dc=kanidm,dc=fickledev,dc=com` | **POSIX (unix) パスワード** | **0** (成立) |
| 無効化後 | 同上 | 同上 | **49** (拒否) |
| 無効化後 | `spn=mail-3-3-verify,app=mail,dc=kanidm,dc=fickledev,dc=com` | アプリケーションパスワード | **0** (成立、影響なし) |
| 無効化後 (参考) | `dn=token` | `mail-ldap-search` の API トークン | **0** (影響なし) |

無効化前に POSIX パスワードでの非アプリケーション指定 bind が成立することを実際に確認したうえで
無効化し、無効化後に同じ bind が拒否されること、アプリケーション指定 bind と検索アカウントの
`dn=token` bind は無関係に成立し続けることを確認した。

検証後、`mail-3-3-verify` を削除した。

### 最終確認

上記すべての API 経由の一時的な変更 (グループメンバーシップの増減、`mail` 属性の一時付与、
test person の作成・削除) を元に戻したうえで、`terraform plan -detailed-exitcode` を実行し
**"No changes." (exit code 0)** であることを再確認した。`mail_users` / `idm_mail_servers` の
実際のメンバーシップも、宣言どおり (`idm_mail_servers` に `mail-ldap-search` のみ、`mail_users` は
空) であることを `kanidm group get` で確認した。

### 裏が取れなかった点 / 運用者の判断が要る点

- `idm_mail_servers` が mail 属性の検索・読み取り許可を実際に与える機構であることは実測により
  特定したが、Kanidm の一次ドキュメント (`kanidm.github.io/kanidm/stable/...`) にはこのグループと
  mail 属性 ACP の対応関係を明記した記述が見当たらなかった。将来の Kanidm バージョンアップで
  この対応関係が変わらない保証はない。
- 「mail属性のみの検索が資源制限で拒否される」という設計上の前提は、現在の本番環境のエントリ数の
  少なさにより実測で再現できなかった。DMS 側 (タスク6.3) の実装は design.md の方針どおり論理積で
  組み立てるが、エントリ数が増えた時点で実際に拒否が機能するかどうかは未検証のまま残っている。
- `terraform-kanidm` サービスアカウントの実際の権限範囲 (どの ACP に基づき person 作成やグループ
  メンバーシップ変更まで可能なのか) は、ブートストラップ時に Kanidm 側へ直接設定されたものであり
  (README.md 記載のとおり本モジュールの適用対象外)、本タスクでは実際に person 作成等が可能である
  ことを実測したのみで、権限の設定自体は確認・変更していない。

## タスク4.1/4.2: LDAPS の公開経路と証明書 (本番)

### 4.1: tailnet 限定の公開経路

既存の NodePort (`kanidm` Service, 3636→30636、`iac-hygiene-remediation` task 26.13 が構築) は
kube-proxy が全ノードへ転送する既定 (`externalTrafficPolicy: Cluster`) だったため、DMZ
(`192.168.1.0/24`) 上のどのホストからも到達でき、tailnet 限定にはなっていなかった。以下の
2点を追加し、Kubernetes 側の設定のみで tailnet 限定を実現した (ホストファイアウォールは変更していない)。

- `gitops-apps/apps/kanidm/service.yaml` に `externalTrafficPolicy: Local` を追加。kanidm Pod は
  PV の nodeAffinity により `k3s-agent-minipc` (`192.168.1.151`) に固定されているため、以後は
  この 1 ノードの NodePort のみが応答し、他ノード (`192.168.1.150` / `.152`) は無応答になる。
  NodePort 中継時の SNAT を避け、送信元 IP をそのまま Pod まで届けるための前提でもある。
- `gitops-apps/apps/kanidm/networkpolicy.yaml` (新規) を追加。k3s は kube-router ベースの
  NetworkPolicy コントローラを既定で有効化しており (`journalctl -u k3s` に
  `Starting network policy controller` を確認)、実際に強制されることを前提に構成した。ldaps
  (3636) を送信元 CIDR `100.64.0.0/10` (tailnet CGNAT) と `10.42.0.0/16` (Pod CIDR、クラスタ内
  bind 用) に限定し、https (8443) は cloudflared 経由の OIDC/UI 利用を壊さないよう無制限のまま
  別ルールで維持した。

コミット: gitops-apps `f02286f` (`feat(kanidm): LDAPS の NodePort を tailnet 限定にする`)。
ArgoCD (`kanidm` Application) は `argocd.argoproj.io/refresh=hard` 後、即座に Synced/Healthy で反映。

**実測 (VPS `100.109.6.7` から)**:

| 接続先 | 経路 | 結果 |
|---|---|---|
| `192.168.1.151:30636` | tailnet (OPNsense 経由の subnet route) | **到達 (OK)** |
| `192.168.1.150:30636` | 同上 | 不達 (Local policy により無応答) |
| `192.168.1.152:30636` | 同上 | 不達 (同上) |

**tailnet-only の実測 (DMZ ローカルからの拒否)**: `k3s-server` (`192.168.1.150`) に SSH ログイン後、
その shell から (送信元 IP が `192.168.1.150`、tailnet を経由しない) `192.168.1.151:30636` へ接続を
試みたところ **`Connection refused`** で拒否された。NetworkPolicy が tailnet を経由しない DMZ
ローカルの接続元を実際に遮断することを確認した。

**回帰確認**: NetworkPolicy 適用後もクラスタ内 Pod (Pod CIDR `10.42.0.0/16`) から ClusterIP
(`10.43.86.123:3636`) への TLS 接続は成立 (`TLSv1.3`)。`https://kanidm.fickledev.com/` (cloudflared
経由の 8443 利用) も `303` (既存の UI リダイレクト挙動、変化なし) を返し、既存の OIDC/UI 経路への
影響がないことを確認した。

### 4.2: 名前解決・証明書の連鎖・3条件同時の実測

`iac-hygiene-remediation` task 26.13 が Terraform (`terraform/cloudflare_dns.tf` の
`kanidm_ldaps_a_records`) で `ldaps.kanidm.fickledev.com` の A レコード (k3s 3 ノード分、非
proxied) を、Ansible (`vps_static_dns_overrides`) で VPS の `/etc/hosts` 静的上書きを、それぞれ
既に構築済みだった (quad100 の DNS リバインディング対策で private アドレスへの応答が drop される
ため、公開 DNS ではなく `/etc/hosts` 上書きで解決先を tailnet 側へ固定する方式)。Terraform の DNS
レコード (公開 DNS、機能的には未使用) は変更せず、実際に解決へ使われる `vps_static_dns_overrides`
のみを 4.1 の変更に合わせて更新した。

- `ansible/roles/vps_proxy/defaults/main.yml`: `vps_static_dns_overrides` の
  `ldaps.kanidm.fickledev.com` を `192.168.1.150/151/152` の3件から **`192.168.1.151` 単独**へ
  変更 (externalTrafficPolicy: Local により応答するノードが1台に絞られたため。複数 IP を残しても
  DMS 側に接続失敗時の別 IP への再試行機能がなく、フェイルオーバーにならない)。
- `ansible-playbook playbooks/vps.yml --limit vps` で適用 (vps_proxy ロールのみ対象、nas/gitea 等
  には触れていない)。適用後、VPS 上の `getent hosts ldaps.kanidm.fickledev.com` が
  `192.168.1.151` のみを返すことを確認した。
- **my-home-network リポジトリはコミット/push していない** (作業ツリーに変更を残した状態)。

**証明書の連鎖の確認**: `ldaps.kanidm.fickledev.com:30636` に対する `openssl s_client -showcerts`
で3枚の証明書が返り、認証局と末端が分離していることを確認した。

| # | subject | issuer |
|---|---|---|
| 1 (末端) | `CN = kanidm.fickledev.com` | `O = Let's Encrypt, CN = YR2` |
| 2 (中間CA) | `O = Let's Encrypt, CN = YR2` | `O = ISRG, CN = Root YR` |
| 3 (上位CA) | `O = ISRG, CN = Root YR` | `O = Internet Security Research Group, CN = ISRG Root X1` |

末端証明書がそのまま認証局証明書として提示される構成にはなっていない (design.md の懸念どおりの
不成立パターンは再現せず、cert-manager + Let's Encrypt の通常構成で自動的に満たされることを実測で
確認)。

**3条件同時の LDAPS 接続の実測**: VPS 上で、Python `ssl.create_default_context()` (VPS のシステム
CA ストアを使用、検証は無効化していない) + `server_hostname="ldaps.kanidm.fickledev.com"` で
`ldaps.kanidm.fickledev.com:30636` へ TLS 接続し、`mail-ldap-search` サービスアカウントの
`dn=token` bind (資格情報は `MAIL_LDAP_SEARCH_PASSWORD`、SSH の暗号化 stdin 経由でのみ渡し、
コマンドライン引数・環境変数・ログのいずれにも値を残していない) を行った。

- TLS: `TLSv1.3`, `TLS_AES_256_GCM_SHA384`。peer cert subject: `commonName = kanidm.fickledev.com`。
- bind resultCode: **0 (success)**。

「認証局が発行した証明書」(上記チェーン確認)・「クラスタ上で稼働する認証基盤」(本番 Kanidm、
k3s 上の実 Pod)・「tailnet を経由する経路」(下記ルート確認) の3条件を同一の接続で同時に満たした。

**通信が tailnet に閉じていることの実測**: VPS 上で `ip route get 192.168.1.151` の結果は
`192.168.1.151 dev tailscale0 table 52 src 100.109.6.7`。`ip route show` (メインテーブル) に
`192.168.1.0/0` 宛の経路は存在せず (`none-in-main-table`)、`tailscale0` 経由の policy routing
(table 52) のみが唯一の経路であることを確認した。`tailscale status --json` で OPNsense の
`AllowedIPs` に `192.168.1.0/24` が含まれることを確認済み (`iac-hygiene-remediation` が確立した
既存の subnet route であり、本タスクで新設していない)。

### 裏が取れなかった点 / 運用者の判断が要る点

- k3s の NetworkPolicy コントローラ (kube-router) が「有効に起動している」ことは journalctl の
  ログで確認したが、その実装の完全性 (例えばフラグメント化したパケットや特殊なトラフィックに
  対する挙動) までは検証していない。今回の実測は通常の TCP 接続に対する許可/拒否の実測に限る。
- `vps_static_dns_overrides` を1ノードのみに絞ったことで、`k3s-agent-minipc` の障害時
  (ノード停止、Pod の再スケジュール失敗等) は LDAPS 到達性そのものが失われる。3ノード冗長から
  単一ノードへ後退したトレードオフであり、可用性を重視するなら Pod の nodeAffinity を外して
  別ノードでも起動できるようにしたうえで、NetworkPolicy 側の CIDR 許可だけで tailnet 限定を担う
  設計 (今回は Local policy と NetworkPolicy を両方使う設計にしたが、NetworkPolicy 単独でも
  CIDR ベースの拒否は成立しうる。ただし Cluster policy 下での cross-node 転送時は kube-proxy が
  送信元 IP を中継ノードの IP に SNAT するため、NetworkPolicy の CIDR 判定が正しく機能しなくなる
  ことを設計段階で確認済み。単独ノードでの運用と可用性のトレードオフは運用者の判断が要る)。
- `terraform/cloudflare_dns.tf` の `kanidm_ldaps_a_records` (公開 DNS、3ノード分) は今回更新して
  いない。実際の名前解決には使われていない (VPS は `/etc/hosts` 上書きが優先) ため機能的な影響は
  ないが、3ノードを指す記述と実態 (1ノードのみ応答) が食い違ったまま残っている。整合させるか
  どうかは運用者の判断とする。

## タスク5.1/5.2/5.3/5.4: メールボックスの格納と取得 (本番)

前任者が構築した `gitops-apps` commit `c7172d6`/`3a6d564` (名前空間 `mailbox`、`Deployment/dovecot`、
`PVC/mailbox-data`) を土台に、5.1 の未検証条件の検証、5.2 (配送・取得の公開)、5.3 (認証と静的識別子)、
5.4 (容量確認) を構築・実証した。実装はすべて `gitops-apps` へ commit/push 済み (最終 `91dc5a8` 以降、
直近の CA 証明書修正まで含め計 17 commit)。並行して稼働していた別エージェントの残骸として
`runAsNonRoot: true` のみで `runAsUser` を指定しない設定が残っており、kubelet が
`CreateContainerConfigError` (非numeric な image user `vmail` を検証できない) で起動を拒否していた。
`runAsUser: 1000` / `runAsGroup: 1000` / `supplementalGroups: [101]` (`vmail` が属する `ssl-cert`
グループ。Docker の `USER` 指令が行う initgroups 相当を明示的に再現) を明示して解消した。

### 5.1: 未検証だった3条件の検証

**1. Maildir形式である根拠**: `doveconf mail_driver` の実測値が `maildir` であることを確認した
うえで、`doveadm save -u <user>` で実際に配送テストを行い、生成されたファイルが
`/srv/vmail/<user>/mail/<hash>/new/1788420949.M418076P41.dovecot-<pod>,S=73,W=78` という
Maildir 標準のユニークファイル名 (タイムスタンプ.M<マイクロ秒>P<pid>.ホスト名,S=サイズ,W=サイズ)
であることを直接確認した。`mailbox_list_layout = index` (Dovecot 2.4 の既定) により各メールボックス
は不透明なハッシュ名のディレクトリに割り当てられるが、そのディレクトリ配下の `cur`/`new`/`tmp` と
メッセージ単位のファイルという Maildir の本質的な構造 (tmp→new の rename による不可分な配送) には
影響しない。

**2. 単一の書き込み側であることの帰結確認**: `Deployment/dovecot` は `replicas: 1`、
`strategy: Recreate`、PVC は `accessModes: ReadWriteOnce`、`storageClassName: local-path`
(ネットワークファイルシステムではない) であることを構成から確認した。`doveconf lock_method` の
実測値は `fcntl` (ローカルファイルシステム向けの既定値) であり、NFS 向けに推奨される `dotlock` 等
の代替方式への切り替えを構成に含めていない。この4点の組み合わせ (単一レプリカ・Recreate・RWO・
ローカルストレージ・既定ロック方式) により、複数プロセスによる同時書き込みが成立しない状態を
構造的に確保している。

**3. 注釈付きPVC定義を一時的に外しても永続ボリュームが削除されないことの検証 (最も危険な検証)**:
本番の `mailbox-data` を直接使う前に、まず使い捨てPVC `mailbox-data-test` (同一の
`argocd.argoproj.io/sync-options: Prune=false,Delete=false` 注釈) を `apps/mailbox/` に追加し、
定義をkustomizationから外したうえで実際の同期結果を確認した。ArgoCDの同期結果は
`status: PruneSkipped`、`message: "ignored (no prune)"` であり、prune対象と判定されつつも実際には
削除されないことを実測した (`requiresPruning: true` かつ生存)。この事前確認のうえで、使い捨て
PVCを削除・後片付けしてから本番の `mailbox-data` で同一の手順を実施した。

| 時刻 (UTC) | 操作 |
|---|---|
| 06:33:00 | `pvc.yaml` をkustomizationのresourcesから除外するcommitをpush |
| 06:33:07 | ArgoCDの同期操作が完了 (phase: Succeeded)。`mailbox-data` の同期結果は `status: PruneSkipped`、`message: "ignored (no prune)"` |
| 06:34:11 | `pvc.yaml` を再度resourcesへ追加するcommitをpush (定義除外の実質的な露出時間: 71秒) |
| 06:34:16 | 再同期が完了、`Application/mailbox` が `Synced`/`Healthy` に復帰 |

`mailbox-data` の `PersistentVolumeClaim` UID (`54c8818c-d1cb-4a4a-a52b-a61ca97a38b8`) は本検証の
前後で不変であり、実体は一度も削除されていないことを確認した。検証時点でメールボックスは空だった
(5.3の実証で使い捨てユーザーのテストメッセージを配送・確認後にexpungeで削除済み)。

Dovecotの `1/1 Running`、`ReplicaSet` 1本、`argocd.argoproj.io/sync-options: Prune=false,Delete=false`
注釈の存在は前任者の構築時点で確認済みであり、本タスクで改めて確認した。

### 5.2: 配送の受け口と取得の終端の公開

配送規約 (LMTP、`lmtps`、イメージ既定で `ssl=yes` 固定) と取得規約 (IMAP、`imaps`) の両方を、
kanidmのLDAPS公開 (タスク4.1) と同一の構成パターン (`Service` type `NodePort` +
`externalTrafficPolicy: Local` + `NetworkPolicy` によるtailnet CGNAT/Pod CIDR限定) で公開した。
Dovecotの `dovecot.conf` は既定で `ssl_server { cert_file = /etc/dovecot/ssl/tls.crt;
key_file = /etc/dovecot/ssl/tls.key }` を参照するため、cert-manager発行のワイルドカード証明書
(`tls-fickledev-com`、cert-manager名前空間) をReflector経由で `mailbox` 名前空間へ複製し
(`apps/cluster-issuer/wildcard-certificate.yaml` の複製先一覧に `mailbox` を追加)、そのパスへ
マウントするだけで済んだ (Dovecot側の証明書設定を上書きしていない)。

**公開ポート**: `imaps` (containerPort 31993 → Service port 993 → NodePort 30993)、
`lmtp` (containerPort 31024 → Service port 24 → NodePort 30024)。平文 `imap` (31143) は
NodePort/NetworkPolicyの対象に含めず、外部には公開していない。

**tailnet限定の実測 (肯定側)**: VPS (`100.109.6.7`、tailnet経由) から
`192.168.1.151:30993`・`192.168.1.151:30024` の双方へ `openssl s_client` でTLS接続し、
`subject=CN = *.fickledev.com`、`Verify return code: 0 (ok)` を確認した。

**tailnet限定の実測 (否定側)**: `k3s-server` (`192.168.1.150`、DMZローカル、tailnet非経由) から
同じ2ポートへ `/dev/tcp` で接続を試みたところ、いずれも `Connection refused` で拒否された。

### 5.3: 認証と静的な識別子

**認証の構成**: `passdb ldap { ldap_uris = ldaps://ldaps.kanidm.fickledev.com:3636; bind = yes;
bind_userdn = spn=%{user},app=mail,dc=kanidm,dc=fickledev,dc=com; passdb_ldap_filter = (spn=%{user}) }`
(bind方式、検索は行わない。VPS側 (タスク6) と同一のbind DNテンプレート形式)。userdbは
`userdb static { fields { uid = vmail; gid = vmail; home = /srv/vmail/%{user} } }` とし、
メールボックスの位置・所有者の識別子をKanidmから取得しない (`%{user}` はbindに使ったログイン名
そのものであり、LDAP属性の取得ではない)。割当量は `quota "User quota" { quota_storage_size = 1G }`
(利用者1名を前提に一律1GiB)。

**クラスタ内で完結する接続の実現**: Kanidmの `Service/kanidm` のClusterIP
(`10.43.86.123`、名前空間 `kanidm`) は安定だが、DNS名 `kanidm.kanidm.svc` はKanidmが提示する
証明書のSAN (`kanidm.fickledev.com` / `ldaps.kanidm.fickledev.com`) に含まれないため直結すると
証明書検証が失敗する。当初Pod単位の `hostAliases` で `ldaps.kanidm.fickledev.com` を
ClusterIPへ割り当てたが、**Dovecotの認証用LDAPクライアント (libldap) は非同期の内部リゾルバを
使っており `/etc/hosts` を参照しない**ことを実機で確認した (`getent hosts`・`openssl s_client` は
`hostAliases` だけで解決できたが、`doveadm auth test` は一貫して `internal auth failure` /
`code=temp_fail` になった)。k3s標準のCoreDNSカスタム拡張点
(`configmap/coredns-custom`、名前空間 `kube-system`、Corefileの `import
/etc/coredns/custom/*.override` / `*.server`) を使い、実際のDNS応答としてClusterIPを返す構成
(`apps/coredns-custom/`) に切り替えた。メインのCorefileは既に `hosts /etc/coredns/NodeHosts {}`
を持つため、同一Server Block内で `hosts` プラグインを二重使用すると
`this plugin can only be used once per Server Block` でreloadそのものが失敗する
(reload失敗時は直前の設定のまま無言で動き続けるため検知しにくい、実機で確認)。
`ldaps.kanidm.fickledev.com:53 { hosts { ... fallthrough } }` という独立したServer Blockを
`.server` として `import` することで回避した。CoreDNS Podの再起動 (削除→自動再作成) 後、
解決が実際に反映されることを確認した。

DNS解決を修正した後もDovecot固有の別の失敗が残った: `auth_debug = yes` を一時的に有効化した
verboseログで `TLS: peer cert untrusted or revoked (0x42)` を確認した。同一コンテナの
`openssl s_client` はOpenSSLの既定CAストアで検証に成功しており、**libldapはOpenSSLの既定CAストアを
自動継承しない**ことが分かった。環境変数 `LDAPTLS_CACERT` (OpenLDAP標準) をコンテナに設定しても
Dovecotの認証プロセスには伝播せず解消しなかった (Dovecotのプロセスモデルが環境変数を
そのまま子プロセスへ渡していないとみられる)。最終的に、libldapが起動時に直接読み込む
OpenLDAP標準の設定ファイル `/etc/ldap/ldap.conf` (`TLS_CACERT
/etc/ssl/certs/ca-certificates.crt`) をConfigMapから供給する方式で解消した。この際、
同一ConfigMapの全キーをそのまま `/etc/dovecot/conf.d/` へマウントすると、Dovecot自身が
`ldap.conf` をconf.d配下の自分の設定ファイルとして誤って読み込みFatalになった
(`Expecting '{'`) ため、`configMap.items` で明示的に分離した専用ボリュームとして
`/etc/ldap/` へマウントした。

**アプリケーションパスワードと主クレデンシャルの実測 (要件2.4/4.4)**: 検証用に使い捨ての
Kanidm人物アカウントを作成し (`mail_users` グループへAPI経由で追加、検証後に削除・
グループを0人に復帰)、Kanidmの資格情報更新セッションAPI (`/v1/person/{id}/_credential/
_update_intent` → `/v1/credential/_exchange_intent` → `/v1/credential/_update`) で主資格情報
(パスワード + TOTP、`mail_users` のアカウントポリシー `credential_type_minimum: any` は
アプリケーションパスワード発行を許すが、利用者自身のログインセッション確立自体は
`idm_all_persons` 側の既定ポリシーによりMFAを要求する) を設定し、`/v1/auth`
(`passwordmfa` 機構) で自分自身の認証済みセッションを確立した。管理者トークン (Terraform用
サービスアカウント、`idm_admins` 所属) でアプリケーションパスワードの代理発行
(`/scim/v1/Person/{id}/Application/_create_password`) を試みたところ `403 accessdenied` で
拒否され、要件2.13 (代理発行が成立しない) を直接確認した。利用者自身の再認証済みセッション
(`/v1/reauth` による特権昇格。ログイン直後のトークンは `purpose.readwrite.expiry: null` だが
再認証後は短い有効期限付きの昇格状態になる) からは同エンドポイントが成功し、
アプリケーションパスワードを取得できた。

このアプリケーションパスワードと主クレデンシャルの双方を、上記の本番Dovecotに対して
`doveadm auth test` で実測した。

| 資格情報 | doveadm auth test |
|---|---|
| アプリケーションパスワード (`app=mail`) | `passdb: mailtest auth succeeded` |
| 主クレデンシャル | `passdb: mailtest auth failed` |

検証後、使い捨てユーザーが配送した1通のテストメッセージ (5.4の検証も兼ねる) を
`doveadm expunge` で削除し、Kanidm側の人物アカウントを削除した (`mail_users` は0人に復帰)。

### 5.4: 容量確認

`doveadm quota get -u <user>` で現在の使用量を取得できる状態にした (5.3のquota設定に依存)。
実測: 使い捨てユーザーへ73バイトのテストメッセージを配送した直後、`STORAGE` が `0` から `1`
(KiB、切り上げ)、`MESSAGE` が `0` から `1` に変化することを確認し、`doveadm expunge` 後に
双方が `0` へ戻ることを確認した。静的な設定値の存在だけでなく、実際の使用量増減に追随することを
実測した。

### 裏が取れなかった点 / 運用者の判断が要る点

- `mailbox-data` の使い捨て検証で作成したKanidm人物アカウント (`mailtest`) はKanidmの
  リサイクルビン機構により論理削除の状態で残っている (即時の完全削除ではない)。運用上問題
  ないと判断したが、完全消去のタイミングは運用者の判断に委ねる。
- Dovecot 2.4系はドキュメントが未整備な部分が多く (`quota`ブロックの構文、`mail_plugins`の
  ブロック形式、`ldap_*`設定の一部)、本タスクでの発見の多くは公式ドキュメントではなく
  doveconfのFatalエラーメッセージや実機の`auth_debug`ログから得た。主要版が更新された際に
  同様の再検証が必要になる可能性が高い (design.md MailboxBackendのIntegration注記が
  想定している版更新時の追随の対象に、このLDAP/CoreDNS/CA証明書関連の詳細も含めるべきである)。
- CoreDNSのカスタム上書き (`apps/coredns-custom/`) はクラスタ全体に影響する共有リソースであり、
  今後 `ldaps.kanidm.fickledev.com` 以外の名前解決にも影響しうる箇所である。追加のカスタム
  ゾーンが必要になった場合、同一ConfigMapの別キー (`*.server`) として追加できる。

## タスク6.1/6.2 実装記録 (2026-09-03)

VPS上に `ansible/roles/mailserver` ロールを新設し、実際にVPSへ適用してdocker-mailserver
v16.0.0を稼働させ、submissionの認証 (Dovecot passdb、bind DNテンプレート方式) を実機で
検証した。以下は設計・研究時点では判明していなかった実装上の発見。

### LDAPS接続先ポートの誤り (VPS側はNodePort、k3s側Dovecot設定のService経由ポートとは異なる)

k3s側Dovecotの `passdb ldap` は `ldap_uris = ldaps://ldaps.kanidm.fickledev.com:3636` を
用いるが、これはCoreDNSのカスタム上書きでClusterIPへ解決した上でのService経由ポート (`3636`)
である。VPSはクラスタ外からノードの実アドレス (`192.168.1.151`) へ直接つなぐため、Service
ポートではなくNodePort (`30636`、`kubectl get svc -n kanidm` で確認) を使う必要がある。3636で
試すと `Connection refused` になることを実機で確認した (Kanidmの `Service/kanidm` は
`3636:30636/TCP` としてNodePortを公開している)。

### VPSコンテナのDNS解決: Tailscaleのアンチリバインド対策を回避する必要がある

`ldaps.kanidm.fickledev.com` は公開DNS上、実在するプライベートアドレス (k3sの各ノード
`192.168.1.150/.151/.152`) を指す。ホストのVPS本体は `/etc/hosts` の静的登録
(`vps_proxy` の `vps_static_dns_overrides`) でTailscaleのDNSリバインディング対策を
回避しているが、Dovecotの内部DNSクライアントは (段階5でk3s側について確認済みの通り)
`/etc/hosts` を参照しない。docker-mailserverはDockerコンテナであり、ホストの`/etc/hosts`
とは独立した名前解決を行うため、同じ問題がVPS側でも起きうると想定し、コンテナのDNSサーバを
Tailscaleの経路を通らないパブリックリゾルバ (`1.1.1.1`、`1.0.0.1`) に直接向けた
(`compose.yaml.j2` の `dns:`)。これにより公開DNSの複数Aレコード (3ノード分) がそのまま
コンテナへ返る前提とした。

実機での結果: `getent hosts` は3ノード全てを返すが、doveadmでの実際のbindは正常に成立
した (`libldap`が複数アドレスを順に試行し、応答するノード (`.151`) への接続に成功したと
みられる)。ホスト側のような単一IPへの静的固定は行っていないが、現状は実用上問題なく動作する。
将来 `.151` 以外のノードでKanidm Podが起動しなくなった場合の切り分けが難しくなる点は残存
リスクとして記録する。

### CA証明書の配置 (要件3.4/4.10): k3s側と同一の手法がそのまま有効

Dovecotの認証用LDAPクライアント (libldap) は環境変数 `LDAPTLS_CACERT` を認識せず、OpenLDAP
標準の `/etc/ldap/ldap.conf` (`TLS_CACERT /etc/ssl/certs/ca-certificates.crt`) で解決する
という段階5の発見は、VPS側 (docker-mailserver) でもそのまま成立することを実機で確認した。
Kanidmの証明書はLet's Encrypt (公開CA) が発行するため、コンテナ既定のCAバンドルで検証でき、
専用のCA証明書ファイルを別途用意する必要はない。`/etc/ldap/ldap.conf` はdocker-mailserverの
起動処理が触れないパスであるため、単純なバインドマウントで問題なく反映される
(dovecot.cfやauth-ldap.conf.extのような「起動処理が書き込もうとするパス」特有の
"Device or resource busy" 制約には当たらない)。

### ACCOUNT_PROVISIONER=LDAPは6.2の時点では設定しない

docker-mailserverの `ACCOUNT_PROVISIONER=LDAP` は、Dovecotの認証だけでなくPostfix側の
`virtual_alias_domains` 等 (ldap-aliases.cf / ldap-groups.cf / ldap-users.cf /
ldap-domains.cf) も既定のダミーbind DN (`cn=admin,dc=example,dc=com`、`LDAP_BIND_DN`
未設定時の既定値) で自動的にLDAP化してしまう。このダミーDNではKanidmへのbindが
resultCode 80 (Other error) で失敗し、Postfixの`trivial-rewrite`がこの失敗を
接続断 ("NOQUEUE: lost connection after MAIL") として扱うため、**submission全体が
機能しなくなる**ことを実機で確認した。宛先照合を検索用サービスアカウントで構成する
task 6.3が完了するまでは `ACCOUNT_PROVISIONER=LDAP` を設定せず、Dovecotのpassdbは
`dovecot.cf` (local.conf) の上書きのみで自己完結させる。

### FILE方式の既定では「アカウントが1件も無いと120秒でシャットダウンする」制約がある

`ACCOUNT_PROVISIONER=LDAP` を設定しない場合、docker-mailserverは既定でFILE方式の
`postfix-accounts.cf` を前提とし、1件もアカウントが定義されていないと起動から120秒で
Dovecotをシャットダウンすることを実機で確認した (ログ: "You need at least one mail
account to start Dovecot")。submissionの認証は独自のDovecot passdb上書きが担うため
このFILEアカウントは実際には参照されないが、起動ゲートを満たすためだけの不使用の
プレースホルダアカウントを1件 (`placeholder@<hostname>|{PLAIN}<ランダム値>`) 配置する
措置を取った。Ansibleロールは `creates` で初回のみ生成し、2回目以降の適用で変更を
報告しない。

### submissionのTLS: task 6.4より前は暫定の自己署名証明書を要する

`SSL_TYPE` を未設定のままにするとdocker-mailserverはSMTP/submissionをSTARTTLS非対応
(平文のみ) で起動し、"!! INSECURE !!" の警告を出す。submissionの認証はTLS (STARTTLS)
経由が前提であり、6.2の受入基準 (アプリケーションパスワードで送信できることの実測)
を満たすにはTLSが必須のため、Ansibleロールが暫定的な自己署名証明書 (`openssl req -x509`、
397日、ホスト名をCNとする) を生成し `SSL_TYPE=self-signed` で使用する。メール用ホスト名の
実証明書の供給と自動更新反映 (要件4.7/4.13) はtask 6.4の対象であり、この暫定証明書は
6.4で実証明書に置き換わる前提の一時的な措置である。

### 6.2の受入基準の実測結果

検証用のKanidm人物アカウント (`mailverify0903`) をAPI経由で作成し、`mail_users` グループへ
追加、主資格情報 (パスワード+TOTP) を資格情報更新セッションAPIで設定、`/v1/auth`
(passwordmfa) で自分自身の認証済みセッションを確立、`/v1/reauth` で特権昇格したうえで
`/scim/v1/Person/{id}/Application/_create_password` によりアプリケーションパスワードを
発行した。

| 検証方法 | アプリケーションパスワード | 主クレデンシャル |
|---|---|---|
| 生のLDAPv3 BindRequest (bind DNに`app=mail`を含む) | resultCode 0 | resultCode 49 |
| 生のLDAPv3 BindRequest (bind DNに`app=mail`を含まない、アプリケーションパスワードを使用) | resultCode 49 | - |
| `docker exec mailserver doveadm auth test` | `auth succeeded` | `auth failed` |
| 実際のSMTP submission (587、STARTTLS、AUTH PLAIN、MAIL FROM/RCPT TO/DATA) | `AUTH: OK` / `SEND: queued` | `AUTH: FAILED (535 5.7.8)` |

`doveconf -n` で `passdb ldap {}` (bind_userdnテンプレート、ldap_uris、ldap_base) と
`userdb static {}` の双方が反映されていること、既定の `auth-ldap.conf.ext` が空に
置き換わっていることを確認した。

認証基盤へ接続できない場合の挙動は2通りの方法で確認した。1つは構築初期段階での
ポート誤り (3636、待受なし) による意図しない実測で、`dovecot: auth: Error:
ldap(...): Can't connect to server` がログに記録され `code=temp_fail` で認証は
成立しなかった。もう1つは検証のため `iptables -I DOCKER-USER -d 192.168.1.151
-p tcp --dport 30636 -j DROP` でVPSからNodePortへの経路を意図的に遮断し、
`docker exec mailserver timeout 25 doveadm auth test` を実行したところ、25秒の
上限内で認証は成立せず (`timeout`によるexit 124)、遮断ルールは検証直後に削除して
復元を確認した (`iptables -L DOCKER-USER -n` が空であることを確認)。いずれの方法でも
接続不能時に認証が成立しないことが確認できた。

検証に用いたKanidm人物アカウントは検証後に削除し (`DELETE /v1/person/mailverify0903`、
リサイクルビンへの論理削除)、`mail_users` グループのメンバー数が0件に戻ったことを
`GET /v1/group/mail_users/_attr/member` で確認した。

### ネットワークフィルタとVPS上の旧中継設定

`ansible/roles/vps_proxy/defaults/main.yml` の `vps_proxy_filter_allow_tcp_ports`
(25/80/443/465/587/993/4190) は、本タスク着手前の時点で既にメール用ポートを含んだ状態
だった (`iac-hygiene-remediation` 側の直近のエッジ整合作業で反映済み)。143と9100は
コメントで明示的に除外されている。したがって6.1のためにこのファイルへの追加変更は
不要だった。VPS上の `/etc/haproxy/haproxy.cfg` (mtime 2026-09-02、`vps_proxy` ロールの
最新適用結果) を確認したところ、メール関連のfrontend/backendは0件で、旧メール基盤
(mailu時代) の凍結設定は既に消えており、復活していないことを確認した
(本タスクの `mailserver` ロールはhaproxy.cfgを一切変更しない)。

### 冪等性の確認

`ansible-playbook playbooks/mailserver.yml --limit vps` を連続して2回適用し、2回目は
`changed=0` であることを確認した。前提変数 (`mailserver_ldap_search_password` /
`mailserver_dkim_private_key`) を空文字列で上書きして適用すると、最初の
`assert` タスクで即座に失敗し (`ok=1, changed=0`)、以降のタスク (ディレクトリ作成や
コンテナ起動を含む) は一切実行されないことを確認した。

### 裏が取れなかった点 / 運用者の判断が要る点

- コンテナのDNSを `1.1.1.1`/`1.0.0.1` に固定する方式は、`ldaps.kanidm.fickledev.com`
  の複数A レコードのうち応答するノードが変わった場合にlibldapの複数アドレス試行が
  常に有効かどうかまでは確認していない (今回は`.151`が応答し、実測上は問題なく
  bindが成立した)。ホスト側のような単一IP固定に揃えるかどうかは運用者の判断とする。
- submissionのTLS証明書は暫定の自己署名であり、task 6.4で実証明書に置き換わるまでの
  間、メールクライアントは証明書検証エラーになる。6.2の時点では意図した状態であり、
  受入基準 (アプリケーションパスワードでの送受信) の検証自体はTLS証明書検証を無効化した
  テストクライアントで行った。
- `postfix-accounts.cf` のプレースホルダアカウントは、task 6.3で宛先照合が
  LDAP化された後も残置してよいか、それとも削除して構わないかは6.3側の設計判断に委ねる
  (現状はDovecotの認証にもPostfixの宛先照合にも一切参照されない不使用のエントリ)。

## タスク6.3 実装記録 (2026-09-03)

前任のエージェント (セッション断絶) が `ansible/roles/mailserver/` に対して、宛先照合と配送先の構成一式をディスク上に実装し、実際に VPS へ適用済みの状態で本タスクを引き継いだ。本節では、引き継ぎ時点で既に入っていた構成と、本タスクで追加・是正した内容を区別して記録する。`my-home-network` リポジトリ側は本タスクを通じて commit/push しない方針のため、`ansible/roles/mailserver/` および `ansible/playbooks/mailserver.yml` は git 上は未追跡のまま (ディスク上のみ) である。

### 着手時点で既に入っていた構成 (前任者の実装、実機に適用済みだった)

- `ansible/roles/mailserver/templates/compose.yaml.j2`: `ACCOUNT_PROVISIONER=LDAP` と `LDAP_SERVER_HOST` / `LDAP_SEARCH_BASE` / `LDAP_BIND_DN` (`dn=token`) / `LDAP_BIND_PW` / `LDAP_QUERY_FILTER_USER` / `LDAP_QUERY_FILTER_DOMAIN` / `LDAP_QUERY_FILTER_ALIAS` / `LDAP_QUERY_FILTER_GROUP` が設定済みだった。
- `postfix-main.cf.j2`: `virtual_transport = lmtp:[192.168.1.151]:30024` (格納側 LMTP、ホスト名を使わず角括弧つきの直接 IP 指定)。
- `postfix-master.cf.j2`: `lmtp/unix/lmtp_tls_wrappermode=yes` / `lmtp_tls_security_level=encrypt` (格納側 LMTP への暗黙 TLS)。
- `tasks/main.yml`: `ACCOUNT_PROVISIONER=LDAP` 化に伴い、6.1/6.2 で置いていた FILE 方式起動ゲート用のプレースホルダアカウント (`postfix-accounts.cf`) を明示的に削除するタスクが既にあった。
- 実機 (`docker inspect mailserver` / `postconf`) で確認したところ、これらは既にコンテナへ反映済みで、`virtual_mailbox_domains = /etc/postfix/vhost, ldap:/etc/postfix/ldap-domains.cf`、`virtual_mailbox_maps = ldap:/etc/postfix/ldap-users.cf` (いずれも docker-mailserver が `LDAP_QUERY_FILTER_*` から自動生成)、`smtpd_recipient_restrictions` に `reject_unauth_destination` / `reject_unknown_recipient_domain` を含む状態で稼働していた。`postfix-accounts.cf` も既に存在しなかった。

前任者が gitops-apps に push した検証用コミット (`335d485`、mailbox dovecot を 0 レプリカにする) は本タスクの待ち行列検証を試みた痕跡であり、そのままセッションが断絶して `replicas: 0` が放置されていた。メインセッションが `d31e9ef` で `replicas: 1` に復旧済みだったため、本タスク着手時点で mailbox は正常 (`ready=1`) だった。Kanidm 側にも前任者の使い捨て検証アカウント `mail-6-3-verify` (`mail` 属性設定済み、`mail_users` に所属) が削除されず残置していたことを本タスクの中で発見し、削除した (下記)。

### 本タスクで追加・是正した内容

**1. `net.ipv4.ip_forward` の是正 (想定外の事象、EdgeMailServer と `iac-hygiene-remediation` の相互作用)**: `vps_proxy` ロールには `net.ipv4.ip_forward` を `0` に固定するタスクがあり、コメント上は「nginx/haproxy はユーザー空間で完結するため IP フォワーディングを使わず、これを必要とするのは凍結中の xrayvpn のみ」という前提だった。この前提は `mailserver` ロール (task 6.1) の追加により崩れている。docker-mailserver のコンテナはブリッジネットワーク経由で外部 (DNS リゾルバ、格納側 LDAPS/LMTP の NodePort) へ到達する際に、カーネルの `FORWARD` チェーンと Docker の NAT を通過する必要があり、これには `net.ipv4.ip_forward=1` が要る。fail2ban 対応 (task A) のために `ansible-playbook playbooks/vps.yml` を適用した際、このタスクが `ip_forward` を `0` へ引き戻し、mailserver コンテナの DNS 解決 (`ldaps.kanidm.fickledev.com` が名前解決不能) と LDAPS/LMTP への疎通が同時に失われた (実機ログ: `dict_ldap_connect: Unable to bind to server ldaps://ldaps.kanidm.fickledev.com:30636 ... Can't contact LDAP server`、宛先照合が全件 `451 4.3.0 Temporary lookup failure` になった)。ホスト自身は同じ 1.1.1.1/192.168.1.151 への到達に問題がなかったため、コンテナ内 (`docker exec mailserver ...`) からの疎通確認で原因を特定した。`ansible/roles/vps_proxy/tasks/main.yml` の該当タスクを `value: '1'` に変更し (`Ensure IPv4 packet forwarding is enabled ...` に改名)、コメントも mailserver コンテナの要件を反映する内容に書き換えた。実機で `sysctl -w net.ipv4.ip_forward=1` により即時復旧を確認したうえで、ロールの恒久修正を適用し、2 回連続適用でこのタスクが `changed` を報告しないことを確認した (vps.yml 全体としては無関係な `Add or update current SSH host key for current host` タスクが `localhost` に対して毎回 changed を報告するが、これは本タスクと無関係の既存動作)。

**2. 宛先照合の実測 (要件2.7/6.8 の受入基準)**: VPS の docker-mailserver に対し、未認証で SMTP (25番) の生の会話 (`MAIL FROM` → `RCPT TO`) を送って実測した。

| ケース | RCPT TO 応答 |
|---|---|
| 存在する宛先 (`mail_users` 所属の検証用アカウント) | `250 2.1.5 Ok` |
| 存在しない宛先 | `550 5.1.1 <...>: Recipient address rejected: User unknown in virtual mailbox table` |
| 認証なしの第三者宛 (`example.com`) | `554 5.7.1 <...>: Relay access denied` |

いずれも **RCPT TO の時点** (DATA 受理前) で応答しており、要件が求める「受理の前の照合」「受理後に返送する経路を作らない」を満たす。第三者宛の拒否も 4xx の一時応答ではなく `554` の恒久応答であり (`smtpd_recipient_restrictions` の `reject_unauth_destination` が先に評価されるため、`smtpd_relay_restrictions` の `defer_unauth_destination` より強い拒否になっている)、中継を許可しない要件を満たす。

**3. 待ち行列と復旧後の配送の実測 (要件5.4 / design.md 統合検証)**: gitops-apps の `apps/mailbox/deployment.yaml` を `replicas: 0` → commit → push し、ArgoCD の自動同期で mailbox Pod が消えたこと (`kubectl get pods -n mailbox` で確認)、格納側 LMTP (`192.168.1.151:30024`) への TCP 接続が `Connection refused` になることを確認したうえで、正しいヘッダ (`Date`/`Message-ID` を含む RFC 5322 準拠のメッセージ。ヘッダを省略した最初の試行は amavis の `BAD-HEADER` 判定でバウンス扱いになり、待ち行列検証にならなかった。amavis / opendkim / opendmarc は task 6.5 で置き換える予定の既定有効な旧来機構であり、現時点ではまだ有効なままであることを実機で再確認した) の宛先ごとに存在する宛先へ SMTP でメールを送信した。

- 送信は `250 2.0.0 Ok: queued as ...` で受理された。
- `docker exec mailserver mailq` で待ち行列に残り、理由が `connect to 192.168.1.151[192.168.1.151]:30024: Connection refused` であることを確認した (メールは破棄されず待ち行列に留まった)。
- `apps/mailbox/deployment.yaml` を `replicas: 1` に戻して commit → push し、ArgoCD の同期で Pod が `1/1 Ready` に復帰したことを確認した後、格納側 LMTP への TCP 到達を再確認し、`postqueue -f` で即時再試行を発火させた。
- ログに `status=sent (250 2.0.0 <...> ... Saved)` (Dovecot LMTP 自身の受理応答) が記録され、`mailq` が空になったことを確認した。破棄されず、復旧後に配送されることを実測した。

**4. `ACCOUNT_PROVISIONER=LDAP` とプレースホルダアカウント**: 上記のとおり、有効化とプレースホルダアカウントの削除は着手時点で既に実装・適用済みだった。本タスクでは実機の `ls /opt/mailserver/config/postfix-accounts.cf` (存在しない) と `docker inspect` の環境変数を確認し、意図どおりであることを再確認したのみで、追加の変更は行っていない。

**5. コンテナの DNS (1.1.1.1/1.0.0.1) の見直し**: 引き継ぎ時の申し送りに「LMTP の宛先を解決する必要が出るので見直す余地がある」とあったが、実際には `postfix-main.cf.j2` の `virtual_transport` は格納側 LMTP を **角括弧つきの静的 IP (`[192.168.1.151]`)** で直接指定しており、DNS 解決を一切経由しない設計になっていた (LMTP について DNS を見直す必要はそもそも生じない)。DNS が必要なのは Dovecot の LDAPS 接続 (`ldaps.kanidm.fickledev.com`) のみであり、これは 6.1/6.2 実装記録に記載のとおり 1.1.1.1/1.0.0.1 で解決させる既存方針のままで問題なく機能することを、本タスクの疎通確認 (`docker exec mailserver getent hosts ldaps.kanidm.fickledev.com` が 3 ノード分のアドレスを返す) で再確認した。変更は行っていない。

### 検証用データの後始末

- Kanidm 検証用人物アカウント `mailq0903verify` (`mail` 属性設定、`mail_users` 所属) を作成して使用し、検証後に `mail_users` のメンバーを `[]` に戻し、アカウント自体を削除した (`GET /v1/person/mailq0903verify` が `null` を返すことを確認)。
- 前任者の残置アカウント `mail-6-3-verify` も同様に削除した (削除前に `mail_users` の実メンバーが空ではなくこのアカウント 1 件だったことを発見し、削除後に空であることを確認)。
- `mail_users` グループの最終メンバー数が 0 件であることを `GET /v1/group/mail_users` で確認した。
- VPS 上の検証用スクリプト (`/tmp/smtp_test.py` 等) を削除し、待ち行列 (`mailq`) が空であることを確認した。

### 冪等性の確認

`ansible-playbook playbooks/mailserver.yml --limit vps` を連続 2 回適用し、2 回目が `changed=0` であることを確認した (`vps_proxy` 側の `ip_forward` 是正タスクについても同様に 2 回目が `changed` を報告しないことを確認済み、上記1.参照)。

### 完了可否

完了。要件2.7 (受理前の宛先照合、存在しない宛先の恒久的拒否)、5.4 (到達不能時の待ち行列保全、実際には破棄されず復旧後に配送)、6.8 (第三者中継の拒否) のいずれも実機で確認した。着手時点で構成の大部分 (LDAP 宛先照合、LMTP 配送先、TLS ラッパー) は前任者により実装・適用済みであり、本タスクで追加したのは (a) `net.ipv4.ip_forward` の恒久修正 (task A との相互作用で発覚した実際の障害の是正)、(b) 3 つの受入基準の実機検証、(c) 前任者が残置した検証用リソース (gitops-apps の replicas、Kanidm の検証アカウント) の後始末である。

### 想定外の事象と対処

- **`net.ipv4.ip_forward` の相互作用**: 上記1.のとおり。task A (fail2ban) の適用が task B (mailserver) の通信を壊すという、2 つのタスクの境界をまたぐ副作用だった。原因を実機のログと疎通確認で特定し、`vps_proxy` ロール側を恒久的に是正した。
- **amavis による待ち行列検証メッセージのバウンス**: 上記3.のとおり、ヘッダを省略した最初の検証メッセージが amavis の `BAD-HEADER` 判定でバウンスされ、バウンス通知自体が (格納側停止中のため) 待ち行列に滞留するという二重に紛らわしい状態になった。RFC 5322 準拠のヘッダを持つメッセージで送り直し、意図した検証 (元メッセージ自体の待ち行列滞留) に切り替えて解消した。
- **ArgoCD の同期反映に遅延があった**: gitops-apps への push から実際に k3s へ反映されるまで、1 回目の `replicas: 0` 反映は約 3 分、2 回目の `replicas: 1` 反映は約 5 分半を要した (通常の `timeout.reconciliation: 180s` より長い)。並行して実行されているタスク21.1 (k3s クラスタトークンのローテーション) による負荷や再起動が影響した可能性があるが、`argocd-application-controller` のログにエラーは見られず、単に反映が遅かっただけだった。mailbox の状態確認は `kubectl get` のみで行い、`replicas` の変更は gitops-apps への commit/push のみで行った (直接の `kubectl scale`/`edit` は行っていない)。最終的に `replicas: 1` / `ready=1` の状態でタスクを終えた。

### 裏が取れなかった点

- 第三者中継の拒否が `554` (恒久) になったのは `smtpd_recipient_restrictions` の `reject_unauth_destination` が `smtpd_relay_restrictions` の `defer_unauth_destination` より先に評価されたためと考えられるが、両restrictionsの評価順序の正確な仕様は docker-mailserver 側のドキュメントで確認していない (実機の応答から推測)。
- ArgoCD の同期反映が数分単位で遅延した根本原因 (アプリケーション数、コントローラの負荷、並行するクラスタ操作のいずれが支配的か) は特定していない。単発の事象であり、本タスクの受入基準には影響しなかったため深追いしていない。

## 追補: LMTP配送とIMAP認証のメールボックス位置不一致の是正 (2026-09-03)

### 原因

`gitops-apps/apps/mailbox/configmap.yaml` の `userdb static` が `home = /srv/vmail/%{user}` を無加工の `%{user}` で組み立てていた。Dovecotのuserdb変数`%{user}`はプロトコルごとに実際に渡される値の形が異なり、実機で以下の食い違いを確認した。

- LMTP配送 (RCPT TO由来) の `%{user}` は完全なメールアドレス (`someone@fickledev.com`)。
- IMAP認証の `%{user}` はアカウント名のみ (`someone`)。Kanidmのbind DNテンプレート (`spn=%{user},app=mail,dc=kanidm,dc=fickledev,dc=com`) がこの形式でしか成立しないため、Dovecotのpassdb側から見た `%{user}` はアカウント名のみに保たれる。

結果、`/srv/vmail/someone@fickledev.com/` へ配送されたメールが、`/srv/vmail/someone/` を見るIMAPログインからは不可視になっていた。

Dovecotの公式ドキュメント (userdb, https://doc.dovecot.org/2.4.2/core/config/auth/userdb.html) は「Userdb lookups are utilized for IMAP & POP3 logins, LMTP mail delivery, and doveadm commands.」と明記しており、userdbはLMTP配送とIMAP認証の双方で共通に参照される唯一の項目である。一方 `lmtp_proxy = yes` を設定しない限りLMTPの受信ではpassdbは評価されない (`lmtp_proxy` を有効にした場合のみプロキシ判定のためpassdb lookupが走る、と同ドキュメントの summaries/settings.html に明記)。本構成は `lmtp_proxy` を設定していない (既定で無効) ため、passdb (bind DNテンプレート) はIMAP認証専用であり、LMTP配送はuserdbのみで完結する。したがって、両者を揃える着地点はuserdb側であり、passdb側 (bind DNテンプレート) には触れずに解決できる。

### 是正方法とその根拠

`userdb static.home` を `%{user}` から `%{user | username | lower}` に変更した (`gitops-apps` commit `8bf32ee`)。

根拠はDovecot 2.4のSettings Variablesのフィルタ機構 (https://doc.dovecot.org/2.4.2/core/settings/variables.html、および 2.3→2.4 移行ガイド https://doc.dovecot.org/2.4.2/installation/upgrade/2.3-to-2.4.html) である。`%{user | username}` は値のローカル部 (`@`より前) を取り出すフィルタで、既に`@`を含まない値 (IMAP認証時の`%{user}`) には無害に働く。`%{user | username | lower}` の形は移行ガイドの例示 (`%{user | username | lower }`) と一致する。

`lower` を追加したのは、当該ConfigMap冒頭のコメント (18-22行目付近) が「イメージ既定値 (`mail_home = /srv/vmail/%{user|lower}`) が既に要件5.1/5.5を満たす」と記していたにもかかわらず、実際には `userdb static` がその既定値を完全に上書きしており `|lower` を伴っていなかった、という記述と実体の不整合が既にあったため。今回の修正でこの不整合も解消し、コメントも「userdb staticが既定値を上書きするため既定値自体は使われない」と実体に合わせて書き換えた。

bind DNテンプレート (`passdb ldap.bind_userdn = spn=%{user},app=mail,...`) は変更していない。上記のとおりLMTP配送の解決にpassdbは関与しないため、`%{user}`を無加工のままアカウント名のみで成立させる必要があるbind DN側に手を入れる理由がない。

### 検証結果

**是正前の記録**: Pod `dovecot-75dbb99fb7-ln7cj` (再起動0)。`/srv/vmail/` 配下に `mail-6-3-verify@fickledev.com` `mail64verify` `mail64verify@fickledev.com` `mailq0903verify@fickledev.com` `mailtest` `sender@fickledev.com` `testfile` `verify-sender@fickledev.com` が存在 (いずれも過去タスクの使い捨て検証アカウントの残骸で、対応するKanidm人物アカウントは本タスク着手前に全て削除済みであることをresearch.mdの既存記録 (タスク3.1・6.3の後始末節) で確認した。実データを持つ現行アカウントは無い)。

**適用**: `gitops-apps` へcommit `8bf32ee` をpush。ArgoCD `mailbox` Applicationが自動同期し (`sync.status=Synced`, `health.status=Healthy`)、`Recreate`戦略により新Pod `dovecot-5b6d8b6bf8-zlmjl` が起動 (再起動0)。既存の `/srv/vmail/` 配下のエントリは同一PVCのままで全て残存していることを確認した (データ損失なし)。

**LMTP配送とIMAP認証が同一パスを解決することの確認手順**: `terraform-kanidm`サービスアカウントのトークンでKanidmの生REST API (`https://kanidm.fickledev.com`、OpenAPI定義 `/docs/v1/openapi.json` および `kanidm/kanidm` リポジトリのRust実装 (`proto/src/v1/auth.rs`, `proto/src/internal/credupdate.rs`, `libs/client/src/lib.rs`) で厳密なJSON形状を確認したうえで叩いた) を用い、使い捨て検証用人物アカウント `mboxfixverify` (`mail = mboxfixverify@fickledev.com`) を作成、`mail_users`グループへ追加 (`POST .../_attr/member`、既存メンバーを保持する追加方式)、パスワード+TOTPを資格情報更新セッションAPIで設定してcommitした。続けて `mboxfixverify` 自身のセッションで `/v1/auth` (passwordmfa) ログイン → `/v1/reauth` 特権昇格 → `/scim/v1/Person/mboxfixverify/Application/_create_password` によりアプリケーションパスワードを自己発行した (タスク3.1と同じく、管理者代理発行ではなく本人セッションによる自己発行)。

1. VPS (`100.109.6.7:25`、Tailscale経由) へ未認証でRFC 5322準拠のテストメール (`Date`/`Message-ID`ヘッダあり) をSMTPで直接投入し、`mboxfixverify@fickledev.com`宛のRCPT TOが`250 2.1.5 Ok`で受理されることを確認した。
2. VPSのコンテナログ (`docker logs mailserver`、ansible経由で読み取り) で `postfix/lmtp` が `to=<mboxfixverify@fickledev.com>, relay=192.168.1.151[192.168.1.151]:30024, ... status=sent (250 2.0.0 <mboxfixverify@fickledev.com> ... Saved)` を出力したことを確認した。
3. `kubectl exec`で格納側Podの `/srv/vmail/` を確認し、`mboxfixverify` (バウンド、`@fickledev.com`を含まない) というディレクトリにメールが配送されたことを確認した。
4. ローカル端末からVPSの993番 (`100.109.6.7:993`、TLSはSNI `mail.fickledev.com` を明示しワイルドカード証明書 `CN=*.fickledev.com` の検証を有効にしたまま実施) へIMAPで接続し、ユーザー名 `mboxfixverify` (アカウント名のみ) + 発行したアプリケーションパスワードでLOGINが成立、`INBOX`を`SELECT`して`SEARCH ALL`が1件を返し、`FETCH`したSubject/Message-IDが手順1で送信したテストメールと一致することを確認した。

以上により、LMTP配送で書き込まれたメールをIMAP認証で取得できることを実機で確認した (**合格**)。

**既存メールボックスの保全確認**: 是正前後で `/srv/vmail/` 配下のエントリ一覧を比較し、既存の8エントリ (前段落) がいずれも変更・消失していないことを確認した。これらは実データを持つ現行アカウントに属さない過去の検証残骸であり、対応するKanidm人物アカウントが既に存在しない (ログインする経路が無い) ため、本タスクでは移動も削除も行わなかった。検証用に新規作成した `/srv/vmail/mboxfixverify` は、格納側Podのコンテナイメージが最小限 (`rm`/`ls`等のcoreutilsを含まない) でありPod内から削除する手段がなかったため、他の残骸と同様に残置した (Kanidm側のアカウントは削除済みのため到達経路は無い)。

**後始末**: 検証後、`mail_users`グループから `mboxfixverify` を除外 (`DELETE .../_attr/member`、指定値のみの削除で他メンバーに影響しない方式。除外後 `GET`が空を返すことを確認)、`DELETE /v1/person/mboxfixverify` で削除 (削除後の`GET`が`null`を返すことを確認)。`terraform-kanidm` (`infisical run --env=prod -- terraform plan -detailed-exitcode`、ワークスペース`kanidm-identity`) は是正前後どちらも **"No changes."** (exit code 0) であり、`mail_users`のメンバーシップ変更がTerraformの管理対象外であることと整合する結果を確認した。

**mailbox Applicationの最終状態**: `sync.status=Synced`, `health.status=Healthy`, `sync.revision=8bf32ee...`。Pod `dovecot-5b6d8b6bf8-zlmjl` の再起動回数は0。

## タスク6.5実装記録 (2026-09-03)

### 有効化・無効化した変数

`ansible/roles/mailserver/defaults/main.yml` に環境変数の宣言を追加し、当該定義を有効化状態の単一の情報源とした (要件11.5)。有効化する3変数と無効化する4変数は「1つの変更」として同一の適用に含めた。

| 変数 (defaults) | コンテナ環境変数 | 値 | 用途 |
|---|---|---|---|
| `mailserver_enable_rspamd` | `ENABLE_RSPAMD` | true→1 | 迷惑メール判定 (要件11.1) |
| `mailserver_enable_clamav` | `ENABLE_CLAMAV` | true→1 | ウイルス検査 (要件11.1、段階0の実測によりゲート通過済み) |
| `mailserver_enable_fail2ban` | `ENABLE_FAIL2BAN` | true→1 | 認証の反復失敗に対する遮断 (要件11.1) |
| `mailserver_enable_opendkim` | `ENABLE_OPENDKIM` | false→0 | 旧来のDKIM署名を無効化 (要件11.2) |
| `mailserver_enable_opendmarc` | `ENABLE_OPENDMARC` | false→0 | 旧来の認証結果の記録を無効化 (要件11.3) |
| `mailserver_enable_policyd_spf` | `ENABLE_POLICYD_SPF` | false→0 | 旧来の送信者方針の検査を無効化 (要件11.3) |
| `mailserver_enable_amavis` | `ENABLE_AMAVIS` | false→0 | 旧来のメッセージ検査の中継を無効化 (要件11.3) |
| `mailserver_rspamd_check_authenticated` | `RSPAMD_CHECK_AUTHENTICATED` | true→1 | 認証済みの送信への検査適用を明示宣言 (要件11.7) |

DKIM署名の担当をrspamdへ一本化 (要件11.2)。秘密鍵 (`mailserver_dkim_private_key`、Infisical `MAIL_DKIM_PRIVATE_KEY`、タスク2.1/2.2でrspamd向けに生成済みのRSA PKCS#1 PEM) をrspamdの既定パス規約 (`/tmp/docker-mailserver/rspamd/dkim/<domain>-<selector>.private`、selector固定値 `mail`) に配置し、`templates/rspamd-dkim-signing.conf.j2` で `dkim_signing.conf` を上書きした (`tasks/main.yml`)。selector_mapは使わず、送信ドメインが `fickledev.com` の1つのみのためselectorを固定値で宣言した。

認証の反復失敗に対する遮断機構が要求するカーネル権限 (要件11.4) は `compose.yaml.j2` に `cap_add: [NET_ADMIN]` を `mailserver_enable_fail2ban` が真の場合のみ宣言した。上流ドキュメント (docker-mailserver `config/security/fail2ban`) の公式例と一致する (NET_RAWは不要)。

### 送信メールの署名が1個であることの確認

自己発行したアプリケーションパスワードを用いて submission (587, STARTTLS) で自分自身 (`mail-6-5-verify@fickledev.com`、本タスク専用の使い捨てテスト人物、後述) 宛にメールを送信し、LMTP配送後にIMAPS (993、VPS経由でk3s Dovecotへ中継) でログインしてメッセージ本文を取得、`DKIM-Signature:` ヘッダの出現数を数えた。

- 初回確認 (rspamd有効化・旧機構無効化の直後、fail2ban/ClamAV未有効化の段階): **1個** (`v=1; a=rsa-sha256; c=relaxed/relaxed; d=fickledev.com`)。合格。
- ClamAV有効化後の再確認で**一時的に0個**になる不具合が発生し (下記「想定外の事象」参照)、修正後の再送信で**1個**に復帰したことを確認した。

### 迷惑メール判定の発火確認

既知の検体 GTUBE (`XJS*C4JDBQADN1.NSBN3*2IDNEN*GTUBE-STANDARD-ANTI-UBE-TEST-EMAIL*C.34X`) を本文に含む未認証のメールを、VPS自身のホストから `127.0.0.1:25` へ (自分のインターネット経路の外向き25番はOP25B相当で到達不能なため、ansible経由でVPS上にPythonスクリプトを配置し実行) `mail-6-5-verify@fickledev.com` 宛に送信した。

`554 5.7.1 Gtube pattern` でDATA段階にて拒否され、迷惑メール判定が正しく発火することを確認した (**合格**)。送信者ドメインに `example.com` (RFC 7505のnull MX) を使った初回試行は、GTUBE判定に到達する前にnullMX判定で550拒否されたため、`gmail.com` に変更して再試行した。

### ウイルス検知の発火確認

既知の検体 EICAR (`X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*`) を添付したメールを、同じくVPS自身のホストから `127.0.0.1:25` へ送信した。

1回目の試行 (添付ファイル名の拡張子が `.com`、`Date`/`Message-ID`ヘッダを省略) は `MIME_BAD_EXTENSION` + `MISSING_MID` + `MISSING_DATE` の合算スコアで拒否され、ClamAVのシンボル (`CLAM_VIRUS`) は発火していなかった。ヘッダを整え添付ファイル名を `.txt` に変更して再試行した結果、`554 5.7.1 ClamAV FOUND VIRUS "Eicar-Test-Signature"` で拒否され、rspamdのログに `CLAM_VIRUS(0.00){Eicar-Test-Signature;}`、`forced: reject "ClamAV FOUND VIRUS ..."; score=nan (set by ClamAV)` が記録されていることを確認した (**合格**)。

### 認証の反復失敗に対する遮断の発火確認と解除手段

**発火前の準備**: fail2banのみを有効化した段階で、既に稼働していたGTUBEテスト等 (VPSホストの `127.0.0.1` 経由でのアクセスがdocker DNAT/hairpin NATによりコンテナのブリッジgw `172.18.0.1` として観測される) が偶発的に `postfix`/`dovecot` 両jailで遮断される事象が発生していた。これを `docker exec mailserver fail2ban-client set <jail> unbanip 172.18.0.1` で実際に解除できることを、意図的な発火の前に確認した (要件が求める「発火前に解除手段を確認する」の実地確認を兼ねる)。

**意図的な発火**: 自分のサンドボックス環境の実インターネット経路 (公開IP `124.155.16.232`。ansible/sshが使うtailnetアドレス `100.127.244.115` とは別インターフェース) から `mail.fickledev.com:587` へ、既存の使い捨てテスト人物 `mail-6-5-verify` のユーザー名 + 意図的に誤ったパスワードでSMTP AUTHを8回試行した。

結果、`postfix`/`dovecot` 両jailで `Total failed: 6` (設定値 `maxretry=6` と一致)、`Currently banned: 1`、`Banned IP list: 124.155.16.232` を確認した (**合格**)。

**遮断の範囲**: 遮断中、同一IPから docker-mailserverコンテナが直接終端するポート (587/465/25) は接続不能 (タイムアウト) だった一方、VPSホストのhaproxy (443) およびnginx streamでk3s Dovecotへ中継されるIMAPS (993) は接続可能なままだった。同時にansible (`-m ping`、tailnet経由) も問題なく疎通した。この結果から、遮断はdocker-mailserverコンテナ自身が終端するメール用ポートに限定されており、送信元IPに対する包括的なホストワイドDROPではないと判断する。design.md/requirements.mdが記す「ホストのパケットフィルタを操作する」という表現は、`cap_add: NET_ADMIN` が必要という点では正しいが、実際の遮断効果はコンテナ自身のネットワーク名前空間 (bridgeネットワーク、`network_mode: host`ではない) に閉じており、ホストの他サービスやSSH管理経路には及ばないことを実機で確認した。

**解除手段**: `docker exec mailserver fail2ban-client set <jail> unbanip <IP>` (ansible経由で実行)。`postfix`・`dovecot` 双方のjailに個別に発行する必要がある (戻り値1が成功、0が対象なし)。解除後、対象ポートへの接続が即座に復旧することを確認した。

**ホスト側fail2banとの非競合確認**: ホストのfail2ban (apt パッケージ、`fail2ban-client status` をコンテナ外で直接実行して確認) は `sshd` jailの1つのみを持ち、コンテナ内fail2ban (`custom`/`dovecot`/`postfix` の3jail) とは別プロセス・別ログソース (`_SYSTEMD_UNIT=sshd.service` 対 `/var/log/mail.log`) である。ホストの `iptables -L -n` にコンテナのfail2banが使う `nftables-allports` 由来のchainは存在せず (コンテナは独自のネットワーク名前空間内でnftablesを操作するため、ホストのiptables-legacyとは完全に別系統)、両者は独立して動作していることを確認した。

### ウイルス検査有効化後の常駐メモリとswap実測

対象: VPS (`free -m`, `swapon --show`, `docker exec mailserver ps aux`)。

| 時点 | total | used | available | swap used |
|---|---|---|---|---|
| タスク1.1 (衛星サービス未適用) | 1966 MB | - | 1404〜1438 MB | 25 MB |
| 第4段直前 (rspamd+fail2ban稼働、ClamAV未起動) | 1966 MB | 673 MB | 1292 MB | 129 MB |
| ClamAV有効化・安定後 | 1966 MB | 1690 MB | **275 MB** | 139 MB |
| 修正適用・最終安定状態 | 1966 MB | 1607 MB | 358 MB | 137 MB |

`clamd` プロセスの常駐メモリ (RSS) は約965 MB (987848 KB) で、上流FAQが示す「約850MB、増加傾向」の目安を実際に上回っていた。利用可能メモリ単体は275〜358 MBまで低下し、タスク1.1で見積もった「利用可能メモリ+swap空き (約3400〜3500MB)」の予算内には収まっているものの、余裕は乏しい。swap使用量自体は137〜139MBで大きくは増えておらず、現時点でメール配送やIMAP取得が不能になるような重度のswap踏みつけは観測されなかったが、将来の定義データベース肥大化やメール処理の同時実行数増加によってこの前提が崩れうる残存リスクとして記録する。

### 認証済みの送信に対する検査の適用可否

`RSPAMD_CHECK_AUTHENTICATED=1` として明示的に宣言した (`mailserver_rspamd_check_authenticated: true`)。既定値 (0) に委ねず、認証済みの送信 (submission経由の自ドメイン利用者) に対しても迷惑メール・ウイルス検査を適用する方針とした。侵害されたアプリケーションパスワードによる送信を自身の検査で検知できるようにするための判断である。

### 想定外の事象: DKIM署名機能の一時的な喪失と修正

第4段 (ClamAV有効化) 後の再検証で、送信した2通目のテストメールのDKIM-Signatureが0個であることが判明した。調査の結果、rspamd.logに `dkim_module_load_key_format: cannot load dkim key ...: cannot stat key file: ... Permission denied` を発見した。

根本原因は次のとおり。冪等性の修正 (後述) で `rspamd/dkim/` ディレクトリと鍵ファイルへのowner/mode強制を外した際、親ディレクトリ `mailserver_dms_config_dir` (`/opt/mailserver/config`) 自体は既存タスクにより常に `0750 root:root` に固定されたままだった。`0750` は other (コンテナ内の非rootユーザ `_rspamd`, uid=112/gid=114) にディレクトリのtraverse権限 (実行ビット) を一切与えないため、子ディレクトリ (`rspamd/`, `rspamd/dkim/` 自体は `0755` で作成済み) より下へ一切降りられず、鍵ファイルの読み取りが `Permission denied` になっていた。`dovecot.cf` 等の直下ファイルはDMS自身がroot権限で読んでから所定の場所へコピーするため `0750` でも問題にならないが、`rspamd/dkim/` 配下だけはコピーされずbind mount先を非rootプロセスが直接読み続けるため、traverse権限が必須という非対称性が原因だった。なぜ最初のDKIM署名確認 (第1段) の時点でこの問題が顕在化していなかったかは特定できていない (裏が取れなかった点、後述)。

修正: `mailserver_dms_config_dir` のみ `mode` を `0750` から `0751` に変更した (`ansible/roles/mailserver/tasks/main.yml` の「Ensure mailserver config directories exist」をpath/mode の辞書リストへ変更)。`0751` はotherにtraverseのみを許可し、ディレクトリの一覧 (list) や直下ファイルの内容読み取りは許可しないため、`dovecot.cf`・`postfix-main.cf` 等の機密性はファイル自体の `0640` 権限により維持される。適用後、`su _rspamd -c "head ..."` が成功することと、実際に送信したメールのDKIM-Signatureが1個に復帰したことを確認した。

### 想定外の事象: `-e` extra-varsのブール型誤り

fail2ban/ClamAVを段階的に有効化する目的で `ansible-playbook -e mailserver_enable_fail2ban=false -e mailserver_enable_clamav=false` (key=value形式) を実行したところ、Ansibleがこれを文字列 `"false"` として渡し、Jinjaの `{% if %}` は非空文字列を真と評価するため、意図に反して両方とも有効化された状態で適用されてしまった。JSON形式 (`-e '{"mailserver_enable_fail2ban": false}'`) に修正して正しく段階的な適用をやり直した。

### 冪等性の副次的な修正

上記の権限修正と合わせて、DKIM鍵ディレクトリ・鍵ファイルへのowner/group/mode強制を撤去した (コンテナの実行時所有権と衝突し、2回目以降の適用でも `changed` を報告し続けていたため)。この修正と権限ビットの修正 (`0751`) を適用した後、`ansible-playbook` を連続2回実行し、2回目が `changed=0` であることを確認した。

### テストアカウントの後始末

本タスク専用の使い捨て人物 `mail-6-5-verify` (Kanidm) を用いた。作成はメール属性の付与のみ (受信者存在確認用) から開始し、迷惑メール判定・ウイルス検査の確認ではこの属性のみを使用した (アプリケーションパスワードは不要)。DKIM署名確認とfail2ban発火確認のためにアプリケーションパスワードが必要になった時点で、`mail_users`グループへ追加し、資格情報更新セッションAPIでパスワード+TOTP (SHA1へのダウングレードを受諾) を設定してコミットし、本人自身のセッション (`POST /v1/auth` によるログイン → `POST /v1/reauth` による特権昇格 → `POST /scim/v1/Person/mail-6-5-verify/Application/_create_password`) でアプリケーションパスワードを自己発行した (管理者による代理発行ではない)。

検証後、`mail_users`グループから除外し (`PUT .../_attr/member` に `[]`)、`DELETE /v1/person/mail-6-5-verify` で削除した (削除後の`GET`が `null` (4バイトのJSON) を返すことを確認)。`terraform-kanidm` で `infisical run --env=prod -- terraform plan -detailed-exitcode` を実行し、**"No changes."** (exit code 0) であることを確認した。

### 裏が取れなかった点

- なぜ第1段の時点でのDKIM鍵読み取り確認 (`su _rspamd -c "head ..."`) が成功していたのか特定できていない。当時も `mailserver_dms_config_dir` は `0750 root:root` だったはずであり、理論上は同じ理由でtraverseできないはずだが、実測では読めていた。コンテナ再作成の直後というタイミング、または調査時に見落とした一時的な状態変化が影響した可能性があるが、再現・特定はしていない。
- ClamAVの定義データベースが将来さらに肥大化した場合の常駐メモリの伸び幅は測定していない (今回の実測はある1時点のスナップショット)。
- rspamd/ClamAVの遅延起動時間 (コンテナ再作成からclamdの常駐メモリ確保が安定するまで、実測で概ね1〜2分) がリソース逼迫時にどこまで伸びるかは未検証。

## タスク8.1: 書庫の取り出しと保存先 (2026-09-04)

### 採った構成

新規Ansibleロール `ansible/roles/mail_backup` (プレイブック `ansible/playbooks/mail_backup.yml`、`site.yml` から import) を作成した。`mail_backup_side` で source/destination の2役を1ロールに収め、以下のpull型構成をとる。

- **destination (pbs, LXC 202)**: systemd timer (`OnCalendar=*-*-* 04:10:00`、`RandomizedDelaySec=10m`) が `mail-backup-pull.sh` をoneshotで起動し、専用のed25519鍵 (`/root/.ssh/mail_backup_ed25519`、Infisical `MAIL_BACKUP_SSH_PRIVATE_KEY`) でsource側へSSH接続し、tarストリームを一時ファイル (`.mailbox-<UTC timestamp>.tar.gz.partial`) へ受信、`gzip -t` で整合性を確認してから最終名へ`mv`する。保存先は `/mnt/zfs-pool-0/mail-backup`。世代数上限 (既定14) を超えた古い生成物を、新しい生成物の確定後にのみ削除する。
- **source (k3s-agent-minipc)**: 対応する公開鍵 (`MAIL_BACKUP_SSH_PUBLIC_KEY`) を、既存の接続用ユーザー (`tochi`) の `authorized_keys` に forced command (`command="/usr/local/sbin/mail-backup-extract.sh",no-agent-forwarding,no-port-forwarding,no-pty,no-X11-forwarding,no-user-rc`) 付きで追加する。この鍵はSSHクライアントが要求した内容に関わらず常にこのスクリプトしか実行できない。スクリプトは `sudo bash -c '...'` の内側でPVディレクトリのglob展開とtar実行の両方を行う (中間ディレクトリ `/var/lib/rancher/k3s` が非rootから辿れないため、glob展開自体をsudoの外に置くと0件になる不具合を実機で踏み、修正した)。

世代数上限、保存先ディレクトリ、リトライ間隔はいずれもロールの変数として定義として保持する (`ansible/roles/mail_backup/defaults/main.yml`)。

### `mariadb_dump` ロールの構成を踏襲したか

**部分的に踏襲し、保存先とインフラ経路は独自に決めた。**

踏襲した点: pbsが「取りに行く」pull型、systemd oneshot + timer、世代数上限を変数として持つ、というアーキテクチャ全体の骨格は`mariadb_dump`と同一にした。pbsを中央のバックアップ集約点として扱う既存の設計方針 (PBSのゲスト単位スナップショットも、mariadb_dumpの論理バックアップも、いずれもpbsが能動的に取得元へ接続する) との一貫性を優先した。

踏襲しなかった点:
1. **保存先ディレクトリ**: `mariadb_dump` は `pbs` のrootfs (`local-lvm`、hp-z440の `sda` = SSD) 上の `/var/backups/mariadb-gitea` に保存する。しかしメール書庫は `.kiro/steering/tech.md` の「添付・画像・バックアップ・メールボックスの実体はHDD」という役割別方針の対象そのものであり、SSDに書き続ける構成は方針違反になる。pbsに既存の `/mnt/zfs-pool-0` マウント (hp-z440の `sdc` = HDD、zfs-pool) があったため、そちらを保存先に選んだ。
2. **転送手段**: `mariadb_dump` はDB専用プロトコル (`mysqldump` over TCP、`mariadb_dump_user`/`mariadb_dump_password` という業務アカウント) で認証する。メールボックスの実体はファイルシステム上のmaildirであり、対応するネットワークプロトコルが存在しないため、SSH + `tar` のstream転送を採用した。これに伴い、`mariadb_dump` には無い新規の認証情報 (SSH鍵ペア) が必要になった。汎用の「fleet全体の接続鍵」(`TF_VAR_ssh_public_key`) を転用せず、この用途専用のed25519鍵を新規に生成しforced commandで制限した。理由: fleet全体の接続鍵をpbsに複製すると、pbsが侵害された場合の被害範囲が「mail-backup-extract.shの実行のみ」から「fleet中の全ホストへのroot相当SSH」に拡大するため。

### 物理ディスクの特定結果

実機調査 (`lsblk`, `qm config`, `pct config`, `cat /proc/mounts`, `kubectl describe pv`) により確認した。

- **メールボックスの実体**: Dovecot Pod (`dovecot-5b6d8b6bf8-zlmjl`) は `k3s-agent-minipc` に固定。PV (`local-path`) の実体は同ノード上の `/var/lib/rancher/k3s/storage/pvc-54c8818c-d1cb-4a4a-a52b-a61ca97a38b8_mailbox_mailbox-data`。`k3s-agent-minipc` (vmid 151) は Proxmoxノード **n100** 上のVMで、そのディスク (`vm-151-disk-0`) は `local-lvm` シンプール上にあり、`n100` の物理ディスクは **`/dev/sda` (SSD、ShiJi 512GB) の1台のみ** (`sdb`/`sdc` は存在しない、ZFSも保持しない)。
- **保全先**: `pbs` (LXC 202) は Proxmoxノード **hp-z440** 上のコンテナ。マウントポイント `/mnt/zfs-pool-0` (今回の保存先 `mail-backup` サブディレクトリの親) は `zfs-pool:subvol-202-disk-0` で、`cat /proc/mounts` で `zfs-pool /zfs-pool zfs ...` と確認でき、`zfs-pool` は hp-z440の **`/dev/sdc` (HDD、ST4000VN006、3.6T)** 上の単一vdevである。

タスク本文が前提とする「メールボックスは(hp-z440の) `sda` 上に、保全先は `sdc` 上に」という記述は**このホストには当てはまらない**。メールボックスを保持するのはn100であり、hp-z440には存在しない。実態は「メールボックスの実体は **n100の `sda`**、保全先は **hp-z440の `sdc`**」であり、ホストをまたいで別々の物理マシン上の別々の物理ディスクに分かれている。

### 分離によって残る障害の範囲 (タスク本文の記述との食い違いを含む)

設計 (design.md) およびタスク本文は「物理ディスク単体の故障では実体と成果物のいずれかが残るが、両者を収容するホストの全損では同時に失われる」という、**同一ホスト上の異なる物理ディスクへの分離**を前提とした残存リスクを記録するよう求めている。しかし実際に採った構成では、実体 (n100) と保全先 (hp-z440) は最初から別ホストであるため、この「ホスト全損で両方失う」という記述は成立しない。

実態に即した残存障害範囲は以下のとおり:

- n100単体の障害 (ディスク故障、電源故障、ホスト全損等) では、メールボックスの実体を喪失するが、直近の書庫がhp-z440側に残るため復旧可能。
- hp-z440単体の障害では、書庫を喪失するが、メールボックスの実体はn100側に残るため保全は継続できる (次回実行までの窓は開くが、実体そのものは失われない)。
- 両ホストが同時に失われる事象 (自宅内の共通障害: 停電、火災、盗難、自宅ネットワーク全体の物理破損等、n100とhp-z440が同一の物理的所在地にあることに由来する事象) でのみ、実体と書庫の両方を同時に喪失する。これは「ホストをまたぐ複製」を要件化しても解消しない、**設置場所の分離**を要する範囲であり、design.mdが書く「ホストをまたぐ複製を要する」という解消条件は今回の構成では既に満たされているが、より広い「サイト全体の分離」までは意図的に扱っていない。

### 世代数上限と失敗記録の確認結果

- **書庫の生成**: `systemctl start mail-backup-pull.service` を手動起動し、`/mnt/zfs-pool-0/mail-backup/mailbox-<timestamp>.tar.gz` が生成されることを確認した。`tar tzf` で実データ (`verify-sender@fickledev.com/mail/...` 等の実在maildir) を含むことも確認した。手動起動後も `systemctl list-timers` で次回スケジュール (`OnCalendar` 由来) が変化していないことを確認し、手動起動が定期実行の状態に影響しないことを確かめた。
- **世代数上限**: `-e mail_backup_retain_generations=2` で一時的に上限を2へ下げて適用し、pull を複数回手動起動して3世代以上を生成させた結果、最新2世代のみが残り古い世代が削除されることを確認した。確認後、`-e` を外して再適用し上限を既定値14へ戻した (スクリプトへ埋め込まれた `retain="14"` を再確認)。
- **失敗記録**: source側の抽出スクリプト (`/usr/local/sbin/mail-backup-extract.sh`) を一時的にリネームし、SSH forced commandが `No such file or directory` (exit 127) で失敗する状態を意図的に作った。この状態でpullを起動した結果、`systemctl is-failed mail-backup-pull.service` が `failed` を報告し、journalに `Failed with result 'exit-code'` が記録され、`.partial` ファイルは残らず、既存の世代 (2件) も一切変化しなかったことを確認した (取得失敗が「成功として扱われない」ことの実地確認)。確認後、抽出スクリプトを元の名前へ戻し、再度手動起動して復旧を確認した。

### PBSの対象一覧

`ansible/inventory/host_vars/pbs/main.yml` の `pbs_backup_targets` には、`k3s-agent-minipc` (vmid 151, `include: true`) が既存の定義として既に含まれており (`git diff` で本タスク中の変更なし)、他のk3sノードと同様に仮想化基盤の保護機構 (PBSゲストスナップショット) の対象であることを確認した。新規追加は不要と判断した。

### 冪等性の確認

`ansible-playbook playbooks/mail_backup.yml` (`infisical run --env=prod --` 経由) を2回連続で適用し、2回目が両ホストとも `changed=0` であることを確認した (途中で世代数上限の一時変更や抽出スクリプトの一時退避を行った後も、最終状態への再適用および連続2回適用でこの結果を再確認している)。

### Infisicalへの新規登録

`MAIL_BACKUP_SSH_PRIVATE_KEY` / `MAIL_BACKUP_SSH_PUBLIC_KEY` (prod環境) を本タスクで新規生成・登録した。ローカルに一時生成した鍵ファイルはInfisicalへの登録後にshredで削除済みで、リポジトリには含まれない。

### 想定外の事象

- テンプレート内の `${#matches[@]}` / `${#old[@]}` (bash配列長構文) がJinja2の `{# ... #}` コメント開始と誤認識され、`ansible.builtin.template` が `Missing end of comment tag` で失敗した。該当箇所を `{% raw %}...{% endraw %}` で囲み、変数展開が必要な箇所のみ `{% endraw %}{{ var }}{% raw %}` で挟む形に修正した。
- 抽出スクリプトのグロブ展開を素朴に「sudoなしで展開してからsudo tarへ渡す」形にした初版では、`/var/lib/rancher/k3s` が非root (`tochi`) から辿れず (`Permission denied`)、展開が常に0件になっていた。グロブ展開自体をsudoの内側 (`sudo bash -c '...'`) に移す修正で解消した。
- pull側スクリプトのSSHログインユーザーを `{{ ansible_user }}` から導出していたところ、宛先(pbs)プレイでの `ansible_user` はpbs自身の接続ユーザー (`root`) を指しており、source側 (`tochi`) とは別人になっていた (`root@192.168.1.151: Permission denied (publickey)`)。両プレイで意味が変わる変数を使わず、`tochi` を固定値として明示する形に修正した。

### 裏が取れなかった点

- n100/hp-z440以外の障害モード (ネットワークスイッチ、自宅回線、UPS等の共有インフラ単体の故障がn100/hp-z440いずれか一方だけを道連れにするか、両方を同時に道連れにするか) は調査していない。上記の「残る障害の範囲」はストレージ・ホスト単位の分離のみを評価したものである。
- 書庫からの実際の復元 (要件9.2/9.3、メールボックスの実体を書庫展開で置き換える手順とその成立確認) は本タスク (8.1) の範囲外として扱った。設計上は別タスクの担当とみて、本タスクでは「取り出しと保存」までを検証対象とした。
