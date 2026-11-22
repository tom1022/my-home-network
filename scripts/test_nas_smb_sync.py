"""Unit tests for ansible/roles/nas/files/nas-smb-sync.py.

The script's filename contains a hyphen, so it is loaded by path. Kanidm,
tdbsam (smbpasswd / pdbedit), openssl and NSS are all replaced by fakes.
"""

import importlib.util
import io
import json
import socket
import sys
import urllib.error
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "ansible/roles/nas/files/nas-smb-sync.py"
spec = importlib.util.spec_from_file_location("nas_smb_sync", SCRIPT)
mod = importlib.util.module_from_spec(spec)
# dataclasses resolves string annotations through sys.modules.
sys.modules["nas_smb_sync"] = mod
spec.loader.exec_module(mod)

Member = mod.Member
Desired = mod.Desired
SecretState = mod.SecretState
Action = mod.Action
Step = mod.Step
build_plan = mod.build_plan

H1 = "A" * 32
H2 = "B" * 32


def desired(name, state=SecretState.PRESENT, nt_hash=H1, resolvable=True):
    return Desired(Member(name, f"uuid-{name}"), state, nt_hash, resolvable)


def plan(desired_list, current=None, managed=None, local=None):
    steps = build_plan(
        desired_list, current or {}, managed or set(), local or {"nextcloud"}
    )
    return {s.name: s.action for s in steps}


def test_rule1_local_user_is_skipped_even_when_unknown_or_managed():
    d = [desired("nextcloud", SecretState.UNKNOWN, None)]
    assert plan(d, managed={"nextcloud"}) == {"nextcloud": Action.SKIP}


def test_rule1_local_user_absent_from_desired_but_managed_is_not_deleted():
    assert plan([], managed={"nextcloud"}) == {"nextcloud": Action.SKIP}


def test_rule2_unknown_is_hold_and_registration_untouched():
    d = [desired("alice", SecretState.UNKNOWN, None)]
    assert plan(d, current={"alice": H1}, managed={"alice"}) == {"alice": Action.HOLD}


def test_rule3_absent_managed_is_delete():
    d = [desired("alice", SecretState.ABSENT, None)]
    assert plan(d, current={"alice": H1}, managed={"alice"}) == {"alice": Action.DELETE}


def test_rule3_absent_unmanaged_is_skip():
    d = [desired("alice", SecretState.ABSENT, None)]
    assert plan(d, current={"alice": H1}) == {"alice": Action.SKIP}


def test_rule3_unresolvable_managed_is_delete():
    d = [desired("alice", resolvable=False)]
    assert plan(d, managed={"alice"}) == {"alice": Action.DELETE}


def test_rule3_unresolvable_unmanaged_is_skip():
    d = [desired("alice", resolvable=False)]
    assert plan(d) == {"alice": Action.SKIP}


def test_rule4_present_unregistered_is_add():
    assert plan([desired("alice")]) == {"alice": Action.ADD}


def test_rule5_present_hash_differs_is_update():
    d = [desired("alice", nt_hash=H2)]
    assert plan(d, current={"alice": H1}, managed={"alice"}) == {"alice": Action.UPDATE}


def test_rule5_update_even_when_unmanaged():
    d = [desired("alice", nt_hash=H2)]
    assert plan(d, current={"alice": H1}) == {"alice": Action.UPDATE}


def test_rule6_hash_match_unmanaged_is_adopt():
    assert plan([desired("alice")], current={"alice": H1}) == {"alice": Action.ADOPT}


def test_rule7_hash_match_managed_is_skip():
    assert plan([desired("alice")], current={"alice": H1}, managed={"alice"}) == {
        "alice": Action.SKIP
    }


def test_rule8_managed_not_in_desired_is_delete():
    assert plan([], current={"bob": H1}, managed={"bob"}) == {"bob": Action.DELETE}


def test_adopt_then_removed_from_group_is_delete():
    first = plan([desired("alice")], current={"alice": H1})
    assert first == {"alice": Action.ADOPT}
    managed = {"alice"}
    assert plan([], current={"alice": H1}, managed=managed) == {"alice": Action.DELETE}


def test_never_delete_unmanaged_name():
    # tdbsam holds entries the job never registered (and nextcloud).
    current = {"nextcloud": H1, "carol": H1}
    steps = build_plan([], current, set(), {"nextcloud"})
    assert all(s.action is not Action.DELETE for s in steps)


