# Snarkypuss User Manual

## Purpose

This is the day-to-day operating guide for an installed Snarkypuss system.

For normal use, you should not need the LISH console. Most operations
are performed from the SnarkyCtl dashboard on your Windows PC.

The reference deployment uses the private name `snarkypuss` for the Linode and the private
WireGuard address `10.8.0.1`.

## 1. Start Snarkypuss for normal use

On the Windows PC:

1. Open **WireGuard**.
2. Select the `snarkypuss` tunnel.
3. Select **Activate** if the tunnel is not already active.
4. Open a web browser.
5. Go to:

   ```text
   https://snarkypuss:8443/
   ```

6. Enter the SnarkyCtl username and password when the browser asks for them.

The dashboard is reachable only through the private WireGuard connection. If WireGuard is
inactive, `https://snarkypuss:8443/` is expected to be unreachable.

If the browser reports an unexpected certificate warning, do not make a habit of bypassing
it. The setup guide installs a private certificate authority specifically so that the
SnarkyCtl certificate can be verified normally.

## 2. Check the gateway mode first

The most important item on the dashboard is **Gateway mode** at the top of the page.

Snarkypuss uses four effective modes:

| Mode | What it means | Normal interpretation |
|---|---|---|
| **VPN** / **Protected VPN** | The upstream VPN is connected and client traffic is using it. | Normal Internet use. |
| **LOCKED** / **Locked** | Leak protection is active, the upstream VPN is disconnected, and public Internet forwarding is blocked. | Safe disconnected state. |
| **DIRECT** / **Direct VPS** | Leak protection is disabled and client Internet traffic can leave through the Linode's public connection. | Intentional exposure only. |
| **UNKNOWN** | SnarkyCtl cannot verify the effective path. | Treat as unverified until investigated. |

**Locked is the safe fallback.** A NordVPN failure or disconnect must not silently become
Direct VPS mode.

Direct VPS mode does not reveal the Windows PC's home public IP to Internet sites; it exposes
the **Linode's public IP** instead of the NordVPN exit IP. It is still an exceptional mode
because it bypasses the upstream VPN protection that Snarkypuss normally provides.

If the dashboard says **UNKNOWN**, **UNAVAILABLE**, or reports that status is incomplete, do
not assume that traffic is protected merely because some parts of the dashboard look normal.

## 3. Read the dashboard

The dashboard is divided into a few operational areas.

### Gateway mode

This is the overall safety state described above. Read this before changing destinations or
using the Internet through Snarkypuss.

### Current connection

The **Upstream VPN** panel shows:

- **Provider** — the configured upstream VPN provider.
- **Target** — the destination alias currently selected, when known.
- **Server** — the provider server or display name reported by the provider.
- **Interface** — the active provider network interface.
- **Public exit IPv4** — the public address observed from the Linode.
- **Leak protection** — whether provider leak protection is active.
- **Last refreshed** — when the displayed status was last collected.

When you are in Protected VPN mode, the public exit address should be a NordVPN exit address,
not the Linode's ordinary public address.

The dashboard refreshes status automatically every **5 seconds**. After changing a target or
mode, allow a few seconds for all status fields to settle.

### DNS

The **DNS** card shows the local DNS service and its current service state. Under normal
operation it should report the configured DNS service as active.

### System

The **System** card shows basic Linode health information such as:

- uptime,
- system load,
- available memory, and
- free space on the root filesystem.

These values are primarily useful as an early warning that the small Linode is running short
of resources.

### Incomplete status

If SnarkyCtl could collect only part of the status, an **Incomplete status** section appears
with the component that failed. A partial failure does not necessarily mean that all traffic
is broken, but safety should not be inferred from missing information.

## 4. Connect to or switch a VPN destination

The **VPN target** section contains the approved destinations that were configured during
setup.

For routine use while the system is already protected or locked:

1. Choose a destination from **Connection target**.
2. Select **Connect / switch**.
3. Wait for the operation to finish.
4. Confirm that **Gateway mode** becomes VPN/Protected VPN.
5. Confirm that **Leak protection** is active.
6. Check the **Public exit IPv4**.

If the selected destination is already active, the button may read **Reconnect**.

A destination shown in the menu is an alias from SnarkyCtl's approved catalogue. The browser
does not send arbitrary NordVPN command-line arguments to the privileged service.

