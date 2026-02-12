provider "proxmox" {
  endpoint  = var.proxmox_api_url
  api_token = format("%s=%s", var.proxmox_api_token_id, var.proxmox_api_token_secret)
  insecure  = var.insecure
}
