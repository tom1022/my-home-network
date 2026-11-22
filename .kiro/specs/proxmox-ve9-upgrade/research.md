# Research & Design Decisions

## Summary
- **Feature**: `proxmox-ve9-upgrade`
- **Discovery Scope**: Complex Integration (稼働中の 2 ノードクラスタ、PBS、ホストの GPU ドライバ、IaC の権限にまたがる)
- **Key Findings**:
  - アップグレード前に入れる変更 (ブート構成、NIC 名の固定、不要パッケージの削除) は、すべて PVE 8.4 のまま適用でき、8.4 の再起動で個別に検証できる。メジャー更新の再起動で切り分ける変数を減らせる。
  - GTX 1650 のドライバは、NVIDIA の CUDA リポジトリ (debian13) の `nvidia-kernel-open-dkms` 620.70.06 が PVE のカーネル 7.0.14-30 と 6.17.13-21 の両方でビルドに成功した。Debian trixie の 550.163.01 は両方で失敗した。
  - `VM.Monitor` の除去は、PVE 8.4 では代わりの `VM.GuestAgent.Audit` が存在しないため、両ノードが 9 になるまで Terraform による guest agent の読み取りが失われる。

## Research Log

### 現行の構成
- **Context**: 両ノードのアップグレード対象と阻害要因を確定するため
- **Sources Consulted**: 両ノードでの読み取りコマンド (`pveversion -v`、`pve8to9 --full`、`efibootmgr -v`、`dpkg -l`、`apt-get -s`)
- **Findings**:
  - 両ノードとも PVE 8.4.21、Debian 12、カーネル 6.8.12-19、UEFI + GRUB + LVM ルート。`proxmox-boot-tool` の管理下にない (`/etc/kernel/proxmox-boot-uuids` が無い)
  - `pve8to9 --full` の FAIL は、両ノード共通が「カスタムロール `TerraformProvisioner` が `VM.Monitor` を含む」「`systemd-boot` メタパッケージが入っている」の 2 件、hp-z440 だけが Ceph の状態を取れない 3 件
  - `grub2/force_efi_extra_removable` は両ノードとも `false`。`/boot/efi/EFI/BOOT/BOOTX64.efi` は 2024 年のインストール時から更新されていない。n100 は BootOrder にこのフォールバックの項目を持つ
  - corosync は `ring0_addr` だけで、管理用ブリッジ側の 192.168.1.x を使う。`vmbr1` (172.16.0.0) はノード間の直結リンク
  - hp-z440 の `/etc/network/interfaces` に、実在しない `auto enxc436c0eafd1d` がある
- **Implications**: ブート構成の修正、NIC 名の固定、存在しないインターフェースの除去を、メジャー更新の前提作業にする

### hp-z440 の Ceph
- **Context**: 要件 6 の「Proxmox VE が依存するもの以外」を確定するため
- **Sources Consulted**: `apt-cache depends`、`apt-get -s remove`
- **Findings**:
  - 導入済みは ceph-squid リポジトリ由来の 19.2.3 の 23 パッケージ
  - `ceph-common`、`ceph-fuse`、`librados2`、`librbd1` 等のクライアント 14 件は、`pve-qemu-kvm`、`libpve-storage-perl`、`pve-manager` が依存する。外すと `proxmox-ve` が巻き込まれる
  - サーバー側の 9 件 (`ceph`、`ceph-base`、`ceph-mds`、`ceph-mgr`、`ceph-mgr-modules-core`、`ceph-mon`、`ceph-osd`、`ceph-volume`、`libsqlite3-mod-ceph`) は巻き込み無しで外せる。残るのは n100 と同じクライアント構成になる
  - PVE 9 の pve-no-subscription リポジトリが `ceph-common` 19.2.6 を持つので、`ceph.list` を外しても trixie への更新でクライアントは PVE リポジトリ版に置き換わる
  - `/etc/pve/ceph.conf` がクラスタ共有の位置に残っている。n100 は同じファイルが見えている状態で Ceph の FAIL を出していない
- **Implications**: 削除対象はサーバー側 9 件と `ceph.list`。`/etc/pve/ceph.conf` は要件の範囲外として残す

