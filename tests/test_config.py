"""Tests for typed, bounded configuration loading."""

from pathlib import Path

import pytest

from snarkyctl.config import ConfigError, load_config


def write_config(tmp_path: Path, *, provider: str = "nordvpn") -> Path:
    targets = tmp_path / "targets.yaml"
    targets.write_text(
        """schema_version: 1
targets:
  - alias: dallas
    label: Dallas
    provider_target: us
""",
        encoding="utf-8",
    )
    config = tmp_path / "snarkyctl.yaml"
    config.write_text(
        f"""schema_version: 1
network:
  management_interface: wg0
  management_address: 10.8.0.1/24
  client_subnet: 10.8.0.0/24
  public_interface: eth0
web:
  bind_address: 10.8.0.1
  port: 8443
  auth_file: /etc/snarkyctl/auth.htpasswd
  tls_certificate: /etc/snarkyctl/tls/server.crt
  tls_private_key: /etc/snarkyctl/tls/server.key
  request_timeout_seconds: 10
control:
  socket_path: /run/snarkyctl/control.sock
  operation_timeout_seconds: 60
upstream_vpn:
  provider: {provider}
  expected_interfaces: [nordlynx]
  targets_file: {targets}
""",
        encoding="utf-8",
    )
    return config


def test_load_valid_config(tmp_path: Path) -> None:
    loaded = load_config(write_config(tmp_path))
    assert loaded.settings.upstream_vpn.provider == "nordvpn"
    assert loaded.settings.status.public_ip_url == "https://api.ipify.org"
    assert loaded.targets.targets[0].alias == "dallas"


def test_unknown_provider_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="provider is not compiled"):
        load_config(write_config(tmp_path, provider="openvpn"))


def test_public_bind_address_is_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        "bind_address: 10.8.0.1", "bind_address: 0.0.0.0"
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="bind_address"):
        load_config(path)


def test_insecure_public_ip_url_is_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        "upstream_vpn:",
        "status:\n  public_ip_url: http://api.ipify.org\n\nupstream_vpn:",
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match="HTTPS URL"):
        load_config(path)


def test_public_ip_url_with_invalid_port_is_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        "upstream_vpn:",
        "status:\n  public_ip_url: https://api.ipify.org:bad\n\nupstream_vpn:",
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid port"):
        load_config(path)


def test_duplicate_target_alias_is_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    targets = tmp_path / "targets.yaml"
    targets.write_text(
        targets.read_text(encoding="utf-8")
        + "  - alias: dallas\n    label: Other\n    provider_target: ca\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="aliases must be unique"):
        load_config(path)


def test_symlink_is_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    link = tmp_path / "linked.yaml"
    link.symlink_to(path)
    with pytest.raises(ConfigError, match="cannot open"):
        load_config(link)


def test_non_mapping_yaml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- item\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="top level"):
        load_config(path)
