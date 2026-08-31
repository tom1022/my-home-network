# WAF rulesets for the fickledev.com zone.
#
# `.discovery/zone_..._rulesets.json` (task 7.1) shows 4 rulesets, all
# Cloudflare-managed defaults (kind: "managed"/"zone", phases:
# http_request_sanitize, http_request_firewall_managed, ddos_l7,
# http_request_cache_settings) with no custom rules attached. There is
# nothing here that differs from what a fresh zone gets by default, so
# coding them as `cloudflare_ruleset` resources would add state to track
# without changing any actual behavior. Intentionally left undefined.
#
# If custom WAF rules are added later (via dashboard or otherwise), define
# them here as `cloudflare_ruleset` resources and import them into state.