### NVIDIA ドライバ
- **Context**: 要件 5 のドライバの入手元と版を確定するため
- **Sources Consulted**: ローカルの docker コンテナ (debian:trixie + Proxmox のカーネルヘッダ) での DKMS ビルド、CUDA リポジトリの Packages、Debian trixie の Packages、NVIDIA open-gpu-kernel-modules の README と issue #1433、NVIDIA の 620 系のドキュメント
- **Findings**:
  - 現在は Debian 12 non-free の 535.261.03 (プロプライエタリのモジュール)。GPU を開いているのは `nvidia-persistenced` と beszel-agent の `nvidia-smi` のポーリングだけ
  - ビルドの結果 (ビルドだけで、実 GPU での動作は未確認):
    - CUDA リポジトリの `nvidia-kernel-open-dkms` 620.70.06: 7.0.14-30 と 6.17.13-21 の両方で成功
    - Debian trixie の 550.163.01: 7.0 は `'struct vm_area_struct' has no member named '__vm_flags'`、6.17 は `implicit declaration of function 'dma_buf_attachment_is_dynamic'` で失敗
    - 580 系は CUDA リポジトリ (debian13) に存在しない
  - ビルドに `libdw1t64` が要る (`gendwarfksyms` が読み込む)。ヘッダパッケージの依存に含まれない
  - 620 系はオープンカーネルモジュールだけになった。GTX 1650 (Turing、PCI ID 1F82) はその対象に含まれる
  - CUDA リポジトリのパッケージ: `nvidia-driver-cuda` が `nvidia-smi` と `nvidia-persistenced` を提供する。`nvidia-kernel-open-dkms` は `firmware-nvidia-gsp` に依存する。`nvidia-driver-pinning-620` がブランチを固定する APT の設定を提供する
  - 両ノードの unattended-upgrades の対象は Debian security と Proxmox の Origin だけ。CUDA リポジトリは自動更新の対象にならないが、Proxmox のカーネルは自動で入る
  - `proxmox-boot-tool kernel pin` は、`proxmox-boot-tool` の管理下にない GRUB 構成でも `/etc/default/grub.d/` のスニペットと `update-grub` で効く
- **Implications**: CUDA リポジトリの 620 系のオープンモジュールを採る。自動で入った新しいカーネルでビルドが失敗したときに既定の起動対象にしない仕組みが要る

### 権限 `VM.Monitor`
- **Context**: 要件 1.2 / 1.4 と Terraform の継続 (要件 8.1)
- **Sources Consulted**: `pveum role list`、PVE Roadmap の 9.0 Known Issues、qemu-server の `Agent.pm` (8.4 の実機と 9 の HEAD)、`pve8to9.pm`、bpg/proxmox v0.111.1 の docs
- **Findings**:
  - `TerraformProvisioner` は IaC の外にあり、`terraform@pve` に `/` で割り当てられている。トークンは privsep=0
  - PVE 9 では guest agent の情報取得 (`network-get-interfaces` 等) が `VM.GuestAgent.Audit` を要求する。PVE 8.4 では同じ操作が `VM.Monitor` を要求し、`VM.GuestAgent.*` は存在しない
  - Terraform の VM モジュールは `agent.wait_for_ip` を使う
  - チェッカーの文言は「adapted after the upgrade」だが、FAIL として報告する
- **Implications**: 要件 1.2 を満たすため最初のノードの更新前に `VM.Monitor` を外す。両ノードが 9 になってから `VM.GuestAgent.Audit` を足す。その間は Terraform を実行しない

### PBS 3 → 4
- **Context**: 要件 7
- **Sources Consulted**: PBS wiki の Upgrade from 3 to 4、PBS Roadmap、Proxmox フォーラムのスタッフの告知
- **Findings**:
  - 前提は 3.4.2-1 以上 (現在 3.4.9)、`/etc/proxmox-backup` の退避、ルートに 10 GB 以上の空き (現在 55G)
  - チェッカーは `pbs3to4 --full`
  - PVE 9 から PBS 3、PVE 8 から PBS 4 のどちらも公式に互換
  - LXC の中の PBS に特有の記述は無い。ホストの pve-container 5.3.6 は Debian 14 までのコンテナに対応している
- **Implications**: PBS は両ノードの後に更新する。PVE 9 と PBS 3 の組み合わせの期間を許容する

