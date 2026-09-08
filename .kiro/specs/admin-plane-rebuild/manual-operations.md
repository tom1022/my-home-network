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

## 6. tailnet 経路の到達性の検証 (タスク 3.6、2026-09-08 実施)

作業機 (`expertbook`, tailnet IP `100.127.244.115`) から実測した。`console-pi` は `100.116.132.42` / `console-pi.tail6c7c64.ts.net`。基本認証の資格情報は Infisical (`CONSOLE_PROXY_BASIC_AUTH_USER` / `_PASSWORD`) から都度取得し、シェル変数以外に残していない。

### 6.1 公開対象・端末の全てへの到達 (要件 1.3, 1.6〜1.11)

`console_proxy_targets` 4 件と `web_terminal_targets` 2 件、計 6 件の Tailscale Service 全てに、非対話の `curl` から到達した。

| service_name | 認証なし | 認証あり | 備考 |
|---|---|---|---|
| `opnsense-admin` | 401 | 200 | OPNsense ログイン画面 |
| `adguard` | 401 | 302 → `/login.html` | AdGuard ログイン画面へのリダイレクト |
| `status` | 401 | 200 | Gatus の Health Dashboard |
| `beszel` | 401 | 200 | Beszel の画面本体 |
| `opnsense-terminal` | 401 | 200 | ttyd (ルータ宛) |
| `console-pi-terminal` | 401 | 200 | ttyd (console-pi 自身宛) |

認証を経ずには 401 で拒否され、正しい資格情報を渡すと到達する。要件 1.5 (認証必須) と 1.11 (非対話クライアントからの到達) を満たす。

### 6.2 起点の 1 ページからの到達性 — **未達 (設計・実装のギャップ)**

`landing_page` (Homer) は `landing_page_caddy_port` (8087) で Caddy に公開されているが、**`console_proxy_targets` / `web_terminal_targets` に含まれないため、`tailscale_node` の serve 適用対象 (`tailscale_node_serve_targets = console_proxy_targets + web_terminal_targets`) にも Terraform の `console_ingress_targets` (Cloudflare ingress) にも入っていない。**

実測結果:

- `console-pi` の `tailscale serve status --json` には 6 件の `svc:*` のみが登録され、Homer 用のエントリは存在しない
- 作業機から `https://console-pi.tail6c7c64.ts.net:8087/` および `http://100.116.132.42:8087/` はいずれも `Connection refused` (Caddy が `127.0.0.1` にのみ bind しており、`tailscale serve` によるトンネルも無いため)
- `console-pi` 自身から `curl -u <user>:<pass> http://127.0.0.1:8087/` は `200` (Caddy 自体は正常に配信している)

**影響**: 要件 1.9「単一の起点から、公開している管理画面と対話的な端末の双方へ到達させる」の起点そのものが、tailnet 経由 (経路 2) では到達できない。利用者は起点ページを経由せず、6 件の Tailscale Service の URL を個別に覚える必要がある状態になっている。design.md の「起点から端末までの流れ」および `landing_page` コンポーネントの意図 (単一の起点となるリンク集) と実装が一致していない。

**対応方針は判断を仰ぐ。**考えられる選択肢 (実装はしていない):
1. `landing_page_caddy_port` を `tailscale_node_serve_targets` および Cloudflare の `console_ingress_targets` に追加する (7 件目の Tailscale Service。上限 10 に対し余裕はある)
2. 起点ページを廃し、`gatus` (`status`) など既存エントリの 1 つに埋め込む
3. 現状を許容し、要件 1.9 の充足範囲を「個別 URL への到達」に限定し直す (要件・設計の修正を要する)

### 6.3 経路の切り替えとクライアント設定の要否 (要件 1.8, 1.10)

6 件の Tailscale Service はいずれも `https://<service_name>.tail6c7c64.ts.net/` の形で、ポートもパスも現れない URL で到達した。作業機に Tailscale クライアント以外の設定 (プロキシ、名前解決の書き換え等) を加えていない。**6.2 のギャップにより「起点ページから経路を切り替えて同じ対象へ到達する」動線自体は検証できていない** (経路 1 の起点ページも 3.8 で別途検証)。個別エントリについては、経路 2 のみで検証済み (経路 1 は 3.8 の対象)。

### 6.4 非対話クライアントからの接続と要求 (要件 1.11)

