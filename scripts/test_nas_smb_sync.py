"""Unit tests for ansible/roles/nas/files/nas-smb-sync.py.

The script's filename contains a hyphen, so it is loaded by path. Kanidm,
tdbsam (smbpasswd / pdbedit), openssl and NSS are all replaced by fakes.
"""

import importlib.util
import inspect
import io
import http.client
import json
import os
import socket
import stat
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


def plan(desired_list, current=None, managed=None):
    steps = build_plan(desired_list, current or {}, managed or set())
    return {s.name: s.action for s in steps}


def test_same_name_as_local_user_unregistered_is_add():
    assert plan([desired("tochi")]) == {"tochi": Action.ADD}


def test_rule7_unmanaged_entry_with_differing_hash_is_skipped_not_updated():
    steps = build_plan([desired("nextcloud", nt_hash=H2)], {"nextcloud": H1}, set())
    assert steps == [Step("nextcloud", Action.SKIP)]
    assert steps[0].reason == "unmanaged entry"


def test_unmanaged_entry_absent_from_desired_is_not_deleted():
    assert plan([], current={"nextcloud": H1}) == {}


def test_rule1_unknown_is_hold_and_registration_untouched():
    d = [desired("alice", SecretState.UNKNOWN, None)]
    assert plan(d, current={"alice": H1}, managed={"alice"}) == {"alice": Action.HOLD}


def test_rule2_absent_managed_is_delete():
    d = [desired("alice", SecretState.ABSENT, None)]
    assert plan(d, current={"alice": H1}, managed={"alice"}) == {"alice": Action.DELETE}


def test_rule2_absent_unmanaged_is_skip():
    d = [desired("alice", SecretState.ABSENT, None)]
    assert plan(d, current={"alice": H1}) == {"alice": Action.SKIP}


def test_rule2_unresolvable_managed_is_delete():
    d = [desired("alice", resolvable=False)]
    assert plan(d, managed={"alice"}) == {"alice": Action.DELETE}


def test_rule2_unresolvable_unmanaged_is_skip():
    d = [desired("alice", resolvable=False)]
    assert plan(d) == {"alice": Action.SKIP}


def test_rule3_present_unregistered_is_add():
    assert plan([desired("alice")]) == {"alice": Action.ADD}


def test_rule6_present_hash_differs_managed_is_update():
    d = [desired("alice", nt_hash=H2)]
    assert plan(d, current={"alice": H1}, managed={"alice"}) == {"alice": Action.UPDATE}


def test_rule4_hash_match_unmanaged_is_adopt():
    assert plan([desired("alice")], current={"alice": H1}) == {"alice": Action.ADOPT}


def test_rule5_hash_match_managed_is_skip():
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
    steps = build_plan([], current, set())
    assert all(s.action is not Action.DELETE for s in steps)


def test_plan_covers_each_name_once():
    steps = build_plan(
        [desired("alice"), desired("bob", SecretState.ABSENT, None)],
        {"alice": H1},
        {"alice", "dave"},
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


def test_every_request_sends_fixed_user_agent():
    c, op = client({("GET", "/v1/self"): SELF_OK, ("POST", "/v1/x"): {}})
    c.call("GET", "/v1/self")
    c.call("POST", "/v1/x", {"a": 1})
    assert [h["User-agent"] for _, _, h, _ in op.calls] == ["nas-smb-sync"] * 2


def test_authorization_header_is_not_sent_to_redirect_targets():
    seen = {}

    def opener(req, timeout=None):
        seen["unredirected"] = dict(req.unredirected_hdrs)
        seen["redirected"] = dict(req.headers)
        return FakeResp({})

    mod.KanidmClient("https://k.example", "tok", opener=opener).call("GET", "/x")
    assert seen["unredirected"]["Authorization"] == "Bearer tok"
    assert "Authorization" not in seen["redirected"]


@pytest.mark.parametrize(
    "exc", [http.client.IncompleteRead(b""), http.client.BadStatusLine("x")]
)
def test_http_client_exceptions_are_fatal(exc):
    c, _ = client({("GET", "/v1/self"): exc})
    with pytest.raises(mod.FatalSyncError):
        mod.ensure_radius_server(c)


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
    assert mod.search_members(c) == [
        Member("alice", "u1"),
        Member("bob", "u2"),
    ]
    sent = json.loads(op.calls[0][1])
    assert sent == {"filter": {"eq": ["class", "person"]}}


def test_search_members_zero_entries_is_ok():
    c, _ = client({("POST", "/v1/raw/search"): {"entries": []}})
    assert mod.search_members(c) == []


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
        mod.search_members(c)


def test_search_members_http_failure_is_fatal():
    c, _ = client({("POST", "/v1/raw/search"): 503})
    with pytest.raises(mod.FatalSyncError):
        mod.search_members(c)


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
        "",
    )
    assert mod.fetch_secret(c, Member("bob", "u2")) == (
        SecretState.PRESENT,
        "s3cret",
        "",
    )


