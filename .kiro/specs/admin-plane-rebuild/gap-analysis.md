# Gap Analysis: admin-plane-rebuild

> **スコープの変更 (2026-09-05)**: 本文書は要件 8 件を前提に書かれている。その後 spec は Console セグメントの足の構築に絞り込まれ、旧要件 2 (認証の独立) / 5 (管理用 PC の転用) / 6 (ネットワーク分離の回復) は後続の `admin-plane-cutover` へ移った。残る要件は番号を詰め直しており、**本文書の要件番号は現行の `requirements.md` と対応しない** (旧 1→1、旧 3→2、旧 4→3、旧 7→4、旧 8→5)。差分の分析そのものは有効である。

要件 (縮小前の 8 要件 / 55 受入基準) と既存実装の差分を、両リポジトリの読み取りと 2026-09-04 に取得済みの実機観測に基づいて整理する。
設計判断は行わない。選択肢と、設計フェーズへ持ち越す調査項目までを示す。

## 1. 現状の把握

### 1.1 管理面に関わる資産

| 資産 | 位置 | 担うもの |
| --- | --- | --- |
| Cloudflare Access (IdP / policy / application) | `terraform/cloudflare_zero_trust.tf:90-167` | `console.fickledev.com` の認証。IdP は Kanidm 単独 |
| `guacamole` トンネル | `terraform/cloudflare_zero_trust.tf:71-78` | Console への唯一の外部到達経路。`config_src = "cloudflare"` |
| DNS の宣言的列挙 | `terraform/cloudflare_dns.tf:20-40` (`vps_hosts`) / `:68-82` (`tunnel_cnames`) | ホスト名を locals マップで列挙するパターン |
| トンネル ingress の列挙 | `terraform/cloudflare_zero_trust.tf:16-67` | `kubernetes` トンネルの経路定義。URL 単位の公開の既存形 |
| Kanidm の宣言 | `terraform-kanidm/identities.tf` / `oauth2_clients.tf` / `mail.tf` | グループ・OAuth2 クライアント・アカウントポリシー |
| `vps_proxy` role | `ansible/roles/vps_proxy/` | nginx / HAProxy / iptables 許可集合 / certbot / tailscaled。プロキシと境界制御の唯一の前例 |
| `systemd_failure_notify` role | `ansible/roles/systemd_failure_notify/` | `OnFailure=notify-failure@%n.service` を宣言したユニットの失敗を webhook へ送る |
| node_exporter の待受拘束 | `ansible/roles/vps_proxy/defaults/main.yml:157-160` | VPS のみ。導入自体は宣言外 (apt の未管理パッケージ) |
| ドリフト検査 | `scripts/check_host_address_drift.py` ほか 2 本 | 宣言間の整合性の検査 |
| インベントリ | `ansible/inventory/inventory.yml:2-33` | `target_hosts` 9 台。全て DMZ (`192.168.1.0/24`) か tailnet |
| k3s ノードの定義 | `terraform/locals.tf:6-63` + `inventory.yml:57-66` + `group_vars/all/main.yml:18-21` | ノードの正が 3 箇所に分散している |
| 手作業の記録の前例 | `.kiro/specs/mail-platform/manual-operations.md` | コード管理外の操作を spec 配下に残す形式 |

Console セグメント (`192.168.10.0/24`) を宣言する資産は 1 件も存在しない。`akishima` という文字列は
本リポジトリ全体で `requirements.md` にしか現れない。CIDR・ゲートウェイ・VLAN ID・ホストのいずれも
宣言されていない。

### 1.2 実機で確認した状態

2026-09-04 に tailnet 経由 (`100.96.0.101`) で取得した観測。読み取りのみ。

**ホスト**

- `akishima`、Console VLAN の `192.168.10.2/24` に足が 1 本のみ。CPU は i5-3470、メモリ 8GB、HDD 465.8GB で使用 62G。
- tailnet の node key の expiry は 180 日 (2027-03-02)。tailnet 内で OPNSense / VPS / k3s は expiry 無効化済みで、**このホストのみ期限を持つ**。
- `sudo` が NOPASSWD を持たない。Ansible の管理対象にする際の最大の障害。
- `ansible` core 2.20.5 が apt で導入済みだが実行の形跡は無い。

**稼働している構成要素**

- **Prometheus** は systemd 直接稼働。公式 tarball の手展開、rc 版 3.6.0-rc.0、`User=root`。scrape 対象は 5 件ですべて `up` — 自身 / OPNSense (`192.168.10.1:9100`) / VPS / hp-z440 / n100。**k3s 3 ノード・NAS・PBS は収集対象外。**保持 15 日 (既定値)、データは CWD 解決で `/data` に 141M。
- **alerting は完全に不在。**Alertmanager のプロセスも、コメントアウトされた設定もそのままで、rule は 0 件。
- **Grafana** 12.1.1 が稼働。`grafana.ini` と `grafana.db` は権限で読めず、**UI 側に手動のアラート設定がある可能性は未確認**。
- **Guacamole** の接続定義は 3 件 — `Console` (rdp → 自身:3389)、`OPNsense` (ssh → `192.168.10.1:2222`)、`Akishima` (ssh → 自身:22)。
- **デスクトップ環境** (LXQt + Openbox + xrdp) は RDP 接続時にのみ起動するが、切断してもセッションが終了せず積み上がる。実測で 2 セッションが 1 日 8 時間生存し、PSS で 669MB を占有。RDP の利用は全期間で 40 回、月 1〜3 回程度。

**保護されていない状態**

- Guacamole は `0.0.0.0:8080` で待受けており、`terraform/cloudflare_zero_trust.tf` のコメント「binds to localhost」は**事実と異なる**。Prometheus (9090) と Grafana (3000) も全インタフェース bind かつ無認証。
- **cloudflared のトンネル token が `ExecStart=` に平文で埋め込まれており `ps aux` で全ユーザーから読める。**`~/.bash_history` にも同じ値が残る。

**このホストが持つ固有の能力**

