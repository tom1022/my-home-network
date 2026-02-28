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
      vmid      = 152
      node      = "hp-z440"
      cores     = 8
      mem       = 16384
      disk      = 128
      zfs_pools = [500, 1000]
      ip0       = "192.168.1.152"
      ip1       = "172.16.0.152"
    }
    "nas" = {
      vmid      = 201
      node      = "hp-z440"
      cores     = 4
      mem       = 8192
      disk      = 64
      zfs_pools = [1000]
      ip0       = "192.168.1.201"
      ip1       = "172.16.0.201"
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
