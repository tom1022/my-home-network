# Research & Design Decisions: admin-plane-rebuild

> **スコープの変更 (2026-09-05)**: 本 spec は Console セグメントの足の構築に絞り込まれた。管理経路の認証の依存の解消、`akishima` の転用と撤去、ネットワーク分離の回復は後続の `admin-plane-cutover` へ移した。**以下のうち「4. 管理経路の認証 — 循環の切り方」の節と、One-time PIN に関する記述は本 spec の設計に反映されていない。**認証は既存の Kanidm をそのまま用いる。要件の番号も縮小前のものであり、現行の `requirements.md` とは対応しない。

## Summary

- **Feature**: `admin-plane-rebuild`
- **Discovery Scope**: Complex Integration (新規に立てる Console の足 + 稼働中の到達経路の置き換え + 既存ホストの転用)
- **Key Findings**:
  - **Uptime Kuma は宣言化と噛み合わない。**設定・監視定義は SQLite にしか入らず、公式の書き込み REST API が無い。v1 にあった JSON のバックアップ / インポートは v2 で削除済み。要件 3 (宣言から再現できる) と要件 4.5 (監視対象事象の列挙) の双方を満たせない。
  - **Gatus が選定条件 4 つを全て満たす。**設定は `config.yaml` で完結し、`storage.type` の既定が `memory` (再起動で履歴が消える)。単一の Go バイナリで arm64 に対応し、`alerting.custom` で汎用 webhook に任意の本文を送れる。内蔵のダッシュボードが状態一覧そのものであるため、**別途ダッシュボードを置く必要が消える**。
  - **`tailscale serve` は 1 ノードに 1 ホスト名しか持てず、設定をファイルから流し込めない。**この 2 つの制約が、リバースプロキシを 1 枚挟む理由になる。Caddy を置くと公開対象の列挙が 1 ファイルに集約され、`tailscale serve` も `cloudflared` も「Caddy の 1 ポートへ向ける」だけに縮む。
  - **WoL は OPNsense の `os-wol` プラグインで解ける。**指定インタフェースのサブネットブロードキャスト宛に送出するため、directed broadcast の転送を許す必要がない。REST API で未登録の MAC を即時送出できるので、**対象の列挙を本リポジトリ側に置ける**。
  - **`config_src = "local"` と `cloudflare_zero_trust_tunnel_cloudflared_config` は排他。**ingress の宣言先が Terraform 側か実機のファイル側かに分かれる。

## Research Log

### 1. 死活監視の製品選定

