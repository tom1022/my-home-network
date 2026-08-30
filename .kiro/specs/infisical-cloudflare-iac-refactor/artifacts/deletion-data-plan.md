# 削除対象アプリケーションのデータ保全計画

タスク 1.4（Requirements 8.5, 12.7, 13.3）の一環として、削除予定のアプリケーションごとに
永続データの残存状況をクラスタ上で実査し、退避の要否を判断した記録。本ドキュメントは判断と
計画のみを扱い、実際のデータ退避作業（DB dump、オブジェクトストレージのコピー等）は行わない。

調査日: 2026-08-29

## 証明書 Secret の退避（実施済み）

- 対象: `cert-manager` namespace の Secret `tls-fickledev-com`（`*.fickledev.com` ワイルドカード証明書、
  ClusterIssuer `letsencrypt-prod` が発行、reflector により全 namespace へ複製されている）
- 退避先: `.kiro/specs/infisical-cloudflare-iac-refactor/artifacts/cert-backup/`
  - `tls-fickledev-com.cert-manager.yaml`（Secret 本体）
  - `wildcard-fickledev-com.certificate.yaml`（cert-manager の `Certificate` リソース、再発行条件の記録用）
- `.gitignore` に `.kiro/specs/infisical-cloudflare-iac-refactor/artifacts/cert-backup/` を追記し、
  `git status` で追跡対象に含まれないことを確認済み。
- 復元手順: `kubectl apply -f tls-fickledev-com.cert-manager.yaml` で Secret をそのまま再投入する。
  cert-manager 側で新規の証明書発行は発生しない（既存の証明書データをそのまま複製しているだけのため）。
  Let's Encrypt の重複証明書発行数上限（同一ドメインセットで週5回）には抵触しない。
- 他 namespace の `tls-fickledev-com` という同名 Secret は reflector
  （`reflector.v1.k8s.emberstack.com`）による複製先であり、いずれも `cert-manager/tls-fickledev-com` を
  正としているため個別の退避は不要。
- `mailu` namespace の `mailu-certificates` は `mailu.fickledev.com` 用の別証明書（非ワイルドカード）であり、
  本タスクの対象（ワイルドカード証明書）にも削除対象アプリにも該当しないため対象外とした。

## 削除対象アプリケーションのデータ保全要否

### aramakisai 系

#### authentik-aramakisai
- 実態: 専用の CNPG `Cluster` `authentik-aramakisai-cluster`（namespace `postgres`）が存在し、
  専用 PVC `authentik-aramakisai-cluster-1`（10Gi, Bound）にユーザー/グループ/SSO 設定を保持している。
  `ScheduledBackup authentik-aramakisai-backup` が定義されているが、実際の `Backup` は
  `cannot proceed with the backup as the cluster has no backup section` 等のエラーで失敗し続けており、
  S3 側に `cnpg-backups` バケット自体が存在しない（Garage のバケット一覧は `default-bucket` と
  `outline` のみ）ため、自動バックアップは機能していない。
  namespace 内の `authentik-postgres` Deployment はボリュームを持たない別プロセスで、実データは
  CNPG 側のみが保持する。
- 判断: **退避不要**。authentik-aramakisai は aramakisai 系スタック専用の ID プロバイダであり、
  これを利用する側（outline, planka, cloudflared-aramakisai）も同時に削除対象であるため、
  削除後に参照されるデータは存在しない。CNPG `Cluster` と `ScheduledBackup`、および共有
  `postgres-cluster` の bootstrap 定義からの `authentik_aramakisai` DB 参照除去は、実装タスク側
  （Requirement 8.3 相当）で対応する。

#### cloudflared-aramakisai
- 実態: トンネル接続を行うだけのステートレスな Deployment。PVC・DB 参照なし。
- 判断: **退避不要**。永続データを持たない。

#### outline
- 実態: DB は専用クラスタを持たず、共有 CNPG `Cluster` `postgres-cluster`（namespace `postgres`）内の
  `outline` データベースを使用（実文書データ）。加えて Garage（`garage.garage.svc.cluster.local:3900`）の
  バケット `outline` を添付ファイル等のオブジェクトストレージとして使用している
  （Secret `outline-secrets` の `AWS_S3_*` から確認）。
  `postgres-cluster` の `ScheduledBackup postgres-cluster-backup` も同様に S3 バケット
  `cnpg-backups` の不在により実効性のあるバックアップが取れていない。Garage 側には
  `apps/garage/values.yaml`（gitops-apps）に rclone による定期バックアップ（4時間毎、CronJob）の
  定義があるが、クラスタ上には該当 CronJob も Secret（`garage-backup-secrets`）も存在せず、
  **実際には稼働していない**。