- 4 件の Web UI: `curl` (非対話) で到達し、上記 6.1 の結果を得た
- 2 件の端末 (ttyd): `GET /` (HTML 取得)・`GET /token` に加えて、`websockets` ライブラリで `wss://<service>.tail6c7c64.ts.net/ws` へ Basic 認証付きで接続し、`echo TTYD_E2E_OK` を送出して PTY のエコーで折り返しを確認した (`opnsense-terminal` は宛先 `192.168.10.1:2222`、`console-pi-terminal` は `localhost` 向けの SSH セッションが張られることを確認)。**ttyd は `-O` (Origin 検査) を有効にしており、`Origin` ヘッダを送らない/一致しないクライアントは接続直後に切断され、Caddy 側からは `502` に見える。**これはブラウザの通常の挙動 (Origin が自動的にページの origin と一致) では問題にならず、実装上の不備ではない。生の `curl`/`websockets` で検証する際は `Origin` ヘッダの付与が必須である点を記録として残す

### 6.5 宣言に無い宛先の拒否 (要件 1.3)

- 存在しない Tailscale Service 名 (`nonexistent-service.tail6c7c64.ts.net`) は名前解決自体が失敗する (NXDOMAIN)
- `console-pi` の tailnet アドレス (`100.116.132.42`) に対し、`caddy_port` (8081, 8087 等) や未宣言のポート (9999) へ直接 TCP 接続すると `Connection refused` になる。**Tailscale Service は仮想 IP 経由でのみ到達し、ノード自身のポートを消費しない**という design.md の記述通りの挙動を確認した

### 6.6 `console-pi` 自身の許可集合の実測 (要件 1.7)

`console-pi` 上で `iptables -L CONSOLE-FIREWALL-INPUT -n -v` / `ip6tables` (同内容) を実測した。

| # | in | 内容 | 対応する宣言 |
|---|----|------|--------------|
| 1 | `lo` | ACCEPT all | 必須の 3 本 (loopback) |
| 2 | `*` | ACCEPT ESTABLISHED,RELATED | 必須の 3 本 (確立済み・関連) |
| 3 | `tailscale0` | ACCEPT all | 必須の 3 本 (tailnet 全許可) |
| 4 | `*` | ACCEPT icmp | PMTUD 用の固定ルール |
| 5 | `tailscale0` | ACCEPT tcp dpt:22 | `console_inbound_allow[0]` (port 22, tcp, source tailnet) |

`console_inbound_allow` の宣言 (22/tcp/tailnet の 1 件) と実機の許可集合が完全に一致した。IPv4/IPv6 とも同一。**境界側 (OPNsense のファイアウォール、Console セグメントへの到達制御そのもの) は本 spec の対象外であり、実測していない。**Console セグメント (`192.168.10.0/24`) からのアクセス制御は `console-pi` の `eth0` に対する明示的な許可規則を持たず、到達可否は OPNsense 側の設定に委ねられている (未実測、設計上の Out of Boundary)。

### 6.7 転送先の画面が崩れずに表示されること (要件 1.3, 1.6)

認証を経た応答の Content-Type とタイトル・サイズを実測した。

| 宛先 | Content-Type | 確認内容 |
|---|---|---|
| `opnsense-admin` | text/html; charset=UTF-8 | `<title>ログイン \| OPNsense</title>` を含む完全な HTML (2813 bytes) |
| `adguard` | text/html; charset=utf-8 | `/login.html` への 302 リダイレクト |
| `status` | text/html | `<title>Health Dashboard \| Gatus</title>` (2097 bytes) |
| `beszel` | text/html; charset=utf-8 | `<title>Beszel</title>`、アプリシェル (1214 bytes) |
| `opnsense-terminal` / `console-pi-terminal` | text/html | ttyd のターミナル画面 (729693 bytes、xterm.js 込み)。6.4 のとおり WebSocket 経由の実セッションも成立 |

いずれも応答が破損・空白化せず、絶対パス由来のリソース欠落は確認されなかった。

### 6.8 リバースプロキシ停止時の代替到達経路 (要件 1.6)

1. `console-pi` 上で `systemctl stop caddy` を実行 (`systemctl is-active` で `inactive` を確認)
2. Caddy 経由の到達 (`https://opnsense-admin.tail6c7c64.ts.net/`) が `502` になることを確認 (`tailscale serve` はトンネル自体を維持するが、バックエンドの Caddy が無いため失敗する)
3. **その間も tailnet 経由の SSH (`ssh root@console-pi`、`console_inbound_allow` の唯一のエントリ) は成立し続けることを確認した。**Caddy を経由しないこの経路が、要件 1.6 が求める「物理的な接続の変更によらない復旧経路」である
4. `systemctl start caddy` で原状復帰し、`opnsense-admin` / `status` への到達が `200` に戻ることを確認した

### まとめ

