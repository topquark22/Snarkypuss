# Installing SnarkyCtl

> **Status:** Development installation procedure for the implemented application, control
> daemon, API, and read-only dashboard. A development Debian package is now available;
> clean-host lifecycle testing and reproducible dependency locking remain to be completed.

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
| `python3-build` | Builds the Python wheel used for development and package verification. |
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
    python3-build \
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

## Build the Debian Package

The preferred deployment artifact is an `amd64` Debian package. The package contains the
application virtual environment, the command-line entry point, all three systemd units,
documentation, and configuration examples. Installing it does not contact PyPI and does
not enable or start any SnarkyCtl unit.

Build on Ubuntu 24.04 with:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends \
    build-essential \
    debhelper \
    devscripts \
    dh-virtualenv \
    lintian \
    python3-dev \
    python3-pip \
    python3-venv
scripts/build-deb.sh
```

The build itself currently needs network access so `dh-virtualenv` can resolve the bounded
Python dependency ranges in `pyproject.toml`. This is acceptable for the development
package, but a stable release additionally requires a committed, hash-verified dependency
lock. Package installation never runs `pip` or accesses PyPI.

The PEP 440 development version `0.1.0.dev2` maps to Debian version
`0.1.0~dev2-1`. The tilde ensures that the development package sorts before the eventual
`0.1.0-1` release. The build helper refuses to continue if `pyproject.toml` and
`debian/changelog` do not match.

After a successful build, inspect the artifact created in the parent directory:

```bash
dpkg-deb --info ../snarkyctl_0.1.0~dev2-1_amd64.deb
dpkg-deb --contents ../snarkyctl_0.1.0~dev2-1_amd64.deb
lintian ../snarkyctl_0.1.0~dev2-1_amd64.deb
```

Install it with:

```bash
sudo apt-get install ./../snarkyctl_0.1.0~dev2-1_amd64.deb
```

The package creates the `snarkyctl` system account and the empty directories
`/etc/snarkyctl`, `/etc/snarkyctl/tls`, and `/var/lib/snarkyctl`. It deliberately does not
create live configuration, an authentication file, or TLS keys. Copy the examples and
continue with Sections 5 through 7:

```bash
sudo install -o root -g snarkyctl -m 0640 \
    /usr/share/doc/snarkyctl/examples/snarkyctl.yaml.example \
    /etc/snarkyctl/snarkyctl.yaml
sudo install -o root -g snarkyctl -m 0640 \
    /usr/share/doc/snarkyctl/examples/targets.yaml.example \
    /etc/snarkyctl/targets.yaml
```

The manual wheel and unit installation below remains useful to developers and explains
each installed component. When deploying the `.deb`, skip the manual virtual-environment,
service-account, and unit-copy commands because the package has already performed those
steps.

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

Capture interfaces, routes, policy rules, firewall rules, WireGuard state, NordVPN settings,
and service status before changing the installation:

```bash
sudo install -d -o root -g root -m 0700 /root/snarkyctl-baseline
ip -brief address | sudo tee /root/snarkyctl-baseline/ip-address.txt >/dev/null
ip route show table all | sudo tee /root/snarkyctl-baseline/ip-routes.txt >/dev/null
ip rule show | sudo tee /root/snarkyctl-baseline/ip-rules.txt >/dev/null
sudo wg show all | sudo tee /root/snarkyctl-baseline/wireguard.txt >/dev/null
sudo nordvpn status | sudo tee /root/snarkyctl-baseline/nordvpn-status.txt >/dev/null
sudo nordvpn settings | sudo tee /root/snarkyctl-baseline/nordvpn-settings.txt >/dev/null
sudo systemctl status wg-quick@wg0 nordvpnd --no-pager \
    | sudo tee /root/snarkyctl-baseline/services.txt >/dev/null
```

Capture the active firewall with the tool already used by the gateway:

```bash
sudo nft list ruleset | sudo tee /root/snarkyctl-baseline/nftables.txt >/dev/null
sudo iptables-save | sudo tee /root/snarkyctl-baseline/iptables.txt >/dev/null
```

One of the last two commands may be inapplicable. Do not install or switch firewall
frameworks merely to make both commands work. These files may contain private addresses and
network metadata; keep the directory root-only.

### 2. Obtain the application

Build from a clean repository checkout. Installed application files and the production
virtual environment live under:

```text
/usr/lib/snarkyctl
```

The runtime account does not own or modify the repository, installed wheel, or virtual
environment.

The checkout is a build input, not the runtime application directory. Do not copy the Git
checkout into `/usr/lib/snarkyctl` and do not run the service from a root-owned home
directory. The wheel installation in the earlier section places the importable package in
the production virtual environment.

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

On Ubuntu, run:

```bash
sudo adduser --system \
    --group \
    --no-create-home \
    --home /nonexistent \
    --shell /usr/sbin/nologin \
    snarkyctl
