"""Tests for post-cutover cleanup of the legacy distro dnsmasq path."""

import subprocess
import sys
from pathlib import Path


CLEANUP_SCRIPT = Path("scripts/snarkypuss-dns-cleanup.py")
MARKER = "disabled by Snarkypuss; bind-dynamic is used"


def prepare_legacy_root(tmp_path: Path) -> Path:
    root = tmp_path / "root"
    (root / "etc/dnsmasq.d").mkdir(parents=True)
    (root / "etc/systemd/system/dnsmasq.service.d").mkdir(parents=True)
    original = "# stock dnsmasq config\nbind-interfaces\n"
    modified = f"# stock dnsmasq config\n# bind-interfaces  # {MARKER}\n"
    (root / "etc/dnsmasq.conf.snarkypuss-original").write_text(original, encoding="utf-8")
    (root / "etc/dnsmasq.conf").write_text(modified, encoding="utf-8")
    (root / "etc/dnsmasq.d/snarkypuss.conf").write_text("bind-dynamic\n", encoding="utf-8")
    (root / "etc/systemd/system/dnsmasq.service.d/snarkypuss.conf").write_text(
        "[Unit]\nRequires=wg-quick@wg0.service\n", encoding="utf-8"
    )
    return root


def test_cleanup_dry_run_describes_restore_without_writing(tmp_path: Path) -> None:
    root = prepare_legacy_root(tmp_path)

    result = subprocess.run(  # noqa: S603 - repository script under test
        [sys.executable, str(CLEANUP_SCRIPT), "--root", str(root), "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "restore" in result.stdout.lower()
    assert "remove legacy Snarkypuss file" in result.stdout
    assert MARKER in (root / "etc/dnsmasq.conf").read_text(encoding="utf-8")
    assert (root / "etc/dnsmasq.d/snarkypuss.conf").exists()


def test_cleanup_apply_restores_original_and_removes_legacy_files(tmp_path: Path) -> None:
    root = prepare_legacy_root(tmp_path)

    subprocess.run(  # noqa: S603 - repository script under test
        [sys.executable, str(CLEANUP_SCRIPT), "--root", str(root), "--apply"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert (root / "etc/dnsmasq.conf").read_text(encoding="utf-8") == (
        "# stock dnsmasq config\nbind-interfaces\n"
    )
    assert not (root / "etc/dnsmasq.d/snarkypuss.conf").exists()
    assert not (root / "etc/systemd/system/dnsmasq.service.d/snarkypuss.conf").exists()
    assert (root / "etc/dnsmasq.conf.snarkypuss-original").exists()


def test_cleanup_refuses_to_overwrite_unrecognized_admin_change(tmp_path: Path) -> None:
    root = prepare_legacy_root(tmp_path)
    (root / "etc/dnsmasq.conf").write_text(
        "# administrator changed this after Snarkypuss\n", encoding="utf-8"
    )

    result = subprocess.run(  # noqa: S603 - repository script under test
        [sys.executable, str(CLEANUP_SCRIPT), "--root", str(root), "--apply"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "refusing to overwrite possible administrator changes" in result.stderr
    assert (root / "etc/dnsmasq.d/snarkypuss.conf").exists()


def test_cleanup_refuses_marker_without_saved_original(tmp_path: Path) -> None:
    root = prepare_legacy_root(tmp_path)
    (root / "etc/dnsmasq.conf.snarkypuss-original").unlink()

    result = subprocess.run(  # noqa: S603 - repository script under test
        [sys.executable, str(CLEANUP_SCRIPT), "--root", str(root), "--dry-run"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "saved original" in result.stderr