- デスクトップの用途は 2 つ — Console セグメントの Web UI (OPNSense の管理画面) をブラウザで開くこと、および **AdGuard の管理**。**AdGuard の所在は未確認。**
- `README.md:158` に `HW_ADMIN_PC -- USB Console --- HW_ROUTER_OPNSENSE` が記されている。**OPNSense への out-of-band の物理経路を持つ。**
- Chrome が普段使いの Google アカウントでログインした状態にあり、私用データ (urls 18,079 件 / visits 57,367 件 / ブックマーク 76 件) を含む。

**到達性**

- 作業機 (`192.168.20.19`) から `192.168.1.2:8006` と `192.168.1.10:8006` がいずれも OPEN。**不備ではなく、承知のうえで分離していない。**作業機から Terraform で Proxmox API を叩く必要があるため。
- 作業機から Console セグメントへは一切到達できない (ping・443・80・22・2222・9100 すべて不達)。

### 1.3 規約と統合点

- **秘匿値**: 単一の正は Infisical。ロール本体は一般名の変数のみ参照し、`group_vars` / `host_vars` の右辺だけを `lookup('env', 'VAR_NAME')` に束縛する。`vault.yml.example` は登録すべき変数名の一覧であり、値の供給経路ではない。
- **ホストの追加**: `structure.md` は「Terraform 側 (`locals`) と Ansible 側 (`inventory.yml`) の両方を更新する」と定める。ベアメタルはこの前提の外にある (第 3 節)。
- **クラスタ管理手段の一本化**: `tech.md` の Cluster Management 節は、クラスタ全体を素通しにするブラウザ管理 UI を置かないと定める。本 spec のプロキシが公開する対象は OPNSense と AdGuard の管理画面であり、k3s の管理 UI ではないため、この規約の対象外と読める (推測)。設計で明示的に位置づけると誤読を防げる。
- **記憶装置の役割別の使い分け**: 索引・データベースは SSD、実体・バックアップは HDD。書き込み量の多い保存先を SSD に置かない。監視の機構が計測値を書き続ける場合の置き場所の判断に効く。microSD は書き込み主体の保存先に向かない。

## 2. 要件と資産の対応

各要件について、既存資産で満たせる部分と、そうでない部分を分ける。
gap は **Missing** (資産が無い) / **Unknown** (調査が要る) / **Constraint** (既存の構造による制約) で示す。

### 要件 1: Console セグメントへの到達

| AC | 既存資産 | gap |
| --- | --- | --- |
| 1.1 到達手段を持つ | `guacamole` トンネル (画面転送) | **Constraint** — 既存トンネルは `config_src = "cloudflare"` で ingress が Terraform 管理外。`:75-77` に破棄・置換の禁止が明記されている |
| 1.2 セグメント全体を広告しない | — | 運用者の方針として subnet router を採らないことが決定済み。既存の Tailscale 資産は `vps_proxy` role 内にのみ存在 |
| 1.3 公開対象を個別に指定 | `cloudflare_zero_trust.tf:16-67` の `config.ingress` 配列 | 既存パターンがそのまま使える。ただし **`config_src` の値と排他**であることに注意 (下記) |
| 1.4 対象を列挙し宣言として保持 | `cloudflare_dns.tf:20-40` / `:68-82` の locals マップ | 同上。ただし `vps_proxy` にあった「ホスト名 → upstream」の列挙変数は Workers 移設時に削除済みで、**現存しない** |
| 1.5 認証を要求する | `cloudflare_zero_trust.tf:90-167` (Access + Kanidm) | **Constraint** — この形をそのまま採ると要件 2 の循環が残る |
| 1.6 停止時に物理作業によらず復旧 | `vps_proxy/defaults/main.yml:60-64` にロールバック経路をコメントで宣言する作法 | **Missing** — Console 側に該当する第 2 経路が無い。tailnet SSH が候補だが、node key の expiry が 2027-03-02 (AC 7.7 と交差) |
| 1.7 inbound を列挙しそれ以外を開放しない | `vps_proxy` の `vps_proxy_filter_allow_tcp_ports` / 専用 chain 差し替え (`defaults/main.yml:41-58`) | 設計パターンとして再利用可能。ただし OPNSense 側の規則には適用手段が無い |

**HTTP プロキシの素材**: `vps_proxy` role は nginx の vhost 生成、iptables の許可集合、systemd unit 配置、tailscaled の配置と再起動後の復帰待ち (`handlers/main.yml:24-35`) を一通り備える。一方で TLS 終端 (ACME DNS-01)・HAProxy の SNI パススルー・fail2ban・MyDNS など Console 側に不要な責務を多く含み、変数接頭辞も単一ホスト前提。**転送先を列挙するデータ構造が現存しない**ため、その部分は新規設計になる。

### 要件 2: 管理経路の認証の独立

**循環の実体は `terraform/cloudflare_zero_trust.tf:90-167` である。**

`console.fickledev.com` → Cloudflare Access → `allowed_idps` は Kanidm のみ (`:156`、`auto_redirect_to_identity = true`) → Kanidm は k3s 上 → k3s を管理する経路が Guacamole。同ファイル `:80-89` のコメントはこの構成をセグメント分離を守るための選択として正当化しており、**循環そのものは記録されていない**。

| AC | 既存資産 | gap |
| --- | --- | --- |
| 2.1 認証が管理対象に依存しない | — | **Missing** — 現状は依存している |
| 2.2 依存関係を図または一覧で記録 | `README.md:100-160` のネットワーク図 | **Missing** — 経路は描くが認証の依存の向きは描かない |
| 2.3 認証基盤停止時も管理経路が成立 | — | **Missing** |
| 2.4 管理者資格情報の回復経路の記録 | `terraform-kanidm/README.md:36-39` が `kanidmd recover-account` に言及 | **Missing** — 手順としての記録が無い。どのコンテキストで実行し、そこへ到達する経路が何に依存するかが未記載。`docs/` は `mail-client-setup.md` 1 本のみ |
| 2.5 配置変更時の依存の向きと可用性低下の記録 | — | **Missing**。IdP を Console 側へ移す案は「ラズベリーパイが落ちると k3s 上の全サービスの認証が止まる」向きの反転を伴う |
| 2.6 本人の資格情報で端から端まで 1 回通す | — | 手順としての要求。設計で検証手順に落とす |

