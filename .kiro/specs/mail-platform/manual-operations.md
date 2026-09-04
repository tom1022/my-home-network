# コードによる管理の対象外となる手順

構成の適用に必要な手順のうち、宣言的な定義の対象にならないものを列挙する。いずれも
Terraform / Ansible のどちらからも実施できず、人手による操作を要する。

| 手順 | 必要になる契機 |
|---|---|
| 逆引きの設定 | VPS の作成・再作成時、および IP アドレスの変更時 |
| Infisical へのシークレットの投入 | シークレットの新規発行時と再発行時 |
| OPNSense 上の DNS 定義 | k3s ノードのアドレスが変わった時、および kanidm Pod の稼働ノードが変わった時 |
| POSIX パスワードによる LDAP bind の無効化 | Kanidm を作成・再作成した時 |
| Kanidm の利用者アカウントと `mail_users` への所属 | 利用者を追加する時、およびグループを再作成した時 |
| 利用者によるアプリケーションパスワードの発行 | 利用者がメールクライアントを設定する時、および紛失・失効させた時 |

## 逆引きの設定

VPS の逆引き (PTR) はメール用ホスト名と一致していなければならない。受信側の多くが
逆引きの一致を配送の判断に用いるため、不一致のままでは拒否されうる。

| 項目 | 値 |
|---|---|
| IPv4 | `163.44.119.79` → `mail.fickledev.com` |
| IPv6 | `2400:8500:2002:3320:163:44:119:79` → `mail.fickledev.com` |
| 権威サーバ | `a.conoha-dns.com` / `b.conoha-dns.org` |
| TTL | 86400 |

**この操作は提供元 (ConoHa) のコントロールパネルからのみ実施できる。**提供元は逆引きの
設定に API を提供しておらず、Terraform のプロバイダにも対応するリソースが存在しない。
したがって逆引きはコードによる管理の対象外であり、VPS を再作成した場合や IP アドレスが
変わった場合は手作業での再設定が必要になる。

正引きは Terraform の管理下にある (`terraform/cloudflare_dns.tf` の `mail` レコード)。
逆引きだけが管理外であるため、両者の一致は自動では保証されない。

設定の結果は外部から `dig -x <アドレス>` を引いて PTR がメール用ホスト名を返すことで確認する。
不一致のまま送信を続けた場合、失敗は受信側の判定として現れるため送信側のログには表れない。

## Infisical へのシークレットの投入

メール基盤の認証情報は Infisical の `prod` を単一の情報源とし、Ansible が実行時に取得する。
Infisical 自体は Terraform の管理下になく、値の登録と更新は人手による操作である。

| キー | 内容 | 値の作り方 |
|---|---|---|
| `MAIL_LDAP_SEARCH_PASSWORD` | Kanidm の `mail-ldap-search` サービスアカウントの API トークン。LDAP の `dn=token` bind に用いる | `terraform-kanidm` の適用でサーバが生成した値を `terraform output -raw mail_ldap_search_api_token` で取り出して登録する。任意の値を指定する経路はない |
| `MAIL_DKIM_PRIVATE_KEY` | rspamd が署名に用いる DKIM の秘密鍵 | 鍵ペアを生成して秘密鍵側を登録する。公開鍵側のみが DNS の定義に現れる |
| `MAIL_BACKUP_SSH_PUBLIC_KEY` / `MAIL_BACKUP_SSH_PRIVATE_KEY` | 書庫の取得に用いる ed25519 鍵ペア。公開鍵は取得元へ forced command 付きで配置され、秘密鍵は取得側に置かれる | ローカルで鍵ペアを生成し、両方を登録する |

値が欠けている場合、対応する Ansible ロール (`mailserver` / `mail_backup`) は適用の開始前に
停止し、不足しているキー名を示す。適用が途中まで進んだ状態にはならない。ロールの実行は
`infisical run --env=prod -- ansible-playbook ...` の形を取り、値をリポジトリやホスト上の
設定ファイルに置かない。

