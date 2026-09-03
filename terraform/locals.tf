locals {
  ci_user = var.ci_user

  template_ids = var.vm_template_ids

  vms = {
    "k3s-server" = {
      vmid  = 150
      node  = "n100"
      cores = 4
      mem   = 8192
      disk  = 64
      ip0   = "192.168.1.150"
      ip1   = "172.16.0.150"
    }
    "k3s-agent-minipc" = {
      vmid  = 151
      node  = "n100"
      cores = 4
      mem   = 8192
      disk  = 64
      ip0   = "192.168.1.151"
      ip1   = "172.16.0.151"
    }
    "k3s-agent-z440" = {
      vmid  = 152
      node  = "hp-z440"
      cores = 8
      mem   = 16384
      disk  = 128
      # 注意: この map の for_each はキーのソート順で disk ブロックを生成し、プロバイダは
      # ディスクブロックを位置で照合する (interface 属性による照合ではない)。既存キーより
      # ソート順で前に来るキーを追加すると、既存ディスクの interface/size が意図せず入れ替わる。
      # 新規キーは既存キーよりアルファベット順で後ろに来る名前にすること。
      zfs_pools = {
        nextcloud = { size = 1000, scsi = 2 }
        # Garage の data_dir (実体)。逐次書き込みが主のため容量の大きい HDD 側 (zfs-pool) に置く。
        object_storage = { size = 200, scsi = 3 }
      }
      # Garage の metadata_dir (索引)。不規則な小さい書き込みが主で遅延に敏感なため SSD 側 (local-lvm) に置く。
      lvm_disks = {
        garage_metadata = { size = 50, scsi = 1 }
      }
      ip0 = "192.168.1.152"
      ip1 = "172.16.0.152"
    }
    "nas" = {
      vmid  = 201
      node  = "hp-z440"
      cores = 4
      mem   = 8192
      disk  = 64
      zfs_pools = {
        data = { size = 1000, scsi = 1 }
      }
      ip0 = "192.168.1.201"
      ip1 = "172.16.0.201"
    }
  }

  containers = {
    "gitea" = {
      vmid  = 200
      node  = "n100"
      cores = 2
      mem   = 4096
      disk  = 64
      ip0   = "192.168.1.200"
      ip1   = "172.16.0.200"
    }
    "pbs" = {
      vmid      = 202
      node      = "hp-z440"
      cores     = 4
      mem       = 8192
      disk      = 64
      ip0       = "192.168.1.202"
      zfs_pools = [500]
      ip1       = "172.16.0.202"
    }
  }
}
