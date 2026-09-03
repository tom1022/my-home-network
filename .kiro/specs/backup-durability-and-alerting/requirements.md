# Requirements Document

## Project Description (Input)

ホームラボ基盤の耐久性と障害検知を確立する。`iac-hygiene-remediation` と `mail-platform` の完走後に残った、「運用が回るか」の観点での穴を埋める。

### 背景

2 つの spec はどちらも受入基準を満たして全タスク完了したが、その後の調査で、退避が守られていない箇所と、壊れたことに気づけない箇所が残っていることが判明した。実例として、夜間バックアップが PBS の ACL 権限不足により毎晩失敗していたにもかかわらず、通知経路も死んでいたため 2 日間気づかれなかった。この 2 件は既に是正済みだが、同じ性質の穴が複数残っている。

### 対象とする課題

1. **退避の完全性が検証されない。** 取得元が空でも tar / gzip は成功し `gzip -t` も通るため、空アーカイブが正常な世代として記録される。14 世代連続すれば良い世代が全て押し出される。systemd の `OnFailure` はユニットが failed のときしか発火しないためこれを検知しない。

2. **`gitops-apps` の実体に退避が存在しない。** Gitea が PBS の対象外である理由は `github-offsite-backup` と記録されているが、GitHub に実体が無い。Git 実体は NAS 経由で hp-z440 の `sdc` 上にあり、PBS のデータストアと同一の物理ディスクである。この 1 枚を失うと NAS データ・Garage の実データ・Gitea のリポジトリ実体・それら全ての PBS バックアップが同時に消える。

3. **PBS に prune / verify / garbage collection のジョブが 1 つも存在しない。** GC は一度も実行されていない。単一 vdev の HDD でビットロットが起きても検出されない。ZFS の scrub も 2026-06-14 以降の実行痕跡が無く、走らなかったことを検知する手段も無い。

4. **障害の通知経路が一本化されていない。** PVE の通知ターゲットが postfix 直配送のままで、家庭回線の OP25B により永久に届かない。n100 に 12 通、hp-z440 に 132 通が滞留している。ArgoCD の notifications は Helm チャート既定値のままで送信先が存在しない。Garage の容量チェック CronJob は閾値超過を標準出力に出すだけで受け取る先が無い。メール基盤の退避失敗については Discord webhook への `OnFailure` 通知を既に確立したので、これを他へ広げる形になる。

5. **Kanidm の online backup が DB と同一ボリュームに出力されている。** Kanidm は person とグループ所属という Git にも Terraform state にも無いデータを持ち、DB だけが唯一の正である。PVC の削除防御は追加済みだが、ボリューム自体を失えばバックアップごと消える。定期スケジュール由来の世代は現在 1 件しか存在しない。

6. **pre-commit が両リポジトリで一度もインストールされていない。** gitleaks も manifest 検証も効いていない。`gitops-apps` にはサーバ側の検証ゲートも `.gitleaks.toml` も存在しない。

7. **退役したゲストの最終バックアップの扱いが決まっていない。** CT 100 (ollama) と CT 113 (mariadb-legacy) の最終バックアップが PBS に残っているが、保持するか削除するかの判断が記録されていない。これらは残骸ではなく、退役前に意図して取られた唯一の残存コピーである。

8. **steering の記述が実態と食い違っている。** `product.md` と `tech.md` がバックアップ対象を 7 件と書いているが実際は 5 件であり、既に destroy されたゲストを「復元可能なバックアップを保持」と記述している。`product.md` は Kanidm 導入も反映しておらず、今も「単一の認証基盤は存在しない」「forward auth で連携しているサービスは無い」と書いている。

### 除外する範囲

以下は別 spec とする。

- メール基盤固有の課題 — DNSBL の修復、迷惑メールの振り分けと学習、postmaster アカウント、shared namespace
- 認証の統合の残り — Crafty、ArgoCD のローカル admin、LDAPS の A レコード
- Nextcloud の VM 105 からの移行

### 前提

本 spec の着手前に、既に実装済みだが要件として宣言されていない変更が複数存在する。

- k3s Dovecot の `passdb static` の閉塞
- ClamAV の k3s への移設
- PBS のデータストア ACL
- 退避失敗の Discord 通知
- 認証済み送信のレート制限

`/kiro:validate-gap` でこれらを洗い出し、要件へ取り込むことで正規化する。

## Requirements
<!-- Will be generated in /kiro-spec-requirements phase -->
