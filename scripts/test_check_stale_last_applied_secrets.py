#!/usr/bin/env python3
"""Assert-based self-check for check_stale_last_applied_secrets.py.

scan() is pure (no kubectl call) so it's tested against synthetic fixtures.
Run directly: python scripts/test_check_stale_last_applied_secrets.py
"""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "check_stale_last_applied_secrets",
    Path(__file__).parent / "check_stale_last_applied_secrets.py",
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

scan = mod.scan
LAC_ANNOTATION = mod.LAC_ANNOTATION


def _secret(namespace: str, name: str, annotations: dict | None = None) -> dict:
    return {
        "metadata": {
            "namespace": namespace,
            "name": name,
            "annotations": annotations,
        }
    }


def test_clean_cluster_reports_nothing() -> None:
    items = [
        _secret("cert-manager", "tls-fickledev-com", {"other": "x"}),
        _secret("argocd", "tls-fickledev-com", None),
    ]
    assert scan(items) == []


def test_finds_annotation_and_reports_length_not_content() -> None:
    secret_payload = '{"data":{"tls.key":"super-secret-base64"}}'
    items = [
        _secret("cert-manager", "wildcard-x", {LAC_ANNOTATION: secret_payload}),
    ]
    findings = scan(items)
    assert len(findings) == 1
    f = findings[0]
    assert f.namespace == "cert-manager"
    assert f.name == "wildcard-x"
    assert f.byte_length == len(secret_payload.encode("utf-8"))
    # The finding tuple must never carry the raw value anywhere.
    assert "super-secret-base64" not in repr(f)


def test_multiple_namespaces_all_reported() -> None:
    items = [
        _secret("ns-a", "s1", {LAC_ANNOTATION: "x"}),
        _secret("ns-b", "s2", {LAC_ANNOTATION: "yy"}),
        _secret("ns-c", "s3", {"unrelated": "z"}),
    ]
    findings = scan(items)
    assert {(f.namespace, f.name) for f in findings} == {("ns-a", "s1"), ("ns-b", "s2")}


if __name__ == "__main__":
    test_clean_cluster_reports_nothing()
    test_finds_annotation_and_reports_length_not_content()
    test_multiple_namespaces_all_reported()
    print("OK")
