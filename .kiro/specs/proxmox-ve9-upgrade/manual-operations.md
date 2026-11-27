# 手動操作の記録

ホスト上の操作の記録。形式は「日時・対象・コマンド・結果」。時刻は JST。

## n100 (192.168.1.10、root)

### タスク 2.1: 作業の開始、8.4 の最新、ブート構成の修正

#### 作業前の状態 (2026-11-22 18:35)

| 項目 | 値 |
|---|---|
| `pveversion` | pve-manager/8.4.21、稼働中のカーネル 6.8.12-19-pve |
| ルートの空き | `df -h /`: 94G 中 30G 使用、空き 61G (10 GB 以上を満たす) |
| `apt-daily-upgrade.timer` | active (作業前) |
| クォーラム | `pvecm status`: Nodes 2、Quorate Yes (two_node)。HA のリソースは無い |
| 導入済みの 6.8 系カーネル | 6.8.12-43 (未起動)、6.8.12-19 (稼働中)、ほか 6.8.12-13、6.8.12-5、6.8.4-3 |
| `grub2/force_efi_extra_removable` | false。`EFI/BOOT/BOOTx64.efi` は 2024-06-15 のまま、`EFI/proxmox/` は 2026-09-04 |
| BootOrder | 0001 (proxmox) , 0002-0005 (PXE), 0007 (UEFI OS)。`proxmox-boot-tool` の管理下に無い |
| `apt list --upgradable` | 44 パッケージ (corosync、qemu-server、systemd、openssh、libc 等) |
| パススルー | 無し (`qm config` に usb / hostpci の定義なし。ディスクは local-lvm のみ) |

作業前のゲストの一覧 (`qm list` / `pct list`):

| 種別 | ID | 名前 | 作業前の状態 | onboot |
|---|---|---|---|---|
| VM | 150 | k3s-server | running | 1 |
| VM | 151 | k3s-agent-minipc | running | 1 |
| VM | 9000 | debian-12-template | stopped | - |
| CT | 200 | gitea | running | 1 |

- running: 150、151、200 / stopped: 9000
- k3s のノード (`kubectl --context default get nodes`): k3s-server、k3s-agent-minipc、k3s-agent-z440 すべて Ready (v1.35.0+k3s3)

#### 実行した操作

1. 18:35 `systemctl stop apt-daily-upgrade.timer` → `is-active` が inactive。作業がすべて終わるまで止めたままにする
2. 18:35 `apt-get update` → bookworm のみ。`apt list --upgradable` は上記 44 件
3. 18:35 `DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold full-upgrade` → rc=0。corosync 3.1.10-pve2~bpo12+1、qemu-server 8.4.10 等を更新。出力の末尾に「Removable bootloader found at '/boot/efi/EFI/BOOT/BOOTX64.efi', but GRUB packages not set up to update it!」の警告 (手順 3 で解消)
4. 18:36 `apt-get -y remove systemd-boot` → `systemd-boot` のみ削除 (`dpkg -l`: rc)。`systemd-boot-efi` は ii のまま
5. 18:36 `echo "grub-efi-amd64 grub2/force_efi_extra_removable boolean true" | debconf-set-selections -v -u` → `debconf-show` で true
6. 18:36 `apt-get -y install --reinstall grub-efi-amd64` → rc=0、「Installation finished. No error reported.」。grub.cfg に 6.8.12-43、6.8.12-19、6.5.13-6、6.5.11-8 の項目
7. 18:36 結果: `EFI/BOOT/BOOTx64.efi` と `EFI/proxmox/shimx64.efi` が 2026-11-22 18:36 で同日付、sha256 も一致 (759fd87f…)。`EFI/BOOT` の 4 ファイルすべてが 18:36:50 に更新。BootOrder は変わらず
8. 18:36 `apt-get update` 後の `apt list --upgradable` → 空 (「Listing...」のみ)

### タスク 2.2: NIC 名の固定

1. 18:36 `pve-network-interface-pinning generate` (既定の引数) → rc=0
   - enp1s0 → nic0、enp2s0 → nic1、wlo1 (wlp0s20f3) → nic2
   - `.link` 生成先 `/usr/local/lib/systemd/network/`、更新対象として `/etc/pve/nodes/n100/host.fw.new`、`/etc/network/interfaces.new`、`/etc/pve/sdn/controllers.cfg` を表示
   - 実際に生成された `.new` は `/etc/network/interfaces.new` のみ。`host.fw` は元から無く `host.fw.new` は生成されない。`/etc/pve/sdn/controllers.cfg` は元から無く、ツールが 0 バイトの空ファイルを作った (`.new` ではない)。`/etc/pve/sdn/fabrics.cfg` は元から無い
2. `.link` 一覧

| ファイル | MACAddress | Name |
|---|---|---|
| 50-pve-nic0.link | 70:70:fc:05:7c:c2 (enp1s0) | nic0 |
| 50-pve-nic1.link | 70:70:fc:05:7c:c3 (enp2s0) | nic1 |
| 50-pve-nic2.link | a0:02:a5:b2:4f:fd (wlo1) | nic2 |

3. 18:37 `diff -y /etc/network/interfaces /etc/network/interfaces.new` → インターフェース名を含む行がすべて新しい名前になっている (差分は `auto/iface enp1s0→nic0`、`enp2s0→nic1`、`iface wlo1→nic2`、`bridge-ports enp1s0→nic0` (vmbr0)、`bridge-ports enp2s0→nic1` (vmbr1) の 7 行のみ)。`.new` を手で直す必要は無かった。`post-up ethtool` 等の旧名を含む行は元から無い
4. `/etc/pve/firewall/cluster.fw` は存在しない (旧名の参照なし)。`/etc/pve`、`/etc/network`、`/etc/default/grub`、`/etc/udev/rules.d`、`/etc/systemd/network`、`/etc/hosts` を `enp1s0|enp2s0|wlo1|wlp0s20f3` で grep → `interfaces` 以外に一致なし
5. 18:37 `update-initramfs -u -k all` → 6.8.12-43、6.8.12-19、6.5.13-6、6.5.11-8 の 4 カーネルすべてを生成 (18:37:31〜18:38:43、いずれも `.link` の 18:36:59 より新しい)
6. 確認: `udevadm test-builtin net_setup_link` で enp1s0 → nic0、enp2s0 → nic1 が `/usr/local/lib/systemd/network/50-pve-nic{0,1}.link` で適用される。wlo1 は 99-default.link が適用され nic2 にならない (`.link` が `Type=ether` で、無線 LAN の wlo1 に一致しない)。wlo1 は DOWN で未使用、`interfaces.new` では `iface nic2 inet manual` (auto なし)
7. 確認: `lsinitramfs` で `.link` (50-pve-nic*.link) は initramfs に含まれない。bookworm の initramfs-tools の udev フック (`/usr/share/initramfs-tools/hooks/udev`) が `/lib/systemd/network` と `/etc/systemd/network` の `.link` だけを取り込み、`/usr/local/lib/systemd/network` は対象外のため。ルートは LVM でネットワークは initramfs では使わない。名前の付与は起動後のルートの udev が行う想定 (再起動で検証する)

### タスク 2.3: 再起動前の確認 (PreRebootCheck) と再起動

#### PreRebootCheck (2026-11-22 18:39)

| 項目 | 結果 |
|---|---|
| nic_link_missing | 失敗なし。3 つの物理 NIC (enp1s0、enp2s0、wlo1) の MAC すべてに `.link` がある |
| interfaces_unknown_name | 失敗なし。`interfaces.new` の名前は lo、nic0、nic1、nic2、vmbr0、vmbr1 で、nic0〜2 は `.link` にある |
| stale_name_reference | 失敗なし。`interfaces.new` に旧名なし。`cluster.fw`、`host.fw` は存在しない |
| initramfs_stale | 失敗なし。起動対象 6.8.12-43 の initrd (18:37:31) が `.link` (18:36:59) より新しい |
| grub_entry_missing | 失敗なし。`grub.cfg` に vmlinuz-6.8.12-43-pve の項目。`GRUB_DEFAULT=0` で先頭がこのカーネル |
| efi_removable_stale | 失敗なし。`BOOTx64.efi` と `EFI/proxmox/shimx64.efi` が同日付・同 sha256 |
| boot_entry_missing | 失敗なし。`efibootmgr` の BootOrder に 0001 (proxmox) |

失敗 0 件。

#### 再起動

- 18:40:27 n100 で `systemctl reboot` (ゲストは PVE の自動の停止・起動のみ。個別の操作なし)
- 18:42:29 起動 (`uptime -s`)。18:42:49 に SSH (`vmbr0` 側、作業 PC から) が復帰。SSH の不通は 約 2 分

#### PostRebootCheck (2026-11-22 18:44〜18:49)

| 項目 | 結果 |
|---|---|
| ssh_unreachable | 失敗なし。作業 PC から 192.168.1.10 に SSH 可 |
| 稼働中のカーネル | `uname -r`: 6.8.12-43-pve (導入済みの 6.8 系の最新)、`pveversion`: 8.4.21 |
| NIC 名 | nic0 (70:70:fc:05:7c:c2) と nic1 (70:70:fc:05:7c:c3) が UP。vmbr0 は 192.168.1.10/24、vmbr1 は 172.16.0.2/16。`/etc/network/interfaces` は `interfaces.new` に置き換わり (`interfaces.new` は消えた)。wlo1 は nic2 にならず wlo1 のまま DOWN (2.2 の確認 6 のとおり) |
| link_unreachable | 失敗なし。hp-z440 から `ping -c3 172.16.0.2` 3/3 到達 (損失 0%、平均 0.38 ms) |
| no_quorum | 失敗なし。n100 と hp-z440 の両方で `pvecm status` が Nodes 2、Quorate Yes |
| guest_not_running | 失敗なし。VM 150、151、CT 200 が running |
| guest_started_unexpectedly | 失敗なし。VM 9000 は stopped のまま |
| passthrough_missing | 対象なし (n100 にパススルーは無い) |
| k3s_node_not_ready | 失敗あり。下記 |
| `apt list --upgradable` | 空 |
| `systemctl --failed` | `openipmi.service` のみ (n100 に IPMI が無く、前回の 2026-08-30 の起動でも同じ失敗。今回の作業とは無関係) |
| `apt-daily-upgrade.timer` | 再起動で active に戻っていた (enabled のため)。18:46 に `systemctl stop apt-daily-upgrade.timer` で再度停止 (inactive) |

k3s のノードの確認: `kubectl --context default get nodes` が 18:44 から 18:50 まで `192.168.1.150:6443` への接続拒否。VM 150 (k3s-server) は起動して SSH 可だが、`k3s.service` が起動のたびに fatal で終了し再起動を繰り返している (18:43 の初回から 75 回)。

