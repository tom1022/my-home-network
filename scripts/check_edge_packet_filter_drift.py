#!/usr/bin/env python3
"""Reconcile ConoHa's provider-side security groups against the edge host's
declared iptables allow-set (`ansible/roles/vps_proxy/defaults/main.yml`).

Both layers must independently allow a port before traffic reaches the host
(task 12.7 research: the 4190/tcp rule that matched no source, and the
41641/udp rule that didn't exist at all, were each invisible from the other
layer). This script is the repeatable check for that class of divergence.

Desired provider-side state is declared in DESIRED_PROVIDER_RULES below —
this module *is* the single definition of ConoHa's rules, since ConoHa
holds none itself (management-console/API only, no IaC of its own).

ConoHa quirk (confirmed 2026-09 against this tenant): the ready-made
"template" security groups it offers in the console (IPv4v6-Web,
IPv4v6-Mail, ...) return zero rows from GET /v2.0/security-group-rules even
while attached and actively passing traffic (verified empirically via
check-host.net refused-vs-timeout probes in research.md — 80/443/25/587/993
all reach the host despite these groups' API-visible rule list being
empty). Their enforcement is internal to ConoHa and not exposed by this
API, so this script can only record that a template group is attached
(OPAQUE_TEMPLATE_GROUPS) — it cannot declare, diff, or manage their actual
rule content. Custom groups (default, ManageSieve, and any group a human
created rather than picked from ConoHa's presets) behave like ordinary
Neutron security groups and are fully reconcilable.

Exit codes: 0 = no drift, 1 = drift found, 2 = couldn't complete the check
(auth/network failure, credentials missing, or a source file didn't parse).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
VPS_PROXY_DEFAULTS_PATH = (
    REPO_ROOT / "ansible" / "roles" / "vps_proxy" / "defaults" / "main.yml"
)


class ProviderRule(NamedTuple):
    group_name: str
    protocol: str  # "tcp" | "udp"
    port: int
    remote_ipv4: str
    remote_ipv6: str


# The declaration (Requirement: "提供元側の定義をどこに保持するか"). Each
# entry is a rule this script ensures exists, scoped open (0.0.0.0/0 /
# ::/0) to match the host-side iptables allow-set it's reconciled against
# below — narrowing either side to a smaller source range is an operator
# decision this script doesn't make on its own.
DESIRED_PROVIDER_RULES: tuple[ProviderRule, ...] = (
    ProviderRule("default", "udp", 41641, "0.0.0.0/0", "::/0"),
    ProviderRule("ManageSieve", "tcp", 4190, "0.0.0.0/0", "::/0"),
    ProviderRule("IPv4v6-Minecraft-Bedrock", "udp", 19132, "0.0.0.0/0", "::/0"),
)

# ConoHa preset groups attached to this server whose rule content the API
# never returns (see module docstring). `ports` documents which host-side
# ports currently depend on the group for the record; it is not something
# this script verifies or can verify via this API.
OPAQUE_TEMPLATE_GROUPS: dict[str, tuple[str, ...]] = {
    "IPv4v6-Web": ("tcp/80", "tcp/443"),
    "IPv4v6-Mail": ("tcp/25", "tcp/465", "tcp/587", "tcp/993"),
}


class HostAllowSet(NamedTuple):
    tcp_ports: frozenset[int]
    udp_ports: frozenset[int]
    ssh_public_allowed: bool


class ActualRule(NamedTuple):
    group_id: str
    group_name: str
    protocol: Optional[str]
    port: Optional[int]
    ethertype: str  # "IPv4" | "IPv6"
    remote_ip_prefix: Optional[str]
    remote_group_id: Optional[str]


class Divergence(NamedTuple):
    kind: str  # "missing" | "wrong_scope" | "extra" | "provider_only" | "host_only"
    detail: str


class ParseError(Exception):
    pass


# --- host-side declared allow-set -------------------------------------------


def parse_host_allow_set(path: Path = VPS_PROXY_DEFAULTS_PATH) -> HostAllowSet:
    try:
        data = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError) as e:
        raise ParseError(f"{path}: 読み込み/解析に失敗: {e}") from e
    if not isinstance(data, dict):
        raise ParseError(f"{path}: トップレベルがマッピングでない")

    tcp = data.get("vps_proxy_filter_allow_tcp_ports")
    udp = data.get("vps_proxy_filter_allow_udp_ports")
    ssh_flag = data.get("vps_proxy_filter_ssh_public_allowed")
    if not isinstance(tcp, list) or not isinstance(udp, list):
        raise ParseError(
            f"{path}: vps_proxy_filter_allow_{{tcp,udp}}_ports が見つからない"
        )
    if not isinstance(ssh_flag, bool):
        raise ParseError(f"{path}: vps_proxy_filter_ssh_public_allowed が見つからない")

    return HostAllowSet(
        tcp_ports=frozenset(int(p) for p in tcp),
        udp_ports=frozenset(int(p) for p in udp),
        ssh_public_allowed=ssh_flag,
    )


# --- ConoHa API (Keystone v3 + Neutron-compatible network API) -------------


def _http_json(
    url: str, *, method: str = "GET", headers: dict, body: Optional[dict] = None
) -> tuple[int, dict, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            return (
                resp.status,
                dict(resp.headers),
                json.loads(payload) if payload else {},
            )
    except urllib.error.HTTPError as e:
        payload = e.read()
        return e.code, dict(e.headers or {}), (json.loads(payload) if payload else {})


def get_scoped_token(
    region: str, user_id: str, password: str, tenant_id: str
) -> tuple[str, list[dict]]:
    url = f"https://identity.{region}.conoha.io/v3/auth/tokens"
    body = {
        "auth": {
            "identity": {
                "methods": ["password"],
                "password": {"user": {"id": user_id, "password": password}},
            },
            "scope": {"project": {"id": tenant_id}},
        }
    }
    status, headers, resp_body = _http_json(
        url, method="POST", headers={"Content-Type": "application/json"}, body=body
    )
    if status != 201:
        raise RuntimeError(f"認証失敗 (HTTP {status}): {resp_body.get('error')}")
    token = headers.get("X-Subject-Token") or headers.get("x-subject-token")
    if not token:
        raise RuntimeError("認証応答に x-subject-token が無い")
    return token, resp_body["token"]["catalog"]


def network_endpoint(catalog: list[dict]) -> str:
    for svc in catalog:
        if svc.get("type") == "network":
            return svc["endpoints"][0]["url"]
    raise RuntimeError("service catalog に network エンドポイントが無い")


def list_security_groups(endpoint: str, token: str) -> dict[str, str]:
    """name -> id"""
    status, _, body = _http_json(
        f"{endpoint}/v2.0/security-groups", headers={"X-Auth-Token": token}
    )
    if status != 200:
        raise RuntimeError(f"security-groups 取得失敗 (HTTP {status})")
    return {g["name"]: g["id"] for g in body["security_groups"]}


def compute_endpoint(catalog: list[dict]) -> str:
    for svc in catalog:
        if svc.get("type") == "compute":
            return svc["endpoints"][0]["url"]
    raise RuntimeError("service catalog に compute エンドポイントが無い")


def list_server_ids(endpoint: str, token: str) -> list[str]:
    status, _, body = _http_json(f"{endpoint}/servers", headers={"X-Auth-Token": token})
    if status != 200:
        raise RuntimeError(f"servers 取得失敗 (HTTP {status})")
    return [s["id"] for s in body["servers"]]


def list_attached_group_names(endpoint: str, token: str, server_id: str) -> list[str]:
    status, _, body = _http_json(
        f"{endpoint}/servers/{server_id}/os-security-groups",
        headers={"X-Auth-Token": token},
    )
    if status != 200:
        raise RuntimeError(f"os-security-groups 取得失敗 (HTTP {status})")
    return [g["name"] for g in body["security_groups"]]


def list_all_rules(endpoint: str, token: str) -> list[dict]:
    status, _, body = _http_json(
        f"{endpoint}/v2.0/security-group-rules?limit=1000",
        headers={"X-Auth-Token": token},
    )
    if status != 200:
        raise RuntimeError(f"security-group-rules 取得失敗 (HTTP {status})")
    return body["security_group_rules"]


def create_rule(
    endpoint: str,
    token: str,
    group_id: str,
    protocol: str,
    port: int,
    ethertype: str,
    remote_ip_prefix: str,
) -> None:
    body = {
        "security_group_rule": {
            "security_group_id": group_id,
            "direction": "ingress",
            "ethertype": ethertype,
            "protocol": protocol,
            "port_range_min": port,
            "port_range_max": port,
            "remote_ip_prefix": remote_ip_prefix,
        }
    }
    status, _, resp_body = _http_json(
        f"{endpoint}/v2.0/security-group-rules",
        method="POST",
        headers={"X-Auth-Token": token, "Content-Type": "application/json"},
        body=body,
    )
    if status not in (200, 201):
        raise RuntimeError(f"rule 作成失敗 (HTTP {status}): {resp_body}")


# --- comparison (pure, testable without network) ----------------------------


def actual_rules_by_group_name(
    raw_rules: list[dict], group_names_by_id: dict[str, str]
) -> list[ActualRule]:
    out = []
    for r in raw_rules:
        if r.get("direction") != "ingress":
            continue
        gid = r["security_group_id"]
        out.append(
            ActualRule(
                group_id=gid,
                group_name=group_names_by_id.get(gid, gid),
                protocol=r.get("protocol"),
                port=r.get("port_range_min"),
                ethertype=r["ethertype"],
                remote_ip_prefix=r.get("remote_ip_prefix"),
                remote_group_id=r.get("remote_group_id"),
            )
        )
    return out


def compare_provider_rules(
    desired: tuple[ProviderRule, ...],
    actual: list[ActualRule],
    attached_group_names: Optional[frozenset[str]] = None,
) -> list[Divergence]:
    divergences: list[Divergence] = []
    matched_ids: set[tuple[str, str, Optional[int], str]] = set()

    if attached_group_names is not None:
        for d in desired:
            if d.group_name not in attached_group_names:
                divergences.append(
                    Divergence(
                        "missing",
                        f"{d.group_name}: サーバーにこのセキュリティグループが"
                        "アタッチされていない (ルールの有無に関わらず無効)",
                    )
                )

    for d in desired:
        for ethertype, remote in (("IPv4", d.remote_ipv4), ("IPv6", d.remote_ipv6)):
            candidates = [
                a
                for a in actual
                if a.group_name == d.group_name
                and a.protocol == d.protocol
                and a.port == d.port
                and a.ethertype == ethertype
            ]
            exact = [a for a in candidates if a.remote_ip_prefix == remote]
            if exact:
                matched_ids.add((exact[0].group_id, d.protocol, d.port, ethertype))
                continue
            if candidates:
                divergences.append(
                    Divergence(
                        "wrong_scope",
                        f"{d.group_name}: {d.protocol}/{d.port} {ethertype} は存在するが "
                        f"remote_ip_prefix={[c.remote_ip_prefix for c in candidates]} "
                        f"(期待値 {remote!r} に一致しない、到達を許さない可能性)",
                    )
                )
                # already reported as wrong_scope; don't also report it as
                # an unrelated "extra" rule below.
                for c in candidates:
                    matched_ids.add((c.group_id, d.protocol, d.port, ethertype))
            else:
                divergences.append(
                    Divergence(
                        "missing",
                        f"{d.group_name}: {d.protocol}/{d.port} {ethertype} "
                        f"({remote}) のルールが存在しない",
                    )
                )

    # extras: ingress rules with a concrete protocol/port that aren't part
    # of the declared set and aren't the harmless self-referencing
    # (remote_group_id) "allow within this group" rule Neutron adds by
    # default to every new security group.
    desired_group_names = {d.group_name for d in desired}
    for a in actual:
        if a.group_name not in desired_group_names:
            continue
        if a.protocol is None or a.remote_group_id is not None:
            continue
        key = (a.group_id, a.protocol, a.port, a.ethertype)
        if key not in matched_ids:
            divergences.append(
                Divergence(
                    "extra",
                    f"{a.group_name}: {a.protocol}/{a.port} {a.ethertype} "
                    f"remote_ip_prefix={a.remote_ip_prefix} は宣言(DESIRED_PROVIDER_RULES)に無い"
                    " (削除はこのスクリプトの範囲外、要判断)",
                )
            )
    return divergences


def compare_provider_vs_host(
    desired: tuple[ProviderRule, ...], host: HostAllowSet
) -> list[Divergence]:
    """Cross-check the declared provider rules against the host-side
    allow-set. Only covers ports this script actually declares for the
    provider side (DESIRED_PROVIDER_RULES) plus the ports the opaque
    template groups are documented to cover — a port absent from both
    lists here is out of this check's scope, not confirmed-consistent."""
    divergences: list[Divergence] = []
    provider_tcp = {d.port for d in desired if d.protocol == "tcp"}
    provider_udp = {d.port for d in desired if d.protocol == "udp"}
    for ports in OPAQUE_TEMPLATE_GROUPS.values():
        for spec in ports:
            proto, port_s = spec.split("/")
            (provider_tcp if proto == "tcp" else provider_udp).add(int(port_s))

    for port in sorted(provider_tcp - host.tcp_ports):
        divergences.append(
            Divergence(
                "provider_only",
                f"tcp/{port} は提供元側で許可されているがホスト側許可集合に無い",
            )
        )
    for port in sorted(host.tcp_ports - provider_tcp):
        divergences.append(
            Divergence(
                "host_only",
                f"tcp/{port} はホスト側許可集合にあるが提供元側の宣言済みルールに無い",
            )
        )
    for port in sorted(provider_udp - host.udp_ports):
        divergences.append(
            Divergence(
                "provider_only",
                f"udp/{port} は提供元側で許可されているがホスト側許可集合に無い",
            )
        )
    for port in sorted(host.udp_ports - provider_udp):
        divergences.append(
            Divergence(
                "host_only",
                f"udp/{port} はホスト側許可集合にあるが提供元側の宣言済みルールに無い",
            )
        )
    return divergences