**手作業同期の箇所**: `cloudflare_zero_trust.tf:96-98` が明記する通り、`client_id = "guacamole"` は `terraform-kanidm/oauth2_clients.tf:138` の `name` と手作業で同期している (state が別で自動連携が無い)。AC 2.5 で配置を変える場合、ここが影響を受ける。

### 要件 3: Console 上の資産の宣言化

| AC | 既存資産 | gap |
| --- | --- | --- |
| 3.1 インベントリに存在する | `inventory.yml:2-33` | **Missing** — Console のホストは 0 台。ネットワーク境界を表すグループ概念自体が inventory に無い |
| 3.2 適用の前提 (権限昇格・資格情報・実行環境) | `host_vars/vps/main.yml:2` の `ansible_become_password` が唯一の前例 | **Constraint** — akishima は `sudo` が NOPASSWD を持たない。同型の become パスワード供給が要る |
| 3.3 既存の構成のうち再現を要するものを含む | — | 読み取りは 2026-09-04 に大半が済んでいる (第 1.2 節)。**Grafana の UI 側アラート設定と AdGuard の所在のみ未確認** |
| 3.4 再現しないと決めたものと理由を記録 | `.kiro/specs/mail-platform/manual-operations.md` の形式 | 記録先の前例あり |
| 3.5 宣言は秘匿値を含まない | Infisical の変数間接化層 | 既存パターンで満たせる |
| 3.6 保護されない秘匿値を改め交換を検討 | — | **cloudflared の token が `ExecStart=` に平文**。宣言化の際は `EnvironmentFile` (0600) にする。`~/.bash_history` にも残るため交換が要る |
| 3.7 2 回続けて適用して 2 回目で変更なし | ansible-lint / CI の既存ゲート | 検証手順の要求 |
| 3.8 旧環境の記憶装置を保持 | — | 手順としての要求 (旧 HDD の保管) |

**Raspberry Pi への既存 role の適用性** (arm64 / Debian 系):

- `ssh_authorized_keys` — アーキ・ディストロ非依存。そのまま適用可。
- `kanidm_unixd` — `tasks/main.yml:20` が `ansible_architecture == 'aarch64'` を arm64 に写す分岐を持つ。**arm64 対応済み。**PPA が対象 suite の arm64 を配布しているかは要確認 (推測)。
- `systemd_failure_notify` — shell + webhook のみでアーキ非依存。流用可。
- `storage_disk` — `tasks/provision.yml:47` が `/dev/disk/by-path` の `*-scsi-` パターンを検索し `:53` でちょうど 1 件を assert する。microSD / USB はこのパターンに一致しない。パーティション接尾辞の判定 (`:68`) は `mmcblk` を既に含む。
- `vault.yml.example` の不整合: `host_vars/vps/vault.yml.example:2-3` と `host_vars/gitea/vault.yml.example:2-3` のヘッダーが `ansible-vault encrypt` を指示したまま残っている。`group_vars/all/` は是正済み。新規ホストの雛形を作るときに旧記述を引き写さないよう注意が要る。

**Console の足の記憶装置構成 (2026-09-04 に決定)**

**microSD は起動区画だけに使い、`root=` は USB 接続のドライブへ向ける。**ドライブは手持ちの余剰から充てる。2.5 インチのものと USB 変換ケースが既にあるため、調達を要さず、akishima の転用の完了も待たない。

- ラズベリーパイ 3 のブートローダは microSD の FAT 区画から `bootcode.bin` / `start.elf` / カーネルを読む。**この構成なら USB からの起動を有効化する OTP の書き込みが要らない**ため、3B / 3B+ のどちらでも同じ手順で成立する。
- `cmdline.txt` の `root=` は `PARTUUID=` で指定する。USB の列挙順は保証されないため `/dev/sda2` の形を使わない。`rootwait` を残し、列挙の遅れを待たせる。
- **microSD への書き込みはカーネルとファームウェアの更新時のみ**になる。書き込み耐性の懸念が実質的に消え、Beszel の hub が持つ SQLite も自動的に HDD 側へ載る。`/boot/firmware` を恒久的に `ro` で固定すると `apt` の更新が失敗するため、更新時のみ `rw` に戻す形にする。
- **HDD の回転停止を無効にする。**ルートを載せる以上、APM / spindown が働くと復帰待ちでシステムが止まる。
- **物理的な前提**: 2.5 インチのドライブはバスパワーで足りる。3.5 インチのもの (akishima から外れる WD5000AAKX 等) を選ぶ場合のみ、12V を供給する外部電源付きのケースが要る。
- **帯域の制約**: ラズベリーパイ 3 の USB は 2.0 のみで、**有線 LAN も同じ USB ハブに相乗りする**。ディスク入出力とネットワークが帯域を食い合う。
- **`storage_disk` role の対象外**。ルートドライブは OS 導入時に用意するものであり、`by-path` の `*-scsi-*` に一致しない件 (前項) はここでは問題にならない。追加のデータ用ディスクを後から足す場合にのみ再燃する。
- **充てるドライブの SMART は実測済み。**FUJITSU MJA2500BH G2 (2.5 インチの回転 HDD、465.8G) で `SMART overall-health self-assessment test result: PASSED`。`Reallocated_Sector_Ct` (ID 5) / `Current_Pending_Sector` (197) / `Offline_Uncorrectable` (198) / `UDMA_CRC_Error_Count` (199) がいずれも 0、`Temperature_Celsius` 38 (Min/Max 7/51)、`Power_On_Hours` 16815、`Power_Cycle_Count` 4160。**USB 接続でも `smartctl 7.4` が `-d sat` の指定なしに自動検出でき、属性が読める。**

**監視の対象となる記憶装置の実測**

