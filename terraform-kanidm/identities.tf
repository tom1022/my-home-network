# このファイルは「誰が到達できるか (kanidm_person とグループ所属)」を宣言しない。
# 個人アカウントとそのグループ所属はテストユーザー等を含め流動的であり、変更のたびに
# public リポジトリの diff に個人の識別子が残ることを避けるため、意図的に IaC の管理対象
# 外とした。IaC が宣言するのは「器」(グループの存在) と「権限構造」(account_policy /
# OIDC クライアントとの scope_map の結び付き) までであり、実際の所属は Kanidm の
# Web UI / CLI で運用者が直接管理する。
#
# 各グループの `members` 属性を省略しているのはこの境界を反映したものであり、
# kanidm_group.argocd_viewers で先に踏んだ provider 0.1.10 の挙動 (Optional+Computed の
# `members` を省略すると、サーバ側の実際の所属を変更せずに Terraform の管理対象からも
# 外れる。明示的な空集合 `[]` は逆に収束しない差分を出し続ける) をそのまま利用している。

# 開発基盤 (autonomous-parallel-dev-platform) そのものへ到達できる利用者の集合。
# ワークスペース (Sandbox Pod の IDE/端末) への直接到達を許可する対象であり、
# 開発環境が公開するサービスへの到達 (dev_platform_service_access) とは
# 保護すべき対象が異なるため、別グループとして分離する (要件 26.32)。
resource "kanidm_group" "dev_platform_workspace_access" {
  name        = "dev_platform_workspace_access"
  description = "autonomous-parallel-dev-platform のワークスペース (Sandbox Pod) へ到達できる利用者"
}

# 開発基盤が公開するサービス (ワークスペース内で稼働するアプリケーションのプレビュー等)
# へ到達できる利用者の集合。
resource "kanidm_group" "dev_platform_service_access" {
  name        = "dev_platform_service_access"
  description = "autonomous-parallel-dev-platform が公開するサービスへ到達できる利用者"
}

# ワークスペースへの到達は開発環境の制御そのものに直結するため、MFA を必須にし
# セッションを短く保つ。
resource "kanidm_account_policy" "dev_platform_workspace_access" {
  group                   = kanidm_group.dev_platform_workspace_access.name
  credential_type_minimum = "mfa"
  authsession_expiry      = 28800 # 8h
}

# 公開サービスの閲覧は相対的に低リスクなため、認証情報種別・セッション有効期限を
# ワークスペース側と独立に緩めた値で設定する (要件 26.33 の「独立設定」の実証)。
resource "kanidm_account_policy" "dev_platform_service_access" {
  group                   = kanidm_group.dev_platform_service_access.name
  credential_type_minimum = "any"
  authsession_expiry      = 86400 # 24h
}

# Gitea (gitea.fickledev.com) へ OIDC でログインできる利用者の集合 (要件 26.18)。
resource "kanidm_group" "gitea_access" {
  name        = "gitea_access"
  description = "Gitea (gitea.fickledev.com) へ OIDC でログインできる利用者"
}

# ArgoCD (argocd.fickledev.com) の RBAC (argocd-rbac-cm) にグループ名で対応付ける
# 2 グループ (要件 26.22)。グループ名は policy.csv 側の g 行と大文字小文字を含め
# 完全一致させること。
resource "kanidm_group" "argocd_admins" {
  name        = "argocd_admins"
  description = "ArgoCD で role:admin (フル権限) を持つ利用者"
}

# role:readonly に対応する検証用グループ。常時は空メンバーで宣言する
# (role:readonly が書き込みを拒否することは argocd_viewers のみに一時的に
# 所属させた状態で実機確認済み。検証記録は research.md 参照)。
# members を明示的な空集合 ([]) にすると、apply 直後は成功することもあるが
# 後続の plan/refresh でサーバ側の読み取りが null を返し際限なく
# "+ members = []" の差分を出し続ける (provider 0.1.10 で実測、収束しない)。
# members 属性自体を省略するとこの差分は消えるが、その場合メンバーの逸脱を
# Terraform が検知・是正しなくなる (このグループは検証専用で実害が小さいため許容する)。
resource "kanidm_group" "argocd_viewers" {
  name        = "argocd_viewers"
  description = "ArgoCD で role:readonly (読み取り専用) を持つ利用者"
}

# forward auth 判定ワークロード (apps/oauth2-proxy、要件 26.35) の OIDC クライアントに
# ログインできる利用者の集合。この単一クライアントは複数サービス共通の forward auth
# 判定ワークロード向けであり、サービスごとの認可 (どのグループがどのサービスに
# 到達できるか) は forward auth 側 (タスク 26.10-26.12 の管轄) で絞り込む前提のため、
# ここでは「forward auth を経由できる」利用者の集合のみを表す。
resource "kanidm_group" "forward_auth_access" {
  name        = "forward_auth_access"
  description = "forward auth 判定ワークロード (oauth2-proxy) の OIDC クライアントにログインできる利用者"
}

# Kanidm のドメイン既定の credential_type_minimum は mfa 相当であり (実機確認: 本グループへの
# 追加なしにパスワードのみで self-service credential update を commit しようとすると
# "MfaRequired" 警告が出て commit できない)、明示しない限りパスワード単体でのログインが
# 成立しない。forward auth が保護する対象は Home Assistant / Garage の UI 等 LAN 限定の
# 低リスクサービスであり、dev_platform_service_access と同じ判断で緩める。
resource "kanidm_account_policy" "forward_auth_access" {
  group                   = kanidm_group.forward_auth_access.name
  credential_type_minimum = "any"
  authsession_expiry      = 86400 # 24h
}

# Guacamole (console.fickledev.com) は Cloudflare Access の背後にのみ存在し、他サービスと
# 異なり forward auth や cluster ingress を経由しない唯一の認証層である (タスク 26.12,
# 要件 26.27, 26.29)。この Access のポリシーが判定に使う集合であり、admin PC への
# 到達可否を直接左右するため dev_platform_workspace_access と同じ判断で MFA を必須にする。
resource "kanidm_group" "guacamole_access" {
  name        = "guacamole_access"
  description = "Cloudflare Access 経由で Guacamole (console.fickledev.com) にログインできる利用者"
}

resource "kanidm_account_policy" "guacamole_access" {
  group                   = kanidm_group.guacamole_access.name
  credential_type_minimum = "mfa"
  authsession_expiry      = 28800 # 8h
}

# NAS (192.168.1.201) への POSIX ログインを許可する利用者の集合 (要件 26.12)。
# kanidm_unixd の pam_allowed_login_groups は POSIX 拡張されたグループしか
# 受け付けないため posix_enabled を有効にする。gidnumber は明示せず、Kanidm の
# 既定動的割当レンジ (research.md タスク 26.4 で NAS 実機の既存 UID/GID との
# 非衝突を確認済み) に委ねる。
resource "kanidm_group" "nas_access" {
  name          = "nas_access"
  description   = "NAS (192.168.1.201) へ POSIX ログインできる利用者"
  posix_enabled = true
}

# NAS への SSH ログインは LAN 内に閉じており、他の低リスク LAN 向けグループ
# (dev_platform_service_access, forward_auth_access) と同じ判断で
# credential_type_minimum を緩める。
resource "kanidm_account_policy" "nas_access" {
  group                   = kanidm_group.nas_access.name
  credential_type_minimum = "any"
  authsession_expiry      = 86400 # 24h
}
