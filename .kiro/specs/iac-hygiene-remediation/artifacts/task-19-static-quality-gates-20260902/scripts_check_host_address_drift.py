#!/usr/bin/env python3
"""Detect drift between duplicate host-address definitions.

Cross-checks terraform/locals.tf against ansible/inventory/ (inventory.yml,
host_vars/pbs, host_vars/vps, group_vars/all, group_vars/k3s). Free-form
sources (.kiro/steering/, gitops/) are not machine-parseable and are out of
scope for this checker; see research.md for the human-maintained inventory
of those.

Read-only. Never modifies any source file. Exit 0 = no drift, non-zero =
drift found or a source file's structure could not be parsed (the two cases
are never conflated: a parse failure must not be reported as "no drift").
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import NamedTuple, Optional, Sequence

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

TF_LOCALS_PATH = REPO_ROOT / "terraform" / "locals.tf"
INVENTORY_PATH = REPO_ROOT / "ansible" / "inventory" / "inventory.yml"
PBS_VARS_PATH = REPO_ROOT / "ansible" / "inventory" / "host_vars" / "pbs" / "main.yml"
VPS_VARS_PATH = REPO_ROOT / "ansible" / "inventory" / "host_vars" / "vps" / "main.yml"
ALL_VARS_PATH = REPO_ROOT / "ansible" / "inventory" / "group_vars" / "all" / "main.yml"
K3S_VARS_PATH = REPO_ROOT / "ansible" / "inventory" / "group_vars" / "k3s" / "main.yml"

# Hosts whose address is defined outside Terraform: Ansible/Terraform can
# disagree about these without it being a drift bug, so they're excluded
# from mismatch judgment (Requirement 7.3) but still collected for the
# inventory. Most of these come from host_vars/pbs `source: external`
# automatically (see unmanaged_hosts()); this set is only for hosts that
# never appear in that list.
#
# mirakurun-epgstation (VM 110) is listed in pbs_backup_excluded_targets,
# not pbs_backup_targets, so unmanaged_hosts() never sees its
# `source: external` marker (that key only exists on pbs_backup_targets
# entries) — without this explicit entry its exclusion depended entirely on
# its address happening not to appear in any of the 6 parsed files.
# nextcloud (VM 105) was decided out of this spec's scope entirely
# (operator decision, 2026-09-02); it has no backup-target entry of any
# kind, so the same accidental-non-appearance risk applied.
STATIC_UNMANAGED_HOSTS: frozenset[str] = frozenset({"mirakurun-epgstation", "nextcloud"})

_TF_GROUP_START = re.compile(r'^\s*(vms|containers)\s*=\s*\{')
_TF_BLOCK_START = re.compile(r'^\s*"([A-Za-z0-9_-]+)"\s*=\s*\{')
_TF_IP = re.compile(r'^\s*(ip0|ip1)\s*=\s*"([^"]+)"')
_URL_IP_RE = re.compile(r'https?://([0-9]{1,3}(?:\.[0-9]{1,3}){3})')

_VPS_UPSTREAM_KEYS = (
    "vps_proxy_upstream_main",
    "vps_proxy_upstream_blog",
    "vps_proxy_upstream_tochiweb",
    "vps_proxy_upstream_mail",
)


class ParseError(Exception):
    """A source file's structure didn't match what this script expects."""


class AddressEntry(NamedTuple):
    host: str
    address: str
    source_file: str
    source_line: int
    role: str  # "external_ip" | "internal_ip" | "reference"


class Mismatch(NamedTuple):
    host: str
    role: str
    entries: Sequence[AddressEntry]


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _compose(path: Path) -> yaml.Node:
    try:
        return yaml.compose(path.read_text(), Loader=yaml.SafeLoader)
    except yaml.YAMLError as e:
        raise ParseError(f"{_rel(path)}: YAML 解析に失敗: {e}") from e


def _map_items(node: yaml.Node, path: Path) -> list:
    if not isinstance(node, yaml.MappingNode):
        raise ParseError(f"{_rel(path)}: マッピングを期待した位置に {type(node).__name__}")
    return node.value


def _map_get(node: yaml.Node, key: str, path: Path) -> Optional[yaml.Node]:
    for k, v in _map_items(node, path):
        if k.value == key:
            return v
    return None


def _line(node: yaml.Node) -> int:
    return node.start_mark.line + 1


def parse_terraform_locals(path: Path) -> list[AddressEntry]:
    text = path.read_text()
    entries: list[AddressEntry] = []
    group: Optional[str] = None
    group_depth: Optional[int] = None
    host: Optional[str] = None
    host_depth: Optional[int] = None
    depth = 0

    for lineno, raw in enumerate(text.splitlines(), 1):
        m_group = _TF_GROUP_START.match(raw)
        m_host = _TF_BLOCK_START.match(raw)
        m_ip = _TF_IP.match(raw)

        if m_ip:
            if host is None:
                raise ParseError(f"{_rel(path)}:{lineno}: ip0/ip1 がホストブロックの外に出現")
            role = "external_ip" if m_ip.group(1) == "ip0" else "internal_ip"
            entries.append(AddressEntry(host, m_ip.group(2), _rel(path), lineno, role))

        if m_group and host is None:
            group, group_depth = m_group.group(1), depth
        elif m_host and group is not None and host is None:
            host, host_depth = m_host.group(1), depth

        depth += raw.count("{") - raw.count("}")
        if depth < 0:
            raise ParseError(f"{_rel(path)}:{lineno}: 閉じ括弧が対応しない")

        if host is not None and depth == host_depth:
            host = None
        if group is not None and depth == group_depth:
            group = None

    if depth != 0:
        raise ParseError(f"{_rel(path)}: 波括弧の対応が取れない (EOF 時点で depth={depth})")
    if not entries:
        raise ParseError(f"{_rel(path)}: ip0/ip1 を含むホストブロックが見つからない")
    return entries


def parse_inventory(path: Path) -> list[AddressEntry]:
    root = _compose(path)
    target_hosts = _map_get(root, "target_hosts", path)
    if target_hosts is None:
        raise ParseError(f"{_rel(path)}: target_hosts が見つからない")
    hosts = _map_get(target_hosts, "hosts", path)
    if hosts is None:
        raise ParseError(f"{_rel(path)}: target_hosts.hosts が見つからない")

    entries = []
    for host_node, attrs_node in _map_items(hosts, path):
        addr_node = _map_get(attrs_node, "ansible_host", path)
        if addr_node is None:
            continue
        entries.append(AddressEntry(host_node.value, addr_node.value, _rel(path), _line(addr_node), "external_ip"))
    if not entries:
        raise ParseError(f"{_rel(path)}: ansible_host を持つホストが1件も無い")
    return entries


def parse_pbs_backup_targets(path: Path) -> tuple[list[AddressEntry], set[str]]:
    root = _compose(path)
    targets = _map_get(root, "pbs_backup_targets", path)
    if targets is None:
        raise ParseError(f"{_rel(path)}: pbs_backup_targets が見つからない")
    if not isinstance(targets, yaml.SequenceNode):
        raise ParseError(f"{_rel(path)}: pbs_backup_targets はシーケンスを期待")

    entries = []
    unmanaged = set()
    for item in targets.value:
        name_node = _map_get(item, "name", path)
        ip_node = _map_get(item, "ip", path)
        if name_node is None or ip_node is None:
            raise ParseError(f"{_rel(path)}:{_line(item)}: name/ip を欠くバックアップ対象")
        entries.append(AddressEntry(name_node.value, ip_node.value, _rel(path), _line(ip_node), "external_ip"))
        source_node = _map_get(item, "source", path)
        if source_node is not None and source_node.value == "external":
            unmanaged.add(name_node.value)
    return entries, unmanaged


def parse_k3s_internal_ips(path: Path) -> list[AddressEntry]:
    root = _compose(path)
    m = _map_get(root, "k3s_internal_ips", path)
    if m is None:
        raise ParseError(f"{_rel(path)}: k3s_internal_ips が見つからない")
    entries = [
        AddressEntry(host_node.value, addr_node.value, _rel(path), _line(addr_node), "internal_ip")
        for host_node, addr_node in _map_items(m, path)
    ]
    if not entries:
        raise ParseError(f"{_rel(path)}: k3s_internal_ips が空")
    return entries


def parse_k3s_group_vars(path: Path) -> list[AddressEntry]:
    root = _compose(path)
    node = _map_get(root, "argocd_gitea_repo_url", path)
    if node is None:
        raise ParseError(f"{_rel(path)}: argocd_gitea_repo_url が見つからない")
    m = _URL_IP_RE.search(node.value)
    if not m:
        raise ParseError(f"{_rel(path)}: argocd_gitea_repo_url から IP を抽出できない: {node.value!r}")
    return [AddressEntry(f"ref:argocd_gitea_repo_url", m.group(1), _rel(path), _line(node), "reference")]


def parse_vps_host_vars(path: Path) -> list[AddressEntry]:
    root = _compose(path)
    entries = []

    for key in _VPS_UPSTREAM_KEYS:
        node = _map_get(root, key, path)
        if node is None:
            continue
        entries.append(AddressEntry(f"ref:{key}", node.value, _rel(path), _line(node), "reference"))

    tcp_upstreams = _map_get(root, "vps_proxy_tcp_upstreams", path)
    if tcp_upstreams is not None:
        if not isinstance(tcp_upstreams, yaml.SequenceNode):
            raise ParseError(f"{_rel(path)}: vps_proxy_tcp_upstreams はシーケンスを期待")
        for group in tcp_upstreams.value:
            members = _map_get(group, "members", path)
            if members is None:
                continue
            for member in members.value:
                host_node = _map_get(member, "host", path)
                if host_node is None:
                    raise ParseError(f"{_rel(path)}:{_line(member)}: members に host が無い")
                entries.append(
                    AddressEntry(f"ref:tcp_upstream:{host_node.value}", host_node.value, _rel(path), _line(host_node), "reference")
                )
    return entries


def _resolve_role(entry: AddressEntry, known: dict[str, str]) -> AddressEntry:
    """Promote an address-only reference to external_ip once its value
    matches a host with a named definition elsewhere (Terraform/inventory/
    pbs target). Unmatched references stay role="reference" so they're
    never silently compared against unrelated hosts."""
    matched = known.get(entry.address)
    if matched is None:
        return entry
    return entry._replace(host=matched, role="external_ip")


def collect() -> Sequence[AddressEntry]:
    tf_entries = parse_terraform_locals(TF_LOCALS_PATH)
    inv_entries = parse_inventory(INVENTORY_PATH)
    pbs_entries, _unmanaged = parse_pbs_backup_targets(PBS_VARS_PATH)
    internal_entries = parse_k3s_internal_ips(ALL_VARS_PATH)
    gitea_ref = parse_k3s_group_vars(K3S_VARS_PATH)
    vps_entries = parse_vps_host_vars(VPS_VARS_PATH)

    known: dict[str, str] = {}
    for e in tf_entries + inv_entries + pbs_entries:
        known.setdefault(e.address, e.host)

    resolved = [_resolve_role(e, known) for e in gitea_ref + vps_entries]

    return tf_entries + inv_entries + pbs_entries + internal_entries + resolved


def unmanaged_hosts() -> frozenset[str]:
    _, dynamic = parse_pbs_backup_targets(PBS_VARS_PATH)
    return frozenset(dynamic) | STATIC_UNMANAGED_HOSTS


def find_mismatches(entries: Sequence[AddressEntry], excluded: Optional[frozenset[str]] = None) -> Sequence[Mismatch]:
    if excluded is None:
        excluded = unmanaged_hosts()

    groups: dict[tuple[str, str], list[AddressEntry]] = {}
    for e in entries:
        if e.host in excluded:
            continue
        groups.setdefault((e.host, e.role), []).append(e)

    mismatches = []
    for (host, role), group_entries in groups.items():
        if len({e.address for e in group_entries}) > 1:
            mismatches.append(Mismatch(host, role, group_entries))
    return mismatches


def main() -> int:
    try:
        entries = collect()
    except ParseError as e:
        print(f"[解析失敗] {e}", file=sys.stderr)
        return 2

    mismatches = find_mismatches(entries)
    if not mismatches:
        print(f"整合: {len(entries)} 件のアドレス定義を確認、不整合なし")
        return 0

    print("不整合を検出:", file=sys.stderr)
    for m in mismatches:
        print(f"  host={m.host} role={m.role}", file=sys.stderr)
        for e in m.entries:
            print(f"    {e.source_file}:{e.source_line} = {e.address}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