鍵を失った場合の再発行の手順と、DKIM で守るべき順序 (公開鍵の DNS 反映を先に済ませてから
秘密鍵を差し替える) は `.kiro/specs/mail-platform/mailbox-restore-recreate-runbook.md` の
再作成の節に記述する。

## OPNSense 上の DNS 定義

tailnet 内の既定のリゾルバは OPNSense である。OPNSense は Terraform / Ansible のどちらからも
構成できず、DNS の定義は GUI 上の手作業でのみ変更できる。したがってメール基盤が依存する
名前解決のうち、tailnet を経由する経路の内容はコードから復元できない。

名前解決の経路は層ごとに分かれており、同じホスト名でも参照先が異なる。

`ldaps.kanidm.fickledev.com` の解決は OPNSense の host override が単一の情報源である。公開 DNS
(Cloudflare) にはこの名前を置かない。宛先が RFC1918 のアドレスであり、公開しても内部の構成を
晒すだけで、利用者はいずれも tailnet の内側にいる。

| 項目 | 値 |
|---|---|
| 種別 | Unbound DNS の Host Override |
| ホスト名 | `ldaps.kanidm.fickledev.com` |
| 向き先 | `192.168.1.151` (kanidm Pod が載るノード) |
| 設定場所 | OPNSense GUI: Services → Unbound DNS → Overrides |
| 確認 | `dig @192.168.1.1 ldaps.kanidm.fickledev.com A` が当該アドレスを 1 件返す |

host override が無い状態では NXDOMAIN ではなく **NODATA** が返る。Unbound は既定で公開ドメインが
RFC1918 アドレスへ解決する応答を DNS リバインディング対策として除去するため、上流に答えがあっても
応答から消える。host override はこの除去を受けない。応答が空であることは「その名前が存在しない」
ではなく「除去された」を意味しうる。

向き先は kanidm Pod が載るノード 1 台でなければならない。Service が `externalTrafficPolicy: Local`
を採るため他ノードの NodePort は応答せず、接続側に別アドレスへ再試行する機能もない。Pod の稼働
ノードが変わった場合はこの override も合わせる。

メールサーバのコンテナは Tailscale の DNS プロキシ (`100.100.100.100`) を自身のリゾルバとして
参照する (`ansible/roles/mailserver/defaults/main.yml` の `mailserver_container_dns_servers`)。
tailnet の既定リゾルバが OPNSense であるため、この経路の解決内容は OPNSense の定義に従う。
Dovecot の内部 DNS クライアントは `/etc/hosts` (NSS) を参照しないため、VPS ホスト側の静的登録
(`vps_proxy_static_dns_overrides`) はコンテナには効かない。この経路が成立しなければ LDAP bind が
失敗し、送信の認証と宛先の照合がいずれも成立しなくなる。

OPNSense へ直接問い合わせる経路は成立しない。DMZ 側の `192.168.1.1` は ICMP には応答するが 53 番は
応答せず、tailnet 側の `100.93.205.102` は pf が `tailscale0` 上の self 宛を block する。したがって
tailnet 上の利用者にとって、OPNSense の解決へ到達する手段は quad100 だけである。

## POSIX パスワードによる LDAP bind の無効化

Kanidm は既定で POSIX (unix) パスワードによる LDAP bind を許容する。許容されたままでは、
メールクライアントへ与えたアプリケーションパスワードとは別の資格情報で同じ bind が成立し、
メール用の資格情報を他の用途から分離するという前提が失われる。

| 項目 | 値 |
|---|---|
| 設定 | `ldap_allow_unix_pw_bind` |
| あるべき状態 | `false` |
| 操作 | `kanidm system domain set-ldap-allow-unix-password-bind false` |
| 権限 | `admin` の対話ログインセッション |
| 確認 | `kanidm system domain show` の出力に `ldap_allow_unix_pw_bind: false` が現れる |

この設定はドメインの状態としてのみ保持され、`terraform-kanidm` の宣言には現れない。provider
(`seanlatimer/kanidm` 0.1.10) にドメイン設定を扱うリソースが存在せず、宣言の対象にできないためである。