@pytest.mark.parametrize("status", [404, 500, 502])
def test_secret_404_5xx_is_unknown(status):
    c, _ = client({("GET", "/v1/person/u1/_radius"): status})
    state, secret, reason = mod.fetch_secret(c, Member("alice", "u1"))
    assert (state, secret) == (SecretState.UNKNOWN, None)
    assert reason == f"HTTP {status}"


@pytest.mark.parametrize("err", [401, 403, urllib.error.URLError("x"), TimeoutError()])
def test_secret_auth_or_connection_failure_is_fatal(err):
    c, _ = client({("GET", "/v1/person/u1/_radius"): err})
    with pytest.raises(mod.FatalSyncError):
        mod.fetch_secret(c, Member("alice", "u1"))


@pytest.mark.parametrize("body", [{"a": 1}, 1.5, ["x"]])
def test_secret_unexpected_type_is_fatal(body):
    c, _ = client({("GET", "/v1/person/u1/_radius"): body})
    with pytest.raises(mod.FatalSyncError):
        mod.fetch_secret(c, Member("alice", "u1"))


@pytest.mark.parametrize(
    "name", ["Alice", "a b", "a/b", "", "al@ce", "ａ", "-alice", "-o", ".a", "_a"]
)
def test_invalid_name_is_unknown_without_request(name):
    c, op = client({})
    state, secret, reason = mod.fetch_secret(c, Member(name, "u1"))
    assert (state, secret) == (SecretState.UNKNOWN, None)
    assert reason == "invalid name"
    assert op.calls == []


@pytest.mark.parametrize("name", ["alice", "a-b", "a.b_c", "0day"])
def test_valid_names_are_requested(name):
    c, op = client({("GET", "/v1/person/u1/_radius"): "pw"})
    assert mod.fetch_secret(c, Member(name, "u1"))[0] is SecretState.PRESENT


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


def full_routes(members, secrets):
    r = {
        ("GET", "/v1/self"): SELF_OK,
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
}


