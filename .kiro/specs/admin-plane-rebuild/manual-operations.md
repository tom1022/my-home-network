# 手作業の記録

本 spec (`admin-plane-rebuild`) が要求する、リポジトリのコードでは完結しない手作業をここに記録する。実施者は運用者本人。

## 1. `console-pi` の物理構築 (タスク 1.1)

### 対象

ラズベリーパイ 3。Console セグメント (`192.168.10.0/24`) に接続する。

### 手順

1. **ドライブの SMART 確認**
   root に充てる USB 接続ドライブについて、書き込み前に SMART を確認する。

   ```sh
   sudo smartctl -a /dev/sdX
   ```

   `Reallocated_Sector_Ct` など再配置セクタ系の値と `SMART overall-health` が `PASSED` であることを確認する。これが唯一の正を載せる前提のため、書き込み前の確認を省略しない。

2. **OS の導入**
   microSD を boot 区画、USB 接続ドライブを root とする構成で OS (Debian 系 arm64) を導入する。
   `cmdline.txt` の `root=` を `PARTUUID=<USB ドライブの root パーティションの PARTUUID>` に指定する。`rootwait` を残す。

3. **sshd の鍵認証を有効にする**
   Tailscale SSH は有効にしない。既存 9 ホストと同じ、通常の sshd による鍵認証に揃える。

   構成管理が用いる公開鍵は Terraform 変数 `ssh_public_key` (Infisical キー `TF_VAR_ssh_public_key`) と同一のものを使う。作業機で以下を実行して値を確認する。

   ```sh
   infisical secrets get TF_VAR_ssh_public_key --plain
   ```

   得られた公開鍵 1 行を `console-pi` の `~/.ssh/authorized_keys` へ手で追記する。

4. **タグを事前付与した認証キーで tailnet へ参加させる**
   Tailscale 管理コンソールで `console-pi` 用のタグ付き auth key を発行し、参加時に付与する。
   **後からタグを張り替えない。** 所有者と ACL の適用先が変わり、その時点で到達を失う。

   ```sh
   sudo tailscale up --authkey=<発行した auth key> --ssh=false --accept-routes=false --advertise-routes=
   ```

5. **起動確認**
   SD の boot 区画のみで起動できること (OTP の書き込みを要さないこと) を実機の起動で確認する。

6. **旧環境の記憶装置の保持**
   `akishima` の記憶装置は、新しい構成の成立を確認するまで取り外さず保持する。破棄・再利用しない。

### 完了条件

- 上記の実施内容が本ファイルに記録されている
- 作業機から `ssh <ansible_user>@console-pi` で鍵認証によりログインできる

### 実施記録 (2026-09-05 実施)

- **機体**: Raspberry Pi 3 Model B Rev 1.2、DietPi (Debian 系 arm64)。`192.168.10.100` で稼働
- **SMART 確認**: root に充てる候補として作業機に USB 接続した 2 台を確認した
  - Seagate `ST9500325AS` 500GB: `overall-health PASSED` だが SMART Error Log に訂正不能読み取りエラー (`UNC`) が同一 LBA 付近で 3 件、`Load_Cycle_Count` 正規化値が閾値ぎりぎりまで低下。**不採用**
  - FUJITSU `MJA2500BH G2` 500GB: `overall-health PASSED`、`Reallocated_Sector_Ct`/`Current_Pending_Sector`/`Offline_Uncorrectable` すべて 0、エラーログなし。**採用**
  - 比較対象として Seagate `ST1000LM035-1RK172` 1TB も確認 (健全、`Reported_Uncorrect` 0)。今回は不使用