- 該当のログ: `level=fatal msg="/var/lib/rancher/k3s/server/cred/passwd newer than datastore and could cause a cluster outage. Remove the file(s) from disk and restart to be recreated from datastore."`
- VM 150 の停止は正常 (前回起動のログ末尾が `Shutting down.` / `Journal stopped`、18:40:35)
- 対処は VM 150 の中のファイル削除になり、ゲストの設定変更に当たるため、この記録の時点では行っていない

#### k3s-server の復旧 (2026-11-22 19:24〜19:29)

- 原因: 2026-09-03 の `k3s token rotate` の直後に `agent-token` を加えて k3s を再起動したため、`server/cred/passwd` だけが書き換わり、datastore (embedded etcd) の bootstrap データは古いまま残った。その後 k3s は再起動しておらず、今回の再起動で `isNewerFile` の判定 (v1.35.0+k3s3 の `pkg/cluster/bootstrap.go`) に掛かった。時計・k3s の版・n100 の apt 更新・NIC 名の固定は原因ではない
- 19:24:55 VM 150 で `/var/lib/rancher/k3s/server/cred/passwd` を `/root/passwd.bak-20261122` へ移した (ユーザー承認済み)。19:25:00 に passwd が datastore から再作成され、19:25:09 に `k3s.service` が active。以後 fatal なし
- `kubectl --context default get nodes`: k3s-server、k3s-agent-minipc、k3s-agent-z440 の 3 ノードが Ready (v1.35.0+k3s3)
- `cnpg-system/cnpg-controller-manager` は API の停止中に `connection refused` で落ち、backoff の上限 (5 分) の後の 19:28:53 に自然に Running に戻った。CNPG の Cluster `nextcloud/nextcloud-db` と `postgres/postgres-cluster` は healthy で、DB の Pod の restarts は 0
- k3s の API の停止: 18:40〜19:25
- 起動のたびに passwd の node のエントリが `agent-token` で書き直され、datastore は上書きされないため、次に k3s-server を再起動すると同じ fatal になる。server token のローテーションは行わない (ユーザーの判断)

## クラスタ

### タスク 3: `TerraformProvisioner` から `VM.Monitor` を外す (2026-11-22 21:38、n100 から実行)

- 変更前の `pveum role list` の該当行 (`/etc/pve/user.cfg` の `role:` 行と一致): `Datastore.Allocate, Datastore.AllocateSpace, Datastore.AllocateTemplate, Datastore.Audit, Sys.Audit, VM.Allocate, VM.Audit, VM.Backup, VM.Clone, VM.Config.CDROM, VM.Config.CPU, VM.Config.Cloudinit, VM.Config.Disk, VM.Config.HWType, VM.Config.Memory, VM.Config.Network, VM.Config.Options, VM.Monitor, VM.PowerMgmt` (19 件)
- 実行: `pveum role modify TerraformProvisioner --privs "<上記から VM.Monitor だけを除いた 18 件>"` → rc=0
- 変更後の該当行: `Datastore.Allocate, Datastore.AllocateSpace, Datastore.AllocateTemplate, Datastore.Audit, Sys.Audit, VM.Allocate, VM.Audit, VM.Backup, VM.Clone, VM.Config.CDROM, VM.Config.CPU, VM.Config.Cloudinit, VM.Config.Disk, VM.Config.HWType, VM.Config.Memory, VM.Config.Network, VM.Config.Options, VM.PowerMgmt` (18 件。差分は `VM.Monitor` の除去のみ)
- ACL は変更なし。`user.cfg` の `acl:1:/:terraform@pve:TerraformProvisioner:`、`/sdn/zones/localnetwork/vmbr0` と `vmbr1` の `PVESDNUser` を確認
- 判定: `VM.Monitor` を含まない。この時点から Terraform を実行しない (`VM.GuestAgent.Audit` はタスク 8 で足す)

## n100 (続き)

### タスク 4.1: 事前チェッカーとバックアップ

#### 前夜のバックアップジョブ (2026-11-22 21:38 確認)

- ジョブ `488fba22-…` (vzdump、04:30、`pbs-zfs-pool`、snapshot、vmid 150,151,152,201,202、keep-last=2)
- `pvesh get /cluster/tasks` の vzdump タスク: 2026-11-22 04:30 に n100 (開始 04:30:08)、hp-z440 (開始 04:30:03) とも OK。直近 11〜14 日分もすべて OK
- PBS 上の VM 150 / 151 に 2026-11-21T19:30 UTC (= 11-22 04:30 JST) のバックアップがある

#### `pve8to9 --full` (2026-11-22 21:38、PVE 8.4.21)

結果: TOTAL 48、PASS 38、SKIP 5、WARN 3、FAIL 0。

| WARN | 扱い |
|---|---|
| `cluster consists of less than three quorum-providing nodes!` | 解消しない。QDevice の追加は本 spec の Non-Goals |
| `3 running guest(s) detected - consider migrating or stopping them.` | 解消しない。ゲストを他方のノードへ移さない (要件 3.5)。ゲストは `dist-upgrade` の間も稼働のまま、停止は再起動時の自動の停止・起動のみ |
| `The matching CPU microcode package 'intel-microcode' could not be found!` | 解消しない。パッケージの追加は design.md の手順に無く、本 spec の範囲外 |

SKIP 5 件: Ceph 無し、`zfs-pool` が disabled、RBD 無し、LXCFS が未更新、dkms の状態が取れない (dkms 未導入)。
NOTICE 1 件: `local-lvm` のゲストボリュームに autoactivation が有効なものがある (`pve-lvm-disable-autoactivation` で無効化できるが、ローカルストレージのみで問題にならないとチェッカー自身が説明している)。design.md に無い変更のため実行していない。

#### 当日の手動バックアップ

- バックアップ対象: `pbs_backup_targets` のうち n100 のゲストは VM 150 (k3s-server)、VM 151 (k3s-agent-minipc)。CT 200 (gitea) は `pbs_backup_excluded_targets` (github-offsite-backup)、VM 9000 はテンプレートで対象外
- 21:38:59 `vzdump 150 151 --storage pbs-zfs-pool --mode snapshot --compress zstd --prune-backups keep-all=1` を n100 の tmux (`ve9`) の中で実行。ログ: n100 の `/root/ve9-upgrade-logs/vzdump-manual.log`。`--prune-backups keep-all=1` は手動の実行で既存世代を間引かないための指定
- 結果: VM 150 は 64.00 GiB を 126 秒、VM 151 は 64.00 GiB を 121 秒で転送、`Backup job finished successfully`、rc=0
- 21:43 `pvesm list pbs-zfs-pool` の当日分:

| VMID | volid |
|---|---|
| 150 | `pbs-zfs-pool:backup/vm/150/2026-11-22T12:38:59Z` |
| 151 | `pbs-zfs-pool:backup/vm/151/2026-11-22T12:41:07Z` |

(11-20 と 11-21 の夜間分も残っている。ゲストは作業前の状態のまま: 150、151、CT 200 が running、9000 が stopped)

### タスク 4.2: 9 への更新と再起動の準備

#### dist-upgrade (2026-11-22 21:43〜21:51)

1. 21:43 n100 の tmux セッション `ve9-upgrade` の中で `/root/ve9-upgrade-logs/dist-upgrade.sh` を実行 (ログ: `/root/ve9-upgrade-logs/dist-upgrade.log`)。スクリプトの内容:
   - 旧 `/etc/apt/sources.list`、`ceph.list` (全行コメント)、`pve-enterprise.list` (全行コメント) を `/root/ve9-upgrade-logs/apt-sources-before/` へ退避し、`sources.list` を空にした
   - `/etc/apt/sources.list.d/debian.sources` (`http://deb.debian.org/debian` の `trixie trixie-updates`、`http://security.debian.org/debian-security` の `trixie-security`。Components は `main contrib non-free-firmware`、Signed-By は `/usr/share/keyrings/debian-archive-keyring.gpg`) と `proxmox.sources` (`http://download.proxmox.com/debian/pve` の `trixie`、`pve-no-subscription`、Signed-By は `/usr/share/keyrings/proxmox-archive-keyring.gpg`) を作成
   - `apt-get update` (rc=0)、`DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef dist-upgrade`
2. 計画: 630 upgraded、247 newly installed、64 to remove (削除は libssl3 等の t64 移行の旧ライブラリ)。ダウンロードは 21:43 から。`DIST_UPGRADE_RC=0`、21:51:29 完了
3. 設定ファイルの扱い (`--force-confold`): 対話の問い合わせは `/etc/issue` の 1 件のみ (既存を残した)。`/etc/lvm/lvm.conf` は既存を残し、新しい版が `/etc/lvm/lvm.conf.dpkg-dist` に置かれた。`/etc/default/grub` は問われず、既存の内容のまま (`GRUB_DEFAULT=0`、`GRUB_CMDLINE_LINUX_DEFAULT="quiet"`、`GRUB_DISABLE_OS_PROBER=true`)
4. `pveversion`: `pve-manager/9.2.32/60a22e26e411402f` (`proxmox-ve: 9.2.0`、`proxmox-kernel-helper 9.2.1`、`proxmox-default-kernel 2.1.0`、`proxmox-kernel-7.0 7.0.14-30`)。稼働中のカーネルは再起動前なので 6.8.12-43-pve のまま
5. 21:52 `DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold install proxmox-default-headers` (tmux セッション `ve9-headers`、ログ `/root/ve9-upgrade-logs/headers.log`) → rc=0。`proxmox-default-headers 2.1.0`、`proxmox-headers-7.0.14-30-pve` が入った
6. 21:54 `pve-manager` 9 が `/etc/apt/sources.list.d/pve-enterprise.sources` (有効な enterprise リポジトリ) を置いていたので、design.md の「他の `.sources` を削除する」に従い削除した (退避: `/root/ve9-upgrade-logs/apt-sources-before/pve-enterprise.sources.from-pve-manager-9`)。`apt-get update` は 4 つの参照先すべてが Hit で、`apt list --upgradable` は 0 件
7. ゲストは hp-z440 へ移していない。tmux のセッションは作業後に撤去 (ログは残す)

#### dist-upgrade の副作用 (想定外)

- `chrony.service` が 21:49:24 から failed (`Fatal error : Could not send notification to $NOTIFY_SOCKET`)。`dist-upgrade` の途中で systemd が 252 から 257 に入れ替わる間に、旧 systemd (稼働中の PID 1 は 18:42 起動のまま) 配下で新しい chronyd が起動したため。`systemctl restart chrony` と `systemctl daemon-reexec` の後の `restart` でも同じ失敗のまま。n100 の時刻同期は、9 での再起動 (タスク 4.3) まで止まった状態。再起動後に active かを確かめる
- `openipmi.service` の failed は 2.3 のとおり n100 に IPMI が無いため (作業と無関係)
- dist-upgrade の途中、`openssh-server` の入れ替えの間に `systemctl: error while loading shared libraries: libcrypto.so.3` が 1 回出た (dpkg は rc=0 で完了)。更新後、新しい SSH 接続はできるが `scp` が `Connection closed` で失敗する (sftp-server は `/usr/lib/openssh/sftp-server` にある)。`ssh` 経由の `cat` でファイルを置いた。再起動で解消するかを 4.3 で確かめる

