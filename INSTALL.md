# Installing SnarkyCtl

> **Status:** Development installation procedure for the implemented application, control
> daemon, API, and read-only dashboard. Debian packaging and automated upgrades remain to
> be completed.

## Scope

This document installs SnarkyCtl on the existing `snarkypuss` gateway. It does not build the underlying WireGuard, NordVPN, DNS, routing, or firewall configuration from scratch; that is documented in [SNARKYPUSS.md](SNARKYPUSS.md).

The dependency installation below is intentionally non-destructive. It installs packages but does not change routes, firewall rules, WireGuard configuration, NordVPN settings, DNS configuration, or service startup policy.

---

## Supported Platform

The initial supported server platform is:

- Ubuntu Server 24.04 LTS
- A working WireGuard interface named `wg0`
- WireGuard server address `10.8.0.1`
- A working NordVPN Linux CLI installation
- `systemd`
- Administrative access through SSH over WireGuard

SnarkyCtl may work on other Debian-derived distributions, but the initial installation procedure and package names are written for Ubuntu 24.04 LTS.

---

## Safety Requirements

Before installation:

- Keep the current SSH session open while testing network-related changes.
- Confirm that a second administrative session can reach `10.8.0.1` through WireGuard.
- Take a Linode snapshot or otherwise back up the current gateway configuration.
- Do not expose TCP port `8443` on the Linode Cloud Firewall or the VPS public firewall.
- Do not change NordVPN, WireGuard, routing, or firewall settings merely to make the dashboard work.

Back up at least:

```text
/etc/wireguard/
/etc/dnsmasq.conf
/etc/iptables/
/etc/nftables.conf
/etc/sysctl.conf
/etc/sysctl.d/
```

Some paths may not exist on every installation.

---

## Linux Packages

### Required packages

| Package | Purpose |
|---|---|
| `apache2-utils` | Supplies `htpasswd` for creating the HTTP Basic authentication file. It does not install or enable the Apache web server. |
| `ca-certificates` | Validates HTTPS connections, including public-IP lookups and package downloads. |
| `curl` | Installation and network diagnostics; also provides a simple independent exit-IP check. |
| `git` | Retrieves and updates the SnarkyCtl repository. |
| `iproute2` | Supplies `ip` and `ss` for interface, route, policy-routing, and listener inspection. |
| `openssl` | Creates and inspects the private CA and HTTPS certificates. |
| `python3` | Runs the SnarkyCtl application. |
| `python3-pip` | Installs Python application dependencies inside the virtual environment. |
| `python3-venv` | Creates an isolated Python virtual environment. |
| `sudo` | Runs installation and service-management commands as an administrator. The `snarkyctl` service account does not receive sudo privileges. |
| `wireguard-tools` | Supplies `wg` and `wg-quick` status tools. |

The base Ubuntu installation already supplies `systemd` and `systemctl`; they are not installed separately here.

### Gateway prerequisites

The following are required by the gateway, but are not installed by the SnarkyCtl dependency command because they should already be configured and working:

| Component | Expected command or service | Notes |
|---|---|---|
| NordVPN Linux client | `nordvpn`, `nordvpnd.service` | Installed from NordVPN's repository or installer, not Ubuntu's standard package set. |
| WireGuard configuration | `wg0`, `wg-quick@wg0.service` | Must remain reachable independently of NordVPN. |
| Firewall and NAT | `iptables` and/or `nft` | SnarkyCtl must first detect and document the gateway's actual ruleset. |
| DNS service | `dnsmasq.service` | Optional for the first SnarkyCtl release; existing gateway DNS must continue working. |

Do not install or switch firewall frameworks during the SnarkyCtl installation. In particular, installing additional persistence packages or replacing existing `iptables`/`nftables` rules is outside the application installer's scope.

### Optional diagnostic packages

These are useful during development and troubleshooting but are not required by the application:

| Package | Purpose |
|---|---|
| `dnsutils` | Supplies `dig` for DNS checks. |
| `jq` | Formats and queries JSON API responses. |
| `tcpdump` | Confirms which interface carries management and forwarded traffic. |
| `traceroute` | Helps inspect the active exit path. |

---

## Install the Required Packages

Run as an administrator:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends \
    apache2-utils \
    ca-certificates \
    curl \
    git \
    iproute2 \
    openssl \
    python3 \
    python3-pip \
    python3-venv \
    sudo \
    wireguard-tools
```

To include the optional diagnostic tools:

```bash
sudo apt-get install --yes --no-install-recommends \
    dnsutils \
    jq \
    tcpdump \
    traceroute