- **root の USB 移行**: 当初 `console-pi` に接続されていたのは前述の不採用ドライブ (root=SD のまま放置されていた)。これを FUJITSU 500GB へ差し替え、GPT + ext4 1 パーティションで作成し、稼働中の SD 上 root (`mmcblk0p2`) から `rsync -axHAWXS --numeric-ids` で全体をコピー。`/etc/fstab` の `/` の UUID と `/boot/firmware/cmdline.txt` の `root=PARTUUID=` を新パーティションの値に書き換えて再起動し、`/` が `sda1` (USB) に切り替わったことを確認した。**旧 SD root (`mmcblk0p2`) は削除せず残置** (フォールバック用)。`cmdline.txt` の書き換え前の内容は `/boot/firmware/cmdline.txt.sdroot.bak` に保持
- **既知のハマりどころ**: 無印 Raspberry Pi 3 Model B は `config.txt` の `max_usb_current=1` (Pi 3 B+ 以降の機能) が効かない。2.5 インチ HDD をバスパワーで繋いだ USB ポートで `mkfs.ext4` 実行中に給電不足と見られる `USB disconnect` が発生した。**対応**: 別の USB ポートへ挿し直したところ安定した。`vcgencmd get_throttled` は両ケースとも `0x0` (電圧低下フラグなし) を示しており、この機構では検知できない不安定化だった
- **公開鍵配置**: `TF_VAR_ssh_public_key` に対応する鍵で `ANSIBLE_SSH_PRIVATE_KEY` (Infisical) を使った鍵認証ログインを確認済み
- **到達経路**: 作業機から Console セグメントへ直接到達できないため、`akishima` を `ssh -J` の踏み台にして到達している (`ssh -J trvlr@akishima root@192.168.10.100`)。tailnet 経由の到達は未確立

### root ドライブの SMART の実測 (`console-pi` 実機、2026-09-05)

`console-pi` に導入済みの `smartctl 7.4` で `/dev/sda` (FUJITSU MJA2500BH G2、USB 接続の 465.8G 2.5 インチ HDD) を読んだ結果。**USB-SATA ブリッジ越しでも `-d sat` の指定なしに自動検出でき、ATA 属性がそのまま読める。**この機体は Beszel の agent の SMART の対象に含める。

| 項目 | 値 |
|------|-----|
| `SMART overall-health self-assessment test result` | `PASSED` |
| `Reallocated_Sector_Ct` (ID 5) | 0 |
| `Current_Pending_Sector` (ID 197) | 0 |
| `Offline_Uncorrectable` (ID 198) | 0 |
| `UDMA_CRC_Error_Count` (ID 199) | 0 |
| `Temperature_Celsius` | 38 (Min/Max 7/51) |
| `Power_On_Hours` | 16815 |
| `Power_Cycle_Count` | 4160 |

`mmcblk0` (28.9G microSD) は SMART を持たない。boot 区画の劣化は検知の対象外であり、読み取り専用の運用が予防としてこれに当たる。

### tailnet 参加 (2026-09-05 実施)

運用者がタグ `tag:console-pi` を付与した auth key で `tailscale up` を実行済み。実機で確認した結果:

- `RunSSH: false` (Tailscale SSH 無効。通常の sshd 鍵認証を使う)
- `AdvertiseRoutes: null` (経路広告なし。subnet router として動作していない)
- `Tags: ["tag:console-pi"]` — タグ付与によりノードキーの期限が無効化されている (`tailscale status --json` の `Self` に `KeyExpiry` が現れない)
- OS のホスト名を DietPi の既定値 `DietPi` から `console-pi` に変更し (`/etc/hostname`, `/etc/hosts`)、`tailscale set --hostname=console-pi` で MagicDNS 名も `console-pi.<tailnet>.ts.net` に揃えた。inventory.yml の `ansible_host: console-pi` がそのまま解決する
- 作業機 (tailnet 参加済み) から `ssh root@console-pi` で直接到達できることを確認した。`akishima` を踏み台にする手段は不要になった

### インベントリとの整合の是正

運用者は `console-pi` に root で直接ログインする形で鍵を配置していた (sudo 昇格のレイヤーを挟まない)。当初 `inventory.yml` は `ansible_user: trvlr` + `ansible_become_password` を想定していたため、実態に合わせて以下を修正した。