**Kanidm を再作成した場合は既定 (`true`) に戻る。**既定の状態では `kanidm system domain show` の
出力に当該項目が現れないため、出力に項目が無いことは「未設定」ではなく「許容されている」を意味する。
再作成のたびに再実施し、上記の確認まで行う。

## Kanidm の利用者アカウントと `mail_users` への所属

メール認証を使える対象は `mail_users` の所属者に限られる。グループそのもの、アカウント
ポリシー、アプリケーション定義、および検索用サービスアカウントは `terraform-kanidm/mail.tf`
が宣言するが、**所属 (誰がメンバーか) と個人アカウントそのものは Terraform の管理対象に
含めない。**個人の識別子を公開リポジトリの差分に残さないための境界であり、他のグループと
同じ方針である。

人手による操作となるのは次の 4 つである。

1. 利用者アカウントの作成。アカウント名をメールアドレスのローカル部と一致させる。bind DN を
   `spn=%{user},app=mail,...` の形で組み立てるため、一致していないアカウントは認証が成立しない。
2. `mail` 属性の設定 (`kanidm person update <名前> --mail <アドレス>`)。**これを省くと外部からの
   受信が成立しない。**宛先の照合 (`LDAP_QUERY_FILTER_USER` / `LDAP_QUERY_FILTER_DOMAIN`) は
   `mail` 属性だけを条件とするため、未設定のアカウントは宛先として存在しない扱いになり、postfix は
   受信を拒否する。送信の認証は bind DN テンプレート方式で `mail` を参照しないため、`mail` が
   未設定でも送信だけは成立してしまう。片方だけが動く状態になるため、設定漏れが表に出にくい。
3. 主資格情報 (パスワードと TOTP) の設定。利用者本人の対話操作を要する。
4. `mail_users` への追加。Kanidm の Web UI / CLI、または `PUT /v1/group/mail_users/_attr/member`
   で行う。

`mail` 属性が設定されているかは、検索用サービスアカウントの経路で確認できる。

```
docker exec mailserver postmap -q <アドレス> ldap:/etc/postfix/ldap-users.cf
```

値が返らない場合、`mail` が未設定であるか、`mail-ldap-search` が `mail` を読めていない
(`idm_mail_servers` への所属が失われている) かのいずれかである。Kanidm は読み取り許可が欠けている
場合もエラーではなく 0 件を返すため、値が空であること自体は両者を区別しない。

区別は LDAP の経路だけで付く。`/etc/postfix/ldap-users.cf` を雛形にして
`query_filter = (&(class=group)(name=idm_mail_servers))`、`result_attribute = member` とした
一時ファイルをコンテナ内に作り、`postmap -v -q x ldap:<一時ファイル>` を引く。
`spn=mail-ldap-search@...` が返れば委譲は実在するので、原因は `mail` 属性の未設定に絞られる。

是正 (`kanidm person update`) だけが対話ログインを要する。切り分けには要らない。

所属していないアカウントでは、アプリケーションパスワードの発行そのものが成立しない。ドメインの
既定のアカウントポリシーがパスワード単体の資格情報を許容せず、これを緩めるポリシーは
`mail_users` に紐づくものだけが与えるためである。

`_attr/member` の更新は属性の集合全体を置き換える。現在の一覧を取得してから追加する操作を
組み立てないと、既存の所属者が失われる。複数の担い手が同時に更新した場合も同様に失われる。

グループからの除外は、その利用者が発行したアプリケーションパスワードを一括で失効させる手段
でもある (`docs/mail-client-setup.md` を参照)。

## 利用者によるアプリケーションパスワードの発行

メールクライアントの認証に用いるアプリケーションパスワードは、利用者自身の認証済み
セッションからのみ発行できる。管理者による代理発行は認証基盤が拒否する。

発行の操作は対話的な端末を要するため**原理的に自動化できず**、宣言的な定義の対象にも
ならない。発行の具体的な手順、接続設定、および失効の手段は `docs/mail-client-setup.md` に
記述する。
