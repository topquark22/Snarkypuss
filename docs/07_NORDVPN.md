# Snarkypuss NordVPN Guide

## Purpose

This guide documents the **NordVPN-specific** part of a Snarkypuss deployment. The general
VPS, WireGuard, DNS, and SnarkyCtl procedures live in the earlier numbered guides.

This document explains what Snarkypuss expects from NordVPN, how the Linux client is
configured, how SnarkyCtl uses the NordVPN adapter, how destinations are represented, and
how to preserve the private WireGuard management path without defeating fail-closed
behavior.

The reference deployment uses Ubuntu 24.04 LTS and NordVPN's NordLynx technology. In that
configuration the expected provider interface is `nordlynx`.

## 1. Responsibility boundary

NordVPN and Snarkypuss have deliberately separate responsibilities.

NordVPN owns:

- the upstream VPN tunnel,
- provider routing,
- provider DNS integration,
- the NordVPN firewall,
- the Kill Switch,
- server selection, and
- the `nordlynx` interface when NordLynx is in use.

The Snarkypuss gateway owns:

- the Windows-to-Linode WireGuard tunnel,
- the private management network,
- forwarding from the WireGuard client,
- the Snarkypuss forwarding and NAT chains,
- private DNS service, and
- the policy that Direct VPS egress must never appear silently as a provider failure
  fallback.

SnarkyCtl does **not** replace NordVPN's route or firewall management. The built-in NordVPN
adapter invokes a narrow set of reviewed NordVPN CLI operations and reads the resulting
provider state.

## 2. Install the NordVPN Linux client

Run these commands on the **Linode**, not on the Windows PC.

The official NordVPN CLI installer is:

```bash
sh <(curl -sSf https://downloads.nordcdn.com/apps/linux/install.sh)
```

If the NordVPN repository is already configured, the package can instead be installed with:

```bash
sudo apt-get update
sudo apt-get install nordvpn
```

Confirm that the command is available:

```bash
nordvpn --version
nordvpn help
```

Snarkypuss uses the Linux CLI client. A graphical Linux desktop is not required.

## 3. Log in on a headless Linode

For a VPS without a browser or desktop session, use a Nord Account access token.

Generate the token in your Nord Account, then run on the Linode:

```bash
nordvpn login --token NORDVPN_ACCESS_TOKEN
```

Replace `NORDVPN_ACCESS_TOKEN` with the actual token. Do not put the token in:

- this repository,
- `/etc/snarkypuss-setup.conf`,
- `/etc/snarkyctl/snarkyctl.yaml`,
- the SnarkyCtl destination database, or
- shell scripts committed to Git.

NordVPN shows a newly generated token only once. Treat it as a credential.

Be careful with `nordvpn logout`: NordVPN documents that a normal logout invalidates the
current token. If you intentionally need to log out while retaining a reusable token, check
the behavior supported by the installed client before doing so.

## 4. Configure the reference safety settings

The reference Snarkypuss deployment uses NordLynx, enables the Kill Switch, and leaves
NordVPN auto-connect disabled so startup behavior remains explicit and observable.

Run:

```bash
sudo nordvpn set technology NordLynx
sudo nordvpn set killswitch on
sudo nordvpn set autoconnect off
```

Then inspect the result:

```bash
sudo nordvpn settings
```

The exact text printed by `nordvpn settings` can vary between client versions. Confirm at a
minimum that:

- the intended technology is NordLynx,
- the Kill Switch is enabled, and
- the client reports the provider firewall/settings needed by the installed version.

Do not invent unsupported NordVPN settings commands. In particular, Snarkypuss does not
require a `nordvpn set firewall on` command; the NordVPN client manages its own firewall
policy.

## 5. Preserve WireGuard management access

The NordVPN Kill Switch can block management traffic when the provider disconnects or changes
servers unless the private management path is explicitly accommodated.

The reference values are:

```text
WireGuard UDP listener: 51820
WireGuard subnet:        10.8.0.0/24
```

Confirm the actual deployment before changing NordVPN policy:

```bash
sudo wg show wg0
sudo grep -E '^[[:space:]]*ListenPort' /etc/wireguard/wg0.conf
ip -brief address show wg0
```

Keep the **LISH console open** while making this change. If NordVPN blocks the remote
management path, LISH remains independent of WireGuard, SSH, and the NordVPN firewall.

NordVPN Linux client versions have used both `allowlist` and `whitelist` terminology. Use
`nordvpn help`, `man nordvpn`, or the installed client's command help to determine which
spelling it accepts.

For clients that accept `allowlist`:

```bash
sudo nordvpn allowlist add port 51820 protocol UDP
sudo nordvpn allowlist add subnet 10.8.0.0/24
```

For clients that use the older `whitelist` spelling, use the equivalent commands supported by
that client, for example:

```bash
sudo nordvpn whitelist add port 51820
sudo nordvpn whitelist add subnet 10.8.0.0/24
```

Inspect the resulting policy:

```bash
sudo nordvpn settings
```

Do **not** broadly allowlist TCP port 22 or TCP port 8443. SSH and the SnarkyCtl dashboard
must remain private services reached through WireGuard. Do not expose them on the Linode's
public interface as a substitute for a correctly functioning management path.

Do not enable broader LAN exceptions merely to make the reference deployment work. Prefer
the narrow WireGuard listener and management-subnet exceptions that you have explicitly
tested.

## 6. Test the fail-closed behavior

An exception that preserves management access is acceptable only if it does **not** allow
ordinary Windows Internet traffic to bypass NordVPN.

Keep LISH open and maintain a second management session during this test.

With NordVPN connected, verify from Windows:

```powershell
Test-NetConnection 10.8.0.1 -Port 22
Test-NetConnection 10.8.0.1 -Port 8443
```

On the Linode, verify the WireGuard peer:

```bash
sudo wg show wg0
sudo nordvpn status
sudo nordvpn settings
```

Then deliberately disconnect NordVPN while leaving the Kill Switch enabled:

```bash
sudo nordvpn disconnect
```

The required result is:

- private SSH over WireGuard remains reachable,
- the SnarkyCtl dashboard remains reachable,
- ordinary Internet traffic forwarded from Windows is blocked, and
- forwarded traffic does not leave through the Linode's public address.

This is the expected **Locked** condition.

Reconnect after the test:

```bash
sudo nordvpn connect
```

If Windows Internet traffic still works directly while NordVPN is disconnected and the Kill
Switch is expected to protect it, treat that as a safety failure. Use LISH, remove the
exception that caused the leak, and do not rely on the deployment until fail-closed behavior
has been restored and retested.

## 7. Connect and inspect NordVPN directly

These commands are useful when separating a provider problem from a SnarkyCtl problem:

```bash
sudo nordvpn connect
sudo nordvpn status
sudo nordvpn settings
sudo nordvpn disconnect
```

A normal manual `nordvpn connect` lets NordVPN choose a recommended server.

When the Kill Switch is enabled, losing Internet access after `nordvpn disconnect` is
expected provider behavior. In Snarkypuss that blocked public path is desirable as long as
the private WireGuard management path remains available.

Do not disable the Kill Switch simply because disconnected Internet traffic is blocked. That
is exactly the condition the safety design is intended to produce.

## 8. NordVPN destinations in SnarkyCtl

SnarkyCtl stores provider-neutral destination aliases in the root-owned SQLite catalogue.
The built-in NordVPN adapter validates the provider-specific selector behind each alias.

The dashboard exposes these NordVPN destination types:

| Type | Meaning |
|---|---|
| **Recommended** | Let NordVPN choose its recommended server. |
| **Country** | Select a server within one country. |
| **City** | Select a server in one city within a country. |
| **Group** | Select a NordVPN specialty group. |
| **Server** | Select one exact NordVPN server. |

The alias and label are local SnarkyCtl names. For example, an alias such as `dallas` can
represent a validated NordVPN city selector without exposing raw command construction to the
browser.

Use the installed NordVPN client to discover available values. Depending on client version,
use commands such as:

```bash
nordvpn countries
nordvpn cities united_states
nordvpn groups
nordvpn help
```

The list and spelling of provider destinations can change independently of Snarkypuss, so
validate selections against the installed NordVPN client rather than copying an old list
from documentation.

Labels should describe the selector honestly. A country selector should not be labelled as
though it guarantees one particular city or physical server.

## 9. What the SnarkyCtl NordVPN adapter actually does

The privileged adapter deliberately supports only a narrow command surface equivalent to:

```text
/usr/bin/nordvpn status
/usr/bin/nordvpn settings
/usr/bin/nordvpn set killswitch on|off
/usr/bin/nordvpn connect <validated selector arguments>
/usr/bin/nordvpn disconnect
```

The adapter does not accept arbitrary shell commands from the browser. Destination aliases
are resolved against the trusted catalogue, selector fields are validated, and the NordVPN
executable path is fixed by the packaged integration.

After a connection or disconnection request, the adapter queries NordVPN again and reports
the observed state rather than assuming that a mutation command succeeded merely because it
returned a message.

