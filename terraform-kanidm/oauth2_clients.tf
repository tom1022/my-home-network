# 開発基盤 (autonomous-parallel-dev-platform) 向けの OIDC クライアント 2 件。
# 開発環境の構築自体は本モジュールのスコープ外 (design.md IdentityPlatform の
# Implementation Notes を参照)。origin/redirect_uris は当該基盤がまだ存在しないため
# 暫定値であり、実際の Ingress ホスト名確定時に更新する前提で宣言する。
# 宣言を後から追加する際に非公式 provider のバージョン固定を再確認する手間を避けるため
# (要件 26.36 に対応する将来のクライアントも含め) 最初の宣言に含めている。

# 開発環境そのものへの到達 (Sandbox Pod の IDE/端末) を制御するクライアント。
# origin は末尾スラッシュ付きで宣言する。Kanidm サーバ側が oauth2_rs_origin_landing を
# 常に末尾スラッシュ付きへ正規化するため、末尾スラッシュ無しで宣言すると
# 適用のたびに差分が出る (provider 0.1.10 で実測)。
resource "kanidm_oauth2_basic" "dev_platform_workspace" {
  name        = "dev-platform-workspace"
  displayname = "Dev Platform Workspace"
  origin      = "https://dev.fickledev.com/"

  redirect_uris = [
    "https://dev.fickledev.com/oauth2/callback",
  ]

  # scope_map.group は provider 0.1.10 の読み取り後 state 上では UUID として保持される。
  # グループ名を渡すと apply のたびに差分が出る (provider 0.1.10 で実測) ため id (UUID) を渡す。
  scope_map {
    group  = kanidm_group.dev_platform_workspace_access.id
    scopes = ["openid", "profile", "email", "groups"]
  }
}

# 開発環境が公開するサービス (ワークスペース内で稼働するアプリケーションのプレビュー) への
# 到達を制御するクライアント。許可グループ・認証情報種別・セッション有効期限を
# dev_platform_workspace とは独立に設定する (要件 26.33)。
resource "kanidm_oauth2_basic" "dev_platform_services" {
  name        = "dev-platform-services"
  displayname = "Dev Platform Services"
  origin      = "https://apps.dev.fickledev.com/"

  redirect_uris = [
    "https://apps.dev.fickledev.com/oauth2/callback",
  ]

  scope_map {
    group  = kanidm_group.dev_platform_service_access.id
    scopes = ["openid", "profile", "email", "groups"]
  }
}

# Gitea (k8s 外の LXC ホスト、gitea.fickledev.com) 向けの OIDC クライアント (要件 26.18)。
# redirect_uris は Gitea が ROOT_URL と認証ソース名から組み立てる形式
# (https://gitea.fickledev.com/user/oauth2/<認証ソース名>/callback、タスク 26.6 で確認済み)。
# 認証ソース名は ansible/roles/gitea が登録する "kanidm" と一致させる。
resource "kanidm_oauth2_basic" "gitea" {
  name        = "gitea"
  displayname = "Gitea"
  origin      = "https://gitea.fickledev.com/"

  redirect_uris = [
    "https://gitea.fickledev.com/user/oauth2/kanidm/callback",
  ]

  scope_map {
    group  = kanidm_group.gitea_access.id
    scopes = ["openid", "profile", "email", "groups"]
  }
}

