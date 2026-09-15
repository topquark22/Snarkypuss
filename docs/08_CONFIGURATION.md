# SnarkyCtl Configuration Reference

## Purpose

This document is the reference for SnarkyCtl's persistent configuration: the main YAML
configuration file and the provider-scoped SQLite VPN destination catalogue.

The reference deployment uses these principal files:

| Path | Purpose |
|---|---|
| `/etc/snarkyctl/snarkyctl.yaml` | Main SnarkyCtl service configuration |
| `/var/lib/snarkyctl/targets.db` | Provider-scoped VPN destination catalogue |
| `/etc/snarkyctl/auth.htpasswd` | Dashboard HTTP Basic authentication database |
| `/etc/snarkyctl/tls/server.crt` | HTTPS server certificate |
| `/etc/snarkyctl/tls/server.key` | HTTPS server private key |

The example main configuration supplied by the repository is:

```text
config/snarkyctl.yaml.example
```

## 1. Complete main configuration example

The current example is:

```yaml
schema_version: 1

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

status:
  public_ip_url: https://api.ipify.org
  public_ip_timeout_seconds: 5

upstream_vpn:
  provider: nordvpn
  expected_interfaces:
    - nordlynx
  targets:
    backend: sqlite
    path: /var/lib/snarkyctl/targets.db
```

Unknown configuration keys are rejected. Paths documented below as absolute paths must be
absolute in the YAML file.

## 2. `schema_version`

```yaml
schema_version: 1
```

The main YAML document currently supports schema version `1` only. SnarkyCtl rejects an
unsupported version instead of silently rewriting the configuration.

The SQLite target database has a separate schema version. The YAML schema version and the
SQLite schema version are independent.

## 3. `network`

The `network` section describes the interfaces and private address range that define the
Snarkypuss management boundary.

### `network.management_interface`

```yaml
management_interface: wg0
```

The Linux interface used by the private client-to-VPS management tunnel. In the reference
deployment this is the WireGuard interface `wg0`.

The interface name must be a valid Linux interface name accepted by SnarkyCtl.

### `network.management_address`

```yaml
management_address: 10.8.0.1/24
```

The VPS address and prefix on the private management interface.

The address must belong to `network.client_subnet`.

### `network.client_subnet`

```yaml
client_subnet: 10.8.0.0/24
```

The IPv4 network containing the trusted WireGuard client and the VPS management address.

### `network.public_interface`

```yaml
public_interface: eth0
```

The VPS interface facing its ordinary public network.

`management_interface` and `public_interface` must be different interfaces.

Do not assume the public interface is always named `eth0`; use the actual interface name on
the VPS.

## 4. `web`

The `web` section configures the private HTTPS dashboard process.

### `web.bind_address`

```yaml
bind_address: 10.8.0.1
```

This value must exactly equal the IP portion of `network.management_address`.

For the reference deployment:

```text
network.management_address = 10.8.0.1/24
web.bind_address           = 10.8.0.1
```

Do not configure `0.0.0.0`, the Linode public IP, or another public address. SnarkyCtl is
intended to be reached through the private WireGuard network.

### `web.port`

```yaml
port: 8443
```

The private HTTPS TCP port. Valid values are `1` through `65535`.

The reference deployment uses `8443`. The Linode Firewall must not expose this port publicly.

### `web.auth_file`

```yaml
auth_file: /etc/snarkyctl/auth.htpasswd
```

Absolute path to the HTTP Basic authentication password file used by the dashboard.

### `web.tls_certificate`

```yaml
tls_certificate: /etc/snarkyctl/tls/server.crt
```

Absolute path to the HTTPS server certificate.

### `web.tls_private_key`

```yaml
tls_private_key: /etc/snarkyctl/tls/server.key
```

Absolute path to the corresponding private key. Protect this file as a secret.

### `web.request_timeout_seconds`

```yaml
request_timeout_seconds: 10
```

Maximum request/control wait used by the web layer. The configured value must be greater
than zero and no greater than 60 seconds.

## 5. `control`

The `control` section configures communication with the privileged SnarkyCtl control daemon.

### `control.socket_path`

```yaml
socket_path: /run/snarkyctl/control.sock
```

Absolute path to the systemd-managed Unix socket used between the unprivileged web process
and the privileged control daemon.

The reference installation uses `/run/snarkyctl/control.sock`.

### `control.operation_timeout_seconds`

```yaml
operation_timeout_seconds: 60
```

Maximum time allowed for privileged provider/control operations. The value must be greater
than zero and no greater than 300 seconds.

## 6. `status`

