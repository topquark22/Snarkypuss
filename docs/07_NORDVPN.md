# Snarkypuss NordVPN Guide

## Purpose

This guide covers the NordVPN-specific part of a Snarkypuss deployment. The general VPS,
WireGuard, DNS, and SnarkyCtl procedures live in the earlier numbered guides.

The reference deployment uses Ubuntu 24.04 LTS and NordVPN's NordLynx technology. NordVPN
owns the upstream tunnel, provider routing, provider firewall/Kill Switch, DNS integration,
and server selection. Snarkypuss owns the private WireGuard management path, forwarding,
private DNS, and the rule that a provider failure must never silently become Direct VPS
egress.

## 1. Install the NordVPN Linux client

Run these commands on the Linode, not on Windows.

The official installer is:

```bash
sh <(curl -sSf https://downloads.nordcdn.com/apps/linux/install.sh)
```

If the NordVPN package repository is already configured, use:

```bash
sudo apt-get update
sudo apt-get install nordvpn
```

Confirm that the client is available:

```bash
nordvpn --version
nordvpn help
```

## 2. Log in on a headless Linode

Generate a Nord Account access token and run:

```bash
nordvpn login --token NORDVPN_ACCESS_TOKEN
```

Do not store the token in the repository, `/etc/snarkypuss-setup.conf`, SnarkyCtl
configuration, the destination database, or committed shell scripts.

## 3. Configure the Snarkypuss NordVPN policy

Snarkypuss includes:

```text
scripts/snarkypuss-nordvpn-configure.py
```

The helper derives the WireGuard listener port and management subnet from
`/etc/snarkypuss-setup.conf`. It then configures the reference NordVPN policy:

- NordLynx technology,
- auto-connect disabled,
- a narrow exception for the WireGuard UDP listener,
- a narrow exception for the private WireGuard management subnet, and
- Kill Switch enabled.

Keep the LISH console available before applying provider firewall changes. LISH is
independent of WireGuard, SSH, and the NordVPN firewall and is the recovery path if remote
management is interrupted.

Preview the exact NordVPN commands first:

```bash
sudo scripts/snarkypuss-nordvpn-configure.py \
    --config /etc/snarkypuss-setup.conf \
    --dry-run
```

The dry run does not modify provider state.

After confirming independent LISH/console access, apply the policy:

```bash
sudo scripts/snarkypuss-nordvpn-configure.py \
    --config /etc/snarkypuss-setup.conf \
    --apply \
    --console-confirmed
```

`--apply` must run as root and intentionally requires `--console-confirmed`.

The helper verifies the resulting NordVPN settings and fails if it cannot confirm:

- `Technology: NordLynx`,
- Kill Switch enabled, and
- auto-connect disabled.

Existing management exceptions are treated idempotently when the installed client reports
that they are already present.

The helper does **not** connect NordVPN and does **not** perform the fail-closed acceptance
test. Those remain explicit operational steps because they require observing the real
network path.

### Equivalent provider operations

The helper performs operations equivalent to:

```bash
sudo nordvpn set technology NordLynx
sudo nordvpn set autoconnect off
sudo nordvpn allowlist add port 51820 protocol UDP
sudo nordvpn allowlist add subnet 10.8.0.0/24
sudo nordvpn set killswitch on
```

The actual port and subnet come from `/etc/snarkypuss-setup.conf`; the reference values above
are not hard-coded policy values.

Do not broadly allowlist TCP port 22 or TCP port 8443. SSH and SnarkyCtl remain private
services reached through WireGuard. Do not expose them publicly as a substitute for a
correct management-path exception.

## 4. Connect and inspect NordVPN

After the policy helper succeeds, connect normally:

```bash
sudo nordvpn connect
sudo nordvpn status
sudo nordvpn settings
```

A plain `nordvpn connect` lets NordVPN choose a recommended server.

Do not proceed to gateway activation unless the provider connection works and the Kill
Switch remains enabled.

## 5. Test fail-closed behavior

The management exceptions are acceptable only if ordinary Windows Internet traffic cannot
bypass NordVPN.

Keep LISH open during this test.

With the Snarkypuss WireGuard tunnel active, verify private management from Windows:

```powershell
Test-NetConnection 10.8.0.1 -Port 22
Test-NetConnection 10.8.0.1 -Port 8443
```

On the Linode, inspect the provider and WireGuard state:

```bash
sudo wg show wg0
sudo nordvpn status
sudo nordvpn settings
```

Then disconnect NordVPN while leaving the Kill Switch enabled:

```bash
sudo nordvpn disconnect
```

The required result is:

- private SSH over WireGuard remains reachable,
- the SnarkyCtl dashboard remains reachable,
- ordinary Internet traffic forwarded from Windows is blocked, and
- forwarded traffic does not leave through the Linode public interface.

This is the expected Locked condition.

Reconnect when the test is complete:

```bash
sudo nordvpn connect
```

If Windows Internet traffic still works directly while NordVPN is disconnected and the Kill
Switch is expected to protect it, treat that as a safety failure. Use LISH, remove the
exception responsible for the leak, and do not rely on the deployment until fail-closed
behavior is restored and retested.

