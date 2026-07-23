# NordVPN Adapter

The built-in NordVPN adapter is a deliberately narrow integration with the official Linux CLI. It delegates tunnel creation, routing, DNS, firewall behaviour, and connection configuration to NordVPN.

SnarkyCtl invokes only these forms:

```text
/usr/bin/nordvpn status
/usr/bin/nordvpn connect <one-root-configured-target>
/usr/bin/nordvpn disconnect
```

Commands use argument arrays with `shell=False`, a fixed absolute executable, a controlled locale, a 45-second timeout, and a 64 KiB output limit. A configured target cannot begin with an option marker or contain shell/control syntax. No browser-supplied value is passed directly to the command.

After `connect` or `disconnect`, the adapter runs `nordvpn status` and returns the observed state rather than inferring success from the mutation command's message.

## Normalized Status

The parser recognizes `Connected`, `Connecting`, `Disconnected`, and `Disconnecting`. It maps them onto the provider-neutral `VpnState` model and retains a bounded set of useful fields:

- Server and hostname
- Provider IP
- Country and city
- Current technology and protocol
- Post-quantum setting
- Transfer counters
- Uptime

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

## Controlled Failures

Missing or non-executable binaries, permission errors, timeouts, excessive output, nonzero exit status, unsafe configured targets, and unrecognized status output are returned as stable `ProviderError` codes. Raw stderr is not exposed to the browser.

The privileged control daemon dispatches `STATUS`, `CONNECT`, and `DISCONNECT` to this adapter. It resolves aliases against the root-owned target allowlist before calling `connect`; an unknown alias never reaches NordVPN. `LOCK` and `DIRECT` remain unavailable until their policy semantics are implemented.