- 判断: **退避を推奨（実データが存在し、現状バックアップの安全網がないため）**。
  - 退避先案: DB は `pg_dump` で論理バックアップを取得しクラスタ外（作業マシンまたは別ストレージ）へ
    保存、オブジェクトストレージは `mc mirror` / `rclone` で `outline` バケットをクラスタ外へコピー。
  - 復元手順案: DB は `pg_restore`（または `psql < dump.sql`）で新規 DB に投入、バケットは
    `mc mirror` で復元先バケットへ書き戻し、`outline-secrets` の接続情報を復元先に合わせて再設定する。
  - 実際の取得作業は本タスクの範囲外（設計の Non-Goals に明記の通り、要否判断のみを本タスクで行う）。
    削除実行前に運用者が要否を最終判断し、必要であれば上記手順で退避すること。

#### planka
- 実態: DB は共有 `postgres-cluster` 内の `planka` データベースのみ（ボード/タスクデータ）。
  PVC・オブジェクトストレージ設定なし（添付ファイルの永続化は行っていない）。
- 判断: **退避を推奨（DB 内容に限り）**。outline 同様、`postgres-cluster` の自動バックアップが
  機能していないため、実データが必要であれば削除前に `pg_dump` で `planka` データベースのみを
  論理バックアップしておく。ファイル添付等の永続化はそもそも行われていないため対象外。

### その他（稼働終了アプリケーション）

#### minio
- 実態: Deployment `minio-helm` は127日以上 `Pending`。参照する PVC `minio-pvc` は
  namespace `minio` に**存在しない**（`kubectl get pvc -n minio` は空）。
  クラスタ内には `minio-pv` という静的 PV（20Gi, hostPath `/var/lib/minio`, ノード `k3s-agent-z440`,
  reclaimPolicy `Retain`）が `Released` 状態で残っているが、その `claimRef` は
  `garage/garage-pvc` であり、MinIO 自身が使ったことはなく、Garage の初期移行時に一時的に
  束縛されていた名残と判断される。
- 判断: **クラスタ内に退避すべき実データなし**（PVC 未束縛のため MinIO 自体は稼働実績が事実上ない）。
  ただし `k3s-agent-z440` の `/var/lib/minio` ディレクトリ自体は本タスクの可視範囲（kubectl 経由）
  では中身を確認できないため、完全削除前にノードへ直接ログインしてディレクトリ内容を目視確認する
  ことを推奨事項として記録するに留める（実施は範囲外）。

#### stalwart
- 実態: Deployment `stalwart`（namespace `default`）は155日以上 `Pending`。マウントを試みる PVC
  `stalwart` は `kubectl get pvc -A` に存在せず、永続化されたメールデータはクラスタ内に存在しない。
- 判断: **退避不要**。長期間停止しており、参照先データも存在しない。

#### vikunja
- 実態: namespace `vikunja` に Pod / Deployment / PVC / Service を含めリソースが一切存在しない
  （`kubectl get all -n vikunja` が空）。gitops-apps にもマニフェストが存在しない、純粋な孤児 namespace。
- 判断: **退避不要**。実体が既に存在しない。

#### tailscale
- 実態: PVC `tailscale-state`（1Gi, Bound）は存在するが、Pod は Secret `tailscale-auth` の不在により
  `CreateContainerConfigError` で起動できていない（長期間停止）。PVC の中身は tailscale ノードの
  認証状態のみで、ユーザーデータではない。
- 判断: **退避不要**。このクラスタでの tailscale 運用自体を終了する方針のため、認証状態を復元する
  意味がない。将来別途 tailscale を導入する場合は新規に認証（`tailscale up`）すればよい。

## まとめ

| 対象 | 実データの有無 | 判断 |
|---|---|---|
| ワイルドカード証明書 Secret | あり | 退避実施済み（本タスクで実施） |
| authentik-aramakisai | あり（DB） | 退避不要（連鎖削除のため参照者なし） |
| cloudflared-aramakisai | なし | 退避不要 |
| outline | あり（DB + Garage バケット） | 退避推奨（実施は運用者判断・範囲外） |
| planka | あり（DB のみ） | 退避推奨（実施は運用者判断・範囲外） |
| minio | 実質なし | 退避不要（ノード上の残骸は目視確認を推奨） |
| stalwart | なし | 退避不要 |
| vikunja | なし（namespace 空） | 退避不要 |
| tailscale | あり（認証状態のみ、ユーザーデータでない） | 退避不要 |

補足: 共有 CNPG クラスタ `postgres-cluster` および `authentik-aramakisai-cluster` の
`ScheduledBackup` は、Garage 側に `cnpg-backups` バケットが存在しないため実際には失敗し続けており、
本スペックの対象外ではあるが恒常的なバックアップ不備として運用者への申し送り事項とする。