For providers that support a parameterless recommended target, SnarkyCtl may also expose a
built-in destination. With NordVPN this is **Fastest available server**. It is always available
in the connection selector, is not stored in SQLite, and therefore does not appear as an
editable destination in **Manage VPN destinations**.

### Important after Direct VPS mode

If the gateway is currently in **Direct VPS** mode, do not rely on an ordinary
**Connect / switch** operation to restore the complete protection policy. Open **Advanced
gateway modes** and use **Enable Protected VPN** instead. That operation explicitly enables
leak protection before connecting the selected target.

## 5. Manage VPN destinations

Most users will configure destinations during setup and change them only occasionally.
Destination editing is available directly in the dashboard under:

**Manage VPN destinations — Advanced**

Open that section to load the editable destination catalogue.

You can:

- add a destination,
- edit an existing destination,
- remove a destination,
- move destinations up or down, and
- save the complete catalogue.

Each destination has:

- an **Alias** — the short internal name used by SnarkyCtl and the CLI,
- a **Label** — the friendly name shown in the dashboard,
- a **Target type**, and
- provider-specific fields appropriate to that target type.

Aliases must begin with a lowercase letter and may contain lowercase letters, digits,
underscores, and hyphens. Keep aliases short and stable; examples are `dallas`, `new_york`,
or `uk-fast`.

For a new destination, the dashboard automatically proposes both the label and a unique alias
from the selected provider values. You can edit either one manually; after manual editing,
the dashboard leaves your value alone.

For the current NordVPN adapter:

- **Fastest in country**, **Fastest in city**, and **Server group** use live choices discovered
  from the installed NordVPN client.
- City selection is cascading: choose the country first, then choose a city from that country.
- **Specific server** is an advanced free-text selector. Enter the server identifier expected
  by NordVPN, for example `us9176`. SnarkyCtl does not try to determine whether that server
  currently exists; an invalid value is reported when NordVPN is asked to connect.
- **Legacy configured target** may appear on older migrated entries. Existing legacy entries
  remain connectable, editable, and removable, but the dashboard does not offer Legacy as a
  type for newly added destinations.

Provider discovery can change over time. If an existing saved provider-backed choice no
longer appears in the provider's current discovery results, the destination manager never
silently substitutes a different provider value. It normally removes unavailable saved
entries automatically; if automatic cleanup cannot complete, it reports the problem for
manual removal or replacement.

After editing, select **Save catalogue**. SnarkyCtl saves the catalogue as one validated
change. If another session changed the catalogue while you were editing it, SnarkyCtl may
refuse the save and tell you to reload before trying again.

Use **Reload** to discard the current browser copy and load the latest saved catalogue.

## 6. Advanced gateway modes

The dashboard's **Advanced gateway modes** section is marked **Danger zone** because it can
change leak-protection policy as well as the VPN connection.

### Protected VPN

Use **Enable Protected VPN** when you want the normal protected state and especially when
returning from Direct VPS mode.

1. Select the desired VPN target in the normal target selector.
2. Open **Advanced gateway modes**.
3. Select **Enable Protected VPN**.

SnarkyCtl enables leak protection first and then connects the selected approved destination.
The operation is considered successful only if the resulting gateway mode is Protected VPN.

### Locked

Use **Enable Locked mode** when you want the Windows PC to keep its private connection to the
Linode but do **not** want client traffic forwarded to the public Internet.

SnarkyCtl enables leak protection and disconnects the upstream VPN. The private WireGuard
management path remains available, so the dashboard and private SSH can continue to work.

Locked mode is useful when:

- you deliberately want to stop Internet forwarding,
- you are changing or checking the upstream VPN,
- you want a safe state before maintenance, or
- the upstream provider is unavailable.

### Direct VPS

**Direct VPS deliberately bypasses the upstream VPN.**

To enable it, the dashboard requires you to type:

```text
EXPOSE VPS IP
```

before the **Enable Direct VPS** button becomes available.

When enabled, SnarkyCtl disables provider leak protection and disconnects the upstream VPN.
Client traffic may then leave through the Linode's public address.

Use Direct VPS only when you specifically want that behavior. Do not use it as a routine way
to fix a provider connection problem.

To leave Direct VPS mode, use **Enable Protected VPN** or **Enable Locked mode** so that leak
protection is explicitly restored.

