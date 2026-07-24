# NordVPN Adapter

The built-in NordVPN adapter is a deliberately narrow integration with the official Linux CLI. It delegates tunnel creation, routing, DNS, firewall behaviour, and connection configuration to NordVPN.

SnarkyCtl invokes only these forms:

```text
/usr/bin/nordvpn status
/usr/bin/nordvpn settings
/usr/bin/nordvpn connect <one-root-configured-target>
/usr/bin/nordvpn disconnect
```

Commands use argument arrays with `shell=False`, a fixed absolute executable, a controlled locale, a 45-second timeout, and a 64 KiB output limit. A configured target cannot begin with an option marker or contain shell/control syntax. No browser-supplied value is passed directly to the command.

After `connect` or `disconnect`, the adapter runs `nordvpn status` and returns the observed state rather than inferring success from the mutation command's message. The daemon reads `nordvpn settings` before disconnection and refuses to disconnect unless both Kill Switch and the NordVPN firewall are verified enabled.

## Normalized Status

The parser recognizes `Connected`, `Connecting`, `Disconnected`, and `Disconnecting`. It maps them onto the provider-neutral `VpnState` model and retains a bounded set of useful fields:

- Server and hostname
- Provider IP
- Country and city
- Current technology and protocol
- Post-quantum setting
- Transfer counters
- Uptime

The settings parser separately normalizes Kill Switch, firewall, routing, firewall mark, and technology. It reads these values but never changes them.

When the reported technology is NordLynx, the normalized interface is `nordlynx`. Other technologies do not currently infer an interface name.

## Responsibility Boundary

The adapter does not:

- Change routing or policy-routing tables.
- Add, remove, or render firewall rules.
- Configure WireGuard management bypass marks.
- Enable or disable NordVPN's kill switch.
- Change NordVPN technology, protocol, DNS, allowlist, or auto-connect settings.
- Determine whether disconnected traffic is using the VPS public IP.

Those are deployment configuration or later status-observation concerns. The existing WireGuard management bypass remains an administrator-managed prerequisite.

## Kill Switch Blocking WireGuard Management

### Symptom

With the NordVPN Kill Switch enabled, an existing WireGuard SSH or dashboard connection
may stop working when NordVPN disconnects, reconnects, or changes servers. Temporarily
disabling the Kill Switch restores management access.

This is a NordVPN firewall-policy issue rather than a SnarkyCtl routing operation. The
WireGuard firewall mark preserves the management route, but it does not by itself require
NordVPN's Kill Switch rules to admit the WireGuard listener and private management subnet.

### Permanent NordVPN configuration

NordVPN's supported remedy is to exempt the WireGuard UDP listener and management subnet
from its tunnel and Kill Switch. Keep the Linode LISH console open while making this
change, so the Kill Switch can be disabled locally if the remote session is interrupted.

The following example uses the current deployment values:

```text
WireGuard UDP listener: 51822
WireGuard subnet:        10.8.0.0/24
```

Confirm the actual values before applying them:

```bash
sudo wg show wg0
sudo grep -E '^[[:space:]]*ListenPort' /etc/wireguard/wg0.conf
ip -brief address show wg0
```

Temporarily disable the Kill Switch:

```bash
sudo nordvpn set killswitch off
```

Recent NordVPN clients use `allowlist`:

```bash
sudo nordvpn allowlist add port 51822 protocol UDP
sudo nordvpn allowlist add subnet 10.8.0.0/24
```

Some installed Linux client versions use the older `whitelist` spelling:

```bash
sudo nordvpn whitelist add port 51822
sudo nordvpn whitelist add subnet 10.8.0.0/24
```

Use only the spelling accepted by the installed client. Inspect the resulting policy:

```bash
sudo nordvpn settings
```

Then restore protection and reconnect:

```bash
sudo nordvpn set killswitch on
sudo nordvpn connect
```

Do not allowlist TCP ports 22 or 8443. SSH and the dashboard must remain bound to and
reachable through WireGuard, not exempted on the VPS public interface. Enabling general
LAN discovery is also broader than the two explicit exceptions and is not the preferred
remedy.

NordVPN documents that allowlisted traffic bypasses the VPN tunnel and is not blocked by
the Kill Switch:

- [NordVPN Linux installation and CLI reference](https://support.nordvpn.com/hc/en-us/articles/20196094470929-How-to-install-the-NordVPN-app-on-Linux-distributions)
- [NordVPN Linux allowlist instructions](https://support.nordvpn.com/hc/en-us/articles/19618692366865-What-is-Split-Tunneling-and-how-to-use-it-with-NordVPN)

### Required safety test

Because this VPS forwards traffic from WireGuard clients, the subnet exception must be
tested to ensure that it preserves management access without permitting client Internet
traffic to bypass NordVPN.

Keep LISH open and maintain a second WireGuard management session. With NordVPN connected,
confirm that SSH and the dashboard remain reachable:

```powershell
Test-NetConnection 10.8.0.1 -Port 22
Test-NetConnection 10.8.0.1 -Port 8443
```

On the VPS, verify the WireGuard handshake:

```bash
sudo wg show wg0
```

Then disconnect NordVPN while leaving the Kill Switch enabled:

```bash
sudo nordvpn disconnect
```

The correct fail-closed result is:

- SSH over WireGuard remains reachable.
- The SnarkyCtl dashboard remains reachable.
- Ordinary Internet traffic forwarded from the WireGuard client is blocked.
- Forwarded traffic does not leave through the VPS real public address.

Reconnect after the test:

```bash
sudo nordvpn connect
```

If forwarded client Internet traffic still works while NordVPN is disconnected,
immediately use LISH to disable the Kill Switch and remove the subnet exception:

```bash
sudo nordvpn set killswitch off
sudo nordvpn allowlist remove subnet 10.8.0.0/24
```

For a client using the older syntax, replace `allowlist` with `whitelist`. Do not leave an
exception in place if the fail-closed test shows that it permits direct public forwarding.

## Controlled Failures

Missing or non-executable binaries, permission errors, timeouts, excessive output, nonzero exit status, unsafe configured targets, and unrecognized status output are returned as stable `ProviderError` codes. Raw stderr is not exposed to the browser.

The privileged control daemon dispatches `STATUS`, `CONNECT`, and guarded `DISCONNECT` to this adapter. It resolves aliases against the root-owned target allowlist before calling `connect`; an unknown alias never reaches NordVPN. It reports `VPN` when connected, `LOCKED` when disconnected with verified leak protection, `DIRECT` when disconnected with verified-disabled leak protection, and `UNKNOWN` otherwise. `DIRECT` remains unavailable as an intentional operation.