#### BootDeadman の配置 (2026-11-22 21:54)

- 戻り先のカーネル: `6.8.12-43-pve` (タスク 2.3 で起動と PostRebootCheck を確かめたもの)。`proxmox-kernel-6.8.12-43-pve-signed 6.8.12-43` は dist-upgrade の後も導入済み
- 配置したファイル (n100 上。IaC には入れない):
  - `/usr/local/sbin/upgrade-deadman`: `/run/upgrade-deadman/confirmed` があれば何もしない。稼働中のカーネルが `6.8.12-43-pve` なら何もしない。それ以外なら `proxmox-boot-tool kernel pin 6.8.12-43-pve` を実行して `systemctl reboot`
  - `/etc/systemd/system/upgrade-deadman.service` (oneshot)、`/etc/systemd/system/upgrade-deadman.timer` (`OnBootSec=15min`、`WantedBy=timers.target`)
- `systemctl enable --now upgrade-deadman.timer` → `is-enabled` enabled、`is-active` active。`systemd-analyze verify` 問題なし
- 有効化の直後に、起動から 15 分を過ぎているためタイマーが 1 回発火した (21:54:17)。稼働中のカーネルが戻り先と同じなので何もせず終了 (`status=0/SUCCESS`)。`proxmox-boot-tool kernel list` に固定なし (`Manually selected kernels: None`)。9 での再起動後は、起動から 15 分で発火する
- 撤去の手順 (タスク 4.3): `systemctl disable --now upgrade-deadman.timer` と、上記 3 ファイルの削除、`daemon-reload`

#### PreRebootCheck (2026-11-22 21:54〜21:55、対象カーネル 7.0.14-30-pve)

| 項目 | 結果 |
|---|---|
| nic_link_missing | 失敗なし。物理 NIC の nic0 (70:70:fc:05:7c:c2、r8169)、nic1 (70:70:fc:05:7c:c3、r8169)、wlo1 (a0:02:a5:b2:4f:fd、iwlwifi) の MAC すべてに `.link` (50-pve-nic{0,1,2}.link) がある |
| interfaces_unknown_name | 失敗なし。`/etc/network/interfaces` の名前は lo、nic0、nic1、nic2、vmbr0 (`bridge-ports nic0`)、vmbr1 (`bridge-ports nic1`)。`interfaces.new` は無い (8.4 の再起動で適用済み) |
| stale_name_reference | 失敗なし。`/etc/network`、`/etc/pve`、`/etc/default/grub*`、`/etc/udev/rules.d`、`/etc/systemd/network`、`/etc/hosts` に `enp1s0|enp2s0|wlp0s20f3` なし。`cluster.fw`、`host.fw` は存在しない |
| initramfs_stale | 失敗なし。`initrd.img-7.0.14-30-pve` (21:51:21) が `.link` (18:36:59) より新しい。`.link` は initramfs に含まれない (8.4 で起動を確かめた 6.8.12-43 の initramfs も同じで、名前の付与は起動後のルートの udev が行う) |
| grub_entry_missing | 失敗なし。`grub.cfg` の既定の項目 (`GRUB_DEFAULT=0` の先頭) が `/boot/vmlinuz-7.0.14-30-pve` と `initrd.img-7.0.14-30-pve`。6.8.12-43-pve の項目も残っている |
| efi_removable_stale | 失敗なし。`EFI/BOOT/BOOTx64.efi` (21:50:56) と `EFI/proxmox/shimx64.efi` (21:50:54) が同日付、sha256 一致 (9dee7152…) |
| boot_entry_missing | 失敗なし。`efibootmgr` の BootOrder は 0001 (proxmox) , 0002〜0005, 0007 |
| パッケージ | `dpkg --audit` 空、`apt-get check` 正常、`apt list --upgradable` 0 件 |

失敗 0 件。

#### 4.2 の受入の実測 (2026-11-22 21:55)

- `pveversion`: `pve-manager/9.2.32/60a22e26e411402f`
- `apt policy` の参照先: `deb.debian.org/debian` の `trixie`・`trixie-updates` (main / contrib / non-free-firmware)、`security.debian.org/debian-security` の `trixie-security`、`download.proxmox.com/debian/pve` の `trixie/pve-no-subscription` のみ。`/etc/apt/sources.list.d/` は `debian.sources` と `proxmox.sources` の 2 ファイル、`/etc/apt/sources.list` は 0 バイト
- BootDeadman: `upgrade-deadman.timer` が enabled / active
- `apt-daily-upgrade.timer`: disabled / inactive のまま
- ゲスト: VM 150、151、CT 200 が running、VM 9000 が stopped のまま。`pvecm status` は Nodes 2、Quorate Yes。再起動はしていない (稼働中のカーネルは 6.8.12-43-pve)

### タスク 4.3 (1 回目、失敗)

- 2026-11-22 21:56:45 n100 で `systemctl reboot`。7.0.14-30-pve で起動し emergency mode に落ちた。SSH・`vmbr1` とも不通。emergency mode ではタイマーが動かず、BootDeadman は発動しなかった
- 原因: カーネル 6.9 以降の ahci が LPM の既定値 (`CONFIG_SATA_MOBILE_LPM_POLICY=3`) を全チップセットに掛けるようになり (上流 commit 7627a0edef54「ata: ahci: Drop low power policy board type」)、n100 (Alder Lake-N `8086:54d3`) のルートの SSD (ata2) が `lpm-pol 3` でリンクのリセットと `READ FPDMA QUEUED` の失敗を繰り返した。`I/O error, dev sda` が 35 回。udevd・journald・modules-load が timeout し、`/boot/efi` と `/dev/pve/swap` のデバイスを待って emergency mode になった。6.8 の起動はどれも `lpm-pol 0` でエラー 0 件。SMART は PASSED (Reallocated 0、UDMA_CRC_Error_Count 0)。userspace (systemd 257.13) は 6.8 で正常に動いており、原因ではない
- 2026-11-24 23:35 現地で電源を入れ直し、GRUB から 6.8.12-43-pve を選んで起動
- 2026-11-25 00:06 `proxmox-boot-tool kernel pin 6.8.12-43-pve` で既定の起動対象を 6.8 に固定
- 2026-11-25 00:07:16 VM 150 で `/var/lib/rancher/k3s/server/cred/passwd` を `/root/passwd.bak-20261122-2` へ移した (ユーザー承認済みの手順)。00:07:33 に k3s の 3 ノードが Ready、00:08:45 に `cloud.fickledev.com` が HTTP 200
- n100 のゲスト (VM 150、151、CT 200) は稼働、VM 9000 は停止のまま。quorum は Nodes 2、Quorate

### タスク 4.3 (2 回目)

- 2026-11-25 00:13 n100 の `/etc/default/grub` を `/root/ve9-upgrade-logs/grub.before-lpm` に退避し、`GRUB_CMDLINE_LINUX_DEFAULT="quiet ahci.mobile_lpm_policy=0"` に変更。`modinfo -k 7.0.14-30-pve ahci` に `mobile_lpm_policy` があることを確認
- `proxmox-boot-tool kernel pin 7.0.14-30-pve --next-boot` (既定の固定は 6.8.12-43-pve のまま)。`grub.cfg` の 7.0 の項目 2 件に引数が入ったことを確認
- 00:19:29 `systemctl reboot` (作業者が現地に待機)。00:21:32 に 7.0.14-30-pve で起動。00:22 に BootDeadman の確認の印を作成
- PostRebootCheck (00:22〜00:24):
  - `/proc/cmdline` に `ahci.mobile_lpm_policy=0`。`dmesg` で ata1・ata2 とも `lpm-pol 0`、ata の exception と I/O error は 0 件
  - nic0・nic1 が UP、vmbr0 は 192.168.1.10/24、vmbr1 は 172.16.0.2/16。hp-z440 から `ping -c3 172.16.0.2` 3/3
  - `pvecm status`: Nodes 2、Quorate Yes
  - VM 150、151、CT 200 が running、VM 9000 は stopped のまま
  - `pveversion`: pve-manager/9.2.32 (running kernel: 7.0.14-30-pve)
  - `chrony` active、作業 PC から `scp` 成功 (dist-upgrade 直後の失敗は再起動で解消)
  - `systemctl --failed`: `openipmi.service` のみ (以前からの失敗)
  - `apt-daily-upgrade.timer` は inactive (disabled)
  - k3s-server は `passwd newer than datastore` の fatal (2 回)。00:22:44 に passwd を `/root/passwd.bak-20261125` へ移した。00:23:10 に 3 ノード Ready、00:23:55 に `cloud.fickledev.com` が HTTP 200。Running/Completed 以外の Pod なし
- 00:25 BootDeadman を撤去 (`upgrade-deadman.timer` を disable、`upgrade-deadman.service`・`.timer`・`/usr/local/sbin/upgrade-deadman` を削除し `daemon-reload`)。`proxmox-boot-tool kernel unpin` で 6.8 の固定を外し、GRUB の既定は先頭の項目 (7.0.14-30-pve)

### n100 の停止と復帰 (2026-11-26〜27)

- 2026-11-26 17:52:02 hp-z440 の corosync に `[CFG] Node 2 was shut down by sysadmin`。n100 は正常な手順でシャットダウンされた。本 spec の作業ではない (11-25 01:05 以降 n100 への操作なし)。停止中は VM 150・151 が止まり、k3s API と Nextcloud が停止。hp-z440 は 2Node 構成で単独 Quorate
- 2026-11-27 01:51 タスク 6.3 の再起動前の確認で停止を検知し、hp-z440 の再起動を見送った
- 03:11 頃 ユーザーが n100 を起動。7.0.14-30-pve、Quorate、VM 150・151 は onboot で running
- k3s-server は `passwd newer than datastore` の fatal (104 回)。03:21:47 に passwd を `/root/passwd.bak-20261127` へ移した。03:22:00 に 3 ノード Ready、Running/Completed 以外の Pod なし、`cloud.fickledev.com/status.php` が HTTP 200

## hp-z440 (192.168.1.2、root)

### タスク 5.1: 作業の開始、8.4 の最新、ブート構成の修正、存在しないインターフェースの除去

#### 作業前の状態 (2026-11-25 00:25)