### NIC 名の固定ツール
- **Context**: 要件 2.1, 2.2
- **Sources Consulted**: 両ノードの実機、Proxmox VE Administration Guide
- **Findings**:
  - `pve-network-interface-pinning` は両ノードの PVE 8.4.21 に入っている (pve-manager 同梱)
  - `.link` を `/usr/local/lib/systemd/network` に生成し、`interfaces`、`host.fw`、`sdn/controllers.cfg`、`sdn/fabrics.cfg` に `.new` を作る。`cluster.fw` は書き換えない
  - PVE は起動時に `interfaces.new` で `interfaces` を置き換える
- **Implications**: `interfaces` への手作業の修正は固定の前に行う。`.new` はすべて突き合わせる

### repo の統合点
- **Context**: 要件 8
- **Sources Consulted**: `ansible/roles/{proxmox_unattended_upgrades,pbs,proxmox_backup,beszel_agent}`、`terraform/`
- **Findings**:
  - `proxmox_unattended_upgrades` は `${distro_codename}` を使う。trixie の Release ファイルの値と照合して変更不要
  - `pbs` ロールは `apt_repository` で 1 行形式の `proxmox-backup.list` を足す。trixie で走らせると bookworm の行が残り、公式手順の `proxmox.sources` と二重定義になる
  - `proxmox_backup` ロールのカスタムロールは `VM.Monitor` を含まない
  - beszel-agent は `nvidia-smi` があれば GPU を自動で検出する。repo に GPU の設定は無い
  - Terraform は bpg/proxmox 0.111.1 で、README は PVE 9.2 対応をうたう。未対応は HA の API だけで、repo は HA を使わない
- **Implications**: `pbs` ロールの deb822 化が必要。それ以外のロールと Terraform のコードは変更しない

## Architecture Pattern Evaluation

| Option | Description | Strengths | Risks / Limitations | Notes |
|--------|-------------|-----------|---------------------|-------|
| 準備と更新を分ける 2 段階 | 8.4 のまま準備の変更を入れて再起動で検証し、その後でメジャー更新 | 再起動 1 回あたりの変数が少ない。準備の失敗を 8.4 のうちに見つけられる | ノードあたりの再起動が 2 回になる | 採用 |
| 一括 | 準備とメジャー更新を続けて実行し、再起動 1 回 | 停止時間が短い | 再起動後に SSH が戻らないときに原因を切り分けられない。コンソールが無い | 不採用 |

## Design Decisions

### Decision: ノードの順序
- **Context**: 要件 3.1
- **Alternatives Considered**:
  1. n100 → hp-z440 → CT 202
  2. hp-z440 → n100 → CT 202
- **Selected Approach**: 1
- **Rationale**: n100 は GPU と PBS を持たず、変更点が少ない。手順の不備を小さいほうで先に見つけられる
- **Trade-offs**: n100 の作業中は k3s-server が止まり、k3s の API が使えない
- **Follow-up**: n100 の作業で見つけた手順の修正を hp-z440 の前に反映する

### Decision: NVIDIA ドライバの入手元
- **Context**: 要件 5.1, 5.2
- **Alternatives Considered**:
  1. Debian trixie の 550.163.01
  2. NVIDIA の .run インストーラ
  3. CUDA リポジトリ (debian13) の 620 系のオープンモジュール
- **Selected Approach**: 3。`nvidia-driver-pinning-620` でブランチを固定する
- **Rationale**: 1 は PVE 9 の全カーネルでビルドに失敗する。2 はパッケージ管理の外になる (要件 5.2 に反する)。3 は両カーネルでビルドが通り、APT で管理できる
- **Trade-offs**: Debian の外のリポジトリへの依存が増える
- **Follow-up**: hp-z440 の実機で `nvidia-smi` が GPU を認識することを確かめる

### Decision: ビルドに失敗したカーネルを既定にしない仕組み
- **Context**: 要件 5.3。Proxmox のカーネルは unattended-upgrades で自動に入る
- **Alternatives Considered**:
  1. 再起動の前に作業者が `dkms status` を確かめる運用
  2. カーネルの postinst フックで NVIDIA のモジュールの導入状態を確かめ、失敗していたら稼働中のカーネルに固定する
