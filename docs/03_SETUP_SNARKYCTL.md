# SnarkyCtl Setup Guide

## Purpose

This guide installs and configures **SnarkyCtl** after the Snarkypuss networking and DNS
setup are working. Complete these guides first:

1. [01_SETUP_VPS.md](01_SETUP_VPS.md) — Linode, WireGuard, NordVPN, forwarding, and
   fail-closed networking.
2. [02_SETUP_DNS.md](02_SETUP_DNS.md) — private Snarkypuss DNS service and DNS verification.

SnarkyCtl is the private dashboard and control software for the Snarkypuss Linode. It is
reachable through the WireGuard tunnel and must not be exposed on the public Internet.

## Before you begin

Before starting this guide, confirm that:

- The Windows `snarkypuss` WireGuard tunnel connects successfully.
- `snarkypuss` resolves to `10.8.0.1` on Windows.
- SSH to the Linode works through the private WireGuard path.
- NordVPN is installed, connected, and its Kill Switch is enabled.
- Disconnecting NordVPN blocks ordinary client Internet traffic while private WireGuard
  management remains reachable.
- `snarkypuss-dns.service` is active and Windows can resolve DNS through `10.8.0.1`.
- The Linode Firewall allows the WireGuard UDP listener but does not expose SnarkyCtl HTTPS
  or DNS publicly.
- The LISH console remains available as a recovery path.

Unless a step is explicitly labelled as a Windows step, run Linux commands on the Linode.
You may continue using LISH, or use private SSH through `snarkypuss` now that WireGuard has
been proven.

## 1. Install the SnarkyCtl package

SnarkyCtl is installed only after the underlying gateway is working. The preferred deployment
artifact is the Debian package; package installation does not connect the provider or change
gateway routing.

Install the reviewed package artifact:

```bash
sudo apt-get install ./snarkyctl_VERSION_amd64.deb
```

The package creates the `snarkyctl` system account and the base application directories, but
it deliberately does not create live credentials or TLS private keys and does not start a
partially configured service.

Copy the packaged configuration example and initialize the empty destination catalogue:

```bash
sudo install -o root -g snarkyctl -m 0640 \
    /usr/share/snarkyctl/examples/snarkyctl.yaml.example \
    /etc/snarkyctl/snarkyctl.yaml
sudo snarkyctl targets-db initialize
sudo snarkyctl targets-db check
```

Edit `/etc/snarkyctl/snarkyctl.yaml` and confirm at least:

- `network.management_interface` names the private WireGuard interface.
- `network.management_address` is the private VPS address.
- `network.client_subnet` matches the WireGuard client network.
- `network.public_interface` matches the real VPS public interface.
- `web.bind_address` is the private WireGuard address only.
- `upstream_vpn.provider` selects a compiled, supported provider.
- `upstream_vpn.expected_interfaces` matches the provider's actual tunnel interface.
- The target database remains `/var/lib/snarkyctl/targets.db` unless deliberately changed.

Validate the file before enabling services:

```bash
sudo snarkyctl validate-config \
    --config /etc/snarkyctl/snarkyctl.yaml
```

Build and release engineering does not belong in this setup guide. Developers producing the
Debian artifact should use the development build/release documentation.

## 2. Configure SnarkyCtl authentication and TLS

SnarkyCtl uses HTTP Basic authentication over HTTPS. Credentials are stored as bcrypt
password hashes in `/etc/snarkyctl/auth.htpasswd`; there is no plaintext password database or
browser session database.

Create the administrator record interactively:

```bash
sudo htpasswd -cB -C 12 /etc/snarkyctl/auth.htpasswd snarkadmin
sudo chown root:snarkyctl /etc/snarkyctl/auth.htpasswd
sudo chmod 0640 /etc/snarkyctl/auth.htpasswd
```

Do not use `htpasswd -b`, because that places the plaintext password on the command line.

The dashboard certificate must cover the private name and/or private WireGuard IP used by
the browser. The reference installation uses a private CA and a server certificate with a
Subject Alternative Name for `snarkypuss` and `10.8.0.1`. The CA private key remains
separate from the SnarkyCtl application; only the CA certificate is imported into the
Windows trust store.

Install the resulting server material under:

```text
/etc/snarkyctl/tls/server.crt
/etc/snarkyctl/tls/server.key
/etc/snarkyctl/tls/ca.crt
```

The web service needs read access to the server key but must not be able to modify it. Never
copy the CA private key or server private key to Windows merely to establish browser trust.

## 3. Run SnarkyCtl preflight and start the private services

Before enabling the HTTPS service, run the complete read-only preflight:

```bash
sudo snarkyctl preflight \
    --config /etc/snarkyctl/snarkyctl.yaml
```

Review every `FAIL`. Do not start the dashboard until failures involving configuration,
file ownership, authentication, TLS, provider safety, management binding, or systemd units
have been corrected.

Enable and start the socket-activated control path and the HTTPS service. The important
service model is:

- `snarkyctl-control.socket` is enabled and listening.
- `snarkyctl-control.service` is started on demand by the socket and is **not** enabled
  directly.