| 項目 | 値 |
|---|---|
| `pveversion` | pve-manager/8.4.21、稼働中のカーネル 6.8.12-19-pve |
| ルートの空き | `df -h /`: 94G 中 24G 使用、空き 66G (10 GB 以上を満たす) |
| `apt-daily-upgrade.timer` | active (作業前) |
| クォーラム | `pvecm status`: Nodes 2、Quorate Yes (two_node) |
| `grub2/force_efi_extra_removable` | false。`EFI/BOOT/BOOTx64.efi` は 2024-04-03 のまま、`EFI/proxmox/` は 2026-09-04 |
| `apt list --upgradable` | 78 パッケージ |
| `/etc/network/interfaces` | `auto enxc436c0eafd1d` / `iface enxc436c0eafd1d inet manual` が残っている (実在する NIC は eno1、ens5f0〜ens5f3) |
| `GRUB_CMDLINE_LINUX_DEFAULT` | `"quiet nouveau.modeset=0"` |

作業前のゲストの一覧 (`qm list` / `pct list`。VM 105 は記録の対象外):

| 種別 | ID | 名前 | 作業前の状態 | onboot |
|---|---|---|---|---|
| VM | 108 | windows | stopped | - |
| VM | 110 | tv | running | 1 |
| VM | 152 | k3s-agent-z440 | running | 1 |
| VM | 201 | nas | running | 1 |
| VM | 9001 | debian-12-template | stopped | - |
| CT | 202 | pbs | running | 1 |

- running: 110、152、201、202 / stopped: 108、9001
- パススルー
  - VM 110: `usb0: host=3275:0080`、`usb1: host=058f:9540` (USB)。ディスクは `virtio0: local-lvm:vm-107-disk-1` (128G) のみで、ホストのディスクのパススルーは無い
  - VM 108 (停止中): `hostpci0: 0000:01:00.0,pcie=1` (GPU)
  - VM 152: `scsi2` / `scsi3` は `zfs-pool` のボリューム。VM 201: `scsi1` は `zfs-pool` のボリューム。CT 202: `mp0: zfs-pool:subvol-202-disk-0`。ホストのディスクのパススルーは無い

#### 実行した操作

1. 00:25 `systemctl disable --now apt-daily-upgrade.timer` → disabled / inactive。ノードの作業がすべて終わるまで戻さない
2. 00:25 `/root/ve9-upgrade-logs/` を作り、`/etc/default/grub` (`grub.before-lpm`)、`/etc/network/interfaces` (`interfaces.before-5.1`)、`/etc/modules` (`modules.before-5.2`) を退避
3. 00:26 `apt-get -s full-upgrade` → 削除対象なし (ceph の 19.2.5 への更新を含む)。`DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold full-upgrade` → rc=0 (ログ `/root/ve9-upgrade-logs/full-upgrade.log`)。カーネルの追加なし (6.8.12-43-pve は導入済みで未起動)。末尾に removable bootloader の警告 (手順 5 で解消)
4. 00:27 `apt-get -y remove systemd-boot` → `systemd-boot` のみ削除 (`dpkg -l`: rc)。`systemd-boot-efi` は ii のまま
5. 00:27 `debconf-set-selections` で `grub2/force_efi_extra_removable` を true にし (`debconf-show` で true)、`apt-get -y install --reinstall grub-efi-amd64` → rc=0。`EFI/BOOT/` の 4 ファイルと `EFI/proxmox/` の 6 ファイルがすべて 2026-11-25 00:27 に更新。`EFI/BOOT/BOOTx64.efi` と `EFI/proxmox/shimx64.efi` の sha256 が一致 (759fd87f…)。`efibootmgr` の BootCurrent は 000C のまま
6. 00:28 `/etc/default/grub` の `GRUB_CMDLINE_LINUX_DEFAULT` を `"quiet nouveau.modeset=0"` → `"quiet nouveau.modeset=0 ahci.mobile_lpm_policy=0"` に変更 (`diff` で当該 1 行のみ)。`update-grub` → rc=0。`grub.cfg` の `ahci.mobile_lpm_policy=0` は 5 行で、既定の 6.8.12-43-pve の項目を含む (`linux /boot/vmlinuz-6.8.12-43-pve root=/dev/mapper/pve-root ro quiet nouveau.modeset=0 ahci.mobile_lpm_policy=0`)
7. 00:28 `/etc/network/interfaces` から `auto enxc436c0eafd1d`、`iface enxc436c0eafd1d inet manual` と直後の空行の 3 行を除去 (`diff` で除去の 3 行のみ)。残る定義は lo、eno1、ens5f0〜ens5f3、vmbr0、vmbr1。`ifquery --list -a` は lo、eno1、vmbr0、vmbr1。実在する NIC (`ip -br link`) は eno1、ens5f0〜ens5f3 で、除去した定義の NIC は無い
8. 00:28 `apt-get update` 後の `apt list --upgradable` → 空 (「Listing...」のみ)

判定: `apt list --upgradable` が空、EFI のフォールバックが `EFI/proxmox` と同日付・同 sha256、`/etc/network/interfaces` が実在するインターフェースだけを参照している。

### タスク 5.2: Ceph のサーバー側と旧 NVIDIA ドライバの除去

1. 00:28 `apt-get -s remove` で対象を確認 → 削除対象は 9 パッケージのみ (`ceph`、`ceph-base`、`ceph-mds`、`ceph-mgr`、`ceph-mgr-modules-core`、`ceph-mon`、`ceph-osd`、`ceph-volume`、`libsqlite3-mod-ceph`)。`apt-get -y remove` で削除し、`/etc/apt/sources.list.d/ceph.list` (`deb … ceph-squid bookworm no-subscription`) を削除。`apt-get update` 後の `sources.list.d` は `pve-enterprise.list` のみ
2. 残った設定 (dpkg の rc) の `ceph-base`、`ceph-mds`、`ceph-mgr`、`ceph-mon`、`ceph-osd` を `apt-get -y purge`。`/var/lib/ceph` は空で、`/etc/ceph` (`ceph.conf`、`ceph.client.admin.keyring`、`rbdmap`) は `ceph-common` の所有で残る。クライアント側 (`ceph-common`、`ceph-fuse`、`libcephfs2`、`python3-ceph-argparse`、`python3-ceph-common`、`python3-cephfs` など) は ii のまま
3. 00:29 NVIDIA: `dpkg -l` で `nvidia` / `glx-alternative-nvidia` に一致する ii のうち `pve-nvidia-vgpu-helper` を除く 24 パッケージ (`nvidia-kernel-dkms`、`nvidia-smi`、`nvidia-persistenced`、`nvidia-modprobe`、`nvidia-driver-libs`、`libnvidia-*`、`libegl-nvidia0`、`libglx-nvidia0`、`libgl1-nvidia-glvnd-glx`、`firmware-nvidia-gsp`、`glx-alternative-nvidia`、`nvidia-alternative` ほか。すべて 535 系または Debian 12 由来) を `apt-get -s purge` で確認 → 削除対象は上記に加えて `glx-diversions` (`glx-alternative-nvidia` の付随) のみ。`pve-nvidia-vgpu-helper` は `pve-manager` が依存するため残す。`apt-get -y purge` → rc=0 (ログ `/root/ve9-upgrade-logs/nvidia-purge.log`)
4. `/etc/modules` の `nvidia`、`nvidia_uvm` の 2 行を削除 (`diff` で当該 2 行のみ)
5. 確認 (`dpkg -l`): `ceph*`・`libceph*`・`python3-ceph*` で残るのは上記のクライアント側 (`ceph-common`、`ceph-fuse`、`libcephfs2`、`python3-ceph-argparse`、`python3-ceph-common`、`python3-cephfs`) のみ。`nvidia` / `libnvidia` / `firmware-nvidia` は ii も rc も無い。`proxmox-ve` 8.4.0、`pve-manager` 8.4.21 は残っている。`apt list --upgradable` は空
6. 00:30 `pve8to9 --full` (出力は `/root/ve9-upgrade-logs/pve8to9-hp-z440.txt`) → TOTAL 48、FAIL 0。Ceph は「SKIP: no hyper-converged ceph setup detected!」で FAIL なし

| WARN | 扱い |
|---|---|
| `cluster consists of less than three quorum-providing nodes!` | 解消しない。QDevice の追加は本 spec の Non-Goals |
| `4 running guest(s) detected - consider migrating or stopping them.` | 解消しない。ゲストを他方のノードへ移さない (要件 3.5) |
| `The matching CPU microcode package 'intel-microcode' could not be found!` | 解消しない。パッケージの追加は design.md の手順に無く、本 spec の範囲外 |

- GPU (VM 108 のパススルーではなくホスト側のドライバ) はメジャー更新が終わるまで使えない (design.md のとおり)。`nvidia-persistenced` は purge で外れた

### タスク 5.3: NIC 名の固定

1. 00:29 `pve-network-interface-pinning generate` (既定の引数) → rc=0
   - ens5f0 (enp3s0f0) → nic0、ens5f1 (enp3s0f1) → nic1、ens5f2 (enp3s0f2) → nic2、ens5f3 (enp3s0f3) → nic3、eno1 (enp0s25) → nic4
   - 更新対象として `host.fw.new`、`interfaces.new`、`/etc/pve/sdn/controllers.cfg` を表示。実際に生成された `.new` は `/etc/network/interfaces.new` のみ。`host.fw` は元から無く `.new` は生成されない。`/etc/pve/sdn/controllers.cfg` は元から無く、0 バイトの空ファイルができた (`.new` ではない)。`fabrics.cfg` は元から無い (`/etc/pve/sdn/fabrics` ディレクトリは 5.1 の `full-upgrade` の `pve-manager` のトリガーが作成)
2. `.link` 一覧 (`/usr/local/lib/systemd/network/`、いずれも `Type=ether`)

| ファイル | MACAddress | Name |
|---|---|---|
| 50-pve-nic0.link | 98:be:94:04:8e:98 (ens5f0) | nic0 |
| 50-pve-nic1.link | 98:be:94:04:8e:99 (ens5f1) | nic1 |
| 50-pve-nic2.link | 98:be:94:04:8e:9a (ens5f2) | nic2 |
| 50-pve-nic3.link | 98:be:94:04:8e:9b (ens5f3) | nic3 |
| 50-pve-nic4.link | c8:d3:ff:b5:f3:52 (eno1) | nic4 |

