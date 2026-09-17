# Snarkypuss

**Snarkypuss** is a self-hosted private VPN gateway for routing a trusted client's Internet
traffic through a Linux VPS and, optionally, through an upstream VPN provider.

It combines two parts:

1. The **Snarkypuss gateway** — the private tunnel, forwarding, DNS, firewall, and upstream
   VPN configuration running on the VPS.
2. **SnarkyCtl** — the private management utility and web dashboard used to observe the
   gateway, select an upstream VPN target, and choose its operating mode.

The management service is part of Snarkypuss; it is not the purpose of the system by itself.

## What Snarkypuss does

A client connects to a VPS through a private VPN tunnel. The VPS then acts as the client's
Internet gateway:

```text
Trusted client
      │
      │ private VPN tunnel
      ▼
Snarkypuss VPS
      │
      ├── upstream VPN provider ──► Internet
      │
      └── direct VPS egress ──────► Internet
```

The normal protected path sends forwarded traffic through the configured upstream VPN.
Direct egress through the VPS is available only as an explicit, clearly warned choice.
If the upstream VPN is unavailable, Snarkypuss must not silently fall back to exposing the
VPS public IP.

The initial reference deployment uses:

- A Windows 11 client
- WireGuard for the private client-to-VPS tunnel
- Ubuntu 24.04 LTS on a Linode VPS
- NordVPN as the upstream VPN provider
- `dnsmasq` for gateway DNS
- SnarkyCtl for private status and control

Those choices describe the tested deployment, not the permanent limit of the design.
SnarkyCtl's provider-adapter boundary allows other upstream VPN software to be added without
changing the browser UI, API, or privileged control protocol.

## Why use a private VPN gateway?

Running the gateway on a VPS keeps the networking policy outside the client computer. It can:

- Hide client traffic from the local ISP.
- Avoid dependence on a commercial VPN application running on every client.
- Route traffic through a selected country or provider endpoint.
- Centralize DNS forwarding and filtering.
- Keep the management interface off the public Internet.
- Preserve private administrative access while the upstream VPN changes or fails.
- Provide a deliberate choice between protected, blocked, and direct egress.

This is a personal infrastructure project for technically proficient users who administer
their own Linux VPS. It is not a hosted VPN service.

## Safety model

Snarkypuss distinguishes three gateway modes:

| Mode | Forwarded Internet traffic |
|---|---|
| **Protected VPN** | Exits through the configured upstream VPN provider. |
| **Locked** | Is blocked while private management access remains available. |
| **Direct VPS** | Exits through the VPS public IP after explicit confirmation. |

**Locked is the safe fallback.** A failed provider connection, timeout, reboot, or unexpected
disconnect must not automatically select Direct VPS mode.

Direct VPS mode is intentionally placed in SnarkyCtl's **Danger Zone**. The interface warns
that it exposes the real public IP of the VPS. Disabling the upstream VPN or its kill switch
is likewise treated as an exceptional administrative action, not ordinary operation.

The private management service is intended to bind only to its private tunnel address. No
SnarkyCtl HTTP or HTTPS listener should be exposed on the VPS public interface.

## SnarkyCtl management utility

SnarkyCtl provides the operational view of the Snarkypuss gateway. It consists of:

- An authenticated HTTPS dashboard
- A provider-neutral REST API
- An unprivileged command-line client
- A privileged local control daemon
- A versioned Unix-socket protocol
- Trusted adapters for supported upstream VPN providers

The web application does not run provider commands or alter networking directly. It sends
allowlisted requests over `/run/snarkyctl/control.sock` to the privileged daemon. The daemon
validates the request and delegates provider-specific behavior to a packaged adapter.

Current management functions include:

- Show gateway mode and upstream VPN status.
- Show the observed public exit IP.
- Show DNS and basic system health.
- Add, edit, reorder, and remove provider-neutral VPN destinations.
- Connect to a provider-neutral target alias.
- Enter Locked mode.
- Enter Direct VPS mode only after explicit confirmation.
- Expose exceptional VPN and kill-switch controls in the Danger Zone.

