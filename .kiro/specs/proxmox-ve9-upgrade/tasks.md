# Implementation Plan

ホスト上の操作は、作業の開始から終了まで `manual-operations.md` に記録する。作業の間 (タスク 2.1 から 10.1 まで) は `site.yml` と `proxmox_unattended_upgrades.yml` を実行しない。タスク 3 からタスク 8 までの間は `terraform plan` / `apply` を実行しない。

- [x] 1. リポジトリ側の準備
- [x] 1.1 (P) hp-z440 の NVIDIA ドライバのロールとエントリポイントを作る
  - NVIDIA の CUDA リポジトリ (debian13/x86_64) を `cuda-keyring` で登録し、ブランチ固定のパッケージ、オープンのカーネルモジュール、CUDA の利用者側パッケージを入れる。X 関連のパッケージは入れない
  - nouveau のブラックリスト、モジュールの起動時の読み込みの宣言、initramfs の更新、適用の最後の nouveau の取り外しと nvidia の読み込みを含める
  - DkmsGuardHook を、oneshot のユニット (OnFailure で既存の失敗通知へつなぐ)、unattended-upgrades の実行後の契機、手動の apt の実行後の契機として配置する。判定はパッケージの構成の残りと、次の起動で選ばれるカーネルの NVIDIA のモジュールの導入状態の 2 つ。このロールが固定した場合だけ、自動で固定を外す
  - エントリポイントは hp-z440 だけを対象にし、`site.yml` には入れない
  - `ansible-lint` がこのロールとエントリポイントについてエラー無く通る
  - _Requirements: 3.3, 5.1, 5.2, 5.3_
  - _Boundary: NvidiaDriverRole_

- [x] 1.2 (P) `pbs` ロールの APT リポジトリの定義を deb822 形式にする
  - PBS のリポジトリを deb822 形式の 1 ファイルで宣言する。URI、suite (配布の codename)、component (`pbs-no-subscription`)、Signed-By (既存の鍵のパス) は設計の値のとおり
  - 旧来の 1 行形式のファイルが残っていれば消す。無効化する enterprise リポジトリに deb822 形式のファイルを加える
  - `ansible-lint` が `site.yml` についてエラー無く通る。bookworm の CT 202 に `--check --diff` で流すと、新しいファイルの作成と旧ファイルの削除だけが差分に出る (適用はしない)
  - _Requirements: 8.2_
  - _Boundary: PbsRoleDeb822_

- [x] 2. n100 の準備 (PVE 8.4 のまま)
- [x] 2.1 n100 の作業の開始を記録し、8.4 の最新とブート構成の修正を入れる
  - `apt-daily-upgrade.timer` を止める。稼働中・停止中のゲストとパススルーの一覧 (作業前の状態) と、ルートの空きが 10 GB 以上あることを記録する
  - 8.4 系の更新をすべて適用する。`systemd-boot` メタパッケージを外し、GRUB の removable のフォールバックの更新を有効にして GRUB を入れ直す
  - EFI のフォールバックの起動ファイルが `EFI/proxmox` 側と同じ日付に更新され、`apt list --upgradable` が空になる
  - _Requirements: 1.1, 1.6, 2.3_

- [x] 2.2 n100 の NIC 名を固定する
  - NIC 名の固定ツールを既定の引数で実行し、生成された `.new` をすべて元のファイルと突き合わせる。インターフェース名を含む行がすべて新しい名前になっていなければ `.new` の側を直す。`cluster.fw` に旧名が無いことを確かめる
  - initramfs を全カーネルについて更新する
  - 物理 NIC ごとに `.link` があり、`interfaces.new` が新しい名前だけを参照していることを記録する
  - _Requirements: 2.1, 2.2_

- [x] 2.3 n100 を 8.4 のまま再起動し、受入を確かめる
  - 再起動前の確認 (PreRebootCheck) で失敗が 0 件であることを確かめてから再起動する
  - 再起動後の確認 (PostRebootCheck) を行う。管理用ブリッジ経由の SSH、hp-z440 からのノード間リンクへの疎通、quorum、作業前に稼働していたゲストの稼働、停止していたゲストが停止のままであること、k3s のノードが Ready であること
  - 稼働中のカーネルが 8.4 系の最新で、NIC が `nicN` の名前で上がり、確認の結果がすべて記録されている
  - _Requirements: 1.1, 2.4, 2.6, 3.4, 4.1, 4.2, 4.4_

- [x] 3. `TerraformProvisioner` から `VM.Monitor` を外す
  - n100 の再起動後の確認が済んでから行う。この時点から Terraform を実行しない
  - 変更前と変更後の権限の一覧を記録する。他の権限と ACL は変えない
  - `pveum role list` で `TerraformProvisioner` が `VM.Monitor` を含まない
  - _Requirements: 1.2, 1.4_