3. 00:29 `diff -y /etc/network/interfaces /etc/network/interfaces.new` → `auto/iface eno1→nic4`、`ens5f1→nic1`、`ens5f2→nic2`、`ens5f3→nic3`、`ens5f0→nic0`、`bridge-ports eno1→nic4` (vmbr0)、`bridge-ports ens5f0→nic0` (vmbr1) の 8 行が置き換わった。`post-up ethtool -K eno1 tso off gso off gro off` (vmbr0 の行) は置き換わっていなかった
4. 00:30 `interfaces.new` の `post-up ethtool -K eno1 …` を `post-up ethtool -K nic4 tso off gso off gro off` に手で直した (`sed` で当該 1 行のみ)。`interfaces.new` に旧名 (`eno1`、`ens5f*`、`enp*`、`enx*`) は無く、`post-up` の行は 1 行で nic4 を指す。`diff` の `>` 側は 9 行
5. `/etc/pve/firewall/` は空で `cluster.fw` は無い (旧名の参照なし)。`/etc/pve`、`/etc/network`、`/etc/default/grub`、`/etc/udev/rules.d`、`/etc/systemd/network`、`/etc/hosts`、`/etc/modprobe.d`、`/etc/modules` を旧名で grep → `/etc/network/interfaces` (現行、再起動で `interfaces.new` に置き換わる) のみ。`/etc`・`/usr/local`・`/root` 全体の grep でも同じ
6. 00:30〜00:31 `update-initramfs -u -k all` → 6.8.12-43、6.8.12-19、6.5.13-6、6.5.11-8 の 4 カーネルすべてを生成 (00:29:45〜00:31:01、いずれも `.link` の 00:29:12 より新しい)。`lsinitramfs` で `.link` (pve-nic*) は 4 つとも含まれない (n100 の 2.2 と同じ)

### タスク 5.1〜5.3 後のノードの状態 (2026-11-25 00:31)

- 再起動していない (稼働中のカーネルは 6.8.12-19-pve)。VM 110、152、201、CT 202 が running、VM 108、9001 が stopped のまま。`pvecm status`: Nodes 2、Quorate Yes
- `apt-daily-upgrade.timer`: disabled / inactive。`systemctl --failed`: `openipmi.service` のみ

### VM 105 の起動設定 (タスク 5.4 の前提)

- 2026-11-25 00:26:29 hp-z440 で `qm set 105 --onboot 0` (ユーザー承認済み)。VM 105 は停止のまま。hp-z440 の再起動で起動しない。戻すときは `qm set 105 --onboot 1`

### タスク 5.4: 再起動前の確認 (PreRebootCheck) と再起動

#### 作業前のゲストの状態 (2026-11-25 00:32)

| 項目 | 値 |
|---|---|
| running | VM 110 (tv)、VM 152 (k3s-agent-z440)、VM 201 (nas)、CT 202 (pbs) |
| stopped | VM 108 (windows)、VM 9001 (debian-12-template)。VM 105 は停止で対象外 (`onboot: 0`) |
| パススルー | VM 110: `usb0: host=3275:0080`、`usb1: host=058f:9540` (ホストの `lsusb` に両方あり)。VM 108: `hostpci0: 0000:01:00.0,pcie=1` (停止中) |
| カーネル | 稼働中 6.8.12-19-pve |
| `pvecm status` | Nodes 2、Quorate Yes |
| k3s | `kubectl --context default get nodes`: 3 ノード Ready。Running/Completed 以外の Pod なし |
| PBS | `proxmox-backup-manager datastore list`: zfs-pool (`/mnt/zfs-pool-0`) |

#### PreRebootCheck (2026-11-25 00:32、対象カーネル 6.8.12-43-pve)

| 項目 | 結果 |
|---|---|
| nic_link_missing | 失敗なし。物理 NIC 5 つ (ens5f0〜3、eno1) の MAC すべてに `50-pve-nic{0..4}.link` がある |
| interfaces_unknown_name | 失敗なし。`interfaces.new` の名前は lo、nic0〜4、vmbr0、vmbr1 で、nic0〜4 は `.link` にある |
| stale_name_reference | 失敗なし。`interfaces.new` を `eno1|ens5f|enp|enx` で grep して一致なし (`post-up ethtool -K nic4`)。`/etc/pve/firewall/*.fw` は存在しない |
| initramfs_stale | 失敗なし。`initrd.img-6.8.12-43-pve` (00:29:45) が `.link` (00:29:12) より新しい |
| grub_entry_missing | 失敗なし。`grub.cfg` に `vmlinuz-6.8.12-43-pve` の項目 (cmdline に `quiet nouveau.modeset=0 ahci.mobile_lpm_policy=0`)。`GRUB_DEFAULT=0` で先頭がこのカーネル |
| efi_removable_stale | 失敗なし。`EFI/BOOT/BOOTx64.efi` と `EFI/proxmox/shimx64.efi` が同日時 (00:27:28)・同 sha256 (759fd87f…) |
| boot_entry_missing | 失敗なし。`efibootmgr` の BootCurrent と BootOrder の先頭が 000C (proxmox) |
| VM 105 の扱い | 決定済み (`onboot: 0`、停止) |

失敗 0 件。

#### 再起動

- 00:33:10 hp-z440 で `systemctl reboot` (ゲストは PVE の自動の停止・起動のみ。個別の操作なし)
- 00:37:37 起動 (`uptime -s`)。00:37:56 に SSH (`vmbr0` 側、作業 PC から) が復帰。SSH の不通は 約 4 分 (10 分以内)

#### PostRebootCheck (2026-11-25 00:38)

| 項目 | 結果 |
|---|---|
| ssh_unreachable | 失敗なし。作業 PC から 192.168.1.2 に SSH 可 |
| 稼働中のカーネル | `uname -r`: 6.8.12-43-pve (導入済みの 6.8 系の最新、`grub.cfg` の既定)、`pveversion`: 8.4.21 |
| `/proc/cmdline` | `BOOT_IMAGE=/boot/vmlinuz-6.8.12-43-pve root=/dev/mapper/pve-root ro quiet nouveau.modeset=0 ahci.mobile_lpm_policy=0` |
| `dmesg` | ata1〜 の `lpm-pol 0`。`ata.*exception` は 0 件 |
| NIC 名 | nic0 (98:be:94:04:8e:98)、nic4 (c8:d3:ff:b5:f3:52) が UP、nic1〜3 は DOWN (リンクなし)。`/sys/class/net` に旧名なし。vmbr0 は 192.168.1.2/24 (nic4)、vmbr1 は 172.16.0.1/24 (nic0)。`interfaces.new` は消え、`interfaces` に置き換わった |
| link_unreachable | 失敗なし。n100 から `ping -c3 172.16.0.1` 3/3 到達 (損失 0%、平均 0.21 ms)。hp-z440 から `172.16.0.2` も 3/3 (平均 0.24 ms) |
| no_quorum | 失敗なし。n100・hp-z440 とも `pvecm status` が Nodes 2、Quorate Yes |
| guest_not_running | 失敗なし。00:38:00 時点では VM 152、201、CT 202 が自動起動の途中で stopped、00:38:26 までに VM 110、152、201、CT 202 のすべてが running |
| guest_started_unexpectedly | 失敗なし。VM 108、9001 は stopped のまま。VM 105 も `qm status 105` が stopped |
| passthrough_missing | 失敗なし。`lsusb` に 3275:0080 と 058f:9540 があり、VM 110 は running。`qm config 110` の `usb0`、`usb1` は変わらない。VM 108 の `hostpci0` も変わらない |
| k3s_node_not_ready | 失敗なし。`kubectl --context default get nodes`: k3s-server、k3s-agent-minipc、k3s-agent-z440 の 3 ノードが Ready。Running/Completed 以外の Pod なし |
| `systemctl --failed` | `openipmi.service` のみ (再起動前と同じ) |
| `apt-daily-upgrade.timer` | disabled のまま |

#### PBS (CT 202)

- CT 202 は running。`pct exec 202 -- proxmox-backup-manager datastore list`: zfs-pool (`/mnt/zfs-pool-0`)。`proxmox-backup`、`proxmox-backup-proxy` が active
- ホストの `zpool list`: zfs-pool 3.62T、ALLOC 539G、HEALTH ONLINE

判定: タスク 5.4 の確認項目はすべて満たした。

### タスク 6.1: 事前チェッカーとバックアップ

#### 前夜のバックアップジョブ (2026-11-25 00:40 確認)

- `pvesh get /cluster/tasks` の vzdump タスク: hp-z440 は 2026-11-24 04:30:01 が OK (11-23、11-22、11-21 の 04:30 も OK)。n100 は 11-22 21:38:59 の手動のバックアップ (OK) の後、11-23 と 11-24 の 04:30 のタスクが無い。n100 が 2026-11-22 21:56 から 11-24 23:35 まで停止していたため (タスク 4.3 の 1 回目) で、ジョブの失敗ではない
- PBS 上の VM 152、VM 201、CT 202 に 2026-11-24 04:30 JST (= 11-23T19:30 UTC) のバックアップがある

#### `pve8to9 --full` (2026-11-25 00:40、PVE 8.4.21、出力は hp-z440 の `/root/ve9-upgrade-logs/pve8to9-hp-z440-6.1.txt`)

結果: TOTAL 48、PASSED 40、SKIPPED 3、WARNINGS 3、FAILURES 0。Ceph は「SKIP: no hyper-converged ceph setup detected!」。

| WARN | 扱い |
|---|---|
| `cluster consists of less than three quorum-providing nodes!` | 解消しない。QDevice の追加は本 spec の Non-Goals |
| `4 running guest(s) detected - consider migrating or stopping them.` | 解消しない。ゲストを他方のノードへ移さない (要件 3.5)。ゲストは `dist-upgrade` の間も稼働のまま |
| `The matching CPU microcode package 'intel-microcode' could not be found!` | 解消しない。パッケージの追加は design.md の手順に無く、本 spec の範囲外 |

SKIP 3 件: Ceph 無し、RBD 無し、LXCFS が未更新。NOTICE 1 件: `local-lvm` のゲストボリュームに autoactivation が有効なものがある (n100 と同じ。ローカルストレージのみで問題にならないとチェッカー自身が説明している。design.md に無い変更のため実行していない)。

#### 当日の手動バックアップ

- バックアップ対象: `pbs_backup_targets` のうち hp-z440 のゲストは VM 152 (k3s-agent-z440。`scsi2` は VM の設定が `backup=0` のため vzdump が除外する)、VM 201 (nas)、CT 202 (pbs。`pbs_backup_include_pbs_self: true`)。VM 110 は `pbs_backup_excluded_targets`、VM 105 は対象外 (触れない)、VM 108 / 9001 は `pbs_backup_targets` に無い
- 00:41:19 `vzdump 152 201 202 --storage pbs-zfs-pool --mode snapshot --compress zstd --prune-backups keep-all=1` を hp-z440 の tmux (`ve9`) の中で実行。ログ: `/root/ve9-upgrade-logs/vzdump-manual.log`。VM 152 は 378.00 GiB を 330 秒、VM 201 は 1.04 TiB を 285 秒、CT 202 は 23 秒。`Backup job finished successfully`、rc=0。`--backup` にディスクの個別除外は指定していない (`scsi2` の除外は手動の vzdump に反映していない)
- 00:52 `pvesm list pbs-zfs-pool` の当日分:

| VMID | volid |
|---|---|
| 152 | `pbs-zfs-pool:backup/vm/152/2026-11-24T15:41:20Z` |
| 201 | `pbs-zfs-pool:backup/vm/201/2026-11-24T15:46:52Z` |
| 202 | `pbs-zfs-pool:backup/ct/202/2026-11-24T15:51:39Z` |

