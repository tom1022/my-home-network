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

  network_devices = concat(
    [
      {
        bridge = var.bridge0
      }
    ],
    var.ip1 != "" ? [{ bridge = var.bridge1, mtu = var.bridge_secondary_mtu }] : []
  )

  ssh_keys             = var.ssh_public_key != "" ? [trimspace(var.ssh_public_key)] : []
  normalized_zfs_pools = var.zfs_pools == null ? [] : try(tolist(var.zfs_pools), [var.zfs_pools])
  zfs_pools_map        = { for idx, val in local.normalized_zfs_pools : tostring(idx) => val }
}

resource "proxmox_virtual_environment_vm" "this" {
  name      = var.name
  node_name = var.node_name
  vm_id     = var.vm_id
  reboot_after_update = true

  clone {
    vm_id     = var.template_vm_id
    node_name = var.template_node_name != "" ? var.template_node_name : var.node_name
    full      = true
  }

  scsi_hardware = "virtio-scsi-pci"

  boot_order = ["scsi0", "net0"]

  cpu {
    cores   = var.cores
    sockets = 1
  }

  memory {
    dedicated = var.memory
  }

  disk {
    datastore_id = var.disk_datastore
    interface    = "scsi0"
    size         = var.disk_size
  }

  dynamic "disk" {
    for_each = local.zfs_pools_map
    content {
      # lookup pool via disk.key/disk.value provided by the dynamic block
      size         = try(local.zfs_pools_map[disk.key].size, local.zfs_pools_map[disk.key])
      datastore_id = "zfs-pool"
      interface    = format("scsi%s", tostring(tonumber(disk.key) + 1))
    }
  }

  agent {
    enabled = var.enable_qemu_agent

    wait_for_ip {
      ipv4 = var.qemu_agent_wait_for_ipv4
      ipv6 = var.qemu_agent_wait_for_ipv6
    }
  }

  initialization {

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
        username = var.ci_user
        keys     = user_account.value
      }
    }
  }

  dynamic "network_device" {
    for_each = local.network_devices
    content {
      bridge = network_device.value.bridge
      model  = "virtio"
      mtu    = lookup(network_device.value, "mtu", null)
    }
  }
}