- [x] 4. n100 のメジャー更新
- [x] 4.1 n100 の事前チェッカーを通し、バックアップを取る
  - 前夜の両ノードのバックアップジョブが成功していることを確かめる
  - `pve8to9 --full` の FAIL を 0 件にする。WARN の各項目について、解消したか、解消しない理由を記録する
  - n100 のゲストのうちバックアップ対象のものを、当日に PBS へ手動でバックアップする
  - `pve8to9 --full` の FAIL が 0 件で、当日のバックアップが PBS の一覧に出る
  - _Requirements: 1.2, 1.3, 1.5, 7.4_

- [x] 4.2 n100 を 9 へ更新し、再起動の準備をする
  - tmux のセッションの中で、APT の参照先を deb822 形式の Debian 13 と PVE 9 の pve-no-subscription だけに置き換え、`dist-upgrade` する。`/etc/default/grub` は既存のファイルを残す
  - `proxmox-default-headers` を入れる。ゲストを hp-z440 へ移さない
  - BootDeadman (15 分 (仮) で 8.4 の検証済みのカーネルに戻す) を置き、タイマーが有効であることを確かめる
  - 再起動前の確認で失敗が 0 件、`pveversion` が 9 系の最新を示し、`apt policy` の参照先が Debian 13 と pve-no-subscription だけになっている
  - _Requirements: 2.3, 2.5, 3.2, 3.3, 3.5_

- [x] 4.3 n100 を 9 で再起動し、受入を確かめる
  - `/etc/default/grub` の `GRUB_CMDLINE_LINUX_DEFAULT` に `ahci.mobile_lpm_policy=0` を加えて `update-grub` する。既定の起動対象を 6.8 に固定したまま、作業者が現地にいる時間に `--next-boot` で 7.0 を起動する
  - 再起動後に SSH で BootDeadman の確認の印を作り、再起動後の確認を行う (タスク 2.3 と同じ項目)
  - 確認を満たしたら BootDeadman を外す。SSH が戻らなければ hp-z440 の作業に進まない
  - 稼働中のカーネルが 7.0 系で、`dmesg` が `lpm-pol 0` を示し ata の exception が 0 件、確認の結果がすべて記録され、BootDeadman と 6.8 の固定が撤去されている
  - _Requirements: 2.4, 2.6, 3.2, 3.4, 4.1, 4.2, 4.4_

- [ ] 5. hp-z440 の準備 (PVE 8.4 のまま)
  - n100 のタスク 4.3 が完了してから着手する (1 ノードずつ)。タスク 5.4 の再起動は、VM 105 の扱いが決まるまで行わない (VM 105 は `onboot: 1` のため再起動で起動する)
  - _Requirements: 3.1_
- [x] 5.1 hp-z440 の作業の開始を記録し、8.4 の最新、ブート構成の修正、存在しないインターフェースの除去を入れる
  - タスク 2.1 と同じ記録と更新を行う。`GRUB_CMDLINE_LINUX_DEFAULT` に `ahci.mobile_lpm_policy=0` を加えて `update-grub` する。作業前の状態に、VM 110 の USB とパススルーのディスクの識別子を含める。VM 105 は記録の対象に含めない
  - `/etc/network/interfaces` から実在しない USB の NIC の定義を除く (NIC 名の固定より前に行う)
  - `apt list --upgradable` が空で、`/etc/network/interfaces` が実在するインターフェースだけを参照している
  - _Requirements: 1.1, 1.6, 2.2, 2.3_

- [x] 5.2 hp-z440 から Ceph のサーバー側と旧 NVIDIA ドライバを外す
  - Ceph のサーバー側の 9 パッケージと Ceph のリポジトリを外す。Proxmox VE が依存するクライアント側は残す
  - Debian non-free の NVIDIA ドライバ 535 を purge し、`/etc/modules` の nvidia の行を外す
  - `dpkg -l` に Ceph のサーバー側のパッケージと Debian の NVIDIA のパッケージが無く、`pve8to9 --full` が Ceph の FAIL を報告しない
  - _Requirements: 6.1, 6.2, 6.3_

- [x] 5.3 hp-z440 の NIC 名を固定する
  - タスク 2.2 と同じ手順で行う。`post-up ethtool` の行が新しい名前になっていることを確かめる
  - 物理 NIC ごとに `.link` があり、`interfaces.new` が新しい名前だけを参照していることを記録する
  - _Requirements: 2.1, 2.2_

- [ ] 5.4 hp-z440 を 8.4 のまま再起動し、受入を確かめる
  - VM 105 の扱いが決まっていることを確かめてから、再起動前の確認を行って再起動する
  - 再起動後の確認を行う。n100 からのノード間リンクへの疎通、VM 110 の USB とディスクのパススルーの維持を含める
  - 稼働中のカーネルが 8.4 系の最新で、NIC が `nicN` の名前で上がり、確認の結果がすべて記録されている
  - _Requirements: 1.1, 2.4, 2.6, 3.4, 4.1, 4.2, 4.3, 4.4_

