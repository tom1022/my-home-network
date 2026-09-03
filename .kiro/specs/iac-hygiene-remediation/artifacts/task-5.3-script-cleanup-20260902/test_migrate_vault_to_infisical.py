#!/usr/bin/env python3
"""Assert-based self-check for migrate-vault-to-infisical.py's pure logic
(naming conversion + duplicate-key detection). No network/vault/infisical
calls. Run directly: python scripts/test_migrate_vault_to_infisical.py
"""
import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "migrate_vault_to_infisical", Path(__file__).parent / "migrate-vault-to-infisical.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_mechanical_conversion():
    assert mod.to_infisical_key("vault_gitea_db_password") == "GITEA_DB_PASSWORD"
    assert mod.to_infisical_key("vault_proxmox_pbs_fingerprint") == "PROXMOX_PBS_FINGERPRINT"


def test_dns01_override():
    assert mod.to_infisical_key("vault_letsencrypt_cloudflare_api_token") == "CLOUDFLARE_DNS01_API_TOKEN"


def test_rejects_non_vault_prefixed():
    try:
        mod.to_infisical_key("k3s_node_token")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for non vault_ prefixed input")


def test_merge_secrets_detects_duplicate():
    secrets, sources = {}, {}
    mod.merge_secrets(secrets, sources, {"GITEA_DB_PASSWORD": "a"}, "file1")
    try:
        mod.merge_secrets(secrets, sources, {"GITEA_DB_PASSWORD": "b"}, "file2")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on duplicate key across sources")
    assert secrets == {"GITEA_DB_PASSWORD": "a"}, "value must not be overwritten by the failed merge"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
    sys.exit(0)
