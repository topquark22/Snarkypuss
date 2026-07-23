# Installing SnarkyCtl

> **Status:** Installation framework for the first implementation. Commands for installing the application itself will be completed as the corresponding code and service files are added.

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
| `sudo` | Allows the unprivileged service account to invoke only approved root-owned wrappers. |
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

## Planned Installation Stages

The completed installer will follow these stages.

### 1. Record the network baseline

Capture interfaces, routes, policy rules, firewall rules, WireGuard state, NordVPN settings, service names, and representative command output. This establishes the control-path invariant before any state-changing endpoint is introduced.

### 2. Obtain the application

The production checkout will live at:

```text
/usr/lib/snarkyctl
```

The final command sequence will clone or update this repository without giving the runtime account ownership of the application code.

### 3. Create the Python environment

The virtual environment will live at:

```text
/usr/lib/snarkyctl/venv
```

Python packages will be installed from the repository's pinned dependency file after it is added. Expected application dependencies include FastAPI, Uvicorn, Jinja2, a YAML parser, password-hash verification support, and pytest for development/testing. Exact Python package versions belong in the repository dependency file, not in the `apt-get` command.

### 4. Create the service account

Create the non-interactive `snarkctl` system account. Application code and privileged wrappers remain owned by `root:root` and are not writable by this account.

### 5. Install configuration and privileged wrappers

Install root-owned configuration, the authoritative server-alias allowlist, and narrowly scoped wrapper commands. Validate `/etc/sudoers.d/snarkyctl` with `visudo` before enabling controls.

### 6. Install authentication and certificates

Create the root-controlled `auth.htpasswd` file for HTTP Basic authentication, followed by the private certificate authority and server certificate. Trust the CA on the Windows management computer. The certificate will include the chosen private hostname and, if used directly, `10.8.0.1` as an IP Subject Alternative Name.

### 7. Install the systemd service

Install and enable `snarkyctl.service`, initially with read-only status functionality. Bind Uvicorn only to:

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
| `/usr/lib/snarkyctl` | Application code and virtual environment | `root:root` |
| `/etc/snarkyctl/` | Configuration, secrets, and authoritative allowlists | `root:snarkctl` or `root:root`, mode-dependent |
| `/etc/snarkyctl/auth.htpasswd` | HTTP Basic username and salted password hash | `root:snarkctl`, mode `0640` |
| `/usr/libexec/snarkyctl/snark-*` | Privileged wrapper commands | `root:root` |
| `/run/snarkyctl/` | Optional runtime lock/state | `snarkctl:snarkctl` |
| `/usr/lib/systemd/system/snarkyctl.service` | Service definition | `root:root` |
| `/etc/sudoers.d/snarkyctl` | Restricted privilege rules | `root:root` |

The service account must not be able to modify application code, wrapper commands, sudoers rules, certificates' private keys, or the authoritative target allowlist.

---

## Not Yet Implemented

The following installation pieces will be filled in as their corresponding application components are created:

- Pinned Python dependency file.
- Application checkout and update commands.
- Service-account creation script.
- Configuration templates.
- NordVPN and mode-control wrappers.
- Restricted sudoers file.
- HTTP Basic auth-file generation and password-change procedure.
- Private CA and server-certificate generation procedure.
- systemd unit and hardening configuration.
- Installation verification script.
- Upgrade, rollback, and removal procedures.

Until those components exist, this document should be treated as the dependency and installation framework rather than a complete production installer.