(夜間分も残っている。ゲストは作業前の状態のまま: 110、152、201、CT 202 が running、105、108、9001 が stopped)

### タスク 6.2: 9 への更新と再起動の準備

#### dist-upgrade (2026-11-25 00:52〜01:01)

1. 00:52:18 hp-z440 の tmux セッション `ve9-upgrade` の中で `/root/ve9-upgrade-logs/dist-upgrade.sh` を実行 (ログ: `/root/ve9-upgrade-logs/dist-upgrade.log`)。n100 のスクリプトと同じ内容で、退避するのは `sources.list` と `pve-enterprise.list` (`ceph.list` はタスク 5.2 で削除済み)。参照先は `debian.sources` (trixie / trixie-updates / trixie-security、`main contrib non-free-firmware`) と `proxmox.sources` (`trixie` の `pve-no-subscription`)、`sources.list` は空。`DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef dist-upgrade`
2. 計画: 824 upgraded、200 newly installed、73 to remove。`DIST_UPGRADE_RC=0`、01:01:13 完了
3. 設定ファイルの扱い (`--force-confold`): 対話の問い合わせは `/etc/issue` の 1 件のみ (既存を残した)。`/etc/default/grub` は既存の内容のまま (`GRUB_CMDLINE_LINUX_DEFAULT="quiet nouveau.modeset=0 ahci.mobile_lpm_policy=0"`)、新しい版は `/etc/default/grub.ucf-dist` に置かれた。`/etc/lvm/lvm.conf` は既存を残し、新しい版が `/etc/lvm/lvm.conf.dpkg-dist` に置かれた
4. 01:01 `pve-manager` 9 が `/etc/apt/sources.list.d/pve-enterprise.sources` (有効な enterprise リポジトリ) を置いていたので、design.md の「他の `.sources` を削除する」に従い削除 (退避: `/root/ve9-upgrade-logs/apt-sources-before/pve-enterprise.sources.from-pve-manager-9`)。`apt-get update` は 3 つの参照先 (debian、security、proxmox) とも Hit で、`apt list --upgradable` は 0 件
5. 01:01 `DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold install proxmox-default-headers libdw1t64` (tmux セッション `ve9-headers`、ログ `/root/ve9-upgrade-logs/headers.log`) → rc=0。両パッケージは `dist-upgrade` の中で入っており (`proxmox-default-headers 2.1.0`、`proxmox-headers-7.0.14-30-pve`、`libdw1t64 0.192-4`)、この操作で新規に入ったものは無い。`apt-mark showmanual` に両パッケージが出る
6. ゲストは n100 へ移していない。tmux のセッションは終了し、ログは残した

#### dist-upgrade の副作用 (想定外。n100 と同じ)

- `chrony.service` が 00:58:47 から failed (`Fatal error : Could not send notification to $NOTIFY_SOCKET`)。`dist-upgrade` の途中の systemd の入れ替えが原因。これに伴い `host-health-chrony.service` が 01:00:28 に failed し、`OnFailure=` が起動した (通知が出た可能性がある)。再起動での解消を 6.3 で確かめる
- `openipmi.service` の failed は以前から
- dist-upgrade の途中、`openssh-server` の入れ替えの間に `systemctl: error while loading shared libraries: libcrypto.so.3` が 1 回出た (dpkg は rc=0 で完了)。更新後の `scp` は成功した (n100 のような失敗なし)

#### BootDeadman の配置 (2026-11-25 01:02)

- 戻り先のカーネル: `6.8.12-43-pve` (タスク 5.4 で起動と PostRebootCheck を確かめたもの)。`proxmox-kernel-6.8.12-43-pve-signed 6.8.12-43` は dist-upgrade の後も導入済み
- n100 と同じ内容のファイルを配置 (hp-z440 上。IaC には入れない): `/usr/local/sbin/upgrade-deadman` (確認の印があれば何もしない。稼働中が `6.8.12-43-pve` なら何もしない。それ以外は `proxmox-boot-tool kernel pin 6.8.12-43-pve` と `systemctl reboot`)、`/etc/systemd/system/upgrade-deadman.service` (oneshot)、`/etc/systemd/system/upgrade-deadman.timer` (`OnBootSec=15min`、`WantedBy=timers.target`)
- `systemctl enable --now upgrade-deadman.timer` → `is-enabled` enabled、`is-active` active。`systemd-analyze verify` 問題なし
- 有効化の直後 (01:02:49) に、起動から 15 分を過ぎているためタイマーが 1 回発火した。稼働中のカーネルが戻り先と同じなので何もせず終了 (`status=0/SUCCESS`)。`proxmox-boot-tool kernel list` に固定なし (`Manually selected kernels: None`)
- 撤去の手順 (タスク 6.3): `systemctl disable --now upgrade-deadman.timer` と、上記 3 ファイルの削除、`daemon-reload`

#### PreRebootCheck (2026-11-25 01:03、対象カーネル 7.0.14-30-pve)

| 項目 | 結果 |
|---|---|
| nic_link_missing | 失敗なし。物理 NIC 5 つ (nic0〜3 は tg3、nic4 は e1000e) の MAC すべてに `50-pve-nic{0..4}.link` がある |
| interfaces_unknown_name | 失敗なし。`/etc/network/interfaces` の名前は lo、nic0〜4、vmbr0 (`bridge-ports nic4`)、vmbr1 (`bridge-ports nic0`)。`interfaces.new` は無い (8.4 の再起動で適用済み) |
| stale_name_reference | 失敗なし。`/etc/network`、`/etc/pve`、`/etc/default/grub*`、`/etc/udev/rules.d`、`/etc/systemd/network`、`/etc/hosts`、`/etc/modprobe.d` に `eno1|ens5f|enp0s25|enp3s0|enxc436` なし。`/etc/pve/firewall/` は空、`host.fw` は無い。`post-up ethtool -K nic4 …` |
| initramfs_stale | 失敗なし。`initrd.img-7.0.14-30-pve` (01:01:05) が `.link` (00:29:12) より新しい。`lsinitramfs` の `nic` 一致はカーネルのモジュール名 (`sata_inic162x`、`hinic3`、`nic7018_wdt`) のみで `.link` は含まれない (8.4 で起動を確かめた 6.8.12-43 の initramfs も同じ) |
| grub_entry_missing | 失敗なし。`grub.cfg` に 7.0.14-30-pve の項目 (cmdline に `quiet nouveau.modeset=0 ahci.mobile_lpm_policy=0`)。`GRUB_DEFAULT=0` の先頭の項目が 7.0.14-30-pve。6.8.12-43-pve の項目も残っている |
| efi_removable_stale | 失敗なし。`EFI/BOOT/BOOTx64.efi` と `EFI/proxmox/shimx64.efi` が同日時 (01:00:32)・同 sha256 (9dee7152…) |
| boot_entry_missing | 失敗なし。`efibootmgr` の BootCurrent と BootOrder の先頭が 000C (proxmox) |
| パッケージ | `dpkg --audit` 空、`apt-get check` 正常、`apt list --upgradable` 0 件 |
| VM 105 の扱い | 決定済み (`onboot: 0`、停止のまま) |

失敗 0 件。

#### 6.2 の受入の実測 (2026-11-25 01:03)

- `pveversion`: `pve-manager/9.2.32/60a22e26e411402f` (`proxmox-ve: 9.2.0`、`proxmox-kernel-helper 9.2.1`、`proxmox-kernel-7.0 7.0.14-30`、導入済みの `proxmox-kernel-6.8.12-43-pve-signed` も残る)。稼働中のカーネルは再起動前なので 6.8.12-43-pve のまま
- `apt policy` の参照先: `deb.debian.org/debian` の `trixie`・`trixie-updates` (main / contrib / non-free-firmware)、`security.debian.org/debian-security` の `trixie-security`、`download.proxmox.com/debian/pve` の `trixie/pve-no-subscription` のみ。`/etc/apt/sources.list.d/` は `debian.sources` と `proxmox.sources` の 2 ファイル、`/etc/apt/sources.list` は 0 バイト
- BootDeadman: `upgrade-deadman.timer` が enabled / active
- `apt-daily-upgrade.timer`: disabled のまま
- ゲスト: VM 110、152、201、CT 202 が running、VM 105、108、9001 が stopped のまま。`pvecm status` は Nodes 2、Quorate Yes。再起動はしていない
- `systemctl --failed`: `chrony`、`host-health-chrony` (上記の副作用)、`openipmi` (以前から)

### タスク 6.3: 9 での再起動と受入

#### 再起動 (2026-11-27)

- 再起動前の確認 (03:24): GRUB の `GRUB_CMDLINE_LINUX_DEFAULT="quiet nouveau.modeset=0 ahci.mobile_lpm_policy=0"`。`proxmox-boot-tool kernel list` は固定 6.8.12-43-pve、次回だけ 7.0.14-30-pve。`upgrade-deadman.timer` enabled。n100 は 7.0.14-30-pve で `pvecm status` が Nodes 2、Quorate Yes。`zpool list`: zfs-pool ONLINE。再起動前の VM 110 は `usb0: host=3275:0080`、`usb1: host=058f:9540` のみ (hostpci と raw ディスクのパススルーは無い。ディスクは `local-lvm` の `virtio0`)
- 03:24:23 hp-z440 で `systemctl reboot` (作業者が現地に待機。ゲストは PVE の自動の停止・起動のみ)
- 03:27:34 起動 (`uptime -s`)、03:27:51 に SSH が復帰。SSH の不通は 約 3 分半 (15 分以内)

#### PostRebootCheck (2026-11-27 03:27〜03:29)

