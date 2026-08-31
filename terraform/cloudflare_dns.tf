# DNS records for the fickledev.com zone.
#
# Excluded on purpose: _acme-challenge.* TXT records. cert-manager creates
# and deletes these dynamically for DNS-01 validation; a Terraform-managed
# copy would fight that automation on every renewal.
#
# Proxied hostnames all resolve to the VPS public IP; the reverse-proxy
# upstream selection happens on the VPS itself (ansible/roles/vps_proxy),
# not in DNS. Comments below reference the corresponding
# ansible/inventory/host_vars/vps/main.yml variables where a mapping exists.
# (Not stored as the Cloudflare record's own `comment` field: none of these
# records carry one live, and setting one would be a real config change.)

locals {
  dns_records = {
    # vps_proxy_domain_main; nginx routes / to vps_proxy_upstream_main, /blog to vps_proxy_upstream_blog
    root_a = {
      name    = "fickledev.com"
      type    = "A"
      content = "163.44.119.79"
      proxied = true
      ttl     = 1
    }
    root_aaaa = {
      name    = "fickledev.com"
      type    = "AAAA"
      content = "2400:8500:2002:3320:163:44:119:79"
      proxied = true
      ttl     = 1
    }
    # vps_proxy_domain_www; primary vhost, see ansible/roles/vps_proxy/templates/fickledev.com.conf.j2
    www_a = {
      name    = "www.fickledev.com"
      type    = "A"
      content = "163.44.119.79"
      proxied = true
      ttl     = 1
    }
    www_aaaa = {
      name    = "www.fickledev.com"
      type    = "AAAA"
      content = "2400:8500:2002:3320:163:44:119:79"
      proxied = true
      ttl     = 1
    }
    # vps_proxy_domain_mail; not HTTP, haproxy TCP-passes through to vps_proxy_upstream_mail
    mail_a = {
      name    = "mail.fickledev.com"
      type    = "A"
      content = "163.44.119.79"
      proxied = false
      ttl     = 1
    }
    mail_aaaa = {
      name    = "mail.fickledev.com"
      type    = "AAAA"
      content = "2400:8500:2002:3320:163:44:119:79"
      proxied = false
      ttl     = 1
    }
    # No corresponding vps_proxy_* upstream found in ansible/inventory/host_vars/vps/main.yml at code time.
    mc_a = {
      name    = "mc.fickledev.com"
      type    = "A"
      content = "163.44.119.79"
      proxied = false
      ttl     = 1
    }
    mc_aaaa = {
      name    = "mc.fickledev.com"
      type    = "AAAA"
      content = "2400:8500:2002:3320:163:44:119:79"
      proxied = false
      ttl     = 1
    }
    # Matched by SNI in vps_proxy_xray_sni; haproxy TCP-passes through to the xray VPN backend on the k3s nodes.
    appflowy_a = {
      name    = "appflowy.fickledev.com"
      type    = "A"
      content = "163.44.119.79"
      proxied = false
      ttl     = 1
    }
    # Routed through the Guacamole Zero Trust tunnel.
    console_cname = {
      name    = "console.fickledev.com"
      type    = "CNAME"
      content = "${cloudflare_zero_trust_tunnel_cloudflared.guacamole.id}.cfargotunnel.com"
      proxied = true
      ttl     = 1
    }
    # Routed through the kubernetes-tunnel Zero Trust tunnel.
    crafty_cname = {
      name    = "crafty.fickledev.com"
      type    = "CNAME"
      content = "${cloudflare_zero_trust_tunnel_cloudflared.kubernetes.id}.cfargotunnel.com"
      proxied = true
      ttl     = 1
    }
    idp_cname = {
      name    = "idp.fickledev.com"
      type    = "CNAME"
      content = "${cloudflare_zero_trust_tunnel_cloudflared.kubernetes.id}.cfargotunnel.com"
      proxied = true
      ttl     = 1
    }
    mx_mail = {
      name     = "fickledev.com"
      type     = "MX"
      content  = "mail.fickledev.com"
      priority = 9
      proxied  = false
      ttl      = 1
    }
    site_verification_txt = {
      name    = "fickledev.com"
      type    = "TXT"
      content = "\"google-site-verification=oZTTqPYWuIahE4Bm9sdfVhESt1KBCM-QiWhBkq_vzD0\""
      proxied = false
      ttl     = 3600
    }
  }
}

resource "cloudflare_dns_record" "this" {
  for_each = local.dns_records

  zone_id  = var.cloudflare_zone_id
  name     = each.value.name
  type     = each.value.type
  content  = each.value.content
  ttl      = each.value.ttl
  proxied  = each.value.proxied
  priority = lookup(each.value, "priority", null)
}
