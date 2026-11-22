# Requirements Document

## Project Description (Input)
Proxmox VE クラスタ(n100, hp-z440)を 8.4 から最新メジャー 9.x へアップグレードし、CT 202 の PBS を 3 から 4 へ上げる。hp-z440 の GTX 1650 は今後も使うため NVIDIA ドライバを PVE 9 カーネルで動く形で維持する。hp-z440 の未使用 Ceph パッケージ・リポジトリは削除する。作業は物理コンソールなしで SSH+tmux で行う。

## Introduction

Proxmox VE 8 と Proxmox Backup Server 3 は、どちらもベースの Debian 12 とともに 2026-08 にサポートを終えている。両ノードは PVE 8.4 の最新版にあるが、8.4 系の更新の一部と再起動が未適用のまま残っている。

本 spec は、2 ノードクラスタ `cluster0` の両ノードを Proxmox VE 9 の最新版へ、CT 202 の PBS を 4 の最新版へ上げる。アップグレードの前後で、稼働中のゲスト、バックアップ、Terraform と Ansible による管理、hp-z440 のホストでの GTX 1650 の利用が引き続き成立することを受入の条件とする。

両ノードには物理コンソールも IPMI も用意せず、作業は SSH と tmux だけで行う。再起動のあとに管理経路が戻らない場合、遠隔からの復旧手段は無い。このため、再起動の前に管理経路が戻ることを確かめることを要件に含める。

## Boundary Context

- **In scope**: n100 と hp-z440 の Proxmox VE 8.4 から 9 への更新、CT 202 の Proxmox Backup Server 3 から 4 への更新、アップグレード事前チェッカー (`pve8to9`) が指摘する事項の解消、hp-z440 での NVIDIA ドライバの維持、hp-z440 からの未使用の Ceph パッケージとリポジトリの削除、アップグレード後の Terraform と Ansible による管理の継続
- **Out of scope**: ゲスト内の OS の更新 (CT 200 gitea の Debian 12 から 13 への更新を含む。CT 202 は PBS 4 の前提として含む)、ストレージやネットワークの構成の変更、クラスタへの QDevice の追加、VM 108 の修復、調査中に見つかったホスト上の別件 (mariadb、beszel-agent の重複、postfix の滞留)
- **Adjacent expectations**: VM 105 の起動設定の扱いは保留中であり、本 spec は VM 105 の設定を変更しない。VM 105 への書き込みは `nextcloud-k3s-migration` の関門の内側に限る。PBS のバックアップの対象と除外の正は `ansible/inventory/host_vars/pbs/main.yml` であり、本 spec はこれを変更しない

## Requirements

### Requirement 1: アップグレード前の準備
**Objective:** As a ホームラボ運用者, I want 各ノードを上げる前にアップグレードを阻む要因を取り除いておきたい, so that アップグレードが途中で止まる事態を避けられる

#### Acceptance Criteria
1. When あるノードのメジャーアップグレードを開始する時点で, the 当該ノード shall Proxmox VE 8.4 系の最新版の更新をすべて適用し、その後の再起動を済ませている。
2. When あるノードのメジャーアップグレードを開始する時点で, the 当該ノードの `pve8to9 --full` shall FAIL を 1 件も報告しない。
3. The アップグレード作業 shall `pve8to9 --full` が報告した WARN の各項目について、解消したか、解消しない理由を記録する。
4. The Proxmox VE クラスタ shall `VM.Monitor` 権限を含むカスタムロールを持たない。
5. When あるノードのメジャーアップグレードを開始する時点で, the PBS shall 当該ノード上のゲストのうち `pbs_backup_targets` に含まれるものについて、開始当日に取得したバックアップを保持している。
6. When あるノードのメジャーアップグレードを開始する時点で, the 当該ノードのルートファイルシステム shall 10 GB 以上の空きを持つ。

### Requirement 2: 物理コンソール無しでの管理経路の維持
**Objective:** As a ホームラボ運用者, I want 再起動のあとも SSH で各ノードに届く状態を保ちたい, so that 現地に出向かずに作業を完了できる

#### Acceptance Criteria
1. When メジャーアップグレード後の最初の再起動を行う前に, the 当該ノード shall 物理 NIC の名前をカーネルの命名規則に依存しない固定の名前に紐付けている。
2. When メジャーアップグレード後の最初の再起動を行う前に, the 当該ノードのネットワーク設定 shall 固定した NIC 名だけを参照し、実在しないインターフェースを参照しない。
3. When メジャーアップグレード後の最初の再起動を行う前に, the 当該ノードのブートローダ shall 新しいカーネルで起動できる構成になっている。
4. When 各ノードが再起動を終えたとき, the 当該ノード shall 管理用ブリッジ (`vmbr0`) 経由の SSH と、クラスタ間リンク (`vmbr1`) 経由の疎通の両方に応答する。
5. While アップグレードのコマンドを実行している間, the アップグレード作業 shall SSH の切断で中断されないセッションの中で実行する。
6. If あるノードが再起動のあとに SSH で応答しない場合, then the アップグレード作業 shall もう一方のノードの作業に進まない。

### Requirement 3: ノードごとの順次アップグレード
**Objective:** As a ホームラボ運用者, I want 1 ノードずつ上げたい, so that 一方のノードで問題が起きても、もう一方のノードのゲストが動き続ける