id snarkyctl
getent passwd snarkyctl
```

If the account already exists, do not recreate it. Confirm that its primary group is
`snarkyctl`, it has no usable home directory, and its shell is `/usr/sbin/nologin`.
Do not add it to `sudo`, `adm`, or another privileged group.

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
sudo /usr/bin/nordvpn status
sudo /usr/bin/nordvpn settings
```

The `snarkyctl` account must have `snarkyctl` as its primary group and a non-interactive
shell. The current systemd unit assumes that WireGuard is managed by
`wg-quick@wg0.service`. Stop here if that service is not active; do not let installation
replace or disrupt a working management tunnel.

For the initial NordVPN adapter, `command -v nordvpn` should print `/usr/bin/nordvpn`.
The daemon runs the NordVPN CLI as root, so the two `sudo /usr/bin/nordvpn` checks are the
relevant execution context. Confirm that the output is the same provider configuration
that currently protects the gateway.

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

status:
  public_ip_url: https://api.ipify.org
  public_ip_timeout_seconds: 5

upstream_vpn:
  provider: nordvpn
  expected_interfaces:
    - nordlynx
  targets_file: /etc/snarkyctl/targets.yaml
```

Replace `eth0` if the default route reports a different public interface. Do not change
`web.bind_address` to `0.0.0.0` or to the public address.

`status.public_ip_url` must be an HTTPS endpoint that returns only the caller's IPv4
address as plain text. SnarkyCtl verifies the server certificate using the operating
system trust store; there is no option to disable verification. It skips the external
request in `LOCKED` and indeterminate gateway modes.

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

The example `provider_target` values are broad country selectors. If an alias is intended
to select a particular city or server, replace the value with the exact provider argument
already accepted by the installed VPN client. SnarkyCtl passes that one configured value
as one argument; it does not interpret shell quoting, spaces, or additional options.

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

The control daemon runs as a capability-restricted root service. Its supplementary
`nordvpn` group grants access to the NordVPN daemon socket without restoring broad
root filesystem privileges. `HOME` and `XDG_CONFIG_HOME` point to the writable
`/var/lib/snarkyctl` state directory so that the NordVPN CLI does not try to create
configuration under `/root`, which is intentionally blocked by `ProtectHome=true`.
Confirm that the installed control service contains:

```ini
SupplementaryGroups=nordvpn
Environment=HOME=/var/lib/snarkyctl
Environment=XDG_CONFIG_HOME=/var/lib/snarkyctl/.config
```

#### 5.7 Start socket activation

The canonical socket path is:

```text
/run/snarkyctl/control.sock
```

It is `control.sock`, not `snarkyctl.sock`. The `/run/snarkyctl` directory normally does
not exist yet. `/run` is volatile and is recreated at boot, so do not create this directory
as permanent installation state. When the socket unit starts, systemd creates the parent
directory using `DirectoryMode=0755`, then creates the socket as
`root:snarkyctl` with mode `0660`.

Reload systemd, enable the socket for future boots, and start it for the current boot:

```bash
sudo systemctl daemon-reload
sudo systemctl enable snarkyctl-control.socket
sudo systemctl start snarkyctl-control.socket
sudo systemctl status snarkyctl-control.socket --no-pager
```

`systemctl enable` alone does not start an inactive unit; it only arranges for it to start
on subsequent boots. The separate `systemctl start` command is therefore required during
this manual installation. The status should report `Active: active (listening)`.

Do not start `snarkyctl-control.service` directly. The socket unit creates
`/run/snarkyctl/control.sock`; the first client request then starts the privileged daemon
and passes the already-open socket to it.

If `/run/snarkyctl` is still absent after the commands above, the socket unit did not start.
Do not work around that by creating a differently named socket. Check the installed unit,
the required group, and the socket journal:

```bash
getent group snarkyctl
sudo systemctl cat snarkyctl-control.socket
sudo systemctl status snarkyctl-control.socket --no-pager
sudo journalctl -u snarkyctl-control.socket -n 50 --no-pager
```

The installed unit must contain:

```ini
ListenStream=/run/snarkyctl/control.sock
SocketUser=root
SocketGroup=snarkyctl
SocketMode=0660
DirectoryMode=0755
```

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

Create the root-controlled `auth.htpasswd` file, followed by the private certificate
authority and server certificate. SnarkyCtl has no user database, login page, plaintext
password file, or server-side session store.

#### 6.1 Create the Basic-auth record

The `apache2-utils` package installed earlier supplies `htpasswd`. Create the first
administrator record interactively:

```bash
sudo htpasswd -cB -C 12 /etc/snarkyctl/auth.htpasswd snarkadmin
sudo chown root:snarkyctl /etc/snarkyctl/auth.htpasswd
sudo chmod 0640 /etc/snarkyctl/auth.htpasswd
```

`-B` selects bcrypt and `-C 12` selects its work factor. Do not use `htpasswd -b`; that
option places the plaintext password in the shell command and possibly its history and
process list.

Verify the password interactively:

```bash
sudo htpasswd -v /etc/snarkyctl/auth.htpasswd snarkadmin
sudo -u snarkyctl test -r /etc/snarkyctl/auth.htpasswd
echo $?
```

The first command prompts for the password and should report that it is correct. The final
exit status should be `0`, confirming that the web account can read but not modify the
file.

To change this user's password later, omit `-c` so that the file is not recreated:

```bash
sudo htpasswd -B -C 12 /etc/snarkyctl/auth.htpasswd snarkadmin
```

#### 6.2 Create or supply a private CA

If a suitable private CA already exists, use it and skip the CA-generation command below.
The following commands create a dedicated CA for the initial deployment in a
root-only working directory:

```bash
sudo install -d -o root -g root -m 0700 /root/snarkyctl-ca
sudo openssl req -x509 -newkey rsa:3072 -sha256 -nodes \
    -days 3650 \
    -subj '/CN=SnarkyCtl Private CA' \
    -keyout /root/snarkyctl-ca/ca.key \
    -out /root/snarkyctl-ca/ca.crt
