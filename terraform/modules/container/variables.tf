variable "name" {
  type = string
}

variable "node_name" {
  type = string
}

variable "vm_id" {
  type = number
}

variable "template_file_id" {
  type = string
}

variable "cores" {
  type = number
}

variable "memory" {
  type = number
}

variable "disk_size" {
  type = number
}

variable "datastore_id" {
  type = string
}

variable "ssh_public_key" {
  type = string
}

variable "ip0" {
  type = string
}

variable "ip1" {
  type    = string
  default = ""
}

variable "gateway" {
  type = string
}

variable "nameservers" {
  type = list(string)
}

variable "bridge0" {
  type = string
}

variable "bridge1" {
  type = string
}

variable "bridge_secondary_mtu" {
  description = "MTU applied to the secondary bridge interface"
  type        = number
  default     = 9000
}

variable "swap" {
  type = number
}

variable "os_type" {
  type = string
}

variable "start" {
  type = bool
}
variable "ci_user" {
  type = string
}
variable "zfs_pools" {
  description = "Optional single number or list of numbers describing sizes (GB) for additional ZFS pool volumes to attach."
  type        = any
  default     = null
}

variable "bind_mounts" {
  description = "Optional bind mount definitions for LXC mount_point blocks."
  type        = list(any)
  default     = []
}
