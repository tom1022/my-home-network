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
        name   = "eth0"
        bridge = var.bridge0
      }
    ],
    var.ip1 != "" ? [{ name = "eth1", bridge = var.bridge1, mtu = var.bridge_secondary_mtu }] : []
  )

  ssh_keys             = var.ssh_public_key != "" ? [trimspace(var.ssh_public_key)] : []
  normalized_zfs_pools = var.zfs_pools == null ? [] : try(tolist(var.zfs_pools), [var.zfs_pools])
  zfs_pools_map        = { for idx, val in local.normalized_zfs_pools : tostring(idx) => val }
}

resource "proxmox_virtual_environment_container" "this" {
  node_name   = var.node_name
  vm_id       = var.vm_id
  description = "Managed through the bpg/proxmox Terraform provider"

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
      name   = network_interface.value.name
      bridge = network_interface.value.bridge
      mtu    = lookup(network_interface.value, "mtu", null)
    }
  }

  operating_system {
    template_file_id = var.template_file_id
    type             = var.os_type
  }

  started = var.start
}
