# Zero Trust tunnels and Access application/policy.

resource "cloudflare_zero_trust_tunnel_cloudflared" "kubernetes" {
  account_id = var.cloudflare_account_id
  name       = "kubernetes-tunnel"
  config_src = "local"
}

# Public hostname routes for the kubernetes-tunnel. Kubernetes-side cloudflared
# runs with a token only; this is the sole place ingress is defined.
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
        # for this hostname, so origin_server_name lets cloudflared
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
        # Gitea (LXC host) has no TLS of its own; the tunnel
        # transport is already encrypted end-to-end to Cloudflare's edge, so
        # the origin scheme does not need to be https (same tolerance as the
        # crafty route above).
        hostname = "gitea.${var.managed_domain}"
        service  = "http://192.168.1.200:3000"
      },
      {
        # oauth2-proxy (forward auth) already terminates TLS via
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
        # devplatform ワークスペース (gitops-apps の autonomous-parallel-dev-platform)。
        # ブランチごとの IngressRoute はクラスタ側 (Workspace Controller) が動的に
        # 生成・削除するため、ここは一括のワイルドカードルートで固定し、ワークスペースの
        # 払い出し・破棄のたびにこのトンネル設定を変更しなくて済むようにする。origin_server_name
        # は個々のワークスペースホスト名と一致させる必要はなく、tls-fickledev-com
        # (*.fickledev.com) の SAN を満たす任意の 1 ラベルであればよい -- Traefik 側の
        # 実際のルーティングは TLS 終端後の HTTP Host ヘッダで決まる。
        #
        # 個別列挙されたホスト名 (上記) 以外の *.fickledev.com 宛はすべてここへ落ち、
        # 遮断点は Cloudflare エッジからクラスタ内の forward-auth-chain (argocd namespace)
        # へ移る -- forward auth を経由しないルーティング設定を Traefik 側に作らない限り、
        # 到達自体は許可されても認証されていないリクエストは forward-auth-chain が拒否する。
        hostname = "*.${var.managed_domain}"
        service  = "https://traefik.kube-system.svc.cluster.local:443"
        origin_request = {
          origin_server_name = "devplatform.${var.managed_domain}"
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
  # cloudflared for this tunnel runs on an admin PC outside this repo's
  # reach, so the resource is imported and kept as-is -- do not
  # destroy/replace it.
}

# Guacamole's own OIDC extension only implements the implicit flow, which
# Kanidm rejects (requirement 26.27). Guacamole itself is not on
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
    # attribute, which is every account in this environment.
    # preferred_username (SPN form) is the
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
      # SPN (name@domain) form; only the SPN form is a stable,
      # human-assignable value to match on.
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

# admin-plane-rebuild: console-pi (Console セグメントの新しい足) 向けの第 2 のトンネル。
# 既存の guacamole トンネル (akishima 上、config_src = "cloudflare" で import 済み) は
# 破棄も置換もしない。新規のトンネルとして追加する。
resource "cloudflare_zero_trust_tunnel_cloudflared" "console" {
  account_id = var.cloudflare_account_id
  name       = "console-pi"
  config_src = "cloudflare"
}

# console_proxy_targets / web_terminal_targets
# (ansible/inventory/group_vars/console/main.yml) の public_hostname / caddy_port を
# 複製したもの。Terraform は Ansible の変数を直接参照できないため、
# cloudflare_zero_trust_access_identity_provider.kanidm の client_id と
# terraform-kanidm/oauth2_clients.tf の kanidm_oauth2_basic.guacamole.name の関係
# (このファイル冒頭付近のコメント) と同じ理由で、手動で同期を保つ。対象を増減した
# ときは両方のファイルを合わせて更新すること。
locals {
  console_ingress_targets = [
    { public_hostname = "opnsense", caddy_port = 8081 },
    { public_hostname = "adguard", caddy_port = 8082 },
    { public_hostname = "status", caddy_port = 8083 },
    { public_hostname = "beszel", caddy_port = 8084 },
    { public_hostname = "opnsense-terminal", caddy_port = 8085 },
    { public_hostname = "console-pi-terminal", caddy_port = 8086 },
  ]
}

# config_src = "cloudflare" のトンネルは ingress を Terraform で管理する
# (cloudflare_zero_trust_tunnel_cloudflared_config)。config_src = "local" とこのリソースは
# 排他のため、上の console トンネルには config_src = "local" を指定しない。
resource "cloudflare_zero_trust_tunnel_cloudflared_config" "console" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.console.id

  config = {
    ingress = concat(
      [
        for target in local.console_ingress_targets : {
          hostname = "${target.public_hostname}.${var.managed_domain}"
          service  = "http://127.0.0.1:${target.caddy_port}"
        }
      ],
      [
        { service = "http_status:404" },
      ]
    )
  }
}

resource "cloudflare_zero_trust_access_policy" "console_kanidm" {
  account_id       = var.cloudflare_account_id
  name             = "Kanidm console_access"
  decision         = "allow"
  session_duration = "24h"

  include = [
    {
      oidc = {
        identity_provider_id = cloudflare_zero_trust_access_identity_provider.kanidm.id
        claim_name           = "groups"
        claim_value          = "console_access@kanidm.${var.managed_domain}"
      }
    }
  ]
}

# 6 ホスト名を 1 つの self_hosted application にまとめる。identity provider は
# guacamole と同じ既存の kanidm をそのまま参照し、新しい識別提供者は作らない。
resource "cloudflare_zero_trust_access_application" "console" {
  account_id                 = var.cloudflare_account_id
  name                       = "Console"
  type                       = "self_hosted"
  session_duration           = "24h"
  app_launcher_visible       = true
  auto_redirect_to_identity  = true
  allowed_idps               = [cloudflare_zero_trust_access_identity_provider.kanidm.id]
  enable_binding_cookie      = false
  http_only_cookie_attribute = false
  options_preflight_bypass   = false

  destinations = [
    for target in local.console_ingress_targets : {
      type = "public"
      uri  = "${target.public_hostname}.${var.managed_domain}"
    }
  ]

  policies = [
    {
      id         = cloudflare_zero_trust_access_policy.console_kanidm.id
      precedence = 1
    }
  ]
}