#### Acceptance Criteria
1. The アップグレード作業 shall 2 つのノードを同時に更新しない。一方のノードのアップグレードと再起動後の確認が完了してから、もう一方のノードに着手する。
2. When 両ノードのアップグレードが完了したとき, the 各ノード shall Proxmox VE 9 系の、作業時点で pve-no-subscription リポジトリにある最新版で稼働している。
3. When 両ノードのアップグレードが完了したとき, the 各ノードの APT の参照先 shall Debian 13 (trixie) と Proxmox VE 9 の pve-no-subscription リポジトリだけになり、Debian 12 (bookworm) のリポジトリを含まない。ただし hp-z440 は、要件 5 のために NVIDIA の CUDA リポジトリ (debian13/x86_64) を加える。
4. When 各ノードが再起動を終えたとき, the Proxmox VE クラスタ shall 両ノードがクラスタに参加し、quorum を持つ状態に戻る。
5. While 2 つのノードのメジャーバージョンが異なる間, the アップグレード作業 shall 新しいノードから古いノードへのゲストの移動を行わない。

### Requirement 4: ゲストの復帰
**Objective:** As a ホームラボ運用者, I want アップグレード前に動いていたゲストがアップグレード後も動いていてほしい, so that ゲスト上のサービスの停止をノードの作業時間内に収められる

#### Acceptance Criteria
1. When 各ノードの作業が完了したとき, the 当該ノード shall アップグレード開始前に稼働していたゲストをすべて稼働させている。VM 105 はこの条件の対象外とする。
2. When 各ノードの作業が完了したとき, the k3s クラスタ shall 当該ノード上の k3s ノードを Ready として報告する。
3. When 各ノードの作業が完了したとき, the 当該ノード上のパススルーを持つゲスト shall アップグレード前と同じデバイスを認識している。
4. The アップグレード作業 shall アップグレード開始前に停止していたゲストを起動しない。

### Requirement 5: hp-z440 での GTX 1650 の利用の継続
**Objective:** As a ホームラボ運用者, I want アップグレード後も hp-z440 のホストで GTX 1650 を使い続けたい, so that 今後の GPU の利用に備えられ、監視の GPU 項目も失わない

#### Acceptance Criteria
1. When hp-z440 のアップグレードが完了したとき, the hp-z440 shall 稼働中のカーネルで NVIDIA のカーネルモジュールを読み込み、`nvidia-smi` が GTX 1650 を認識する。
2. The hp-z440 shall NVIDIA ドライバをパッケージ管理の下で導入する。カーネルの更新のたびに手作業でドライバを導入し直す必要が無い。
3. If 導入済みのいずれかのカーネルに対して NVIDIA のカーネルモジュールのビルドが失敗する場合, then the hp-z440 shall そのカーネルを既定の起動対象にしない。
4. When hp-z440 のアップグレードが完了したとき, the beszel-agent shall GPU の監視項目を引き続き取得する。

### Requirement 6: hp-z440 からの未使用の Ceph の削除
**Objective:** As a ホームラボ運用者, I want 使っていない Ceph のパッケージとリポジトリを外したい, so that アップグレードの対象と事前チェッカーの誤検知を減らせる

#### Acceptance Criteria
1. When hp-z440 のアップグレードが完了したとき, the hp-z440 shall Ceph のリポジトリを APT の参照先に持たない。
2. When hp-z440 のアップグレードが完了したとき, the hp-z440 shall Proxmox VE のパッケージが依存するもの以外の Ceph パッケージを持たない。
3. When hp-z440 で `pve8to9 --full` を実行したとき, the 事前チェッカー shall Ceph に関する FAIL を報告しない。

### Requirement 7: PBS の 4 への更新
**Objective:** As a ホームラボ運用者, I want バックアップ基盤もサポート中の版に上げたい, so that サポート切れの基盤にバックアップを預け続けずに済む

#### Acceptance Criteria
1. When PBS の更新が完了したとき, the CT 202 shall Proxmox Backup Server 4 系の、作業時点で pbs-no-subscription リポジトリにある最新版で稼働している。
2. When PBS の更新が完了したとき, the PBS のデータストア shall 更新前に保持していたすべてのバックアップを保持し、それらを一覧できる。
3. When PBS の更新が完了したあとの最初のバックアップの実行時刻が来たとき, the 両ノードのバックアップジョブ shall 成功する。
4. While PBS が 3 系である間, the 両ノードのバックアップジョブ shall 成功し続ける。成功しない場合は PBS の更新を先に行う。

### Requirement 8: アップグレード後の IaC による管理の継続
**Objective:** As a IaC 保守担当, I want アップグレード後も Terraform と Ansible で両ノードとゲストを管理し続けたい, so that 宣言と実機の対応がアップグレードで崩れない

#### Acceptance Criteria
1. When 両ノードのアップグレードが完了したとき, the `terraform plan` shall エラー無く完了し、アップグレードに起因する差分を出さない。
2. When 両ノードのアップグレードが完了したとき, the `ansible-playbook playbooks/site.yml` shall 両ノードと CT 202 に対してエラー無く適用できる。
3. The `proxmox_unattended_upgrades` ロール shall Debian 13 のノードに対して、Debian 12 のときと同じ範囲の自動更新を構成する。
4. When 両ノードのアップグレードが完了したとき, the steering shall Proxmox VE と PBS の現行の版とベースの Debian について、実機と一致する記述を持つ。
