# Workers custom domains for the portfolio site (task 24.4). Routes
# fickledev.com and www.fickledev.com directly to the fickledev-portfolio
# Worker instead of the VPS edge host. The Worker script itself is deployed
# out-of-band by the portfolio repo's GitHub Actions workflow (task 24.3/
# 24.8), not by this Terraform config -- `service` below just names it.
#
# Rollback (delivery back to the edge host): remove this resource, then set
# both `enabled` flags in cloudflare_dns.tf's vps_hosts map back to `true`.
# vps_proxy still serves these two vhosts (task 24.5, which removes that
# definition, depends on this task and has not run), so no Ansible change is
# needed to make the edge host serve traffic again.
resource "cloudflare_workers_custom_domain" "portfolio" {
  for_each = toset([var.managed_domain, "www.${var.managed_domain}"])

  account_id = var.cloudflare_account_id
  zone_id    = var.cloudflare_zone_id
  hostname   = each.value
  service    = "fickledev-portfolio"

  # A custom domain and a plain address record cannot coexist on the same
  # hostname; cloudflare_dns.tf disables the matching vps_hosts entries in
  # this same apply. depends_on orders that record deletion before this
  # create so the two don't race within one `terraform apply`.
  depends_on = [cloudflare_dns_record.this]
}
