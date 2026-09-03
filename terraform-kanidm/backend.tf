terraform {
  cloud {
    organization = "fickledev"

    workspaces {
      # 既存の my-home-network ワークスペース (Proxmox/Cloudflare) とは意図的に分離。
      # 理由は README.md の「state の分離」を参照。
      name = "kanidm-identity"
    }
  }
}