| 項目 | 結果 |
|---|---|
| ssh_unreachable | 失敗なし。作業 PC から 192.168.1.2 に SSH 可 |
| 稼働中のカーネル | `uname -r`: 7.0.14-30-pve、`pveversion`: pve-manager/9.2.32 (running kernel: 7.0.14-30-pve) |
| `/proc/cmdline` | `BOOT_IMAGE=/boot/vmlinuz-7.0.14-30-pve root=/dev/mapper/pve-root ro quiet nouveau.modeset=0 ahci.mobile_lpm_policy=0` |
| LPM | `link_power_management_policy`: host0〜5 (ata1〜6) が `max_performance`、host6〜7 が `keep_firmware_settings`。`dmesg` の ata1〜6 は `lpm-pol 1` (`max_performance` に対応。n100 の `lpm-pol 0` と値が違う。C610 は同じ `ahci.mobile_lpm_policy=0` でも `max_performance` になった)。省電力は掛かっていない |
| ata の障害 | `dmesg \| grep -c "ata.*exception"` は 0 件、`I/O error` は 0 件、`ata[0-9]+.*(error\|reset\|failed)` は 0 件 |
| NIC 名 | nic0 (98:be:94:04:8e:98)、nic4 (c8:d3:ff:b5:f3:52) が UP、nic1〜3 は DOWN (リンクなし。8.4 と同じ)。vmbr0 は 192.168.1.2/24 (nic4)、vmbr1 は 172.16.0.1/24 (nic0) |
| link_unreachable | 失敗なし。hp-z440 から `ping -c3 172.16.0.2` 3/3 (損失 0%、平均 0.247 ms)。n100 から `ping -c3 172.16.0.1` 3/3 (損失 0%、平均 0.191 ms) |
| no_quorum | 失敗なし。`pvecm status` が Nodes 2、Quorate Yes |
| guest_not_running | 失敗なし。03:27:56 は自動起動の途中で停止、03:28:30 までに VM 110、152、201、CT 202 がすべて running |
| guest_started_unexpectedly | 失敗なし。VM 108、9001 は stopped のまま。VM 105 は `qm status 105` が stopped (触れていない) |
| passthrough_missing | 失敗なし。`lsusb` に 3275:0080 と 058f:9540。`qm config 110` の `usb0`、`usb1`、`virtio0` は再起動前と同一。`qm monitor 110` の `info usb` に PX-S1UD Digital TV Tuner (usb0) と EMV Smartcard Reader (usb1)。VM 108 の `hostpci0` も変わらない。VM 201 の `scsi0`、`scsi1`、VM 152 の `scsi0〜3` も同一。VM 201 は `qm guest cmd 201 get-osinfo` に応答 |
| k3s_node_not_ready | 失敗なし。`kubectl --context default get nodes`: k3s-server、k3s-agent-minipc、k3s-agent-z440 の 3 ノードが Ready。03:28:30 時点では k3s-agent-z440 上の Pod が Unknown だったが、03:29:10 までに Running/Completed 以外の Pod が 0 件になった |
| Nextcloud | `https://cloud.fickledev.com/status.php`: 03:28:30 は 503 (Pod の回復前)、03:29:10 に HTTP 200 |
| `systemctl --failed` | `openipmi.service` のみ (以前からの失敗)。`chrony` は active (`Selected source` あり、stratum 3)、`host-health-chrony` は inactive (dead)。dist-upgrade 後の失敗は再起動で解消 |
| PBS (CT 202) | running。`proxmox-backup`、`proxmox-backup-proxy` が active。`zpool status -x`: all pools are healthy |

判定: タスク 6.3 の確認項目はすべて満たした。

#### 撤去 (2026-11-27 03:29)

- BootDeadman を撤去 (`upgrade-deadman.timer` を disable、`upgrade-deadman.service`・`.timer`・`/usr/local/sbin/upgrade-deadman` を削除し `daemon-reload`)。`list-unit-files` に deadman は 0 件
- `proxmox-boot-tool kernel unpin` で 6.8.12-43-pve の固定と `next-boot-pin` を外した (`Pinned kernel` なし)。`GRUB_DEFAULT=0`、`grub.cfg` の先頭の項目は `vmlinuz-7.0.14-30-pve`

### タスク 7.1: NVIDIA ドライバの適用 (hp-z440、2026-11-27)

- 03:31 `nvidia_driver.yml --check --diff`: ok=2、changed=1、failed=1。失敗は `nvidia-driver-pinning-620` の取得で、check モードでは cuda-keyring が入らず CUDA リポジトリが見えないための制約
- 03:31〜03:37 本適用 (1 回目): ok=5、changed=3、failed=1。cuda-keyring、`nvidia-driver-pinning-620`、`nvidia-kernel-open-dkms`、`nvidia-driver-cuda` は入ったが、`firmware-nvidia-gsp` の確認で止まった。`nvidia_driver_version: "620.70.06"` を期待したが、pinning は 620 系の範囲を固定するだけで、CUDA リポジトリの最新 620.70.10-1 が入ったため
- 設計の修正 (8eb4a09): 系の中の版は固定せず 620 系の範囲で固定する。ロールは `nvidia_driver_version` を廃止し、assert を `Installed: 620.` の判定に変更。実機は 620.70.10 のまま (ダウングレードなし)
- 03:42:31〜03:43:39 本適用 (2 回目): ok=16、changed=8、failed=0、skipped=2。続けて 3 回目: ok=14、changed=0、failed=0、skipped=2 (冪等)
- ansible-lint: Passed (0 failure、0 warning)。`scripts/test_nvidia_dkms_guard.py`: 7 passed

| 項目 | 結果 |
|---|---|
| `nvidia-smi -L` (03:43:44) | `GPU 0: NVIDIA GeForce GTX 1650` |
| `dkms status -k 7.0.14-30-pve` | `nvidia/620.70.10, 7.0.14-30-pve, x86_64: installed` |
| `apt-cache policy firmware-nvidia-gsp` | Installed 620.70.10-1 (CUDA リポジトリ) |
| nouveau | `lsmod` に無し。nvidia、nvidia_uvm は読み込み済み。再起動なし |
| `/etc/modules-load.d/nvidia.conf` | `nvidia`、`nvidia_uvm` |
| DkmsGuardHook | `/usr/local/sbin/nvidia-dkms-guard` (0755)、`nvidia-dkms-guard.service` (`OnFailure=notify-failure@%n.service`)、`apt-daily-upgrade.service.d/nvidia-dkms-guard.conf`、`apt.conf.d/99nvidia-dkms-guard` を配置。手動で start して Result=success、固定の印 (`/var/lib/nvidia-dkms-guard`) は作られない |
| Beszel hub の GPU 項目 | 未検証。リポジトリに GPU 項目の確認手順が無く、hub の画面と API は認証が要るため |

判定: タスク 7.1 は Beszel の GPU 項目が未検証のため、チェックしない。

#### Beszel の GPU 項目の確認 (2026-11-27 09:57〜10:01)

| 項目 | 結果 |
|---|---|
| agent | `beszel-agent 0.19.0`。systemd の `beszel-agent.service` で単体バイナリ (`/usr/local/bin/beszel-agent`) を起動。env は `LISTEN` と `KEY` のみ |
| v0.19.0 の GPU 検出 | `agent/gpu.go` の `NewGPUManager` は起動時に 1 回だけ `nvidia-smi` を PATH で探し、見つかれば `GPU_COLLECTOR` や `NVML` の設定なしで `nvidia-smi -l 4 --query-gpu=...` を常駐させる |
| 再起動前の agent | 起動は 03:27:47 で、`/usr/bin/nvidia-smi` の再配置 (ctime 03:32:32) とドライバ適用より前。agent の子プロセスに `nvidia-smi` が無く、GPU を収集していなかった |
| agent の再起動 | 09:57:11 に hp-z440 の `beszel-agent.service` だけを 1 回 restart (監視エージェントのみ。ホスト・ゲストの再起動なし) |
| 再起動後の agent | 子プロセス `nvidia-smi -l 4 --query-gpu=index,name,temperature.gpu,memory.used,memory.total,utilization.gpu,power.draw --format=csv,noheader,nounits` が 09:57:10 から常駐 |
| 同じ問い合わせの手動実行 (09:57:24) | `0, NVIDIA GeForce GTX 1650, 30.47, 0 MiB, 4096 MiB, 0 %, [N/A]` |
| hub からの接続 | 09:57:24〜10:00:51 の間、hp-z440 の 45876/tcp に確立済み・TIME_WAIT を含め接続が 1 本も無い (`ss -tan`) |
| hub 側の GPU 項目 | 未検証。作業端末の Tailscale が停止しており console-pi (100.116.132.42) に SSH できないため |

判定: agent は GPU を収集しているが、hub で hp-z440 の GPU 項目が更新されることは未確認のため、タスク 7.1 はチェックしない。

### タスク 7.2: DkmsGuardHook の実 apt での確認 (hp-z440、2026-11-27 10:02〜10:04)

開始時の状態: 稼働中 7.0.14-30-pve、固定なし (`proxmox-boot-pin`、`next-boot-pin` とも無し)、`/var/lib/nvidia-dkms-guard/` に印なし、`dkms status` は 6.8.12-13、-17、-43、7.0.14-30 のすべて installed。`apt-daily-upgrade.timer` は disabled のまま。

| 場合 | 操作 | 期待 | 結果 |
|---|---|---|---|
| (1) 正常 | 10:02:52 `apt-get install --reinstall -y less` | ユニットが成功し、固定が起きない | 10:02:54 に `nvidia-dkms-guard.service` が Result=success (ExecMainStatus=0)。固定、印とも作られず |
| (2) 未導入 | 10:03:02 `dkms remove nvidia/620.70.10 -k 6.8.12-43-pve` (稼働中ではないカーネル)、`proxmox-boot-tool kernel pin 6.8.12-43-pve` でそのカーネルを既定にした (`proxmox-boot-pin` = 6.8.12-43-pve)。10:03:08 に同じ apt | 固定、印の作成、通知 | 10:03:13 にユニットが ExecMainStatus=1 で失敗。`proxmox-boot-pin` が 7.0.14-30-pve に書き換わり、`/var/lib/nvidia-dkms-guard/pinned` が作られた。`notify-failure@nvidia-dkms-guard.service` が `webhook HTTP 204` |
| (3) 復旧 | 10:03:40 `dkms install nvidia/620.70.10 -k 6.8.12-43-pve` (rc=0、installed)。10:04:44 に同じ apt | 固定と印が外れる | 10:04:46 にユニットが Result=success。ユニット自身の `proxmox-boot-tool kernel unpin` で `proxmox-boot-pin`、`next-boot-pin` が除去され、印も消えた |

終了時の状態 (10:04:50): 開始時と `dkms status`、固定の有無、印、GRUB (`GRUB_DEFAULT=0`、自動選択は 6.8.12-43 と 7.0.14-30)、`apt-daily-upgrade.timer` (disabled) が一致 (差分なし)。稼働中 7.0.14-30-pve、nvidia モジュール読み込み済み、`nvidia-smi -L` は GTX 1650。再起動なし。

判定: 3 つの場合とも設計どおり。タスク 7.2 をチェックする。

## クラスタ (続き)

### タスク 8: `TerraformProvisioner` に `VM.GuestAgent.Audit` を足す (2026-11-27、n100 から実行)