- `ansible/inventory/inventory.yml`: `console-pi` の `ansible_user` を `trvlr` → `root` に変更 (`n100`/`hp-z440`/`gitea`/`pbs` と同じ形)
- `ansible/inventory/host_vars/console-pi/main.yml` と `vault.yml.example`: 不要になった `ansible_become_password` (`CONSOLE_PI_BECOME_PASSWORD`) の宣言を削除

### 実機での適用検証 (タスク 1.4 完了条件)

- `console-pi` に `python3` が未導入だった (DietPi のミニマル環境)。導入 (`apt-get install -y python3`) 後に `ansible console-pi -m ping` が `pong` を返すことを確認
- `ansible-playbook playbooks/ping.yml` を全 10 ホスト (`console-pi` 含む) に対して 2 回連続実行し、1 回目は `console-pi` のみ `changed` (known_hosts 登録)、2 回目は全ホスト `changed=0` で冪等性を確認した
- `ansible-playbook playbooks/console.yml` (公開鍵配布) も 2 回連続実行し、1 回目から `changed=0` (運用者が事前に配置した鍵と同一のため) で冪等性を確認した。他の 9 ホストへの影響もなし

### 未実施・要検討

- **`PasswordAuthentication`**: `/etc/ssh/sshd_config.d/dietpi.conf` に `yes` のまま残っている。鍵認証は機能しているため完了条件は満たすが、無効化の要否は要検討
- **SD boot 区画のみでの起動確認 (OTP 不要)**: 今回の再起動で SD の `mmcblk0p1` から正常に起動し `root=` を USB 側に向けられることを確認できたため、この項目は満たされたとみなす
- **`console-pi` 停止時に既存 9 ホストへの適用が完走すること**: 稼働中のホストを意図的に落とすテストは行っていない。`refresh_known_hosts.yml` の `ignore_errors: true` の妥当性は、タスク 1.4 実装時に分離した scratch 環境で根拠を確認済み (詳細はタスク 1.4/1.5 実装時のログを参照)

---

## 2. OPNsense 側の手作業

### 到達可否の実測結果 (タスク 1.2、2026-09-04 実施)

`akishima` から実測した。境界 (ファイアウォール) の追加設定を要する対象は無かった。全ての公開対象・監視対象へ既存の経路で到達できる。

| 対象 | アドレス:ポート | 結果 | 備考 |
|------|------------------|------|------|
| OPNsense 管理画面 | `192.168.10.1:443` | 到達 (HTTP 200) | `console_proxy_targets` の `opnsense.upstream` は `https://192.168.10.1:443` で確定 |
| OPNsense SSH | `192.168.10.1:2222` | 到達 (SSH バナー応答) | `web_terminal_targets` の `opnsense.ssh_target` は `192.168.10.1:2222` で確定 |
| DNS フィルタ (AdGuard Home) | `192.168.10.1:3000` | 到達 (HTTP 302 → `/login.html`、AdGuard のログイン画面を確認) | `console_proxy_targets` の `adguard.upstream` は `http://192.168.10.1:3000` で確定。ルータと同一機体のため `opnsense.internal` のようなホスト名は使わずアドレスで指定する |
| Proxmox `n100` | `192.168.1.10:8006` | 到達 | |
| Proxmox `hp-z440` | `192.168.1.2:8006` | 到達 | |
| `k3s-server` | `192.168.1.150:6443` | 到達 | 管理画面は無い。資源と到達不能は Beszel の agent が担うため `gatus_endpoints` の死活の対象には含めない |
| `k3s-agent-minipc` | `192.168.1.151:22` | 到達 | |
| `k3s-agent-z440` | `192.168.1.152:22` | 到達 | |
| `nas` (ファイル共有) | `192.168.1.201` | 22 のみ到達。80/443/445/139/5000/5001/8080/9000/3000 はいずれも閉 | **管理画面を持たない。** NFS エクスポート専用ホストであり Web UI が無いため、`console_proxy_targets` (Web UI 公開) の対象には含めない。資源と到達不能は Beszel の agent が担い、`gatus_endpoints` の死活の対象には含めない |
| `pbs` (退避基盤) | `192.168.1.202:8007` | 到達 | PBS 既定の管理画面ポート。**`hp-z440` 上の LXC コンテナ**であり、コンテナ内から SMART も ZFS プールも読めない。資源と failed ユニットのみを Beszel の agent が担う |
| `vps` | `100.109.6.7:22` (tailnet) | 到達 (ポート開通を確認。host key 未登録のため対話ログインは別途 known_hosts 登録が要る) | |