- `snarkyctl-web.service` is enabled and runs as the unprivileged `snarkyctl` account.

Verify that the dashboard listener exists only on the private WireGuard address:

```bash
sudo ss -ltnp | grep ':8443'
```

The reference deployment must show `10.8.0.1:8443`, never `0.0.0.0:8443`, `[::]:8443`, or
the VPS public address.

From Windows with WireGuard active, open:

```text
https://snarkypuss:8443/
```

If the private hostname is not configured, use the private IP address covered by the server
certificate.

## 4. Add the first VPN destination

The target database is intentionally empty after initialization. SnarkyCtl does not guess a
default provider destination.

Open **Manage VPN destinations** in the authenticated dashboard and add a destination with:

- A stable provider-neutral alias, such as `dallas`.
- A user-facing label.
- One provider-defined selector type and its validated fields.

Save the catalogue, then inspect it from the VPS if desired:

```bash
sudo snarkyctl targets list
sudo snarkyctl targets-db check
```

The browser uses only the public alias for ordinary connection requests. Provider command
arguments and structured selectors remain behind the privileged control boundary.

## 5. Verify normal operating modes

Test the normal protected connection using a configured alias:

```bash
snarkyctl connect dallas
snarkyctl status
```

Replace `dallas` with an alias in the local catalogue.

The dashboard and current control plane distinguish these effective modes:

| Mode | Expected forwarded Internet behavior |
|---|---|
| **Protected VPN** | Exits through the configured upstream VPN provider. |
| **Locked** | Public Internet forwarding is blocked while private management remains available. |
| **Direct VPS** | Exits through the VPS public IP after explicit confirmation. |
| **Unknown** | SnarkyCtl cannot verify the effective safety state. |

Direct VPS mode is exceptional. It deliberately exposes the VPS public IP and belongs in the
dashboard **Danger Zone**. Never use Direct VPS mode as an automatic recovery from provider
failure.

During mode tests, keep a second WireGuard management session open and confirm that the
private dashboard and SSH path remain reachable.

## 6. Verify boot persistence

A service working immediately after installation does not prove that it will return after
reboot.

Before rebooting, verify enablement and current state:

```bash
systemctl is-enabled ssh.service \
    snarkyctl-control.socket \
    snarkyctl-web.service

systemctl is-active ssh.service \
    snarkyctl-control.socket \
    snarkyctl-web.service
```

The socket and web service should be enabled. The privileged
`snarkyctl-control.service` may be inactive until a request arrives; that is normal socket
activation.

Keep the independent VPS console available and perform a controlled reboot. After the host
returns, verify the base gateway, DNS, and SnarkyCtl services:

```bash
systemctl is-active wg-quick@wg0.service snarkypuss-dns.service ssh.service
systemctl is-active snarkyctl-control.socket snarkyctl-web.service
sudo ss -xlpn | grep /run/snarkyctl/control.sock
```

Then reconnect from Windows and verify:

- WireGuard handshake and traffic counters.
- Private SSH reachability.
- DNS resolution through the gateway.
- The SnarkyCtl dashboard.
- Provider state.
- Public exit IP.
- Protected/Locked behavior as appropriate for the configured provider startup policy.

If an enabled unit is inactive after boot, inspect the current boot journal before repeatedly
starting it by hand. A manual start may restore service without explaining the persistence
failure.

## 7. Final acceptance checklist

Treat the initial setup as complete only when all of the following are true:

- The Windows client establishes the private WireGuard tunnel.
- WireGuard has a recent handshake and nonzero bidirectional transfer.
- `10.8.0.1` is reachable only through the intended private path.
- DNS queries from the Windows client use the gateway and do not leak to the client's ISP.
- Protected traffic exits through the configured upstream VPN provider.
- Provider disconnection with leak protection enabled blocks client Internet traffic.
- Provider disconnection does not destroy private SSH or management access.
- The VPS public address is not used silently as a fallback.
- The SnarkyCtl HTTPS listener is not exposed on the public interface.
- The browser trusts the SnarkyCtl server certificate and requires authentication.
- At least one provider destination can be selected through SnarkyCtl.
- Direct VPS mode requires explicit confirmation and presents a conspicuous exposure warning.
- WireGuard, `snarkypuss-dns.service`, SSH, the SnarkyCtl control socket, and the SnarkyCtl web
  service survive a controlled reboot as intended.
- Independent VPS console access remains documented and available for recovery.

## Next documentation

After initial installation:

- Use [User Manual](04_USER_MANUAL.md) for normal day-to-day operation.
- Use [Troubleshooting](05_TROUBLESHOOTING.md) when a working deployment develops a problem.
- Use [Backup and Recovery](06_BACKUP_RECOVERY.md) before upgrades or significant
  network/provider changes.
- Use [NordVPN](07_NORDVPN.md) for provider-specific details.
- Use [Configuration](08_CONFIGURATION.md), [Preflight](09_PREFLIGHT.md), [API](10_API.md),
  and [Architecture](11_ARCHITECTURE.md) for detailed reference material.

The setup path should remain linear. Detailed documents may explain why a component works the
way it does, but they should not create competing installation procedures for the same
supported deployment.
