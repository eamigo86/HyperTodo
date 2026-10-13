"""Run the Makefile's development recipes against stand-ins for the external tools.

Only nvm, corepack, node, uv and the macOS network tools are replaced, so the real
recipes decide the environment and arguments each tool receives.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NODE_VERSION = (ROOT / "mobile/.nvmrc").read_text().strip()
LAN_IP = "192.168.1.20"
LOCAL = "http://127.0.0.1:8000/hv/"
EMULATOR = "http://10.0.2.2:8000/hv/"
DEVICE = f"http://{LAN_IP}:8000/hv/"
SYNTHETIC = "https://hypertodo-ci.invalid/hv/"
# What the old recipe parsed: a VPN tunnel is listed before the interface in use.
VPN_FIRST_IFCONFIG = """cat <<'EOF'
lo0: flags=8049<UP,LOOPBACK>
    inet 127.0.0.1 netmask 0xff000000
utun3: flags=8051<UP,POINTOPOINT>
    inet 100.64.0.9 --> 100.64.0.9 netmask 0xffffffff
en7: flags=8863<UP>
    inet 192.168.50.7 netmask 0xffffff00
EOF"""


def _stub(directory, name, body):
    path = directory / name
    path.write_text(f"#!/bin/bash\n{body}\n")
    path.chmod(0o755)


@pytest.fixture
def make(tmp_path):
    """Return a runner for make with fake tools first on PATH."""
    bin_dir, pinned_dir, nvm_dir = (tmp_path / n for n in ("bin", "pinned", "nvm"))
    for directory in (bin_dir, pinned_dir, nvm_dir):
        directory.mkdir()
    _stub(bin_dir, "corepack", 'echo "corepack $*"; env | grep ^EXPO_PUBLIC_ | sort')
    _stub(bin_dir, "node", "echo system node")
    _stub(bin_dir, "uv", "echo /stub/hxml_editor.js")
    _stub(
        pinned_dir,
        "node",
        'echo "pinned node $*"; echo "HXML_EDITOR_JS=$HXML_EDITOR_JS"',
    )
    # A host whose default route is en7 and whose VPN interface is listed first.
    _stub(bin_dir, "ifconfig", VPN_FIRST_IFCONFIG)
    _stub(bin_dir, "route", "echo '  interface: en7'")
    _stub(bin_dir, "ipconfig", '[[ "$*" == "getifaddr en7" ]] && echo 192.168.50.7')

    def run(*targets, nvm_status=0, **env):
        # Like nvm, put the pinned Node first on PATH; a missing version returns 3.
        use = (
            f'PATH="{pinned_dir}:$PATH"' if nvm_status == 0 else f"return {nvm_status}"
        )
        (nvm_dir / "nvm.sh").write_text(
            f'nvm() {{ echo "$*" >> "{tmp_path}/nvm.log"; {use}; }}\n'
        )
        return subprocess.run(
            ["make", "--no-print-directory", *targets],
            cwd=ROOT,
            env={
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "HOME": str(tmp_path),
                "NVM_DIR": str(nvm_dir),
                **env,
            },
            capture_output=True,
            text=True,
            timeout=30,
        )

    return run


@pytest.mark.parametrize(
    ("target", "api_url", "command"),
    [
        ("mobile-start", LOCAL, "yarn start"),
        ("mobile-start-android", EMULATOR, "yarn start"),
        ("mobile-start-device", DEVICE, "yarn start"),
        ("mobile-start-go", DEVICE, "yarn start:go"),
        ("mobile-ios", LOCAL, "yarn ios"),
        ("mobile-ios-device", DEVICE, "yarn expo run:ios --device"),
        ("mobile-android", EMULATOR, "yarn android"),
        ("mobile-android-device", DEVICE, "yarn expo run:android --device"),
    ],
)
def test_development_targets_opt_into_the_local_api(make, target, api_url, command):
    # app.config.ts refuses cleartext (and an unset URL) without this opt-in, so a
    # fresh clone without a private mobile/.env has to get both from the Makefile.
    result = make(target, LAN_IP=LAN_IP)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"corepack {command}",
        "EXPO_PUBLIC_ALLOW_LOCAL_API=1",
        f"EXPO_PUBLIC_API_URL={api_url}",
    ]


def test_doctor_validates_a_synthetic_https_api_whatever_the_shell_holds(make):
    # `make check` must work on a fresh clone, and a development URL exported by the
    # caller would be refused by the same guard once the opt-in is switched off.
    result = make(
        "mobile-doctor",
        EXPO_PUBLIC_API_URL=DEVICE,
        EXPO_PUBLIC_ALLOW_LOCAL_API="1",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "corepack yarn doctor",
        "EXPO_PUBLIC_ALLOW_LOCAL_API=0",
        f"EXPO_PUBLIC_API_URL={SYNTHETIC}",
    ]
    override = make("mobile-doctor", DOCTOR_API_URL="https://staging.example.test/hv/")
    assert "EXPO_PUBLIC_API_URL=https://staging.example.test/hv/" in override.stdout


def test_missing_node_stops_with_an_actionable_message(make):
    # `nvm use --silent` exits 3 without a word when the pinned version is absent.
    result = make("mobile-test", nvm_status=3)

    assert f"Node {NODE_VERSION} missing: run 'nvm install' in mobile/" in result.stderr
    assert "Error 1" in result.stderr and "Error 3" not in result.stderr
    assert "corepack" not in result.stdout


def test_missing_nvm_stops_with_an_actionable_message(make, tmp_path):
    result = make("mobile-test", NVM_DIR=str(tmp_path / "absent"))

    assert "nvm not found" in result.stderr and "NVM_DIR" in result.stderr
    assert "Error 1" in result.stderr
    assert "corepack" not in result.stdout


def test_editor_javascript_runs_on_the_pinned_node(make, tmp_path):
    result = make("backend-test-editor")

    assert result.returncode == 0, result.stderr
    node, editor = result.stdout.splitlines()
    assert node.startswith("pinned node --test tests/js/")
    assert editor == "HXML_EDITOR_JS=/stub/hxml_editor.js"
    assert (tmp_path / "nvm.log").read_text() == f"use --silent {NODE_VERSION}\n"


def test_lan_ip_follows_the_default_route_not_the_first_interface(make):
    result = make("lan-ip")

    assert result.returncode == 0, result.stderr
    assert result.stdout == "192.168.50.7\n"


@pytest.mark.parametrize("broken_tool", ["route", "ipconfig"])
def test_lan_ip_fails_clearly_without_a_default_route_address(
    make, tmp_path, broken_tool
):
    _stub(tmp_path / "bin", broken_tool, "exit 1")

    result = make("lan-ip")

    assert result.stdout == ""
    assert "No LAN address found" in result.stderr
    assert "Error 1" in result.stderr


def test_backend_gates_are_locked_and_check_formatting():
    # CI runs the same commands; `-n` prints the expansion without running anything.
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", "backend-install", "backend-lint"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )

    assert "uv sync --locked" in result.stdout
    assert "uv run ruff check ." in result.stdout
    assert "uv run ruff format --check ." in result.stdout
