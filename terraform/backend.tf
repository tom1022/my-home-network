terraform {
  cloud {
    organization = "fickledev"

    workspaces {
      name = "my-home-network"
    }
  }
}
