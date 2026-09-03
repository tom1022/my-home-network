# 送信元の識別に関する記録 (SPF / DKIM / DMARC)

`fickledev.com` の送受信メール認証に関する DNS 記録の仕様と、実機での検証結果。すべて
Terraform (`terraform/cloudflare_dns.tf` の `local.other_dns_records`) で管理する。手動作成は
行っていない。

## 現在の記録

| 種別 | 名前 | 内容の要旨 |
|---|---|---|
| MX | `fickledev.com` | `9 mail.fickledev.com.` (既存、変更なし) |
| TXT (SPF) | `fickledev.com` | `v=spf1 ip4:163.44.119.79 -all` |
| TXT (DKIM) | `mail._domainkey.fickledev.com` | `v=DKIM1; k=rsa; p=<2048bit RSA公開鍵>` (255byte超のため2つの quoted string に分割) |
| TXT (DMARC) | `_dmarc.fickledev.com` | `v=DMARC1; p=none; rua=mailto:postmaster@fickledev.com; fo=1` |

## SPF: 送信元を VPS の実際の送出アドレスに限定

`ansible/roles/mailserver` の docker-mailserver コンテナは bridge ネットワーク上で動作し、
IPv6 を持たない (`docker network inspect` で `EnableIPv6: false`、コンテナ内に `inet6` の
global アドレスなし)。コンテナ内から `https://api.ipify.org` へ到達した際の送出元アドレスは
VPS の IPv4 (`163.44.119.79`、`var.vps_ipv4`) に一致することを実機で確認した。`mail.fickledev.com`
の AAAA レコードは受信・取得用のホスト名解決であり、送出経路には使われない。したがって SPF に
`ip6` は含めない。

逆引き (PTR) は IPv4 (`163.44.119.79 → mail.fickledev.com.`)・IPv6 (`2400:8500:2002:3320:163:44:119:79
→ mail.fickledev.com.`) とも権威サーバ側で設定済みだが、これは受信側の FCrDNS 評価に関わる別軸の
事実であり、実際に IPv6 で外向き SMTP を張る経路が存在しない以上、SPF の対象を広げる理由には
ならないと判断した。

家庭回線からの送出は存在しない (送信は VPS の docker-mailserver からのみ) ため、限定の範囲に
家庭側のアドレスは含めない。`-all` (hard fail) とし、VPS 以外からの送出はすべて不正とみなす。

## DKIM: 稼働中の秘密鍵から公開鍵のみを導出

署名は rspamd が担う (`mailserver_enable_rspamd: true`、`mailserver_enable_opendkim: false`、
task 6.5 で適用済み)。セレクタは `ansible/roles/mailserver/defaults/main.yml` の
`mailserver_dkim_selector` (`mail`) と一致させている。

公開鍵は、稼働中の秘密鍵ファイル (`{{ mailserver_dms_config_dir }}/rspamd/dkim/fickledev.com-mail.private`)
から VPS 上で `docker exec mailserver openssl rsa -pubout` により導出した。秘密鍵の値は
標準出力・ファイル・報告のいずれにも一切出していない。鍵の再生成は行っていない (既存の署名済み
メールとの整合を壊さないため)。

RSA 2048bit の公開鍵 (base64 392 文字) は `v=DKIM1; k=rsa; p=...` を合わせると 410 文字となり、
DNS の character-string 上限 255byte を超える。Cloudflare の実際の格納形式に合わせ、255byte
ちょうどで区切った2つの quoted string (`"..." "..."`) として Terraform に定義した。

## DMARC: 導入直後は監視のみ (p=none)

SPF・DKIM とも本タスクで新規に公開したばかりであり、アライメントの見落としが正当な送信メールの
破棄・隔離に直結するリスクを避けるため、`p=none` (認証結果の反映は行わず監視のみ) を選択した。
`rua=mailto:postmaster@fickledev.com` で集計レポートを既存の postmaster アドレスへ送らせ、
実際の認証結果を継続的に観測できるようにしている。`fo=1` (SPF・DKIM いずれかが失敗した時点で
失敗レポートの対象とする) を付与した。運用実績が積み上がった段階で `p=quarantine` /
`p=reject` への引き上げを検討する。

## 検証方法と結果

### 送信側 (SPF / DKIM / DMARC が受信側からどう評価されるか)

