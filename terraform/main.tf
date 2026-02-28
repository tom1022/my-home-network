module "containers" {
  source   = "./modules/container"
  for_each = local.containers

  name                 = each.key
  node_name            = each.value.node
  vm_id                = each.value.vmid
  template_file_id     = var.container_template_file_id
  cores                = each.value.cores
  memory               = each.value.mem
  disk_size            = each.value.disk
  datastore_id         = var.container_datastore
  ssh_public_key       = var.ssh_public_key
  ip0                  = each.value.ip0
  ip1                  = each.value.ip1
  gateway              = var.gateway
  nameservers          = var.nameservers
  bridge0              = var.bridge_primary
  bridge1              = var.bridge_secondary
  bridge_secondary_mtu = var.bridge_secondary_mtu
  swap                 = var.container_swap
  os_type              = "debian"
  start                = true
  ci_user              = local.ci_user
  zfs_pools            = lookup(each.value, "zfs_pools", null)
  bind_mounts          = try(var.container_bind_mounts[each.key], [])
}

module "virtual_machines" {
  source   = "./modules/vm"
  for_each = local.vms

  name                     = each.key
  node_name                = each.value.node
  vm_id                    = each.value.vmid
  template_vm_id           = local.template_ids[each.value.node]
  template_node_name       = each.value.node
  cores                    = each.value.cores
  memory                   = each.value.mem
  disk_size                = each.value.disk
  disk_datastore           = var.vm_disk_datastore
  ssh_public_key           = var.ssh_public_key
  gateway                  = var.gateway
  nameservers              = var.nameservers
  bridge0                  = var.bridge_primary
  bridge1                  = var.bridge_secondary
  bridge_secondary_mtu     = var.bridge_secondary_mtu
  ip0                      = each.value.ip0
  enable_qemu_agent        = var.vm_enable_qemu_agent
  qemu_agent_wait_for_ipv4 = var.vm_qemu_agent_wait_for_ipv4
  qemu_agent_wait_for_ipv6 = var.vm_qemu_agent_wait_for_ipv6
  ip1                      = each.value.ip1
  ci_user                  = local.ci_user
  zfs_pools                = lookup(each.value, "zfs_pools", null)
}