### 手作業事項

現時点で OPNsense 側の追加設定 (ファイアウォール規則変更等) は不要と判明した。3 章 (到達手段) ・5 章 (遠隔起動、`os-wol` プラグインの導入) のタスク進行にあわせて、必要な手作業が出た場合はここに追記する。

### 公開鍵の登録 (タスク 3.3、web_terminal コンポーネント)

OPNsense はこのリポジトリの Ansible 管理対象外 (inventory に存在しない) であり、`console-pi` 上の ttyd (`opnsense` エントリ、`192.168.10.1:2222` 宛) が使う公開鍵の登録は自動化できない。運用者が以下を行う必要がある。

1. OPNsense へ SSH (`192.168.10.1:2222`) し、管理者アカウント (`root` 想定。実際のログインユーザー名は OPNsense の設定次第のため、接続を試みて確認する) の `~/.ssh/authorized_keys` へ以下の公開鍵を追記する。

   ```
   ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAID2laLwFoBuCWoiXfmrFlf7GTHIsH4gyNBv2S+ndVQeF console-pi-web-terminal
   ```

2. 対応する秘密鍵は Infisical prod に `CONSOLE_WEB_TERMINAL_SSH_PRIVATE_KEY` として登録済みで、`console-pi` の `web_terminal` role がこれを使って `192.168.10.1:2222` へ接続する。

**現時点でこの登録は未実施。** 登録が完了するまで、ブラウザ端末 (`127.0.0.1:7681`) 経由の OPNsense への SSH は認証で失敗する (ttyd プロセス自体は起動し、Caddy 経由でハンドシェイクまでは到達する)。

## 3. 旧環境からの読み取りで再現しないと決めたものの理由 (タスク 1.3、2026-09-04 実施)

`akishima` に `trvlr` で SSH し、`systemctl list-units`・`docker ps`・`systemctl cat cloudflared`・`lsusb` で実機を確認した (sudo はパスワードを要求され、非対話では使えなかったため root 権限を要する確認は行っていない)。

design.md の「旧環境から引き継ぐもの」表に対する実機確認の結果は以下の通り。表に無い新規の機能は見つからなかった。

