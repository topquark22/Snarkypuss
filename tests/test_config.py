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
    provider_config = loaded.settings.upstream_vpn.active_provider_config()
    assert provider_config.provider == "nordvpn"
    assert provider_config.executable == Path("/usr/bin/nordvpn")
    assert provider_config.expected_interfaces == ("nordlynx",)
    assert loaded.settings.status.public_ip_url == "https://api.ipify.org"
    assert loaded.targets is not None
    assert loaded.targets.targets[0].alias == "dallas"


def test_explicit_sqlite_backend_does_not_load_yaml(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    database = tmp_path / "targets.db"
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        f"  targets_file: {tmp_path / 'targets.yaml'}",
        f"  targets:\n    backend: sqlite\n    path: {database}",
    )
    path.write_text(text, encoding="utf-8")
    loaded = load_config(path)
    assert loaded.targets is None
    assert loaded.settings.upstream_vpn.targets is not None
    assert loaded.settings.upstream_vpn.targets.path == database


def test_target_backend_must_be_explicit_and_unambiguous(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        "  targets_file:",
        f"  targets:\n    backend: sqlite\n    path: {tmp_path / 'targets.db'}\n"
        "  targets_file:",
    )
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="exactly one"):
        load_config(path)


def test_unknown_provider_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="provider is not compiled"):
        load_config(write_config(tmp_path, provider="openvpn"))


def test_typed_nordvpn_provider_configuration(tmp_path: Path) -> None:
    path = write_config(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        "  expected_interfaces: [nordlynx]\n",
        """  providers:
    nordvpn:
      executable: /opt/nordvpn/bin/nordvpn
      service: nordvpnd.service
      expected_interfaces: [nordlynx]
""",
    )
    path.write_text(text, encoding="utf-8")

    provider_config = load_config(path).settings.upstream_vpn.active_provider_config()

    assert provider_config.provider == "nordvpn"
    assert provider_config.executable == Path("/opt/nordvpn/bin/nordvpn")
    assert provider_config.expected_interfaces == ("nordlynx",)


def test_duplicate_global_and_provider_interface_configuration_is_rejected(
    tmp_path: Path,
) -> None:
    path = write_config(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        "  targets_file:",
        """  providers:
    nordvpn:
      expected_interfaces: [nordlynx]
  targets_file:""",
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError, match="both globally and"):
        load_config(path)


def test_inactive_mullvad_configuration_is_typed_but_not_compiled(
    tmp_path: Path,
) -> None:
    path = write_config(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        "  targets_file:",
        """  providers:
    mullvad:
      executable: /usr/bin/mullvad
      service: mullvad-daemon.service
      expected_interfaces: []
  targets_file:""",
    )
    path.write_text(text, encoding="utf-8")

    loaded = load_config(path)

    assert loaded.settings.upstream_vpn.providers.mullvad is not None
    assert loaded.settings.upstream_vpn.providers.mullvad.provider == "mullvad"
    assert loaded.settings.upstream_vpn.provider == "nordvpn"


@pytest.mark.parametrize(
    "provider_block",
    [
        """nordvpn:
      executable: relative/nordvpn
      service: nordvpnd.service
""",
        """nordvpn:
      executable: /usr/bin/nordvpn
      service: ../../unsafe.service
""",
        """nordvpn:
      executable: /usr/bin/nordvpn
      service: nordvpnd.service
      arbitrary_command: ip route flush table main
""",
    ],
)
def test_unsafe_or_unknown_provider_configuration_is_rejected(
    tmp_path: Path, provider_block: str
) -> None:
    path = write_config(tmp_path)
    text = path.read_text(encoding="utf-8").replace(
        "  targets_file:", f"  providers:\n    {provider_block}  targets_file:"
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config(path)


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