| ホスト | 記憶装置 | 記憶領域 |
| --- | --- | --- |
| `console-pi` | `sda` USB 接続 465.8G HDD、`mmcblk0` 28.9G microSD | — |
| `n100` | `sda` 476.9G SATA SSD 1 本 | ZFS プールを持たない |
| `hp-z440` | `sda` 931.5G SATA SSD、`sdb` 1.8T SATA HDD、`sdc` 3.6T SATA HDD | **`zfs-pool` (ONLINE)。単一 vdev の実体は `sdc` (ST4000VN006-3CW104)** |
| `pbs` | **`hp-z440` 上の LXC コンテナ** (`systemd-detect-virt` が `lxc` を返す)。`lsblk` が物理ディスクを列挙するのは LXC がホストのブロックデバイスを見せているためで、**コンテナ内から SMART は読めない** | **コンテナ内では `zpool list` が空。**プールの実体は `hp-z440` にある |
| `k3s-server` / `k3s-agent-minipc` / `k3s-agent-z440` / `nas` / `gitea` | KVM ゲストの仮想ディスク | — |
| `vps` | 仮想ディスク | — |

**この環境の記憶装置に NVMe は 1 本も無い。**接続方式は SATA / USB / MMC のみであり、NVMe 特有の検知の制限は現状では影響しない。**microSD は SMART を持たない**ため、`console-pi` の boot 区画の劣化は検知の対象外になり、読み取り専用の運用が検知ではなく予防としてこれに当たる。

### 要件 4: 監視と通知

**運用者の決定 (2026-09-04): 時系列の収集そのものを持たない。**Grafana に加えて **Prometheus も廃止する**。
ログを日常的に読む運用は行わないため、ログの蓄積機構も持たない。この決定により要件 4.4 と 4.7 が
構成の選択そのものによって満たされる。

**監視は 3 層に分かれる。**外形の死活と状態一覧の画面は **Gatus** (履歴を持たず `storage.type: memory`)、各ホストの
資源・記憶装置の状態・記憶領域の health・failed ユニット・到達不能は **Beszel** (hub を `console-pi`、agent を
対象ホストへ)、その双方が備えない検査だけを **`host_health`** が担う。**中央に時系列データベースを立てない。**
以下の表ではこの 3 者を名前で指す。

| AC | 既存資産 | gap |
| --- | --- | --- |
| 4.1 異常検知時に通知 | `systemd_failure_notify` role | **リポジトリ内で唯一の通知実装。**消費者は `mail_backup/templates/mail-backup-pull.service.j2:6` の 1 件のみ。Gatus は `alerting.custom`、Beszel は shoutrrr の `discord://` と、いずれも自身の送出機構を持つ。**3 者とも同じ Discord の宛先へ寄せ、経路を 1 本に保つ** (第 3.2 節の分担と交差) |
| 4.2 対話的な連絡手段への逐次送信を用いない | — | 既存の唯一の経路が Discord webhook (`PORTFOLIO_DISCORD_WEBHOOK_URL`)。**この AC が排除するのは正常時を含む逐次の送信であり、状態が遷移したときにのみ送る形はこれに当たらない。**3 者ともこの宛先へ寄せ、経路を 1 本に保つ |
| 4.3 意図的に事象を発生させて到達を確認 | — | **Missing** — `notify-failure@` について確認の記録が見当たらない |
| 4.4 計測値の蓄積を目的としない | — | **決定により満たされる。**Gatus は履歴を持たず、Beszel が持つのは自身の画面を描くための最長 30 日分 (1 システムあたり全チャートで約 400 レコード) に限られ、他の機構が問い合わせる汎用の時系列基盤ではない。**保持量は実測して記録する** |
| 4.5 監視対象事象を列挙 | — | **Missing** — 該当する文書が無い。`gatus_endpoints` / `beszel_systems` / `beszel_alerts` と自前の検査の表が実質の一覧になる。**いずれも宣言としてファイルに保持する** |
| 4.6 状態を一望できる画面 | ArgoCD Web UI (GitOps 同期状態のみ) | **Missing** — 該当する資産は両リポジトリに 0 件。**Gatus の内蔵ダッシュボードが外形の状態一覧を、Beszel の hub の画面が各ホストの資源の状態を担う。**別立てのダッシュボードは置かない |
| 4.7 画面の資源消費が規模に見合う | — | **決定により満たされる。**ラズベリーパイ 3 (1GB) が上限。**この機体で Beszel の hub を動かした報告が存在しない**ため、上限値は設計で固定せず、全ての常駐が揃った状態の実測値をもって判断する |
| 4.8 既存の収集機構の存廃を決定 | Prometheus (宣言外、akishima 上) | **決定は「廃止」。**残る作業は 4.9 の判断のみ。ただし **Grafana の UI 側アラートの有無が未確認**で、これを確認せずに落とすと既存の検知を気づかずに失う |
| 4.9 廃止する場合は収集対象の通知の要否を先に判断 | scrape 対象 5 件が判明済み (自身 / OPNSense / VPS / hp-z440 / n100) | **ディスク使用率と負荷を含む資源は Beszel の agent が代替する。**FreeBSD で agent の公式バイナリの対象外である OPNSense のみ Gatus の外形が担う。収集対象外だった k3s の各ノード・NAS・PBS も agent の対象に含まれ、廃止が検知の後退にならない。**VPS の node_exporter は収集側が消えるため待受を閉じる**対象になる (要件 6.1 / 6.5 と交差) |
| 4.10 秘匿値・個人識別情報を含まない | `systemd_failure_notify/templates/notify-failure.sh.j2` が journal 抜粋を載せない設計 | 既存実装がこの AC を満たす形で書かれている。Gatus は `[RESULT_ERRORS]` を使わないことで、Beszel は**本文の文面を差し替える手段が無いため、ログ抜粋を最大 1800 文字埋め込む `ContainerHealth` のアラートを設定しないことと、システム名に個人を識別する語を含めないこと**で同じ制約を満たす |

**k3s 側に可観測性は無い。**`gitops-apps/apps/` の 18 ディレクトリに Prometheus / Grafana / Alertmanager / Loki の Application は 1 つも無く、`ServiceMonitor` / `PodMonitor` / `PrometheusRule` の実体も 0 件。VPS の node_exporter を収集していたのはクラスタ側ではなく宣言外の akishima である。

**CI は異常検知の経路になっていない。**`.github/workflows/ci.yml` は push / pull_request のみで cron を持たない。`check_edge_packet_filter_drift.py` と `check_stale_last_applied_secrets.py` は外部資格情報を要するため CI から呼ばれていない (推測)。定期実行されるのは `secret-scan.yml` の日次のみ。加えて **CI の失敗そのものが `systemd_failure_notify` の経路に乗っていない**。