- **Selected Approach**: 2 を、カーネルのフックではなく apt の実行の後に行う形にする。`apt-daily-upgrade.service` の drop-in の `ExecStopPost=` と `DPkg::Post-Invoke` から、`OnFailure=notify-failure@%n.service` を持つ oneshot ユニットを起動する。ユニットは `dpkg --audit` と、次の起動で選ばれるカーネルの `dkms status` を判定する
- **Rationale**: カーネルの postinst は `run-parts --exit-on-error` で、dkms のフックがビルドに失敗すると後続のフックを止める。Proxmox のヘッダパッケージの postinst は `header_postinst.d` を実行しない (pve-kernel の `debian/proxmox-kernel.postinst.in` と `debian/proxmox-headers.postinst.in`)。カーネルのフックに置いた判定は失敗時に到達しない
- **Trade-offs**: 固定されている間は新しいカーネルで起動しない。このユニットが固定した場合に限り、後続のカーネルでビルドが通れば自動で外す
- **Follow-up**: 実際の apt の操作で、正常、固定、解除の 3 つの場合を確かめる

### Decision: `VM.Monitor` を外す時期
- **Context**: 要件 1.2, 1.4, 8.1
- **Alternatives Considered**:
  1. 最初のノードの更新前に外し、両ノードが 9 になってから `VM.GuestAgent.Audit` を足す
  2. 公式の文言どおり更新後に置き換える (要件 1.2 の変更が要る)
- **Selected Approach**: 1
- **Rationale**: 要件をそのまま満たす。PVE 8 のノードが未知の権限を含む `user.cfg` をどう扱うかという未確認の挙動を避けられる
- **Trade-offs**: 外してから足すまでの間は Terraform を実行しない
- **Follow-up**: 足したあとで `terraform plan` を実行する (要件 8.1)

## Risks & Mitigations
- 再起動後に SSH が戻らない (コンソールなし) — NIC 名の固定、ブート構成の修正、存在しないインターフェースの除去を 8.4 の再起動で先に検証する。戻らない場合は現地での対処になる
- 9 の新しいカーネルで管理経路が戻らない (Z440 は発売から 10 年以上で、公式 wiki が事前の試験を勧める対象) — 9 での最初の再起動の前に deadman を置き、確認が無ければ 8.4 で確かめた 6.8 のカーネルに固定して再起動する。`proxmox-boot-tool --next-boot` は起動完了後に解除されるので途中停止の逃げ道にならず、`grub-reboot` は `/boot` が LVM 上で使えない。起動途中の停止とパニックは受け入れる (ユーザー決定)
- ホスト OS の更新は戻せない (ルートは LVM でスナップショットが無い) — ゲストは PBS のバックアップから戻す。CT 202 は更新前に rootfs を vzdump で退避する
- VM 105 は `onboot: 1` のため、hp-z440 の再起動で起動する — VM 105 の扱いは保留中で、hp-z440 を再起動する前に決定が要る
- 620 系のドライバが実機の GPU で動かない — ビルドはローカルで確かめた。動かない場合は GPU が使えない状態になるだけで、ホストの起動と管理経路には影響しない
- PBS が hp-z440 の上にある — hp-z440 の作業中はバックアップが取れない。作業の直前にバックアップを取る

## References
- [Upgrade from 8 to 9](https://pve.proxmox.com/wiki/Upgrade_from_8_to_9) — 手順、systemd-boot、UEFI + LVM の GRUB
- [Roadmap](https://pve.proxmox.com/wiki/Roadmap) — 9.x のリリース内容、`VM.Monitor` の廃止
- [FAQ](https://pve.proxmox.com/wiki/FAQ) — PVE 8 と PBS 3 の EOL
- [Proxmox VE Administration Guide](https://pve.proxmox.com/pve-docs/pve-admin-guide.html) — `pve-network-interface-pinning`、カーネルの固定
- [PBS Upgrade from 3 to 4](https://pbs.proxmox.com/wiki/Upgrade_from_3_to_4) — PBS の手順
- [open-gpu-kernel-modules](https://github.com/NVIDIA/open-gpu-kernel-modules) — 対応 GPU、issue #1433
- [Beszel GPU](https://beszel.dev/guide/gpu) — GPU の自動検出
- [bpg/proxmox CHANGELOG](https://github.com/bpg/terraform-provider-proxmox/blob/main/CHANGELOG.md) — PVE 9 対応