```

The CA private key is used only to sign server certificates. It must not be copied into
`/etc/snarkyctl`, included in a package, or made readable by the `snarkyctl` account.
After issuing the certificate, archive the CA key securely away from the VPS if practical.
Only the CA certificate is imported into Windows.

#### 6.3 Create the server certificate

Generate a private key and certificate request for the dashboard. The following example
uses the private hostname `snarkypuss` and management address `10.8.0.1`:

```bash
sudo openssl req -new -newkey rsa:3072 -sha256 -nodes \
    -subj '/CN=snarkypuss' \
    -addext 'subjectAltName=DNS:snarkypuss,IP:10.8.0.1' \
    -keyout /root/snarkyctl-ca/server.key \
    -out /root/snarkyctl-ca/server.csr
sudo openssl x509 -req \
    -in /root/snarkyctl-ca/server.csr \
    -CA /root/snarkyctl-ca/ca.crt \
    -CAkey /root/snarkyctl-ca/ca.key \
    -CAcreateserial \
    -copy_extensions copy \
    -sha256 \
    -days 825 \
    -out /root/snarkyctl-ca/server.crt
```

Replace `snarkypuss` if the browser will use a different private DNS name. Keep the IP SAN
if the dashboard will also be opened as `https://10.8.0.1:8443/`. Modern browsers validate
the Subject Alternative Name rather than relying on the Common Name.

Install only the server key, server certificate, and public CA certificate:

```bash
sudo install -d -o root -g snarkyctl -m 0750 /etc/snarkyctl/tls
sudo install -o root -g snarkyctl -m 0640 \
    /root/snarkyctl-ca/server.key \
    /etc/snarkyctl/tls/server.key
sudo install -o root -g root -m 0644 \
    /root/snarkyctl-ca/server.crt \
    /etc/snarkyctl/tls/server.crt
sudo install -o root -g root -m 0644 \
    /root/snarkyctl-ca/ca.crt \
    /etc/snarkyctl/tls/ca.crt
```

The web service needs read access to `server.key`, but cannot modify it. The CA private key
remains outside the application directory.

#### 6.4 Verify the certificate installation

Run:

```bash
sudo openssl verify \
    -CAfile /etc/snarkyctl/tls/ca.crt \
    /etc/snarkyctl/tls/server.crt
sudo openssl x509 \
    -in /etc/snarkyctl/tls/server.crt \
    -noout -subject -issuer -dates -ext subjectAltName
sudo -u snarkyctl test -r /etc/snarkyctl/tls/server.crt
sudo -u snarkyctl test -r /etc/snarkyctl/tls/server.key
```