### 要件 5: 管理用 PC の転用

| AC | 既存資産 | gap |
| --- | --- | --- |
| 5.1 役割の移設先が確定している | — | 移設対象は Guacamole / cloudflared / デスクトップ / **USB シリアルコンソール** の 4 つ。**Prometheus と Grafana は移設先を要さず廃止する** (要件 4.8 の決定) |
| 5.2 失われる能力の列挙と代替の記録 | — | **Missing** — `README.md:158` の USB シリアルコンソールがネットワーク図にしか記録が無い。OPNSense への out-of-band 経路であり、要件 1.6 の第 2 経路の候補でもある |
| 5.3 未確定の役割が残るなら転用しない | — | 手順としての要求 |
| 5.4 個人データの扱いを転用前に決定 | — | Chrome の私用データ (urls 18,079 件ほか) |
| 5.5 保全する場合はインフラの構成と別手段で | — | **Missing** |
| 5.6 転用後のホストが構成管理の対象 | `inventory.yml:61` の `k3s_agent` グループ | 第 3 節のベアメタルの非対称が該当 |

### 要件 6: ネットワーク分離の回復

| AC | 既存資産 | gap |
| --- | --- | --- |
| 6.1 分離に反して開けている経路の列挙と理由 | — | 既知の 1 件: 作業機から Proxmox の 8006 が OPEN。理由は「作業機から Terraform で Proxmox API を叩く必要があり、当時は管理用 PC からの適用を実装できていなかった」 |
| 6.2 仮想化基盤の管理画面は管理面からのみ | — | **Missing** — `8006` の宣言は `proxmox_backup` role の API 呼び出し URL (利用側) のみ。到達制御の宣言は皆無。制御点は OPNSense にあるが**コード管理外** |
| 6.3 閉じる前に代替経路の成立を確認 | — | AC 6.2 の前提条件が「作業機以外からの Terraform 適用」。本 spec は「編集は作業機で行う」方針を採るため、**適用の実行主体をどこに置くかが AC 6.2 の可否を決める** |
| 6.4 閉じた後に到達性を実測で確認 | `scripts/check_*_drift.py` の作法 | 実測の手段は新規。既存チェッカーは宣言間の整合のみを見る |
| 6.5 意図的な開放は理由を記録 | `vps_proxy/defaults/main.yml:41-64` のコメントによる宣言 | 既存の作法を踏襲できる |

**OPNSense は IaC 化の手段を持たない。**規則の宣言は本リポジトリに 1 件も無く、`opnsense` の出現は全て「host override はコード管理外」と述べるコメント。既知の依存として `ldaps.kanidm.fickledev.com` の解決が OPNSense の host override だけに依存しており、壊れたときの検知経路が無い (`check_host_address_drift.py` は repo 内の定義しか見ないため対象外)。**Console セグメントが到達可能になった以上、この検知の実装先は本 spec が筋。**

### 要件 7: 実施における制約

| AC | 既存資産 | gap |
| --- | --- | --- |
| 7.1 / 7.2 到達手段を失わない | `vps_proxy/handlers/main.yml:24-35` (管理経路を切る操作の直後に復帰を待つ)、`templates/vps-proxy-iptables-apply.j2:14` (`This host has no reachable console` を前提にした安全弁) | 既存の作法がある |
| 7.3 所属変更を並行実行しない | — | 並列エージェントが同時に Kanidm のグループを触るとメンバーが消える既知の失敗様式に対応する制約 |
| 7.4 VM 105 に読み取りを含め触れない | — | **Missing** — コード上の機械的なガードは無い。`terraform/locals.tf` に定義が無いこと (Terraform 管理外) が唯一の間接的な保護 |
| 7.5 永続データを失う操作の前に承認 | — | 手順としての要求 |
| 7.6 物理作業は運用者が実施 | `.kiro/specs/mail-platform/manual-operations.md` | 記録先の前例あり。SSD 交換・OS 導入・Tailscale 導入・旧 HDD の読み取り専用マウントが該当 |
| 7.7 到達手段の期限による失効の把握 | — | **akishima の tailnet node key の expiry が 2027-03-02。**tailnet 内で他のノードは expiry 無効化済みで、このホストのみ期限を持つ。新しい Console の足でも同じ判断が要る |

### 要件 8: 停止している機器の遠隔起動

**宣言はゼロ。**`wake on lan` / `wol` / `etherwake` / `magic packet` のいずれも、リポジトリ全体で 1 件も一致しない。

| AC | 既存資産 | gap |
| --- | --- | --- |
| 8.1 遠隔から起動する手段 | — | **Missing** |
| 8.2 対象の列挙を宣言として保持 | `cloudflare_dns.tf` の locals マップ、`pbs_backup_targets` の列挙 | 列挙を宣言に持つ作法は既存にある。対象ごとに MAC アドレスを持つ必要がある点が新しい |
| 8.3 別セグメントの対象にも到達 | — | **Constraint** — **これが実現可否を決める。**magic packet はブロードキャストであり、送出元が対象と同じブロードキャストドメインに居るか、経路上の機器が代理で送出する必要がある。Console の足 (`192.168.10.0/24`) から DMZ (`192.168.1.0/24`) の機器へは、そのままでは届かない |
| 8.4 認証を経ずに送出できない | 要件 1.5 の到達手段の認証 | 送出の口を管理面のプロキシの背後に置けば、要件 1 の認証をそのまま流用できる |
| 8.5 対応の可否を確認し記録 | — | **Missing** — 対象の NIC と BIOS / UEFI が対応しているかは**物理的な確認を要する** (要件 7.6)。省電力状態からの起動可否は機体ごとに異なる |
| 8.6 起動が成立しなかったことを判別 | 要件 4 の Gatus | 起動要求の後に対象の死活を確認すれば足りる。**外形の死活監視を持つことがそのまま 8.6 の手段になる** |

**8.3 の解き方の候補** (設計で決める):

