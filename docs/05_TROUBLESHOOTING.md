# Snarkypuss Troubleshooting Guide

## Purpose

This guide is for an installed Snarkypuss system that was previously working or has reached
far enough through setup to diagnose a specific problem. It is organized by **symptom**, so
start with what you can observe rather than trying to guess which subsystem is at fault.

For installation instructions, use the setup guides instead:

1. [01_SETUP_VPS.md](01_SETUP_VPS.md) — Linode, WireGuard, NordVPN, forwarding, and firewall.
2. [02_SETUP_DNS.md](02_SETUP_DNS.md) — `dnsmasq` and Windows DNS through WireGuard.
3. [03_SETUP_SNARKYCTL.md](03_SETUP_SNARKYCTL.md) — SnarkyCtl services, HTTPS, and initial validation.
4. [04_USER_MANUAL.md](04_USER_MANUAL.md) — normal day-to-day operation.

The reference deployment uses:

- WireGuard interface `wg0`,
- private network `10.8.0.0/24`,
- Linode private WireGuard address `10.8.0.1`,
- Windows WireGuard address `10.8.0.2`,
- WireGuard UDP port `51820`,
- NordVPN with the `nordlynx` interface, and
- SnarkyCtl HTTPS at `https://snarkypuss:8443/`.

Adjust commands if your deployment deliberately uses different values.

## 1. Troubleshoot safely

Networking failures are easy to make worse by changing several safety controls at once.
Before changing anything:

- Keep the **LISH console** available in Akamai Cloud Manager.
- Do not expose SnarkyCtl port `8443` publicly as a recovery shortcut.
- Do not open public SSH merely because private SSH has stopped working unless you have
  deliberately chosen that recovery path and understand the exposure.
- Do not disable the NordVPN Kill Switch as a routine first step.
- Prefer **Locked** mode while investigating an uncertain provider state.
- Do not enter **Direct VPS** merely to make Internet access work again.
- Record the last change made before the failure appeared.
- When collecting diagnostics, prefer read-only commands before restarting or editing
  services.

If the dashboard reports **UNKNOWN**, **UNAVAILABLE**, or cannot verify leak protection, do
not assume traffic is protected.

## 2. Quick triage

Work through these checks in order. Stop when you find the first layer that is not working.

### On Windows

1. Is the `snarkypuss` WireGuard tunnel active?
2. Does WireGuard show a recent handshake?
3. Are the transfer counters increasing in both directions?
4. Can you reach the private Linode address?

   ```powershell
   ping 10.8.0.1
   ```

5. Does the private hostname resolve correctly?

   ```powershell
   Resolve-DnsName snarkypuss
   ```

   The hosts-file entry should resolve `snarkypuss` to `10.8.0.1`.

6. Does the SnarkyCtl dashboard load?

   ```text
   https://snarkypuss:8443/
   ```

7. Does DNS through the Linode work?

   ```powershell
   Resolve-DnsName example.com -Server 10.8.0.1
   ```

### On the Linode

Use private SSH if it works; otherwise use LISH.

```bash
sudo wg show wg0
ip route
ip rule
sudo nordvpn status
sudo nordvpn settings
systemctl --failed
snarkyctl status
```

Interpret the result by layers:

- **No WireGuard handshake:** start with Section 3.
- **Handshake but no useful traffic:** use Section 4.
- **Private management works but Internet does not:** use Section 5.
- **Internet works but the public IP is wrong:** use Section 6 immediately.
- **IP traffic works but names do not resolve:** use Section 7.
- **Dashboard cannot be reached:** use Section 8.
- **Dashboard loads but status is incomplete or Unknown:** use Section 9.

## 3. WireGuard will not connect

### Symptom

Windows shows no recent handshake for the `snarkypuss` tunnel.

### Check the Windows configuration

In the WireGuard application, verify that the tunnel has:

```ini
[Interface]
Address = 10.8.0.2/24
DNS = 10.8.0.1

[Peer]
Endpoint = LINODE_PUBLIC_IPV4:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
```

Also verify that:

- the Windows private key is still the one generated for this tunnel,
- the peer `PublicKey` is the Linode's WireGuard **public** key,
- the endpoint contains the Linode's current public IPv4 address, and
- the endpoint uses UDP port `51820` in the reference deployment.

### Check the Linode Firewall

In Akamai Cloud Manager, confirm that the Linode Firewall allows inbound `51820/UDP`.
Do not open SnarkyCtl `8443/TCP` publicly.

### Check WireGuard on the Linode

```bash
systemctl status wg-quick@wg0.service
sudo wg show wg0
sudo ss -lunp | grep ':51820'
ip address show wg0
```

Expected signs of a healthy server side are:

