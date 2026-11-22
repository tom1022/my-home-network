#!/usr/bin/env python3
"""Mirror Kanidm RADIUS secrets of a group's members into Samba's tdbsam.

Dependency direction: types -> plan (pure) -> I/O -> main.
"""

from __future__ import annotations

import grp
import http.client
import json
import os
import pwd
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

HTTP_TIMEOUT = 10
STATE_PATH = Path("/var/lib/nas-smb-sync/managed")
PASSWD_PATH = Path("/etc/passwd")
RADIUS_GROUP = "idm_radius_servers"
# Names reach tdbsam via argv and Kanidm URLs; a leading "-" would be read as an
# smbpasswd / pdbedit option, and anything else is not a Kanidm name we can
# safely hand over.
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


@dataclass(frozen=True)
class Member:
    name: str
    uuid: str


class SecretState(Enum):
    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Desired:
    member: Member
    state: SecretState
    nt_hash: str | None
    resolvable: bool
    reason: str = field(default="", compare=False)


class Action(Enum):
    ADD = "add"
    UPDATE = "update"
    ADOPT = "adopt"
    DELETE = "delete"
    SKIP = "skip"
    HOLD = "hold"


@dataclass(frozen=True)
class Step:
    name: str
    action: Action
    reason: str = field(default="", compare=False)


class FatalSyncError(Exception):
    """Whole-run failure during collection; tdbsam must not be touched."""


class ApplyError(Exception):
    """A single smbpasswd / pdbedit invocation failed."""


def _decide(
    d: Desired,
    current_hashes: dict[str, str],
    managed: set[str],
    local_users: set[str],
) -> tuple[Action, str]:
    name = d.member.name
    if name in local_users:
        return Action.SKIP, "local user"
    if d.state is SecretState.UNKNOWN:
        return Action.HOLD, d.reason
    if d.state is SecretState.ABSENT or not d.resolvable:
        if name in managed:
            return Action.DELETE, ""
        return Action.SKIP, "not issued" if d.state is SecretState.ABSENT else (
            "unresolvable"
        )
    if name not in current_hashes:
        return Action.ADD, ""
    if current_hashes[name] != d.nt_hash:
        return Action.UPDATE, ""
    if name in managed:
        return Action.SKIP, "up to date"
    return Action.ADOPT, ""


def build_plan(
    desired: list[Desired],
    current_hashes: dict[str, str],
    managed: set[str],
    local_users: set[str],
) -> list[Step]:
    steps = [
        Step(d.member.name, *_decide(d, current_hashes, managed, local_users))
        for d in desired
    ]
    seen = {d.member.name for d in desired}
    for name in sorted(managed - seen):
        # Local users are never deleted, even if a stale state file lists one.
        if name in local_users:
            steps.append(Step(name, Action.SKIP, "local user"))
        else:
            steps.append(Step(name, Action.DELETE))
    return steps


class HttpStatusError(Exception):
    def __init__(self, status: int):
        super().__init__(f"HTTP {status}")
        self.status = status


class KanidmClient:
    def __init__(self, base_url: str, token: str, opener=urllib.request.urlopen):
        self._base = base_url.rstrip("/")
        self._token = token
        self._opener = opener

    def request(self, method: str, path: str, body=None):
        """Return parsed JSON. HTTP errors raise HttpStatusError; transport
        and decoding failures raise FatalSyncError."""
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self._base + path, data=data, method=method)
        # The token is deliberately kept out of every exception message.
        # Unredirected so a redirect cannot carry the token to another host.
        req.add_unredirected_header("Authorization", f"Bearer {self._token}")
        # Cloudflare in front of kanidm rejects urllib's default UA with 403 (1010).
        req.add_header("User-Agent", "nas-smb-sync")
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with self._opener(req, timeout=HTTP_TIMEOUT) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            raise HttpStatusError(e.code) from None
        except (OSError, ValueError, http.client.HTTPException) as e:
            # URLError (incl. TLS failures) and timeouts are OSError.
            raise FatalSyncError(
                f"kanidm unreachable or bad response: {type(e).__name__}"
            ) from None

    def call(self, method: str, path: str, body=None):
        """Like request, but every HTTP error is a whole-run failure."""
        try:
            return self.request(method, path, body)
        except HttpStatusError as e:
            raise FatalSyncError(f"{method} {path}: HTTP {e.status}") from None


