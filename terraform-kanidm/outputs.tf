output "dev_platform_workspace_client_secret" {
  value     = kanidm_oauth2_basic.dev_platform_workspace.client_secret
  sensitive = true
}

output "dev_platform_services_client_secret" {
  value     = kanidm_oauth2_basic.dev_platform_services.client_secret
  sensitive = true
}

output "gitea_client_secret" {
  value     = kanidm_oauth2_basic.gitea.client_secret
  sensitive = true
}

output "forward_auth_client_secret" {
  value     = kanidm_oauth2_basic.forward_auth.client_secret
  sensitive = true
}

output "guacamole_client_secret" {
  value     = kanidm_oauth2_basic.guacamole.client_secret
  sensitive = true
}