- `wg-quick@wg0.service` is active,
- `wg0` exists with address `10.8.0.1/24`,
- WireGuard is listening on the configured UDP port, and
- the configured peer public key matches the Windows tunnel public key.

If the service failed during the current boot, inspect:

```bash
journalctl -u wg-quick@wg0.service -b --no-pager
```

Do not regenerate keys casually. A key mismatch is fixed by identifying which public key is
wrong, not by repeatedly generating new pairs on both sides.

## 4. WireGuard handshakes, but traffic does not pass

### Symptom

WireGuard reports a recent handshake, but the Windows client cannot reach `10.8.0.1`, cannot
reach the Internet, or one transfer counter remains at zero.

A handshake proves only that the WireGuard peers can exchange tunnel packets. It does **not**
prove that forwarding, DNS, provider routing, or Windows routing is correct.

### Check the transfer counters

On the Linode:

```bash
sudo wg show wg0
```

Generate traffic from Windows, for example:

```powershell
ping 10.8.0.1
```

Run `wg show` again and see whether both received and sent byte counters increase.

### Check the private interface

```bash
ip address show wg0
ip route
```

The reference Linode should have `10.8.0.1/24` on `wg0`.

### Check forwarding and Snarkypuss firewall chains

```bash
sysctl net.ipv4.ip_forward
sudo iptables -L -n -v
sudo iptables -t nat -L -n -v
```

IPv4 forwarding should be enabled after a confirmed Snarkypuss activation. The Snarkypuss
forwarding and NAT rules should still exist and should accumulate counters when Windows sends
traffic through the tunnel.

### Check for another VPN on Windows

If another VPN client is active on the Windows PC, temporarily pause or disconnect it as a
diagnostic test. A local VPN can install routes or filtering rules that interfere with the
WireGuard tunnel even when WireGuard itself still handshakes successfully.

After changing the local VPN state, deactivate and reactivate the `snarkypuss` WireGuard
tunnel and check its transfer counters again.

Do not confuse this Windows-side test with the NordVPN client running on the Linode. NordVPN
belongs on the Linode in the reference Snarkypuss design.

## 5. Private management works, but Internet access does not

### Symptom

Windows can reach `10.8.0.1`, private SSH works, and perhaps the SnarkyCtl dashboard works,
but ordinary Internet traffic does not.

First determine whether this is actually a fault.

### Check gateway mode

Open the dashboard or run:

```bash
snarkyctl status
```

If the gateway is **Locked**, blocked public Internet access is the intended behavior. The
private management path remains available specifically so that you can recover safely.

If you want normal protected Internet access, select an approved destination and enter
**Protected VPN** mode.

### Check NordVPN

```bash
sudo nordvpn status
sudo nordvpn settings
ip link show nordlynx
```

For protected operation:

- NordVPN should be connected,
- the Kill Switch should be enabled,
- the provider firewall should be reported enabled, and
- the protected provider interface should exist.

If NordVPN is disconnected while leak protection is active, Snarkypuss should remain Locked
rather than silently forwarding through the Linode's public interface.

## 6. Internet works through the wrong public IP

### Symptom

The Windows client can reach the Internet, but the observed public IPv4 address is the
Linode's ordinary public IP when you expected a NordVPN exit address.

Treat this as a **safety failure**, not merely a cosmetic status problem.

1. Stop using the connection for traffic that depends on upstream VPN protection.
2. If SnarkyCtl is reachable, enter **Locked** mode.
3. Check:

   ```bash
   snarkyctl status
   sudo nordvpn status
   sudo nordvpn settings
   ip route
   ip rule
   ```

4. Confirm that NordVPN leak protection is enabled before attempting to reconnect.
5. Use **Enable Protected VPN** in the dashboard when returning from Direct VPS or an
   uncertain protection state.

Do not accept Direct VPS as an automatic fallback. Direct VPS is valid only when explicitly
chosen and clearly understood.

If the dashboard itself reports **Direct VPS**, the exposed address is intentional until you
leave that mode. Use **Enable Protected VPN** or **Enable Locked mode** to restore leak
protection.

## 7. DNS does not work

### Symptoms

Typical DNS symptoms include:

- websites work by IP address but not by name,
- Windows reports that DNS requests time out,
- the SnarkyCtl DNS card reports an inactive or failed service,
- `dnsmasq.service` is failed, or
- nothing is listening on `10.8.0.1:53`.

The canonical setup procedure is in [02_SETUP_DNS.md](02_SETUP_DNS.md). Start diagnostics with:

```bash
systemctl status dnsmasq.service --no-pager
journalctl -u dnsmasq.service -b --no-pager
sudo dnsmasq --test
sudo ss -luntp | grep ':53'
cat /etc/dnsmasq.d/snarkypuss.conf
systemctl cat dnsmasq.service
```