## 7. Disconnect safely without losing management access

There are two different kinds of "disconnect" in a Snarkypuss deployment.

### Disconnect the upstream VPN

The safe Snarkypuss state for an upstream VPN disconnect is **Locked**. Internet forwarding
is blocked, but the Windows-to-Linode WireGuard management tunnel remains available.

Use **Enable Locked mode** in the dashboard when that is what you want.

### Disconnect Windows from the Linode

To disconnect the Windows PC from Snarkypuss entirely, deactivate the `snarkypuss` tunnel in
the WireGuard application.

When the WireGuard tunnel is inactive:

- the private address `10.8.0.1` is no longer reachable from that PC,
- `https://snarkypuss:8443/` is no longer reachable, and
- private SSH to `snarkypuss` is no longer reachable.

Reactivating the WireGuard tunnel restores the private management path, assuming the Linode
services are running normally.

## 8. Use the command line when useful

The dashboard is the normal user interface. The SnarkyCtl command-line client runs on the
Linode, so from Windows you normally reach it through private SSH first:

```bash
ssh root@snarkypuss
```

Then common commands are:

```bash
snarkyctl status
snarkyctl targets list
snarkyctl connect dallas
snarkyctl disconnect
```

Replace `dallas` with one of the aliases shown by `snarkyctl targets list`.

`snarkyctl status` displays the upstream VPN state, gateway mode, public exit address, DNS
state, system health, and any partial status failures.

`snarkyctl connect ALIAS` connects an approved destination. For routine CLI use, verify first
that leak protection is already active. If you are recovering from Direct VPS mode, use the
dashboard's **Enable Protected VPN** control so leak protection is explicitly restored before
the connection.

`snarkyctl disconnect` is intentionally safety checked. It refuses to disconnect the upstream
VPN unless provider leak protection and the provider firewall are verified enabled. A
successful safe disconnect should therefore leave public Internet forwarding protected rather
than creating an unprotected direct path.

Add `--json` to `status`, `connect`, or `disconnect` when a machine-readable response is
useful, for example:

```bash
snarkyctl status --json
```

## 9. After a reboot

Do not assume the gateway's state after a reboot merely because WireGuard reconnects.

After the Linode or Windows PC has restarted:

1. Activate the Windows `snarkypuss` WireGuard tunnel if necessary.
2. Open `https://snarkypuss:8443/`.
3. Check **Gateway mode**.
4. Check **Leak protection**.
5. Check the upstream VPN state and target.
6. Check **Public exit IPv4** if Internet forwarding is enabled.
7. Confirm that DNS reports an active state.

If the system comes up Locked, that is a safe condition: private management remains
available while public forwarding is blocked. Select a destination and enter Protected VPN
mode when you are ready to resume Internet use.

If the mode is Unknown or the dashboard cannot collect enough status to establish safety,
verify the system before using it for traffic that depends on VPN protection.

## 10. Normal safety rules

For ordinary operation, keep these rules in mind:

- Use **Protected VPN** for normal Internet access.
- Use **Locked** when you want a safe disconnected state.
- Use **Direct VPS** only deliberately and temporarily.
- Never assume an **Unknown** or unavailable state is protected.
- Do not disable NordVPN leak protection or its Kill Switch as a routine troubleshooting
  step.
- Do not expose TCP port `8443` on the Linode Firewall.
- Keep the SnarkyCtl dashboard bound to the private WireGuard address.
- Keep LISH available as the independent recovery path for administrative problems.

## 11. Quick checks when something looks wrong

Before doing deeper troubleshooting, check the simple things first:

1. Is the Windows `snarkypuss` WireGuard tunnel active?
2. Does `https://snarkypuss:8443/` load?
3. What does **Gateway mode** say?
4. Is **Leak protection** Active?
5. Is the upstream VPN connected or deliberately Locked?
6. Does **Public exit IPv4** match the state you expect?
7. Is the DNS service active?
8. Does the dashboard show **Incomplete status**?
9. Wait at least one 5-second refresh cycle after a recent operation.
10. If necessary, use private SSH and run:

    ```bash
    snarkyctl status
    ```

The next document in this series, [05_TROUBLESHOOTING.md](05_TROUBLESHOOTING.md), is the
detailed troubleshooting guide for problems that are not resolved by these basic checks.