def run_job(
    tmp_path,
    routes,
    tdb,
    managed=None,
    unresolvable=(),
    unixd_status=lambda: "system: online\nKanidm: online\n",
    env=ENV,
):
    state = tmp_path / "managed"
    if managed is not None:
        state.write_text("".join(f"{n}\n" for n in managed))
    op = FakeOpener(routes)
    code = mod.run(
        env,
        tdb,
        state_path=state,
        resolve=lambda n: n not in unresolvable,
        unixd_status=unixd_status,
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


def test_run_never_touches_unmanaged_entry_even_if_member_with_other_secret(
    tmp_path,
):
    tdb = FakeTdb({"nextcloud": fake_hash("nc")})
    routes = full_routes(["nextcloud"], {"nextcloud": "other"})
    code, state, _ = run_job(tmp_path, routes, tdb)
    assert code == 0
    assert tdb.hashes == {"nextcloud": fake_hash("nc")}
    assert all(op[0] == "list" for op in tdb.ops)
    assert managed_of(state) == set()


def test_run_registers_member_named_like_local_user(tmp_path):
    tdb = FakeTdb()
    routes = full_routes(["tochi"], {"tochi": "pw"})
    code, state, _ = run_job(tmp_path, routes, tdb)
    assert code == 0
    assert tdb.hashes == {"tochi": fake_hash("pw")}
    assert managed_of(state) == {"tochi"}


def test_passwd_is_not_read():
    assert not hasattr(mod, "read_local_users")
    assert not hasattr(mod, "PASSWD_PATH")
    assert "passwd_path" not in inspect.signature(mod.run).parameters


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


@pytest.mark.parametrize(
    "out",
    [
        "system: online\nKanidm: offline\n",
        "",
        "Kanidm: online (stale)\n",
        "xKanidm: online\n",
    ],
)
def test_run_unixd_not_online_is_fatal_and_deletes_nobody(tmp_path, capsys, out):
    tdb = FakeTdb({"alice": fake_hash("pw1")})
    code, state, op = run_job(
        tmp_path,
        full_routes(["alice"], {"alice": "pw1"}),
        tdb,
        managed={"alice"},
        unresolvable={"alice"},
        unixd_status=lambda: out,
    )
    assert code == 1
    assert tdb.ops == []
    assert managed_of(state) == {"alice"}
    assert capsys.readouterr().err.startswith("fatal:")


def test_run_unixd_status_command_failure_is_fatal(tmp_path, capsys):
    def boom():
        raise FileNotFoundError("kanidm-unix")

    tdb = FakeTdb({"alice": fake_hash("pw1")})
    code, state, _ = run_job(
        tmp_path,
        full_routes(["alice"], {"alice": "pw1"}),
        tdb,
        managed={"alice"},
        unixd_status=boom,
    )
    assert code == 1
    assert tdb.ops == []
    assert managed_of(state) == {"alice"}
    assert capsys.readouterr().err.startswith("fatal:")


def test_run_unixd_online_proceeds_to_plan(tmp_path):
    tdb = FakeTdb()
    code, _, _ = run_job(
        tmp_path,
        full_routes(["alice"], {"alice": "pw1"}),
        tdb,
        unixd_status=lambda: "system: online\nKanidm: online\n",
    )
    assert code == 0
    assert tdb.hashes == {"alice": fake_hash("pw1")}


def test_read_unixd_status_runs_kanidm_unix_status():
    r = Rec(b"Kanidm: online\n", code=0)
    assert mod.read_unixd_status(run=r) == "Kanidm: online\n"
    assert r.calls[0][0] == ["kanidm-unix", "status"]


def test_missing_group_env_is_not_required(tmp_path):
    code, _, _ = run_job(tmp_path, full_routes([], {}), FakeTdb())
    assert code == 0


def test_run_managed_but_absent_from_tdbsam_is_dropped_without_pdbedit(tmp_path):
    tdb = FakeTdb()
    code, state, _ = run_job(tmp_path, full_routes([], {}), tdb, managed={"ghost"})
    assert code == 0
    assert tdb.ops == [("list",)]
    assert managed_of(state) == set()


def test_run_unresolvable_managed_absent_from_tdbsam_is_dropped(tmp_path):
    tdb = FakeTdb()
    code, state, _ = run_job(
        tmp_path,
        full_routes(["alice"], {"alice": "pw"}),
        tdb,
        managed={"alice"},
        unresolvable={"alice"},
    )
    assert code == 0
    assert ("delete", "alice") not in tdb.ops
    assert managed_of(state) == set()


@pytest.mark.parametrize(
    "url", ["http://k.example", "k.example", "ftp://k.example", ""]
)
def test_run_non_https_url_exits_1_before_any_request(tmp_path, capsys, url):
    tdb = FakeTdb()
    code, _, op = run_job(
        tmp_path, full_routes([], {}), tdb, env={**ENV, "KANIDM_URL": url}
    )
    assert code == 1
    assert op.calls == [] and tdb.ops == []
    assert capsys.readouterr().err.startswith("fatal:")


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


def test_state_dir_is_fsynced_after_rename(tmp_path, monkeypatch):
    events = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd):
        events.append("fsync-dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync")
        real_fsync(fd)

    def replace(a, b):
        events.append("replace")
        real_replace(a, b)

    monkeypatch.setattr(os, "fsync", fsync)
    monkeypatch.setattr(os, "replace", replace)
    mod.save_managed(tmp_path / "managed", {"a"})
    assert events == ["fsync", "replace", "fsync-dir"]


def test_state_file_is_replaced_atomically_with_mode_0600(tmp_path):
    p = tmp_path / "managed"
    mod.save_managed(p, {"b", "a"})
    assert p.read_text() == "a\nb\n"
    assert (p.stat().st_mode & 0o777) == 0o600
    assert [f.name for f in tmp_path.iterdir()] == ["managed"]
    assert mod.load_managed(p) == {"a", "b"}
    assert mod.load_managed(tmp_path / "missing") == set()


def test_logs_contain_names_and_actions_only(tmp_path, capsys):
    routes = full_routes(["alice"], {"alice": "TOPSECRETPW"})
    run_job(tmp_path, routes, FakeTdb())
    out = capsys.readouterr()
    text = out.out + out.err
    assert "alice" in text and "add" in text
    for leaked in ("TOPSECRETPW", "tok", fake_hash("TOPSECRETPW")):
        assert leaked not in text.replace("token", "")


def test_logs_state_reasons_for_skip_and_hold(tmp_path, capsys):
    routes = full_routes(
        ["alice", "bob", "carol", "dave", "nextcloud", "erin", "-x"],
        {
            "alice": None,
            "bob": "pw",
            "carol": 500,
            "dave": "pw",
            "nextcloud": "pw",
            "erin": "pw",
        },
    )
    tdb = FakeTdb({"erin": fake_hash("pw"), "nextcloud": fake_hash("nc")})
    run_job(tmp_path, routes, tdb, managed={"erin"}, unresolvable={"bob"})
    out = capsys.readouterr()
    lines = (out.out + out.err).splitlines()
    assert "skip alice (not issued)" in lines
    assert "skip bob (unresolvable)" in lines
    assert "hold carol (HTTP 500)" in lines
    assert "skip nextcloud (unmanaged entry)" in lines
    assert "skip erin (up to date)" in lines
    assert "hold -x (invalid name)" in lines
    assert "add dave" in lines


def test_missing_env_exits_1(tmp_path):
    assert mod.run({}, FakeTdb(), state_path=tmp_path / "m") == 1


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