def _attr(entry, key: str) -> str:
    try:
        v = entry["attrs"][key]
    except (KeyError, TypeError):
        raise FatalSyncError(f"malformed entry: missing {key}") from None
    if not (isinstance(v, list) and v and isinstance(v[0], str)):
        raise FatalSyncError(f"malformed entry: bad {key}")
    return v[0]


def ensure_radius_server(client: KanidmClient) -> None:
    """`_radius` returns null both for "not issued" and "ACP hides it", so a
    lost membership must stop the run rather than read as "delete everyone"."""
    body = client.call("GET", "/v1/self")
    try:
        memberof = body["youare"]["attrs"]["memberof"]
    except (KeyError, TypeError):
        raise FatalSyncError("malformed /v1/self response") from None
    if not isinstance(memberof, list):
        raise FatalSyncError("malformed /v1/self response")
    names = {m.split("@")[0] for m in memberof if isinstance(m, str)}
    if RADIUS_GROUP not in names:
        raise FatalSyncError(f"token is not a member of {RADIUS_GROUP}")


def get_group_uuid(client: KanidmClient, group: str) -> str:
    body = client.call("GET", "/v1/group/" + urllib.parse.quote(group, safe=""))
    if body is None:
        raise FatalSyncError(f"group {group} does not exist")
    return _attr(body, "uuid")


def search_members(client: KanidmClient, group_uuid: str) -> list[Member]:
    body = client.call(
        "POST",
        "/v1/raw/search",
        {
            "filter": {
                "and": [
                    {"eq": ["class", "person"]},
                    {"eq": ["class", "posixaccount"]},
                    {"eq": ["memberof", group_uuid]},
                ]
            }
        },
    )
    entries = body.get("entries") if isinstance(body, dict) else None
    if not isinstance(entries, list):
        raise FatalSyncError("malformed search response")
    return [Member(_attr(e, "name"), _attr(e, "uuid")) for e in entries]


def fetch_secret(
    client: KanidmClient, member: Member
) -> tuple[SecretState, str | None, str]:
    """Returns (state, secret, reason); reason is set only for UNKNOWN."""
    if not NAME_RE.match(member.name):
        return SecretState.UNKNOWN, None, "invalid name"

    path = f"/v1/person/{urllib.parse.quote(member.uuid, safe='')}/_radius"
    try:
        body = client.request("GET", path)
    except HttpStatusError as e:
        if e.status in (401, 403):
            raise FatalSyncError(f"GET _radius: HTTP {e.status}") from None
        return SecretState.UNKNOWN, None, f"HTTP {e.status}"
    if body is None:
        return SecretState.ABSENT, None, ""
    if isinstance(body, str):
        return SecretState.PRESENT, body, ""
    raise FatalSyncError("malformed _radius response")


