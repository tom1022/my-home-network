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
  # Hostnames that share the VPS's public A/AAAA pair; only `proxied` and
  # AAAA presence vary per host. Map key doubles as the dns_records key
  # prefix below (root_a, root_aaaa, ...) so resource addresses are unchanged.
  # `enabled = false` suspends a host's record without deleting its
  # definition here, so re-enabling it is a one-line revert.
  vps_hosts = {
    # delivery moved to the fickledev-portfolio Workers custom domain
    # (cloudflare_workers.tf), which cannot coexist with an address record on
    # the same hostname. Definition kept, not deleted, so rollback (see
    # cloudflare_workers.tf) is enabled = true here. The vps_proxy role no
    # longer serves these hostnames either (ansible/roles/vps_proxy/templates/
    # fickledev.com.conf.j2 dropped the vhost and vps_proxy_upstream_main/
    # vps_proxy_upstream_blog): full rollback also needs that vhost restored
    # from git history, not just this flag flipped.
    root = { name = var.managed_domain, proxied = true, aaaa = true, enabled = false }
    www  = { name = "www.${var.managed_domain}", proxied = true, aaaa = true, enabled = false }
    # mailu (k3s) 撤去に伴い vps_proxy_domain_mail / vps_proxy_upstream_mail の中継先は削除済み。
    # レコード自体は VPS 上に構築予定の後続メール基盤 (mail-platform spec) が同一ホスト名で
    # 再利用するため保持する。
    mail = { name = "mail.${var.managed_domain}", proxied = false, aaaa = true, enabled = true }
    # No corresponding vps_proxy_* upstream found in ansible/inventory/host_vars/vps/main.yml at code time.
    mc = { name = "mc.${var.managed_domain}", proxied = false, aaaa = true, enabled = true }
    # xrayvpn は停止中 (vps_proxy_xray_sni を空にして SNI 分岐も無効化済み)。
    # 復帰時は enabled を true に戻して apply するのみ。
    appflowy = { name = "appflowy.${var.managed_domain}", proxied = false, aaaa = false, enabled = false }
  }

  vps_a_records = {
    for key, host in local.vps_hosts : "${key}_a" => {
      name    = host.name
      type    = "A"
      content = var.vps_ipv4
      proxied = host.proxied
      ttl     = 1
    } if host.enabled
  }

  vps_aaaa_records = {
    for key, host in local.vps_hosts : "${key}_aaaa" => {
      name    = host.name
      type    = "AAAA"
      content = var.vps_ipv6
      proxied = host.proxied
      ttl     = 1
    } if host.aaaa && host.enabled
  }

  cloudflare_tunnel_ids = {
    guacamole  = cloudflare_zero_trust_tunnel_cloudflared.guacamole.id
    kubernetes = cloudflare_zero_trust_tunnel_cloudflared.kubernetes.id
  }

  # CNAMEs routed through Cloudflare Zero Trust tunnels.
  tunnel_cnames = {
    console = { name = "console.${var.managed_domain}", tunnel = "guacamole" }
    crafty  = { name = "crafty.${var.managed_domain}", tunnel = "kubernetes" }
    # 認証基盤 (Kanidm) の新規公開ホスト名 (task 26.1)。DNS レコードと
    # トンネルの ingress 経路 (cloudflare_zero_trust.tf) をあわせて Terraform 管理下に置く。
    kanidm = { name = "kanidm.${var.managed_domain}", tunnel = "kubernetes" }
    # ArgoCD (task 26.6)。IngressRoute は ansible/roles/argocd が既に生成済みで
    # 内部到達は成立している。欠けていたのはこの DNS レコードのみ。
    argocd = { name = "argocd.${var.managed_domain}", tunnel = "kubernetes" }
    # Gitea (task 26.6)。LXC ホスト (192.168.1.200:3000) への直接ルートは
    # cloudflare_zero_trust.tf 側で定義。
    gitea = { name = "gitea.${var.managed_domain}", tunnel = "kubernetes" }
    # oauth2-proxy / forward auth (task 26.35)。保護対象 (ha/garage) の認証後
    # 戻り先である redirect_uri のホスト名を外部から解決・到達可能にする。
    forwardauth = { name = "forwardauth.${var.managed_domain}", tunnel = "kubernetes" }
  }

  cname_records = {
    for key, cname in local.tunnel_cnames : "${key}_cname" => {
      name    = cname.name
      type    = "CNAME"
      content = "${local.cloudflare_tunnel_ids[cname.tunnel]}.cfargotunnel.com"
      proxied = true
      ttl     = 1
    }
  }

  # 要件 26.37 / task 26.13: LDAPS の到達手段 (k3s ノードへの NodePort 直指定) と
  # 証明書の対象名を一致させる。kanidm.fickledev.com は Cloudflare Tunnel 経由の HTTPS
  # 専用のホスト名であり同じ名前は使えない (Tunnel の ingress が上書きする) ため、別名を
  # 割り当てて公開 DNS の役割を分離する。Let's Encrypt は private/RFC1918 の IP アドレスに
  # 証明書を発行できない (http-01/tls-alpn-01 のみで DNS-01 不可、かつ検証サーバが
  # 192.168.0.0/16 へ到達できない) ため、IP SAN 方式ではなくホスト名を割り当てる方式を採る。
  # NodePort は kube-proxy が全ノードへ転送するため、この A レコードは特定の「待受ノード」
  # ではなく全 k3s ノードを指す (単一障害点にしない)。ノード入れ替えは local.vms の
  # 該当エントリを更新するだけで反映される。
  kanidm_ldaps_hostname = "ldaps.kanidm.${var.managed_domain}"

  kanidm_ldaps_a_records = {
    for key, vm in local.vms : "kanidm_ldaps_a_${key}" => {
      name    = local.kanidm_ldaps_hostname
      type    = "A"
      content = vm.ip0
      proxied = false
      ttl     = 1
    } if startswith(key, "k3s-")
  }

  other_dns_records = {
    mx_mail = {
      name     = var.managed_domain
      type     = "MX"
      content  = "mail.${var.managed_domain}"
      priority = 9
      proxied  = false
      ttl      = 1
    }
    site_verification_txt = {
      name    = var.managed_domain
      type    = "TXT"
      content = "\"google-site-verification=oZTTqPYWuIahE4Bm9sdfVhESt1KBCM-QiWhBkq_vzD0\""
      proxied = false
      ttl     = 3600
    }
  }

  dns_records = merge(local.vps_a_records, local.vps_aaaa_records, local.cname_records, local.other_dns_records, local.kanidm_ldaps_a_records)
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
