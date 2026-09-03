# Zero Trust tunnels and Access application/policy.

resource "cloudflare_zero_trust_tunnel_cloudflared" "kubernetes" {
  account_id = var.cloudflare_account_id
  name       = "kubernetes-tunnel"
  config_src = "local"
}

# Public hostname routes for the kubernetes-tunnel. Kubernetes-side cloudflared
# runs with a token only (task 7.5); this is the sole place ingress is defined.
resource "cloudflare_zero_trust_tunnel_cloudflared_config" "kubernetes" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.kubernetes.id

  config = {
    ingress = [
      {
        hostname = "crafty.${var.managed_domain}"
        service  = "https://minecraft-bedrock.minecraft-bedrock.svc.cluster.local:8443"
        origin_request = {
          no_tls_verify = true
        }
      },
      {
        # Kanidm terminates TLS itself with a cert-manager-issued certificate
        # for this hostname (task 26.1), so origin_server_name lets cloudflared
        # verify it instead of skipping verification like the crafty route.
        hostname = "kanidm.${var.managed_domain}"
        service  = "https://kanidm.kanidm.svc.cluster.local:8443"
        origin_request = {
          origin_server_name = "kanidm.${var.managed_domain}"
        }
      },
      {
        # ArgoCD already terminates TLS via the live Traefik IngressRoute
        # (ansible/roles/argocd, tls-fickledev-com); routing through the
        # Traefik service with matching SNI reuses that single definition
        # instead of bypassing it with a second direct-to-service route.
        hostname = "argocd.${var.managed_domain}"
        service  = "https://traefik.kube-system.svc.cluster.local:443"
        origin_request = {
          origin_server_name = "argocd.${var.managed_domain}"
        }
      },
      {
        # Gitea (LXC host, task 26.6) has no TLS of its own; the tunnel
        # transport is already encrypted end-to-end to Cloudflare's edge, so
        # the origin scheme does not need to be https (same tolerance as the
        # crafty route above).
        hostname = "gitea.${var.managed_domain}"
        service  = "http://192.168.1.200:3000"
      },
      {
        # oauth2-proxy (forward auth, task 26.35) already terminates TLS via
        # its own Ingress (tls-fickledev-com) behind Traefik, same shape as
        # the argocd route above: route through Traefik with matching SNI
        # instead of a second direct-to-service definition.
        hostname = "forwardauth.${var.managed_domain}"
        service  = "https://traefik.kube-system.svc.cluster.local:443"
        origin_request = {
          origin_server_name = "forwardauth.${var.managed_domain}"
        }
      },
      {
        service = "http_status:404"
      },
    ]
  }
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "guacamole" {
  account_id = var.cloudflare_account_id
  name       = "Guacamole"
  config_src = "cloudflare"
  # status: down at code time (task 7.1 dump). Not the app targeted for
  # removal in this refactor, so it is coded and imported as-is rather
  # than deleted. Confirmed alive and unchanged in task 26.12 (status:
  # healthy, cloudflared runs on an admin PC outside this repo's reach) --
  # do not destroy/replace this resource.
}

# Guacamole's own OIDC extension only implements the implicit flow, which
# Kanidm rejects (task 26.12, requirement 26.27). Guacamole itself is not on
# the cluster or any Proxmox guest -- it binds to localhost on a physically
# separate admin PC on CONSOLE-VLAN, reachable only through this Access
# application's dedicated tunnel. Routing it through the same forward-auth
# chain as other services (argocd-forward-auth-chain) would require opening
# CONSOLE-VLAN -> DMZ-VLAN reachability, breaking the segmentation the
# network is built around. Swapping this identity provider is the only
# change needed: it sits in front of the tunnel already, so no new reachable
# path is introduced.
resource "cloudflare_zero_trust_access_identity_provider" "kanidm" {
  account_id = var.cloudflare_account_id
  name       = "Kanidm"
  type       = "oidc"

  config = {
    # client_id equals the `name` of kanidm_oauth2_basic.guacamole in
    # terraform-kanidm/oauth2_clients.tf -- a separate Terraform state with
    # no automatic linkage, so this must be kept in sync by hand.
    client_id     = "guacamole"
    client_secret = var.kanidm_oidc_guacamole_client_secret

    # auth_url/token_url are shared across all Kanidm OIDC clients; only the
    # certs (jwks) endpoint is per-client (confirmed against the discovery
    # document; kanidm/kanidm docs: "client-specific Issuer URLs" -- the
    # provider's issuer_url config field is SAML-only, not usable here).
    auth_url  = "https://kanidm.${var.managed_domain}/ui/oauth2"
    token_url = "https://kanidm.${var.managed_domain}/oauth2/token"
    certs_url = "https://kanidm.${var.managed_domain}/oauth2/openid/guacamole/public_key.jwk"

    scopes = ["openid", "profile", "email", "groups"]

    # Cloudflare Access does not surface a custom claim to policy evaluation
    # unless the claim name is listed here. Requesting the `groups` scope is
    # not sufficient on its own: without this the `groups` claim never reaches
    # the identity, and any policy matching on it can never succeed.
    claims = ["groups"]

    # Kanidm omits the `email` ID token claim for accounts without a `mail`
    # attribute, which is every account in this environment (task 26.9,
    # confirmed against a real token). preferred_username (SPN form) is the
    # claim Kanidm guarantees on every account, so use it in place of email.
    email_claim_name = "preferred_username"

    pkce_enabled = true
  }
}

resource "cloudflare_zero_trust_access_policy" "guacamole_kanidm" {
  account_id       = var.cloudflare_account_id
  name             = "Kanidm guacamole_access"
  decision         = "allow"
  session_duration = "24h"

  include = [
    {
      # Kanidm's `groups` ID token claim lists each group in both UUID and
      # SPN (name@domain) form (task 26.8, confirmed against a real token);
      # only the SPN form is a stable, human-assignable value to match on.
      oidc = {
        identity_provider_id = cloudflare_zero_trust_access_identity_provider.kanidm.id
        claim_name           = "groups"
        claim_value          = "guacamole_access@kanidm.${var.managed_domain}"
      }
    }
  ]
}

resource "cloudflare_zero_trust_access_application" "guacamole" {
  account_id                 = var.cloudflare_account_id
  name                       = "Guacamole"
  domain                     = "console.${var.managed_domain}"
  type                       = "self_hosted"
  session_duration           = "24h"
  app_launcher_visible       = true
  auto_redirect_to_identity  = true
  allowed_idps               = [cloudflare_zero_trust_access_identity_provider.kanidm.id]
  enable_binding_cookie      = false
  http_only_cookie_attribute = false
  options_preflight_bypass   = false

  policies = [
    {
      id         = cloudflare_zero_trust_access_policy.guacamole_kanidm.id
      precedence = 1
    }
  ]
}