```

The use of `--no-install-recommends` keeps the VPS installation small and predictable. It does not remove any existing package.

---

## Verify the Host Dependencies

Run:

```bash
python3 --version
git --version
openssl version
ip -Version
wg --version
sudo --version
```

Confirm that the existing gateway components are available:

```bash
systemctl is-active wg-quick@wg0
systemctl is-active nordvpnd
wg show wg0
nordvpn status
ip -brief address show wg0
```

The expected WireGuard address is:

```text
10.8.0.1/24
```

Do not continue to remote control implementation if `wg0` is unavailable or if connecting and disconnecting NordVPN breaks the WireGuard management path.

---

## Python Application Dependencies

FastAPI and the other Python libraries are application dependencies, not Ubuntu packages.
They are declared in `pyproject.toml` and installed together inside the private SnarkyCtl
virtual environment.

| Python package | Purpose |
|---|---|
| `fastapi` | Defines the authenticated dashboard and versioned HTTP API routes. |
| `uvicorn` | Runs the FastAPI application as the HTTPS ASGI server. |
| `jinja2` | Renders the initial dashboard HTML template. |
| `bcrypt` | Verifies password hashes in the local `auth.htpasswd` file. |
| `pydantic` | Strictly validates configuration, control messages, and API models. |
| `PyYAML` | Parses the root-owned YAML configuration and target allowlist. |

FastAPI also requires libraries such as Starlette and AnyIO. They are transitive
dependencies and are installed automatically. Do not install them individually or maintain
a separate hand-written dependency list.

The project currently constrains Python to version 3.12. Ubuntu 24.04 supplies Python 3.12
through its standard `python3` packages.

## Build and Install the Python Application

Run these commands from the root of a clean SnarkyCtl repository checkout.

### 1. Build the wheel

Create a temporary build environment owned by the current administrator:

```bash
python3 -m venv .build-venv
.build-venv/bin/python -m pip install --upgrade pip
.build-venv/bin/python -m pip install build
.build-venv/bin/python -m build
```

This creates both a wheel and source archive under `dist/`. The wheel contains the Python
code, dashboard template, CSS, and JavaScript. The build environment is not used to run the
service.

For development and testing, install the declared development tools instead:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install --editable '.[dev]'
.venv/bin/pytest
```

The development extra adds Build, HTTPX, mypy, pytest, coverage support, Ruff, and YAML type
information. None of these tools is required by the deployed service.

### 2. Create the production virtual environment

The existing systemd units expect the production environment at
`/usr/lib/snarkyctl/venv`:

```bash
sudo install -d -o root -g root -m 0755 /usr/lib/snarkyctl
sudo python3 -m venv /usr/lib/snarkyctl/venv
sudo /usr/lib/snarkyctl/venv/bin/python -m pip install --upgrade pip
sudo /usr/lib/snarkyctl/venv/bin/python -m pip install dist/snarkyctl-*.whl
```

Installing the wheel installs FastAPI, Uvicorn, Jinja2, bcrypt, Pydantic, PyYAML, and their
required transitive dependencies into that virtual environment. It does not modify
Ubuntu's system Python.

The wheel and its dependencies are root-owned. The `snarkyctl` service account may execute
them but must not be able to modify them.

### 3. Verify the Python installation

Run:

```bash
/usr/lib/snarkyctl/venv/bin/python -m pip check
/usr/lib/snarkyctl/venv/bin/python -c \
  "import bcrypt, fastapi, jinja2, pydantic, uvicorn, yaml; print('Python dependencies OK')"
/usr/lib/snarkyctl/venv/bin/snarkyctl --version
```

`pip check` must report that no installed packages have broken requirements.

Do not run Uvicorn manually on `0.0.0.0`. The packaged systemd service binds it only to the
private WireGuard address and supplies the configured TLS certificate and key.

---

## Application Installation Stages

The complete deployment follows these stages.

### 1. Record the network baseline

Capture interfaces, routes, policy rules, firewall rules, WireGuard state, NordVPN settings, service names, and representative command output. This establishes the control-path invariant before any state-changing endpoint is introduced.

### 2. Obtain the application

Build from a clean repository checkout. Installed application files and the production
virtual environment live under:

```text
/usr/lib/snarkyctl
```

The runtime account does not own or modify the repository, installed wheel, or virtual
environment.

### 3. Create the Python environment

The production virtual environment lives at:

```text
/usr/lib/snarkyctl/venv
```

Install the built wheel as described above. Runtime dependency constraints remain
authoritative in `pyproject.toml`; development tools are not installed in production.

