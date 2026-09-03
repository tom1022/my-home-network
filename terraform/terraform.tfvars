# 非機密の構成値はこのファイルで管理します。

gateway     = "192.168.1.1"
nameservers = ["192.168.1.1"]
ci_user     = "tochi"

managed_domain = "fickledev.com"
vps_ipv4       = "163.44.119.79"
vps_ipv6       = "2400:8500:2002:3320:163:44:119:79"
vm_template_ids = {
  n100      = 9000
  "hp-z440" = 9001
}

# Proxmox の両ノードは自己署名のクラスタ内部 CA (PVE Cluster Manager CA) を提示する。
# variables.tf の既定値は検証を有効にする側 (false) に倒しているため、実際に plan/apply
# を成立させるにはここで明示的に無効化する。
insecure = true

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
