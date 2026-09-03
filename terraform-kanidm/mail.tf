# メール認証 (mail-platform タスク 3.1) — アプリケーション定義と利用者グループ。
#
# アプリケーションパスワードを発行できる対象をこのグループの所属者に限定する。
# 所属者のアカウント名はメールアドレスのローカル部と一致させる (bind DN を
# spn=%{user},app=mail,... のテンプレートで組み立てる前提。DMS 側の実装はタスク 6 で
# 構成する)。所属そのもの (誰がメンバーか) は個人アカウントに紐づく操作のため、
# identities.tf の他グループと同じ方針で Terraform の管理対象に含めない。
resource "kanidm_group" "mail_users" {
  name        = "mail_users"
  description = "メールクライアントのアプリケーションパスワードを発行できる利用者 (アカウント名はメールアドレスのローカル部と一致させる)"
}

# Kanidm ドメインの既定 (idm_all_persons 経由で継承される credential_type_minimum: mfa) は
# パスワード単体の資格情報を許容せず、アプリケーションパスワードの発行そのものが成立しない。
# mail_users には any まで緩めたアカウントポリシーを与える (要件 2.12)。
# 利用者自身のログインセッション確立に要る MFA は idm_all_persons 側の要求のまま残り、
# このポリシーでは緩まない (研究ログのタスク1.2/1.3実証記録を参照)。
resource "kanidm_account_policy" "mail_users" {
  group                   = kanidm_group.mail_users.name
  credential_type_minimum = "any"
}

resource "kanidm_application" "mail" {
  name         = "mail"
  displayname  = "Mail"
  linked_group = kanidm_group.mail_users.id
}

# メール認証 (mail-platform タスク 3.2) — メール属性検索用サービスアカウント。
#
# idm_mail_servers は Kanidm 組み込みの "MAIL server access delegation" グループであり、
# 所属アカウントに mail 属性の読み取り許可を与える (検索結果の取得だけでなく検索条件と
# して用いる場合にも必要。許可が欠けている場合はエラーではなく 0 件が返る)。
# mail 属性はインデックスされていないため、DMS 側 (タスク 6.3) の検索フィルタは
# 必ずインデックス済み属性 (例: name) との論理積で組み立てる。単独条件は資源制限に
# より拒否される。
resource "kanidm_service_account" "mail_ldap_search" {
  name               = "mail-ldap-search"
  displayname        = "Mail LDAP Search"
  entry_managed_by   = "idm_admins"
  generate_api_token = true
}

resource "kanidm_group_members" "idm_mail_servers" {
  group   = "idm_mail_servers"
  members = [kanidm_service_account.mail_ldap_search.name]
}

# LDAP bind (dn=token) の資格情報として使う。値は Infisical `MAIL_LDAP_SEARCH_PASSWORD` と
# 一致させる (このモジュールの適用後、実際に生成された値で Infisical 側を上書きする)。
output "mail_ldap_search_api_token" {
  value     = kanidm_service_account.mail_ldap_search.api_token
  sensitive = true
}
