# 削除対象アプリケーションの反映確認とデータ削除要否記録

タスク 5.4（Requirements 8.4, 8.5）の記録。5.1/5.2（コミット `9e48c43`）で削除した
aramakisai 系4アプリと稼働終了系4アプリについて、Argo CD 同期後のクラスタ状態を実査した結果と、
1.4 の判断（`deletion-data-plan.md`）に基づく手動削除要否の一覧。

確認日: 2026-08-30

## Argo CD 同期状況

`kubectl get applications -n argocd` の結果、削除対象8アプリ（authentik-aramakisai,
cloudflared-aramakisai, outline, planka, minio, stalwart, vikunja, tailscale）に対応する
Application は存在しない。孤児 Application `common-secrets`（5.3 で削除済み）も存在しない。
残る全 Application は Synced（`postgres` のみ OutOfSync、`garage`/`kubernetes-dashboard` は
Degraded だが、これらは本タスクの削除対象と無関係な既知事項であり対象外）。

## クラスタ実査結果

### aramakisai 系4アプリ（authentik-aramakisai, cloudflared-aramakisai, outline, planka）

いずれも namespace.yaml が Application の管理対象リソースに含まれていたため、Application 削除に
伴う prune で namespace ごと消滅済み。実査（`kubectl get ns`, `kubectl get cluster.postgresql.cnpg.io -n postgres`,
`kubectl get deploy,sts,svc,cronjob -A | grep -iE aramakisai\|outline\|planka`）でリソース残存なしを確認。
CNPG `Cluster` `authentik-aramakisai-cluster` も消滅済み（PVC含む）。

### 稼働終了系4アプリ（minio, stalwart, vikunja, tailscale）

1.4 の実査時点で判明していた通り、これらは gitops-apps 上に対応するマニフェスト（または
ApplicationSet の exclude 設定）がなく、Application が存在しないため Argo CD の prune 対象外
（孤児状態）。5.2 のリポジトリ削除だけではクラスタ上のリソースは消えないことを確認したため、
本タスクで以下を直接実行し、削除を完了させた。

- `kubectl delete deployment stalwart -n default` / `kubectl delete service stalwart -n default`
  （stalwart の実体は `stalwart` namespace ではなく `default` namespace 上の Deployment/Service
  として存在していた。1.4 の実査記録と一致。PVC 参照なし、退避不要と判断済みのため削除）
- `kubectl delete namespace minio stalwart tailscale vikunja`
  （4つとも 1.4 で「退避不要」と判断済み。namespace 内の Secret/ConfigMap は reflector 複製の
  証明書や kube-root-ca.crt のみで実データではないことを確認済み）

削除後、`kubectl get ns` に上記4 namespace が存在しないこと、`kubectl get all -n default` に
stalwart 関連リソースが存在しないことを確認した。

## 手動削除が必要な残存データ（未実施・記録のみ）

以下は 1.4 の判断で「退避不要」に至らなかった、または kubectl 操作の範囲外のためクラスタ上に
意図的に残置したデータ。実データの削除は行っていない。

| # | 対象 | 内容 | 現状 | 必要な手動作業 |
|---|---|---|---|---|
| 1 | `minio-pv`（PersistentVolume） | hostPath `/var/lib/minio`、ノード `k3s-agent-z440`、20Gi、reclaimPolicy `Retain`、Status `Released` | クラスタに残存（本タスクでは未削除） | ノードへ直接ログインし `/var/lib/minio` の中身を目視確認した上で、不要と判断できれば `kubectl delete pv minio-pv` 及びノード上のディレクトリ削除（`rm -rf /var/lib/minio`）を実施する（1.4 の推奨事項どおり、kubectl 経由の実査では中身を確認できないため未実施） |
| 2 | `postgres-cluster`（namespace `postgres`）内の `outline` データベース | outline の文書データ（実データあり） | クラスタに残存（DB は削除していない） | 1.4 で「退避推奨」と判断済み。運用者が `pg_dump` 等で論理バックアップを取得した上で `DROP DATABASE outline;` を実施するか、バックアップ不要と最終判断した場合のみ削除する |
| 3 | `postgres-cluster`（namespace `postgres`）内の `planka` データベース | planka のボード/タスクデータ（実データあり） | クラスタに残存（DB は削除していない） | 同上。`pg_dump` でのバックアップ後、または不要と最終判断した場合に `DROP DATABASE planka;` を実施する |
| 4 | Garage オブジェクトストレージのバケット `outline` | outline の添付ファイル等（実データあり、`kubectl exec -n garage deploy/garage -- /garage bucket list` で存在確認済み） | クラスタに残存（未削除） | 1.4 で「退避推奨」と判断済み。運用者が `mc mirror` 等でクラスタ外へコピーした上で、Garage 管理コマンドでバケットを削除するか、不要と最終判断した場合に削除する |

上記 #2〜#4 は 1.4 で「退避不要」ではなく「退避推奨（実施は運用者判断・範囲外）」と判断された
実データであるため、本タスクでは削除を行っていない。#1 は 1.4 で「退避不要」と判断されているが、
ノード上のファイルシステム内容を kubectl 経由で確認できないため、目視確認を伴う手動削除として
記録するに留めた。

## まとめ

- 削除対象8アプリ（aramakisai 系4 + 稼働終了系4）のリソースはクラスタ上に存在しない
  （aramakisai 系は Argo CD の prune で、稼働終了系4つは本タスクでの直接 `kubectl delete` で解消）
- 手動削除が必要な残存データは上表の4件（PV 1件、DB 2件、オブジェクトストレージバケット 1件）