- 前提: 両ノードが PVE 9.2.32、クラスタは quorate
- 変更前の `pveum role list` の該当行: `Datastore.Allocate, Datastore.AllocateSpace, Datastore.AllocateTemplate, Datastore.Audit, Sys.Audit, VM.Allocate, VM.Audit, VM.Backup, VM.Clone, VM.Config.CDROM, VM.Config.CPU, VM.Config.Cloudinit, VM.Config.Disk, VM.Config.HWType, VM.Config.Memory, VM.Config.Network, VM.Config.Options, VM.PowerMgmt` (18 件)
- 実行: `pveum role modify TerraformProvisioner --privs "<上記 18 件 + VM.GuestAgent.Audit>"` → rc=0
- 変更後の該当行: `Datastore.Allocate, Datastore.AllocateSpace, Datastore.AllocateTemplate, Datastore.Audit, Sys.Audit, VM.Allocate, VM.Audit, VM.Backup, VM.Clone, VM.Config.CDROM, VM.Config.CPU, VM.Config.Cloudinit, VM.Config.Disk, VM.Config.HWType, VM.Config.Memory, VM.Config.Network, VM.Config.Options, VM.GuestAgent.Audit, VM.PowerMgmt` (19 件。差分は `VM.GuestAgent.Audit` の追加のみ。集合の差分を機械的に比較して確認)
- `terraform plan` (`terraform/`、`infisical run` 経由、`-lock=false`): エラーなし、`No changes. Your infrastructure matches the configuration.`

## CT 202 (PBS)

### タスク 9.1: PBS の退避と更新の準備 (2026-11-27、hp-z440 の CT 202、途中で停止)

#### 更新前の確認 (14:26〜14:28 JST)

- 直近の vzdump タスク: 2026-11-25、11-26、11-27 の 04:30 に n100、hp-z440 とも OK
- 更新前の PBS: Debian 12 (bookworm)、`proxmox-backup-server 3.4.9-2` (running 3.4.9)、リポジトリは `proxmox-backup.list` (1 行形式、bookworm)
- 更新前のバックアップの件数: `pvesm list pbs-zfs-pool` で 15 件 (100: 1、113: 4、150: 2、151: 2、152: 2、201: 2、202: 2)。11-26 夜の最新は 150: 19:30:00Z、151: 19:32:13Z、152: 19:30:00Z、201: 19:34:06Z、202: 19:39:32Z
- 実行中の vzdump: hp-z440、n100 とも無し (`pgrep -x vzdump`)

#### 退避

- 14:27 `/etc/proxmox-backup` を tar にまとめ (CT 内で作成)、`pct pull` で hp-z440 の `/var/lib/vz/dump/pbs202-etc-proxmox-backup-pre-pbs4.tar.gz` (5267 bytes) へ移した。sha256 が CT 内の元と一致 (`e0002354…5660`)
- 14:27:04〜14:27:45 `vzdump 202 --storage local --mode snapshot --compress zstd` が成功。`/var/lib/vz/dump/vzdump-lxc-202-2026_11_27-14_27_04.tar.zst` (1.09 GB、書込 4.8 GiB で `mp0` は含まれない)

#### メンテナンスモードと `pbs3to4 --full` (14:28 JST)

- 14:28 `proxmox-backup-manager datastore update zfs-pool --maintenance-mode read-only`。`datastore show` で `maintenance-mode = read-only` を確認
- `pbs3to4 --full`: TOTAL 9、PASS 3、SKIP 1、WARN 4、FAIL 1

| 区分 | 内容 |
|---|---|
| FAIL | `could not match the 'proxmox-backup' package version, is it installed?`。メタパッケージ `proxmox-backup` が未導入 (`apt-cache policy` で Installed: (none)、`proxmox-backup-server` と `-docs` のみ導入)。導入すると `proxmox-default-kernel`、`proxmox-kernel-helper`、`grub-pc` などの kernel と bootloader (28 パッケージ新規、`apt-get -s` で確認) が入るため、コンテナには不適切と判断して導入していない |
| WARN | 更新可能パッケージあり (bookworm の通常更新)。`unexpected running and installed kernel '7.0.14-30-pve'` (コンテナはホストのカーネルで動く)。NTP 無し (ホストの時計を共有する CT。host_vars の chrony 無効化と同じ理由)。`grub-efi-amd64` 未導入 (コンテナで不要) |
| SKIP | dkms の状態が取れない |

判定: FAIL が 0 件にならないため、この時点では停止した。設計に例外 (9ff1a77) が加わったため、後述のとおり再開した。

#### 停止時点の状態 (14:30 JST、再開前)

- データストア `zfs-pool` は read-only のメンテナンスモードのまま (解除していない)。04:30 のバックアップジョブはこの状態では書き込めない
- CT 202 は稼働のまま、再起動なし。パッケージ・リポジトリの変更なし (`proxmox-backup-server 3.4.9-2`、bookworm)

#### 再開: 例外の確認 (14:32 JST)

- `pbs3to4 --full` を再実行: TOTAL 9、PASS 3、SKIP 1、WARN 4、FAIL 1。FAIL は `could not match the 'proxmox-backup' package version` の 1 件のみ
- `apt-cache policy proxmox-backup-server`: Installed 3.4.9-2、Candidate 3.4.9-2 (一致)。メタパッケージ `proxmox-backup` は導入していない

#### リポジトリの置き換えと dist-upgrade (14:33〜14:35 JST、CT 202 内の `/root/pbsup.sh`、ログ `/root/pbs4-upgrade-logs/dist-upgrade.log`)

1. 旧 `sources.list` と `sources.list.d` を `/root/pbs4-upgrade-logs/apt-sources-before/` へ退避
2. `proxmox-release-trixie.gpg` を `https://enterprise.proxmox.com/debian/proxmox-release-trixie.gpg` から `/usr/share/keyrings/` へ取得 (0644)
3. `/etc/apt/sources.list` を空にし、`proxmox-backup.list` を削除。`debian.sources` (`deb.debian.org/debian` の `trixie trixie-updates`、`security.debian.org/debian-security` の `trixie-security`、Components は `main contrib non-free-firmware`、Signed-By は `/usr/share/keyrings/debian-archive-keyring.gpg`) と `proxmox.sources` (`download.proxmox.com/debian/pbs` の `trixie`、`pbs-no-subscription`、Signed-By は `/usr/share/keyrings/proxmox-release-trixie.gpg`) を作成
4. `apt-get update` rc=0。`DEBIAN_FRONTEND=noninteractive apt-get -y -o Dpkg::Options::=--force-confold -o Dpkg::Options::=--force-confdef dist-upgrade`: 290 upgraded、65 newly installed、21 to remove。`DIST_UPGRADE_RC=0` (14:35 完了)
5. 設定ファイルの扱い: 対話の問い合わせは `/etc/issue` の 1 件 (既存を残した)。新しい版が `.dpkg-dist` として残ったのは `/etc/issue`、`/etc/crontab`、`/etc/cron.d/e2scrub_all`。`/etc/ca-certificates.conf.dpkg-old` もできた。`/etc/ssh/ssh_config`、`/etc/login.defs`、`/etc/systemd/*.conf` などは変更が無く新しい版が入った
6. `proxmox-backup-server` 4 の postinst が `/etc/apt/sources.list.d/pbs-enterprise.sources` (有効な enterprise リポジトリ、401) を置いたため、`apt-get update` が 401 で失敗した。`pbs` ロールが `pbs_enterprise_repo_files` で削除するのと同じファイルなので削除した。再実行の `apt-get update` は 3 つの参照先すべて Hit、`apt list --upgradable` は 0 件
7. 依存で新規に入ったもの: `chrony 4.8-4~bpo13+2` (inactive)、`zfsutils-linux`、`zfs-zed`、`libzfs7linux` 2.4.4-pve1

#### 更新後の状態 (14:36 JST、再起動前)

| 項目 | 結果 |
|---|---|
| `proxmox-backup-manager versions` | `proxmox-backup-server 4.2.14-1 running version: 4.2.14` (`proxmox-backup` は `unknown`、メタパッケージ未導入のため) |
| OS | Debian GNU/Linux 13 (trixie) |
| `proxmox-backup.service`、`proxmox-backup-proxy.service` | active。proxy は更新中に SIGHUP でリロードされたが、`ActiveEnterTimestamp` は更新前の 2026-11-26 18:28:21 UTC のまま (新しい版での再起動はしていない) |
| `systemctl --failed` | `logrotate.service` (00:00 に 226/NAMESPACE で失敗、更新前から)、`systemd-networkd.service` と `.socket` (11-26 18:28 の CT 起動時から失敗)、`zfs-mount.service`、`zfs-share.service`、`zfs-zed.service` (更新で zfs パッケージが入り、05:35 に失敗) |
| `/var/run/reboot-required` | 作成された (05:35) |
| `pbs3to4 --full` | FAIL 1 (`'proxmox-backup' package not found!`、例外の 1 件)、WARN 3 (稼働カーネル、NTP、grub-efi-amd64) |
| バックアップの件数 | `pvesm list pbs-zfs-pool` で 15 件 (更新前と一致) |
| メンテナンスモード | `zfs-pool` は read-only のまま。設計は CT の再起動後に解除するため、解除していない |

CT の再起動はしていない (承認待ち)。判定: 再起動と解除、更新後の確認が残るため、タスク 9.1 はチェックしない。

#### CT 202 の再起動と失敗 (14:37〜14:41 JST、停止)

- 14:37 再起動の前に確認: `proxmox-backup-manager task list` は空 (実行中のタスクなし)。hp-z440 と n100 に実行中の vzdump なし
- 14:37:46 hp-z440 で `pct reboot 202` (1 回)。`WARN: Systemd 257 detected. You may need to enable nesting.` が出て rc=0。CT は 14:37:56 に SSH へ戻った (`uptime -s` = 05:37:51 UTC)
- 結果: `proxmox-backup-proxy.service` が起動に失敗した (`Error: mkstemp "/run/proxmox-backup/proxy.pid.tmp_XXXXXX" failed: EACCES: Permission denied`、再起動の試行 5 回で `Start request repeated too quickly`)。`proxmox-backup.service` は active
- 原因の調査: `run-proxmox\x2dbackup.mount` (tmpfs を `/run/proxmox-backup` へマウントするユニット) が `mount: /run/proxmox-backup: tmpfs already mounted on /dev/shm` で失敗。`/run/proxmox-backup` は root:root 0755 で、backup ユーザーの proxy が書けない。ほかに `dev-mqueue.mount`、`run-lock.mount`、`tmp.mount` も失敗。CT の設定 (`pct config 202`) に `features` が無い (nesting なし)
- `systemctl --failed` (14:39): 上記 4 つの mount、`proxmox-backup-proxy.service`、`zfs-mount.service`、`zfs-share.service`、`zfs-zed.service` (zfs-* は再起動後も失敗のまま)
- `proxmox-backup-manager versions`: `proxmox-backup-server 4.2.14-1 running version: 4.2.14`
- `pvesm status` (両ノード): `pbs-zfs-pool` は inactive (`Can't connect to 192.168.1.202:8007 (Connection refused)`)。`pvesm list pbs-zfs-pool` は 0 件 (接続できないため。更新前の 15 件が消えたわけではない)
- メンテナンスモードは read-only のまま、解除していない。mask や削除は行っていない
- 判定: 設計の前提が崩れたため停止。タスク 9.1 はチェックしない。CT 202 の設定の変更 (`features: nesting=1` の追加は Terraform 管理の CT 設定の変更になる) などは設計に無く、未実施
