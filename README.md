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

The documentation is divided by purpose:

- [**SNARKYPUSS.md**](SNARKYPUSS.md) — technical reference for building and validating the
  private VPN gateway itself.
- [**INSTALL.md**](INSTALL.md) — detailed installation of SnarkyCtl and its system services.
- [**CONFIGURATION.md**](CONFIGURATION.md) — application and target configuration.
- [**ARCHITECTURE.md**](ARCHITECTURE.md) — components, privilege boundaries, and gateway modes.
- [**NORDVPN.md**](NORDVPN.md) — NordVPN adapter behavior and operational considerations.
- [**PREFLIGHT.md**](PREFLIGHT.md) — deployment validation and safety checks.
- [**API.md**](API.md) — authenticated HTTPS API.
- [**DEPLOYMENT.md**](DEPLOYMENT.md) — wheel and Debian packaging, upgrades, and release process.
- [**development/**](development/README.md) — requirements, roadmap, and architectural
  decision artifacts used during development.

A practical deployment proceeds in two stages:

1. Build and verify the Snarkypuss private VPN gateway using
   [SNARKYPUSS.md](SNARKYPUSS.md).
2. Install SnarkyCtl using [INSTALL.md](INSTALL.md), then run the documented preflight checks.

Do not expose the management listener publicly as a shortcut during installation.

## Repository layout

```text
README.md                 Project overview
SNARKYPUSS.md             Private VPN gateway technical reference
ARCHITECTURE.md           Software and security architecture
development/              Requirements and design-process artifacts
INSTALL.md                Administrator installation guide
CONFIGURATION.md          Runtime configuration reference
NORDVPN.md                NordVPN provider-adapter reference
PREFLIGHT.md              Deployment validation reference
API.md                    HTTP API reference
DEPLOYMENT.md             Build and packaging reference
src/snarkyctl/            Management utility source
config/                   Example configuration
scripts/                  Build, gateway, and archived migration utilities
systemd/                  Service and socket units
debian/                   Debian package source
tests/                    Automated tests
```

## Project status

Snarkypuss `0.10.0.dev4` has passed Plan 10 user-acceptance testing on the reference VPS.
It remains a development release while reproducible packaging and clean-install coverage
are completed. Administrators should retain console access and verify leak protection
before relying on it for sensitive traffic.
