# 非機密の構成値はこのファイルで管理します。

container_bind_mounts = {
  gitea = [
    {
      volume    = "/mnt/pve/nas-gitea"
      path      = "/var/lib/gitea"
      backup    = false
      shared    = true
      read_only = false
    }
  ]
}