- **OPNSense に送出させる (確認済み)。**`os-wol` プラグインが存在し、指定したインタフェースのサブネットブロードキャスト宛に magic packet を送出する。REST API から未登録の MAC を即時送出できるため、**対象の列挙 (8.2) は OPNSense 側ではなく本リポジトリに置ける**
- **Proxmox のノードから送出させる。**DMZ に足を持ち、Ansible の管理対象でもある。対象が DMZ の機器に限られるなら成立する。ただし**起こしたい対象が Proxmox のノード自身である場合には使えない**
- **経路上でブロードキャストを転送させる。**OPNSense に directed broadcast の転送を設定する。分離の設計 (要件 6) と逆行するため、採るなら理由の記録 (6.5) が要る

**起こしたい対象が何かで解が変わる。**Proxmox のノード (n100 / hp-z440) を落として必要なときだけ起こすのか、転用後の k3s ノードなのかが未確定 (Research Needed)。

## 3. 要件をまたぐ構造的な論点

### 3.1 ベアメタルの k3s ノードは既存の宣言の形に乗らない

既存の k3s ノードは 3 台とも Proxmox VM で、転用する管理用 PC はベアメタルである。この差は 4 箇所に現れる。

- **ノードの正が分裂する。**`terraform/locals.tf:6-63` の `vms` map が現在のノードの正だが、ベアメタルはそこに載らない。`tech.md` の「Proxmox Guests」節が示す VM 105 / 108 / 110 と同じ「実機にあるが Terraform 管理外」の構造が、今度は k3s ノード側に新設される。
- **`k3s_internal_ips` が静的 map で、未追記でも失敗しない。**`group_vars/all/main.yml:18-21` の 3 エントリを `group_vars/k3s/main.yml:23` が `| default('')` で引き、`rlex.k3s/templates/k3s-config.yaml.j2:30-31` が `node-ip` に渡す。**追記を忘れると空文字にフォールバックし、node-ip 無指定で静かに起動する。**
- **`172.16.0.0/16` のクラスタ内部 NIC は Terraform が VM に付けている** (`locals.tf` 各 VM の `ip1`)。ベアメタルにこの経路を作る宣言は存在しない。DMZ 側で通すか物理 NIC / VLAN を別途構成するかが未決 (Research Needed)。
- **ディスク供給も同じ非対称。**`storage_disk` の `scsi_address` は Proxmox の virtio-scsi 前提で、`locals.tf` の `scsi` 番号と対応している。物理ディスクは `by-path` の形が異なる。

一方、**agent の追加手順そのものは Terraform を介さない**。`playbooks/k3s.yml:6` は `hosts: k3s` の総なめで、inventory の `k3s_agent` に 1 行と `host_vars/<name>/main.yml` の `k3s_agent: true` だけで足りる (`host_vars/k3s-agent-minipc/main.yml:4` がその最小形)。`rlex.k3s` は arm64 のバイナリ URL を解決できる (`vars/main.yml:3-9`)。

### 3.2 `backup-durability-and-alerting` と受入基準が重複する

同 spec は `requirements-generated` / 未承認。通知に関する受入基準が**逐語で一致する対**が 4 組ある。

| 本 spec | backup spec | 内容 |
| --- | --- | --- |
| 4.3 | Req4 AC9 | 意図的に事象を発生させた到達確認 |
| 4.10 | Req4 AC10 | 秘匿値・個人識別情報の排除 |
| 4.5 | Req4 AC12 | 通知対象事象の一覧 |
| 4.2 | Req4 AC4 | 対話的な連絡手段への逐次送信の排除 |

**同一の成果物を二重に作らないための分担の明示が要る。**加えて次の 3 点が交差する。

- backup Req4 AC1 が「単一の経路」を定める。本 spec の監視機構はその経路に**乗る側**であり、独自の経路を立てない。
- backup Req4 AC14 が「定めた経路に合致しない既存実装の置換」を求める。`systemd_failure_notify` がその対象なのか、むしろ「定めた経路」の本体候補なのかの判断が要る。
- backup Req4 AC13 が「宣言外ホストに依存する場合の明示」を求めるが、本 spec の要件 5 で依存そのものが消える方向。**本 spec を先行させると AC13 が空になる。**同様に backup Req4 AC3 (既に稼働している収集機構の確認) は、本 spec の 4.8 が廃止を決めると対象が消える。

### 3.3 「蓄積しない」と「容量の推移を見る」の緊張は解消する

本 spec の 4.4 は「計測値の蓄積を目的としない。蓄積のための資源を割かない」と定める。一方 backup spec の Req2 AC4 は「複製先の使用量を把握できる状態にし、上限に近づいたことを検知できるようにする」を求める。

**Prometheus を廃止する決定により、この緊張は「中央に時系列データベースを立てず、閲覧のための保持は機体の資源を圧迫しない量に留める」形に確定する。**複製先の使用量は Beszel の hub の画面で読め、上限への接近は agent の計測に対する `Disk` の閾値のアラートが捕捉する。既製の機構が備えない検査だけを各ホスト上の systemd timer が担い、超過時にユニットを failed にして既存の `systemd_failure_notify` の経路へ乗せる。**気づくことが目的であって傾向の分析は目的でない**という要件 4 の前提と整合する。

### 3.4 適用の実行主体が要件 6.2 の可否を決める

要件 6.2 (仮想化基盤の管理画面は管理面からのみ) を満たすには、作業機から Proxmox の 8006 を閉じる必要がある。その前提条件は「作業機以外からの Terraform 適用」であり、これが 2026-09-04 時点で「管理用 PC を実行主体にする」構想が立てられた理由だった。**本 spec は「編集は作業機で行う」方針を採るため、適用の実行主体を別途決める必要がある。**候補は (a) ラズベリーパイ上で適用する、(b) k3s 上のジョブとして適用する、(c) 6.2 を「代替経路が成立していない」として据え置く (AC 6.3 が許す形)。

## 4. 実装の方針の選択肢

### Option A: 既存の role と Terraform 資産を拡張する

`vps_proxy` role を多ホスト対応に一般化し、Cloudflare の既存トンネルに ingress を足す。