### 4. Create the service account

Create the non-interactive `snarkyctl` system account. Application code remains owned by
`root:root` and is not writable by this account.

### 5. Install configuration and the privileged daemon

Install the root-owned configuration, authoritative target allowlist, systemd-activated
control socket, and privileged control daemon. The web service receives no `sudo`
permission; it communicates with the daemon only through `/run/snarkyctl/control.sock`.

Run the following commands from the root of the SnarkyCtl repository checkout.

#### 5.1 Confirm the prerequisites

Confirm that the service account and installed application exist:

```bash
getent passwd snarkyctl
getent group snarkyctl
/usr/lib/snarkyctl/venv/bin/snarkyctl --version
systemctl is-active wg-quick@wg0
command -v nordvpn
```

The `snarkyctl` account must have `snarkyctl` as its primary group and a non-interactive
shell. The current systemd unit assumes that WireGuard is managed by
`wg-quick@wg0.service`. Stop here if that service is not active; do not let installation
replace or disrupt a working management tunnel.

For the initial NordVPN adapter, `command -v nordvpn` should print `/usr/bin/nordvpn`.

#### 5.2 Install the configuration templates

Create the configuration directory and install editable copies of the example files:

```bash
sudo install -d -o root -g snarkyctl -m 0750 /etc/snarkyctl
sudo install -o root -g snarkyctl -m 0640 \
    config/snarkyctl.yaml.example \
    /etc/snarkyctl/snarkyctl.yaml
sudo install -o root -g snarkyctl -m 0640 \
    config/targets.yaml.example \
    /etc/snarkyctl/targets.yaml
```

Both files are writable only by root. Group read access is necessary because the
unprivileged web service reads the same validated configuration when it starts.

#### 5.3 Edit the main configuration

First identify the VPS public interface:

```bash
ip route show default
ip -brief address show wg0
```

Then edit:

```bash
sudoedit /etc/snarkyctl/snarkyctl.yaml
```

At minimum, verify these values:

```yaml
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

control:
  socket_path: /run/snarkyctl/control.sock

upstream_vpn:
  provider: nordvpn
  expected_interfaces:
    - nordlynx
  targets_file: /etc/snarkyctl/targets.yaml
```

Replace `eth0` if the default route reports a different public interface. Do not change
`web.bind_address` to `0.0.0.0` or to the public address.

If NordVPN is configured to use a technology with an interface other than `nordlynx`,
record the actual expected interface instead. This is an allowlist, not a command.

#### 5.4 Configure target aliases

Edit:

```bash
sudoedit /etc/snarkyctl/targets.yaml
```

Each entry maps a short user-facing alias to the exact argument passed to the configured
provider. For example:

```yaml
schema_version: 1

targets:
  - alias: dallas
    label: Dallas, United States
    provider_target: us

  - alias: prague
    label: Prague, Czechia
    provider_target: cz
```

Aliases may contain lowercase letters, digits, underscores, and hyphens, and must begin
with a letter. The browser and CLI submit only the alias. The root-owned file determines
the provider target, preventing a web request from supplying arbitrary command arguments.

Restore the required ownership and permissions after editing:

```bash
sudo chown root:snarkyctl \
    /etc/snarkyctl/snarkyctl.yaml \
    /etc/snarkyctl/targets.yaml
sudo chmod 0640 \
    /etc/snarkyctl/snarkyctl.yaml \
    /etc/snarkyctl/targets.yaml
```

#### 5.5 Validate the configuration

Run the validator as root:

```bash
sudo /usr/lib/snarkyctl/venv/bin/snarkyctl validate-config \
    --config /etc/snarkyctl/snarkyctl.yaml
```

Expected output resembles:

```text
Configuration is valid: provider=nordvpn, targets=2
```

This validates both YAML files, the schema, provider registry name, interface-name syntax,
path requirements, and unique target aliases. It does not connect or disconnect the VPN.

#### 5.6 Install the control units

Install the unit source files:

```bash
sudo install -o root -g root -m 0644 \
    systemd/snarkyctl-control.socket \
    /usr/lib/systemd/system/snarkyctl-control.socket
sudo install -o root -g root -m 0644 \
    systemd/snarkyctl-control.service \
    /usr/lib/systemd/system/snarkyctl-control.service
```

Check their syntax before loading them:

```bash
sudo systemd-analyze verify \
    /usr/lib/systemd/system/snarkyctl-control.socket \
    /usr/lib/systemd/system/snarkyctl-control.service
```