def test_plan_covers_each_name_once():
    steps = build_plan(
        [desired("alice"), desired("bob", SecretState.ABSENT, None)],
        {"alice": H1},
        {"alice", "dave"},
        {"nextcloud"},
    )
    names = [s.name for s in steps]
    assert sorted(names) == sorted(set(names)) == ["alice", "bob", "dave"]
    assert Step("dave", Action.DELETE) in steps


# --- Kanidm response interpretation -------------------------------------


class FakeResp:
    def __init__(self, body):
        self._b = json.dumps(body).encode() if not isinstance(body, bytes) else body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._b


class FakeOpener:
    """Maps (method, path) -> body | Exception | int (HTTP status)."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, req, timeout=None):
        path = req.full_url.split("://", 1)[1].split("/", 1)[1]
        key = (req.get_method(), "/" + path)
        self.calls.append((key, req.data, dict(req.header_items()), timeout))
        r = self.routes[key]
        if isinstance(r, Exception):
            raise r
        if isinstance(r, int):
            raise urllib.error.HTTPError(req.full_url, r, "x", {}, io.BytesIO(b""))
        return FakeResp(r)


def client(routes):
    op = FakeOpener(routes)
    return mod.KanidmClient("https://k.example", "tok", opener=op), op


SELF_OK = {
    "youare": {"attrs": {"memberof": ["idm_radius_servers@k.example", "x@k.example"]}}
}


def test_client_sends_bearer_and_timeout_10():
    c, op = client({("GET", "/v1/self"): SELF_OK})
    c.call("GET", "/v1/self")
    _, _, headers, timeout = op.calls[0]
    assert headers["Authorization"] == "Bearer tok"
    assert timeout == 10


def test_ensure_radius_server_ok():
    c, _ = client({("GET", "/v1/self"): SELF_OK})
    mod.ensure_radius_server(c)


@pytest.mark.parametrize(
    "body",
    [
        {"youare": {"attrs": {"memberof": ["other@k.example"]}}},
        {"youare": {"attrs": {}}},
        {"youare": {"attrs": {"memberof": "idm_radius_servers"}}},
        {"youare": []},
        [],
    ],
)
def test_ensure_radius_server_fatal_on_bad_membership_or_shape(body):
    c, _ = client({("GET", "/v1/self"): body})
    with pytest.raises(mod.FatalSyncError):
        mod.ensure_radius_server(c)


@pytest.mark.parametrize(
    "err",
    [
        401,
        403,
        500,
        urllib.error.URLError("refused"),
        socket.timeout("t"),
        TimeoutError("t"),
        b"not json",
    ],
)
def test_collection_errors_are_fatal(err):
    c, _ = client({("GET", "/v1/self"): err})
    with pytest.raises(mod.FatalSyncError):
        mod.ensure_radius_server(c)


def test_tls_failure_is_fatal():
    import ssl

    err = urllib.error.URLError(ssl.SSLCertVerificationError("bad"))
    c, _ = client({("GET", "/v1/self"): err})
    with pytest.raises(mod.FatalSyncError):
        mod.ensure_radius_server(c)


def test_group_uuid():
    c, _ = client({("GET", "/v1/group/nas_access"): {"attrs": {"uuid": ["g-1"]}}})
    assert mod.get_group_uuid(c, "nas_access") == "g-1"


@pytest.mark.parametrize(
    "body",
    [None, {"attrs": {}}, {"attrs": {"uuid": []}}, {"attrs": {"uuid": [1]}}, "x"],
)
def test_group_null_or_bad_shape_is_fatal(body):
    c, _ = client({("GET", "/v1/group/nas_access"): body})
    with pytest.raises(mod.FatalSyncError):
        mod.get_group_uuid(c, "nas_access")


def test_search_members_builds_filter_and_parses():
    c, op = client(
        {
            ("POST", "/v1/raw/search"): {
                "entries": [
                    {"attrs": {"name": ["alice"], "uuid": ["u1"]}},
                    {"attrs": {"name": ["bob"], "uuid": ["u2"]}},
                ]
            }
        }
    )
    assert mod.search_members(c, "g-1") == [
        Member("alice", "u1"),
        Member("bob", "u2"),
    ]
    sent = json.loads(op.calls[0][1])
    assert sent == {
        "filter": {
            "and": [
                {"eq": ["class", "person"]},
                {"eq": ["class", "posixaccount"]},
                {"eq": ["memberof", "g-1"]},
            ]
        }
    }


def test_search_members_zero_entries_is_ok():
    c, _ = client({("POST", "/v1/raw/search"): {"entries": []}})
    assert mod.search_members(c, "g") == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"entries": None},
        {"entries": "x"},
        {"entries": [{"attrs": {"name": ["a"]}}]},
        {"entries": [{"attrs": {"name": "a", "uuid": ["u"]}}]},
        {"entries": [1]},
    ],
)
def test_search_members_bad_shape_is_fatal(body):
    c, _ = client({("POST", "/v1/raw/search"): body})
    with pytest.raises(mod.FatalSyncError):
        mod.search_members(c, "g")


def test_search_members_http_failure_is_fatal():
    c, _ = client({("POST", "/v1/raw/search"): 503})
    with pytest.raises(mod.FatalSyncError):
        mod.search_members(c, "g")


def test_secret_null_is_absent_and_string_is_present():
    c, _ = client(
        {
            ("GET", "/v1/person/u1/_radius"): None,
            ("GET", "/v1/person/u2/_radius"): "s3cret",
        }
    )
    assert mod.fetch_secret(c, Member("alice", "u1")) == (
        SecretState.ABSENT,
        None,
    )
    assert mod.fetch_secret(c, Member("bob", "u2")) == (
        SecretState.PRESENT,
        "s3cret",
    )


@pytest.mark.parametrize("status", [404, 500, 502])
def test_secret_404_5xx_is_unknown(status):
    c, _ = client({("GET", "/v1/person/u1/_radius"): status})
    assert mod.fetch_secret(c, Member("alice", "u1")) == (
        SecretState.UNKNOWN,
        None,
    )


@pytest.mark.parametrize("err", [401, 403, urllib.error.URLError("x"), TimeoutError()])
def test_secret_auth_or_connection_failure_is_fatal(err):
    c, _ = client({("GET", "/v1/person/u1/_radius"): err})
    with pytest.raises(mod.FatalSyncError):
        mod.fetch_secret(c, Member("alice", "u1"))


def test_secret_unexpected_type_is_unknown():
    c, _ = client({("GET", "/v1/person/u1/_radius"): {"a": 1}})
    assert mod.fetch_secret(c, Member("alice", "u1")) == (
        SecretState.UNKNOWN,
        None,
    )


@pytest.mark.parametrize("name", ["Alice", "a b", "a/b", "", "al@ce", "ａ"])
def test_invalid_name_is_unknown_without_request(name):
    c, op = client({})
    assert mod.fetch_secret(c, Member(name, "u1")) == (SecretState.UNKNOWN, None)
    assert op.calls == []


# --- NT hash ------------------------------------------------------------


def test_nt_hash_known_vector():
    assert mod.nt_hash("password") == "8846F7EAEE8FB117AD06BDD830B7586C"


def test_nt_hash_passes_secret_via_stdin_not_argv():
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw["input"]

        class R:
            returncode = 0
            stdout = b"MD4(stdin)= 8846f7eaee8fb117ad06bdd830b7586c\n"

        return R()

    assert mod.nt_hash("pässword", run=fake_run) == "8846F7EAEE8FB117AD06BDD830B7586C"
    assert "pässword" not in " ".join(seen["cmd"])
    assert seen["input"] == "pässword".encode("utf-16-le")


def test_nt_hash_failure_is_fatal_without_leaking_secret():
    def fake_run(cmd, **kw):
        class R:
            returncode = 1
            stdout = b""

        return R()

    with pytest.raises(mod.FatalSyncError) as e:
        mod.nt_hash("s3cret", run=fake_run)
    assert "s3cret" not in str(e.value)


# --- collection, apply, state file, exit code ---------------------------


def fake_hash(secret):
    return secret.upper().ljust(32, "0")


class FakeTdb:
    def __init__(self, hashes=None, fail=()):
        self.hashes = dict(hashes or {})
        self.fail = set(fail)
        self.ops = []

    def list_hashes(self):
        self.ops.append(("list",))
        return dict(self.hashes)

    def set_password(self, name, secret):
        self.ops.append(("set", name))
        if name in self.fail:
            raise mod.ApplyError("set")
        self.hashes[name] = fake_hash(secret)

    def delete(self, name):
        self.ops.append(("delete", name))
        if name in self.fail:
            raise mod.ApplyError("delete")
        self.hashes.pop(name, None)


def full_routes(members, secrets, group="nas_access"):
    r = {
        ("GET", "/v1/self"): SELF_OK,
        ("GET", f"/v1/group/{group}"): {"attrs": {"uuid": ["g-1"]}},
        ("POST", "/v1/raw/search"): {
            "entries": [{"attrs": {"name": [n], "uuid": [f"u-{n}"]}} for n in members]
        },
    }
    for n, s in secrets.items():
        r[("GET", f"/v1/person/u-{n}/_radius")] = s
    return r


ENV = {
    "KANIDM_URL": "https://k.example",
    "KANIDM_TOKEN": "tok",
    "NAS_SMB_SYNC_GROUP": "nas_access",
}


def run_job(tmp_path, routes, tdb, managed=None, local=("nextcloud",), unresolvable=()):
    state = tmp_path / "managed"
    if managed is not None:
        state.write_text("".join(f"{n}\n" for n in managed))
    passwd = tmp_path / "passwd"
    passwd.write_text("".join(f"{n}:x:1:1::/:/bin/sh\n" for n in local))
    op = FakeOpener(routes)
    code = mod.run(
        ENV,
        tdb,
        state_path=state,
        passwd_path=passwd,
        resolve=lambda n: n not in unresolvable,
        hasher=fake_hash,
        opener=op,
    )
    return code, state, op


def managed_of(state):
    return set(state.read_text().split()) if state.exists() else set()


def test_run_add_update_delete_and_exit_0(tmp_path):
    tdb = FakeTdb({"bob": fake_hash("old"), "gone": fake_hash("x")})
    routes = full_routes(["alice", "bob"], {"alice": "pw1", "bob": "pw2"})
    code, state, _ = run_job(tmp_path, routes, tdb, managed={"bob", "gone"})
    assert code == 0
    assert tdb.hashes == {
        "alice": fake_hash("pw1"),
        "bob": fake_hash("pw2"),
    }
    assert managed_of(state) == {"alice", "bob"}


def test_run_second_run_changes_nothing(tmp_path):
    tdb = FakeTdb()
    routes = full_routes(["alice"], {"alice": "pw1"})
    run_job(tmp_path, routes, tdb)
    tdb.ops.clear()
    code, _, _ = run_job(tmp_path, routes, tdb, managed={"alice"})
    assert code == 0
    assert tdb.ops == [("list",)]


def test_run_empty_state_adopts_then_group_removal_deletes(tmp_path):
    tdb = FakeTdb({"alice": fake_hash("pw1")})
    code, state, _ = run_job(tmp_path, full_routes(["alice"], {"alice": "pw1"}), tdb)
    assert code == 0 and managed_of(state) == {"alice"}
    assert ("set", "alice") not in tdb.ops
    code, state, _ = run_job(tmp_path, full_routes([], {}), tdb, managed={"alice"})
    assert code == 0 and "alice" not in tdb.hashes and managed_of(state) == set()


def test_run_never_touches_nextcloud_even_if_member_and_in_state(tmp_path):
    tdb = FakeTdb({"nextcloud": fake_hash("nc")})
    routes = full_routes(["nextcloud"], {"nextcloud": "other"})
    code, state, _ = run_job(tmp_path, routes, tdb, managed={"nextcloud"})
    assert code == 0
    assert tdb.hashes == {"nextcloud": fake_hash("nc")}
    assert all(op[0] == "list" for op in tdb.ops)


def test_run_unresolvable_member_is_skipped_without_failure(tmp_path):
    tdb = FakeTdb()
    code, _, _ = run_job(
        tmp_path,
        full_routes(["alice"], {"alice": "pw1"}),
        tdb,
        unresolvable={"alice"},
    )
    assert code == 0 and tdb.hashes == {}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r.update({("GET", "/v1/self"): 403}),
        lambda r: r.update({("GET", "/v1/self"): urllib.error.URLError("x")}),
        lambda r: r.update({("GET", "/v1/group/nas_access"): None}),
        lambda r: r.update({("POST", "/v1/raw/search"): {"entries": 1}}),
        lambda r: r.update({("GET", "/v1/person/u-alice/_radius"): 401}),
        lambda r: r.update(
            {("GET", "/v1/self"): {"youare": {"attrs": {"memberof": []}}}}
        ),
    ],
)
def test_run_fatal_collection_exits_1_without_touching_tdbsam_or_state(
    tmp_path, mutate
):
    routes = full_routes(["alice"], {"alice": "pw1"})
    mutate(routes)
    tdb = FakeTdb({"alice": fake_hash("pw1")})
    code, state, _ = run_job(tmp_path, routes, tdb, managed={"alice"})
    assert code == 1
    assert tdb.ops == []
    assert managed_of(state) == {"alice"}


def test_run_hold_keeps_entry_continues_others_and_exits_1(tmp_path):
    routes = full_routes(["alice", "bob"], {"alice": 500, "bob": "pw2"})
    tdb = FakeTdb({"alice": fake_hash("old")})
    code, state, _ = run_job(tmp_path, routes, tdb, managed={"alice"})
    assert code == 1
    assert tdb.hashes["alice"] == fake_hash("old")
    assert tdb.hashes["bob"] == fake_hash("pw2")
    assert managed_of(state) == {"alice", "bob"}


def test_run_apply_failure_is_isolated_and_exits_1(tmp_path):
    routes = full_routes(["alice", "bob"], {"alice": "pw1", "bob": "pw2"})
    tdb = FakeTdb(fail={"alice"})
    code, _, _ = run_job(tmp_path, routes, tdb)
    assert code == 1
    assert "bob" in tdb.hashes


def test_run_delete_failure_keeps_name_in_state(tmp_path):
    tdb = FakeTdb({"gone": fake_hash("x")}, fail={"gone"})
    code, state, _ = run_job(tmp_path, full_routes([], {}), tdb, managed={"gone"})
    assert code == 1
    assert managed_of(state) == {"gone"}


def test_run_state_written_before_tdbsam_write(tmp_path):
    state = tmp_path / "managed"
    seen = {}

    class Spy(FakeTdb):
        def set_password(self, name, secret):
            seen["managed_at_write"] = managed_of(state)
            super().set_password(name, secret)

    run_job(tmp_path, full_routes(["alice"], {"alice": "pw1"}), Spy())
    assert seen["managed_at_write"] == {"alice"}


def test_state_file_is_replaced_atomically_with_mode_0600(tmp_path):
    p = tmp_path / "managed"
    mod.save_managed(p, {"b", "a"})
    assert p.read_text() == "a\nb\n"
    assert (p.stat().st_mode & 0o777) == 0o600
    assert [f.name for f in tmp_path.iterdir()] == ["managed"]
    assert mod.load_managed(p) == {"a", "b"}
    assert mod.load_managed(tmp_path / "missing") == set()


def test_local_users_reads_passwd_names(tmp_path):
    p = tmp_path / "passwd"
    p.write_text("root:x:0:0::/root:/bin/sh\n\nnextcloud:x:33:33::/:/sbin/nologin\n")
    assert mod.read_local_users(p) == {"root", "nextcloud"}


def test_logs_contain_names_and_actions_only(tmp_path, capsys):
    routes = full_routes(["alice"], {"alice": "TOPSECRETPW"})
    run_job(tmp_path, routes, FakeTdb())
    out = capsys.readouterr()
    text = out.out + out.err
    assert "alice" in text and "add" in text
    for leaked in ("TOPSECRETPW", "tok", fake_hash("TOPSECRETPW")):
        assert leaked not in text.replace("token", "")


def test_missing_env_exits_1(tmp_path):
    assert (
        mod.run({}, FakeTdb(), state_path=tmp_path / "m", passwd_path=tmp_path / "p")
        == 1
    )


# --- real command wrappers (subprocess faked) ---------------------------


class Rec:
    def __init__(self, stdout=b"", code=0):
        self.calls, self.stdout, self.code = [], stdout, code

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw.get("input")))

        class R:
            returncode = self.code
            stdout = self.stdout

        return R()


def test_tdbsam_list_hashes_parses_pdbedit_w_output():
    out = (
        b"nextcloud:1000:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX:"
        b"8846f7eaee8fb117ad06bdd830b7586c:[U          ]:LCT-5F000000:\n"
        b"alice:1001:XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX:"
        + b"B" * 32
        + b":[U          ]:LCT-5F000000:\n"
    )
    t = mod.Tdbsam(run=Rec(out))
    assert t.list_hashes() == {
        "nextcloud": "8846F7EAEE8FB117AD06BDD830B7586C",
        "alice": "B" * 32,
    }


def test_tdbsam_set_password_uses_stdin_not_argv():
    rec = Rec()
    mod.Tdbsam(run=rec).set_password("alice", "s3cret")
    cmd, stdin = rec.calls[0]
    assert cmd == ["smbpasswd", "-a", "-s", "alice"]
    assert stdin == b"s3cret\ns3cret\n"


def test_tdbsam_delete_and_failure_raises_without_secret():
    rec = Rec()
    mod.Tdbsam(run=rec).delete("alice")
    assert rec.calls[0][0] == ["pdbedit", "-x", "-u", "alice"]
    with pytest.raises(mod.ApplyError):
        mod.Tdbsam(run=Rec(code=1)).set_password("alice", "s3cret")