def nt_hash(secret: str, run=subprocess.run) -> str:
    """Python's hashlib cannot do MD4 on OpenSSL 3, so shell out; the secret
    goes via stdin so it never appears in argv."""
    r = run(
        ["openssl", "dgst", "-md4", "-provider", "legacy"],
        input=secret.encode("utf-16-le"),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if r.returncode != 0:
        raise FatalSyncError("openssl md4 failed")
    out = r.stdout.decode().strip()
    return out.rsplit("= ", 1)[-1].strip().upper()


class Tdbsam:
    def __init__(self, run=subprocess.run):
        self._run = run

    def _exec(self, cmd: list[str], stdin: bytes | None = None, what: str = ""):
        r = self._run(
            cmd,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        if r.returncode != 0:
            raise ApplyError(what or cmd[0])
        return r.stdout

    def list_hashes(self) -> dict[str, str]:
        out = self._exec(["pdbedit", "-L", "-w"], what="pdbedit -L")
        hashes = {}
        for line in out.decode().splitlines():
            parts = line.split(":")
            if len(parts) >= 4:
                hashes[parts[0]] = parts[3].upper()
        return hashes

    def set_password(self, name: str, secret: str) -> None:
        self._exec(
            ["smbpasswd", "-a", "-s", name],
            stdin=f"{secret}\n{secret}\n".encode(),
            what="smbpasswd",
        )

    def delete(self, name: str) -> None:
        self._exec(["pdbedit", "-x", "-u", name], what="pdbedit -x")


def load_managed(path: Path) -> set[str]:
    try:
        return set(path.read_text().split())
    except FileNotFoundError:
        return set()


def save_managed(path: Path, names: set[str]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("".join(f"{n}\n" for n in sorted(names)))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    # Without this the rename itself can be lost on power failure.
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def read_local_users(path: Path) -> set[str]:
    return {
        line.split(":", 1)[0] for line in path.read_text().splitlines() if line.strip()
    }


def resolve_nss(name: str) -> bool:
    try:
        pwd.getpwnam(name)
    except KeyError:
        return False
    return True


def lookup_group_nss(name: str) -> None:
    grp.getgrnam(name)


def collect(
    client: KanidmClient, group: str, resolve, hasher
) -> tuple[list[Desired], dict[str, str]]:
    ensure_radius_server(client)
    members = search_members(client, get_group_uuid(client, group))
    desired = []
    secrets: dict[str, str] = {}
    for m in members:
        state, secret, reason = fetch_secret(client, m)
        h = None
        if state is SecretState.PRESENT:
            secrets[m.name] = secret
            h = hasher(secret)
        desired.append(Desired(m, state, h, resolve(m.name), reason))
    return desired, secrets


def apply_plan(
    steps: list[Step],
    current_hashes: dict[str, str],
    secrets: dict[str, str],
    tdb,
    managed: set[str],
    state_path: Path,
) -> int:
    """Returns the number of failures; each step is independent."""
    failures = 0
    for step in steps:
        name, action = step.name, step.action
        why = f" ({step.reason})" if step.reason else ""
        print(f"{action.value} {name}{why}", flush=True)
        try:
            if action in (Action.ADD, Action.UPDATE, Action.ADOPT):
                # Recorded first so a crash can only widen, never narrow,
                # what the job believes it owns.
                managed.add(name)
                save_managed(state_path, managed)
                if action is not Action.ADOPT:
                    tdb.set_password(name, secrets[name])
            elif action is Action.DELETE:
                # An entry already gone (failed registration, manual removal)
                # would make pdbedit -x fail every cycle.
                if name in current_hashes:
                    tdb.delete(name)
                managed.discard(name)
                save_managed(state_path, managed)
            elif action is Action.HOLD:
                failures += 1
        except (ApplyError, OSError) as e:
            failures += 1
            print(f"failed {name}: {action.value} ({e})", file=sys.stderr, flush=True)
    return failures


def run(
    env,
    tdb,
    state_path: Path = STATE_PATH,
    passwd_path: Path = PASSWD_PATH,
    resolve=resolve_nss,
    group_lookup=lookup_group_nss,
    hasher=nt_hash,
    opener=urllib.request.urlopen,
) -> int:
    try:
        url, token, group = (
            env["KANIDM_URL"],
            env["KANIDM_TOKEN"],
            env["NAS_SMB_SYNC_GROUP"],
        )
    except KeyError as e:
        print(f"fatal: missing env {e.args[0]}", file=sys.stderr)
        return 1
    if not url.startswith("https://"):
        print("fatal: KANIDM_URL must start with https://", file=sys.stderr)
        return 1
    try:
        # With kanidm-unixd down every member looks unresolvable, which the
        # plan would turn into deleting everyone in managed.
        group_lookup(group)
    except KeyError:
        print(f"fatal: group {group} is not resolvable via NSS", file=sys.stderr)
        return 1
    try:
        desired, secrets = collect(
            KanidmClient(url, token, opener=opener), group, resolve, hasher
        )
    except FatalSyncError as e:
        print(f"fatal: {e}", file=sys.stderr)
        return 1
    try:
        managed = load_managed(state_path)
        current = tdb.list_hashes()
        steps = build_plan(
            desired,
            current,
            managed,
            read_local_users(passwd_path),
        )
    except (ApplyError, OSError) as e:
        print(f"fatal: cannot read local state ({e})", file=sys.stderr)
        return 1
    return 1 if apply_plan(steps, current, secrets, tdb, managed, state_path) else 0


def main() -> int:
    return run(os.environ, Tdbsam())


if __name__ == "__main__":
    sys.exit(main())
