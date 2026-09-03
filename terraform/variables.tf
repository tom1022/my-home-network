variable "proxmox_api_token_id" {
  description = "API token that Terraform will use to authenticate against Proxmox"
  type        = string
  sensitive   = true
}
variable "proxmox_api_token_secret" {
  description = "API token that Terraform will use to authenticate against Proxmox"
  type        = string
  sensitive   = true
}
variable "proxmox_auth_method" {
  description = "Authentication method for Proxmox provider: token or password"
  type        = string
  default     = "token"

  validation {
    condition     = contains(["token", "password"], var.proxmox_auth_method)
    error_message = "proxmox_auth_method must be either token or password."
  }
}
# proxmox_username/proxmox_password keep a default: they are only read when
# proxmox_auth_method = "password" (providers.tf ternary), an inactive path
# today, and are not supplied via Infisical. Stripping the default here would
# make every plan/apply demand a value for an unused credential pair.
variable "proxmox_username" {
  description = "Proxmox username for password-based authentication (example: root@pam)"
  type        = string
  default     = ""
  sensitive   = true
}
variable "proxmox_password" {
  description = "Proxmox password for password-based authentication"
  type        = string
  default     = ""
  sensitive   = true
}
variable "proxmox_api_url" {
  description = "API endpoint for Proxmox VE"
  type        = string
}
# Proxmox's own cluster CA (self-signed, not in any public/system trust
# store) is the only CA either node presents; see the iac-hygiene-remediation
# research.md "タスク 13.1" entry. Default is the safe (verify) side — the
# actual deployment overrides this to true in terraform.tfvars.
variable "insecure" {
  description = "Skip TLS verification against the Proxmox API"
  type        = bool
  default     = false
}

variable "ssh_public_key" {
  description = "Public key installed into all guests for access"
  type        = string
}

variable "gateway" {
  description = "Default IPv4 gateway assigned to each guest"
  type        = string
}

variable "nameservers" {
  description = "List of DNS servers for guests"
  type        = list(string)
}

variable "container_template_file_id" {
  description = "Storage ID of the LXC template used for new containers"
  type        = string
  default     = "local:vztmpl/debian-12-standard_12.12-1_amd64.tar.zst"
}

variable "container_datastore" {
  description = "Datastore to store container rootfs disks"
  type        = string
  default     = "local-lvm"
}

variable "container_swap" {
  description = "Amount of swap (in MB) allocated to each container"
  type        = number
  default     = 512
}

variable "vm_disk_datastore" {
  description = "Datastore where VM disks are created"
  type        = string
  default     = "local-lvm"
}

variable "vm_zfs_pool_datastore" {
  description = "Datastore backing the additional ZFS-pool disks declared per VM via zfs_pools"
  type        = string
  default     = "zfs-pool"
}

variable "vm_template_ids" {
  description = "Template VM IDs keyed by node name. Update these to match your environment."
  type        = map(number)
}

variable "bridge_primary" {
  description = "Primary bridge used for eth0/net0"
  type        = string
  default     = "vmbr0"
}

variable "bridge_secondary" {
  description = "Secondary bridge used for eth1/net1"
  type        = string
  default     = "vmbr1"
}

variable "bridge_secondary_mtu" {
  description = "MTU applied to the secondary bridge/interface"
  type        = number
  default     = 9000
}

variable "vm_enable_qemu_agent" {
  description = "Whether to enable the QEMU guest agent inside cloned VMs"
  type        = bool
  default     = true
}

variable "vm_qemu_agent_wait_for_ipv4" {
  description = "When qemu guest agent is enabled, wait for IPv4 addresses"
  type        = bool
  default     = true
}

variable "vm_qemu_agent_wait_for_ipv6" {
  description = "When qemu guest agent is enabled, wait for IPv6 addresses"
  type        = bool
  default     = false
}

variable "ci_user" {
  description = "Cloud-init user created inside VMs"
  type        = string
}

variable "container_bind_mounts" {
  description = "Map of bind mount definitions keyed by container name. Each item requires `volume` (host path) and `path` (path inside container)."
  type        = map(any)
  default     = {}
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token used by Terraform, separate from the DNS-01 token used for certificate issuance"
  type        = string
  sensitive   = true
}

variable "cloudflare_account_id" {
  description = "Cloudflare account identifier"
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone identifier for the managed zone"
  type        = string
}

variable "managed_domain" {
  description = "Domain name of the Cloudflare zone this configuration manages"
  type        = string
}

variable "kanidm_oidc_guacamole_client_secret" {
  description = "Client secret for the Kanidm OIDC client \"guacamole\" (terraform-kanidm), consumed by the Cloudflare Access generic OIDC identity provider that fronts Guacamole"
  type        = string
  sensitive   = true
}

variable "vps_ipv4" {
  description = "Public IPv4 address of the VPS edge host"
  type        = string
}

variable "vps_ipv6" {
  description = "Public IPv6 address of the VPS edge host"
  type        = string
}
