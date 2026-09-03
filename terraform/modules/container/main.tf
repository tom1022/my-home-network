locals {
  ip_configs = concat(
    [
      {
        address = var.ip0
        gateway = var.gateway
      }
    ],
    var.ip1 != "" ? [{ address = var.ip1, gateway = null }] : []
  )

  network_interfaces = concat(
    [
      {
        name     = "eth0"
        bridge   = var.bridge0
        firewall = var.network_interface_firewall
      }
    ],
    var.ip1 != "" ? [{ name = "eth1", bridge = var.bridge1, mtu = var.bridge_secondary_mtu, firewall = var.network_interface_firewall }] : []
  )

  ssh_keys             = var.ssh_public_key != "" ? [trimspace(var.ssh_public_key)] : []
  normalized_zfs_pools = var.zfs_pools == null ? [] : try(tolist(var.zfs_pools), [var.zfs_pools])
  zfs_pools_map        = { for idx, val in local.normalized_zfs_pools : tostring(idx) => val }
  zfs_pool_mount_points = [
    for idx in sort(keys(local.zfs_pools_map)) : {
      volume = try(local.zfs_pools_map[idx].volume, "zfs-pool")
      size   = try(local.zfs_pools_map[idx].size, format("%sG", local.zfs_pools_map[idx]))
      path   = try(local.zfs_pools_map[idx].path, format("/mnt/zfs-pool-%s", idx))
      backup = try(local.zfs_pools_map[idx].backup, false)
    }
  ]
  all_mount_points = concat(local.zfs_pool_mount_points, var.bind_mounts)
}

resource "proxmox_virtual_environment_container" "this" {
  node_name   = var.node_name
  vm_id       = var.vm_id
  description = "Managed through the bpg/proxmox Terraform provider"
  protection  = var.protection

  unprivileged = true

  cpu {
    cores = var.cores
  }

  memory {
    dedicated = var.memory
    swap      = var.swap
  }

  disk {
    datastore_id = var.datastore_id
    size         = var.disk_size
  }


  initialization {
    hostname = var.name

    dns {
      servers = var.nameservers
    }

    dynamic "ip_config" {
      for_each = local.ip_configs
      content {
        ipv4 {
          address = format("%s/24", ip_config.value.address)
          gateway = ip_config.value.gateway
        }
      }
    }

    dynamic "user_account" {
      for_each = length(local.ssh_keys) > 0 ? [local.ssh_keys] : []
      content {
        keys = user_account.value
      }
    }
  }

  dynamic "network_interface" {
    for_each = local.network_interfaces
    content {
      name     = network_interface.value.name
      bridge   = network_interface.value.bridge
      mtu      = lookup(network_interface.value, "mtu", null)
      firewall = lookup(network_interface.value, "firewall", null)
    }
  }

  dynamic "mount_point" {
    for_each = local.all_mount_points
    content {
      volume        = lookup(mount_point.value, "volume", null)
      path          = mount_point.value.path
      backup        = lookup(mount_point.value, "backup", null)
      read_only     = lookup(mount_point.value, "read_only", null)
      replicate     = lookup(mount_point.value, "replicate", null)
      shared        = lookup(mount_point.value, "shared", null)
      acl           = lookup(mount_point.value, "acl", null)
      quota         = lookup(mount_point.value, "quota", null)
      size          = lookup(mount_point.value, "size", null)
      mount_options = lookup(mount_point.value, "mount_options", null)
    }
  }

  operating_system {
    template_file_id = var.template_file_id
    type             = var.os_type
  }

  started = var.start

  lifecycle {
    # operating_system: このブロックで template_file_id と type を宣言しているが、Proxmox は
    # クローン後に内部識別用の追加属性を補って返すため、宣言していない部分の不一致が毎回差分として現れる。
    # features/console: このモジュールはいずれも宣言しないが、Proxmox API はクローン元や実機の
    # 実効値を computed 属性として返すため、宣言なし=null との差分が常に出る。features の変更は
    # root@pam 権限を要求し (実測: HTTP 403)、現在の API トークンでは適用できない。
    ignore_changes = [operating_system, features, console]
  }
}