- [ ] 6. hp-z440 のメジャー更新
- [ ] 6.1 hp-z440 の事前チェッカーを通し、バックアップを取る
  - 前夜の両ノードのバックアップジョブが成功していることを確かめる
  - `pve8to9 --full` の FAIL を 0 件にし、WARN を記録する。hp-z440 のゲストのうちバックアップ対象のものを当日に PBS へ手動でバックアップする
  - `pve8to9 --full` の FAIL が 0 件で、当日のバックアップが PBS の一覧に出る
  - _Requirements: 1.2, 1.3, 1.5, 6.3, 7.4_

- [ ] 6.2 hp-z440 を 9 へ更新し、再起動の準備をする
  - タスク 4.2 と同じ手順で行う。加えて、NVIDIA の DKMS ビルドに要る `libdw1t64` を入れる
  - 再起動前の確認で失敗が 0 件、`pveversion` が 9 系の最新を示し、`apt policy` の参照先が Debian 13 と pve-no-subscription だけになっている
  - _Requirements: 2.3, 2.5, 3.2, 3.3, 3.5_

- [ ] 6.3 hp-z440 を 9 で再起動し、受入を確かめる
  - タスク 4.3 と同じ手順で行う。パススルーの維持を含める
  - 稼働中のカーネルが 7.0 系で、確認の結果がすべて記録され、BootDeadman が撤去されている
  - _Requirements: 2.4, 2.6, 3.2, 3.4, 4.1, 4.2, 4.3, 4.4_

- [ ] 7. hp-z440 の GPU を使える状態にする
- [ ] 7.1 NVIDIA ドライバのロールを hp-z440 に適用し、GPU を確かめる
  - `--check --diff` の後に本適用する。`firmware-nvidia-gsp` が CUDA リポジトリの 620 系から入っていることを確かめる
  - `dkms status` で NVIDIA のモジュールが稼働中のカーネルに対して installed になり、`nvidia-smi -L` が GTX 1650 を表示し、console-pi の Beszel hub で hp-z440 の GPU 項目が更新される
  - _Depends: 1.1_
  - _Requirements: 3.3, 5.1, 5.2, 5.4_

- [ ] 7.2 カーネル更新時の保護を実際の apt の操作で確かめる
  - 正常な状態で apt を 1 回実行し、保護のユニットが成功して固定が起きないことを確かめる
  - 稼働中ではない導入済みのカーネルから NVIDIA のモジュールを外し、そのカーネルを既定にした状態で apt を実行すると、固定、印の作成、Discord への通知が起きることを確かめる
  - モジュールを戻して apt を実行すると、固定と印が外れることを確かめる
  - 3 つの場合の結果が記録され、最後に既定の起動対象が 7.0 系の最新に戻っている
  - _Requirements: 5.3_

- [ ] 8. `TerraformProvisioner` に `VM.GuestAgent.Audit` を足し、Terraform の整合を確かめる
  - 権限の変更前後の一覧を記録する
  - Infisical 経由で `terraform plan` を実行し、エラーが無く、差分が無い
  - _Requirements: 1.4, 8.1_

- [ ] 9. PBS を 4 へ更新する
- [ ] 9.1 PBS の退避を取り、CT 202 を更新する
  - `/etc/proxmox-backup` の tar と、データストアを除く CT 202 の vzdump を hp-z440 の `local` に取る。更新前のバックアップの件数を記録する
  - データストアを read-only のメンテナンスモードにし、`pbs3to4 --full` の FAIL を 0 件にする
  - APT の参照先を deb822 形式の Debian 13 と PBS の pbs-no-subscription (タスク 1.2 と同じ内容) に置き換えて `dist-upgrade` し、CT を再起動してメンテナンスモードを解除する
  - `proxmox-backup-manager versions` が 4 系の最新を示し、バックアップの件数が更新前と一致する
  - _Requirements: 7.1, 7.2_

- [ ] 9.2 更新後の最初のバックアップジョブを確かめる
  - 更新後の最初の夜間のジョブで、両ノードのジョブが成功していることを確かめる
  - 両ノードのジョブの成功が記録されている
  - _Requirements: 7.3_

- [ ] 10. IaC と記述の整合を確かめる
- [ ] 10.1 Ansible の適用と自動更新の範囲を確かめる
  - `site.yml` を `proxmox_nodes` と `pbs` に限って `--check --diff` で流し、次に本適用する。これで `apt-daily-upgrade.timer` が両ノードで再開する
  - 両ノードの unattended-upgrades の有効行が作業前と同じで、`unattended-upgrade --dry-run` が trixie の Debian-Security と Proxmox の Origin を対象にすることを確かめる
  - 本適用がエラー無く終わり、`apt-daily-upgrade.timer` が両ノードで active になっている
  - _Depends: 1.2_
  - _Requirements: 8.2, 8.3_

- [ ] 10.2 steering を実機に合わせる
  - Proxmox VE と PBS の版、ベースの Debian、LXC テンプレートの版、hp-z440 の NVIDIA ドライバの記述を実機に合わせ、Active Specifications に本 spec を加える
  - steering の該当する記述が、タスク 4.3、6.3、9.1 で記録した版と一致する
  - _Requirements: 8.4_