## 6. Manual provider commands

Direct NordVPN commands remain useful for diagnosis and deliberate administration:

```bash
sudo nordvpn connect
sudo nordvpn status
sudo nordvpn settings
sudo nordvpn disconnect
```

A manual `nordvpn disconnect` bypasses SnarkyCtl's higher-level safety checks. Use direct
provider commands for setup and testing, not as an unnoticed substitute for SnarkyCtl's
Locked/Protected mode transitions.

When the Kill Switch is enabled, losing public Internet access after `nordvpn disconnect` is
expected. In Snarkypuss that is desirable as long as the private WireGuard management path
remains available.

## 7. NordVPN destinations in SnarkyCtl

SnarkyCtl stores provider-neutral destination aliases in the root-owned SQLite catalogue.
The built-in NordVPN adapter validates the provider-specific selector behind each alias.

The dashboard supports these NordVPN destination types:

| Type | Meaning |
|---|---|
| Recommended | Let NordVPN choose its recommended server. |
| Country | Select a server within one country. |
| City | Select a server in one city within a country. |
| Group | Select a NordVPN specialty group. |
| Server | Select one exact NordVPN server. |

Use the installed NordVPN client to discover available values. Depending on client version,
commands include:

```bash
nordvpn countries
nordvpn cities united_states
nordvpn groups
nordvpn help
```

Provider destinations can change independently of Snarkypuss, so validate selectors against
the installed client rather than copying an old list from documentation.

## 8. What the SnarkyCtl NordVPN adapter does

The privileged runtime adapter deliberately supports only a narrow command surface
equivalent to:

```text
/usr/bin/nordvpn status
/usr/bin/nordvpn settings
/usr/bin/nordvpn set killswitch on|off
/usr/bin/nordvpn connect <validated selector arguments>
/usr/bin/nordvpn disconnect
```

This is separate from the one-time `snarkypuss-nordvpn-configure.py` setup helper. The setup
helper establishes the provider policy and management exceptions; the SnarkyCtl adapter
performs bounded runtime operations after deployment.

The browser never supplies arbitrary shell commands. Target aliases are resolved against the
trusted catalogue and provider selector fields are validated before the fixed NordVPN
executable is invoked.

## 9. NordVPN and Snarkypuss gateway modes

SnarkyCtl translates provider state into four effective modes:

- **Protected VPN** — leak protection enabled and NordVPN connected.
- **Locked** — leak protection enabled and NordVPN disconnected; public forwarding blocked.
- **Direct VPS** — exceptional explicit mode with provider leak protection disabled and
  traffic leaving through the VPS public connection.
- **Unknown** — provider state cannot be established confidently; do not assume protection.

Direct VPS must never be an automatic response to a failed NordVPN connection. If a Direct
transition fails after disabling the Kill Switch, the control daemon attempts to restore
leak protection.

## 10. Troubleshooting

Start with:

```bash
sudo nordvpn status
sudo nordvpn settings
ip link show nordlynx
snarkyctl status
```

If initial policy setup fails, preview it again with:

```bash
sudo scripts/snarkypuss-nordvpn-configure.py \
    --config /etc/snarkypuss-setup.conf \
    --dry-run
```

If the installed NordVPN client's command names or output differ from the helper's supported
forms, inspect:

```bash
nordvpn help
man nordvpn
```

If NordVPN connects but WireGuard management disappears, review the management exceptions
and use LISH for recovery. If Internet works through the Linode public IP when Protected VPN
was expected, stop using the connection for protected traffic and follow the wrong-public-IP
procedure in [05_TROUBLESHOOTING.md](05_TROUBLESHOOTING.md).

## 11. Provider-specific safety rules

For the reference NordVPN deployment:

- Keep the Kill Switch enabled for normal operation.
- Keep LISH available while changing provider firewall/allowlist policy.
- Use the setup helper rather than hand-building broader exceptions.
- Verify fail-closed forwarding after every material provider-policy change.
- Do not expose SSH or SnarkyCtl publicly to work around a provider firewall problem.
- Keep NordVPN access tokens out of Git and unrelated configuration files.
- Verify the observed public exit address after provider changes.
- Treat Unknown protection state conservatively.

For general symptoms, return to [05_TROUBLESHOOTING.md](05_TROUBLESHOOTING.md).

## Official NordVPN references

NordVPN changes its Linux client independently of Snarkypuss. When syntax differs from the
installed examples, consult the current provider documentation:

- Linux installation and CLI reference:
  https://support.nordvpn.com/hc/en-us/articles/20196094470929-How-to-install-the-NordVPN-app-on-Linux-distributions
- Headless token login:
  https://support.nordvpn.com/hc/en-us/articles/20286980309265-How-to-log-in-to-NordVPN-without-a-GUI-using-a-token
- Linux Kill Switch behavior:
  https://support.nordvpn.com/hc/en-us/articles/19509682644369-NordVPN-Kill-Switch-how-does-it-work
- Linux allowlist/split-tunneling behavior:
  https://support.nordvpn.com/hc/en-us/articles/19618692366865-What-is-Split-Tunneling-and-how-to-use-it-with-NordVPN