The `status` section configures read-only external status collection.

### `status.public_ip_url`

```yaml
public_ip_url: https://api.ipify.org
```

HTTPS endpoint used to observe the VPS's current public exit IPv4 address.

SnarkyCtl requires:

- `https` scheme,
- a valid hostname,
- no embedded username or password, and
- no URL fragment.

TLS verification uses the operating system trust store and is not disabled by configuration.

### `status.public_ip_timeout_seconds`

```yaml
public_ip_timeout_seconds: 5
```

Timeout for the external public-IP request. The value must be greater than zero and no
greater than 15 seconds.

If the entire `status` section is omitted, the current defaults are the public-IP URL above
and a 5-second timeout.

## 7. `upstream_vpn`

The `upstream_vpn` section selects the compiled VPN adapter and the target catalogue.

### `upstream_vpn.provider`

```yaml
provider: nordvpn
```

The provider name is a fixed registry identifier compiled into SnarkyCtl. It is **not** a
Python module name, executable path, shell command, or dynamically loaded plugin name.

A provider name that is not compiled into the installed SnarkyCtl release is rejected during
configuration validation.

Provider-specific configuration and behavior are documented separately. For the current
reference provider, see [07_NORDVPN.md](07_NORDVPN.md).

### `upstream_vpn.expected_interfaces`

```yaml
expected_interfaces:
  - nordlynx
```

Root-controlled allowlist of network-interface names that the selected provider is expected
to report as its protected tunnel interface.

The list:

- must contain at least one interface,
- may contain at most eight,
- must not contain duplicates, and
- must not overlap the configured management or public interface.

This field prevents an unexpected provider-reported interface from being accepted silently.

### `upstream_vpn.targets`

New deployments use the SQLite target catalogue:

```yaml
targets:
  backend: sqlite
  path: /var/lib/snarkyctl/targets.db
```

`backend` currently accepts only `sqlite`.

`path` must be an absolute filesystem path.

The reference path is:

```text
/var/lib/snarkyctl/targets.db
```

### Legacy `targets_file`

The current configuration parser still understands the older YAML target-file form through
`upstream_vpn.targets_file`. It exists for compatibility with earlier deployments.

Configure **exactly one** of:

```text
upstream_vpn.targets
upstream_vpn.targets_file
```

not both.

New deployments and the current documentation use the SQLite `targets` backend. Do not start
a new installation with the legacy YAML target catalogue.

## 8. Validate the main configuration

After changing `/etc/snarkyctl/snarkyctl.yaml`, validate it before restarting services:

```bash
sudo snarkyctl validate-config \
    --config /etc/snarkyctl/snarkyctl.yaml
```

The default path is already `/etc/snarkyctl/snarkyctl.yaml`, so this shorter form is also
valid:

```bash
sudo snarkyctl validate-config
```

Validation is side-effect free. It does not:

- connect or disconnect the upstream VPN,
- change provider settings,
- alter routes,
- modify firewall rules,
- start or stop services, or
- rewrite the configuration.

It validates the YAML structure, schema version, field types, paths, address relationships,
provider registry name, interface constraints, and configured target backend.

## 9. SQLite target catalogue

The target database is separate from the main YAML file because VPN destinations are
editable operational data.

The reference database is:

```text
/var/lib/snarkyctl/targets.db
```

The production database is opened by the privileged SnarkyCtl control daemon, not directly
by the network-facing web process. It is therefore intentionally root-controlled. Do not make
`targets.db` writable by the `snarkyctl` web-service user.

The supported initialization/check commands are:

```bash
sudo snarkyctl targets-db initialize
sudo snarkyctl targets-db check
```

For backup and restoration procedures, use [06_BACKUP_RECOVERY.md](06_BACKUP_RECOVERY.md)
rather than copying a live SQLite database directly.

## 10. Database organization

The current SQLite schema is provider-scoped.

At a conceptual level there are two related tables:

```text
provider_catalogues
    provider
    revision

targets
    provider
    alias
    label
    position
    selector_json
```

Each provider has its own catalogue revision.

Within `targets`:

- `(provider, alias)` is unique,
- `(provider, position)` is unique,
- aliases may therefore be reused by different providers,
- positions are ordered within one provider catalogue, and
- `selector_json` contains the provider-owned structured selector.

The ordinary dashboard/API does not need direct SQLite access and does not submit SQL.
Catalogue operations pass through the reviewed control interface.

## 11. Destination records

A destination has four important concepts:

### Alias

A stable short identifier used internally and by the CLI, for example:

```text
dallas
```

