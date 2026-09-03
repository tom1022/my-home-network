terraform {
  required_version = ">= 1.10.0"

  required_providers {
    kanidm = {
      source = "seanlatimer/kanidm"
      # 完全一致で固定 (非公式 provider のため、意図しないマイナー更新を自動適用しない)。
      # 供給元・バージョンの記録は README.md を参照。
      version = "0.1.10"
    }
  }
}
