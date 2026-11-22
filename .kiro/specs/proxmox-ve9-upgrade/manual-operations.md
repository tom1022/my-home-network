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