- **Context**: 要件 4 が「収集基盤を持たない」「定義を宣言として保持する」「1GB の機体に載る」「汎用 webhook で通知する」を同時に要求する。運用者が挙げた Uptime Kuma は水準の目安であり、採用は確定していなかった。
- **Sources Consulted**:
  - [Uptime Kuma Wiki: Internal API](https://github.com/louislam/uptime-kuma/wiki/Internal-API)
  - [Uptime Kuma `clear-old-data.js` (2.5.3)](https://github.com/louislam/uptime-kuma/blob/2.5.3/server/jobs/clear-old-data.js)
  - [Uptime Kuma issue #7537](https://github.com/louislam/uptime-kuma/issues/7537) / [#3039](https://github.com/louislam/uptime-kuma/issues/3039)
  - [Gatus README](https://github.com/TwiN/gatus)
  - [monit documentation](https://mmonit.com/monit/documentation/monit.html)
- **Findings**:
  - Uptime Kuma の設定と監視定義は SQLite (既定) または MariaDB に入る。設定ファイル形式は存在しない。
  - 公式 Wiki は内部 API について「primarily designed for the application's own use and is not officially supported for third-party integrations」「Breaking changes may occur between versions without prior notice」と明記する。公開されている REST は push monitor / badge / `/metrics` / 公開ステータスページに限られ、監視定義の CRUD は socket.io 経由のみ。
  - v1 の Settings にあった Backup (JSON エクスポート / インポート) は v2 で削除されている。2.5.3 のツリーに該当コンポーネントが無く、Settings のタブ一覧にも Backup が無い。
  - メモリは公式の数値が無い。issue の報告値は slim 版で 151MB から最大 3GB、別報告で物理 0.7GB。**1GB の機体では危険側**。
  - Gatus は `config/config.yaml` が既定で、`GATUS_CONFIG_PATH` にディレクトリを指定すると `*.yaml` / `*.yml` をマージする。
  - Gatus の `storage.type` の既定は `memory` で、再起動により履歴が消える。`storage.maximum-number-of-results` の既定は 100、`maximum-number-of-events` は 50。
  - Gatus の `alerting.custom` は `url` / `method` / `headers` / `body` を持ち、`[ENDPOINT_NAME]` `[ALERT_STATUS]` `[ALERT_DESCRIPTION]` `[RESULT_ERRORS]` 等のプレースホルダを展開する。
  - Gatus は単一の Go バイナリで配布され、内蔵のダッシュボード (既定ポート 8080) を持つ。
  - monit も設定ファイルで完結し履歴を持たないが、汎用 webhook を持たず `EXEC` で外部コマンドを呼ぶ形になる。ホスト内部の資源監視には向くが、外形の死活と状態一覧の面で Gatus に劣る。
- **Implications**:
  - 死活監視は **Gatus** を採る。要件 4.4 は `storage.type: memory` の 1 行で満たされる。
  - 要件 4.6 の「一望できる画面」は Gatus の内蔵ダッシュボードで満たす。**Homepage を含むダッシュボードを別途置かない。**常駐プロセスが 1 本減る。
  - Uptime Kuma を採る場合、宣言化の道はサードパーティ (uptime-kuma-api / AutoKuma) 経由で内部 API を叩くことになり、上流の breaking change を自前で被る。要件 3 の趣旨に反するため却下する。

### 2. ダッシュボードを別立てにするか

- **Context**: 運用者が Homepage を挙げていたが、死活監視ツール自身が状態一覧を持つ場合に部品が重複する。
- **Sources Consulted**:
  - [Homepage: Configuration](https://gethomepage.dev/configs/) / [Installation](https://gethomepage.dev/installation/)
  - [Homepage `docs/installation/index.md`](https://github.com/gethomepage/homepage/blob/main/docs/installation/index.md)
  - [Homer README](https://github.com/bastienwirtz/homer)
- **Findings**:
  - Homepage の設定は `/app/config` 配下の YAML 群 (`settings.yaml` / `services.yaml` / `bookmarks.yaml` / `widgets.yaml` ほか) で完結し、宣言的な管理とは噛み合う。
  - 実行形態は Next.js で、`HOMEPAGE_ALLOWED_HOSTS` の指定が必須。公式にメモリ要件の記載は無い。
  - v2.0 から自前の認証ゲート (パスワード / OIDC) を持つが、公式自身が「We still recommend homepage be deployed behind a reverse proxy including authentication, SSL etc, and / or behind a VPN」「Homepage does not apply application-level rate limiting to password attempts」と述べている。
  - Homer はバックエンドを持たない完全な静的ファイルで、単一の `assets/config.yml` を読む。ヘルスチェック機能は持たない。
- **Implications**:
  - **ダッシュボードを別立てにしない。**Gatus の内蔵ダッシュボードが要件 4.6 を満たす。
  - リンク集が必要になった場合の追加は Homer とする。静的ファイルであるため Caddy から配信でき、常駐プロセスが増えない。本 spec では実装しない。

### 3. 到達手段 — プロキシを置くか置かないか

- **Context**: 要件 1.2 が「セグメント全体を広告しない」、1.3 が「公開する対象を個別に指定」、1.4 が「対象を列挙し宣言として保持」を求める。プロキシを置かずに `tailscale serve` と `cloudflared` の ingress だけで賄えるかを判定する。
- **Sources Consulted**:
  - [Tailscale Serve](https://tailscale.com/kb/1312/serve) / [features/tailscale-serve](https://tailscale.com/docs/features/tailscale-serve)
  - [tailscale CLI: serve](https://tailscale.com/docs/reference/tailscale-cli/serve)
  - [Tailscale Services](https://tailscale.com/docs/features/tailscale-services)
  - [tailscale issue #16313](https://github.com/tailscale/tailscale/issues/16313)
  - [cloudflared configuration file](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/)
  - [Caddyfile: basic_auth](https://caddyserver.com/docs/caddyfile/directives/basic_auth) / [patterns](https://caddyserver.com/docs/caddyfile/patterns)
  - [Traefik BasicAuth middleware](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/basicauth/)
  - [nginx linux packages](https://nginx.org/en/linux_packages.html)
- **Findings**:
  - `tailscale serve` は tailnet 内のみへの公開で、HTTPS を終端し、`Tailscale-User-Login` 等の識別ヘッダを注入する。公開範囲は tailnet に限られ、`funnel` に切り替えない限り外へ出ない。
  - `tailscale serve` の DNS 名は `device-name.tailnet-name.ts.net` に限られる。**1 ノードに 1 ホスト名。**複数の UI を分けるには `--set-path` によるパス分割になる。
  - 非 Docker の環境で serve の設定をファイルから流し込む手段が無い。Docker の `TS_SERVE_CONFIG` に相当するものが無く、要望の issue #16313 は 2025-06-18 起票で open のまま。
  - ホスト名を分けたい場合は Tailscale Services (`tailscale serve set-config --all serveconfig.json`) が該当するが、GA の状態とプラン要件が公式ドキュメントに明記されていない。
  - `cloudflared` の `ingress` は YAML の配列で、`hostname` / `path` / `service` を持ち上から順に評価し、末尾に catch-all を要求する。パスは Go の正規表現。リクエストパスは書き換えずにそのまま転送する。
  - Caddy は管理 UI 2 つを別ホスト名で振り分け、basic 認証を掛ける最小構成が約 8 行。arm64 の公式 `.deb` と apt リポジトリがあり、`basic_auth` は bcrypt / argon2id のハッシュを取り、`forward_auth` も組み込み。
  - nginx の同等構成は約 20〜25 行、Traefik は静的と動的の 2 ファイルで約 35〜40 行。Traefik には公式の `.deb` が無く tarball を自前で配置する。
  - nginx の `auth_request` は既定ではビルドされないが、Debian の `nginx-full` には同梱される。
- **Implications**:
  - **Caddy を 1 枚挟む。**理由は 2 つ。(a) `tailscale serve` の「1 ノードに 1 ホスト名」制約を Caddy 側のホスト振り分けで吸収でき、パス分割による相対パスの破綻を避けられる。(b) 公開対象の列挙が Caddyfile 1 箇所に集約され、要件 1.3 / 1.4 を単一の宣言で満たせる。
  - `tailscale serve` の非宣言な面 (ファイルから流し込めない) は、向き先が Caddy の 1 ポートだけになることで 1 コマンドに縮む。Ansible から冪等に適用する。
  - `cloudflared` の ingress も「1 ホスト名 → Caddy」の 1 エントリで済む。

### 4. 管理経路の認証 — 循環の切り方

- **Context**: 要件 2 が「管理経路の認証が管理対象に依存しない」を求める。現状は Cloudflare Access の IdP が k3s 上の Kanidm 単独で、Kanidm が落ちると管理経路に入れない。
- **Sources Consulted**:
  - [Cloudflare One-time PIN](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/)
  - [Authentication FAQ](https://developers.cloudflare.com/cloudflare-one/faq/authentication-faq/)
  - [Changelog: Cloudflare as identity provider](https://developers.cloudflare.com/changelog/post/2026-05-19-cloudflare-as-identity-provider/)
- **Findings**:
  - One-time PIN は「approved email addresses に PIN を送る、IdP を統合する代わりの手段」として組み込みで提供される。外部 IdP を設定していなくても使える。
  - PIN は発行から 10 分で失効し単回使用。新しい PIN の要求で前の PIN が無効化される。
  - 「OTP を Include ルールに使うだけでメールドメイン制限をしないと、任意のメールアドレスの人がコードを受け取ってアクセスできる」と明記されている。**メールリストまたはドメイン制限との併用が必須。**
  - 1 つの Access application に複数の IdP を同時に設定し、利用者に選ばせる構成が公式に可能。IdP が 1 つのときに使う *Apply instant authentication* は、複数を選ばせたい場合には有効化しない。
  - Terraform では `cloudflare_zero_trust_access_identity_provider` の type に `onetimepin` を指定する。
  - 2026-05-19 の変更で、新規作成の Zero Trust アカウントは Cloudflare 自身が既定 IdP になり OTP は自動追加されなくなった。既存のアカウントには影響しない。
- **Implications**:
  - Cloudflare 経路の認証を **One-time PIN** に切り替える。宛先は運用者のメールアドレス 1 件に限定する。**Kanidm への依存が消え、要件 2.1 / 2.3 が成立する。**
  - **PIN の宛先を自ホストのメール基盤に置かない。**メール基盤は k3s 上の `mailbox` と VPS の docker-mailserver に依存しており、そこへ送ると別の循環を作る。宛先は外部の事業者のメールアドレスとする。
  - tailnet 経路の認証は tailnet のノード認証と ACL が担う。こちらも Kanidm に依存しない。
  - **2 経路の認証は互いに独立した障害領域を持つ。**Cloudflare 経路は Cloudflare と外部メールに、tailnet 経路は Tailscale の制御平面に依存する。要件 1.6 の「もう 1 つの経路」が成立する。

### 5. Raspberry Pi 3 の起動構成

- **Context**: 運用者が「microSD は起動区画のみ、`root=` は USB 接続のドライブ」と決定した。この構成の公式な裏付けと、運用上の落とし穴を確定する。
- **Sources Consulted**:
  - [Raspberry Pi OS release notes (2023-10-10)](https://downloads.raspberrypi.org/raspios_armhf/release_notes.txt)
  - [config.txt documentation](https://www.raspberrypi.com/documentation/computers/config_txt.html)
  - [pi-gen `cmdline.txt`](https://github.com/RPi-Distro/pi-gen/blob/master/stage1/00-boot-files/files/cmdline.txt) / [`04-set-partuuid`](https://github.com/RPi-Distro/pi-gen/blob/master/export-image/04-set-partuuid/00-run.sh)
  - [kernel-parameters.txt](https://www.kernel.org/doc/Documentation/admin-guide/kernel-parameters.txt)
  - [Raspberry Pi documentation: USB boot modes](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html)
  - [raspi-config](https://github.com/RPi-Distro/raspi-config/blob/master/raspi-config) / [raspi-firmware postinst](https://salsa.debian.org/debian/raspi-firmware/-/raw/master/debian/raspi-firmware.postinst)
- **Findings**:
  - boot 区画のマウント先は **`/boot/firmware/`**。Bookworm (2023-10-10) のリリースノートに `/boot mount point moved to /boot/firmware` と記載される。同時にカーネルとファームウェアが Debian パッケージ (`linux-image-rpi-*` / `raspi-firmware`) 経由の配布へ変わった。
  - 出荷時の `cmdline.txt` は `root=PARTUUID=<IMGID>-02` の形で、`rootwait` を含む。`PARTUUID` の採用理由はリリースノートに `Use PARTUUID to support USB boot` と明記される。
  - `rootwait` は「root デバイスが現れるまで無期限に待つ。USB や MMC のように非同期に検出されるデバイスに有用」。`rootdelay=` は固定秒数の待機で、出荷時には入っていない。
  - USB からの起動可否: 3B+ は「out of the box」で対応、3B は `program_usb_boot_mode=1` による OTP の書き込みが要る。**ただし公式ドキュメント内で 3B+ の扱いが 2 箇所で食い違っている** (`USB boot modes` 節は 3B+ を要設定に含め、`USB mass storage boot` 節は不要としている)。OTP の変更は恒久で取り消せない。
  - boot 区画の読み取り専用運用は公式のオプション。raspi-config の *Write-protect Boot Partition* が該当し、実体は `/etc/fstab` の boot 行に `ro` を足すだけ。overlayfs 側のコードは書き込みが必要なとき `mount -o remount,rw /boot` を行い、失敗すれば中断する。
  - `raspi-firmware` の postinst は `set -e` の下で `cp -r /usr/lib/raspi-firmware/* /boot/firmware/` を実行する。**boot 区画が読み取り専用のままだとパッケージ設定がエラー終了する。**
- **Implications**:
  - `root=PARTUUID=` と `rootwait` を使う。どちらも出荷時の既定であり、逸脱ではない。
  - **OTP の書き込みは行わない。**OTP が制御するのはブートローダの起動元であって `root=` の向き先ではない。SD に boot 区画を残す構成では効かない。公式が 3B 向けに案内する `bootcode.bin`-only boot mode (「SD からは `bootcode.bin` だけ読み、OS の残りは USB に置く」) が OTP 不要の回避策として提示されていることが傍証になる。**ただしこの構成について OTP 不要と直接述べた公式記述は見つからなかったため、実機での確認を要する。**
  - boot 区画は読み取り専用で運用し、**カーネルとファームウェアの更新の前後で `rw` に戻す手順を宣言に含める。**戻さずに `apt` を走らせるとパッケージ設定が失敗する。

### 6. 遠隔起動 (Wake-on-LAN)

- **Context**: 要件 8.3 が「対象が別のセグメントにある場合にも到達する」を求める。magic packet はブロードキャストであり、そのままでは VLAN を越えない。
- **Sources Consulted**:
  - [OPNsense Wol API](https://docs.opnsense.org/development/api/plugins/wol.html)
  - [os-wol `WolController.php`](https://github.com/opnsense/plugins/blob/master/net/wol/src/opnsense/mvc/app/controllers/OPNsense/Wol/Api/WolController.php) / [`Makefile`](https://github.com/opnsense/plugins/blob/master/net/wol/Makefile)
  - [OPNsense Firmware API](https://docs.opnsense.org/development/api/core/firmware.html) / [Use the API](https://docs.opnsense.org/development/how-tos/api.html)
  - [RFC 2644](https://www.rfc-editor.org/rfc/rfc2644)
  - [Debian Wiki: WakeOnLan](https://wiki.debian.org/WakeOnLan) / [ethtool(8)](https://manpages.debian.org/trixie/ethtool/ethtool.8.en.html)
  - [wol(1) FreeBSD Ports](https://man.freebsd.org/cgi/man.cgi?query=wol&sektion=1&manpath=FreeBSD+Ports)
- **Findings**:
  - OPNsense の Wake-on-LAN は**組み込みではなくプラグイン** `os-wol` (ports の `net/wol` に依存)。UI は Services → Wake on LAN (`/ui/wol`)。プラグインの導入は `POST /api/core/firmware/install/os-wol` でも行える。
  - コントローラは指定インタフェースの IPv4 と subnet から**サブネットブロードキャストアドレスを計算**し、`wol -i <broadcast_ip> <mac>` を実行する。**ルータ自身が対象 VLAN 上で送出するため、directed broadcast の転送を許す必要がない。**
  - 当該インタフェースの IPv4 が静的でないと `Incorrect IPv4 configuration on interface` で失敗する。
  - `POST /api/wol/wol/set` に `{"wake": {"interface": "<if>", "mac": "<MAC>"}}` を渡すと、**config に保存せずその場で送出する**。認証は API key / secret の HTTP Basic。
  - RFC 2644 (BCP 34) は directed broadcast の受信と転送を既定で無効にすることを要求する。動機は Smurf 攻撃の増幅器化の防止。
  - 静的 ARP を置いた unicast WoL も成立する (`wakeonlan(1)` が「Unless you have static ARP tables you should use some kind of broadcast address」と述べる)。OPNsense 側の受け皿は Interfaces → Neighbors → Static Assignments。
  - Debian 側の恒久化: 「most Linux drivers disable the WOL feature on boot」。systemd-networkd の `.link` に `WakeOnLan=magic`、ifupdown なら `ethernet-wol g`、NetworkManager なら `802-3-ethernet.wake-on-lan magic`。
  - 対応確認は `ethtool <iface>` の `Supports Wake-on:` と `Wake-on:` の 2 行。`g` が magic packet。設定は `ethtool -s <iface> wol g`。
  - ACPI 上、WoL がサポートされるのは S3 / S4。**S5 (soft off) からの起動は仕様上許容されるが保証されず、BIOS / UEFI 設定とマザーボード次第。**
  - FreeBSD の `wol(1)` は既定の宛先ポートが **UDP/40000**、Debian の `wakeonlan` は 9。`os-wol` は `-p` を渡さないため 40000 で出る。magic packet はペイロードで判定されるため通常は問題にならない。
- **Implications**:
  - **送出は OPNsense に任せる。**directed broadcast の転送を有効化しない。要件 6 (分離の回復) と逆行する設定を追加せずに済む。
  - **対象の列挙は本リポジトリに置く。**`/api/wol/wol/set` の `wake` 形式が config に保存しないため、OPNsense 側に MAC を登録する必要がない。要件 8.2 が宣言として満たされる。
  - 起動の要求は Ansible の playbook から発行する。要件 8.4 の認証は OPNsense の API key / secret が担い、値は Infisical から供給する。**新しい常駐プロセスも Web の口も増やさない。**
  - 対象側の対応確認 (要件 8.5) は `ethtool` の出力で行い、S5 からの起動可否は BIOS / UEFI の設定を含めて実機で確認する。物理作業として切り出す。

### 7. Cloudflare トンネルの宣言先

- **Context**: 既存の `guacamole` トンネルは `config_src = "cloudflare"` で ingress が Terraform 管理外、かつ破棄が禁じられている。新しいトンネルの ingress をどこに宣言するかを決める。
- **Sources Consulted**:
  - [`cloudflare_zero_trust_tunnel_cloudflared` (v5.24.0)](https://github.com/cloudflare/terraform-provider-cloudflare/blob/v5.24.0/docs/resources/zero_trust_tunnel_cloudflared.md)
  - [`cloudflare_zero_trust_tunnel_cloudflared_config` (v5.24.0)](https://github.com/cloudflare/terraform-provider-cloudflare/blob/v5.24.0/docs/resources/zero_trust_tunnel_cloudflared_config.md)
  - [create a locally-managed tunnel](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/create-local-tunnel/)
- **Findings**:
  - `config_src` の取りうる値は `"local"` と `"cloudflare"`。「If `local`, manage the tunnel using a YAML file on the origin machine. If `cloudflare`, manage the tunnel on the Zero Trust dashboard.」
  - **`config_src = "local"` と `cloudflare_zero_trust_tunnel_cloudflared_config` は排他。**後者は Cloudflare 側に設定を置く方式に属する。
  - v5 では `cloudflare_zero_trust_tunnel_cloudflared_config` の `config` がブロックではなく属性になり、`config = { ingress = [ { hostname, service, path, origin_request } ] }` の形を取る。v4 の `config { ingress_rule { } }` とは異なる。
  - ローカル管理のトンネルのパスワードは `tunnel_secret` (v4 の `secret` から改名、32 バイト以上の base64)。
  - ローカル管理では `cert.pem` (アカウント証明書) と `<TUNNEL-UUID>.json` (トンネル資格情報) が実機に要る。
- **Implications**:
  - **`config_src = "cloudflare"` を採る。**理由は 2 つ。(a) ingress が 1 エントリ (`console` → Caddy) しか無いため、実機にファイルを置く利点が小さい。(b) 既存の `kubernetes` トンネルが同じ形で Terraform に宣言されており、パターンが揃う。
  - 実機側には `cloudflared` のトンネル token のみを供給する。**現状の akishima のように `ExecStart=` へ平文で埋めず、`EnvironmentFile` (0600) から与える** (要件 3.6)。

### 8. Ansible からの適用と既存 role の再利用

- **Context**: Console の足を構成管理の対象に含める (要件 3.1) にあたり、既存の資産で賄える範囲を確定する。
- **Sources Consulted**: 本リポジトリの読み取り (gap-analysis.md 第 2 節に詳細)
- **Findings**:
  - `ssh_authorized_keys` はアーキテクチャ・ディストリビューション非依存でそのまま適用できる。
  - `systemd_failure_notify` は shell と webhook のみでアーキテクチャ非依存。要件 4.10 を満たす形で本文が書かれている (journal 抜粋を載せない)。
  - Tailscale の配置は `vps_proxy` role の内部に埋没しており、独立した role になっていない。再利用には抽出が要る。
  - `storage_disk` role は `/dev/disk/by-path` の `*-scsi-*` を前提とするが、Console の足のルートドライブは OS 導入時に用意するため対象外。
  - become パスワードの供給は `host_vars/vps/main.yml` の `ansible_become_password` が唯一の前例。
- **Implications**:
  - `ssh_authorized_keys` と `systemd_failure_notify` はそのまま適用する。
  - Tailscale は `tailscale_node` role として抽出し、`vps_proxy` と Console の足で共有する。**抽出時に `vps_proxy` の「再起動後に tailnet SSH の復帰を待つ」ハンドラの挙動を落とさない。**落とすと VPS への到達を失う。
  - become パスワードは `host_vars` に `lookup('env', ...)` で束縛し、Infisical に登録する。

### 9. ブラウザからの端末と、非対話クライアントからの到達

- **Context**: 要件 1.8〜1.11 が追加された。作業機に固有の設定を要求せず、単一の起点から管理画面と対話的な端末の双方へ到達し、かつ非対話のクライアント (作業機の上で動くエージェント) からも成立することを求める。Guacamole の廃止で失われる「ブラウザからの SSH」を、より軽い手段で回復する必要がある。
- **Sources Consulted**:
  - [Tailscale SSH Console](https://tailscale.com/docs/features/tailscale-ssh/tailscale-ssh-console) / [Tailscale SSH](https://tailscale.com/kb/1193/tailscale-ssh) / [tags](https://tailscale.com/kb/1068/tags)
  - [Cloudflare Browser-rendered terminal](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/non-http/browser-rendering/) / [SSH browser rendering](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/use-cases/ssh/ssh-browser-rendering/)
  - [Cloudflare Access service tokens](https://developers.cloudflare.com/cloudflare-one/access-controls/authenticate-agents/) / [Access policies](https://developers.cloudflare.com/cloudflare-one/access-controls/policies/)
  - [ttyd](https://github.com/tsl0922/ttyd) / [Wetty](https://github.com/butlerx/wetty) / [sshwifty](https://github.com/nirui/sshwifty) / [Homer](https://github.com/bastienwirtz/homer)
- **Findings**:
  - **Tailscale SSH は Tailscale 自身が port 22 を claim して終端する。**対象ホストの sshd を必要としない。認証と認可は tailnet の identity と ACL の SSH access rule が行う。全プランで利用できる。
  - **Tailscale SSH Console** は管理コンソールのブラウザから WebAssembly の一時ノードを生成して SSH を張る。全プランで利用でき作業機に何も入れないが、**セッションは Tailscale の管理コンソールからしか開始できない**。
  - **`check` モードはタグ付きノードを送信元とする rule に書けない。**公式が「An SSH access rule from a tagged device cannot be in check mode」と明記し、加えて「Choosing to always require check mode may cause unexpected behavior with automation tools that open many SSH connections in a short time span, like Ansible」と注意する。
  - **タグを事前付与した auth key でノードを参加させると、鍵の期限が既定で無効化される** (「the tagged device's key expiry is disabled by default」)。
  - Cloudflare の **Browser-rendered terminal** は SSH / VNC / RDP に対応するが、SSH は「**user email prefixes must match their username on the server**」という制約を持ち、sshd の KEX を特定の 5 種のいずれかに合わせる必要がある。self-hosted の public application のみでパス単位の指定は不可。
  - **Cloudflare Access の service token** は「static credential pairs that authenticate requests without a browser login. Use them for automated workflows where no user is present」として自動化クライアント向けに公式に案内される。ヘッダは `CF-Access-Client-Id` / `CF-Access-Client-Secret`、policy の Action を **Service Auth** にし Include に **Service Token** を置く。**ただしこれは HTTP のリクエストの認証手段であり、SSH のセッションを張る経路ではない。**
  - `ttyd` は aarch64 の静的バイナリが **1,370,112 バイト**の単一ファイル。接続先は起動時の引数で固定する。**既定は読み取り専用で、書き込みには `-W` が要る。**`-O` で別 origin からの WebSocket を拒否できる。`-c user:pass` による基本認証を持つが、**資格情報がプロセスの引数に載る**。
  - Wetty は Node.js のランタイムを常駐させる (Node >= 20 必須)。sshwifty は 13MB で接続先を利用者が指定でき `Presets` で一覧を宣言できるが、公式が「DO NOT add any secret information into Preset」と警告する。
  - Homer は「full static html/js dashboard, based on a simple yaml configuration file」で常駐プロセスを持たない。ビルド済みの `homer.zip` が配布され、設定は `assets/config.yml` 1 ファイル。**`file://` では動かないため HTTP サーバからの配信が要る。**
- **Implications**:
  - **非対話クライアントの経路は tailnet に置く。**作業機をタグ付きノードとして参加させ、その送信元からの SSH rule を `accept` にする。タグ付きの送信元には `check` を書けないため、ブラウザでの再認証が構造的に発生しない。要件 1.11 がこれで成立する。
  - **副次的に要件 7.7 も解ける。**タグ付与により鍵の期限が既定で無効化される。`akishima` のみが期限を持っていた状態を繰り返さない。
  - **Cloudflare のブラウザ描画 SSH は採らない。**メールのローカル部とサーバ上のログイン名の一致という制約が、One-time PIN の宛先を外部の事業者のアドレスにする決定と衝突する。加えてブラウザ専用であり、非対話クライアントからは同じ経路を使えない。
  - **ブラウザからの端末は `ttyd` を自前で置く。**Caddy の背後に置けば **tailnet 経路と Cloudflare 経路の双方**で使える。Tailscale SSH Console は tailnet 経路でしか使えず、tailnet が落ちているときに役に立たない。要件 1.6 の「もう 1 つの経路」と要件 1.9 を同時に満たすのは `ttyd` だけである。
  - **`ttyd` の基本認証を `-c` で渡さない。**資格情報がプロセスの引数に載り、`akishima` の cloudflared と同じ失敗様式になる。`127.0.0.1` に bind し、認証は Caddy に一任する。
  - **起点は Homer の静的ファイルを Caddy から配信する。**常駐プロセスが増えない。要件 1.9 の「単一の起点」がこれになる。
  - Cloudflare の service token は、tailnet が落ちたときの**非対話クライアントの予備経路**として管理画面への HTTP に用いる。SSH の予備にはならない。


### 10. `tailscale serve` のポートと Tailscale Services の提供状況

- **Context**: 設計で Caddy を到達手段の集約点に置いたが、`tailscale serve` の DNS 名がノードの MagicDNS 名 1 つに限られるため、tailnet 経路ではホスト名で対象を振り分けられない。振り分けの軸をポートに変える案の成立可否と、以前「GA の状態とプラン要件が不明」として却下した Tailscale Services の現状を確定させる。
- **Sources Consulted**:
  - [tailscale serve CLI reference](https://tailscale.com/docs/reference/tailscale-cli/serve) / [KB 1312](https://tailscale.com/kb/1312/serve) / [KB 1242](https://tailscale.com/kb/1242/tailscale-serve)
  - [KB 1223 Funnel](https://tailscale.com/kb/1223/funnel) / [KB 1153 HTTPS](https://tailscale.com/kb/1153/enabling-https)
  - [`cmd/tailscale/cli/serve_v2.go`](https://github.com/tailscale/tailscale/blob/main/cmd/tailscale/cli/serve_v2.go) / [`ipn/serve.go`](https://github.com/tailscale/tailscale/blob/main/ipn/serve.go)
  - [Tailscale Services GA (2026-02-19)](https://tailscale.com/blog/services-ga) / [Services docs](https://tailscale.com/docs/features/tailscale-services)
- **Findings**:
  - **`serve` の `--https` に許可ポートの制限は無い。**実装上の検証は `if v > math.MaxUint16` の上限のみで、ホワイトリストが存在しない。フラグ省略時の既定が 443。
  - **「443 / 8443 / 10000」の制限は Funnel 専用。**実体は `CheckFunnelPort` で、呼び出し元は `CheckFunnelAccess` のみ。`serve_v2.go` 内の funnel 検証は `subcmd == funnel` でガードされた 1 箇所に限られる。serve と funnel が共有する制約は「同じポート番号を両方に同時に使えない」ことだけ。
  - 異なるポートの serve は別エントリとして共存する。失敗するのは同一のマウントポイントに複数のタイプを指定した場合のみ (`cannot serve multiple types for a single mount point`)。
  - 証明書は tailnet の DNS 名 (`machine-name.tailnet-name.ts.net`) に対して発行され、ポートに紐づかない。`messageForPort()` は 443 / 80 以外のとき URL に `:port` を付けて表示するため、非標準ポートは想定された利用形態である。
  - **Tailscale Services は 2026-02-19 に GA になっている。**「Tailscale Services is now generally available」「available on all plans」と明記され、Personal を含む全ティアで最大 10 サービス、追加課金の記述は無い。
  - Services は各サービスが独自の安定 MagicDNS 名を持ち、ノードのホスト名とは別になる。書式は `tailscale serve --service=svc:<name> --https=443 127.0.0.1:<port>`。1 ノードが複数のサービスをホストできることを公式が明示している。
  - **`serve set-config` という個別のコマンドは公式リファレンスに存在しない。**設定ファイル方式は「Tailscale Services configuration file」として別に文書化されている。
- **Implications**:
  - **前回の調査で Tailscale Services を「GA の状態とプラン要件が不明」として却下したのは誤りだった。**GA のブログ記事に両方の記載がある。
  - ポート分割は成立する。ただし転送先の Web UI が `https://<Host>/path` の形で絶対 URL を生成する場合、ポート番号が落ちて別の対象へ飛ぶ失敗様式が残る。
  - **Services を採ると URL にポートもパスも現れないため、この失敗様式が存在しない。**加えて tailnet 経路と Cloudflare 経路の双方がホスト名で分かれ、対称になる。
  - Caddy 側の設計はどちらでも変わらない。対象ごとに `127.0.0.1:<caddy_port>` で待ち受ける形は共通で、宣言の `tailnet_port` が `service_name` に変わるだけである。


## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| A: プロキシ無し | `cloudflared` の ingress と `tailscale serve` だけで公開 | 常駐プロセスが最小 (3 本) | `tailscale serve` が 1 ホスト名しか持てずパス分割になる。管理 UI が相対パス前提だと破綻する。公開対象の列挙が 2 箇所に分かれる | 却下 |
| B: Caddy を 1 枚挟む | 両経路を Caddy の 1 ポートへ向け、Caddy が振り分ける | 公開対象の列挙が Caddyfile 1 箇所に集約。ホスト名の振り分けが可能。基本認証が組み込み | 常駐が 1 本増える (数十 MB) | **採用** |
| C: Tailscale Services | サービスごとに独立した MagicDNS 名を生やす | tailnet 経路と Cloudflare 経路の双方がホスト名で分かれ対称になる。URL にポートもパスも現れない | 上限 10 サービス | **当初は「GA の状態とプラン要件が不明」として却下したが、後の調査 (第 10 節) で GA かつ全プラン対応と判明し、根拠が消えた** |
| D: nginx を使う | 既存の `vps_proxy` と同じ実装で揃える | リポジトリ内の実装が 1 種類に揃う | 設定量が Caddy の 3 倍。`vps_proxy` は転送先の列挙を持たず、そのままでは再利用できない | 却下 (下記 Decision 参照) |

## Design Decisions

### Decision: 死活監視に Gatus を採用する

- **Context**: 要件 4 が宣言化・非蓄積・小資源・webhook 通知を同時に要求する。
- **Alternatives Considered**:
  1. Uptime Kuma — 運用者が水準の目安として挙げた候補
  2. monit — 設定ファイルで完結し履歴を持たない
  3. Gatus — 設定 YAML、`storage.type: memory`
- **Selected Approach**: Gatus を単一バイナリで導入し、`config.yaml` を Ansible の template で生成する。`storage.type` は `memory`。通知は `alerting.custom` で既存の webhook 宛先へ送る。
- **Rationale**: 選定条件 4 つを全て満たす唯一の候補。加えて内蔵ダッシュボードが要件 4.6 を満たすため、部品が 1 つ減る。
- **Trade-offs**: 履歴が再起動で消えるため、事後に「いつから落ちていたか」を追えない。要件 4 の前提 (気づくことが目的であり傾向の分析は目的でない) と整合するため許容する。
- **Follow-up**: `config.yaml` の記述が要件 4.5 の「監視対象事象の一覧」を兼ねることを、設計と実装の双方で明示する。

### Decision: Caddy を到達手段の集約点に置く

- **Context**: 公開対象の列挙を 1 箇所に持ちたい (要件 1.4) が、`tailscale serve` はファイル宣言ができずホスト名も 1 つに限られる。
- **Alternatives Considered**:
  1. プロキシを置かない (Option A)
  2. Caddy (Option B)
  3. nginx (Option D) — 既存の `vps_proxy` と実装を揃える
- **Selected Approach**: Caddy を Console の足に置き、`tailscale serve` と `cloudflared` の双方を Caddy の待受へ向ける。Caddyfile は Ansible の template で、転送先の一覧を変数から生成する。
- **Rationale**: nginx を採ると実装は揃うが、`vps_proxy` には転送先を列挙するデータ構造が現存しない (Workers 移設時に削除済み) ため、いずれにせよ新規設計になる。それなら設定量が 1/3 で基本認証が組み込みの Caddy を採る方が小さい。**「既存に揃える」利点が、揃える先の実体を失っているため成立しない。**
- **Trade-offs**: リポジトリ内に nginx と Caddy が併存する。役割が明確に分かれる (VPS の公開系 vs Console の管理系) ため許容する。
- **Follow-up**: `vps_proxy` には手を入れない。Caddy の導入は Console の足に閉じる。

### Decision: Cloudflare 経路の認証を One-time PIN に切り替える

- **Context**: 要件 2.1 / 2.3 が、管理経路の認証が管理対象に依存しないことを求める。
- **Alternatives Considered**:
  1. Kanidm を Console 側へ移設する — 依存の向きは切れるが、可用性が k3s 3 ノードより下がり、移設そのものが大きい
  2. Cloudflare Access の One-time PIN — 外部 IdP を要さない組み込みの手段
  3. Caddy の基本認証のみ — Cloudflare 経路にも Access を掛けず、Caddy だけで守る
- **Selected Approach**: Cloudflare Access の IdP を `onetimepin` にし、Include ルールを運用者のメールアドレス 1 件に限定する。**PIN の宛先は外部の事業者のメールアドレスとし、自ホストのメール基盤に向けない。**Caddy 側の基本認証は二重の防御として残す。
- **Rationale**: IdP の移設を伴わずに循環だけが切れる。運用者が挙げていた「より軽い折衷」に一致する。
- **Trade-offs**: 認証の強度が Kanidm の OIDC (パスワード + TOTP) より下がる。Caddy の基本認証との二段で補う。tailnet 経路はノード認証で守られるため、常用はそちらになる。
- **Follow-up**: 要件 2.6 に従い、運用者本人の資格情報で 2 経路とも端から端まで 1 回通して確認する。

### Decision: 遠隔起動の送出を OPNsense に委ね、列挙は本リポジトリに置く

- **Context**: 要件 8.3 の VLAN 越え。
- **Alternatives Considered**:
  1. OPNsense の `os-wol` の API を叩く
  2. Proxmox のノードから送出する — 対象が Proxmox のノード自身の場合に使えない
  3. directed broadcast の転送を有効化する — RFC 2644 が既定で無効を要求し、要件 6 と逆行する
  4. 静的 ARP を置いた unicast — OPNsense 側に静的エントリの管理が増える
- **Selected Approach**: `POST /api/wol/wol/set` に `{"wake": {"interface": ..., "mac": ...}}` を送る。対象の一覧は本リポジトリの変数として保持し、Ansible の playbook から発行する。
- **Rationale**: OPNsense が対象 VLAN 上で直接送出するため経路の問題が消える。config に保存しない形式のため、OPNsense 側に状態を持たせずに済む。
- **Trade-offs**: OPNsense の API key / secret という新しい資格情報が増える。Infisical で管理する。
- **Follow-up**: `os-wol` プラグインの導入自体が手作業になる (`POST /api/core/firmware/install/os-wol` で行えるが、OPNsense の構成は宣言の対象外)。`manual-operations.md` に記録する。

### Decision: ブラウザからの端末に `ttyd` を自前で置く

- **Context**: 要件 1.9 が「単一の起点から管理画面と対話的な端末の双方へ到達させる」を求める。Guacamole の廃止でこの能力が失われる。
- **Alternatives Considered**:
  1. Tailscale SSH Console — 作業機に何も入れずブラウザから SSH できる。全プランで利用可
  2. Cloudflare の Browser-rendered terminal — トンネルの service を SSH にして Access 配下に置く
  3. `ttyd` を Caddy の背後に置く
  4. `sshwifty` — 接続先の一覧を `Presets` で宣言でき、1 プロセスで複数の宛先を扱える
- **Selected Approach**: `ttyd` を宣言された宛先ごとに 1 ユニット起動し、`127.0.0.1` に bind して Caddy の背後に置く。認証は Caddy の基本認証に一任する。
- **Rationale**: **tailnet 経路と Cloudflare 経路の双方で使える唯一の候補。**Tailscale SSH Console は tailnet 経路でしか使えず、tailnet が落ちた場合に役に立たない。Cloudflare のブラウザ描画 SSH はメールのローカル部とログイン名の一致を要求し、One-time PIN の宛先を外部のアドレスにする決定と衝突する。`ttyd` は aarch64 で 1.37MB の単一バイナリであり、1GB の機体への影響が小さい。
- **Trade-offs**: 宛先ごとにプロセスが 1 本増える。宛先は 2〜3 件を見込むため許容する。`sshwifty` なら 1 プロセスで済むが 13MB あり、利用者が接続ごとに資格情報を入力する形になる。
- **Follow-up**: `-W` を付けないと読み取り専用のままである。`-O` で origin の検査を有効にする。**`-c` を使わない** (資格情報がプロセスの引数に載るため)。

### Decision: 作業機をタグ付きノードとして tailnet に参加させる

- **Context**: 要件 1.11 が非対話のクライアントからの到達を求める。Tailscale SSH の `check` モードはブラウザでの再認証を要求するため、自動化されたクライアントを妨げる。
- **Alternatives Considered**:
  1. SSH access rule を `accept` にする (利用者ノードのまま)
  2. 作業機をタグ付きノードとして参加させ、その送信元からの rule を `accept` にする
- **Selected Approach**: タグを事前付与した auth key で作業機を参加させ、そのタグを送信元とする SSH access rule を `accept` にする。
- **Rationale**: **タグ付きの送信元には `check` を書けない**と公式が明記しているため、設定の誤りで対話的な再認証が復活する余地が構造的に無い。公式も Ansible のような自動化ツールとの相性の悪さを注意しており、この形が想定された使い方である。
- **Trade-offs**: 作業機が「人間の利用者のノード」ではなく「機械のノード」として扱われる。人間が使う経路と機械が使う経路の識別が tailnet 上で分かれる。
- **Follow-up**: **副次的に要件 7.7 が解ける。**タグ付与時に鍵の期限が既定で無効化される。`console-pi` にも同じ扱いを適用する。

### Decision: 起点を Homer の静的ファイルにする

- **Context**: 要件 1.9 の「単一の起点」を、常駐プロセスを増やさずに用意する。
- **Alternatives Considered**:
  1. Gatus の状態一覧を起点にする — リンクの管理機能を持たない
  2. Homer の `homer.zip` を Caddy の `file_server` で配信する
  3. 手書きの `index.html` を 1 枚置く
- **Selected Approach**: Homer のビルド済み配布物を Caddy から静的に配信し、`assets/config.yml` を Ansible の template で生成する。
- **Rationale**: 常駐プロセスが増えない。設定が YAML 1 ファイルで完結し、公開対象の宣言から生成できる。手書きの HTML より保守が軽い。
- **Trade-offs**: 配布物の取得と展開の手順が増える。`file://` では動かないため Caddy からの配信が前提になる。
- **Follow-up**: リンクの一覧を `console_proxy_upstreams` と `web_terminal_targets` の宣言から生成し、二重管理にしない。

## Risks & Mitigations

- **Tailscale role の抽出で VPS への到達を失う** — `vps_proxy` の「再起動後に tailnet SSH の復帰を待つ」ハンドラを抽出後も保持する。抽出は Console の足が独立して到達可能になった後に行う。
- **boot 区画の読み取り専用のまま `apt` を走らせ、パッケージ設定が失敗する** — カーネル / ファームウェアの更新の前後で `rw` に戻す手順を宣言に含め、失敗を検知できるようにする。
- **OTP 不要という前提が外れる** — 公式の明文が無いため、SD の boot 区画のみで起動できることを実機で先に確認する。外れた場合は `program_usb_boot_mode=1` の書き込みが要り、これは取り消せない。
- **Grafana の UI 側アラートを確認せずに廃止し、既存の検知を失う** — 廃止の前に `grafana.db` を読める権限で確認する。読めない場合は UI へログインして確認する。
- **One-time PIN の Include ルールが緩く、任意のメールアドレスで入れてしまう** — メールアドレスを 1 件に限定する。設定後に別のアドレスで到達を試みて拒否されることを確認する。
- **Gatus の履歴が再起動で消えるため、通知を取りこぼす** — 通知は webhook で外部へ出るため、Gatus 自身の履歴の消失は通知の到達に影響しない。
- **転用した k3s ノードが `k3s_internal_ips` への追記漏れで静かに誤起動する** — 追記が無い場合に失敗するよう、変数の解決を `default('')` に頼らない形へ改める。
- **S5 からの WoL が機体によって成立しない** — 対応の可否を実機で確認し、成立しない機体は要件 8.5 に従って理由とともに記録する。

## References

- [Gatus](https://github.com/TwiN/gatus) — 死活監視の採用候補。設定と保存方式の一次情報
- [Uptime Kuma Internal API](https://github.com/louislam/uptime-kuma/wiki/Internal-API) — 宣言化が成立しない根拠
- [Caddyfile directives](https://caddyserver.com/docs/caddyfile/directives/basic_auth) — 基本認証と forward auth
- [Tailscale Serve](https://tailscale.com/kb/1312/serve) — tailnet 内公開の範囲と制約
- [tailscale issue #16313](https://github.com/tailscale/tailscale/issues/16313) — serve 設定のファイル化が未提供である根拠
- [Cloudflare One-time PIN](https://developers.cloudflare.com/cloudflare-one/integrations/identity-providers/one-time-pin/) — 循環を切る手段
- [cloudflared configuration file](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/) — ingress の形式
- [Cloudflare Terraform provider v5.24.0](https://github.com/cloudflare/terraform-provider-cloudflare/blob/v5.24.0/docs/resources/zero_trust_tunnel_cloudflared.md) — `config_src` の排他性
- [OPNsense Wol API](https://docs.opnsense.org/development/api/plugins/wol.html) — 遠隔起動のエンドポイント
- [RFC 2644](https://www.rfc-editor.org/rfc/rfc2644) — directed broadcast を採らない根拠
- [Raspberry Pi OS release notes](https://downloads.raspberrypi.org/raspios_armhf/release_notes.txt) — `/boot/firmware` への移動と PARTUUID の採用理由
- [Debian Wiki: WakeOnLan](https://wiki.debian.org/WakeOnLan) — 対象側の恒久化手段