| 検証項目 | 結果 |
|---|---|
| 公開対象・端末全てへの到達 (6.1) | ○ |
| 起点の 1 ページからの到達 | **× (6.2 参照。設計・実装のギャップ。判断待ち)** |
| 経路切り替え時のクライアント設定不要 (6.3) | ○ (個別エントリのみ。起点ページ経由の切り替えは 6.2 により未検証) |
| 非対話クライアントからの接続・要求 (6.4) | ○ |
| 宣言に無い宛先の拒否 (6.5) | ○ |
| `console-pi` 自身の許可集合の実測 (6.6) | ○ (境界側は対象外、記録のみ) |
| 転送先画面の非崩壊 (6.7) | ○ |
| リバースプロキシ停止時の代替経路 (6.8) | ○ (検証後 Caddy は再起動し原状復帰済み) |

## 7. 外部経路 (Cloudflare) の到達性の検証 (タスク 3.8、2026-09-08 実施)

ブラウザで Kanidm へログインし、Cloudflare Access (`console_kanidm` ポリシー、claim `console_access@kanidm.fickledev.com`) を経由して 6 件の公開対象・端末全てへの到達を実測した。

### 7.1 前提の是正 (実装漏れ)

初回のログイン試行は **"That account does not have access."** で拒否された。Kanidm 側 (`terraform-kanidm/identities.tf`) に `console_access` グループが存在せず (Cloudflare Access ポリシーが要求する claim が Kanidm 側に無かった)、3.7 実装時の漏れと判明。運用者がグループを作成しメンバーを追加して是正した (Kanidm 利用者の所属変更にあたるため、運用者自身が実施)。

### 7.2 6 件全てへの到達結果

| public_hostname | 結果 | 備考 |
|---|---|---|
| `opnsense` | ○ (ログイン画面まで) | 7.3 参照。OPNsense 自身の CSRF 対策で実ログインは失敗 |
| `adguard` | ○ | 7.4 参照。Chrome Safe Browsing 誤検知、AdGuard 側のレート制限による一時ブロックあり |
| `status` | ○ | Gatus Health Dashboard が正常表示 |
| `beszel` | ○ (ログイン画面まで) | Basic 認証の後段に Beszel 自身のログイン画面があり二重ログインになる (7.5) |
| `opnsense-terminal` | ○ | ttyd 経由で OPNsense のコンソールメニューまで到達、鍵認証で自動ログイン |
| `console-pi-terminal` | ○ | ttyd 経由で `console-pi` の root シェルまで到達 |

いずれも Kanidm 認証 → Cloudflare Access → Caddy の Basic 認証を経て、崩れずに転送先の画面へ到達した。要件 1.1 (経路 1 の存在) を満たす。**経路 1 は確立したため、要件 1.1 の「確立しない場合は経路 2 のみで運用継続」の判断は不要だった。**

### 7.3 OPNsense: HTTP_REFERER 不整合 (運用者対応が必要)

`opnsense.fickledev.com` でログインボタンを押すと `The HTTP_REFERER "https://opnsense.fickledev.com/" does not match the predefined settings.` となり、実ログインができない。OPNsense 自身の CSRF 対策 (`System: Settings: Administration` の Alternate Hostnames) が `opnsense.fickledev.com` を許可リストに含めていないため。**OPNsense は Out of Boundary (Ansible 管理対象外) であり、この設定は運用者が直接追加する必要がある。**画面の到達自体 (GET) は問題ない。

### 7.4 AdGuard: レート制限による一時的な共有ロックアウト (既知の制約として記録、対応は見送り)

`adguard.fickledev.com` で以下 2 点を確認した。いずれも対応は行わず、記録に留める判断とした:

- **Chrome Safe Browsing の誤検知。**「Dangerous site」警告が表示された。実インフラ側の問題ではなく外部の評価データベース起因とみられる
- **AdGuardHome 自身のログイン試行ブロック (429) が発生し、Caddy 非経由の直接アクセス (`http://192.168.10.1:3000/control/login`) でも同様に再現した。**AdGuardHome のブロックは接続元の MAC アドレス単位 (既定 15 分、[公式 Discussion #6805](https://github.com/AdguardTeam/AdGuardHome/discussions/6805) より) であり、`console-pi` が AdGuard への唯一の到達点であるため、**この経路を使う誰か・何かが一度ブロック対象になると、15 分間はこの経路の全利用者がロックアウトされる。**単一到達点の構造上の弱点であり、Caddy/cloudflared 側の不具合ではない。時間経過 (15 分) で自然に解除されることを実測で確認した (`429` → `403 invalid username or password` に変化)

### 7.5 UX 課題として記録した項目 (対応は別途、今回は未実装)

検証中に運用者から次の設計変更の要望が出た。**いずれも要件・設計の見直しを要する規模のため、今回のタスク 3.6/3.8 では実装せず、次のステップ (要件・設計の修正) の入力として記録するに留める:**

- **Basic 認証 (二段目の認証) を廃止し、Caddy 自体を Kanidm と OIDC で連携させたい。**標準ビルドの Caddy は OIDC をネイティブ対応しないため、`caddy-security` 等の外部モジュールを `xcaddy` で組み込むか、`oauth2-proxy` を前段に置く構成の検討が要る。Kanidm 側に新規 OAuth2 クライアント登録も伴う
- **要件 1.3 (公開対象を個別に指定する) の見直し要求。**6 ホスト名に分離する現行の構成ではなく、Guacamole (`console.fickledev.com` 1 本) と同様に単一ドメインへ統合してほしいという要望。運用者は「要件 1.3 は間違い」と明言している

### まとめ (タスク 3.8)

| 検証項目 | 結果 |
|---|---|
| 公開対象・端末全てへの到達 (7.2) | ○ (6/6) |
| 転送先画面の非崩壊 | ○ |
| 経路 1 の確立可否の判断 (要件 1.1) | ○ 確立した。経路 2 のみへの縮退は不要 |
| 新たに判明した不備・課題 | OPNsense の HTTP_REFERER 設定 (7.3、運用者対応)、AdGuard のレート制限による共有ロックアウトリスク (7.4、対応見送り)、Basic 認証と要件 1.3 の見直し要望 (7.5、次ステップへ) |

## 8. 要件 5 (遠隔起動) の見送り (タスク 5.1〜5.3、2026-09-08 判断)

要件 5 は仕様上「望ましい能力であり、既存の機構で賄えない場合は見送る。他の要件の成立を妨げてまで実現しない」と定義されている任意機能。運用者に実装継続の可否を確認し、**今回の spec-impl では要件 5 全体 (タスク 5.1〜5.3) を見送る判断**を得た。

### 確認した内容と回答

- OPNsense の `os-wol` プラグイン・REST API の有効化 (API key/secret の発行) は未確認。この確認自体を含めて見送り対象とする
- WoL の対象範囲についての判断: VM・LXC コンテナ・VPS は物理 NIC への magic packet が届かないため技術的に対象外。対象になり得るのは Proxmox の物理ノード (`n100`, `hp-z440`) のみ、との認識を共有した
- 電源断を伴う実機検証 (対象ノード上の VM/コンテナが道連れで停止する) は今回承認しない

### 現状

- `group_vars/all/main.yml` には `opnsense_api_key` / `opnsense_api_secret` の変数束縛のみ既に存在する (別タスクで先行投入済み)。`wol_targets` の宣言、`playbooks/wol.yml` は未実装
- `os-wol` プラグインの導入・OPNsense API key/secret の発行という運用者作業は未提示・未実施
- 再着手する場合の入力: 対象を `n100` / `hp-z440` の物理ノードに限定する方向で検討し、着手前に `os-wol` 導入状況の確認と電源断検証の承認を改めて取ること

**この spec の構成・コードは一切変更していない。**6.2 で見つかったギャップ (起点ページが tailnet 経路で到達不能) は記録に留め、対応方針の判断を仰ぐ。

## 9. 常駐と保持量の実測 (タスク 4.8、2026-09-08 実施)

### 9.1 `console-pi` のメモリ使用量・load average

全ての常駐 (Caddy、ttyd x2、cloudflared、Gatus、Beszel hub、Beszel agent、host_health のタイマー群) が揃った状態、稼働 2 日 22 時間経過時点での実測 (`free -m` / `uptime`)。

```
               total        used        free      shared  buff/cache   available
Mem:             955         174         265          17         548         780
Swap:              0           0           0

 load average: 0.00, 0.14, 0.26   (4 コア)
```

`used` は 174MB、`available` は 780MB (総量 955MB の約82%) が空いている。`buff/cache` の 548MB はページキャッシュで大半が再利用可能。load average は 4 コアに対して常時 1 未満で、CPU 負荷側の懸念は無い。

常駐プロセスごとの RSS (`ps -eo pid,comm,rss --sort=-rss` 抜粋、降順):

| プロセス | RSS |
|---|---|
| tailscaled | 50.3MB |
| caddy | 44.8MB |
| beszel (hub) | 43.8MB |
| cloudflared | 38.8MB |
| gatus | 31.3MB |
| beszel-agent | 12.6MB |
| ttyd (opnsense-terminal) | 1.16MB |
| ttyd (console-pi-terminal) | 1.16MB |

ttyd 2 プロセス合計は 2.3MB に留まり、常駐の中では軽量な部類。host_health のタイマー群は通常時は非常駐 (timer 起動時のみプロセスが立つ) のため、この一覧には現れない。

### 9.2 保持している計測値の実際の量

Beszel hub のデータ永続化先は `ansible/roles/beszel_hub/defaults/main.yml` の `beszel_hub_data_dir` (`/var/lib/beszel-hub`)。実機で `du -sh` を実測:

```
8.0M    /var/lib/beszel-hub
3.5M    data.db
4.5M    data.db-wal
32K     data.db-shm
32K     auxiliary.db
```

`beszel_systems` 宣言の 10 ホスト分 (hp-z440, n100, console-pi, pbs, k3s-server, k3s-agent-minipc, k3s-agent-z440, nas, gitea, vps) を約 1.25 日分収集した時点で合計 8MB。`hub.env.j2` は `USER_EMAIL`/`USER_PASSWORD` のみを持ち、保持期間・件数を制御する環境変数は本構成に無く、Beszel 組み込みの既定の自動間引き (直近は高頻度、古いものほど間引かれて集約される) に委ねている。この増加率であれば 1GB 機体のディスク (`df -h /` で 434G 空き) に対して問題にならない量。

### 9.3 pbs (LXC コンテナ) の Beszel agent 値の由来判定

pbs は Terraform (`terraform/locals.tf`) 上で `node = "hp-z440"`、`cores = 4`、`mem = 8192` (MB) の非特権 LXC コンテナ。物理ホスト hp-z440 の実際の資源 (`nproc`=28、`free -m` total=32008MB) と比較して、Beszel hub が保持する pbs の値がどちらに由来するかを突き合わせた。

| 項目 | pbs コンテナ自身の実測 | Beszel hub の pbs レコード (`info`) | hp-z440 ホストの実測 |
|---|---|---|---|
| CPU コア数 | `nproc` = 4 | `t` = 4 | `nproc` = 28 |
| メモリ使用率 | `free -m`: 83MB / 8192MB ≈ 1.0% | `mp` = 0.98% | 28136MB / 32008MB ≈ 87.9% |
| ディスク使用率 (`/`) | `df -h /`: 1.5G / 63G ≈ 2.4% | `dp` = 2.39% | 24G / 94G ≈ 25.5% (ホストの `/`) |

Beszel hub API (`/api/collections/systems/records/<id>`) から取得した pbs の `info.mp`・`info.dp`・`info.t` は、いずれも hp-z440 ホスト全体の値ではなく、pbs コンテナ自身の cgroup 割当 (Terraform で宣言した 4 コア・8192MB・63GB ルートディスク) に一致した。Proxmox の lxcfs が LXC コンテナ内の `/proc/meminfo`・`/proc/cpuinfo` 等をコンテナのカレント割当値に仮想化しているため、Beszel agent (gopsutil 経由で `/proc` を読む) が取得する値もコンテナスコープに閉じている。

**判定: pbs の Beszel agent が報告する値はコンテナ由来であり、ホスト由来の値の混入は無かった。** タスク文が想定していた「ホストの値を返している項目があれば監視対象から外す」対応の必要性は無く、`beszel_systems` / `beszel_alerts` の宣言変更は行っていない。

### 9.4 機体容量 (1GB) に対する判断

現状の常駐一式 (Caddy、ttyd x2、cloudflared、Gatus、Beszel hub、Beszel agent) で `available` 780MB を維持しており、load average も 4 コアに対して余裕がある。**1GB 機体の容量に対して現状の常駐は見合っている。** 保持データも 8MB/1.25日という増加率で当面ディスクを圧迫しない。

将来メモリが逼迫した場合の最初の調整点は、タスク文の指示どおり端末 (ttyd) の常駐数を減らすことになるが、実測ではその 2 プロセス合計が 2.3MB と全常駐の中で最も軽く、逼迫時の実効性は低い。逼迫が生じた場合の優先候補はむしろ RSS 上位の tailscaled (50.3MB)・caddy (44.8MB)・beszel hub (43.8MB)・cloudflared (38.8MB) 側になる見込みだが、現時点でその判断が必要になるほどの逼迫は観測されていない。

## 10. 通知の到達と本文の確認 (タスク 4.9、2026-09-08 実施)

3 経路 (Gatus・Beszel・host_health/systemd_failure_notify) それぞれについて、実際に障害を起こして Discord webhook への到達を確認した。全項目、確認後に原状復帰済み。

### 10.0 前提の是正 (実装漏れ): Beszel の Discord webhook が機能していなかった

検証の過程で、**Beszel hub の資源アラート (Status/Disk/SystemdFailed) が deploy 当初から一度も Discord に届いていなかった**ことが判明した。

- `beszel_hub` role は `user_settings.settings.webhooks` に生の Discord webhook URL (`https://discord.com/api/webhooks/<id>/<token>`) をそのまま渡していた
- Beszel の通知送出は `shoutrrr` (`github.com/nicholas-fedor/shoutrrr`) 経由で、渡された URL の scheme をサービス名として解決する。生の `https://` URL は shoutrrr に認識されるサービス名ではないため、`url.Parse` の scheme が `https` になり `unknown service: https` で送信そのものが失敗する
- Beszel hub 自身の内部ログ (`/api/logs`、`message: "Failed to send shoutrrr alert"`) で実機確認した。この内部ログは systemd の journal には出ない (PocketBase の `_logs` コレクションのみに記録される) ため、`journalctl -u beszel-hub` を見ているだけでは気付けない
- shoutrrr の discord サービスが要求する形式は `discord://<token>@<webhookid>` (公式ドキュメントで確認)。**是正**: `ansible/roles/beszel_hub/defaults/main.yml` に `beszel_hub_discord_webhook_shoutrrr_url` (正規表現変換) を追加し、`tasks/main.yml` の 2 箇所 (`user_settings` の作成・更新) をこちらに差し替えた。変換後の形を検証する assert も追加した。`ansible-playbook playbooks/console.yml --limit console-pi` で適用済み、適用後は Disk アラートの再発火で内部ログにエラーが出なくなったことを確認した
- **この是正が無ければ、要件 3.1/3.2 (通知経路の一本化) は Gatus と systemd_failure_notify の 2 経路のみで、Beszel 由来のアラートは検知はしていても運用者に一切届いていなかった。**

### 10.1 外形の監視を意図的に落とす (Gatus)

`beszel-hub` を `systemctl stop` して落とした (Gatus の `beszel-hub` エンドポイントは loopback 宛の外形監視、要件 3.17 の「受けから独立した検知」に対応する対象)。

- 停止 13:34:42 UTC → 3 回連続失敗 (interval 60s) を経て 13:37:39 UTC に `[watchdog.handleAlertsToTrigger] Sending initial custom alert ... TRIGGERED` を確認 (journalctl -u gatus)
- `systemctl start beszel-hub` で復旧 → 次の成功チェックで 13:38:39 UTC に `... RESOLVED` を確認 (success-threshold 1)
- 到達: ○ (TRIGGERED・RESOLVED とも実際の Discord webhook 宛に送出。Gatus はエラー時にログを残す実装だが、該当区間にエラーログは無かった)

### 10.2 閾値検査 (host_health) と資源監視 (Beszel) 双方の到達確認

**host_health 側**: `console-pi` の `/usr/local/sbin/host-health-inode.sh` の `max_percent` を一時的に `90` → `0` に書き換え、`systemctl start host-health-inode.service` で強制的に失敗させた。

- `OnFailure=notify-failure@%n.service` が発火し、journal に `notify-failure: host-health-inode.service -> webhook HTTP 204` を確認 (実際の Discord webhook への到達、2xx)
- 閾値を `90` に戻し再実行、成功 (`status=0/SUCCESS`) を確認

**Beszel 側**: `Disk` アラート (既定 `value=85, min=10`) を `k3s-agent-z440` (実測ディスク使用率 29%) に対して `value=20, min=1` へ一時的に引き下げ、Beszel hub の API (`/api/beszel/user-alerts`) で適用した。

- 適用直後は 10.0 の未修正状態だったため送信自体が失敗 (`unknown service: https`) しており、この段階では検知 (`triggered: true` への遷移) のみ確認できた
- 10.0 の是正後に同じ手順で再実施し、`triggered: true` への遷移後の内部ログにエラーが記録されないこと (= 送信成功) を確認した
- 閾値を `value=85, min=10` に戻し、`triggered: false` への復帰を確認した

### 10.3 資源監視の受け (Beszel hub) を停止 → 外形監視 (Gatus) からの到達確認

10.1 と同一の操作 (`beszel-hub` の停止) が本項も兼ねる。Beszel hub 自身が停止している間は Beszel からの通知は原理的に発せられない (受け自体が死んでいるため) が、Gatus の `beszel-hub` エンドポイント (loopback への外形監視、Beszel hub プロセスとは独立したチェッカー) が上記 10.1 の通り TRIGGERED を送出した。**受けの死活を、受け自身に依存しない別プロセスが検知する設計 (要件 3.17) を実際の停止で確認した。**

### 10.4 計測 agent の停止 → 受け (hub) からの到達不能通知、および監視対象の分担確認

`k3s-agent-minipc` の `beszel-agent` を停止した (`sudo systemctl stop beszel-agent`)。

- 停止: 13:49:38 UTC (10.0 の是正後、実際の webhook に対して実施)
- Beszel hub の `Status` アラート (`min=5` 分) が 13:55:00 UTC に `triggered: true` へ遷移 (約 5 分 22 秒後、閾値通り)。システムの `status` フィールドも `up` → `down` に変化
- `systemctl start beszel-agent` で復旧 → `triggered: false` に復帰したことを確認
- **監視対象の分担確認**: 同時に、`console-pi` の Gatus のエンドポイント一覧 (`/api/v1/endpoints/statuses`) を確認したところ `beszel-hub`・`console-caddy`・`kanidm-ldaps-dns`・`opnsense` の 4 件のみで、**`k3s-agent-minipc` を含む `beszel_systems` の各ホストは 1 件も含まれていない**ことを設定 (`group_vars/console/main.yml` の `gatus_endpoints`) と実機の両方で確認した。Beszel agent 導入ホストの死活は Beszel の `Status` アラートが唯一の担い手であり、Gatus 側は最初から対象に含めていない設計 (タスク 4.4 で実装済み) のため、**二重通知は構造的に発生しない**ことを実測で確認した

### 10.5 通知の宛先を誤った値にする (不達と成功の区別)

`console-pi` の `/etc/systemd/notify-failure.env` の `NOTIFY_FAILURE_WEBHOOK_URL` を存在しない webhook (`https://discord.com/api/webhooks/000000000000000000/invalid-token-e2e-test-4-9`) に一時的に差し替え、`host-health-inode.service` を再度強制失敗させた。

- journal: `notify-failure: host-health-inode.service -> webhook HTTP 404` → `notify-failure: webhook delivery failed` → `notify-failure@host-health-inode.service.service` 自体が `failed` 状態になった
- 正常時 (10.2) の `HTTP 204` / `Deactivated successfully` と明確に区別できた。**不達がハンドラ自身の failed 状態として残るため、「送信成功と誤認する」経路は無い**
- 正しい webhook URL に戻し、`host-health-inode.sh` の閾値も戻して再実行し、`HTTP 204` に戻ることを確認。`notify-failure@host-health-inode.service.service` と `host-health-inode.service` の failed 状態を `reset-failed` で解消した

### 10.6 届いた通知の本文の実物確認 (要件 3.10, 3.17)

**方針**: 実際の Discord チャンネルは運用者個人の私用アカウント上にあり、目視確認のためのブラウジングは他の私的な情報 (フレンド一覧・他サーバー) に触れる範囲が広く、プライバシー上適切でないと判断した。代わりに、各経路が実際に送出したバイト列を送出元プロセス側 (systemd の journal、プロセスの実行中コマンドライン、Beszel の送出コード) から直接確認する方法をとった。

- **Gatus** (`alerting.custom.body`、`ansible/roles/gatus/templates/config.yaml.j2`): 固定テンプレート `{"content": "[ALERT_TRIGGERED_OR_RESOLVED] [ENDPOINT_NAME]"}`。変数はエンドポイント名と遷移状態のみで、応答本文・接続先詳細・秘匿値・運用者個人情報のいずれも含まれない (ソース確認、要件 3.10 を満たす)
- **notify-failure.sh** (`systemd_failure_notify`): 10.5 の実施中に実行中プロセスのコマンドライン (`ps`/`systemctl status` 経由) で実際の送出本文を実物確認した。実際に構築された本文は `{"content":"[INFRA] systemd unit failed\nhost: console-pi\nunit: host-health-inode.service\ntime: 2026-09-08T13:56:43Z\nresult: exit-code (exit status 1)\ndetails: journalctl -u host-health-inode.service -n 50 on that host"}` で、host/unit/time/result のみ。journal の抜粋・秘匿値・運用者個人情報は含まれない
- **Beszel**: `henrygd/beszel` のソース (`internal/alerts/alerts_status.go`, `alerts_systemd.go`) を確認したところ、本文は `Title`+`Message`+`Link` の 3 要素で構成される
  - Status: `Title: "Connection to <systemName> is <up/down> <emoji>"` (システム名は `beszel_systems` の宣言名、例 `k3s-agent-minipc`)
  - SystemdFailed: `Message: "<N> failed service(s) on <systemName>: <失敗ユニット名のリスト>"`。失敗した systemd ユニット名そのものが列挙される (journal 抜粋ではなくユニット名のみ、notify-failure.sh と同水準)
  - `Link`: `am.hub.MakeLink("system", systemID)` が生成する Beszel 自身の画面への URL。実機の `appURL` 設定を確認したところ `http://localhost:8090` (loopback) のままだった。**この Link は console-pi の外からは到達不能で、通知本体としては無害だが実質的に壊れたリンクになっている。** 修正は本タスクの範囲外のため対応していない (次タスクへの申し送り事項)
  - いずれも秘匿値・HTTP応答本文・運用者個人を識別する情報は含まれない。ソースコードと実際の `triggered`/`value` 遷移 (10.2/10.4 で実測) を突き合わせて確認した。**Discord 上での見た目のレンダリング (実物のスクリーンショット) までは確認していない**

### まとめ (タスク 4.9)

| 検証項目 | 結果 |
|---|---|
| 外形監視の意図的停止からの到達 (10.1) | ○ |
| host_health と Beszel 双方の閾値検査からの到達 (10.2) | ○ (Beszel は 10.0 の是正後に到達を確認) |
| 受け (Beszel hub) 停止 → 外形監視からの到達 (10.3) | ○ |
| agent 停止 → 受けからの到達不能通知、および監視対象の分担 (10.4) | ○ (二重通知なしを実機で確認) |
| 誤った宛先での不達と成功の区別 (10.5) | ○ |
| 本文の実物確認、秘匿値等の混入なし (10.6) | ○ (Gatus/notify-failure.sh は実際の送出バイト列を確認。Beszel はソース+実際の状態遷移から確認、Discord 上の見た目までは未確認) |

**次タスクへの申し送り**:
- Beszel の通知リンク (`appURL`) が `http://localhost:8090` のまま。実用的なリンクにする (Caddy 経由の `beszel` エンドポイント URL にする、または `appURL` を設定しない/リンクを使わない) かどうかの判断が必要
- `vps` に事前から存在する failed unit 4 件 (`fwupd-refresh.service`, `fwupd.service`, `host-health-fail2ban.service`, `prometheus-node-exporter.service`) を今回の検証中に発見した。うち `host-health-fail2ban.service` は 11 章で是正済み。残り3件は今回のタスク 4.9 の範囲外のため放置した。`console-pi` にも `var-swap.swap` の failed unit が既存 (DietPi 既定の swap ファイルが sparse で `swapon` に失敗、実害なし)、これも未対応

## 11. `host-health-fail2ban.service` の恒常的な誤検知の修正 (2026-09-08 実施)

`fail2ban-client status` の出力は `Jail list:` や `Banned IP list:` の直後がコロン+**TAB** (`:\t`) であり、コロン+スペース (`: `) ではない。`ansible/roles/host_health/templates/host-health-fail2ban.sh.j2` の `awk -F': '` はこの区切りに一致せず、jail 一覧の抽出が常に空文字列になり、実際の jail 状態に関わらず「fail2ban has no active jails」で恒常的に失敗していた (タスク 4.7 で導入して以降、常時 failed)。

`systemd-run --uid=0` で実際の systemd 実行環境を再現して再現を確認し (`fail2ban-client status` 単体は成功するが、スクリプト全体は失敗する)、`cat -A` で出力のバイト列 (`Jail list:^Isshd`) を確認して原因を特定した。

`awk -F': '` を `awk -F'\t'` に変更 (jail 一覧・banned IP list の両方の抽出箇所)。`vps` へ適用し、手動でユニットを起動して `Result=success` / `ExecMainStatus=0` を確認、続けて2回目の適用で `changed=0` (冪等性) を確認した。

## 12. 既存の収集・可視化機構 (Prometheus/Grafana) の存廃判断 (タスク 4.10、2026-09-08 判断)

要件 3.8 / 3.9 への対応。設計時点で既に確定していた内容 (design.md 「旧環境から引き継ぐもの」節、および Prometheus/beszel_hub の Implementation Notes) を、タスクの完了記録として確定する。

**決定**: `akishima` 上の Prometheus と Grafana はいずれも廃止する。中央の時系列データベースと可視化基盤は新しい足では持たない。

**理由**: 資源監視の目的は「壊れたことに気づくこと」であり、可視化に資源を割く価値がないと運用者が既に判断済み (requirements.md)。メモリ 1GB の機体に載る構成を優先し、外形の死活 (Gatus) / 資源と記憶装置の監視 (Beszel) / 既製の機構が備えない検査 (`host_health`) の 3 層で代替する。

**収集対象ごとの対応づけ** (Prometheus が収集していた 5 件 + 収集対象外だったもの):

| 旧収集対象 | 代替する機構 |
|---|---|
| `akishima` 自身 | 代替なし。`akishima` 自体が撤去対象 (`admin-plane-cutover` が扱う) |
| OPNsense | Gatus (外形の死活、4.4 で実装済み) |
| VPS | Beszel agent (資源)、`host_health` (fail2ban、4.7 で実装済み) |
| hp-z440 | Beszel agent (資源)、`host_health` (ZFS scrub、4.7 で実装済み) |
| n100 | Beszel agent (資源、4.7 で実装済み) |
| (収集対象外) k3s 各ノード・NAS・PBS | Beszel agent (資源、4.2/4.7 で新規に対象化)、`host_health` (全ホスト共通の6件、4.7 で実装済み) |

Grafana による可視化は再現しない。外形の状態一覧は Gatus の内蔵ダッシュボードが、各ホストの資源の状態は Beszel hub の画面が代替する。閲覧のための保持は Beszel の既定の間引きに限られ (4.8 で実測)、中央の時系列データベースは持たない。

**実際の停止は本 spec の範囲外**: `akishima` は本 spec の全期間を通じて稼働したままとする (実行前の禁止事項、要件 4.1 / 4.2)。実際の停止と、停止に先立つ「収集していた対象ごとの通知の要否の判断」(要件 3.9) は、後続の spec `admin-plane-cutover` が担う。
