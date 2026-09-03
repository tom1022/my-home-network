# Kubernetes Dashboard (GitOps manifest)

このディレクトリは Kubernetes Dashboard を kustomize でデプロイするためのマニフェストを含みます。

- `kustomization.yaml`: 公式 recommended.yaml を参照し、`ingress.yaml` と `admin-user.yaml` を追加します。
- `ingress.yaml`: ホスト `kd.fickledev.com` への Ingress（IP制限: 192.168.0.0/16、NGINX を想定）
- `admin-user.yaml`: 管理者ユーザー（トークンでログイン可能）

対応手順（例）:

1. DNS: `kd.fickledev.com` を Ingress コントローラの外部IPへ向ける。
2. Ingress Controller（例: nginx-ingress）をクラスタにインストールする。
3. Git を push して Argo CD がいる場合は同期する、あるいは手動で適用する:

```bash
kubectl apply -k apps/kubernetes-dashboard
```

4. 管理者トークン取得（Kubernetes >=1.24 推奨）:

```bash
kubectl -n kubernetes-dashboard create token admin-user
```

注意:
- TLS は含めていません。`kd.fickledev.com` で HTTPS を有効にする場合は cert-manager 等で証明書を発行し、Ingress の `tls` と Secret を追加してください。
- Ingress コントローラの種類によっては注釈名が異なるため、必要に応じて `ingress.yaml` の注釈を調整してください。

追記: SSL と Ingress の負荷について
- このディレクトリの `ingress.yaml` はクライアント側で TLS を終端しない前提（Ingress に TLS の Secret を入れていない）です。公開範囲がローカルネットワーク（192.168.0.0/16）のため、クライアント→Ingress の TLS は不要である想定です。
- 外部公開時は VPS や Cloudflare 等で TLS をオフロード（エッジで終端）し、オリジン（クラスタ）へは HTTP/既存設定で接続する方針が最も負荷を下げられます。
- 注意点: Dashboard 本体はデフォルトで HTTPS(8443) で動作するため、Ingress がバックエンドへ HTTPS 接続を行う設定（`nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"`）のままにすると、Ingress→Pod 間で TLS が発生します。これはクライアント向け TLS をIngressが終端するよりは軽い負荷ですが、完全に TLS を避けたい場合は下記のパススルーを利用してください。

TLS パススルー（Ingress に TLS 処理させない、負荷ゼロに近い）
- 概要: Ingress コントローラで SSL/TLS passthrough を有効にすると、Ingress は TLS 処理を行わず、暗号化されたまま Pod にバイパスします。Pod 側で証明書を持たせる必要があります。
- nginx-ingress の例: コントローラ起動時に `--enable-ssl-passthrough` を有効にし、`apps/kubernetes-dashboard/ingress-passthrough.yaml` を適用します。
- 制約: コントローラ側の追加設定が必要で、ロードバランサ設定や SNI ルールの制約を理解しておく必要があります。

簡単な運用フロー（推奨）:
1. 外部公開は Cloudflare/VPS 側で TLS を終端する。
2. Cloudflare→クラスタ間は HTTP（または軽微な内部 TLS）で接続する。
3. ローカル限定でアクセスする場合は `ingress.yaml` の IP 制限（`192.168.0.0/16`）を利用する。

パススルーを試したい場合:

```bash
# コントローラを ssl-passthrough 有効で再デプロイ
# 例: helm values に追加 --set controller.extraArgs.enable-ssl-passthrough=""

kubectl apply -f apps/kubernetes-dashboard/ingress-passthrough.yaml
```

推奨 Cloudflare 設定: `Full (strict)` を使い、証明書はエッジ側で管理してください。

---

TLS を有効にする手順と Vault 設定について

- 重要: Ingress の `tls.secretName` に指定する Secret は Ingress と同じネームスペースに存在する必要があります。現在の Ingress は `kubernetes-dashboard` ネームスペースに配置されています。

- 2つの選択肢:
	1. Vault/Let’s Encrypt の自動配置先を `kubernetes-dashboard` にする（推奨）。
		 例（あなたの設定に合わせて）:

```yaml
vault_letsencrypt_k8s_secrets:
	- cert_name: "fickledev.com"
		secret_name: "tls-fickledev"
		namespace: "kubernetes-dashboard"
```

	2. 既存の `ingress` ネームスペースにある Secret をコピーして `kubernetes-dashboard` ネームスペースに配置する。
		 例:

```bash
kubectl -n ingress get secret tls-fickledev -o yaml \
	| sed 's/namespace: ingress/namespace: kubernetes-dashboard/' \
	| kubectl apply -f -
```

- その後、`apps/kubernetes-dashboard/ingress.yaml` の `spec.tls` にある `secretName: tls-fickledev` を利用して Ingress を適用してください:

```bash
kubectl apply -k apps/kubernetes-dashboard
```

---

補足: 現在の `ingress.yaml` はクライアント TLS を終端して Ingress→Pod 間も HTTPS で接続する設定（`nginx.ingress.kubernetes.io/backend-protocol: "HTTPS"`）になっています。Ingress で TLS を終端しつつバックエンドも HTTPS にするか（双方向 TLS）、Ingress で終端してバックエンドを HTTP にするかは運用要件に応じて選択してください。