The local CLI uses the same control boundary:

```bash
snarkyctl status
snarkyctl connect dallas
snarkyctl disconnect
```

Add `--json` for the complete machine-readable response.

Target aliases such as `dallas` are resolved from the root-owned SQLite catalogue. Browser and API
clients never submit arbitrary shell commands, executable paths, or dynamically loaded
provider modules.

## Getting started

The user documentation lives under [`docs/`](docs/) and is numbered in the order a new user
should normally read it:

1. [**01_SETUP_VPS.md**](docs/01_SETUP_VPS.md) — create the Linode and configure WireGuard,
   NordVPN, fail-closed behavior, and the Linode Firewall.
2. [**02_SETUP_DNS.md**](docs/02_SETUP_DNS.md) — configure and verify the private `dnsmasq`
   service used by the Windows WireGuard client.
3. [**03_SETUP_SNARKYCTL.md**](docs/03_SETUP_SNARKYCTL.md) — install and configure SnarkyCtl
   after networking and DNS are working.
4. [**04_USER_MANUAL.md**](docs/04_USER_MANUAL.md) — normal day-to-day use of the dashboard,
   VPN destinations, gateway modes, and CLI commands.
5. [**05_TROUBLESHOOTING.md**](docs/05_TROUBLESHOOTING.md) — symptom-oriented diagnosis and
   safe recovery when WireGuard, DNS, NordVPN, SnarkyCtl, or boot persistence fails.
6. [**06_BACKUP_RECOVERY.md**](docs/06_BACKUP_RECOVERY.md) — backups, Linode snapshots,
   restoration, migration, and full disaster recovery.
7. [**07_NORDVPN.md**](docs/07_NORDVPN.md) — NordVPN-specific installation, safety settings,
   management-path exceptions, destination selectors, and SnarkyCtl adapter behavior.
8. [**08_CONFIGURATION.md**](docs/08_CONFIGURATION.md) — authoritative SnarkyCtl YAML and
   SQLite target-catalogue configuration reference.
9. [**09_PREFLIGHT.md**](docs/09_PREFLIGHT.md) — read-only deployment validation, result
   states, implemented checks, and limits of what preflight proves.
10. [**10_API.md**](docs/10_API.md) — private SnarkyCtl HTTP API contracts, authentication,
    mutation protections, status/target endpoints, gateway-mode operations, and errors.
11. [**11_ARCHITECTURE.md**](docs/11_ARCHITECTURE.md) — Snarkypuss system architecture,
    trust boundaries, data/control planes, privilege separation, provider abstraction, and
    failure model.

## Repository layout

```text
README.md                 Project overview and documentation entry point
docs/                     Numbered user, setup, operations, and reference documentation
development/              Requirements, plans, decisions, and development artifacts
src/snarkyctl/            Management utility source
config/                   Example configuration
scripts/                  Build, gateway, and archived migration utilities
systemd/                  Service and socket units
debian/                   Debian package source
tests/                    Automated tests
```

## Versioning and release tags

The Git repository is versioned as the complete Snarkypuss system. Repository release tags
use this format:

```text
YYYY.MM.DD-N_<snarkyctl-version>
```

For example:

```text
2026.09.15-4_2.0.0
```

`YYYY.MM.DD` is the repository release date. `N` is a sequence number beginning at `1` and
incremented only when more than one repository release is made on the same date. The suffix
after the underscore records the SnarkyCtl application version contained in that repository
snapshot.

A repository release covers the gateway scripts, documentation, tests, build tooling,
SnarkyCtl source, and Debian packaging as one source-tree snapshot.

SnarkyCtl retains its own application/package version independently. The currently published
application version is `2.0.1`, represented by `pyproject.toml`, wheel metadata, command
version output, and the Debian upstream version. The corresponding Debian package version is
`2.0.1-1`.

The repository tag therefore identifies both the complete source snapshot and the SnarkyCtl
version it contains without making the two release schemes identical. Repository-only changes
can advance the date/sequence while retaining the same SnarkyCtl suffix.

## [License Terms](README-licensing.md)
