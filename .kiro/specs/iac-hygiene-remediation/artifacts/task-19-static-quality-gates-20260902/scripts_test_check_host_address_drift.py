#!/usr/bin/env python3
"""Assert-based self-check for check_host_address_drift.py.

Uses synthetic fixtures in a temp dir (never touches the real ansible/ or
terraform/ trees, which other work may be editing concurrently). Run
directly: python scripts/test_check_host_address_drift.py
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_host_address_drift", Path(__file__).parent / "check_host_address_drift.py"
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

AddressEntry = mod.AddressEntry


def _write(dir_path: Path, name: str, content: str) -> Path:
    p = dir_path / name
    p.write_text(content)
    return p


TF_LOCALS = '''
locals {
  vms = {
    "k3s-server" = {
      vmid = 150
      ip0  = "192.168.1.150"
      ip1  = "172.16.0.150"
    }
  }
  containers = {
    "gitea" = {
      vmid = 200
      ip0  = "192.168.1.200"
    }
  }
}
'''

INVENTORY_CONSISTENT = '''
target_hosts:
  hosts:
    k3s-server:
      ansible_host: 192.168.1.150
    gitea:
      ansible_host: 192.168.1.200
'''

INVENTORY_DRIFTED = '''
target_hosts:
  hosts:
    k3s-server:
      ansible_host: 192.168.1.199
    gitea:
      ansible_host: 192.168.1.200
'''


def _collect_with(tmp: Path, inventory_text: str, extra_host=None, extra_ip=None):
    _write(tmp, "locals.tf", TF_LOCALS)
    _write(tmp, "inventory.yml", inventory_text)
    entries = mod.parse_terraform_locals(tmp / "locals.tf") + mod.parse_inventory(tmp / "inventory.yml")
    if extra_host is not None:
        entries = list(entries) + [AddressEntry(extra_host, extra_ip, "fixture", 1, "external_ip")]
    return entries


def test_no_mismatch_when_consistent():
    with tempfile.TemporaryDirectory() as d:
        entries = _collect_with(Path(d), INVENTORY_CONSISTENT)
        assert mod.find_mismatches(entries, excluded=frozenset()) == []


def test_mismatch_when_one_value_diverges():
    with tempfile.TemporaryDirectory() as d:
        entries = _collect_with(Path(d), INVENTORY_DRIFTED)
        mismatches = mod.find_mismatches(entries, excluded=frozenset())
        assert len(mismatches) == 1
        assert mismatches[0].host == "k3s-server"
        assert mismatches[0].role == "external_ip"


def test_excluded_host_suppresses_mismatch():
    with tempfile.TemporaryDirectory() as d:
        entries = _collect_with(Path(d), INVENTORY_DRIFTED)
        mismatches = mod.find_mismatches(entries, excluded=frozenset({"k3s-server"}))
        assert mismatches == [], "excluded host must not be judged even if its values diverge"


def test_broken_terraform_braces_raise_parse_error():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        broken = TF_LOCALS.rstrip().rsplit("}", 1)[0]  # drop the final closing brace
        p = _write(tmp, "locals.tf", broken)
        try:
            mod.parse_terraform_locals(p)
        except mod.ParseError:
            pass
        else:
            raise AssertionError("expected ParseError for unbalanced braces")


def test_ip_outside_host_block_raises_parse_error():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        p = _write(tmp, "locals.tf", 'locals {\n  ip0 = "192.168.1.1"\n}\n')
        try:
            mod.parse_terraform_locals(p)
        except mod.ParseError:
            pass
        else:
            raise AssertionError("expected ParseError for ip0 outside a host block")


def test_malformed_yaml_raises_parse_error():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        p = _write(tmp, "inventory.yml", "target_hosts: [unterminated\n")
        try:
            mod.parse_inventory(p)
        except mod.ParseError:
            pass
        else:
            raise AssertionError("expected ParseError for malformed YAML")


def test_missing_expected_key_raises_parse_error():
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        p = _write(tmp, "inventory.yml", "not_target_hosts: {}\n")
        try:
            mod.parse_inventory(p)
        except mod.ParseError:
            pass
        else:
            raise AssertionError("expected ParseError when target_hosts is missing")


def test_reference_promotes_to_external_ip_on_address_match():
    known = {"192.168.1.150": "k3s-server"}
    ref = AddressEntry("ref:some_var", "192.168.1.150", "fixture", 1, "reference")
    resolved = mod._resolve_role(ref, known)
    assert resolved.host == "k3s-server"
    assert resolved.role == "external_ip"


def test_reference_stays_reference_when_unmatched():
    ref = AddressEntry("ref:some_var", "10.0.0.9", "fixture", 1, "reference")
    resolved = mod._resolve_role(ref, {})
    assert resolved.role == "reference"
    assert resolved.host == "ref:some_var"


def test_static_unmanaged_hosts_registers_vm105_and_vm110():
    # mirakurun-epgstation (VM 110) sits in pbs_backup_excluded_targets, which
    # unmanaged_hosts() never reads (that dict only has a `reason` field, not
    # `source`), and nextcloud (VM 105) has no backup-target entry at all -
    # both previously relied on their address never appearing in any of the
    # 6 parsed files rather than on an explicit exclusion. Task 28.3's
    # correction registers them statically; this locks that registration in.
    assert {"mirakurun-epgstation", "nextcloud"} <= mod.STATIC_UNMANAGED_HOSTS
    assert {"mirakurun-epgstation", "nextcloud"} <= mod.unmanaged_hosts()


def test_static_unmanaged_host_mismatch_suppressed_even_when_addresses_appear():
    # Proves the registration is a real guard, not incidental: even if
    # nextcloud's address were added to two source files with conflicting
    # values, find_mismatches() must not flag it once it's in
    # STATIC_UNMANAGED_HOSTS (unlike an unregistered host with the same
    # conflict, which must still be caught).
    entries = [
        AddressEntry("nextcloud", "10.99.99.1", "fixture-a", 1, "external_ip"),
        AddressEntry("nextcloud", "10.99.99.2", "fixture-b", 1, "external_ip"),
        AddressEntry("some-other-host", "10.99.99.3", "fixture-a", 2, "external_ip"),
        AddressEntry("some-other-host", "10.99.99.4", "fixture-b", 2, "external_ip"),
    ]
    mismatches = mod.find_mismatches(entries, excluded=mod.unmanaged_hosts())
    hosts_flagged = {m.host for m in mismatches}
    assert "nextcloud" not in hosts_flagged
    assert "some-other-host" in hosts_flagged


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
    sys.exit(0)