| 旧環境の機能 | 実機確認 | 本 spec での扱い |
|--------------|----------|------------------|
| Guacamole の画面転送 | Docker コンテナ 3 つ (`guacamole` / `guacd` / `guac_postgres`) で稼働。`guacamole` が `0.0.0.0:8080` で bind (設計書の記載通り、全インタフェース公開かつ無認証相当) | **代替する。**`console_proxy` 経由の Web UI 到達と `web_terminal` のブラウザ端末。理由: 画面転送の代わりに URL 単位での到達で十分であり、Guacamole 自体の運用コスト (Postgres を含む 3 プロセス) を負わない |
| cloudflared | `systemctl cat cloudflared` で `ExecStart=` にトンネル token が平文で含まれることを実機で再確認した (`ps aux` からも同様に読める) | **同型で引き継ぐ。**新しいトンネルを追加し、token は `EnvironmentFile` (0600) から供給する形に改める。既存の `guacamole` トンネルは破棄しない |
| Prometheus による計測値の収集 | `prometheus.service` が稼働中 | **中央の時系列データベースとしては再現しない。**収集していた 5 件のうち OPNsense の死活は Gatus が、残りの資源は Beszel の agent が代替し、既製の機構が備えない検査は `host_health` が担う。実際の停止は `admin-plane-cutover` が担う |
| Grafana による可視化 | `grafana-server.service` が稼働中 | **再現しない。**外形の状態一覧は Gatus の内蔵ダッシュボードが、各ホストの資源の状態は Beszel の hub の画面が代替する |
| LXQt デスクトップと Chrome (RDP 経由) | `xrdp` / `xrdp-sesman` が稼働中。Guacamole の `Console` 接続定義 (RDP → 自身:3389) の実体 | **再現しない。**OPNsense と AdGuard の管理画面は Caddy 経由の Web UI で到達するため、デスクトップ環境を経由する必要が無い |
| USB シリアルコンソール | `lsusb` で FTDI FT232R USB UART (`/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0` → `/dev/ttyUSB0`) を確認。ルータ等の物理コンソールケーブルと見られる | **本 spec では移設しない。**`akishima` に接続されたまま残る。引き継ぎ先の決定は `admin-plane-cutover` が扱う |

**表に無い追加の発見**: `avahi-daemon` / `bluetooth` / `ofono` / `dundee` / `fwupd` / `thermald` / `upower` / `rtkit-daemon` が稼働しているが、いずれも LXQt デスクトップ環境に付随する汎用デーモンであり、独立した「機能」として移設や代替の判断を要するものではない。デスクトップ環境自体を再現しない決定 (上表) に含まれる。

**保護されない秘匿値**: cloudflared のトンネル token が `ExecStart=` に平文で存在することを確認した (design.md の既知の指摘と一致)。他に同様の平文秘匿値は `trvlr` 権限で確認できた範囲では見つからなかった (root 権限を要する箇所は未確認)。

## 4. Tailscale Services の名前衝突と ACL grants (タスク 3.5、2026-09-07 実施)

### 名前衝突

tailnet には `OPNsense` というホスト名の既存デバイス (ルータ自身が持つ tailscale クライアント、`tom1022@` 所有、タグ無し) が別途参加しており、その MagicDNS 名 (`opnsense.<tailnet>.ts.net`、ホスト名の小文字化) が、`console_proxy_targets` の `service_name: opnsense` から生成される Tailscale Service (`svc:opnsense`) の MagicDNS 名と衝突していた。名前解決は既存デバイス側が勝ち、作業機から `opnsense.<tailnet>.ts.net` へアクセスしても `svc:opnsense` (console-pi 経由の Caddy) には到達しない。

`service_name` を `opnsense-admin` に変更して衝突を解消した (`console_proxy_targets` の `name`/`service_name`、`public_hostname` は Cloudflare 経路用のラベルで衝突と無関係のため変更なし)。**この変更は宣言 (コード) のみ反映済みで、`console-pi` への適用 (`ansible-playbook playbooks/console.yml`) は未実施。**適用には Infisical 経由の `ssh_authorized_keys_public_key` 等の供給 (`infisical run -- ansible-playbook ...`) が要るため、運用者が実行する。

### 残り 5 件 (`adguard`, `status`, `beszel`, `opnsense-terminal`, `console-pi-terminal`) が解決しない原因

`console-pi` 側の `tailscale serve status --json` では 6 件全てが正しく登録されている一方、作業機の `tailscale status --json` には `Services` フィールド自体が一切現れない (デバイス一覧のみ)。Tailscale Services は tailnet ポリシーファイルの **grants で明示的に許可した宛先でなければ、DNS 解決の対象にすら現れない** (Tailscale 公式ドキュメント: サービスへの到達には `dst: ["svc:<name>"]` 形式の grant が必須で、grant が無いノードの netmap にはサービス自体が配信されない)。本 tailnet のポリシーファイルには現時点で `svc:` 宛の grant が無いと見られる。