The adapter reads and normalizes useful provider information including:

- connection state,
- server/display name,
- provider IP,
- country and city,
- technology and protocol,
- transfer information,
- Kill Switch state, and
- provider firewall/settings state when available.

When NordVPN reports NordLynx, SnarkyCtl expects the provider interface `nordlynx` in the
reference deployment.

## 10. NordVPN and Snarkypuss gateway modes

SnarkyCtl translates the provider state into four effective gateway modes.

### Protected VPN

The protected-mode operation enables leak protection first and then connects the selected
approved destination. SnarkyCtl expects the resulting mode to be VPN/Protected VPN.

### Locked

The locked-mode operation enables leak protection and disconnects NordVPN. Public forwarding
is blocked while private management remains available.

### Direct VPS

Direct VPS is exceptional. SnarkyCtl disables provider leak protection and disconnects
NordVPN, allowing client traffic to use the Linode's public Internet connection.

The dashboard requires explicit confirmation before entering this mode. Never use Direct VPS
as an automatic response to a failed NordVPN connection.

If a Direct VPS transition fails after disabling the Kill Switch, the control daemon attempts
to restore leak protection.

### Unknown

If SnarkyCtl cannot establish a trustworthy combination of provider connection state and
leak-protection state, it reports Unknown. Do not assume Unknown is protected.

## 11. Safe disconnect behavior

The ordinary SnarkyCtl CLI disconnect operation is safety checked. It refuses to disconnect
the upstream VPN unless the provider's leak protection and firewall state are verified safe
for the operation.

For a deliberate safe disconnected state, the dashboard's **Enable Locked mode** control is
clearer because it explicitly turns on leak protection before disconnecting the provider.

A manual command such as:

```bash
sudo nordvpn disconnect
```

bypasses SnarkyCtl's higher-level operation checks. Use direct NordVPN commands for setup,
provider testing, or deliberate administration—not as an unnoticed replacement for the
SnarkyCtl safety model.

## 12. Troubleshooting NordVPN-specific failures

Start with:

```bash
sudo nordvpn status
sudo nordvpn settings
ip link show nordlynx
snarkyctl status
```

If NordVPN itself cannot connect, solve the provider problem before treating it as a
SnarkyCtl destination problem.

If NordVPN connects but WireGuard management disappears during provider transitions, review
Section 5 and the management-path exceptions.

If management works but Internet access is blocked, check whether Snarkypuss is simply in the
intended Locked state before changing anything.

If Internet works through the Linode public IP when Protected VPN was expected, stop using
the connection for protected traffic and follow the wrong-public-IP procedure in
[05_TROUBLESHOOTING.md](05_TROUBLESHOOTING.md).

If the installed NordVPN client's command names or output differ from examples in this guide,
consult:

```bash
nordvpn help
man nordvpn
```

and the current NordVPN Linux documentation before changing Snarkypuss code or configuration
merely to match an older client example.

## 13. Provider-specific safety rules

For the reference NordVPN deployment:

- Keep the Kill Switch enabled for normal Snarkypuss operation.
- Do not use Direct VPS as automatic recovery.
- Keep LISH available while changing NordVPN firewall/allowlist policy.
- Make the narrowest exception required to preserve the WireGuard management path.
- Verify fail-closed forwarding after every material provider-policy change.
- Do not expose SSH or SnarkyCtl publicly to work around a provider firewall problem.
- Keep NordVPN access tokens out of Git and configuration files that do not require them.
- Verify the observed public exit address after provider changes.
- Treat Unknown protection state conservatively.

For general symptoms rather than NordVPN-specific administration, return to
[05_TROUBLESHOOTING.md](05_TROUBLESHOOTING.md).

## Official NordVPN references

NordVPN changes its Linux client independently of Snarkypuss. When command syntax differs
from the installed examples, consult the current provider documentation:

- Linux installation and CLI reference:
  https://support.nordvpn.com/hc/en-us/articles/20196094470929-How-to-install-the-NordVPN-app-on-Linux-distributions
- Headless token login:
  https://support.nordvpn.com/hc/en-us/articles/20286980309265-How-to-log-in-to-NordVPN-without-a-GUI-using-a-token
- Linux Kill Switch behavior:
  https://support.nordvpn.com/hc/en-us/articles/19509682644369-NordVPN-Kill-Switch-how-does-it-work
- Linux allowlist/split-tunneling behavior:
  https://support.nordvpn.com/hc/en-us/articles/19618692366865-What-is-Split-Tunneling-and-how-to-use-it-with-NordVPN