# ArgoCD (argocd.fickledev.com) 向けの OIDC クライアント (要件 26.20-26.22)。
#
# UI (ブラウザ) と CLI (`argocd login --sso`) を別々の Kanidm クライアントに分けない。
# Kanidm は OAuth2 クライアントごとに issuer URL (https://.../oauth2/openid/:client_id:/)
# が異なる (公式ドキュメント integrations/oauth2.md: "Kanidm uses client-specific Issuer
# URLs, endpoint URLs and token signing keys")。一方 ArgoCD の dex 非経由 OIDC 設定
# (argocd-cm の oidc.config) は issuer を 1 つしか持てず、発行された ID トークンの検証は
# 常にこの単一 issuer に対して行われる (util/oidc/provider.go の Verify はログイン時に
# 限らずその後の全 API 呼び出しで実行され、util/session/sessionmanager.go の Create() は
# 「token-based session creation no longer supported」として ID トークンを ArgoCD 自身の
# セッションに引き継がない実装であることをソースで確認した)。そのため UI 用の confidential
# クライアントと CLI 用の public クライアントを別々に登録すると、どちらか一方の issuer は
# 常に検証エラーになり機能しない。
#
# 解決策として単一の public クライアントを UI と CLI の双方で共用する。ArgoCD v2.12.1 の
# 配布フロントエンド (main.*.js) は enablePKCEAuthentication 用の PKCE 実装
# (code_challenge/codeVerifier/S256) を同梱しており、ブラウザ側でも PKCE 完結の認可コード
# フローが行えることを実機のバンドルで確認済み (argocd-cm 側で enablePKCEAuthentication:
# true を設定する)。public クライアントは PKCE を無効化できない (Kanidm 側の仕様) ため、
# 要件 26.21 が要求する「PKCE を要求する公開クライアント」を UI 用途にも安全に転用できる。
resource "kanidm_oauth2_public" "argocd" {
  name        = "argocd"
  displayname = "ArgoCD"
  origin      = "https://argocd.fickledev.com/"

  redirect_uris = [
    # ブラウザ (server 側 URL: ansible/roles/argocd の argocd-cm `url` から組み立て)。
    "https://argocd.fickledev.com/auth/callback",
    # `argocd login --sso` の既定ローカルコールバック (--sso-port 既定値 8085)。
    "http://localhost:8085/auth/callback",
  ]

  scope_map {
    group  = kanidm_group.argocd_admins.id
    scopes = ["openid", "profile", "email", "groups"]
  }

  scope_map {
    group  = kanidm_group.argocd_viewers.id
    scopes = ["openid", "profile", "email", "groups"]
  }
}

# forward auth 判定ワークロード (apps/oauth2-proxy、gitops-apps) 向けの OIDC クライアント
# (要件 26.35, 26.36)。認証基盤は OIDC のみを提供し forward auth の終端を提供しないため、
# Traefik の forwardAuth middleware の転送先となる oauth2-proxy をこのクライアントで
# 認証させる。confidential クライアント (client_secret あり) とする。
# origin は末尾スラッシュ付きで宣言し、scope_map.group には kanidm_group.<name>.id
# (UUID) を渡す (provider 0.1.10 の実装バグ回避策。タスク 26.3 の記録を参照)。
resource "kanidm_oauth2_basic" "forward_auth" {
  name        = "forward-auth"
  displayname = "Forward Auth"
  origin      = "https://forwardauth.fickledev.com/"

  redirect_uris = [
    "https://forwardauth.fickledev.com/oauth2/callback",
  ]

  scope_map {
    group  = kanidm_group.forward_auth_access.id
    scopes = ["openid", "profile", "email", "groups"]
  }
}

# Cloudflare Access (console.fickledev.com の唯一の認証層) の識別提供元を Kanidm に
# 差し替えるための OIDC クライアント (要件 26.27, 26.29)。Guacamole 自体は k8s 外の
# 管理用 PC の localhost にのみ bind されており forward auth や cluster ingress を
# 経由しないため (research.md タスク 26.12)、他サービスと同じ forward auth 経路には載せず、
# トンネル手前の既存の接続制御 (Cloudflare Access) の識別提供元だけを差し替えて委譲を
# 完結させる。CONSOLE-VLAN → DMZ-VLAN の到達性は新設しない。OIDC の RP は Guacamole
# ではなく Cloudflare Access 自身であるため、origin/redirect_uris は Guacamole の
# ホスト名ではなく Cloudflare の team domain を指す。Guacamole 内蔵の OIDC 拡張は
# implicit flow のみを実装し Kanidm が拒否するため使用しない (要件 26.27)。
resource "kanidm_oauth2_basic" "guacamole" {
  name        = "guacamole"
  displayname = "Guacamole (Cloudflare Access)"
  origin      = "https://fickledev.cloudflareaccess.com/"

  redirect_uris = [
    "https://fickledev.cloudflareaccess.com/cdn-cgi/access/callback",
  ]

  scope_map {
    group  = kanidm_group.guacamole_access.id
    scopes = ["openid", "profile", "email", "groups"]
  }
}
