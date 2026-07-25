# SnarkyCtl

**SnarkyCtl** is a lightweight management service and web dashboard for the [**snarkypuss**](SNARKYPUSS.md) privacy gateway.

The project turns a Linux VPS into a remotely managed network appliance that is accessible **only through a private WireGuard tunnel**. It provides a secure control plane for monitoring and controlling an optional upstream VPN, WireGuard, DNS services, and selected system functions without exposing any management interface to the public Internet.

SnarkyCtl is not tied to one VPN technology or commercial provider. Its provider-adapter interface can support command-line VPN clients, WireGuard-based services, OpenVPN-based services, or other VPN implementations. NordVPN is the first implemented adapter, not an architectural requirement.

---

## Motivation

The `snarkypuss` gateway routes traffic through a private WireGuard tunnel to a VPS, and optionally onward through a separately configured upstream VPN.

While this architecture provides strong privacy and jurisdictional control, day-to-day administration currently requires provider-specific SSH commands. For example, the initial NordVPN deployment uses:

```bash
ssh root@snarkypuss "nordvpn connect us9167"
```

SnarkyCtl replaces those manual commands with a simple authenticated web interface and a small REST API.

---

# Goals

The project is designed to:

- Provide a private web dashboard.
- Expose a small, well-defined REST API.
- Monitor the configured upstream VPN and local gateway health.
- Switch VPN exit locations.
- Display the current public exit IP.
- Manage selected system services (such as `dnsmasq`).
- Remain accessible while the upstream VPN connects, disconnects, changes endpoints, or fails.
- Follow the principle of least privilege.

---

# Core Principles

- **Private by design** — reachable only via WireGuard.
- **No public management ports**.
- **Minimal dependencies**.
- **No arbitrary shell execution**.
- **Least-privilege architecture**.
- **Readable, maintainable code**.

---

# Current Features

## Dashboard

- Upstream VPN status, provider, and connection details
- Current exit IP
- DNS service status
- System health
- Uptime and load

## Upstream VPN Control

- Connect and disconnect through a trusted provider adapter
- Select predefined provider-neutral target aliases
- Choose Protected VPN, Locked, or explicitly confirmed Direct VPS policy modes
- Display normalized connection state and provider-specific details
- Support additional VPN technologies without changing the web API, control protocol, or firewall policy

The development release includes a NordVPN adapter. Future adapters may support other command-line clients, WireGuard configurations, OpenVPN configurations, or commercial VPN services. An adapter must be compiled into the trusted package registry; configuration cannot load arbitrary modules or executables.

Advanced gateway modes appear in a collapsed danger zone. **Protected VPN** enables leak
protection before connecting; **Locked** enables protection before disconnecting; and
**Direct VPS** disables protection and disconnects only after the user types
`EXPOSE VPS IP`. Direct mode prominently reports that the VPS public IP is exposed.

## DNS Status

- View DNS status

## System Information

- CPU
- Memory
- Disk usage
- Uptime
- Service health

---

# Security Model

SnarkyCtl is **not** intended to be an Internet-facing application.

The intended deployment is:

```text
Browser
      │
WireGuard
      │
10.8.0.1
      │
SnarkyCtl
```

The application binds only to the WireGuard interface and is additionally protected by authentication.

---

# Technology

Current stack:

- Python 3
- FastAPI
- Uvicorn
- HTML
- CSS
- JavaScript
- systemd

---

# Architecture

A plain-language explanation of the server framework, application components, security boundaries, and operating modes is available in [**ARCHITECTURE.md**](ARCHITECTURE.md).

Settled architectural choices are recorded in [**DECISIONS.md**](DECISIONS.md).

---

# Deployment

The reproducible wheel and Debian-package build, filesystem layout, release pipeline, and upgrade model are documented in [**DEPLOYMENT.md**](DEPLOYMENT.md).

---

# Installation

Installation prerequisites, Linux package dependencies, and the staged deployment framework are documented in [**INSTALL.md**](INSTALL.md).

The versioned main YAML schema, SQLite target catalogue, validation commands, and
configuration security boundaries are documented in
[**CONFIGURATION.md**](CONFIGURATION.md).

The read-only deployment checks, result states, exit codes, and current safety limitations of `snarkyctl preflight` are documented in [**PREFLIGHT.md**](PREFLIGHT.md).

The implemented NordVPN command boundary, normalized status fields, and delegated networking responsibilities are documented in [**NORDVPN.md**](NORDVPN.md).

The authenticated HTTPS status and VPN-target API, browser request protection, and stable
response schemas are documented in [**API.md**](API.md).

The local administration CLI communicates exclusively with the privileged daemon:

```bash
snarkyctl status
snarkyctl connect dallas
snarkyctl disconnect
```

Add `--json` to any of these commands for the complete machine-readable response. The CLI
does not invoke a VPN client directly. A Direct gateway state is reported prominently as
exposing the VPS public IP; disconnect remains subject to the daemon's leak-protection policy.

---

# Repository Layout

```text
README.md
ARCHITECTURE.md
DECISIONS.md
DEPLOYMENT.md
INSTALL.md
CONFIGURATION.md
PREFLIGHT.md
NORDVPN.md
SNARKYCTL.revised.md
SNARKYPUSS.md
pyproject.toml
src/snarkyctl/
config/
systemd/
tests/
debian/
```

---

# Development Roadmap

1. Establish the command parsers and typed status models.
2. Implement the root control daemon and versioned Unix-socket protocol.
3. Delegate routing and leak protection to the configured VPN provider.
4. Establish the unprivileged `snarkyctl` account and systemd socket/service units.
5. Build the authenticated, HTTPS-only status and control API.
6. Build the status dashboard and provider-neutral target selector.
7. Enable serialized CLI and dashboard controls through the control daemon.
8. Complete Debian packaging, preflight, hardening, and operational tests.

Detailed implementation requirements are contained in
[**SNARKYCTL.revised.md**](SNARKYCTL.revised.md), with settled architectural choices in
[**DECISIONS.md**](DECISIONS.md).

---

# Intended Audience

This project is intended for technically proficient users who operate their own Linux VPS and want a secure, self-hosted management interface for a WireGuard-based privacy gateway.

---

# License

To be determined.
