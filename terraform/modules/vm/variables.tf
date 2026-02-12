variable "name" {
  type = string
}

variable "node_name" {
  type = string
}

variable "vm_id" {
  type = number
}

variable "template_vm_id" {
  type = number
}

variable "template_node_name" {
  type    = string
  default = ""
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

variable "disk_datastore" {
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

variable "enable_qemu_agent" {
  description = "Enable the QEMU guest agent reporting"
  type        = bool
  default     = true
}

variable "qemu_agent_wait_for_ipv4" {
  description = "Wait for IPv4 addresses from the guest agent"
  type        = bool
  default     = true
}

variable "qemu_agent_wait_for_ipv6" {
  description = "Wait for IPv6 addresses from the guest agent"
  type        = bool
  default     = false
}

variable "bridge_secondary_mtu" {
  description = "MTU applied to the secondary bridge interface"
  type        = number
  default     = 9000
}

variable "ci_user" {
  type = string
}
