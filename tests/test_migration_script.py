from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
MIGRATE = ROOT / "scripts" / "snarkypuss-migrate.py"
PRIVATE_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
PUBLIC_KEY = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA="


def gateway(root: Path) -> str:
    wireguard = root / "etc/wireguard"
    wireguard.mkdir(parents=True)
    original = (
        "[Interface]\n"
        "Address = 10.8.0.1/24\n"
        "ListenPort = 51820\n"
        f"PrivateKey = {PRIVATE_KEY}\n"
        "FwMark = 0xe1f1\n"
        "PostUp = iptables -A FORWARD -i wg0 -j ACCEPT\n"
        "PostDown = iptables -D FORWARD -i wg0 -j ACCEPT\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {PUBLIC_KEY}\n"
        "AllowedIPs = 10.8.0.2/32\n"
        "PersistentKeepalive = 30\n"
    )
    (wireguard / "wg0.conf").write_text(original, encoding="utf-8")
    dnsmasq = root / "etc/dnsmasq.d"
    dnsmasq.mkdir(parents=True)
    (dnsmasq / "legacy.conf").write_text("server=1.1.1.1\n", encoding="utf-8")
    return original


def command(root: Path, mode: str, *extra: str) -> list[str]:
    return [
        sys.executable,
        str(MIGRATE),
        mode,
        "--root",
        str(root),
        "--protected-egress-interface",
        "nordlynx",
        *extra,
    ]


def test_audit_reports_values_but_not_private_key(tmp_path: Path) -> None:
    gateway(tmp_path)
    result = subprocess.run(
        command(tmp_path, "--audit"),
        check=True,
        capture_output=True,
        text=True,
    )
    assert "Listen port: 51820" in result.stdout
    assert "Legacy WireGuard lifecycle hooks found: PostUp, PostDown" in result.stdout
    assert PRIVATE_KEY not in result.stdout
    assert not (tmp_path / "var/backups/snarkypuss").exists()


def test_prepare_preserves_identity_and_restore_recovers_files(
    tmp_path: Path, monkeypatch
) -> None:
    original = gateway(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    wg = fake_bin / "wg"
    wg.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = pubkey ]; then\n"
        f"  printf '%s\\n' '{PUBLIC_KEY}'\n"
        "  exit 0\n"
        "fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    wg.chmod(0o755)
    monkeypatch.setenv("PATH", f"{fake_bin}:{os.environ['PATH']}")

    result = subprocess.run(
        command(tmp_path, "--prepare"),
        check=True,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )
    assert "Live services, routes, firewall rules, and sysctl values were not changed." in (
        result.stdout
    )
    generated = (tmp_path / "etc/wireguard/wg0.conf").read_text(encoding="utf-8")
    assert f"PrivateKey = {PRIVATE_KEY}" in generated
    assert "PersistentKeepalive = 30" in generated
    assert "PostUp" not in generated
    assert (tmp_path / "etc/wireguard/wg0.private.key").read_text().strip() == PRIVATE_KEY
    assert (tmp_path / "etc/snarkypuss/client.pub").read_text().strip() == PUBLIC_KEY

    backups = list((tmp_path / "var/backups/snarkypuss").glob("migration-*"))
    assert len(backups) == 1
    manifest = json.loads(
        (backups[0] / "migration-manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["format"] == 1

    restore = subprocess.run(
        [
            sys.executable,
            str(MIGRATE),
            "--restore",
            str(backups[0]),
            "--root",
            str(tmp_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "File restoration complete" in restore.stdout
    assert (tmp_path / "etc/wireguard/wg0.conf").read_text(encoding="utf-8") == original
    assert not (tmp_path / "etc/wireguard/wg0.private.key").exists()
    assert not (tmp_path / "etc/snarkypuss-setup.conf").exists()