The reference generated file should bind `dnsmasq` to `wg0` and `10.8.0.1`. The systemd
drop-in requires `wg-quick@wg0.service`, so a WireGuard startup failure can also prevent DNS
from starting correctly.

Check the dependency and both services:

```bash
systemctl status wg-quick@wg0.service dnsmasq.service --no-pager
systemctl cat dnsmasq.service
```

If `dnsmasq --test` reports a configuration error, fix that error before repeatedly
restarting the service.

If the configuration tests successfully but the service still fails, the journal normally
contains the reason. Common categories include another process already using port 53, the
expected WireGuard interface/address not existing yet, or a systemd dependency failure.

From the Linode, test the listener directly:

```bash
dig @10.8.0.1 example.com
```

From Windows with WireGuard active:

```powershell
Resolve-DnsName example.com -Server 10.8.0.1
```

Do not change the Windows tunnel to use an unrelated public DNS server merely to hide a
broken Snarkypuss DNS configuration. Fix the private DNS path or deliberately redesign it.

## 8. The SnarkyCtl dashboard will not open

### Symptom

WireGuard appears to work, but `https://snarkypuss:8443/` does not load.

### Check name resolution on Windows

The Windows hosts file should contain:

```text
10.8.0.1 snarkypuss
```

Check it with:

```powershell
Resolve-DnsName snarkypuss
```

### Check private reachability

```powershell
ping 10.8.0.1
```

If the private address itself is unreachable, troubleshoot WireGuard before SnarkyCtl.

### Check the web service

On the Linode:

```bash
systemctl status snarkyctl-web.service --no-pager
sudo ss -ltnp | grep ':8443'
journalctl -u snarkyctl-web.service -b --no-pager
```

The reference listener must be:

```text
10.8.0.1:8443
```

It must **not** be `0.0.0.0:8443`, `[::]:8443`, or the Linode public address.

A browser certificate warning is different from a connectivity failure. If the page is
reachable but the browser does not trust its certificate, review the private CA and server
certificate setup in [03_SETUP_SNARKYCTL.md](03_SETUP_SNARKYCTL.md). Do not solve a trust
problem by exposing the dashboard publicly.

## 9. Dashboard loads, but status is UNKNOWN, UNAVAILABLE, or incomplete

### Symptom

The dashboard itself opens, but it cannot establish the gateway mode or shows an
**Incomplete status** warning.

Run the CLI status command over private SSH:

```bash
snarkyctl status
snarkyctl status --json
```

Then inspect the control path:

```bash
systemctl status snarkyctl-control.socket --no-pager
systemctl status snarkyctl-control.service --no-pager
sudo ss -xlpn | grep /run/snarkyctl/control.sock
```

The control service is socket activated, so `snarkyctl-control.service` may normally be
inactive until a request arrives. `snarkyctl-control.socket` is the unit that should remain
enabled and listening.

If a control request triggers a failure, inspect:

```bash
journalctl -u snarkyctl-control.service -b --no-pager
journalctl -u snarkyctl-web.service -b --no-pager
```

A partial failure can come from one component while the rest of the dashboard remains
available, for example provider status, provider settings, public-IP collection, DNS status,
or system-status collection. Treat missing safety information conservatively.

## 10. Cannot connect or switch VPN destinations

### Check the approved catalogue

```bash
snarkyctl targets list
snarkyctl status
```

Verify that the alias you are trying to use actually exists.

If the dashboard destination list is empty, open **Manage VPN destinations** and confirm that
the catalogue contains at least one saved destination.

If a destination edit was rejected, reload the catalogue before editing again. SnarkyCtl
uses catalogue revisions to avoid silently overwriting a change made in another session.

### Check NordVPN directly

```bash
sudo nordvpn status
sudo nordvpn settings
```

If the provider itself cannot connect, SnarkyCtl cannot make that provider connection
succeed merely by choosing a different alias.

If the dashboard reports that another operation is already in progress, allow the existing
control operation to finish before submitting another one.

## 11. Locked mode will not return to Protected VPN

1. Select a valid destination in the dashboard.
2. Open **Advanced gateway modes**.
3. Select **Enable Protected VPN**.
4. Wait for the operation to complete and for at least one dashboard refresh cycle.
5. Confirm that leak protection is active and the gateway mode is Protected VPN.

If it fails, check:

```bash
sudo nordvpn status
sudo nordvpn settings
snarkyctl status
journalctl -u snarkyctl-control.service -b --no-pager
```

Do not disable the Kill Switch simply because a connection attempt failed. First identify
whether the provider is refusing the connection, the destination is invalid, or SnarkyCtl
cannot verify the protection state.