**必要な手作業**: Tailscale 管理コンソールでポリシーファイルへ以下のような grant を追加する (対象は 6 件のサービス名。`opnsense` は上記の通り `opnsense-admin` に変更済み)。

```json
"grants": [
  {
    "src": ["autogroup:member"],
    "dst": ["svc:opnsense-admin", "svc:adguard", "svc:status", "svc:beszel", "svc:opnsense-terminal", "svc:console-pi-terminal"],
    "ip": ["443"]
  }
]
```

**現時点でこの grant 追加は未実施。** これが無い限り、コード側の修正 (名前衝突の解消) を適用しても 6 件とも作業機から到達できない。タスク 3.5 の完了条件 (作業機から全対象へ到達) は、コードの適用と grants の追加の両方が終わるまで満たされない。

### 追記: 実際の原因は grants ではなく VIP Service の未承認だった

上記の grants 理論は誤りだった。実際には tailnet ポリシーに `autoApprovers.services` を設定していても、Tailscale Service (VIP Service) を Define しただけではホスト側の承認 (`approved`) が自動で付かず、承認されるまで対象ノードへの TCP 接続がタイムアウトする。`tailscale_node` ロール (`ansible/roles/tailscale_node/tasks/vip_services.yml`) が Tailscale API 経由で Define と承認の両方を行うよう実装済み。grants の追加は不要だった。

## 5. tailnet 経由で basic_auth がバイパスされる問題 (タスク 3.5、2026-09-07 実施)

作業機から tailnet 経由 (`https://<service>.<tailnet>.ts.net/`) で 6 対象へアクセスすると、認証情報を渡さなくても `basic_auth` が掛からず `200`(空応答)が返っていた。`console-pi` 自身から `curl http://127.0.0.1:<port>/` を叩くと期待通り `401` になるため、原因の切り分けが必要だった。

### 原因

Caddyfile のサイトブロックのアドレスを `http://127.0.0.1:<port>` と書くと、host 部分 (`127.0.0.1`) が Caddy 内部で **Host ヘッダの厳密一致マッチャー**になる (`bind 127.0.0.1` とは無関係で、listen 先の制限にはならない)。`tailscale serve` も `cloudflared` も、クライアントが実際にアクセスした公開ホスト名 (tailnet の FQDN や公開ドメイン) を Host ヘッダに乗せたまま Caddy へ転送するため、その値が `127.0.0.1` と一致せず、`basic_auth` を含むルート全体が「不一致」として素通りする。一致するルートが無いリクエストに対して Caddy は空の `200` を返す。console-pi 自身からの `curl http://127.0.0.1:<port>/` は Host ヘッダが `127.0.0.1:<port>` になるため偶然一致し、`401` が返っていた。

Caddy の実行時設定 (`curl http://127.0.0.1:2019/config/`) を見て `"match": [{"host": ["127.0.0.1"]}]` が各ルートに付いていることを確認し、`curl -H 'Host: 127.0.0.1' http://127.0.0.1:<port>/` は `401`、`curl -H 'Host: <tailnet FQDN>' http://127.0.0.1:<port>/` は `200`(空応答)になることで実測確認した。Tailscale Service の承認前後の過渡状態 (TCP タイムアウト) とは別の問題であり、承認済みの状態でも再現する。

### 対処

`ansible/roles/console_proxy/templates/Caddyfile.j2` の全サイトブロックのアドレスを `http://127.0.0.1:<port>` から `http://:<port>` (host 部分を空) に変更した。Host ヘッダを一切マッチ条件に使わなくなり、listen 先を `127.0.0.1` に限定する役目は従来通り `bind` ディレクティブが担う。`ansible-playbook playbooks/console.yml` を再適用し、6 対象すべてで認証情報無し `401` / 正しい認証情報で到達 (`200`/`302`、バックエンド未構築の 2 件は `502`) を確認した。
