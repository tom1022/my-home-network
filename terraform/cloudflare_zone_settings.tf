# Zone settings for the fickledev.com zone.
#
# Only settings the API reports as `editable: true` are managed here.
# Non-editable settings (advanced_ddos, http2, long_lived_grpc, mirage,
# origin_error_page_pass_thru, polish, prefetch_preload, proxy_read_timeout,
# response_buffering, sort_query_string_for_cache, true_client_ip_header,
# webp) are plan-only/read-only on the Free plan and would either error on
# apply or produce a permanent diff, so they are intentionally omitted.

locals {
  zone_settings = {
    "0rtt"                    = "off"
    always_online             = "on"
    always_use_https          = "on"
    automatic_https_rewrites  = "on"
    brotli                    = "on"
    browser_cache_ttl         = 14400
    browser_check             = "on"
    cache_level               = "aggressive"
    challenge_ttl             = 1800
    ciphers                   = []
    cname_flattening          = "flatten_at_root"
    development_mode          = "off"
    early_hints               = "off"
    ech                       = "on"
    edge_cache_ttl            = 7200
    email_obfuscation         = "on"
    filter_logs_to_cloudflare = "off"
    hotlink_protection        = "off"
    http3                     = "on"
    ip_geolocation            = "on"
    ipv6                      = "on"
    log_to_cloudflare         = "on"
    max_upload                = 100
    min_tls_version           = "1.3"
    minify = {
      css  = "off"
      html = "off"
      js   = "off"
    }
    mobile_redirect = {
      status           = "off"
      mobile_subdomain = null
      strip_uri        = false
    }
    opportunistic_encryption = "on"
    opportunistic_onion      = "on"
    orange_to_orange         = "off"
    pq_keyex                 = "on"
    privacy_pass             = "on"
    pseudo_ipv4              = "off"
    replace_insecure_js      = "on"
    rocket_loader            = "off"
    security_header = {
      strict_transport_security = {
        enabled            = true
        max_age            = 15552000
        include_subdomains = false
        preload            = false
        nosniff            = true
      }
    }
    security_level      = "medium"
    server_side_exclude = "on"
    ssl                 = "strict"
    tls_1_2_only        = "off"
    tls_1_3             = "on"
    tls_client_auth     = "off"
    visitor_ip          = "on"
    waf                 = "off"
    websockets          = "on"
  }
}

resource "cloudflare_zone_setting" "this" {
  for_each = local.zone_settings

  zone_id    = var.cloudflare_zone_id
  setting_id = each.key
  value      = each.value
}