## 12. Direct VPS was enabled accidentally

Direct VPS deliberately disables provider leak protection and allows client traffic to leave
through the Linode's public connection.

To recover safely, use one of these dashboard controls:

- **Enable Protected VPN** — restores leak protection and connects the selected VPN target.
- **Enable Locked mode** — restores leak protection and leaves public forwarding blocked.

Then verify:

```bash
snarkyctl status
sudo nordvpn settings
```

Do not assume protection has returned merely because NordVPN happens to show a connected
state. Confirm the effective SnarkyCtl gateway mode and leak-protection state.

## 13. Private SSH through WireGuard fails

From Windows:

```powershell
ping 10.8.0.1
```

If the private address is unreachable, troubleshoot WireGuard first.

If `10.8.0.1` is reachable but SSH fails, use LISH and inspect:

```bash
systemctl status ssh.service --no-pager
sudo ss -ltnp | grep ':22'
journalctl -u ssh.service -b --no-pager
```

Do not change the Linode Firewall first. Traffic to `10.8.0.1` arrives over the private
WireGuard path; the public Linode Firewall is not a substitute for fixing the private tunnel
or SSH service.

Use LISH as the independent recovery channel while private SSH is unavailable.

## 14. Services fail after reboot

A service working immediately after installation does not prove that its boot dependencies
are correct.

Start with:

```bash
systemctl --failed
systemctl is-active wg-quick@wg0.service dnsmasq.service ssh.service
systemctl is-active snarkyctl-control.socket snarkyctl-web.service
```

For each failed service, inspect only the current boot first:

```bash
journalctl -u UNIT_NAME -b --no-pager
```

Useful examples are:

```bash
journalctl -u wg-quick@wg0.service -b --no-pager
journalctl -u dnsmasq.service -b --no-pager
journalctl -u snarkyctl-control.socket -b --no-pager
journalctl -u snarkyctl-web.service -b --no-pager
```

Check enablement separately from current state:

```bash
systemctl is-enabled wg-quick@wg0.service dnsmasq.service
systemctl is-enabled ssh.service snarkyctl-control.socket snarkyctl-web.service
```

Do not repeatedly run `systemctl start` until a service happens to stay up. A manual start
can hide an ordering or boot-dependency problem that will return on the next reboot.

## 15. Recover through LISH

Use LISH when ordinary network administration paths are unavailable.

1. Sign in to **Akamai Cloud Manager**.
2. Select the Snarkypuss Linode.
3. Launch the **LISH Console**.
4. Log in as `root`.
5. Determine which layer failed before editing anything:

   ```bash
   systemctl --failed
   ip address
   ip route
   ip rule
   sudo wg show
   sudo nordvpn status
   ```

6. Restore one known-safe layer at a time.

LISH does not depend on the Linode's SSH, WireGuard, NordVPN, or SnarkyCtl configuration, so
it is the preferred recovery path when those systems are uncertain.

## 16. Diagnostic information to collect before asking for help

When a problem is not obvious, collect the relevant output **before** making several changes.
A useful general diagnostic set is:

```bash
sudo wg show
ip address
ip route
ip rule
sudo nordvpn status
sudo nordvpn settings
systemctl --failed
systemctl status wg-quick@wg0.service --no-pager
systemctl status dnsmasq.service --no-pager
systemctl status snarkyctl-control.socket --no-pager
systemctl status snarkyctl-web.service --no-pager
snarkyctl status
```

For a failed unit, also collect its current-boot journal:

```bash
journalctl -u UNIT_NAME -b --no-pager
```

For forwarding problems, add:

```bash
sudo iptables -L -n -v
sudo iptables -t nat -L -n -v
```

For DNS problems, add:

```bash
sudo dnsmasq --test
sudo ss -luntp | grep ':53'
cat /etc/dnsmasq.d/snarkypuss.conf
```

Do not publish private keys, NordVPN access tokens, passwords, TLS private keys, or other
credentials with diagnostic output. WireGuard **public** keys are not secret, but there is
usually no need to publish them unless a peer-key mismatch is being investigated.

## 17. After the immediate problem is fixed

Before considering the incident closed, verify the complete path again:

- WireGuard has a recent handshake and bidirectional transfer.
- `10.8.0.1` is reachable privately.
- DNS works through `10.8.0.1`.
- SnarkyCtl reports a known gateway mode.
- Leak protection has the intended state.
- Protected traffic exits through NordVPN when Protected VPN mode is selected.
- Locked mode blocks public forwarding while private management remains reachable.
- SnarkyCtl remains private on `10.8.0.1:8443`.

If the failure involved boot persistence, perform a controlled reboot and verify the system
again rather than assuming a manual restart permanently fixed it.
