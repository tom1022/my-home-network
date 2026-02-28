provider "proxmox" {
  endpoint = var.proxmox_api_url

  api_token = var.proxmox_auth_method == "token" ? format("%s=%s", var.proxmox_api_token_id, var.proxmox_api_token_secret) : null
  username  = var.proxmox_auth_method == "password" ? var.proxmox_username : null
  password  = var.proxmox_auth_method == "password" ? var.proxmox_password : null

  insecure = var.insecure
}