Warnings about other unrelated units can be reviewed separately. Errors naming either
SnarkyCtl unit must be corrected before continuing.

#### 5.7 Start socket activation

Reload systemd and enable the socket:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now snarkyctl-control.socket
sudo systemctl status snarkyctl-control.socket --no-pager
```

Do not start `snarkyctl-control.service` directly. The socket unit creates
`/run/snarkyctl/control.sock`; the first client request then starts the privileged daemon
and passes the already-open socket to it.

Verify the socket:

```bash
sudo stat -c '%A %U:%G %n' /run/snarkyctl/control.sock
sudo ss -xlpn | grep /run/snarkyctl/control.sock
```

The expected owner, group, and mode are:

```text
srw-rw---- root:snarkyctl /run/snarkyctl/control.sock
```

#### 5.8 Test the daemon connection

Run the status request as the unprivileged service account:

```bash
sudo -u snarkyctl /usr/lib/snarkyctl/venv/bin/snarkyctl status
```

This is an end-to-end test of socket permissions, systemd activation, request framing, peer
authentication, the privileged daemon, and the NordVPN adapter. It is read-only and does
not connect or disconnect NordVPN.

After the request, inspect the daemon:

```bash
sudo systemctl status snarkyctl-control.service --no-pager
sudo journalctl -u snarkyctl-control.service -n 50 --no-pager
```

If the request fails, leave the WireGuard and VPN configuration unchanged. Collect:

```bash
sudo systemctl status snarkyctl-control.socket snarkyctl-control.service --no-pager
sudo journalctl -u snarkyctl-control.service -n 100 --no-pager
sudo ls -ld /run/snarkyctl
sudo ls -l /run/snarkyctl/control.sock
sudo -u snarkyctl test -r /etc/snarkyctl/snarkyctl.yaml
sudo -u snarkyctl test -r /etc/snarkyctl/targets.yaml
```

The last two commands produce no output when the files are readable; inspect their exit
status with `echo $?` immediately after each command if necessary.

### 6. Install authentication and certificates

Create the root-controlled `auth.htpasswd` file for HTTP Basic authentication, followed by the private certificate authority and server certificate. Trust the CA on the Windows management computer. The certificate will include the chosen private hostname and, if used directly, `10.8.0.1` as an IP Subject Alternative Name.

### 7. Install the systemd service

Install `snarkyctl-control.socket`, `snarkyctl-control.service`, and
`snarkyctl-web.service`. Bind Uvicorn only to:

```text
10.8.0.1:8443
```

### 8. Verify private reachability

Confirm all of the following:

- The dashboard is reachable over WireGuard.
- Nothing listens on the VPS public address at TCP port `8443`.
- Authentication is required.
- The HTTPS certificate is trusted by the Windows browser.
- NordVPN transitions do not interrupt the management path.
- Unexpected NordVPN failure leaves forwarded traffic Locked rather than exposing the VPS public IP.

### 9. Enable state-changing controls

Only after the earlier checks pass, enable the restricted NordVPN and operating-mode endpoints. Direct VPS mode must require deliberate confirmation and must display a persistent public-IP exposure warning.

---

## Installation Paths

The planned filesystem locations are:

| Path | Purpose | Ownership |
|---|---|---|
| `/usr/lib/snarkyctl/` | Installed wheel and production virtual environment | `root:root` |
| `/etc/snarkyctl/` | Configuration, authentication, TLS, and authoritative allowlists | `root:snarkyctl` or `root:root`, mode-dependent |
| `/etc/snarkyctl/auth.htpasswd` | HTTP Basic username and salted password hash | `root:snarkyctl`, mode `0640` |
| `/run/snarkyctl/control.sock` | Web-to-daemon control socket | systemd-managed, group `snarkyctl` |
| `/var/lib/snarkyctl/` | Optional persistent policy state | `root:root` |
| `/etc/systemd/system/snarkyctl-*.service` | Service definitions | `root:root` |
| `/etc/systemd/system/snarkyctl-control.socket` | Socket activation definition | `root:root` |

The service account must not be able to modify application code, daemon code, service
definitions, certificate private keys, or the authoritative target allowlist.

---

## Not Yet Implemented

The following installation pieces will be filled in as their corresponding application components are created:

- Pinned Python dependency file.
- Service-account creation script.
- HTTP Basic auth-file generation and password-change procedure.
- Private CA and server-certificate generation procedure.
- Installation verification script.
- Upgrade, rollback, and removal procedures.

Until those components exist, this document should be treated as the dependency and installation framework rather than a complete production installer.