Kanidm に使い捨て人物アカウント `mail71verify` (`mail=mail71verify@fickledev.com`、
`mail_users` 所属) を作成し、本人セッションでアプリケーションパスワードを自己発行した上で、
production の submission (587、`mail.fickledev.com`) へ認証済みで接続し、
[mail-tester.com](https://www.mail-tester.com/) が発行する一意の宛先へテストメールを送信した。

結果 (スコア 9.5/10、"Wow! Perfect, you can send"):

- **SPF**: `pass` — `Your server 163.44.119.79 is authorized to use mail71verify@fickledev.com`
- **DKIM**: `pass` — 署名が公開した鍵と一致 (2048bit)
- **DMARC**: `pass (p=none dis=none) header.from=fickledev.com`
- 逆引き: `163.44.119.79` → `mail.fickledev.com` (HELO と一致)

VPS のメールログ (`docker logs mailserver`) でも、この送信が
`relay=reception.mail-tester.com[134.98.158.159]:25, ... status=sent (250 2.0.0 Ok: queued as ...)`
として実際に配送されたことを確認した。

### 受信側 (公開後、外部からの受信がメールボックスに現れるか)

外部サービス [mailtestpro.com](https://mailtestpro.com/) の受信到達性プローブから
`mail71verify@fickledev.com` 宛にテストメールを送らせた。サービス自身の UI 表示は演出的な
要素が強く単体では信頼しなかったため、VPS 側のメールログと IMAP の両方で実際の着信を裏取りした。

- メールログ: `185.85.241.127 (jara.dedidns.com)` からの接続を確認。
  `from=<mailtestpro@sndgrd.shop>` のメールが
  `to=<mail71verify@fickledev.com>, relay=192.168.1.151[192.168.1.151]:30024, ...
  status=sent (250 2.0.0 <mail71verify@fickledev.com> ... Saved)` として格納側 (k3s) へ
  LMTP 配送された。
- IMAP: `mail71verify` のアプリケーションパスワードで `mail.fickledev.com:993` へログインし、
  `INBOX` の `SEARCH ALL` が1件を返し、`FETCH` した `Message-ID`
  (`<1788450703.EB3BC134@mailtestpro.com>`) がメールログの記録と一致することを確認した。

### 後始末

検証後、`mail71verify` を `mail_users` グループから除外し (`DELETE .../_attr/member`、
指定値のみの削除)、`DELETE /v1/person/mail71verify` で削除した (削除後の `GET` が `null` を
返すことを確認)。`terraform-kanidm` の `infisical run --env=prod -- terraform plan
-detailed-exitcode` は **"No changes."** であり、`mail_users` のメンバーシップ変更が
Terraform の管理対象外であることと整合する。ローカルに一時生成したパスワード・TOTP
シークレット・アプリケーションパスワードのファイルは `shred -u` で削除した。

## Terraform apply の記録

`-target` で以下の3リソースのみに限定して apply した。`module.virtual_machines` を含む
既知のドリフト (`k3s-agent-z440` の `disk.backup`) には一切触れていない。

- `cloudflare_dns_record.this["spf_txt"]`
- `cloudflare_dns_record.this["dkim_mail_txt"]`
- `cloudflare_dns_record.this["dmarc_txt"]`

plan は 3 added / 0 changed / 0 destroyed のみで、apply も同一の3件のみが作成された。

## 完了可否

**完了。** MX は着手前から公開済みであり (運用者承認済み)、本タスクでは以下を満たした。

- 送信者方針 (SPF) を VPS の実測アドレスに限定して定義した。
- 公開鍵レコードを追加してから署名 (rspamd DKIM、task 6.5 で有効化済み) が検証可能な状態にした
  (順序の逆転を解消した)。
- 認証失敗時の扱い (DMARC) を定義した。
- すべて Terraform で管理し、手動作成は行っていない。
- 公開後、外部からの受信メールがメールボックスに現れることを実機で確認した。
- 送信メールが外部の受信側から見て SPF/DKIM/DMARC のいずれも `pass` することを実機で確認した。

## 裏が取れなかった点

- `mailtestpro.com` は SMTP プローブの過程で `postscreen` に `172.18.0.1` (VPS 自身の docker
  ブリッジゲートウェイ) からの接続も記録していた (メッセージは cancel され未達)。この接続が
  同サービスの何らかの経路によるものか、無関係の事象がたまたま同時刻に発生したものかは
  特定していない。実害はない (対応するメッセージは配送されていない) ため深追いしなかった。

## タスク 7.3: 外部への到達性の確認

タスク 7.1 で得た結果 (2026-09-02 時点) を流用せず、本タスクで新たに使い捨てアカウントを作成し、
新規に外部の受信ドメインへ送信して、受信側が実際に報告する検証結果を確認した。

### 手順

Kanidm に使い捨て人物アカウント `mail73verify` (`mail=mail73verify@fickledev.com`、
`mail_users` 所属) を作成し、本人セッションでアプリケーションパスワードを自己発行した上で、
production の submission (587、STARTTLS、`mail.fickledev.com`) へ認証済みで接続し、
[mail-tester.com](https://www.mail-tester.com/) が新たに発行した一意の宛先
(`test-2ozq6nmwi@srv1.mail-tester.com`) へテストメールを送信した。件名を
`task 7.3 SPF/DKIM/DMARC verification` とし、受信側の結果画面の件名表示と突き合わせることで、
タスク 7.1 の結果の使い回しでないことを確認できるようにした。

### 結果 (受信側 mail-tester.com が報告した検証結果)

スコア 9.5/10、"Wow! Perfect, you can send"。結果ページ: `https://mail-tester.com/test-2ozq6nmwi`

- **送信者方針 (SPF)**: `pass` — `Your server 163.44.119.79 is authorized to use
  mail73verify@fickledev.com`。`Received-SPF: pass ... identity=mailfrom;
  envelope-from="mail73verify@fickledev.com"; helo=mail.fickledev.com; client-ip=163.44.119.79`
- **署名 (DKIM)**: 有効な署名。`d=fickledev.com`, `s=mail`, `a=rsa-sha256`, 2048bit 鍵。
  `dkim=pass (2048-bit key; unprotected) header.d=fickledev.com header.i=@fickledev.com
  header.a=rsa-sha256 header.s=mail`
- **両者に基づく方針 (DMARC)**: `pass` — `dmarc=pass (p=none dis=none)
  header.from=fickledev.com`。`p=none` (監視のみ) だが、評価結果自体は `pass`。
- **アライメント**: 受信側が示した `From Domain: fickledev.com` / `DKIM Domain: fickledev.com`
  が一致 (DKIM アライメント成立)。SPF の envelope-from
  (`mail73verify@fickledev.com`、ドメイン部 `fickledev.com`) も `From` ヘッダのドメイン
  (`fickledev.com`) と一致 (SPF アライメント成立)。両者とも `From` ヘッダのドメインと揃っており、
  DMARC の pass はアライメントの成立によるものであることを送信側の情報からも確認した。
- 逆引き: `163.44.119.79` → `mail.fickledev.com` (HELO と一致、タスク 7.2 の記録と整合)。

**判定: 送信者方針・署名・両者に基づく方針の 3 つすべてが `pass`。アライメントも成立。合格。**

### 手段の独立性について

運用者からの指摘を受け、当初検討していた実プロバイダのメールボックス (Gmail 等) への送信や
`check-auth@verifier.port25.com` 等の自動応答型サービスの追加取得は行わなかった。要件が求めるのは
「外部の受信ドメインに対して送信し、受信側が報告する検証結果を確認する」ことであり、
`mail-tester.com` はこれを文字どおり満たす外部の受信ドメインである。タスク 7.1 との違いは、
タスク 7.1 の結果を流用せず、本タスクで新規に使い捨てアカウント (`mail73verify`) を作成し、
新たに払い出された宛先へ改めて送信し、受信側から新規に得た報告を確認した点にある。

### 後始末

検証後、`mail73verify` を `mail_users` グループから除外し (`DELETE .../_attr/member`、
指定値のみの削除)、`DELETE /v1/person/mail73verify` で削除した (削除後の `GET` が `null` を
返すことを確認)。除外直後の `mail_users` メンバー一覧は `null` (空) であり、本タスク着手前の
状態と一致する。`terraform-kanidm` の `infisical run --env=prod -- terraform plan
-detailed-exitcode` は **"No changes."** であった。ローカルに一時生成したパスワード・TOTP
シークレット・アプリケーションパスワード・SMTP デバッグログ (AUTH PLAIN の base64 に資格情報が
含まれるため) は `shred -u` で削除した。

### 完了可否

**完了。** 定義の存在ではなく、mail-tester.com という外部の受信ドメインが実際に報告した検証結果
(SPF/DKIM/DMARC すべて `pass`、アライメント成立) によって確認した。タスク 7.1 の結果の流用ではなく、
本タスクで新規に取得した結果である。DNS レコードやロールの定義の変更は不要だった (是正は発生せず)。
