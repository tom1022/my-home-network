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
