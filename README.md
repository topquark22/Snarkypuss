# SnarkyCtl

**SnarkyCtl** is a lightweight management service and web dashboard for the [**snarkypuss**](SNARKYPUSS.md) privacy gateway.

The project turns a Linux VPS into a remotely managed network appliance that is accessible **only through a private WireGuard tunnel**. It provides a secure control plane for monitoring and controlling NordVPN, WireGuard, DNS services, and selected system functions without exposing any management interface to the public Internet.

---

## Motivation

The `snarkypuss` gateway routes traffic through a private WireGuard tunnel to a VPS, and optionally onward through NordVPN.

While this architecture provides strong privacy and jurisdictional control, day-to-day administration currently requires running SSH commands such as:

```bash
ssh root@snarkypuss "nordvpn connect us9167"
```

SnarkyCtl replaces those manual commands with a simple authenticated web interface and a small REST API.

---

# Goals

The project is designed to:

- Provide a private web dashboard.
- Expose a small, well-defined REST API.
- Monitor WireGuard and NordVPN.
- Switch VPN exit locations.
- Display the current public exit IP.
- Manage selected system services (such as `dnsmasq`).
- Remain accessible even while NordVPN reconnects.
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

# Planned Features

## Dashboard

- WireGuard status
- NordVPN status
- Current exit IP
- DNS service status
- System health
- Uptime and load

## NordVPN Control

- Connect
- Disconnect
- Select predefined exit locations
- Display current server

## DNS Management

- Restart `dnsmasq`
- Reload blocklists
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

Current planned stack:

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

---

# Deployment

The reproducible wheel and Debian-package build, filesystem layout, release pipeline, and upgrade model are documented in [**DEPLOYMENT.md**](DEPLOYMENT.md).

---

# Installation

Installation prerequisites, Linux package dependencies, and the staged deployment framework are documented in [**INSTALL.md**](INSTALL.md).

---

# Repository Layout

```text
README.md
SNARKYCTL.md
app/
config/
scripts/
tests/
```

---

# Development Roadmap

1. Command execution layer
2. Status parser
3. Read-only REST API
4. Dashboard
5. NordVPN controls
6. Authentication
7. HTTPS
8. Privilege separation
9. Service hardening

Detailed implementation notes are contained in [**SNARKYCTL.md**](SNARKYCTL.md).

---

# Intended Audience

This project is intended for technically proficient users who operate their own Linux VPS and want a secure, self-hosted management interface for a WireGuard-based privacy gateway.

---

# License

To be determined.
