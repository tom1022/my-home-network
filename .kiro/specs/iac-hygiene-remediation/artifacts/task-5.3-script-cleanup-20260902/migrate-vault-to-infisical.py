#!/usr/bin/env python3
"""Migrate ansible-vault secrets and the plaintext k3s node token into Infisical.

Read-only against this repository: never deletes or rewrites any source file.
Naming follows .kiro/specs/infisical-cloudflare-iac-refactor/artifacts/secret-mapping.md.
"""
import argparse
import getpass
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent

VAULT_FILES = [
    REPO_ROOT / "ansible/inventory/group_vars/all/vault.yml",
    REPO_ROOT / "ansible/inventory/host_vars/gitea/vault.yml",
    REPO_ROOT / "ansible/inventory/host_vars/pbs/vault.yml",
    REPO_ROOT / "ansible/inventory/host_vars/vps/vault.yml",
    REPO_ROOT / "ansible/inventory/host_vars/k3s-server/argocd_gitea_vault.yml",
]

# secret-mapping.md rule 4 exception: DNS-01 token gets a use-specific name
# instead of the mechanical vault_ prefix strip.
NAME_OVERRIDES = {
    "vault_letsencrypt_cloudflare_api_token": "CLOUDFLARE_DNS01_API_TOKEN",
}

K3S_TOKEN_FILE = "ansible/inventory/host_vars/k3s-server/main.yml"
K3S_TOKEN_VAR = "k3s_node_token"
K3S_TOKEN_KEY = "K3S_NODE_TOKEN"

DEFAULT_ENV = "prod"


def to_infisical_key(vault_var: str) -> str:
    if vault_var in NAME_OVERRIDES:
        return NAME_OVERRIDES[vault_var]
    if not vault_var.startswith("vault_"):
        raise ValueError(f"unexpected non vault_ variable: {vault_var}")
    return vault_var.removeprefix("vault_").upper()


def merge_secrets(secrets: dict, sources: dict, new_items: dict, source_label: str) -> None:
    for key, value in new_items.items():
        if key in secrets:
            raise ValueError(f"duplicate Infisical key {key} from {source_label} (already set by {sources[key]})")
        secrets[key] = value
        sources[key] = source_label


def decrypt_vault_file(path: Path, vault_password: str) -> dict:
    """Decrypt via ansible-vault, passing the password through a 0600 temp file
    (never argv/subprocess command line) so it never shows up in `ps`."""
    fd, pw_path = tempfile.mkstemp(prefix="vaultpw-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(vault_password)
        result = subprocess.run(
            ["ansible-vault", "view", "--vault-password-file", pw_path, str(path)],
            capture_output=True, text=True, check=True,
        )
        return yaml.safe_load(result.stdout) or {}
    finally:
        os.remove(pw_path)


def collect_vault_secrets(vault_password: str) -> tuple[dict, dict]:
    secrets: dict = {}
    sources: dict = {}
    for path in VAULT_FILES:
        if not path.exists():
            print(f"warning: vault file not found, skipping: {path}", file=sys.stderr)
            continue
        data = decrypt_vault_file(path, vault_password)
        try:
            label = str(path.relative_to(REPO_ROOT))
        except ValueError:
            label = str(path)
        converted = {}
        for var, value in data.items():
            if not var.startswith("vault_"):
                print(f"warning: skipping non vault_ key '{var}' in {label}", file=sys.stderr)
                continue
            converted[to_infisical_key(var)] = str(value)
        merge_secrets(secrets, sources, converted, label)
    return secrets, sources


def collect_k3s_token() -> tuple[dict, dict]:
    """Retrieve the plaintext, git-tracked k3s node token from HEAD (not the
    working tree) so migration reflects what's actually committed."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "show", f"HEAD:{K3S_TOKEN_FILE}"],
        capture_output=True, text=True, check=True,
    )
    data = yaml.safe_load(result.stdout) or {}
    if K3S_TOKEN_VAR not in data:
        raise ValueError(f"{K3S_TOKEN_VAR} not found in git HEAD:{K3S_TOKEN_FILE}")
    label = f"git HEAD:{K3S_TOKEN_FILE}"
    return {K3S_TOKEN_KEY: str(data[K3S_TOKEN_VAR])}, {K3S_TOKEN_KEY: label}


def push_to_infisical(secrets: dict, env: str, project_id: str | None = None, token: str | None = None) -> None:
    """Write NAME=VALUE pairs to a temp dotenv file and hand it to
    `infisical secrets set --file`, so secret values never appear in argv/ps
    either (same rationale as the vault password handling above).

    `token`/`project_id` bypass the CLI's globally logged-in session (which may
    belong to a different, unrelated Infisical account on this machine) in
    favor of the machine identity access token passed explicitly."""
    fd, path = tempfile.mkstemp(prefix="infisical-secrets-", suffix=".env")
    env_vars = os.environ.copy()
    if token:
        env_vars["INFISICAL_TOKEN"] = token
    try:
        with os.fdopen(fd, "w") as f:
            for key, value in secrets.items():
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                f.write(f'{key}="{escaped}"\n')
        cmd = ["infisical", "secrets", "set", "--file", path, "--env", env]
        if project_id:
            cmd += ["--projectId", project_id]
        # `secrets set` prints a table with every secret value in plaintext;
        # capture and discard it instead of letting it hit the terminal/logs.
        subprocess.run(cmd, cwd=REPO_ROOT, check=True, env=env_vars, capture_output=True)
    finally:
        os.remove(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="list target Infisical key names only; no values printed, nothing pushed")
    parser.add_argument("--untrack", action="store_true",
                         help="reserved for task 3.4 (untrack migrated vault files); not implemented here")
    parser.add_argument("--env", default=DEFAULT_ENV, help=f"Infisical environment slug (default: {DEFAULT_ENV})")
    parser.add_argument("--project-id", help="Infisical project (workspace) ID; bypasses org ambiguity in the CLI's logged-in session")
    parser.add_argument("--token-file", help="path to a file containing a machine identity access token; bypasses the CLI's globally logged-in session")
    args = parser.parse_args()

    if args.untrack:
        print("--untrack is reserved for task 3.4 and is not implemented by this script.", file=sys.stderr)
        return 1

    if not (REPO_ROOT / ".infisical.json").exists():
        print("error: .infisical.json not found at repo root; run `infisical init` first", file=sys.stderr)
        return 1

    vault_password = getpass.getpass("Vault password: ")
    if not vault_password:
        print("error: empty vault password", file=sys.stderr)
        return 1

    try:
        secrets, sources = collect_vault_secrets(vault_password)
    except subprocess.CalledProcessError:
        print("error: ansible-vault decryption failed; check the vault password", file=sys.stderr)
        return 1
    k3s_items, k3s_sources = collect_k3s_token()
    merge_secrets(secrets, sources, k3s_items, k3s_sources[K3S_TOKEN_KEY])

    if args.dry_run:
        print(f"{len(secrets)} keys would be migrated to Infisical env '{args.env}':")
        for key in sorted(secrets):
            print(f"  {key}  <- {sources[key]}")
        return 0

    token = None
    if args.token_file:
        token = Path(args.token_file).read_text().strip().splitlines()[-1].strip()
    push_to_infisical(secrets, env=args.env, project_id=args.project_id, token=token)
    print(f"migrated {len(secrets)} keys to Infisical env '{args.env}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