The verification should report `server.crt: OK`. Inspect the output to confirm the intended
DNS name and `IP Address:10.8.0.1` are present.

Copy `/etc/snarkyctl/tls/ca.crt` to the Windows management computer over the private
management connection and import it into the Windows **Trusted Root Certification
Authorities** store. Never copy `ca.key` or `server.key` to Windows merely to trust the
site.

### 7. Install the systemd service

The control socket and daemon were installed in Section 5. This section installs and starts
the unprivileged HTTPS service.

#### 7.1 Check the unit's application-specific values

The supplied unit starts:

```bash
/usr/lib/snarkyctl/venv/bin/uvicorn snarkyctl.main:app \
    --host 10.8.0.1 \
    --port 8443 \
    --ssl-certfile /etc/snarkyctl/tls/server.crt \
    --ssl-keyfile /etc/snarkyctl/tls/server.key
```

These values must agree with `/etc/snarkyctl/snarkyctl.yaml`. In particular, the host must
be the address assigned to `wg0`, never `0.0.0.0` or the VPS public address. If the private
address, port, or certificate paths differ, update both the configuration and a local copy
of the unit before installing it.

`EnvironmentFile=-/etc/snarkyctl/snarkyctl.env` reserves an optional location for future
non-secret service settings. No environment file is required for the current release, and
it does not override the bind address or configuration path.

#### 7.2 Install and verify the web unit

From the repository root, run:

```bash
sudo install -o root -g root -m 0644 \
    systemd/snarkyctl-web.service \
    /usr/lib/systemd/system/snarkyctl-web.service
sudo systemd-analyze verify \
    /usr/lib/systemd/system/snarkyctl-web.service
sudo systemctl daemon-reload
```

Do not enable the web service yet.

#### 7.3 Run the activation preflight

Run the complete read-only preflight before the web listener occupies port 8443:

```bash
sudo /usr/lib/snarkyctl/venv/bin/snarkyctl preflight \
    --config /etc/snarkyctl/snarkyctl.yaml
```

Review every `FAIL`. Do not start the service until failures involving configuration,
identity, file ownership, TLS, provider safety, or systemd units have been corrected.
`SKIP` for the separately documented public-exposure observation is expected in the
current implementation and is not proof that public exposure is impossible.

Preflight checks that the NordVPN Kill Switch and NordVPN firewall are enabled. If either
is disabled or cannot be verified, correct the provider configuration before continuing.

#### 7.4 Enable the HTTPS service

After preflight completes without a failure:

```bash
sudo systemctl enable snarkyctl-web.service
sudo systemctl start snarkyctl-web.service
sudo systemctl status snarkyctl-web.service --no-pager
```

The service runs as `snarkyctl`, reads the configuration, password hashes, and TLS key,
and connects to the root daemon through the Unix socket. It receives no sudo privileges.

#### 7.5 Verify the listener and HTTPS endpoints

Confirm that Uvicorn listens only on the WireGuard address:

```bash
sudo ss -ltnp | grep ':8443'
```

The local address must be `10.8.0.1:8443`; output showing `0.0.0.0:8443`, `[::]:8443`, or
the VPS public address is unsafe. Stop the web service and correct the unit if that occurs.

Test the unauthenticated liveness endpoint:

```bash
curl --cacert /etc/snarkyctl/tls/ca.crt \
    https://10.8.0.1:8443/api/health/live
```

Then test the authenticated status API. Supplying the username without a password causes
curl to prompt without placing the password in shell history:

```bash
curl --cacert /etc/snarkyctl/tls/ca.crt \
    --user snarkadmin \
    https://10.8.0.1:8443/api/v1/status
```

Finally, open the dashboard from the Windows computer while its WireGuard tunnel is active:

```text
https://snarkypuss:8443/
```

The browser should trust the certificate, prompt for the Basic-auth credentials, and show
the read-only gateway dashboard. If the hostname is not resolvable on Windows, use
`https://10.8.0.1:8443/` or add the private hostname to the Windows hosts file.

#### 7.6 Diagnose startup failures

If the service does not start or the dashboard is unavailable, collect:

```bash
sudo systemctl status snarkyctl-web.service --no-pager
sudo journalctl -u snarkyctl-web.service -n 100 --no-pager
sudo ss -ltnp | grep ':8443'
sudo -u snarkyctl test -r /etc/snarkyctl/snarkyctl.yaml
sudo -u snarkyctl test -r /etc/snarkyctl/targets.yaml
sudo -u snarkyctl test -r /etc/snarkyctl/auth.htpasswd
sudo -u snarkyctl test -r /etc/snarkyctl/tls/server.crt
sudo -u snarkyctl test -r /etc/snarkyctl/tls/server.key
```

Do not open TCP port 8443 on the public firewall to work around a reachability problem.
The dashboard is intentionally reachable only through WireGuard.

### 8. Verify private reachability

From Windows with WireGuard connected, confirm private reachability in PowerShell:

```powershell
Test-NetConnection 10.8.0.1 -Port 8443
curl.exe --cacert .\ca.crt --user snarkadmin https://10.8.0.1:8443/api/v1/status
```

The first command should report `TcpTestSucceeded : True`. `curl.exe` prompts for the
password.

Then disconnect WireGuard on Windows and repeat only the connectivity test:

```powershell
Test-NetConnection 10.8.0.1 -Port 8443
```

It should fail because `10.8.0.1` is a private WireGuard address. Reconnect WireGuard
before continuing. Separately confirm in the Linode Cloud Firewall that TCP port 8443 has
no public inbound rule.

With a second WireGuard SSH session kept open, verify the supported VPN transitions:

```bash
sudo -u snarkyctl /usr/lib/snarkyctl/venv/bin/snarkyctl connect dallas
sudo -u snarkyctl /usr/lib/snarkyctl/venv/bin/snarkyctl status
sudo -u snarkyctl /usr/lib/snarkyctl/venv/bin/snarkyctl disconnect
sudo -u snarkyctl /usr/lib/snarkyctl/venv/bin/snarkyctl status
```

Replace `dallas` with an alias actually present in `/etc/snarkyctl/targets.yaml`.
Disconnect is deliberately refused unless the provider reports both leak protection and
its firewall enabled. After each transition, confirm that the dashboard and the second SSH
session remain reachable through WireGuard.

The final installation should satisfy all of the following:

- The dashboard is reachable over WireGuard.
- Nothing listens on the VPS public address at TCP port `8443`.
- Authentication is required.
- The HTTPS certificate is trusted by the Windows browser.
- NordVPN transitions do not interrupt the management path.
- Unexpected NordVPN failure leaves forwarded traffic Locked rather than exposing the VPS public IP.

### 9. Enable state-changing controls

There is no additional switch to enable in the current release.

The local `snarkyctl connect ALIAS` and `snarkyctl disconnect` commands are implemented and
always pass through the privileged daemon. The web dashboard and HTTP API remain
read-only. Web Connect and Disconnect endpoints have not yet been implemented.

The protocol reserves `LOCK` and `DIRECT`, but the daemon currently returns
`NOT_IMPLEMENTED` for both operations. Do not add firewall exceptions or invoke provider
commands outside SnarkyCtl in an attempt to enable them. Direct VPS mode will require a
separate implementation, explicit confirmation, and a persistent public-IP exposure
warning.

---

## Installation Paths

The current manual-installation filesystem locations are:

| Path | Purpose | Ownership |
|---|---|---|
| `/usr/lib/snarkyctl/` | Installed wheel and production virtual environment | `root:root` |
| `/etc/snarkyctl/` | Configuration, authentication, TLS, and authoritative allowlists | `root:snarkyctl` or `root:root`, mode-dependent |
| `/etc/snarkyctl/auth.htpasswd` | HTTP Basic username and salted password hash | `root:snarkyctl`, mode `0640` |
| `/run/snarkyctl/control.sock` | Web-to-daemon control socket | systemd-managed, group `snarkyctl` |
| `/var/lib/snarkyctl/` | Optional persistent policy state | `root:root` |
| `/usr/lib/systemd/system/snarkyctl-*.service` | Service definitions | `root:root` |
| `/usr/lib/systemd/system/snarkyctl-control.socket` | Socket activation definition | `root:root` |

The service account must not be able to modify application code, daemon code, service
definitions, certificate private keys, or the authoritative target allowlist.

---

## Not Yet Implemented

The following release packaging work remains:

- Pinned Python dependency file.
- Clean Ubuntu 24.04 install, upgrade, rollback, remove, and purge tests.
- A non-superficial package installation verification test under systemd.

Until those items are complete, this document describes a controlled development package,
not a finalized stable-release package.