- **触る対象**: `ansible/roles/vps_proxy/` の変数接頭辞と責務の切り分け、`terraform/cloudflare_zero_trust.tf` の `config.ingress`、`cloudflare_dns.tf` の `tunnel_cnames`。
- **トレードオフ**:
  - 新規ファイルが最小で、DNS / ingress の列挙は既存パターンをそのまま使える
  - `vps_proxy` は TLS 終端・HAProxy・fail2ban・MyDNS を含み、Console 側に不要な責務が大半を占める。一般化すると VPS 側の挙動に影響が及ぶ
  - **既存の `guacamole` トンネルは `config_src = "cloudflare"` で ingress が Terraform 管理外**。`:75-77` が破棄・置換を明示的に禁じているため、このトンネルに ingress を宣言的に足すことはできない

### Option B: Console 専用の資産を新規に作る

Console の足 (ラズベリーパイ) 用の role 群と、`config_src = "local"` の新規トンネルを作る。

- **新規に作るもの**: 到達手段の宣言 (プロキシを別途置くか、`tailscale serve` と `cloudflared` の ingress で賄うかは設計で決める)、Tailscale の配置 role、監視の 3 層それぞれの配置 role、Console 用の inventory グループ、新規トンネルとその ingress 宣言。
- **トレードオフ**:
  - 責務が明確で、`vps_proxy` に手を入れずに済む
  - ingress の宣言先を選べる。**`config_src = "cloudflare"` なら Terraform の `cloudflare_zero_trust_tunnel_cloudflared_config` に置き、`config_src = "local"` なら実機上の `config.yml` に置く。両者は排他で、併用できない。**どちらでも要件 1.3 / 1.4 は満たせるが、宣言の置き場所が Terraform 側か Ansible 側かで変わる
  - 新規トンネルを立てて旧トンネルを残すため、移行期間中は 2 本が並走する (要件 7.1 / 7.2 の観点ではむしろ有利)
  - ファイル数が増える。Tailscale の配置ロジックが `vps_proxy` と新 role に重複する

### Option C: 折衷 — 到達手段は新規、通知は既存を拡張、Tailscale は抽出して共有

- 到達手段 (プロキシ・新規トンネル・Console の inventory グループ) は Option B の通り新規に作る。
- **監視は 3 層に分ける。**外形の死活は Gatus、各ホストの資源・記憶装置・記憶領域と到達不能は Beszel、その双方が備えない検査だけを各ホスト上の systemd timer が担う。最後の層は超過時にユニットを failed にするだけで、通知は既存の `systemd_failure_notify` に任せる。**中央に時系列データベースを立てない。同じ事象を 2 つの層で見ない。**
- 通知は `systemd_failure_notify` を土台にする。**対象ユニット側に `OnFailure=notify-failure@%n.service` を 1 行足すだけで対象を増やせる設計**であり、要件 4.10 (秘匿値・個人識別情報を含まない) を満たす形で既に書かれている。Gatus と Beszel の通知も同じ宛先へ寄せると経路が 1 本になる。
- Tailscale の配置ロジック (`vps_proxy/tasks/main.yml:315-320` + `handlers/main.yml:24-35`) を独立 role へ抽出し、VPS と Console の足で共有する。
- **段階の分け方**: (1) ラズベリーパイを inventory に載せ tailnet で到達可能にする → (2) プロキシと新規トンネルで到達手段を二重化する → (3) 認証の依存を切る → (4) 監視と通知を移す → (5) 旧到達手段を停止する → (6) akishima を k3s へ転用する → (7) 分離を戻す。
- **トレードオフ**:
  - 要件 7.1 / 7.2 (到達手段を失わない) が段階の順序に自然に対応する
  - 抽出のリファクタリングが VPS 側の回帰リスクを持つ。`vps_proxy` の Tailscale 部分は「再起動後に tailnet SSH の復帰を待つ」ハンドラを含み、切り出しの際にこの挙動を落とすと VPS への到達を失いうる
  - 計画が最も複雑

## 5. 規模と危険度

| 要件 | 規模 | 危険度 | 根拠 |
| --- | --- | --- | --- |
| 1 到達 | M | Medium | ingress / DNS の列挙は既存パターン。新規トンネルの追加と旧トンネルの並走が要る |
| 2 認証の独立 | M | **High** | 切り替えを誤ると管理経路を失う。回復経路が未記録のまま着手すると戻せない |
| 3 宣言化 | L | Medium | ゼロからの宣言。読み取りは概ね済んでいるが、become パスワード・秘匿値の交換・冪等性の確認が積み上がる |
| 4 監視と通知 | M | Low | 中央の収集基盤は立てないが、3 層それぞれの配置と、agent および検査の 10 ホストへの展開が積み上がる。残る未確認事項は Grafana の UI アラートのみ |
| 5 転用 | L | **High** | 個人データと USB シリアルコンソールの扱いが未決。物理作業を伴い、着手すると戻せない |
| 6 分離の回復 | M | **High** | OPNSense に IaC の手段が無く、規則の変更が手作業。誤ると到達手段を失う。実行主体の決定に依存する |
| 7 制約 | S | Low | 手順としての要求が中心。tailnet の expiry の把握だけが実装を伴う |
| 8 遠隔起動 | S | Low | 送出元をどこに置くかが決まれば小さい。既存の機構で賄えなければ見送る要件 |

全体では **L (1〜2 週間)** / 危険度 **High**。物理作業を含み、失敗すると管理経路を失う経路が複数ある。

## 6. 設計フェーズで調査を要する項目 (Research Needed)

**到達手段**

- 新規トンネル (`config_src = "local"`) の cloudflared をラズベリーパイ上で宣言的に配置する手段。本リポジトリに cloudflared を配置する Ansible role は存在しない。
- プロキシの認証方式。Kanidm の forward auth を使うと循環が残る。tailnet のノード認証で足りるのか、基本認証を置くのか、Cloudflare Access を Kanidm 以外の IdP で構成できるのか。
- 要件 1.6 の第 2 経路。USB シリアルコンソールを移設するのか、tailnet SSH を第 2 経路とみなすのか。後者なら node key の expiry の扱いが要件 7.7 と直結する。

**Console の足の構成**

記憶装置の構成と、充てるドライブの SMART は確認済み (要件 3 の節を参照)。残る調査は次の 2 点。