# --- CLI ---------------------------------------------------------------------


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        raise RuntimeError(
            f"環境変数 {name} が未設定 (infisical run --env=prod で実行すること)"
        )
    return val


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="missing なルールを ConoHa 側へ作成する (既存ルールの削除/変更は行わない)",
    )
    args = parser.parse_args(argv)

    try:
        host = parse_host_allow_set()
    except ParseError as e:
        print(f"[解析失敗] {e}", file=sys.stderr)
        return 2

    try:
        region = _require_env("CONOHA_REGION")
        user_id = _require_env("CONOHA_API_USER_ID")
        password = _require_env("CONOHA_API_PASSWORD")
        tenant_id = _require_env("CONOHA_TENANT_ID")
        token, catalog = get_scoped_token(region, user_id, password, tenant_id)
        net_endpoint = network_endpoint(catalog)
        group_ids = list_security_groups(net_endpoint, token)
        group_names = {v: k for k, v in group_ids.items()}
        raw_rules = list_all_rules(net_endpoint, token)
        comp_endpoint = compute_endpoint(catalog)
        server_ids = list_server_ids(comp_endpoint, token)
        attached: set[str] = set()
        for sid in server_ids:
            attached |= set(list_attached_group_names(comp_endpoint, token, sid))
    except (RuntimeError, urllib.error.URLError) as e:
        print(f"[取得失敗] {e}", file=sys.stderr)
        return 2

    actual = actual_rules_by_group_name(raw_rules, group_names)
    provider_divergences = compare_provider_rules(
        DESIRED_PROVIDER_RULES, actual, frozenset(attached)
    )
    cross_divergences = compare_provider_vs_host(DESIRED_PROVIDER_RULES, host)
    all_divergences = provider_divergences + cross_divergences

    missing = [d for d in provider_divergences if d.kind == "missing"]
    if args.apply and missing:
        for rule in DESIRED_PROVIDER_RULES:
            gid = group_ids.get(rule.group_name)
            if gid is None:
                print(
                    f"[skip] group {rule.group_name!r} が存在しない、作成できない",
                    file=sys.stderr,
                )
                continue
            for ethertype, remote in (
                ("IPv4", rule.remote_ipv4),
                ("IPv6", rule.remote_ipv6),
            ):
                exists = any(
                    a.group_name == rule.group_name
                    and a.protocol == rule.protocol
                    and a.port == rule.port
                    and a.ethertype == ethertype
                    and a.remote_ip_prefix == remote
                    for a in actual
                )
                if exists:
                    continue
                print(
                    f"[apply] {rule.group_name}: {rule.protocol}/{rule.port} "
                    f"{ethertype} {remote} を作成"
                )
                create_rule(
                    net_endpoint,
                    token,
                    gid,
                    rule.protocol,
                    rule.port,
                    ethertype,
                    remote,
                )
        # re-fetch and re-compare so the report below reflects reality.
        raw_rules = list_all_rules(net_endpoint, token)
        actual = actual_rules_by_group_name(raw_rules, group_names)
        provider_divergences = compare_provider_rules(
            DESIRED_PROVIDER_RULES, actual, frozenset(attached)
        )
        cross_divergences = compare_provider_vs_host(DESIRED_PROVIDER_RULES, host)
        all_divergences = provider_divergences + cross_divergences

    print(f"提供元 (ConoHa) 側の宣言済みルール: {len(DESIRED_PROVIDER_RULES)} 件")
    print(
        f"ホスト側許可集合: tcp={sorted(host.tcp_ports)} udp={sorted(host.udp_ports)}"
    )
    print("opaque template groups (API からは内容が見えない、参考情報):")
    for name, ports in OPAQUE_TEMPLATE_GROUPS.items():
        state = "attached" if name in attached else "NOT attached"
        print(f"  {name} ({state}): {', '.join(ports)}")

    if not all_divergences:
        print("突き合わせ完了: 乖離なし")
        return 0

    print("乖離を検出:", file=sys.stderr)
    for d in all_divergences:
        print(f"  [{d.kind}] {d.detail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
