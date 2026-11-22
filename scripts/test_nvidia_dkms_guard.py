"""Self-check for ansible/roles/nvidia_driver/files/nvidia-dkms-guard.

dpkg / dkms / uname / proxmox-boot-tool are replaced by fakes on PATH.
"""

import os
import stat
import subprocess
from pathlib import Path

GUARD = (
    Path(__file__).parent.parent / "ansible/roles/nvidia_driver/files/nvidia-dkms-guard"
)

FAKES = {
    "uname": 'echo "$FAKE_RUNNING"',
    "dpkg": 'echo "$FAKE_AUDIT"',
    # FAKE_DKMS_OK は NVIDIA モジュールが installed のカーネル版 (空白区切り)
    "dkms": (
        'while [ "$1" != -k ]; do shift; done; k="$2"\n'
        'for v in $FAKE_DKMS_OK; do [ "$v" = "$k" ] && echo "nvidia/620.70.06, $k, x86_64: installed" && exit 0; done\n'
        "exit 0"
    ),
    "proxmox-boot-tool": 'echo "$@" >> "$FAKE_LOG"',
}


def run(
    tmp_path,
    *,
    running,
    installed,
    dkms_ok,
    audit="",
    pin=None,
    next_pin=None,
    marker=False,
):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in FAKES.items():
        f = bin_dir / name
        f.write_text(f"#!/bin/bash\n{body}\n")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    boot = tmp_path / "boot"
    boot.mkdir()
    for v in installed:
        (boot / f"vmlinuz-{v}").touch()
    state = tmp_path / "state"
    if marker:
        state.mkdir()
        (state / "pinned").touch()
    pinfile = tmp_path / "pin"
    nextfile = tmp_path / "next"
    if pin:
        pinfile.write_text(pin + "\n")
    if next_pin:
        nextfile.write_text(next_pin + "\n")
    log = tmp_path / "log"
    log.touch()
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_RUNNING": running,
        "FAKE_AUDIT": audit,
        "FAKE_DKMS_OK": " ".join(dkms_ok),
        "FAKE_LOG": str(log),
        "NVIDIA_DKMS_GUARD_STATE_DIR": str(state),
        "NVIDIA_DKMS_GUARD_PINFILE": str(pinfile),
        "NVIDIA_DKMS_GUARD_NEXT_PINFILE": str(nextfile),
        "NVIDIA_DKMS_GUARD_BOOT_DIR": str(boot),
    }
    r = subprocess.run(["bash", str(GUARD)], env=env, capture_output=True, text=True)
    return r.returncode, log.read_text().splitlines(), (state / "pinned").exists()


OLD, NEW = "6.17.13-21-pve", "7.0.14-30-pve"


def test_healthy_succeeds_without_pin(tmp_path):
    rc, calls, marker = run(
        tmp_path, running=OLD, installed=[OLD, NEW], dkms_ok=[OLD, NEW]
    )
    assert (rc, calls, marker) == (0, [], False)


def test_missing_module_on_next_kernel_pins_running(tmp_path):
    rc, calls, marker = run(tmp_path, running=OLD, installed=[OLD, NEW], dkms_ok=[OLD])
    assert rc != 0
    assert calls == [f"kernel pin {OLD}"]
    assert marker


def test_module_restored_on_latest_unpins_own_pin(tmp_path):
    rc, calls, marker = run(
        tmp_path,
        running=OLD,
        installed=[OLD, NEW],
        dkms_ok=[OLD, NEW],
        pin=OLD,
        marker=True,
    )
    assert (rc, calls, marker) == (0, ["kernel unpin"], False)


def test_own_pin_kept_while_latest_still_lacks_module(tmp_path):
    rc, calls, marker = run(
        tmp_path,
        running=OLD,
        installed=[OLD, NEW],
        dkms_ok=[OLD],
        pin=OLD,
        marker=True,
    )
    assert rc != 0
    assert (calls, marker) == ([], True)


def test_manual_pin_without_marker_is_left_alone(tmp_path):
    rc, calls, marker = run(
        tmp_path, running=OLD, installed=[OLD, NEW], dkms_ok=[OLD], pin=OLD
    )
    assert (rc, calls, marker) == (0, [], False)


def test_next_boot_pin_takes_precedence(tmp_path):
    rc, calls, _ = run(
        tmp_path,
        running=OLD,
        installed=[OLD, NEW],
        dkms_ok=[OLD],
        pin=OLD,
        next_pin=NEW,
    )
    assert rc != 0
    assert calls == [f"kernel pin {OLD}"]


def test_unconfigured_package_fails(tmp_path):
    rc, calls, _ = run(
        tmp_path,
        running=OLD,
        installed=[OLD],
        dkms_ok=[OLD],
        audit="pkg half-configured",
    )
    assert rc != 0 and calls == []