- `kanidm_unixd` の PPA が対象 suite の arm64 を配布しているか。**Console の足に UNIX 統合が要るかどうか自体が未決**で、要らなければこの調査ごと消える。
- USB 2.0 と有線 LAN の帯域競合が Gatus の監視間隔と Beszel の hub の応答に影響するか。外形の監視は小さい HTTP 要求が主のため問題にならない見込み (推測)。

**k3s ノードの転用**

- ベアメタルノードの `172.16.0.0/16` 相当のクラスタ内部経路。DMZ 側で通すか、物理 NIC / VLAN を構成するか。
- Terraform 管理外のノードを「ノードの一覧」としてどこに宣言するか。`k3s_internal_ips` の静的 map が未追記でも静かに通る点への対処。

**監視と通知**

- Grafana の UI 側に手動のアラート設定があるか (`grafana.db` は権限で読めていない)。廃止の前に確認しないと既存の検知を気づかずに失う。
- AdGuard の所在。デスクトップの固有用途の 1 つであり、プロキシの公開対象になるかがここで決まる。
- **`pbs` の agent が報告する資源の値がコンテナのものかホストのものか。**Proxmox は lxcfs を用いるためコンテナの値になる見込みだが未確認で、ホストの値を報告する場合は `hp-z440` の agent と重複する。
- **1GB の機体で Beszel の hub を動かした報告が存在しない。**全ての常駐が揃った状態での実測が要件 4.7 の唯一の判断材料になる。
- **Beszel の hub が保持する計測値の実際の量。**要件 4.4 は保持量を実測して記録することを求める。

**遠隔起動**

- **OPNsense に Wake on LAN の機能が組み込まれているか。**あれば送出元の問題が追加の部品ゼロで解ける。API から叩けるかどうかが、管理面の画面に載せられるかを決める。
- **VLAN をまたぐ magic packet の解法。**directed broadcast の転送を許すか、静的 ARP を置いた unicast で送るか。前者は分離の設計と逆行する。
- **対象の機器が Wake-on-LAN に対応しているか。**NIC と BIOS / UEFI の両方が要る。物理的な確認になる。Debian 側の `ethtool` の設定が再起動をまたいで保持されるかも確認が要る。
- **起こしたい対象の確定。**Proxmox のノードなのか、転用後の k3s ノードなのか。対象が Proxmox のノード自身なら、Proxmox から送出する案が使えない。

**認証**

- `kanidmd recover-account` の実行コンテキストと、そこへ到達する経路の依存 (要件 2.4)。
- IdP を Console 側へ移す場合の可用性の低下の見積もり (要件 2.5)。

## 7. 既存の構造との衝突

- **`guacamole` トンネルは破棄できない。**`terraform/cloudflare_zero_trust.tf:75-77` が明示的に禁じており、ingress も Cloudflare 側が保持する。**新しい到達手段は既存トンネルの置き換えではなく、新規トンネルの追加になる。**
- **`vps_proxy` から転送先の列挙が失われている。**`vps_proxy_upstream_main` / `_blog` は Workers 移設時に削除済みで、現行の `fickledev.com.conf.j2` は全 19 行、vhost は 2 つとも `return 403`。要件 1.3 / 1.4 を満たすデータ構造は新規に設計する。
- **OPNSense と Proxmox の 8006 の到達制御に足場が無い。**要件 6.2 / 6.4 は本リポジトリ内で完結しない。`manual-operations.md` 方式で手作業として記録するか、OPNSense を inventory に載せる新たな適用手段を導入するかの判断が要る。
- **`PORTFOLIO_DISCORD_WEBHOOK_URL` がどの `vault.yml.example` にも記載されていない。**`group_vars/all` / `host_vars/gitea` / `host_vars/vps` の 3 ファイルに 0 件。名前一覧の網羅性が既に破れており、通知経路を拡張する際に是正の対象になる。
- **Cluster Management の一本化の規約との関係。**`tech.md` は「クラスタ全体を素通しにするブラウザ管理 UI を置かない」と定める。本 spec のプロキシは OPNSense と AdGuard の Web UI を公開するもので k3s の管理 UI ではないが、設計でその区別を明示しないと規約違反として誤読されうる。

## 8. 設計フェーズへの引き継ぎ

- **推す方針は Option C (折衷)。**到達手段は新規に作らざるを得ず (既存トンネルが破棄禁止、転送先の列挙が現存しない)、一方で通知は `systemd_failure_notify` が要件 4.10 を満たす形で既に存在する。段階の順序が要件 7.1 / 7.2 に自然に対応する点も効く。
- **着手の順序で先に決めるべきは 2 点。**(a) 適用の実行主体 — 要件 6.2 の可否を決める。(b) プロキシの認証方式 — 要件 2 の循環を切る手段そのもの。
- **`backup-durability-and-alerting` との分担を先に確定する。**通知に関する 4 組の重複する受入基準について、どちらの spec が成果物を持つかを決める。本 spec を先行させると backup 側の 2 つの AC (宣言外ホストへの依存の明示、稼働中の収集機構の確認) の対象が消える。
- **中央の収集基盤は持たない。**Grafana も Prometheus も廃止する。監視は Gatus の外形、Beszel の資源と記憶装置、`host_health` の 3 層で置き換え、**同じ事象を 2 つの層で見ない。**とりわけホストの到達不能の担い手は agent の有無で一意に決まり、agent を置くホストを Gatus の死活の対象に入れない。3 者はいずれも「定義をファイルで宣言的に保持できる」「保持する計測値が機体の資源を圧迫しない」「1GB の機体に載る」「宛先を 1 つに集約できる」を満たす。
- **廃止の判断の前に確認する未確認事項が 2 つ。**Grafana の UI 側アラート設定と AdGuard の所在。どちらも「廃止してから気づく」と戻せない。
- **物理作業として切り出すもの**: ラズベリーパイの用意、microSD を起動区画・USB ドライブをルートとする OS 導入と `cmdline.txt` の `root=PARTUUID=` 指定、Tailscale の導入 (ここが通れば以降は自動化できる)、旧 HDD の読み取り専用マウント、USB シリアルコンソールの移設。いずれも `manual-operations.md` 形式で記録する。
