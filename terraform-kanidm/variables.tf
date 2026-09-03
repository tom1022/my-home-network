variable "kanidm_url" {
  type        = string
  description = "Kanidm の公開オリジン"
  default     = "https://kanidm.fickledev.com"
}

variable "kanidm_token" {
  type        = string
  description = "terraform-kanidm サービスアカウントの API トークン (Infisical prod: TF_VAR_kanidm_token)"
  sensitive   = true
}
