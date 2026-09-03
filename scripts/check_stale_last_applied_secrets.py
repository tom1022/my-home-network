#!/usr/bin/env python3
"""Detect Secret objects that still carry kubectl.kubernetes.io/last-applied-configuration.

A Secret created via `kubectl apply` stores the entire manifest it was
applied with -- key material included -- in this annotation. If the Secret's
`.data` is later rotated by something other than `kubectl apply` (e.g. a
cert-manager renewal), the annotation is never refreshed: it keeps the
original key readable under the same RBAC as the live Secret, indefinitely,
as a second undocumented path to a credential that may otherwise be
considered rotated. Scope is Secret objects specifically (not every
resource kind) because this is a key-material concern, not a generic
last-applied-configuration audit.

Read-only. Never prints annotation content -- only namespace, name, and the
annotation's byte length, which is enough to prove presence/absence without
reproducing the secret it might contain.

Run directly: uv run python scripts/check_stale_last_applied_secrets.py
Exit 0 = no Secret carries the annotation. Exit 1 = at least one does.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any, Iterable, NamedTuple

LAC_ANNOTATION = "kubectl.kubernetes.io/last-applied-configuration"


class Finding(NamedTuple):
    namespace: str
    name: str
    byte_length: int


def fetch_secrets() -> list[dict[str, Any]]:
    out = subprocess.run(
        ["kubectl", "get", "secrets", "--all-namespaces", "-o", "json"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return json.loads(out)["items"]


def scan(items: Iterable[dict[str, Any]]) -> list[Finding]:
    findings = []
    for item in items:
        annotations = item.get("metadata", {}).get("annotations") or {}
        value = annotations.get(LAC_ANNOTATION)
        if value is not None:
            findings.append(
                Finding(
                    namespace=item["metadata"]["namespace"],
                    name=item["metadata"]["name"],
                    byte_length=len(value.encode("utf-8")),
                )
            )
    return findings


def main() -> int:
    findings = scan(fetch_secrets())
    if not findings:
        print("OK: 全名前空間の Secret に last-applied-configuration の残存なし")
        return 0

    print(f"検出: last-applied-configuration を保持する Secret が {len(findings)} 件 (内容は非表示)")
    for f in findings:
        print(f"  {f.namespace}/{f.name}: {f.byte_length} bytes")
    return 1


if __name__ == "__main__":
    sys.exit(main())
