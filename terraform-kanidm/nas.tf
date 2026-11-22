# NAS の SMB 同期ジョブが、nas_access のメンバーの RADIUS 秘密を読むための主体。
# provider が発行するトークンは読み書き可能で無期限のため generate_api_token は使わず、
# 読み取り専用のトークンを CLI で発行する (README 参照)。
resource "kanidm_service_account" "nas_smb_sync" {
  name               = "nas_smb_sync"
  displayname        = "NAS SMB Sync"
  entry_managed_by   = "idm_admins"
  generate_api_token = false
}

# idm_radius_servers は Kanidm 組み込みのグループで、所属アカウントに person の
# RADIUS 秘密の読み取り許可を与える。
resource "kanidm_group_members" "idm_radius_servers" {
  group   = "idm_radius_servers"
  members = [kanidm_service_account.nas_smb_sync.name]
}