Aliases begin with a lowercase letter and may contain lowercase letters, digits, underscores,
and hyphens.

### Label

Human-readable display text, for example:

```text
Dallas, United States
```

The label is presentation text. It is not passed to the provider as an arbitrary command.

### Position

Zero-based ordering within the provider's catalogue. The stored positions are contiguous.

### Selector

Structured provider-owned data describing what the destination means.

For example, a provider may define selector kinds such as recommended, country, city, group,
or server. SnarkyCtl validates the selector through the compiled provider adapter before it
is stored or used.

The selector is **data**, not provider-supplied executable code. The browser does not submit
arbitrary shell fragments or executable paths.

## 12. Provider target schema

The active provider exposes reviewed schema metadata describing the target forms that the
generic dashboard may render.

The current field types are:

```text
text
choice
boolean
integer
```

The schema may define multiple selector kinds, each with its own fields.

This schema is provider-neutral metadata. The dashboard renders the form generically rather
than containing provider-specific HTML or JavaScript.

This document describes the currently implemented static schema behavior only. Planned
dynamic provider target discovery is development work and is not part of the current
configuration contract.

## 13. Administrative target commands

The target catalogue can also be inspected or replaced from the Linode command line.

List the current provider's targets:

```bash
sudo snarkyctl targets list
```

Show the active provider's target schema:

```bash
sudo snarkyctl targets schema
```

Export the full administrative catalogue:

```bash
sudo snarkyctl targets export > /root/targets.json
```

The export contains the provider, current catalogue revision, and complete structured target
records. Its revision is represented as `expected_revision` for a subsequent replacement.

To edit administratively:

```bash
sudoedit /root/targets.json
sudo snarkyctl targets replace /root/targets.json
```

Keep `expected_revision` unchanged while editing the exported document. If another session
changes the catalogue first, the replacement is rejected instead of silently overwriting the
newer catalogue. Re-export the current catalogue and repeat the edit.

Normal browser use does not require these administrative JSON operations; the dashboard's
**Manage VPN destinations** editor uses the same revision-safe catalogue model.

## 14. Important configuration invariants

A valid configuration must preserve these relationships:

- `network.management_interface` and `network.public_interface` are different.
- `network.management_address` belongs to `network.client_subnet`.
- `web.bind_address` exactly equals the management IPv4 address.
- `web.bind_address` is never a wildcard or public address in the supported deployment.
- upstream provider interfaces do not overlap management or public interfaces.
- configured filesystem paths that require absolute paths are absolute.
- `status.public_ip_url` is a safe HTTPS URL.
- the provider name is present in the compiled provider registry.
- exactly one target backend is configured.
- new deployments use the SQLite target backend.

Passing YAML validation confirms these structural rules. It does **not** by itself prove that
interfaces exist, services are running, the provider is connected, or traffic is protected.
Those live-system checks belong to preflight and operational verification.

## 15. File ownership and secrets

Configuration and state should follow least-privilege ownership.

Important rules are:

- `/etc/snarkyctl/snarkyctl.yaml` is administrator-controlled configuration.
- `/var/lib/snarkyctl/targets.db` is root-controlled state used by the privileged control
  daemon.
- the unprivileged `snarkyctl-web` process communicates with the control daemon through the
  Unix socket rather than opening the target database directly.
- `/etc/snarkyctl/tls/server.key` is a private key and must be protected accordingly.
- authentication hashes in `/etc/snarkyctl/auth.htpasswd` should be readable only by the
  processes that require them.
- NordVPN access tokens and WireGuard private keys do not belong in `snarkyctl.yaml` or the
  destination database.

The full process privilege boundary and systemd security model are documented in the
architecture reference later in this documentation series.

## 16. Change configuration safely

For an ordinary configuration change:

1. Back up important state when appropriate.
2. Edit `/etc/snarkyctl/snarkyctl.yaml` as root.
3. Run `snarkyctl validate-config`.
4. If validation fails, correct the file before restarting anything.
5. Restart only the service affected by the change when practical.
6. Verify SnarkyCtl status and the private dashboard afterward.

Do not use configuration editing as a shortcut around the safety model. In particular, do
not bind the dashboard publicly, bypass provider-interface checks, or weaken target-database
permissions merely to make a failing deployment appear operational.

## 17. Version behavior

The main YAML configuration and SQLite database are independently versioned.

Current main YAML:

```text
schema_version: 1
```

Current SQLite target database:

```text
schema version 1
```

Unsupported versions are rejected explicitly. Schema migration must be an intentional
administrative operation; SnarkyCtl does not silently reinterpret an unknown configuration
or database schema.
