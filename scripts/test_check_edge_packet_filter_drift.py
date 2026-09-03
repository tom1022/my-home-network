#!/usr/bin/env python3
"""Assert-based self-check for check_edge_packet_filter_drift.py.

All comparison logic is pure (no network) so it's tested directly against
synthetic fixtures. Run directly: python scripts/test_check_edge_packet_filter_drift.py
"""

import importlib.util
import sys
import tempfile
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_edge_packet_filter_drift",
    Path(__file__).parent / "check_edge_packet_filter_drift.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

ProviderRule = mod.ProviderRule
ActualRule = mod.ActualRule
HostAllowSet = mod.HostAllowSet

DESIRED = (ProviderRule("default", "udp", 41641, "0.0.0.0/0", "::/0"),)


def _write(dir_path: Path, name: str, content: str) -> Path:
    p = dir_path / name
    p.write_text(content)
    return p


DEFAULTS_YAML = """
vps_proxy_filter_allow_tcp_ports:
  - 25
  - 4190
vps_proxy_filter_allow_udp_ports:
  - 19132
  - 41641
vps_proxy_filter_ssh_public_allowed: false
"""


def test_parse_host_allow_set_reads_ports_and_flag():
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td), "main.yml", DEFAULTS_YAML)
        result = mod.parse_host_allow_set(path)
        assert result.tcp_ports == frozenset({25, 4190})
        assert result.udp_ports == frozenset({19132, 41641})
        assert result.ssh_public_allowed is False


def test_parse_host_allow_set_missing_key_raises_parse_error():
    with tempfile.TemporaryDirectory() as td:
        path = _write(Path(td), "main.yml", "some_other_key: 1\n")
        try:
            mod.parse_host_allow_set(path)
            assert False, "expected ParseError"
        except mod.ParseError:
            pass


def test_compare_provider_rules_all_present_is_clean():
    actual = [
        ActualRule("gid1", "default", "udp", 41641, "IPv4", "0.0.0.0/0", None),
        ActualRule("gid1", "default", "udp", 41641, "IPv6", "::/0", None),
    ]
    divergences = mod.compare_provider_rules(DESIRED, actual, frozenset({"default"}))
    assert divergences == []


def test_compare_provider_rules_missing_rule_detected():
    divergences = mod.compare_provider_rules(DESIRED, [], frozenset({"default"}))
    kinds = {d.kind for d in divergences}
    assert kinds == {"missing"}
    assert len(divergences) == 2  # IPv4 + IPv6


def test_compare_provider_rules_wrong_scope_detected():
    # the real-world bug this task fixed: a /32 that matches nobody.
    actual = [
        ActualRule("gid1", "default", "udp", 41641, "IPv4", "0.0.0.0/32", None),
        ActualRule("gid1", "default", "udp", 41641, "IPv6", "::/0", None),
    ]
    divergences = mod.compare_provider_rules(DESIRED, actual, frozenset({"default"}))
    assert len(divergences) == 1
    assert divergences[0].kind == "wrong_scope"


def test_compare_provider_rules_group_not_attached_is_missing():
    actual = [
        ActualRule("gid1", "default", "udp", 41641, "IPv4", "0.0.0.0/0", None),
        ActualRule("gid1", "default", "udp", 41641, "IPv6", "::/0", None),
    ]
    divergences = mod.compare_provider_rules(DESIRED, actual, frozenset())
    kinds = [d.kind for d in divergences]
    assert "missing" in kinds
    assert any("アタッチされていない" in d.detail for d in divergences)


def test_compare_provider_rules_extra_rule_reported_not_deleted():
    actual = [
        ActualRule("gid1", "default", "udp", 41641, "IPv4", "0.0.0.0/0", None),
        ActualRule("gid1", "default", "udp", 41641, "IPv6", "::/0", None),
        ActualRule("gid1", "default", "tcp", 9999, "IPv4", "0.0.0.0/0", None),
    ]
    divergences = mod.compare_provider_rules(DESIRED, actual, frozenset({"default"}))
    assert len(divergences) == 1
    assert divergences[0].kind == "extra"


def test_compare_provider_rules_self_referencing_rule_ignored():
    # Neutron's default "allow within this group" rule (remote_group_id set,
    # protocol None) must never be reported as an extra.
    actual = [
        ActualRule("gid1", "default", "udp", 41641, "IPv4", "0.0.0.0/0", None),
        ActualRule("gid1", "default", "udp", 41641, "IPv6", "::/0", None),
        ActualRule("gid1", "default", None, None, "IPv4", None, "gid1"),
    ]
    divergences = mod.compare_provider_rules(DESIRED, actual, frozenset({"default"}))
    assert divergences == []


def test_compare_provider_vs_host_finds_both_directions():
    host = HostAllowSet(
        tcp_ports=frozenset({4190}), udp_ports=frozenset(), ssh_public_allowed=False
    )
    desired = (ProviderRule("default", "udp", 41641, "0.0.0.0/0", "::/0"),)
    divergences = mod.compare_provider_vs_host(desired, host)
    kinds = {(d.kind, d.detail) for d in divergences}
    assert (
        "provider_only",
        "udp/41641 は提供元側で許可されているがホスト側許可集合に無い",
    ) in kinds
    assert (
        "host_only",
        "tcp/4190 はホスト側許可集合にあるが提供元側の宣言済みルールに無い",
    ) in kinds


def test_compare_provider_vs_host_clean_when_aligned():
    host = HostAllowSet(
        tcp_ports=frozenset({80, 443, 25, 465, 587, 993, 4190}),
        udp_ports=frozenset({19132, 41641}),
        ssh_public_allowed=False,
    )
    divergences = mod.compare_provider_vs_host(mod.DESIRED_PROVIDER_RULES, host)
    assert divergences == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"ok  {name}")
    print("all tests passed")
    sys.exit(0)
